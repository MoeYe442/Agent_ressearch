import operator
import threading
from typing import Annotated,TypedDict
import pytest
from langgraph.graph import StateGraph,START,END
from langgraph.types import Send
from repolens.checkpoints import saver_for,checkpoint_exists
from repolens.execution_store import WorkerPaused,LeaseLost,WorkerLease
from tests.test_execution_store import session


class State(TypedDict):
    values:Annotated[list,operator.add]


def test_real_sqlite_checkpointer_restores_pending_completed_branch(indexed):
    s,lease=session(indexed);count={'a':0,'b':0};done=threading.Event();paused=[True]
    def work(job):
        count[job['id']]+=1
        if job['id']=='b':
            done.wait(5)
            if paused[0]:raise WorkerPaused()
        else:done.set()
        return {'values':[job['id']]}
    builder=StateGraph(State);builder.add_node('plan',lambda st:{});builder.add_node('work',work);builder.add_edge(START,'plan');builder.add_conditional_edges('plan',lambda st:[Send('work',{'id':'a'}),Send('work',{'id':'b'})],['work']);builder.add_edge('work',END)
    config={'configurable':{'thread_id':'durable'},'max_concurrency':2}
    with saver_for(s) as saver:
        graph=builder.compile(checkpointer=saver)
        with pytest.raises(WorkerPaused):list(graph.stream({'values':[]},config,durability='sync'))
    assert checkpoint_exists(indexed[1],'durable')
    paused[0]=False
    with saver_for(s) as saver:
        result=builder.compile(checkpointer=saver).invoke(None,config,durability='sync')
    assert result['values']==['a','b'] and count=={'a':1,'b':2}
    lease.release()


def test_expired_worker_cannot_commit_checkpoint(indexed):
    now=[100.];s,lease=session(indexed,lambda:now[0])
    builder=StateGraph(State);builder.add_node('work',lambda st:{'values':['x']});builder.add_edge(START,'work');builder.add_edge('work',END)
    now[0]=106.;replacement=WorkerLease(indexed[1],ttl=5,clock=lambda:now[0]);replacement.acquire()
    with saver_for(s) as saver:
        with pytest.raises(LeaseLost):builder.compile(checkpointer=saver).invoke({'values':[]},{'configurable':{'thread_id':'durable'}},durability='sync')


def test_checkpoint_deserializer_never_invokes_unregistered_constructor(indexed,monkeypatch):
    import os
    import ormsgpack
    called=[]
    monkeypatch.setattr(os,'getcwd',lambda:called.append(True) or 'unsafe-constructor')
    payload=ormsgpack.packb(ormsgpack.Ext(1,ormsgpack.packb(('os','getcwd',[]))))
    s,lease=session(indexed)
    try:
        with saver_for(s) as saver:saver.serde.loads_typed(('msgpack',payload))
        assert called==[]
    finally:lease.release()
