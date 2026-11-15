"""Human semantic judgments bind to immutable row hashes, facts and claim/citation pairs."""
import hashlib
import math
from repolens.benchmark.protocol import digest,CONFIGS


def usage_valid(usage):
    if usage is None:return True
    if not isinstance(usage,dict) or not isinstance(usage.get('estimated'),bool):return False
    return all(type(usage.get(key)) is int and usage[key]>=0 for key in ['model_calls','tool_calls','input_tokens','output_tokens'])


def inspect_record(plan,spec,record,context):
    if not isinstance(record,dict) or record.get('run_id')!=plan.run_id or record.get('plan_hash')!=digest(plan.model_dump(mode='json')) or any(record.get(key)!=spec[key] for key in spec):raise ValueError('result_identity_mismatch')
    if record.get('execution_status') not in {'succeeded','partial','failed','cancelled','timeout','error'}:raise ValueError('invalid_result_status')
    if record.get('configuration_valid') is not True:raise ValueError('invalid_execution_configuration')
    elapsed=record.get('elapsed_ms')
    if elapsed is not None and (type(elapsed) not in {int,float} or not math.isfinite(elapsed) or elapsed<0):raise ValueError('invalid_result_latency')
    task=record.get('task')
    if record['execution_status']!='error' and not task:raise ValueError('observed_task_required')
    if not task and (record.get('report') or record.get('evidence')):raise ValueError('report_without_observed_task')
    if task:
        if not usage_valid(task.get('usage')):raise ValueError('invalid_result_usage')
        if task.get('model_identifier')!=context['server']['model_identifier'] or task.get('budget_limits')!=context['server']['budget_limits']:raise ValueError('result_configuration_mismatch')
    evidence=record.get('evidence',[])
    if not isinstance(evidence,list):raise ValueError('invalid_evidence_records')
    by_id={item.get('id'):item for item in evidence if isinstance(item,dict)}
    if len(by_id)!=len(evidence):raise ValueError('duplicate_or_invalid_evidence')
    case=next(case for case in plan.suite.cases if case.id==spec['case_id'])
    repo=next(repo for repo in plan.suite.repositories if repo.id==case.repository)
    if task:
        snapshot=record.get('snapshot') or {}
        mode,retrieval,rerank=CONFIGS[spec['configuration']]
        if snapshot.get('commit')!=repo.commit or task.get('snapshot_id')!=snapshot.get('id') or task.get('question')!=case.question or task.get('mode')!=mode or task.get('retrieval_mode')!=retrieval or task.get('rerank') is not rerank or task.get('document_ids',[]):raise ValueError('result_task_scope_mismatch')
        if record['execution_status']!='timeout' and task.get('status')!=record['execution_status']:raise ValueError('result_terminal_status_mismatch')
    for item in evidence:
        start,end=item.get('start_line'),item.get('end_line')
        if type(start) is not int or type(end) is not int or start<1 or end<start or not isinstance(item.get('excerpt'),str):raise ValueError('invalid_evidence_range')
        checksum=hashlib.sha256(item['excerpt'].encode()).hexdigest()
        snapshot=record.get('snapshot') or {}
        if item.get('snapshot_id')!=snapshot.get('id') or item.get('commit_sha')!=repo.commit or item.get('content_hash')!=checksum:raise ValueError('evidence_snapshot_or_hash_mismatch')
        expected=hashlib.sha256(f"{item['snapshot_id']}:{item.get('path')}:{start}:{end}:{checksum}".encode()).hexdigest()
        if item.get('id')!=expected:raise ValueError('evidence_identifier_mismatch')
    claims=[];citations=[]
    report=record.get('report')
    if report:
        if not isinstance(report,dict) or not isinstance(report.get('claims'),list):raise ValueError('invalid_report')
        if report.get('status')!=task.get('status') or report.get('mode')!=task.get('mode') or not usage_valid(report.get('usage')):raise ValueError('report_task_state_mismatch')
        for index,claim in enumerate(report['claims']):
            if not isinstance(claim,dict) or not isinstance(claim.get('text'),str) or not isinstance(claim.get('evidence_ids'),list):raise ValueError('invalid_claim')
            refs=claim['evidence_ids']
            if not refs or len(set(refs))!=len(refs) or any(ref not in by_id for ref in refs):raise ValueError('claim_reference_invalid')
            key=digest([index,claim['text'],refs])[:24]
            claims.append({'claim_key':key,'text':claim['text'],'evidence_ids':refs})
            citations.extend({'citation_key':key+':'+ref,'claim_key':key,'evidence_id':ref} for ref in refs)
        if set(by_id)!={ref for claim in claims for ref in claim['evidence_ids']}:raise ValueError('uncited_evidence_record')
    elif record['execution_status'] in {'succeeded','partial'} and not record.get('artifact_error'):raise ValueError('completed_report_missing')
    matches={fact.id:[item['id'] for item in evidence if any(item.get('path')==anchor.path and item['start_line']<=anchor.end_line and item['end_line']>=anchor.start_line for anchor in fact.evidence)] for fact in case.facts}
    return {'case':case,'evidence':by_id,'claims':claims,'citations':citations,'fact_candidates':matches,'structure_pass':bool(claims) and all(matches.values()) and not record.get('artifact_error')}


