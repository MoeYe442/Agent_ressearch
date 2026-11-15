"""Explicit API experiments. Stable server idempotency keys survive lost responses."""
import json
import math
import re
import time
import httpx
from repolens.benchmark.files import Artifacts,runner_lock
from repolens.benchmark.protocol import CONFIGS,digest,matrix,utcnow

TERMINAL={'succeeded','partial','failed','cancelled'}


class RunInterrupted(ValueError):pass


class API:
    def __init__(self,url):self.client=httpx.Client(base_url=url,trust_env=False,follow_redirects=False)
    def request(self,method,route,payload=None,*,optional=False,deadline=None):
        try:
            end=min(time.time()+30,deadline) if deadline is not None else time.time()+30
            if time.time()>=end:raise ValueError('evaluation_export_timeout')
            with self.client.stream(method,route,json=payload,timeout=max(.001,end-time.time())) as response:
                if optional and (response.status_code==404 or response.status_code==409 and route.endswith('/report')):return None
                body=bytearray()
                for chunk in response.iter_bytes():
                    if time.time()>end:raise RunInterrupted('api_response_timeout_outcome_may_be_unknown')
                    body.extend(chunk)
                    if len(body)>4*1024*1024:
                        if method=='POST':raise RunInterrupted('api_submission_response_limit_outcome_unknown')
                        raise ValueError('api_response_limit')
                if response.status_code>=500 and method=='POST':raise RunInterrupted('api_submission_response_error_outcome_unknown')
                if response.status_code>=300:raise ValueError('api_http_'+str(response.status_code))
                try:value=json.loads(body,parse_constant=lambda _:(_ for _ in ()).throw(ValueError('nonfinite_api_json')))
                except ValueError:
                    if method=='POST':raise RunInterrupted('api_submission_response_invalid_outcome_unknown') from None
                    raise ValueError('invalid_api_json') from None
                if not isinstance(value,dict):
                    if method=='POST':raise RunInterrupted('api_submission_response_invalid_outcome_unknown')
                    raise ValueError('api_object_required')
                return value
        except httpx.HTTPError:raise RunInterrupted('api_unavailable_outcome_may_be_unknown') from None
    def close(self):self.client.close()


def wait(api,route,pending,deadline):
    while True:
        value=api.request('GET',route)
        if value.get('status') not in pending:return value
        if time.time()>=deadline:raise RunInterrupted('pending_operation_timeout')
        time.sleep(.25)


def optional_artifact(files,name):
    return files.read(name) if files.path(name).exists() else None


