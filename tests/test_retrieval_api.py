import time
from fastapi.testclient import TestClient
from repolens.api import create_app
from tests.retrieval_services import RetrievalServices,RetrievalModel
from tests.test_retrieval_http import config
from tests.scripted_model import ScriptedModel
from tests.test_collaborative_api import wait


def wait_index(client,snapshot_id):
    for _ in range(400):
        result=client.get('/repositories/'+snapshot_id+'/retrieval-index').json()
        if result['status'] not in {'queued','building'}:return result
        time.sleep(.01)
    raise AssertionError('index never finished')


def test_unconfigured_hybrid_is_explicit_and_keyword_still_works(indexed):
    with TestClient(create_app(indexed[0],ScriptedModel()),client=('127.0.0.1',1)) as client:
        sid=indexed[2].id
        assert client.get('/health').json()['retrieval_configured'] is False
        assert client.post('/repositories/'+sid+'/retrieval-index',json={}).status_code==409
        response=client.post('/tasks',json={'snapshot_id':sid,'question':'status','retrieval_mode':'hybrid'})
        assert response.status_code==409 and response.json()['error_code']=='retrieval_not_configured'
        task=client.post('/tasks',json={'snapshot_id':sid,'question':'status'}).json()
        assert wait(client,task['id'])['retrieval_mode']=='keyword'


def test_index_api_search_and_hybrid_task_share_bounded_usage(indexed):
    settings=config(indexed[0].data_dir.parent).model_copy(update={'test_environment':True})
    fixtures=RetrievalServices(settings)
    with TestClient(create_app(settings,RetrievalModel(),retrieval_factory=lambda s,db:fixtures.service(db)),client=('127.0.0.1',1)) as client:
        sid=indexed[2].id
        missing=client.post('/tasks',json={'snapshot_id':sid,'question':'status','retrieval_mode':'hybrid'})
        assert missing.status_code==409 and missing.json()['error_code']=='retrieval_index_not_ready'
        first=client.post('/repositories/'+sid+'/retrieval-index',json={'idempotency_key':'index-key'})
        assert first.status_code==202
        built=wait_index(client,sid);assert built['status']=='ready'
        assert client.post('/repositories/'+sid+'/retrieval-index',json={'idempotency_key':'index-key'}).json()['id']==built['id']
        response=client.post('/repositories/'+sid+'/search',json={'query':'StateStore','retrieval_mode':'hybrid','rerank':True,'scope':'code'})
        assert response.status_code==200
        result=response.json();assert result['hits'] and result['usage']['model_calls']==2
        assert all(h['evidence']['snapshot_id']==sid and h['path']!='README.md' for h in result['hits'])
        body={'snapshot_id':sid,'question':'Where is status saved?','retrieval_mode':'hybrid','rerank':True,'idempotency_key':'query-key'}
        task=client.post('/tasks',json=body).json();done=wait(client,task['id'])
        assert done['status']=='succeeded' and done['retrieval_mode']=='hybrid' and done['rerank']
        assert done['retrieval_configuration']['index_id']==built['id']
        assert done['usage']['model_calls']>=5
        assert client.post('/tasks',json={**body,'retrieval_mode':'keyword','rerank':False}).status_code==409
        assert client.post('/tasks',json={**body,'rerank':False}).status_code==409


def test_keyword_rerank_is_validation_error(indexed):
    with TestClient(create_app(indexed[0]),client=('127.0.0.1',1)) as client:
        assert client.post('/tasks',json={'snapshot_id':indexed[2].id,'question':'status','rerank':True}).status_code==422
