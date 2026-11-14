import pytest
from repolens.budget import BudgetManager
from repolens.model_gateway import ModelGateway
from repolens.models import ModelTurn,ModelUsage
from repolens.model_client import ProviderError
from tests.test_execution_store import session


def test_model_response_and_settlement_replay_without_provider(indexed):
    s,lease=session(indexed);calls=[]
    class Model:
        def complete(self,*args,**kwargs):calls.append(True);return ModelTurn(content='cached',usage=ModelUsage(input_tokens=20,output_tokens=2))
    events=[];one=ModelGateway(Model(),BudgetManager(indexed[0],session=s),events.append,lambda:False,'durable')
    assert one.complete([],[]).content=='cached'
    two=ModelGateway(Model(),BudgetManager(indexed[0],session=s),events.append,lambda:False,'durable')
    assert two.complete([],[]).content=='cached' and len(calls)==1
    assert two.budget.snapshot().model_calls==1 and two.budget.snapshot().input_tokens==20
    assert any(e.type=='model_replayed' for e in events)
    lease.release()


def test_auxiliary_response_replays_with_fixed_payload(indexed):
    s,lease=session(indexed);calls=[]
    def request():calls.append(True);return [[1.,0.]],ModelUsage(input_tokens=5,output_tokens=0)
    for _ in range(2):
        gateway=ModelGateway(None,BudgetManager(indexed[0],session=s),lambda e:None,lambda:False,'durable')
        assert gateway.external(request,100,'embedding','c',cache_payload={'model':'fixture','input':['text']})==[[1.,0.]]
    assert len(calls)==1 and gateway.budget.snapshot().model_calls==1
    lease.release()


def test_saved_provider_failure_is_replayed_without_new_cost(indexed):
    s,lease=session(indexed);calls=[]
    class Model:
        def complete(self,*a,**kw):calls.append(True);raise ProviderError('fixture_offline')
    for _ in range(2):
        gateway=ModelGateway(Model(),BudgetManager(indexed[0],session=s),lambda e:None,lambda:False,'durable')
        with pytest.raises(ProviderError,match='fixture_offline'):gateway.complete([],[])
    assert len(calls)==1 and gateway.budget.snapshot().estimated
    lease.release()


def test_saved_tools_and_model_transcript_replay_without_new_calls(indexed,monkeypatch):
    from repolens.agent import AgentRunner
    from repolens.models import ToolContext
    from tests.scripted_model import ScriptedModel
    s,lease=session(indexed);calls=[];tools=[];registry=indexed[5];original=registry.invoke
    class Model(ScriptedModel):
        def complete(self,*a,**kw):calls.append(True);return super().complete(*a,**kw)
    def invoke(*a,**kw):tools.append(True);return original(*a,**kw)
    monkeypatch.setattr(registry,'invoke',invoke)
    for _ in range(2):
        budget=BudgetManager(indexed[0],session=s)
        result=AgentRunner(Model(),registry,indexed[0]).run('Question',ToolContext(snapshot_id=indexed[2].id,task_id='durable'),lambda e:None,lambda:False,budget=budget)
        assert result.status=='succeeded'
    assert len(calls)==3 and len(tools)==2 and result.usage.model_calls==3 and result.usage.tool_calls==2
    lease.release()
