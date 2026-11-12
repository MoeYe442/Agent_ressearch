"""Authoritative local chunks, staged vector generations and explicit hybrid search."""
import hashlib
import json
import threading
from uuid import uuid4
from repolens.budget import BudgetManager,BudgetExceeded
from repolens.model_gateway import ModelGateway
from repolens.model_client import ProviderError
from repolens.retrieval_chunks import chunk_snapshot,fuse_rankings,CHUNKER_VERSION
from repolens.retrieval_http import EmbeddingClient,RerankClient,MilvusStore
from repolens.evidence import EvidenceStore
from repolens.document_scope import allows_path
from repolens.indexing import RepositoryIndex
from repolens.models import SearchHit


class RetrievalService:
    def __init__(self,settings,db,embedding=None,vectors=None,reranker=None):
        self.settings,self.db=settings,db
        self.embedding=embedding or EmbeddingClient(settings)
        self.vectors=vectors or MilvusStore(settings)
        self.reranker=reranker or RerankClient(settings)
        self.store,self.index=EvidenceStore(db),RepositoryIndex(db)
        self.lock=threading.RLock()
        with db.connect() as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS retrieval_chunks (id TEXT PRIMARY KEY, index_id TEXT, snapshot_id TEXT, source_scope TEXT, payload TEXT NOT NULL)')

    @property
    def configured(self):
        return bool(self.settings.embedding_url and self.settings.embedding_model and self.settings.milvus_url)

    @property
    def rerank_configured(self):
        return bool(self.settings.rerank_url and self.settings.rerank_model)

    def configuration(self):
        return {'embedding_model':self.settings.embedding_model,'dimensions':self.settings.embedding_dimensions,'chunker_version':CHUNKER_VERSION,'embedding_endpoint_hash':hashlib.sha256(self.settings.embedding_url.encode()).hexdigest(),'milvus_endpoint_hash':hashlib.sha256(self.settings.milvus_url.encode()).hexdigest(),'collection':self.settings.milvus_collection}

    def fingerprint(self):
        return hashlib.sha256(json.dumps(self.configuration(),sort_keys=True).encode()).hexdigest()

    def status(self,snapshot_id):
        self.db.get_snapshot(snapshot_id)
        try:
            head=self.db.get('retrieval_heads',snapshot_id)
            job=self.db.get('retrieval_jobs',head['id'])
            if job['fingerprint']!=self.fingerprint():
                return {'snapshot_id':snapshot_id,'status':'not_ready','error_code':'retrieval_configuration_changed'}
            return job
        except KeyError:
            return {'snapshot_id':snapshot_id,'status':'not_ready' if self.configured else 'not_configured'}

    def ready(self,snapshot_id):
        if not self.configured:
            raise ValueError('retrieval_not_configured')
        job=self.status(snapshot_id)
        snapshot=self.db.get_snapshot(snapshot_id)
        if job['status']!='ready' or snapshot.status!='ready' or job.get('manifest_hash')!=snapshot.manifest_hash:
            raise ValueError('retrieval_index_not_ready')
        return job

    def register(self,snapshot_id,idempotency_key=None):
        if not self.configured:
            raise ValueError('retrieval_not_configured')
        snapshot=self.db.get_snapshot(snapshot_id)
        if snapshot.status!='ready':
            raise ValueError('snapshot_not_ready')
        fingerprint=self.fingerprint()
        with self.lock,self.db.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            if idempotency_key:
                row=conn.execute("SELECT payload FROM entities WHERE kind='retrieval_keys' AND id=?",(idempotency_key,)).fetchone()
                if row:
                    prior=json.loads(row['payload'])
                    if prior['snapshot_id']!=snapshot_id or prior['fingerprint']!=fingerprint:
                        raise ValueError('idempotency_conflict')
                    return json.loads(conn.execute("SELECT payload FROM entities WHERE kind='retrieval_jobs' AND id=?",(prior['id'],)).fetchone()['payload'])
            old=self.status(snapshot_id)
            if old['status'] in {'queued','building','ready'}:
                job=old
            else:
                job={'id':uuid4().hex,'snapshot_id':snapshot_id,'manifest_hash':snapshot.manifest_hash,'fingerprint':fingerprint,'configuration':self.configuration(),'status':'queued','usage':None,'role_usage':{},'error_code':None,'chunks':0}
                conn.execute("INSERT INTO entities VALUES ('retrieval_jobs',?,?)",(job['id'],json.dumps(job)))
                conn.execute("INSERT OR REPLACE INTO entities VALUES ('retrieval_heads',?,?)",(snapshot_id,json.dumps({'id':job['id']})))
            if idempotency_key:
                conn.execute("INSERT INTO entities VALUES ('retrieval_keys',?,?)",(idempotency_key,json.dumps({'id':job['id'],'snapshot_id':snapshot_id,'fingerprint':fingerprint})))
            return job

    def interrupt_unfinished(self):
        for job in self.db.all('retrieval_jobs'):
            if job['status'] in {'queued','building'}:
                job.update(status='failed',error_code='interrupted_retrieval_index')
                self.db.put('retrieval_jobs',job['id'],job)

    def build(self,job_id,cancelled=lambda:False):
        with self.lock:
            job=self.db.get('retrieval_jobs',job_id)
            if job['status']!='queued':
                return job
            job['status']='building';self.db.put('retrieval_jobs',job_id,job)
        budget=BudgetManager(self.settings)
        def emit(event):
            job.update(usage=budget.snapshot().model_dump(),role_usage=budget.roles())
            self.db.put('retrieval_jobs',job_id,job)
        gateway=ModelGateway(None,budget,emit,cancelled,job_id)
        try:
            if job['fingerprint']!=self.fingerprint():
                raise ValueError('retrieval_configuration_changed')
            gateway.check()
            chunks=chunk_snapshot(job['snapshot_id'],self.store)
            if not chunks or len(chunks)>10000:
                raise ValueError('retrieval_chunk_limit')
            self.vectors.ensure(budget.deadline)
            staged=[];offset=0
            while offset<len(chunks):
                gateway.check()
                batch=[];size=0
                while offset<len(chunks) and len(batch)<16:
                    row=chunks[offset]
                    if batch and size+len(row['content'].encode())>24000:
                        break
                    batch.append(row);size+=len(row['content'].encode());offset+=1
                texts=[row['content'] for row in batch]
                bound=len(json.dumps(texts,ensure_ascii=False).encode())+1024
                vectors=gateway.external(lambda:self.embedding.embed(texts,budget.deadline),bound,'embedding','index')
                records=[]
                for row,vector in zip(batch,vectors):
                    chunk={**row,'id':hashlib.sha256((job_id+row['id']).encode()).hexdigest(),'index_id':job_id}
                    staged.append(chunk)
                    records.append({'chunk_id':chunk['id'],'vector':vector,'snapshot_id':job['snapshot_id'],'index_id':job_id,'source_scope':row['source_scope']})
                gateway.check();self.vectors.upsert(records,budget.deadline);gateway.check()
                job['chunks']=len(staged);emit(None)
            job.update(status='ready',usage=budget.snapshot().model_dump(),role_usage=budget.roles())
            with self.db.connect() as conn:
                conn.execute('BEGIN IMMEDIATE')
                for row in staged:
                    conn.execute('INSERT INTO retrieval_chunks VALUES (?,?,?,?,?)',(row['id'],job_id,job['snapshot_id'],row['source_scope'],json.dumps(row,ensure_ascii=False)))
                conn.execute("UPDATE entities SET payload=? WHERE kind='retrieval_jobs' AND id=?",(json.dumps(job),job_id))
        except Exception as exc:
            reason=exc.code if isinstance(exc,ProviderError) else str(exc) if isinstance(exc,(ValueError,BudgetExceeded)) else 'retrieval_index_failed'
            job.update(status='failed',error_code=reason,usage=budget.snapshot().model_dump(),role_usage=budget.roles())
            self.db.put('retrieval_jobs',job_id,job)
        return job

    def search(self,query,context,gateway,*,rerank=False,limit=20):
        job=self.ready(context.snapshot_id)
        if rerank and not self.rerank_configured:
            raise ValueError('rerank_not_configured')
        gateway.check()
        bound=len(query.encode())+1024
        vectors=gateway.external(lambda:self.embedding.embed([query],gateway.budget.deadline),bound,'embedding',context.task_id)
        gateway.check()
        ids=self.vectors.search(vectors[0],context.snapshot_id,job['id'],context.source_scope,20,gateway.budget.deadline)
        vector_hits=[]
        with self.db.connect() as conn:
            for chunk_id in ids:
                record=conn.execute('SELECT payload FROM retrieval_chunks WHERE id=? AND index_id=? AND snapshot_id=?',(chunk_id,job['id'],context.snapshot_id)).fetchone()
                if record is None:
                    raise ValueError('retrieval_foreign_chunk')
                chunk=json.loads(record['payload'])
                if not allows_path(chunk['path'],context.source_scope):
                    raise ValueError('retrieval_foreign_chunk')
                evidence=self.store.read_evidence(context.snapshot_id,chunk['path'],chunk['start_line'],chunk['end_line'])
                if evidence.content_hash!=chunk['content_hash']:
                    raise ValueError('retrieval_chunk_hash_mismatch')
                vector_hits.append(SearchHit(path=chunk['path'],symbol=chunk['parent_symbol'],start_line=chunk['start_line'],end_line=chunk['end_line']))
        keyword=self.index.search_text(context.snapshot_id,query,20,scope=context.source_scope)
        symbols=self.index.search_symbols(context.snapshot_id,query,20,scope=context.source_scope)
        symbols=[hit.model_copy(update={'end_line':min(hit.end_line,hit.start_line+119)}) for hit in symbols]
        hits=fuse_rankings({'keyword':keyword,'symbols':symbols,'vector':vector_hits},20)
        excerpts=[self.store.read_evidence(context.snapshot_id,h.path,h.start_line,h.end_line).excerpt for h in hits]
        if rerank and hits:
            bound=len(query.encode())+sum(len(text.encode()) for text in excerpts)+1024
            order=gateway.external(lambda:self.reranker.rank(query,excerpts,gateway.budget.deadline),bound,'rerank',context.task_id,output_bound=128)
            hits=[hits[i] for i in order]
        gateway.check()
        return hits[:min(max(limit,1),20)]
