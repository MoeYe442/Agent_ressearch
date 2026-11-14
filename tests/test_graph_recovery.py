import threading
from repolens.tasks import TaskService
from tests.collaborative_model import CollaborativeModel
from tests.test_tasks import wait_task


def test_collaborative_checkpoint_resumes_without_replanning(indexed):
    entered,release=threading.Event(),threading.Event();planner=[]
    class SlowPlanner(CollaborativeModel):
        def complete(self,messages,*a,**kw):
            if 'ROLE: planner' in messages[0]['content']:
                planner.append(True);entered.set();release.wait(5)
            return super().complete(messages,*a,**kw)
    one=TaskService(indexed[0],indexed[1],SlowPlanner());one.start();task=one.submit(indexed[2].id,'Compare code and documentation',mode='collaborative')
    assert entered.wait(3);stop=threading.Thread(target=one.stop);stop.start();assert one.stopping.wait(3);release.set();stop.join(8)
    class Resume(CollaborativeModel):
        def complete(self,messages,*a,**kw):
            if 'ROLE: planner' in messages[0]['content']:planner.append(True)
            return super().complete(messages,*a,**kw)
    two=TaskService(indexed[0],indexed[1],Resume());two.start()
    try:
        assert two.get(task.id).resume_available
        two.resume(task.id,'resume-collaborative')
        done=wait_task(two,task.id)
        assert done.status=='succeeded' and done.usage.model_calls==6 and len(planner)==1
        assert len(indexed[1].get('graphs',task.id)['subtasks'])==2
    finally:two.stop()
