"""Offline HTTP protocol fixture. Not a semantic model or real Milvus."""
import json
import re
import httpx
from tests.scripted_model import ScriptedModel
from repolens.models import ModelTurn,ModelUsage,ToolCall
from tests.test_retrieval_http import config


class RetrievalModel(ScriptedModel):
    def complete(self,messages,tools,max_output_tokens):
        if not any(m['role']=='assistant' for m in messages):
            return ModelTurn(tool_calls=[ToolCall(id='search',name='search_text',arguments={'query':'Processor.run'})],usage=ModelUsage(input_tokens=100,output_tokens=20))
        return super().complete(messages,tools,max_output_tokens)


class RetrievalServices:
    def __init__(self, settings):
        self.settings=settings;self.records={};self.schema=None;self.calls=[];self.fail_upsert=False;self.forged=[]
        self.transport=httpx.MockTransport(self.handle)

    def handle(self, request):
        body=json.loads(request.content);path=request.url.path;self.calls.append((path,body))
        if path.endswith('/embeddings'):
            # Explicit toy lexical vectors, only for verifying integration plumbing.
            vectors=[]
            for i,text in enumerate(body['input']):
                lower=text.lower()
                vector=[1.,.01] if any(x in lower for x in ['state','save','状态','storage']) else [.01,1.]
                vectors.append({'index':i,'embedding':vector})
            return httpx.Response(200,json={'data':vectors,'usage':{'prompt_tokens':len(body['input'])*5}})
        if path.endswith('/rerank'):
            return httpx.Response(200,json={'results':[{'index':i,'relevance_score':i+.1} for i in reversed(range(len(body['documents'])))],'tokens':{'input_tokens':5,'output_tokens':0}})
        data={}
        if path.endswith('/has'):data={'has':self.schema is not None}
        elif path.endswith('/create'):self.schema=body['schema']
        elif path.endswith('/describe'):
            data={'autoId':False,'fields':[{'name':f['fieldName'],'type':f['dataType'],'primaryKey':f.get('isPrimary',False),'params':[{'key':k,'value':v} for k,v in f.get('elementTypeParams',{}).items()]} for f in self.schema['fields']], 'indexes':[{'fieldName':'vector','metricType':'COSINE'}]}
        elif path.endswith('/get_load_state'):data={'loadState':'LoadStateLoaded'}
        elif path.endswith('/upsert'):
            if self.fail_upsert:return httpx.Response(500,text='SECRET_FAILURE')
            for row in body['data']:self.records[row['chunk_id']]=row
            data={'upsertCount':len(body['data'])}
        elif path.endswith('/search'):
            if getattr(self,'fail_search',False):return httpx.Response(503,text='SECRET_SERVICE_BODY')
            conditions=dict((key,json.loads(value)) for key,value in re.findall(r'(snapshot_id|index_id|source_scope) == ("(?:[^"\\]|\\.)*")',body['filter']))
            candidates=[r for r in self.records.values() if all(r.get(k)==v for k,v in conditions.items())]
            candidates.sort(key=lambda r:(-sum(a*b for a,b in zip(r['vector'],body['data'][0])),r['chunk_id']))
            data=[{'chunk_id':r['chunk_id'],'distance':.5} for r in candidates[:body['limit']]]+self.forged
        return httpx.Response(200,json={'code':0,'data':data})

    def service(self, db):
        from repolens.retrieval import RetrievalService
        from repolens.retrieval_http import EmbeddingClient,RerankClient,MilvusStore
        return RetrievalService(self.settings,db,EmbeddingClient(self.settings,self.transport),MilvusStore(self.settings,self.transport),RerankClient(self.settings,self.transport))
