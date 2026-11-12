import time
import threading
import pytest
from fastapi.testclient import TestClient
from repolens.api import create_app
from tests.collaborative_model import CollaborativeModel
from tests.scripted_model import ScriptedModel


def wait(client,task_id):
    for _ in range(500):
        task=client.get('/tasks/'+task_id).json()
        if task['status'] not in {'queued','running'}:return task
        time.sleep(.01)
    raise AssertionError('task did not finish')


def test_old_task_request_defaults_to_single(indexed):
    with TestClient(create_app(indexed[0],ScriptedModel()),client=('127.0.0.1',1)) as client:
        task=client.post('/tasks',json={'snapshot_id':indexed[2].id,'question':'Question'}).json()
        assert wait(client,task['id'])['mode']=='single'
        assert client.get('/tasks/'+task['id']+'/report').json()['mode']=='single'


def test_mode_persists_and_graph_events_are_task_scoped(indexed):
    with TestClient(create_app(indexed[0],CollaborativeModel()),client=('127.0.0.1',1)) as client:
        response=client.post('/tasks',json={'snapshot_id':indexed[2].id,'question':'Compare code and docs','mode':'collaborative'})
        assert response.status_code==202
        task=wait(client,response.json()['id'])
        assert task['status']=='succeeded' and task['mode']=='collaborative'
        graph=client.get('/tasks/'+task['id']+'/graph').json()
        assert graph['task_id']==task['id'] and len(graph['subtasks'])==2
        assert graph['status']=='succeeded' and graph['reviews']
        report=client.get('/tasks/'+task['id']+'/report').json()
        assert report['usage']==task['usage'] and report['mode']==task['mode']
        assert client.get('/tasks/missing/graph').status_code==404


def test_idempotency_conflicts_across_modes(indexed):
    with TestClient(create_app(indexed[0],ScriptedModel()),client=('127.0.0.1',1)) as client:
        body={'snapshot_id':indexed[2].id,'question':'Question','idempotency_key':'mode-key'}
        first=client.post('/tasks',json=body)
        assert client.post('/tasks',json={**body,'mode':'single'}).json()['id']==first.json()['id']
        assert client.post('/tasks',json={**body,'mode':'collaborative'}).status_code==409
        assert client.post('/tasks',json={**body,'mode':'unknown'}).status_code==422


def test_restart_marks_graph_interrupted_without_resume(indexed):
    from repolens.tasks import TaskService
    settings,db,snapshot,_,_,_=indexed
    task=TaskService(settings,db,None).submit(snapshot.id,'Question',None,mode='collaborative')
    task.status='running';db.put('tasks',task.id,task)
    with TestClient(create_app(settings,CollaborativeModel()),client=('127.0.0.1',1)) as client:
        saved=client.get('/tasks/'+task.id).json()
        assert saved['status']=='failed' and saved['error_code']=='interrupted'
        assert client.post('/tasks/'+task.id+'/resume').status_code==404


def test_cancel_stops_new_subtasks(indexed):
    gate,entered=threading.Event(),threading.Event()
    class Slow(CollaborativeModel):
        def complete(self,*args,**kwargs):
            entered.set();gate.wait(5)
            return super().complete(*args,**kwargs)
    with TestClient(create_app(indexed[0],Slow()),client=('127.0.0.1',1)) as client:
        task=client.post('/tasks',json={'snapshot_id':indexed[2].id,'question':'Question','mode':'collaborative'}).json()
        assert entered.wait(3)
        client.post('/tasks/'+task['id']+'/cancel');gate.set()
        assert wait(client,task['id'])['status']=='cancelled'
        events=client.get('/tasks/'+task['id']+'/events').text
        assert 'subtask_started' not in events


