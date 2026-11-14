import sqlite3
import time
import pytest
from fastapi.testclient import TestClient
from repolens.api import create_app
from repolens.tasks import TaskService
from tests.test_task_recovery import interrupted
from tests.scripted_model import ScriptedModel
from tests.test_collaborative_api import wait


def test_resume_key_and_queue_transition_are_atomic(indexed):
    task_id,_=interrupted(indexed);service=TaskService(indexed[0],indexed[1],ScriptedModel());service.start()
    try:
        with indexed[1].connect() as conn:
            conn.execute("CREATE TRIGGER fail_resume BEFORE INSERT ON entities WHEN NEW.kind='resume_keys' BEGIN SELECT RAISE(ABORT,'fixture_boundary'); END")
        try:service.resume(task_id,'atomic-key')
        except sqlite3.IntegrityError:pass
        else:raise AssertionError('failure trigger did not fire')
        assert service.get(task_id).status=='partial' and service.get(task_id).attempt==1
    finally:
        with indexed[1].connect() as conn:conn.execute('DROP TRIGGER fail_resume')
        service.stop()


def test_resume_endpoint_and_same_key_retry_do_not_duplicate_calls(indexed):
    task_id,_=interrupted(indexed)
    with TestClient(create_app(indexed[0],ScriptedModel()),client=('127.0.0.1',1)) as client:
        first=client.post('/tasks/'+task_id+'/resume',json={'idempotency_key':'resume-once'})
        assert first.status_code==202
        assert client.post('/tasks/'+task_id+'/resume',json={'idempotency_key':'resume-once'}).status_code==202
        done=wait(client,task_id);assert done['status']=='succeeded' and done['attempt']==2 and done['usage']['model_calls']==3
        assert client.post('/tasks/'+task_id+'/resume',json={'idempotency_key':'resume-once'}).json()['attempt']==2
        assert client.post('/tasks/'+task_id+'/resume',json={'idempotency_key':'different'}).status_code==409


@pytest.mark.parametrize('change,expected', [('expired','time_budget_exhausted'),('model','recovery_configuration_changed'),('snapshot','recovery_snapshot_changed'),('cancel','task_not_resumable')])
def test_resume_rejects_changed_or_terminal_context_without_provider(indexed,change,expected):
    task_id,_=interrupted(indexed);settings=indexed[0];calls=[]
    if change=='expired':
        with indexed[1].connect() as conn:conn.execute('UPDATE execution_runs SET deadline=? WHERE task_id=?',(time.time()-1,task_id))
    if change=='model':settings=settings.model_copy(update={'model_name':'different'})
    if change=='snapshot':(indexed[2].root/'app.py').write_text('tampered')
    class Model(ScriptedModel):
        def complete(self,*a,**kw):calls.append(True);return super().complete(*a,**kw)
    with TestClient(create_app(settings,Model()),client=('127.0.0.1',1)) as client:
        if change=='cancel':assert client.post('/tasks/'+task_id+'/cancel').json()['status']=='cancelled'
        response=client.post('/tasks/'+task_id+'/resume',json={'idempotency_key':'reject'})
        assert response.status_code==409 and response.json()['error_code']==expected
        assert not calls and client.get('/tasks/'+task_id).json()['attempt']==1
