import pytest
from repolens.retrieval import RetrievalService
from repolens.budget import BudgetManager
from repolens.model_gateway import ModelGateway
from repolens.models import ToolContext
from tests.retrieval_services import RetrievalServices
from tests.test_retrieval_http import config


def prepared(indexed):
    settings=config(indexed[0].data_dir.parent)
    fixture=RetrievalServices(settings);service=fixture.service(indexed[1])
    job=service.register(indexed[2].id,'build-key');service.build(job['id'])
    assert service.status(indexed[2].id)['status']=='ready'
    return settings,fixture,service


def gateway(settings):
    return ModelGateway(None,BudgetManager(settings),lambda e:None,lambda:False,'retrieval-test')


def test_staged_index_and_hybrid_scope_verified_from_snapshot(indexed):
    settings,fixture,service=prepared(indexed)
    g=gateway(settings)
    context=ToolContext(snapshot_id=indexed[2].id,task_id='t',source_scope='docs')
    hits=service.search('StateStore saves status',context,g,rerank=True)
    assert hits and all(hit.path=='README.md' for hit in hits)
    assert g.budget.snapshot().model_calls==2
    assert {'embedding','rerank'}==set(g.budget.roles())
    job=service.status(indexed[2].id)
    assert job['manifest_hash']==indexed[2].manifest_hash and job['usage']['model_calls']>0


def test_failed_index_is_never_published_or_retried_implicitly(indexed):
    settings=config(indexed[0].data_dir.parent);fixture=RetrievalServices(settings);fixture.fail_upsert=True;service=fixture.service(indexed[1])
    job=service.register(indexed[2].id,'stable-key');service.build(job['id'])
    assert service.status(indexed[2].id)['status']=='failed'
    calls=len(fixture.calls)
    assert service.register(indexed[2].id,'stable-key')['id']==job['id'] and len(fixture.calls)==calls
    with pytest.raises(ValueError,match='retrieval_index_not_ready'):service.ready(indexed[2].id)


def test_forged_milvus_chunk_cannot_contribute_evidence(indexed):
    settings,fixture,service=prepared(indexed)
    fixture.forged=[{'chunk_id':'foreign-snapshot-chunk','distance':1.}]
    with pytest.raises(ValueError,match='retrieval_foreign_chunk'):
        service.search('status',ToolContext(snapshot_id=indexed[2].id,task_id='t'),gateway(settings))


def test_configuration_change_invalidates_ready_generation(indexed):
    settings,fixture,service=prepared(indexed)
    changed=RetrievalService(settings.model_copy(update={'embedding_model':'different'}),indexed[1])
    with pytest.raises(ValueError,match='retrieval_index_not_ready'):changed.ready(indexed[2].id)


def test_index_registration_is_idempotent_and_rejects_key_reuse(indexed):
    settings,fixture,service=prepared(indexed)
    old=service.status(indexed[2].id)
    assert service.register(indexed[2].id,'build-key')['id']==old['id']
    assert service.register(indexed[2].id,'other-key')['id']==old['id']
    assert len([p for p,b in fixture.calls if p.endswith('/embeddings')])==old['usage']['model_calls']
    from repolens.repositories import create_snapshot
    from repolens.indexing import build_index
    other=create_snapshot(indexed[2].source,settings);indexed[1].put_snapshot(other);build_index(other,indexed[1])
    with pytest.raises(ValueError,match='idempotency_conflict'):service.register(other.id,'build-key')


def test_restart_marks_unfinished_index_interrupted(indexed):
    settings=config(indexed[0].data_dir.parent);service=RetrievalServices(settings).service(indexed[1])
    job=service.register(indexed[2].id,'key')
    service.interrupt_unfinished()
    assert service.status(indexed[2].id)['status']=='failed' and service.status(indexed[2].id)['error_code']=='interrupted_retrieval_index'


def test_source_tampering_is_not_hidden_by_vector_store(indexed):
    settings,fixture,service=prepared(indexed)
    (indexed[2].root/'README.md').write_text('tampered')
    with pytest.raises(ValueError,match='snapshot_integrity_error'):
        service.search('status',ToolContext(snapshot_id=indexed[2].id,task_id='t',source_scope='docs'),gateway(settings))


def test_auxiliary_provider_failure_is_structured_tool_error(indexed):
    from repolens.tools import ToolRegistry
    from repolens.model_client import ProviderError
    settings,fixture,service=prepared(indexed)
    def broken(*args,**kwargs):raise ProviderError('embedding_http_503')
    service.embedding.embed=broken
    registry=ToolRegistry(indexed[1],retrieval=service)
    result=registry.invoke('search_text',{'query':'status'},ToolContext(snapshot_id=indexed[2].id,task_id='t',retrieval_mode='hybrid'),gateway=gateway(settings))
    assert result.status=='error' and result.error_code=='embedding_http_503' and not result.evidence_ids
