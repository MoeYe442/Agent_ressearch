import time
import pytest
from repolens.budget import BudgetManager,BudgetExceeded
from repolens.models import ModelUsage
from tests.test_execution_store import session


def test_pending_cost_and_child_tools_survive_restart(indexed):
    s,lease=session(indexed);one=BudgetManager(indexed[0],session=s)
    one.reserve_model(100,40,'code','child')
    for _ in range(8):one.reserve_tool('child')
    two=BudgetManager(indexed[0],session=s)
    assert two.snapshot().model_calls==1 and two.snapshot().input_tokens==100 and two.snapshot().output_tokens==40
    assert two.snapshot().estimated and not two.pending
    with pytest.raises(BudgetExceeded,match='subtask_tool_limit'):two.reserve_tool('child')
    lease.release()


def test_abnormal_usage_stop_is_durable(indexed):
    s,lease=session(indexed);one=BudgetManager(indexed[0],session=s);r=one.reserve_model(10,10,'code','c')
    one.settle_model(r.id,ModelUsage(input_tokens=30,output_tokens=10))
    two=BudgetManager(indexed[0],session=s)
    with pytest.raises(BudgetExceeded,match='provider_usage_exceeded_reservation'):two.check()
    assert two.snapshot().input_tokens==30
    lease.release()


def test_absolute_deadline_is_not_extended_by_new_budget(indexed):
    s,lease=session(indexed);BudgetManager(indexed[0],session=s)
    with indexed[1].connect() as conn:conn.execute('UPDATE execution_runs SET deadline=? WHERE task_id=?',(time.time()-1,'durable'))
    again=type(s)(indexed[1],'durable',1,lease,{'fixture_version':1})
    with pytest.raises(BudgetExceeded,match='time_budget_exhausted'):BudgetManager(indexed[0],session=again).check()
    lease.release()
