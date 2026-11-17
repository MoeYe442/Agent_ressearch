"""Read-only recovery eligibility, non-secret version binding and partial reports."""
import hashlib
import json
import time
from pathlib import Path
from repolens.execution_store import digest,unseal,RecoveryRejected
from repolens.checkpoints import checkpoint_exists
from repolens.models import AnalysisResult,Usage,Claim
from repolens.evidence import EvidenceStore
from repolens.review import collect_claims,render_report
from repolens.context_compression import combine_stats


def signature(task,settings,db):
    snapshot=db.get_snapshot(task.snapshot_id)
    root=Path(__file__).parent
    source={path.relative_to(root).as_posix():hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(root.rglob('*.py'))}
    provider={name:hashlib.sha256(getattr(settings,name).encode()).hexdigest() for name in ['model_url','embedding_url','rerank_url','milvus_url']}
    # Bind every non-secret setting; paths do not alter the frozen snapshot semantics.
    excluded={'workspace_root','data_dir','execution_mode','redis_queue','client_networks',*provider}
    runtime={key:value for key,value in settings.model_dump(mode='json').items() if key not in excluded and not hasattr(getattr(settings,key),'get_secret_value')}
    runtime['storage_backend']=db.backend
    from repolens.documents import DocumentStore
    runtime['attached_documents']=DocumentStore(db).summaries(task.document_ids,task.snapshot_id)
    return {'version':'recovery-v1','source':source,'provider':provider,'execution_configuration':runtime,'model':settings.model_name,'embedding_model':settings.embedding_model,'dimensions':settings.embedding_dimensions,'rerank_model':settings.rerank_model,'test_environment':settings.test_environment,'snapshot_id':task.snapshot_id,'manifest':digest(snapshot.manifest),'question':digest(task.question),'mode':task.mode,'context_compression':task.context_compression,'retrieval_mode':task.retrieval_mode,'rerank':task.rerank,'retrieval_configuration':task.retrieval_configuration,'task_limits':task.budget_limits,'runtime_limits':{k:getattr(settings,k) for k in ['max_model_calls','max_tool_calls','max_tokens','max_seconds','max_output_tokens']}}


def saved_run(db,task_id):
    with db.connect() as conn:row=conn.execute('SELECT * FROM execution_runs WHERE task_id=?',(task_id,)).fetchone()
    if not row:return None
    try:
        value={**dict(row),'signature':json.loads(row['signature']),'budget':None}
        if row['budget']:value['budget']=unseal(row['budget'],'recovery_budget_corrupt')
        return value
    except RecoveryRejected:return {**dict(row),'signature':{},'budget':None,'recovery_error':'recovery_budget_corrupt'}
    except (ValueError,TypeError):return None


def eligibility(db,task,settings,*,validate_sources=False,retrieval=None):
    run=saved_run(db,task.id)
    if not task.recovery_enabled or not run or not checkpoint_exists(db,task.id):return False,'recovery_checkpoint_missing'
    if run.get('recovery_error'):return False,run['recovery_error']
    try:current=signature(task,settings,db)
    except (ValueError,KeyError,OSError):return False,'recovery_source_changed'
    if run['signature']!=current or digest(run['signature'])!=task.recovery_config_hash:return False,'recovery_configuration_changed'
    if task.retrieval_mode=='hybrid':
        if retrieval is None:
            from repolens.retrieval import RetrievalService
            retrieval=RetrievalService(settings,db)
        try:
            if retrieval.ready(task.snapshot_id)['id']!=task.retrieval_configuration.get('index_id'):return False,'retrieval_configuration_changed'
        except ValueError as exc:return False,str(exc)
    if time.time()>=run['deadline']:return False,'time_budget_exhausted'
    try:
        budget=run['budget'];usage=Usage.model_validate(budget['usage'])
        if budget['version']!=1 or budget['limits']!=run['signature']['runtime_limits']:return False,'recovery_budget_corrupt'
        if budget['stop_reason']:return False,budget['stop_reason']
        if usage.model_calls>=settings.max_model_calls or usage.tool_calls>=settings.max_tool_calls or usage.input_tokens+usage.output_tokens>=settings.max_tokens:return False,'budget_exhausted'
    except (KeyError,ValueError,TypeError):return False,'recovery_budget_corrupt'
    if validate_sources:
        store=EvidenceStore(db)
        try:
            for path in db.get_snapshot(task.snapshot_id).manifest:
                if time.time()>=run['deadline']:return False,'time_budget_exhausted'
                store.file_text(task.snapshot_id,path)
        except (ValueError,KeyError,OSError):return False,'recovery_snapshot_changed'
    return True,None


def current_usage(db,task_id):
    run=saved_run(db,task_id)
    if not run or not run['budget']:
        try:return Usage.model_validate(db.get('tasks',task_id).get('usage') or {}).model_copy(update={'estimated':True})
        except (ValueError,KeyError):return Usage(estimated=True)
    state=run['budget']
    return Usage.model_validate({**state['usage'],'estimated':state['unknown_usage'] or bool(state['pending']),'elapsed_ms':max(0,time.time()-run['started'])*1000})


def paused_report(db,task,graph=None):
    run=saved_run(db,task.id);roles=run['budget']['role_usage'] if run and run['budget'] else {}
    claims=collect_claims((graph or {}).get('subtasks',[]));valid=[];store=EvidenceStore(db)
    for claim in claims:
        try:
            if claim.evidence_ids and all(store.validate_evidence(ref,task.snapshot_id) for ref in claim.evidence_ids):
                claim.verification_status='references_valid';valid.append(claim)
        except (ValueError,KeyError,OSError):pass
    reason='cancelled' if task.cancel_requested else 'interrupted'
    return AnalysisResult(status='cancelled' if task.cancel_requested else 'partial',mode=task.mode,claims=valid,limitations=[reason],markdown=render_report(valid,[reason]),usage=current_usage(db,task.id),role_usage=roles,evidence_ids=sorted({ref for claim in valid for ref in claim.evidence_ids}),context_stats=combine_stats((graph or {}).get('subtasks',[])))
