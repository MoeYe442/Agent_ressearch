"""Same-snapshot retrieval comparison. Offline protocol checks are not model quality."""
import argparse
import hashlib
import json
import time
from pathlib import Path
from datetime import datetime,timezone
import httpx
from eval.run import wait_for

CONFIGURATIONS=[('keyword','keyword',False),('hybrid','hybrid',False),('hybrid_rerank','hybrid',True)]


def score_retrieval(case,hits,snapshot_id,k):
    valid=[];invalid=0
    for hit in hits[:k]:
        e=hit.get('evidence',{})
        if e.get('snapshot_id')!=snapshot_id or hashlib.sha256(e.get('excerpt','').encode()).hexdigest()!=e.get('content_hash'):
            invalid+=1
        else:valid.append(e)
    expected=case.get('expected_evidence',[])
    found=sum(any(e.get('path')==item['path'] and e.get('start_line',0)<=item['end_line'] and e.get('end_line',0)>=item['start_line'] for e in valid) for item in expected)
    return {'recall_at_k':found/len(expected) if expected else None,'k':k,'expected_evidence':len(expected),'found_evidence':found,'invalid_evidence':invalid,'quality_pass':None}


def run_retrieval(base_url,cases,root=None,timeout=960,synthetic=False,k=5):
    root=Path(root or Path.cwd()).resolve();snapshots={};rows=[]
    with httpx.Client(base_url=base_url,timeout=30,trust_env=False) as client:
        health=client.get('/health').raise_for_status().json();synthetic=synthetic or health.get('test_environment',False)
        for case in cases:
            snapshot=None;failure=None
            try:
                source=str((root/case['repository']).resolve())
                if source not in snapshots:
                    submitted=client.post('/repositories',json={'path':source}).raise_for_status().json()
                    snapshot=wait_for(client,'/repositories/'+submitted['id'],'status',{'importing'},timeout)
                    if snapshot['status']!='ready':raise ValueError(snapshot.get('error_code') or 'import_failed')
                    snapshots[source]=snapshot
                snapshot=snapshots[source]
            except Exception as exc:failure=type(exc).__name__
            for name,mode,rerank in CONFIGURATIONS:
                started=time.monotonic();row={'id':case['id'],'configuration':name,'query':case['query'],'status':'failed','usage':None,'quality_pass':None,'synthetic':synthetic,'recall_at_k':None}
                try:
                    if failure:raise ValueError(failure)
                    sid=snapshot['id'];row.update(snapshot_id=sid,manifest_hash=snapshot['manifest_hash'])
                    if mode=='hybrid':
                        registered=client.post('/repositories/'+sid+'/retrieval-index',json={'idempotency_key':'eval-'+sid}).raise_for_status().json()
                        index=wait_for(client,'/repositories/'+sid+'/retrieval-index','status',{'queued','building'},timeout)
                        row['index_usage']=index.get('usage');row['index_id']=index.get('id')
                        if index['status']!='ready':raise ValueError(index.get('error_code') or 'retrieval_index_not_ready')
                    response=client.post('/repositories/'+sid+'/search',json={'query':case['query'],'retrieval_mode':mode,'rerank':rerank,'limit':20}).raise_for_status().json()
                    row.update(status='succeeded',usage=response['usage'],role_usage=response['role_usage'],hits=response['hits'],backend_configuration=response['configuration'],**score_retrieval(case,response['hits'],sid,k))
                except Exception as exc:row['error_code']=str(exc) if isinstance(exc,ValueError) else type(exc).__name__
                row['elapsed_ms']=round((time.monotonic()-started)*1000,2);rows.append(row)
    summary={}
    for name,_,_ in CONFIGURATIONS:
        selected=[r for r in rows if r['configuration']==name];recalls=[r['recall_at_k'] for r in selected]
        summary[name]={'total':len(selected),'execution_succeeded':sum(r['status']=='succeeded' for r in selected),'unknown_usage':sum(r['usage'] is None for r in selected),'recall_at_k_all_cases':sum(v or 0 for v in recalls)/len(selected) if selected else None,'pending_manual_review':len(selected)}
    return {'created_at':datetime.now(timezone.utc).isoformat(),'synthetic':synthetic,'quality_improvement':None,'quality_note':'Recall checks annotated source overlap, not semantic answer quality. Failed cases remain in denominators. Index usage is a shared build cost and must not be summed once per query. Offline toy vectors cannot demonstrate real retrieval gains.','summary':summary,'results':rows}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',required=True);parser.add_argument('--tasks',type=Path,default=Path('eval/retrieval_tasks.jsonl'));parser.add_argument('--output',type=Path,required=True);parser.add_argument('--synthetic',action='store_true')
    args=parser.parse_args();cases=[json.loads(line) for line in args.tasks.read_text(encoding='utf-8').splitlines() if line.strip()]
    result=run_retrieval(args.base_url,cases,synthetic=args.synthetic);args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result['summary'],ensure_ascii=False))


if __name__=='__main__':main()
