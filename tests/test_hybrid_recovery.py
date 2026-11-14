import threading
import pytest
from repolens.tasks import TaskService
from repolens.recovery import current_usage
from tests.scripted_model import ScriptedModel
from tests.test_retrieval import prepared
from tests.test_tasks import wait_task


def paused_hybrid(indexed):
    settings,fixture,retrieval=prepared(indexed)
    entered,release=threading.Event(),threading.Event()
    class Slow(ScriptedModel):
        def complete(self,*a,**kw):
            entered.set();release.wait(5)
            return super().complete(*a,**kw)
    service=TaskService(settings,indexed[1],Slow(),retrieval_factory=lambda s,db:fixture.service(db))
    service.start();task=service.submit(indexed[2].id,'Question',retrieval_mode='hybrid')
    assert entered.wait(3)
    stop=threading.Thread(target=service.stop);stop.start();assert service.stopping.wait(3)
    release.set();stop.join(8);assert not stop.is_alive()
    assert service.get(task.id).usage.model_calls==1
    return settings,fixture,retrieval,task.id


def invalidate(indexed,retrieval,change):
    job=retrieval.status(indexed[2].id)
    if change=='unavailable':job['status']='failed'
    else:job['id']='replacement-generation'
    indexed[1].put('retrieval_jobs',job['id'],job)
    indexed[1].put('retrieval_heads',indexed[2].id,{'id':job['id']})


@pytest.mark.parametrize('change',['unavailable','replaced'])
def test_resume_rejects_invalid_original_hybrid_generation_before_queue(indexed,change):
    settings,fixture,retrieval,task_id=paused_hybrid(indexed)
    invalidate(indexed,retrieval,change)
    service=TaskService(settings,indexed[1],ScriptedModel(),retrieval_factory=lambda s,db:fixture.service(db));service.start()
    try:
        assert not service.get(task_id).resume_available
        with pytest.raises(ValueError,match='retrieval_index_not_ready|retrieval_configuration_changed'):
            service.resume(task_id,'invalid-index')
        assert service.get(task_id).attempt==1
        assert service.get(task_id).usage.model_calls==current_usage(indexed[1],task_id).model_calls==1
    finally:service.stop()


def test_hybrid_generation_loss_after_resume_preserves_durable_usage(indexed):
    settings,fixture,retrieval,task_id=paused_hybrid(indexed)
    service=TaskService(settings,indexed[1],ScriptedModel(),retrieval_factory=lambda s,db:fixture.service(db));service.start()
    # Serialize invalidation between accepted resume and the queued worker's execution.
    try:
        with service.lock:
            service.resume(task_id,'index-race')
            invalidate(indexed,retrieval,'unavailable')
        done=wait_task(service,task_id)
        assert done.status=='failed' and done.attempt==2
        assert done.usage.model_calls==current_usage(indexed[1],task_id).model_calls==1
        assert indexed[1].get('reports',task_id)['usage']['model_calls']==1
        assert service.events(task_id)[-1].payload['usage']['model_calls']==1
    finally:service.stop()
