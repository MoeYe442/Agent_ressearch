"""Recompute reports from fixed slots, verified raw artifacts and bound human reviews."""
import csv
import html
import io
import json
import math
import statistics
from repolens.benchmark.files import Artifacts,read_json
from repolens.benchmark.protocol import digest,matrix
from repolens.benchmark.review import inspect_record,adjudicate,template


def load_rows(files,plan):
    specs=matrix(plan);context=files.read('context.json') if files.path('context.json').exists() else None
    if context and (context.get('run_id')!=plan.run_id or context.get('plan_hash')!=digest(plan.model_dump(mode='json'))):raise ValueError('foreign_run_context')
    if sum(files.path('rows/'+spec['key']+'.json').stat().st_size for spec in specs if files.path('rows/'+spec['key']+'.json').exists())>256*1024*1024:raise ValueError('run_artifact_total_limit')
    rows=[]
    for spec in specs:
        name='rows/'+spec['key']+'.json'
        row={**spec,'record':None,'inspection':None,'error':None,'review':None}
        if files.path(name).exists():
            try:
                if context is None:raise ValueError('run_context_missing')
                if type(context['server'].get('synthetic')) is not bool:raise ValueError('unknown_run_environment')
                record=files.read(name);inspection=inspect_record(plan,spec,record,context)
                if record.get('task'):
                    preparation=files.read('preparations/'+inspection['case'].repository+'-snapshot.json')['snapshot']
                    snapshot=record.get('snapshot') or {}
                    if preparation['id']!=snapshot.get('id') or preparation['manifest_hash']!=snapshot.get('manifest_hash') or preparation['commit_sha']!=snapshot.get('commit'):raise ValueError('snapshot_preparation_mismatch')
                row.update(record=record,inspection=inspection)
            except (ValueError,KeyError,TypeError,OSError):row['error']='invalid_or_foreign_result_artifact'
        rows.append(row)
    return context,rows


def review_packet(directory):
    files=Artifacts(directory);plan=files.plan();context,rows=load_rows(files,plan)
    return {'schema_version':1,'run_id':plan.run_id,'plan_hash':digest(plan.model_dump(mode='json')),'rows':[template(plan,row,row['record'],row['inspection']) for row in rows if row['inspection'] and row['inspection']['claims'] and not row['record'].get('artifact_error')]}


def reviews_for(paths,plan):
    result={}
    allowed={spec['key'] for spec in matrix(plan)}
    for path in paths:
        packet=read_json(path)
        if not isinstance(packet,dict) or set(packet)!={'schema_version','run_id','plan_hash','rows'} or packet.get('schema_version')!=1 or packet.get('run_id')!=plan.run_id or packet.get('plan_hash')!=digest(plan.model_dump(mode='json')) or not isinstance(packet.get('rows'),list):raise ValueError('invalid_or_foreign_review_packet')
        for row in packet['rows']:
            key=row.get('row_key')
            if key not in allowed or key in result:raise ValueError('duplicate_or_unknown_review_row')
            result[key]=row
    return result


def summarize(plan,rows,synthetic):
    total=len(rows);observed=[row for row in rows if row['record']]
    missing=sum(row['record'] is None and not row['error'] for row in rows);invalid=sum(bool(row['error']) for row in rows)
    complete=bool(total) and missing==0 and invalid==0
    ready_quality=complete and plan.suite.annotation_status=='human_approved' and synthetic is False and all(row['review'] and row['review']['quality_pass'] is not None for row in observed)
    usage=[row['record'].get('task',{}).get('usage') if row['record'].get('task') else None for row in observed]
    known=[item for item in usage if item is not None]
    latency=[row['record']['elapsed_ms'] for row in observed if row['record'].get('elapsed_ms') is not None]
    counts={status:sum(row['record']['execution_status']==status for row in observed) for status in ['succeeded','partial','failed','cancelled','timeout','error']}
    successes=counts['succeeded'];reports=sum(bool(row['record'].get('report')) for row in observed)
    citation_total=sum((row['review'] or {}).get('citation_reviewed',0) for row in observed)
    return {'planned':total,'observed_valid':len(observed),'not_run_or_pending':missing,'invalid_records':invalid,'run_complete':complete,'execution_status_counts':counts,'execution_completion_rate':successes/total if complete else None,'report_production_rate':reports/total if complete else None,'structure_passes':sum(row['inspection']['structure_pass'] for row in observed),'quality_completion_rate':sum(row['review']['quality_pass'] is True for row in observed)/total if ready_quality else None,'pending_manual_review':sum(row['review'] is None or row['review']['quality_pass'] is None for row in observed),'annotation_status':plan.suite.annotation_status,'synthetic':synthetic,'citation_accuracy':sum((row['review'] or {}).get('citation_passes',0) for row in observed)/citation_total if citation_total and synthetic is False and plan.suite.annotation_status=='human_approved' else None,'citation_sample_size':citation_total,'citation_population_size':sum(len(row['inspection']['citations']) for row in observed),'latency_sample_size':len(latency),'latency_population':'observed terminal slots, including failures; excludes shared preparation; includes runner downtime','median_latency_ms':statistics.median(latency) if latency else None,'p95_latency_ms':sorted(latency)[math.ceil(.95*len(latency))-1] if latency else None,'known_usage_slots':len(known),'unknown_or_unrun_usage_slots':total-len(known),'known_usage_subtotal':{key:sum(item[key] for item in known) for key in ['model_calls','tool_calls','input_tokens','output_tokens']} if known else None,'complete_usage_totals':{key:sum(item[key] for item in known) for key in ['model_calls','tool_calls','input_tokens','output_tokens']} if complete and len(known)==total else None,'estimated':any(item.get('estimated') for item in known) if known else None,'monetary_cost':None,'cost_note':'No verified provider price configuration; unknown usage is never zero.'}