def template(plan,spec,record,inspection):
    case=inspection['case'];repo=next(repo for repo in plan.suite.repositories if repo.id==case.repository)
    return {'run_id':plan.run_id,'row_key':spec['key'],'result_hash':digest(record),'case_id':case.id,'question':case.question,'repository_url':repo.url,'commit':repo.commit,'evidence':list(inspection['evidence'].values()),'expected_evidence':{fact.id:[anchor.model_dump(mode='json') for anchor in fact.evidence] for fact in case.facts},'reviewer':'','independent_attested':False,'overall_note':'','facts':[{'fact_id':fact.id,'text':fact.text,'passed':None,'evidence_ids':[],'reason':''} for fact in case.facts],'claims':[{'claim_key':item['claim_key'],'text':item['text'],'supported':None,'reason':''} for item in inspection['claims']],'citations':[dict(item,supported=None,reason='') for item in inspection['citations']]}


def adjudicate(plan,spec,record,inspection,review):
    if review.get('run_id')!=plan.run_id or review.get('row_key')!=spec['key'] or review.get('result_hash')!=digest(record):raise ValueError('stale_or_foreign_review')
    canonical=template(plan,spec,record,inspection)
    if set(review)!=set(canonical):raise ValueError('invalid_review_fields')
    if any(review[key]!=canonical[key] for key in ['case_id','question','repository_url','commit']):raise ValueError('review_question_scope_changed')
    if review.get('evidence')!=canonical['evidence'] or review.get('expected_evidence')!=canonical['expected_evidence']:raise ValueError('review_source_material_changed')
    expected={'facts':{fact.id for fact in inspection['case'].facts},'claims':{item['claim_key'] for item in inspection['claims']},'citations':{item['citation_key'] for item in inspection['citations']}}
    identifiers={'facts':'fact_id','claims':'claim_key','citations':'citation_key'}
    judgments=[];coverage={'facts':0,'claims':0,'citations':0};citation_passes=0
    for group in expected:
        rows=review.get(group)
        if not isinstance(rows,list) or len(rows)!=len(expected[group]) or {row.get(identifiers[group]) for row in rows if isinstance(row,dict)}!=expected[group]:raise ValueError('review_items_missing_or_duplicate')
        for row in rows:
            reference=next(item for item in canonical[group] if item[identifiers[group]]==row[identifiers[group]])
            mutable={'passed','evidence_ids','reason'} if group=='facts' else {'supported','reason'}
            if set(row)!=set(reference) or any(row[key]!=value for key,value in reference.items() if key not in mutable):raise ValueError('review_immutable_text_changed')
            verdict=row.get('passed' if group=='facts' else 'supported')
            if verdict is not None and type(verdict) is not bool:raise ValueError('boolean_review_verdict_required')
            if verdict is not None:
                if not isinstance(row.get('reason'),str) or not row['reason'].strip():raise ValueError('review_reason_required')
                coverage[group]+=1
            if group=='facts' and verdict is True:
                refs=row.get('evidence_ids',[])
                if not isinstance(refs,list) or not refs or any(ref not in inspection['fact_candidates'][row['fact_id']] for ref in refs):raise ValueError('fact_support_requires_annotated_observed_evidence')
            if group=='citations' and verdict is True:citation_passes+=1
            judgments.append(verdict)
    if review.get('reviewer')=='' and review.get('independent_attested') is False and all(value is None for value in judgments):
        return {'quality_pass':None,'complete':False,'reviewer':None,'coverage':coverage,'citation_passes':0,'citation_reviewed':0}
    if not isinstance(review.get('reviewer'),str) or not review['reviewer'].strip() or review.get('independent_attested') is not True:raise ValueError('independent_reviewer_attestation_required')
    complete=all(value is not None for value in judgments)
    quality=(all(judgments) and bool(inspection['claims']) and not record.get('artifact_error')) if complete else None
    return {'quality_pass':quality,'complete':complete,'reviewer':review['reviewer'],'coverage':coverage,'citation_passes':citation_passes,'citation_reviewed':coverage['citations']}
