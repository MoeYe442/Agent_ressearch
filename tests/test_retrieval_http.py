import json
import time
import httpx
import pytest
from repolens.config import Settings
from repolens.model_client import ProviderError
from repolens.retrieval_http import EmbeddingClient,RerankClient,MilvusStore


def config(tmp_path):
    return Settings(workspace_root=tmp_path,data_dir=tmp_path/'data',embedding_url='http://127.0.0.1:9000/v1',embedding_model='fixture-embed',embedding_dimensions=2,embedding_key='TEST_ONLY',rerank_url='http://127.0.0.1:9000/v1',rerank_model='fixture-rank',milvus_url='http://127.0.0.1:19530')


def test_embedding_reorders_provider_indices_and_keeps_usage(tmp_path):
    def handler(request):
        assert request.url.path=='/v1/embeddings' and request.headers['authorization']=='Bearer TEST_ONLY'
        return httpx.Response(200,json={'data':[{'index':1,'embedding':[0.,1.]},{'index':0,'embedding':[1.,0.]}],'usage':{'prompt_tokens':8,'total_tokens':8}})
    vectors,usage=EmbeddingClient(config(tmp_path),httpx.MockTransport(handler)).embed(['a','b'],time.monotonic()+5)
    assert vectors==[[1.,0.],[0.,1.]] and usage.input_tokens==8


@pytest.mark.parametrize('data',[
    [{'index':0,'embedding':[1.,0.]},{'index':0,'embedding':[0.,1.]}],
    [{'index':0,'embedding':[1.]}],
    [{'index':0,'embedding':[float('nan'),1.]}],
    [{'index':0,'embedding':[0.,0.]}],
    [{'index':True,'embedding':[1.,0.]}],
])
def test_embedding_rejects_invalid_vectors(tmp_path,data):
    client=EmbeddingClient(config(tmp_path),httpx.MockTransport(lambda r:httpx.Response(200,json={'data':data})))
    with pytest.raises(ProviderError):client.embed(['text'],time.monotonic()+5)


def test_embedding_missing_usage_stays_unknown(tmp_path):
    client=EmbeddingClient(config(tmp_path),httpx.MockTransport(lambda r:httpx.Response(200,json={'data':[{'index':0,'embedding':[1.,0.]}]})))
    assert client.embed(['text'],time.monotonic()+5)[1] is None


@pytest.mark.parametrize('response',[
    httpx.Response(302,headers={'location':'http://elsewhere.invalid/steal'}),
    httpx.Response(401,text='SECRET_UPSTREAM_BODY'),
    httpx.Response(200,content=b'x'*(2*1024*1024+1)),
    httpx.Response(200,json=['wrong']),
])
def test_response_bounds_redirect_and_errors_are_safe(tmp_path,response):
    calls=[]
    def handler(request):calls.append(request);return response
    with pytest.raises(ProviderError) as exc:EmbeddingClient(config(tmp_path),httpx.MockTransport(handler)).embed(['a'],time.monotonic()+5)
    assert len(calls)==1 and 'SECRET' not in str(exc.value) and 'TEST_ONLY' not in str(exc.value)


@pytest.mark.parametrize('results',[
    [{'index':2,'relevance_score':1}],
    [{'index':0,'relevance_score':1},{'index':0,'relevance_score':.5}],
    [{'index':0,'relevance_score':float('inf')}],
])
def test_rerank_rejects_bad_positions_and_scores(tmp_path,results):
    client=RerankClient(config(tmp_path),httpx.MockTransport(lambda r:httpx.Response(200,json={'results':results})))
    with pytest.raises(ProviderError):client.rank('query',['a','b'],time.monotonic()+5)


def test_rerank_returns_all_indices_in_score_order(tmp_path):
    client=RerankClient(config(tmp_path),httpx.MockTransport(lambda r:httpx.Response(200,json={'results':[{'index':0,'relevance_score':.1},{'index':1,'relevance_score':.9}],'tokens':{'input_tokens':5,'output_tokens':0}})))
    indices,usage=client.rank('query',['a','b'],time.monotonic()+5)
    assert indices==[1,0] and usage.input_tokens==5


def test_milvus_filter_is_server_scoped_and_escaped(tmp_path):
    bodies=[]
    def handler(request):bodies.append(json.loads(request.content));return httpx.Response(200,json={'code':0,'data':[]})
    store=MilvusStore(config(tmp_path),httpx.MockTransport(handler))
    assert store.search([1.,0.],'snapshot" OR true','generation','docs',20,time.monotonic()+5)==[]
    assert 'source_scope == "docs"' in bodies[0]['filter']
    assert 'snapshot_id == "snapshot\\" OR true"' in bodies[0]['filter']
    assert bodies[0]['limit']==20 and bodies[0]['consistencyLevel']=='Strong'


def test_http_configuration_rejects_nonlocal_plain_http_and_credentials(tmp_path):
    from pydantic import ValidationError
    for url in ['http://example.com/v1','https://user:secret@example.com','https://example.com?api_key=secret']:
        with pytest.raises(ValidationError):Settings(workspace_root=tmp_path,data_dir=tmp_path/'data',embedding_url=url)