def test_legacy_task_list_and_report_load(indexed):
    from repolens.tasks import TaskService
    settings,db,snapshot,_,_,_=indexed
    task=TaskService(settings,db,None).submit(snapshot.id,'Question',None)
    raw=task.model_dump(mode='json');raw.pop('mode');db.put('tasks',task.id,raw)
    with TestClient(create_app(settings,ScriptedModel()),client=('127.0.0.1',1)) as client:
        wait(client,task.id)
        assert client.get('/tasks').json()[0]['mode']=='single'
        report=db.get('reports',task.id)
        for key in ['mode','role_usage','evidence_ids']:report.pop(key,None)
        for claim in report['claims']:
            claim.pop('claim_id',None);claim.pop('review_status',None)
        db.put('reports',task.id,report)
        restored=client.get('/tasks/'+task.id+'/report').json()
        assert restored['mode']=='single' and restored['claims'][0]['review_status']=='not_reviewed'


def test_failure_and_budget_events_are_not_succeeded(indexed):
    settings=indexed[0].model_copy(update={'max_model_calls':1})
    with TestClient(create_app(settings,CollaborativeModel()),client=('127.0.0.1',1)) as client:
        task=client.post('/tasks',json={'snapshot_id':indexed[2].id,'question':'Question','mode':'collaborative'}).json()
        done=wait(client,task['id'])
        assert done['status']=='partial' and done['usage']['model_calls']==1
        report=client.get('/tasks/'+task['id']+'/report').json()
        graph=client.get('/tasks/'+task['id']+'/graph').json()
        assert graph['status']==report['status']==done['status']
        assert 'budget_exhausted' in report['limitations']


@pytest.mark.parametrize('throws',[False,True])
def test_final_reference_recheck_keeps_partial_terminal_atomic(indexed,monkeypatch,throws):
    from repolens.tasks import TaskService
    from repolens.evidence import EvidenceStore
    finished=threading.Event();save=TaskService._save;validate=EvidenceStore.validate_evidence
    bad=indexed[4].read_evidence(indexed[2].id,'app.py',9,11).id
    def persist(self,task,type,*args,**kwargs):
        result=save(self,task,type,*args,**kwargs)
        if type=='review_completed':finished.set()
        return result
    def check(self,evidence_id,*args,**kwargs):
        if finished.is_set() and evidence_id==bad:
            if throws:raise RuntimeError('SECRET_INTERNAL_FAILURE')
            return False
        return validate(self,evidence_id,*args,**kwargs)
    monkeypatch.setattr(TaskService,'_save',persist);monkeypatch.setattr(EvidenceStore,'validate_evidence',check)
    with TestClient(create_app(indexed[0],CollaborativeModel()),client=('127.0.0.1',1)) as client:
        task=client.post('/tasks',json={'snapshot_id':indexed[2].id,'question':'Compare docs','mode':'collaborative'}).json()
        done=wait(client,task['id']);graph=client.get('/tasks/'+task['id']+'/graph').json()
        response=client.get('/tasks/'+task['id']+'/report');report=response.json()
        assert response.status_code==200 and done['status']==graph['status']==report['status']=='partial'
        assert len(report['claims'])==1 and report['usage']==done['usage']
        assert 'SECRET_INTERNAL_FAILURE' not in response.text


def test_unexpected_worker_error_updates_graph_report_and_usage_atomically(indexed,monkeypatch):
    from repolens.orchestration import CollaborativeRunner
    original=CollaborativeRunner.run
    def crash(self,*args,**kwargs):
        original(self,*args,**kwargs)
        raise RuntimeError('SECRET_INTERNAL_FAILURE')
    monkeypatch.setattr(CollaborativeRunner,'run',crash)
    with TestClient(create_app(indexed[0],CollaborativeModel()),client=('127.0.0.1',1)) as client:
        task=client.post('/tasks',json={'snapshot_id':indexed[2].id,'question':'Question','mode':'collaborative'}).json()
        done=wait(client,task['id']);graph=client.get('/tasks/'+task['id']+'/graph').json()
        response=client.get('/tasks/'+task['id']+'/report');report=response.json()
        assert response.status_code==200 and done['status']==graph['status']==report['status']=='failed'
        assert report['usage']==done['usage'] and done['error_code']=='worker_error'
        assert 'SECRET_INTERNAL_FAILURE' not in response.text