class Runner:
    def __init__(self,directory,allow_draft=False):
        self.files=Artifacts(directory);self.plan=self.files.plan();self.timeout=self.plan.timeout_seconds
        self.plan_hash=digest(self.plan.model_dump(mode='json'))
        if self.plan.suite.annotation_status!='human_approved' and not allow_draft:raise ValueError('draft_rubric_requires_explicit_allow_draft')
        self.api=API(self.plan.api_url)
        self.context=None
    def check_configuration(self):
        current=self.api.request('GET','/evaluation/config')
        if not re.fullmatch('[a-f0-9]{64}',current.get('execution_fingerprint','')):raise ValueError('invalid_server_configuration')
        if self.context is None:
            self.context=optional_artifact(self.files,'context.json')
            if self.context is None:
                if not current.get('model_configured'):raise ValueError('evaluation_model_not_configured')
                self.context={'run_id':self.plan.run_id,'plan_hash':self.plan_hash,'server':current}
                self.files.write('context.json',self.context,exclusive=True)
        if self.context.get('run_id')!=self.plan.run_id or self.context.get('plan_hash')!=self.plan_hash or current!=self.context['server']:raise RunInterrupted('execution_configuration_changed_restore_original_before_resume')
        return current
    def snapshot(self,repo):
        name='preparations/'+repo.id+'-snapshot.json'
        saved=optional_artifact(self.files,name)
        if saved:
            value=self.api.request('GET','/repositories/'+saved['snapshot']['id'])
        else:
            started=time.time()
            response=self.api.request('POST','/repositories',{'github_url':repo.url,'ref':repo.commit,'idempotency_key':'bench-import:'+self.plan.run_id+':'+repo.id})
            value=wait(self.api,'/repositories/'+response['id'],{'importing'},time.time()+self.timeout)
        if value.get('status')!='ready' or value.get('commit_sha')!=repo.commit:raise ValueError('snapshot_not_ready_or_commit_changed')
        for path,source in repo.sources.items():
            if value.get('manifest',{}).get(path)!=source.sha256:raise ValueError('annotated_source_hash_mismatch')
        if saved and saved['snapshot']['manifest_hash']!=value['manifest_hash']:raise ValueError('snapshot_manifest_changed')
        if not saved:self.files.write(name,{'snapshot':value,'elapsed_ms':round((time.time()-started)*1000,2)},exclusive=True)
        return value
    def index(self,repo,snapshot):
        name='preparations/'+repo.id+'-index.json';saved=optional_artifact(self.files,name)
        if not saved:
            self.api.request('POST','/repositories/'+snapshot['id']+'/retrieval-index',{'idempotency_key':'bench-index:'+self.plan.run_id+':'+repo.id})
            value=wait(self.api,'/repositories/'+snapshot['id']+'/retrieval-index',{'queued','building'},time.time()+self.timeout)
            self.files.write(name,{'index':value},exclusive=True)
        else:value=self.api.request('GET','/repositories/'+snapshot['id']+'/retrieval-index')
        if value.get('status')!='ready' or (saved and saved['index']['id']!=value.get('id')):raise ValueError('evaluation_index_not_ready_or_changed')
        return value
    def collect_terminal(self,record):
        # Observing/cancelling a task must not extend its original deadline.
        # Exporting its immutable terminal artifacts is a separate read-only job.
        deadline=time.time()+120
        task=record['task']
        record['report']=self.api.request('GET','/tasks/'+task['id']+'/report',optional=True,deadline=deadline)
        record['evidence']=[]
        if record['report']:
            refs=sorted({ref for claim in record['report'].get('claims',[]) for ref in claim.get('evidence_ids',[])})
            if len(refs)>1000:raise ValueError('evidence_export_limit')
            for ref in refs:
                if not re.fullmatch('[a-f0-9]{64}',ref):raise ValueError('invalid_evidence_identifier')
                record['evidence'].append(self.api.request('GET','/evidence/'+ref,deadline=deadline))
        record['artifact_collected_at']=utcnow()
    def recollect_terminal(self,spec,record):
        # This path never submits, resumes or cancels an analysis. A new artifact
        # hash invalidates old human reviews, but the measured task stays fixed.
        self.check_configuration()
        current=self.api.request('GET','/tasks/'+record['task']['id'])
        if current.get('status') not in TERMINAL or any(current.get(key)!=record['task'].get(key) for key in ['status','attempt','execution_epoch','model_identifier','budget_limits','usage']):raise RunInterrupted('measured_task_changed_cannot_recollect')
        record['artifact_error']=None;record['artifact_recollections']=record.get('artifact_recollections',0)+1
        try:
            self.collect_terminal(record);self.check_configuration()
            record['error_code']=record['task'].get('error_code')
        except (RunInterrupted,ValueError,KeyError,TypeError):record['artifact_error']='terminal_artifact_recollection_failed'
        attempt=optional_artifact(self.files,'attempts/'+spec['key']+'.json')
        if attempt:record['elapsed_ms']=round(max(0,time.time()-attempt['started'])*1000,2)
        self.files.write('rows/'+spec['key']+'.json',record)
    def save_record(self,spec,record,attempt):
        record['elapsed_ms']=round(max(0,time.time()-attempt['started'])*1000,2) if attempt else None
        try:self.files.write('rows/'+spec['key']+'.json',record,exclusive=True)
        except ValueError:
            record.update(report=None,evidence=[],artifact_error='result_size_limit')
            self.files.write('rows/'+spec['key']+'.json',record,exclusive=True)
    def cell(self,spec):
        case=next(case for case in self.plan.suite.cases if case.id==spec['case_id'])
        repo=next(repo for repo in self.plan.suite.repositories if repo.id==case.repository)
        mode,retrieval,rerank=CONFIGS[spec['configuration']]
        key='bench:'+self.plan.run_id+':'+spec['key'];attempt_name='attempts/'+spec['key']+'.json'
        attempt=optional_artifact(self.files,attempt_name)
        if attempt and (type(attempt.get('started')) not in {int,float} or not math.isfinite(attempt['started']) or attempt['started']<=0 or attempt['started']>time.time()+60 or attempt.get('phase') not in {'prepared','submitting','observing','cancel_pending'}):raise RunInterrupted('invalid_attempt_artifact_restore_before_resume')
        record={'schema_version':1,'run_id':self.plan.run_id,'plan_hash':self.plan_hash,**spec,'observed_at':utcnow(),'execution_status':'error','task':None,'report':None,'evidence':[],'artifact_error':None,'configuration_valid':True,'elapsed_ms':0}
        try:
            self.check_configuration()
            snapshot=self.snapshot(repo)
            index=self.index(repo,snapshot) if retrieval=='hybrid' else None
            if attempt is None:
                attempt={'started':time.time(),'snapshot_id':snapshot['id'],'idempotency_key':key,'phase':'prepared','task_id':None}
                self.files.write(attempt_name,attempt,exclusive=True)
            if attempt.get('snapshot_id')!=snapshot['id'] or attempt.get('idempotency_key')!=key:raise ValueError('attempt_identity_changed')
            task=self.api.request('GET','/evaluation/tasks/'+key,optional=True)
            deadline=attempt['started']+self.timeout
            if task is None:
                if time.time()>=deadline:raise RunInterrupted('expired_submission_outcome_unknown_no_new_task_created')
                self.check_configuration()
                attempt['phase']='submitting';self.files.write(attempt_name,attempt)
                task=self.api.request('POST','/tasks',{'snapshot_id':snapshot['id'],'question':case.question,'mode':mode,'retrieval_mode':retrieval,'rerank':rerank,'idempotency_key':key})
            attempt['task_id']=task['id']
            if attempt.get('phase')!='cancel_pending':attempt['phase']='observing'
            self.files.write(attempt_name,attempt)
            record['snapshot']={'id':snapshot['id'],'commit':repo.commit,'manifest_hash':snapshot['manifest_hash']}
            if task.get('model_identifier')!=self.context['server']['model_identifier'] or task.get('budget_limits')!=self.context['server']['budget_limits'] or (index and task.get('retrieval_configuration',{}).get('index_id')!=index['id']):
                self.api.request('POST','/tasks/'+task['id']+'/cancel')
                raise RunInterrupted('task_configuration_mismatch_cancel_requested')
            while task.get('status') not in TERMINAL:
                if time.time()>=deadline:
                    attempt['phase']='cancel_pending';self.files.write(attempt_name,attempt)
                    task=self.api.request('POST','/tasks/'+task['id']+'/cancel')
                    if task.get('status') not in TERMINAL:raise RunInterrupted('evaluation_timeout_cancel_pending_resume_to_observe_original_task')
                    break
                time.sleep(.25);task=self.api.request('GET','/tasks/'+task['id'])
            record['task']=task
            record['error_code']=task.get('error_code')
            record['terminal_observed_at']=utcnow()
            record['execution_status']='timeout' if attempt.get('phase')=='cancel_pending' else task['status']
            self.collect_terminal(record)
            self.check_configuration()
        except RunInterrupted as exc:
            if record['task'] is not None and record['task'].get('status') in TERMINAL:
                record['artifact_error']='terminal_artifact_export_interrupted'
                record['error_code']=str(exc)
                self.save_record(spec,record,attempt)
            raise
        except (ValueError,KeyError,TypeError) as exc:
            if attempt and attempt.get('phase') in {'submitting','observing','cancel_pending'} and record['task'] is None:raise RunInterrupted('pending_original_task_requires_reconciliation') from None
            code=str(exc) if isinstance(exc,ValueError) and re.fullmatch(r'[a-z0-9_]+',str(exc)) else 'evaluation_artifact_error'
            record['error_code']=code
            if record['task'] is not None:record['artifact_error']=code
        self.save_record(spec,record,attempt)
    def run(self):
        try:
            with runner_lock(self.files):
                self.check_configuration()
                for spec in matrix(self.plan):
                    if self.files.path('rows/'+spec['key']+'.json').exists():
                        previous=self.files.read('rows/'+spec['key']+'.json')
                        if previous.get('run_id')!=self.plan.run_id or previous.get('plan_hash')!=self.plan_hash or any(previous.get(key)!=value for key,value in spec.items()):raise ValueError('stale_result_record')
                        if previous.get('artifact_error') and previous.get('task') and previous['task'].get('status') in TERMINAL:self.recollect_terminal(spec,previous)
                        continue
                    self.cell(spec)
        finally:self.api.close()
