from concurrent.futures import ThreadPoolExecutor
import json
import threading
import time
import pytest
from repolens.budget import BudgetManager, BudgetExceeded
from repolens.model_gateway import ModelGateway
from repolens.model_client import ProviderError,HTTPChatModel
from repolens.models import ModelTurn,ModelUsage
from tests.test_budget import settings


def test_peak_model_concurrency_is_two(tmp_path):
    lock=threading.Lock()
    active=peak=0
    class Model:
        def complete(self,*args,**kwargs):
            nonlocal active,peak
            with lock:
                active+=1;peak=max(peak,active)
            time.sleep(.03)
            with lock:active-=1
            return ModelTurn(content='{}',usage=ModelUsage(input_tokens=10,output_tokens=2))
    config=settings(tmp_path)
    gateway=ModelGateway(Model(),BudgetManager(config),lambda e:None,lambda:False,'task')
    with ThreadPoolExecutor(4) as pool:
        list(pool.map(lambda i:gateway.complete([],[],'code',str(i)),range(4)))
    assert peak==2 and gateway.budget.snapshot().model_calls==4


def test_retry_and_json_repair_share_global_budget(tmp_path):
    class Offline:
        def complete(self,*args,**kwargs):raise ProviderError('offline',retryable=True)
    config=settings(tmp_path,max_model_calls=2)
    gateway=ModelGateway(Offline(),BudgetManager(config),lambda e:None,lambda:False,'task')
    with pytest.raises(BudgetExceeded):gateway.complete([],[],'planner','p')
    assert gateway.budget.snapshot().model_calls==2
    assert gateway.budget.snapshot().estimated


def test_cancelled_waiter_never_enters_provider(tmp_path):
    called=[]
    class Model:
        def complete(self,*args,**kwargs):called.append(True);return ModelTurn()
    gateway=ModelGateway(Model(),BudgetManager(settings(tmp_path)),lambda e:None,lambda:True,'task')
    with pytest.raises(BudgetExceeded,match='cancelled'):gateway.complete([],[],'code','c')
    assert not called and gateway.budget.snapshot().model_calls==0


def test_parallel_deadlines_do_not_overwrite_each_other(tmp_path):
    model=HTTPChatModel(settings(tmp_path))
    earlier=model.with_deadline(100)
    later=model.with_deadline(200)
    assert earlier.deadline==100 and later.deadline==200 and model.deadline is None
    assert earlier.ssl_context is later.ssl_context


def test_inflight_usage_settles_before_cancelled_terminal(tmp_path):
    cancel=threading.Event()
    class Model:
        def complete(self,*args,**kwargs):
            cancel.set()
            return ModelTurn(usage=ModelUsage(input_tokens=19,output_tokens=3))
    gateway=ModelGateway(Model(),BudgetManager(settings(tmp_path)),lambda e:None,cancel.is_set,'task')
    with pytest.raises(BudgetExceeded,match='cancelled'):gateway.complete([],[],'docs','d')
    assert gateway.budget.snapshot().input_tokens==19
    assert not gateway.budget.snapshot().estimated


@pytest.mark.parametrize('reason',['cancelled','time_budget_exhausted'])
def test_cancel_during_started_event_does_not_enter_provider(tmp_path,reason):
    called=[];cancel=threading.Event();budget=BudgetManager(settings(tmp_path))
    class Model:
        def complete(self,*args,**kwargs):called.append(True);return ModelTurn()
    def emit(event):
        if event.type=='model_started':
            if reason=='cancelled':cancel.set()
            else:budget.deadline=time.monotonic()-1
    gateway=ModelGateway(Model(),budget,emit,cancel.is_set,'task')
    with pytest.raises(BudgetExceeded,match=reason):gateway.complete([],[],'planner','p')
    assert not called and not budget.pending
    assert budget.snapshot().model_calls==0 and budget.snapshot().input_tokens==0
