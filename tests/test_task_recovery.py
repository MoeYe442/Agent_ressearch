import threading
from repolens.tasks import TaskService
from tests.scripted_model import ScriptedModel
from tests.test_tasks import wait_task


def interrupted(indexed):
    entered,release=threading.Event(),threading.Event();calls=[]
    class Slow(ScriptedModel):
        def complete(self,*args,**kwargs):
            calls.append(True);entered.set();release.wait(5)
            return super().complete(*args,**kwargs)
    service=TaskService(indexed[0],indexed[1],Slow());service.start();task=service.submit(indexed[2].id,'Question')
    assert entered.wait(3)
    stop=threading.Thread(target=service.stop);stop.start();assert service.stopping.wait(3);release.set();stop.join(8);assert not stop.is_alive()
    return task.id,calls


def test_service_stop_is_recoverable_and_saved_first_response_is_not_repeated(indexed):
    task_id,old_calls=interrupted(indexed);calls=[]
    class Counting(ScriptedModel):
        def complete(self,*a,**kw):calls.append(True);return super().complete(*a,**kw)
    next_service=TaskService(indexed[0],indexed[1],Counting());next_service.start()
    try:
        paused=next_service.get(task_id)
        assert paused.status=='partial' and paused.resume_available
        assert paused.usage.model_calls==1
        next_service.resume(task_id,'resume-key')
        done=wait_task(next_service,task_id)
        assert done.status=='succeeded' and done.attempt==2 and done.execution_epoch==2
        assert done.usage.model_calls==3 and len(old_calls)+len(calls)==3
        assert [e.sequence for e in next_service.events(task_id)]==list(range(1,len(next_service.events(task_id))+1))
    finally:next_service.stop()
