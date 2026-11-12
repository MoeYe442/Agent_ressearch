"""Bounded, explicitly configured retrieval services; no automatic paid retries."""
import asyncio
import json
import math
import time
import httpx
from repolens.model_client import ProviderError
from repolens.models import ModelUsage


def integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def usage_from(data):
    usage = data.get('usage') or data.get('tokens')
    if not isinstance(usage, dict):
        return None
    incoming = usage.get('prompt_tokens', usage.get('input_tokens'))
    outgoing = usage.get('completion_tokens', usage.get('output_tokens', 0))
    if incoming is None:
        return None
    if not integer(incoming) or not integer(outgoing) or min(incoming, outgoing) < 0:
        raise ProviderError('retrieval_usage_protocol_error')
    return ModelUsage(input_tokens=incoming, output_tokens=outgoing)


class BoundedHTTP:
    def __init__(self, url, key, label, settings, transport=None):
        self.url, self.key, self.label = url, key, label
        self.timeout, self.transport = settings.provider_timeout, transport

    def post(self, route, payload, deadline):
        return asyncio.run(self._post(route, payload, deadline))

    async def _post(self, route, payload, deadline):
        remaining = min(self.timeout, deadline-time.monotonic())
        if remaining <= 0:
            raise ProviderError('time_budget_exhausted')
        headers = {'Authorization':'Bearer '+self.key.get_secret_value()} if self.key.get_secret_value() else {}
        try:
            async with asyncio.timeout(remaining):
                async with httpx.AsyncClient(timeout=remaining, follow_redirects=False, trust_env=False, transport=self.transport) as client:
                    async with client.stream('POST', self.url+route, json=payload, headers=headers) as response:
                        if response.status_code != 200:
                            raise ProviderError(f'{self.label}_http_{response.status_code}')
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > 2*1024*1024:
                                raise ProviderError(f'{self.label}_response_too_large')
                        data = json.loads(body)
                        if not isinstance(data, dict):
                            raise ValueError('object_required')
                        return data
        except TimeoutError:
            raise ProviderError(f'{self.label}_timeout') from None
        except httpx.HTTPError:
            raise ProviderError(f'{self.label}_network_error') from None
        except (ValueError, TypeError):
            raise ProviderError(f'{self.label}_protocol_error') from None


class EmbeddingClient:
    def __init__(self, settings, transport=None):
        self.settings = settings
        self.http = BoundedHTTP(settings.embedding_url, settings.embedding_key, 'embedding', settings, transport)

    def embed(self, texts, deadline):
        if not 1 <= len(texts) <= 16 or any(not text or len(text.encode()) > 8000 for text in texts):
            raise ProviderError('embedding_input_limit')
        data = self.http.post('/embeddings', {'model':self.settings.embedding_model, 'input':texts, 'encoding_format':'float'}, deadline)
        try:
            rows = data['data']
            if not isinstance(rows, list) or len(rows) != len(texts):
                raise ValueError()
            vectors = {}
            for row in rows:
                index, vector = row['index'], row['embedding']
                if not integer(index) or index not in range(len(texts)) or index in vectors:
                    raise ValueError()
                if not isinstance(vector,list) or len(vector)!=self.settings.embedding_dimensions or not all(finite(v) for v in vector) or not any(v!=0 for v in vector):
                    raise ValueError()
                vectors[index] = vector
            return [vectors[i] for i in range(len(texts))], usage_from(data)
        except (KeyError, TypeError, ValueError):
            raise ProviderError('embedding_protocol_error') from None


class RerankClient:
    def __init__(self, settings, transport=None):
        self.settings = settings
        self.http = BoundedHTTP(settings.rerank_url, settings.rerank_key, 'rerank', settings, transport)

    def rank(self, query, texts, deadline):
        if not 1 <= len(texts) <= 20 or any(len(text.encode())>8000 for text in texts):
            raise ProviderError('rerank_input_limit')
        data = self.http.post('/rerank', {'model':self.settings.rerank_model,'query':query,'documents':texts,'top_n':len(texts),'return_documents':False}, deadline)
        try:
            rows = data['results']
            if not isinstance(rows,list) or len(rows)!=len(texts):
                raise ValueError()
            seen = set()
            for row in rows:
                i = row['index']
                if not integer(i) or i not in range(len(texts)) or i in seen or not finite(row['relevance_score']):
                    raise ValueError()
                seen.add(i)
            return [row['index'] for row in sorted(rows,key=lambda row:(-row['relevance_score'],row['index']))], usage_from(data)
        except (KeyError, TypeError, ValueError):
            raise ProviderError('rerank_protocol_error') from None