def build_report(directory,review_paths=()):
    files=Artifacts(directory);plan=files.plan();context,rows=load_rows(files,plan)
    reviews=reviews_for(review_paths,plan)
    for row in rows:
        if row['key'] in reviews:
            if not row['inspection']:raise ValueError('review_has_no_valid_result')
            row['review']=adjudicate(plan,row,row['record'],row['inspection'],reviews[row['key']])
        elif row['record'] and not row['inspection']['claims'] and not row['record'].get('artifact_error'):
            row['review']={'quality_pass':False,'complete':True,'reviewer':None,'citation_passes':0,'citation_reviewed':0}
    synthetic=context['server']['synthetic'] if context else None
    summaries={config:summarize(plan,[row for row in rows if row['configuration']==config],synthetic) for config in plan.configurations}
    primary=[summaries.get(name) for name in ['single_keyword','collaborative_keyword']]
    difference=(primary[1]['quality_completion_rate']-primary[0]['quality_completion_rate'])*100 if all(item and item['quality_completion_rate'] is not None for item in primary) else None
    preparations=[]
    for repo in plan.suite.repositories:
        path='preparations/'+repo.id+'-index.json'
        if files.path(path).exists():
            value=files.read(path)['index'];preparations.append({'repository':repo.id,'index_id':value.get('id'),'status':value.get('status'),'usage':value.get('usage')})
    public_rows=[{'key':row['key'],'case_id':row['case_id'],'configuration':row['configuration'],'repeat':row['repeat'],'status':row['record']['execution_status'] if row['record'] else 'invalid' if row['error'] else 'not_run','artifact_error':row['error'] or (row['record'] or {}).get('artifact_error'),'error_code':(row['record'] or {}).get('error_code'),'structure_pass':row['inspection']['structure_pass'] if row['inspection'] else None,'quality_pass':(row['review'] or {}).get('quality_pass') if plan.suite.annotation_status=='human_approved' and synthetic is False else None,'manual_quality_judgment':(row['review'] or {}).get('quality_pass'),'synthetic':synthetic,'annotation_status':plan.suite.annotation_status,'result_hash':digest(row['record']) if row['record'] else None} for row in rows]
    return {'schema_version':1,'run_id':plan.run_id,'plan_hash':digest(plan.model_dump(mode='json')),'suite_id':plan.suite.id,'suite_hash':plan.suite_hash,'repeat_count':plan.repeats,'case_count':len(plan.case_ids),'selected_case_ids':plan.case_ids,'annotation_status':plan.suite.annotation_status,'synthetic':synthetic,'server':context['server'] if context else None,'summaries':summaries,'primary_quality_difference_percentage_points':difference,'comparison_note':'Descriptive paired configurations on identical planned case/repeat slots. Three repeats are not independent repositories; no statistical-significance claim. Draft rubrics or synthetic runs never publish quality rates.','shared_index_builds':preparations,'results':public_rows}


def csv_text(report):
    buffer=io.StringIO(newline='');columns=['key','case_id','configuration','repeat','status','artifact_error','error_code','structure_pass','quality_pass','manual_quality_judgment','synthetic','annotation_status','result_hash']
    writer=csv.DictWriter(buffer,fieldnames=columns);writer.writeheader()
    for row in report['results']:
        clean={key:('' if value is None else value) for key,value in row.items()}
        for key,value in clean.items():
            if isinstance(value,str) and value.lstrip().startswith(('=','+','-','@')):clean[key]="'"+value
        writer.writerow(clean)
    return buffer.getvalue()


def markdown(report):
    lines=['# RepoLens evaluation report','',f"Run `{report['run_id']}` · rubric `{report['annotation_status']}` · synthetic `{report['synthetic']}`",'',report['comparison_note'],'','| Configuration | Planned | Valid observed | Not run | Invalid | Execution rate | Quality rate |','|---|---:|---:|---:|---:|---:|---:|']
    for config,item in report['summaries'].items():
        rate=lambda value:'pending' if value is None else f'{value:.2%}'
        lines.append(f"| {config} | {item['planned']} | {item['observed_valid']} | {item['not_run_or_pending']} | {item['invalid_records']} | {rate(item['execution_completion_rate'])} | {rate(item['quality_completion_rate'])} |")
    lines+=['','Unknown use and unrun slots are not zero cost. Prices unavailable: monetary cost is null. Shared index build usage is listed separately in report.json; never sum it once per query.','',f"Primary quality difference (percentage points): {report['primary_quality_difference_percentage_points']}"]
    return '\n'.join(lines)+'\n'


def html_text(report):
    body=html.escape(markdown(report))
    return '<!doctype html><html lang="en"><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'"><meta name="viewport" content="width=device-width"><title>RepoLens evaluation</title><style>body{max-width:1100px;margin:40px auto;padding:0 20px;background:#f5f6f3;color:#202d2a;font:16px/1.6 system-ui}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:white;padding:24px;border:1px solid #d8dfd6;border-radius:12px}</style><h1>RepoLens · auditable evaluation</h1><pre>'+body+'</pre></html>'
