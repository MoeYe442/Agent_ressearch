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