class MilvusStore:
    def __init__(self, settings, transport=None):
        self.settings = settings
        self.http = BoundedHTTP(settings.milvus_url, settings.milvus_token, 'milvus', settings, transport)

    def post(self, route, body, deadline):
        response = self.http.post('/v2/vectordb/'+route, {'collectionName':self.settings.milvus_collection, **body}, deadline)
        if type(response.get('code')) is not int or response['code'] != 0:
            raise ProviderError('milvus_operation_failed')
        if 'data' not in response:
            raise ProviderError('milvus_protocol_error')
        return response['data']

    def ensure(self, deadline):
        has = self.post('collections/has', {}, deadline)
        if not isinstance(has,dict) or type(has.get('has')) is not bool:
            raise ProviderError('milvus_protocol_error')
        if not has['has']:
            fields = [{'fieldName':'chunk_id','dataType':'VarChar','isPrimary':True,'elementTypeParams':{'max_length':'64'}}, {'fieldName':'vector','dataType':'FloatVector','elementTypeParams':{'dim':str(self.settings.embedding_dimensions)}}]
            fields.extend({'fieldName':name,'dataType':'VarChar','elementTypeParams':{'max_length':str(size)}} for name,size in [('snapshot_id',100),('index_id',32),('source_scope',8)])
            self.post('collections/create', {'schema':{'autoId':False,'enableDynamicField':False,'fields':fields},'indexParams':[{'fieldName':'vector','indexName':'vector','metricType':'COSINE','params':{'index_type':'AUTOINDEX'}}]}, deadline)
        description = self.post('collections/describe', {}, deadline)
        try:
            fields = {row['name']:row for row in description['fields']}
            dimension = {p['key']:p['value'] for p in fields['vector']['params']}['dim']
            if fields['chunk_id']['type']!='VarChar' or not fields['chunk_id']['primaryKey'] or fields['vector']['type']!='FloatVector' or int(dimension)!=self.settings.embedding_dimensions or description.get('autoId') is not False:
                raise ValueError()
            if any(fields[name]['type']!='VarChar' for name in ['snapshot_id','index_id','source_scope']):
                raise ValueError()
            if not any(i['fieldName']=='vector' and i['metricType']=='COSINE' for i in description['indexes']):
                raise ValueError()
        except (KeyError,TypeError,ValueError):
            raise ProviderError('milvus_schema_mismatch') from None
        self.post('collections/load', {}, deadline)
        until = min(deadline,time.monotonic()+self.settings.provider_timeout)
        while time.monotonic() < until:
            result = self.post('collections/get_load_state', {}, until)
            if isinstance(result,dict) and result.get('loadState')=='LoadStateLoaded':
                return
            time.sleep(.1)
        raise ProviderError('milvus_not_loaded')

    def upsert(self, records, deadline):
        result = self.post('entities/upsert', {'data':records}, deadline)
        if not isinstance(result,dict) or result.get('upsertCount')!=len(records):
            raise ProviderError('milvus_upsert_incomplete')

    def search(self, vector, snapshot_id, index_id, scope, limit, deadline):
        if scope not in {'all','code','docs'}:
            raise ValueError('invalid_source_scope')
        expression = f'snapshot_id == {json.dumps(snapshot_id)} and index_id == {json.dumps(index_id)}'
        if scope!='all':
            expression += f' and source_scope == {json.dumps(scope)}'
        rows = self.post('entities/search', {'data':[vector],'annsField':'vector','filter':expression,'limit':min(max(limit,1),20),'outputFields':['chunk_id','snapshot_id','index_id','source_scope'],'consistencyLevel':'Strong'}, deadline)
        if not isinstance(rows,list) or len(rows)>20 or any(not isinstance(row,dict) or not isinstance(row.get('chunk_id',row.get('id')),str) or not finite(row.get('distance')) for row in rows):
            raise ProviderError('milvus_protocol_error')
        return [row.get('chunk_id',row.get('id')) for row in rows]
