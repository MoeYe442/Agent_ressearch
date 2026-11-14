import json
import subprocess
import sys
import time
from pathlib import Path
import pytest
from repolens.tasks import TaskService
from tests.scripted_model import ScriptedModel
from tests.collaborative_model import CollaborativeModel
from tests.test_tasks import wait_task
from tests.recovery_audit import write_case


@pytest.mark.parametrize('point,expected_calls',[('response',3),('inflight',4),('terminal',3),('parallel',7)])
def test_real_process_exit_recovers_durable_work_and_unknown_cost(indexed,tmp_path,point,expected_calls):
    output=tmp_path/'task.json';calls=tmp_path/'calls.txt';settings=indexed[0].model_copy(update={'test_environment':True})
    child=subprocess.run([sys.executable,'-m','tests.recovery_child','--data',str(settings.data_dir),'--workspace',str(settings.workspace_root),'--snapshot',indexed[2].id,'--point',point,'--output',str(output),'--calls',str(calls)],cwd=str(Path(__file__).resolve().parents[1]),capture_output=True,timeout=20)
    assert child.returncode==72,child.stderr.decode(errors='replace')
    task_id=json.loads(output.read_text())['task_id'];new_calls=[]
    class Single(ScriptedModel):
        def complete(self,*a,**kw):new_calls.append('single');return super().complete(*a,**kw)
    class Graph(CollaborativeModel):
        def complete(self,messages,*a,**kw):
            role=next(r for r in ['planner','reviewer','code','docs'] if 'ROLE: '+r in messages[0]['content']);new_calls.append(role);return super().complete(messages,*a,**kw)
    service=TaskService(settings,indexed[1],Graph() if point=='parallel' else Single())
    deadline=time.monotonic()+8
    while True:
        try:service.start();break
        except ValueError as exc:
            assert str(exc)=='worker_already_running' and time.monotonic()<deadline
            time.sleep(.05)
    try:
        paused=service.get(task_id);assert paused.status=='partial' and paused.resume_available
        service.resume(task_id,'real-process-resume');done=wait_task(service,task_id)
        assert done.status=='succeeded'
        old_calls=calls.read_text().splitlines()
        assert len(old_calls)+len(new_calls)==expected_calls
        assert done.usage.model_calls==expected_calls
        assert done.usage.estimated==(point in {'inflight','parallel'})
        if point=='parallel':
            assert old_calls.count('code')==2 and new_calls.count('code')==0 and new_calls.count('planner')==0
            assert sum(e.type=='subtask_started' and e.payload.get('role')=='code' for e in service.events(task_id))==1
        if point=='terminal':assert new_calls==[]
        write_case(point,{'status':done.status,'task_id':task_id,'same_task_id':done.id==task_id,'attempt':done.attempt,'execution_epoch':done.execution_epoch,'provider_calls_observed':len(old_calls)+len(new_calls),'new_provider_calls':len(new_calls),'usage':done.usage.model_dump(),'completed_code_replayed_without_execution':point=='parallel' and new_calls.count('code')==0,'budget_limits':done.budget_limits})
    finally:service.stop()
