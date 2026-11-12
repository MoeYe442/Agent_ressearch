import time
from pathlib import Path
from types import SimpleNamespace
import httpx
import pytest
from fastapi.testclient import TestClient
from repolens.api import create_app
from repolens.agent import AgentRunner
from repolens.models import ToolContext
from repolens.tools import ToolRegistry
from repolens.model_client import ProviderError
from repolens.budget import BudgetExceeded
from repolens.retrieval_chunks import chunk_snapshot
from repolens.retrieval_http import MilvusStore
from repolens.repositories import create_snapshot
from repolens.indexing import build_index
from tests.test_retrieval import prepared,gateway
from tests.test_retrieval_http import config
from tests.retrieval_services import RetrievalServices,RetrievalModel
from tests.server import running_app
from eval.retrieval import run_retrieval


def test_hybrid_failure_cannot_be_hidden_by_valid_read_fallback(indexed):
    settings,fixture,service=prepared(indexed)
    def broken(*args,**kwargs):raise ProviderError('embedding_http_503')
    service.embedding.embed=broken
    runner=AgentRunner(RetrievalModel(),ToolRegistry(indexed[1],retrieval=service),settings)
    result=runner.run('status',ToolContext(snapshot_id=indexed[2].id,task_id='t',retrieval_mode='hybrid'),lambda e:None,lambda:False)
    assert result.claims and result.status=='partial'
    assert any('embedding_http_503' in reason for reason in result.limitations)


def test_missing_remote_vectors_invalidate_generation_and_allow_explicit_retry(indexed):
    settings,fixture,service=prepared(indexed);old=service.ready(indexed[2].id);fixture.records.clear()
    with pytest.raises(ValueError,match='retrieval_vector_index_missing'):
        service.search('status',ToolContext(snapshot_id=indexed[2].id,task_id='t'),gateway(settings))
    assert service.status(indexed[2].id)['status']=='failed'
    assert service.register(indexed[2].id,'build-key')['id']==old['id']
    new=service.register(indexed[2].id,'explicit-retry');assert new['id']!=old['id']
    service.build(new['id']);assert service.ready(indexed[2].id)['id']==new['id']


def test_rerank_uses_bounded_source_windows_for_legacy_fts_spans(indexed):
    settings=config(indexed[0].data_dir.parent);source=Path(indexed[2].source)
    (source/'long.md').write_text(''.join('state '+'x'*140+'\n' for _ in range(60)),encoding='utf-8')
    snap=create_snapshot(source,settings);indexed[1].put_snapshot(snap);build_index(snap,indexed[1])
    fixture=RetrievalServices(settings);service=fixture.service(indexed[1]);job=service.register(snap.id,'long');service.build(job['id'])
    g=gateway(settings);hits=service.search('state',ToolContext(snapshot_id=snap.id,task_id='t'),g,rerank=True)
    assert hits and g.budget.snapshot().model_calls==2
    calls=[body for path,body in fixture.calls if path.endswith('/rerank')]
    assert len(calls)==1 and all(len(text.encode())<=8000 for text in calls[0]['documents'])
    assert all(len(service.store.read_evidence(snap.id,h.path,h.start_line,h.end_line).excerpt.encode())<=8000 for h in hits)


@pytest.mark.parametrize('issue',['short_id','extra_required'])
def test_incompatible_collection_rejected_before_embedding(indexed,issue):
    settings,fixture,service=prepared(indexed)
    if issue=='short_id':fixture.schema['fields'][0]['elementTypeParams']['max_length']='16'
    else:fixture.schema['fields'].append({'fieldName':'required_vector','dataType':'FloatVector','elementTypeParams':{'dim':'2'}})
    fixture.calls.clear()
    # Simulate an explicit new generation after operator identifies a failed cache.
    old=service.ready(indexed[2].id);old['status']='failed';indexed[1].put('retrieval_jobs',old['id'],old)
    job=service.register(indexed[2].id,'new-attempt');service.build(job['id'])
    assert service.status(indexed[2].id)['status']=='failed'
    assert service.status(indexed[2].id)['error_code']=='milvus_schema_mismatch'
    assert not any(path.endswith('/embeddings') for path,body in fixture.calls)


def test_failed_query_keeps_usage_reason_generation_and_rerank_model(indexed):
    settings=config(indexed[0].data_dir.parent).model_copy(update={'test_environment':True});fixture=RetrievalServices(settings);fixture.fail_search=True
    with running_app(settings,RetrievalModel(),retrieval_factory=lambda s,db:fixture.service(db)) as url:
        result=run_retrieval(url,[{'id':'x','repository':indexed[2].source,'query':'status','expected_evidence':[]}])
    failed=[row for row in result['results'] if row['configuration']!='keyword']
    assert len(failed)==2
    for row in failed:
        assert row['status']=='failed' and row['error_code']=='milvus_http_503'
        assert row['usage']['model_calls']==1 and row['usage']['input_tokens']==5 and not row['usage']['estimated']
        assert row['role_usage']['embedding']['model_calls']==1
        assert row['backend_configuration']['index_id']==row['index_id']
    assert failed[1]['backend_configuration']['rerank_model']=='fixture-rank'


def test_chunk_limit_stops_inside_first_file_without_reading_more():
    reads=[]
    class Store:
        db=SimpleNamespace(get_snapshot=lambda sid:SimpleNamespace(manifest={'a.md':'x','b.md':'y'}))
        def file_text(self,sid,path):reads.append(path);return ''.join(f'# Heading {i}\nbody\n' for i in range(10002))
    with pytest.raises(ValueError,match='retrieval_chunk_limit'):chunk_snapshot('s',Store())
    assert reads==['a.md']


def test_chunk_cancel_is_checked_during_generation():
    reads=[]
    class Store:
        db=SimpleNamespace(get_snapshot=lambda sid:SimpleNamespace(manifest={'a.md':'x','b.md':'y'}))
        def file_text(self,sid,path):reads.append(path);return '# Header\nbody\n'*100
    def check():
        if reads:raise BudgetExceeded('cancelled')
    with pytest.raises(BudgetExceeded,match='cancelled'):chunk_snapshot('s',Store(),check=check)
    assert reads==['a.md']


@pytest.mark.parametrize('count',[True,1.0])
def test_malformed_upsert_ack_cannot_publish_success(tmp_path,count):
    store=MilvusStore(config(tmp_path),httpx.MockTransport(lambda r:httpx.Response(200,json={'code':0,'data':{'upsertCount':count}})))
    with pytest.raises(ProviderError,match='milvus_upsert_incomplete'):store.upsert([{'chunk_id':'x'}],time.monotonic()+5)


def test_invalid_query_is_rejected_before_auxiliary_reservation(indexed):
    settings,fixture,service=prepared(indexed);g=gateway(settings)
    with pytest.raises(ProviderError,match='embedding_input_limit'):
        service.search('x'*8001,ToolContext(snapshot_id=indexed[2].id,task_id='t'),g)
    assert g.budget.snapshot().model_calls==0 and not g.budget.pending


def test_genuinely_empty_scope_does_not_invalidate_generation(indexed):
    settings=config(indexed[0].data_dir.parent);source=Path(indexed[2].source)
    (source/'README.md').unlink()
    snap=create_snapshot(source,settings);indexed[1].put_snapshot(snap);build_index(snap,indexed[1])
    fixture=RetrievalServices(settings);service=fixture.service(indexed[1]);job=service.register(snap.id,'code-only');service.build(job['id'])
    assert service.search('status',ToolContext(snapshot_id=snap.id,task_id='t',source_scope='docs'),gateway(settings))==[]
    assert service.ready(snap.id)['status']=='ready'
