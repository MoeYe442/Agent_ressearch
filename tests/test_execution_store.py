import sqlite3
import pytest
from repolens.execution_store import WorkerLease,ExecutionSession,LeaseLost,RecoveryRejected


def session(indexed,clock=None):
    db=indexed[1];lease=WorkerLease(db,ttl=5,clock=clock or __import__('time').time);lease.acquire()
    db.put('tasks','durable',{'id':'durable','status':'running','execution_epoch':1})
    return ExecutionSession(db,'durable',1,lease,{'fixture_version':1}),lease


def test_valid_worker_lease_cannot_be_stolen_and_epochs_increase(indexed):
    now=[100.];one=WorkerLease(indexed[1],ttl=5,clock=lambda:now[0]);one.acquire()
    two=WorkerLease(indexed[1],ttl=5,clock=lambda:now[0])
    with pytest.raises(ValueError,match='worker_already_running'):two.acquire()
    now[0]=106.;two.acquire();assert two.epoch>one.epoch
    with indexed[1].connect() as conn:
        with pytest.raises(LeaseLost):one.guard(conn)


def test_stale_session_cannot_write_budget_or_cache(indexed):
    now=[100.];s,old=session(indexed,lambda:now[0]);s.save_budget({'usage':{'model_calls':1}})
    now[0]=106.;new=WorkerLease(indexed[1],ttl=5,clock=lambda:now[0]);new.acquire()
    with pytest.raises(LeaseLost):s.save_budget({'usage':{'model_calls':0}})
    assert s.load_budget()['usage']['model_calls']==1


def test_execution_epoch_is_fenced_even_with_same_worker(indexed):
    s,lease=session(indexed);raw=indexed[1].get('tasks','durable');raw['execution_epoch']=2;indexed[1].put('tasks','durable',raw)
    with pytest.raises(LeaseLost):s.save_budget({'usage':{}})
    lease.release()


def test_configuration_mismatch_is_rejected_without_overwriting_run(indexed):
    s,lease=session(indexed)
    with pytest.raises(RecoveryRejected):ExecutionSession(indexed[1],'durable',1,lease,{'fixture_version':2})
    assert s.signature=={'fixture_version':1}
    lease.release()


def test_delayed_heartbeat_can_renew_only_if_no_replacement_epoch(indexed):
    now=[100.];old=WorkerLease(indexed[1],ttl=5,clock=lambda:now[0]);old.acquire();now[0]=106.
    old.renew()
    competing=WorkerLease(indexed[1],ttl=5,clock=lambda:now[0])
    with pytest.raises(ValueError,match='worker_already_running'):competing.acquire()
    now[0]=112.;competing.acquire()
    with pytest.raises(LeaseLost):old.renew()
