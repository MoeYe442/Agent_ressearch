from concurrent.futures import ThreadPoolExecutor
import threading
import pytest
from repolens.config import Settings
from repolens.budget import BudgetManager, BudgetExceeded
from repolens.models import ModelUsage


def settings(tmp_path, **kwargs):
    return Settings(workspace_root=tmp_path,data_dir=tmp_path/'data',**kwargs)


def test_parallel_reservations_cannot_overspend(tmp_path):
    budget=BudgetManager(settings(tmp_path,max_tokens=100))
    barrier=threading.Barrier(2)
    def attempt(i):
        barrier.wait()
        try:
            return budget.reserve_model(60,20,'code',str(i))
        except BudgetExceeded:
            return None
    with ThreadPoolExecutor(2) as pool:
        admitted=list(pool.map(attempt,range(2)))
    assert sum(r is not None for r in admitted)==1
    assert budget.snapshot().model_calls==1
    assert budget.snapshot().input_tokens+budget.snapshot().output_tokens<=100


def test_subtask_tool_cap_survives_reentry(tmp_path):
    budget=BudgetManager(settings(tmp_path))
    for _ in range(8):
        budget.reserve_tool('child')
    with pytest.raises(BudgetExceeded,match='subtask_tool_limit'):
        budget.reserve_tool('child')
    budget.reserve_tool('other')
    assert budget.snapshot().tool_calls==9


def test_usage_without_provider_counts_is_estimated(tmp_path):
    budget=BudgetManager(settings(tmp_path))
    reservation=budget.reserve_model(100,50,'docs','d')
    assert budget.snapshot().estimated
    budget.settle_model(reservation.id,None)
    assert budget.snapshot().estimated
    assert budget.snapshot().input_tokens==100 and budget.snapshot().output_tokens==50


def test_actual_usage_is_not_clamped_to_limit(tmp_path):
    budget=BudgetManager(settings(tmp_path,max_tokens=100))
    reservation=budget.reserve_model(50,40,'code','c')
    budget.settle_model(reservation.id,ModelUsage(input_tokens=90,output_tokens=30))
    assert budget.snapshot().input_tokens+budget.snapshot().output_tokens==120
    with pytest.raises(BudgetExceeded):
        budget.reserve_model(1,1,'review','r')


def test_settlement_is_once_only_and_measured_usage_replaces_reserve(tmp_path):
    budget=BudgetManager(settings(tmp_path))
    r=budget.reserve_model(100,40,'single','single')
    budget.settle_model(r.id,ModelUsage(input_tokens=12,output_tokens=5))
    budget.settle_model(r.id,ModelUsage(input_tokens=12,output_tokens=5))
    assert budget.snapshot().input_tokens==12 and not budget.snapshot().estimated
