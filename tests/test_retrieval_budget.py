import threading
from concurrent.futures import ThreadPoolExecutor
import pytest
from repolens.budget import BudgetManager,BudgetExceeded
from repolens.model_gateway import ModelGateway
from repolens.models import ModelUsage
from tests.test_budget import settings


def test_auxiliary_requests_share_call_and_token_budget(tmp_path):
    config=settings(tmp_path,max_model_calls=1,max_tokens=100)
    budget=BudgetManager(config);gateway=ModelGateway(None,budget,lambda e:None,lambda:False,'t')
    assert gateway.external(lambda:('data',ModelUsage(input_tokens=20,output_tokens=0)),50,'code.embedding','a')=='data'
    assert budget.snapshot().model_calls==1 and budget.snapshot().input_tokens==20
    with pytest.raises(BudgetExceeded):gateway.external(lambda:('bad',None),1,'docs.embedding','b')


def test_auxiliary_failure_and_missing_usage_remain_estimated(tmp_path):
    budget=BudgetManager(settings(tmp_path));gateway=ModelGateway(None,budget,lambda e:None,lambda:False,'t')
    assert gateway.external(lambda:('data',None),50,'code.embedding','a')=='data'
    assert budget.snapshot().estimated and budget.snapshot().input_tokens==50


def test_separate_gateways_share_one_provider_semaphore(tmp_path):
    budget=BudgetManager(settings(tmp_path));gateways=[ModelGateway(None,budget,lambda e:None,lambda:False,'t') for _ in range(4)]
    lock=threading.Lock();active=peak=0
    def call(i):
        def request():
            import time
            nonlocal active,peak
            with lock:active+=1;peak=max(active,peak)
            time.sleep(.03)
            with lock:active-=1
            return i,ModelUsage(input_tokens=1,output_tokens=0)
        return gateways[i].external(request,10,'embedding',str(i))
    with ThreadPoolExecutor(4) as pool:assert sorted(pool.map(call,range(4)))==list(range(4))
    assert peak==2
