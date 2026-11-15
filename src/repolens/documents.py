"""Explicit collection jobs and immutable paragraph evidence, bound to one snapshot."""
import hashlib
import re
import time
from datetime import datetime,timezone
from uuid import uuid4
from repolens.document_network import canonical_url,DocumentFetcher,DocumentError
from repolens.document_text import extract
from repolens.execution_store import digest,LeaseLost
from repolens.models import Evidence


def utcnow():return datetime.now(timezone.utc).isoformat()


class DocumentStore:
    def __init__(self,db):self.db=db
    def ready(self,document_id,snapshot_id):
        row=self.db.get('web_documents',document_id)
        if row['snapshot_id']!=snapshot_id:raise ValueError('document_snapshot_mismatch')
        if row['status']!='ready':raise ValueError('document_not_ready')
        if row.get('content_hash')!=digest(row.get('paragraphs')):raise ValueError('document_integrity_error')
        return row
    def evidence(self,snapshot_id,document_id,start_line=1,end_line=None):
        row=self.ready(document_id,snapshot_id);paragraphs=row['paragraphs']
        if end_line is None:
            end_line=min(len(paragraphs),start_line+19)
            while end_line>start_line and len('\n'.join(paragraphs[start_line-1:end_line]).encode())>24000:end_line-=1
        if start_line<1 or end_line<start_line or end_line>len(paragraphs) or end_line-start_line>=40:raise ValueError('invalid_document_range')
        excerpt='\n'.join(paragraphs[start_line-1:end_line])
        if len(excerpt.encode())>24000:raise ValueError('document_excerpt_limit')
        checksum=hashlib.sha256(excerpt.encode()).hexdigest()
        evidence_id=digest({'snapshot':snapshot_id,'document':document_id,'range':[start_line,end_line],'hash':checksum})
        item=Evidence(id=evidence_id,snapshot_id=snapshot_id,path='web:'+document_id,start_line=start_line,end_line=end_line,excerpt=excerpt,content_hash=checksum,source_type='web_document',document_id=document_id,url=row['final_url'],title=row['title'],collected_at=row['collected_at'],declared_version=row['declared_version'],version_match='unverified')
        item.collection_limitations=row['limitations']
        self.db.put('evidence',item.id,item)
        return item
    def get_evidence(self,item):
        fresh=self.evidence(item.snapshot_id,item.document_id,item.start_line,item.end_line)
        if item!=fresh:raise ValueError('evidence_integrity_error')
        return item
    def summaries(self,document_ids,snapshot_id):
        return [{key:row.get(key) for key in ['id','title','final_url','collected_at','declared_version','version_match','content_hash','limitations']} for row in (self.ready(key,snapshot_id) for key in document_ids)]
    def search(self,document_ids,snapshot_id,query,limit):
        terms=re.findall(r'\w+',query.casefold())[:20]
        if not terms:return []
        candidates=[]
        for document_id in document_ids:
            row=self.ready(document_id,snapshot_id)
            for position,paragraph in enumerate(row['paragraphs'],1):
                score=sum(paragraph.casefold().count(term) for term in terms)
                if score:candidates.append((score,document_id,position))
        candidates.sort(key=lambda item:(-item[0],item[1],item[2]))
        return [self.evidence(snapshot_id,document_id,position,position) for _,document_id,position in candidates[:min(limit,3)]]


class DocumentService:
    def __init__(self,settings,db):self.settings,self.db=settings,db
    def register(self,snapshot_id,url,render=False,declared_version=None,idempotency_key=None):
        url=canonical_url(url,self.settings.document_hosts)
        descriptor={'snapshot_id':snapshot_id,'url':url,'render':render,'declared_version':declared_version}
        with self.db.atomic():
            if self.db.get_snapshot(snapshot_id).status!='ready':raise ValueError('snapshot_not_ready')
            if idempotency_key:
                try:
                    prior=self.db.get('document_keys',idempotency_key)
                    if prior['descriptor']!=descriptor:raise ValueError('idempotency_conflict')
                    return self.db.get('web_documents',prior['id'])
                except KeyError:pass
            if sum(row['snapshot_id']==snapshot_id for row in self.db.all('web_documents'))>=100:raise ValueError('document_collection_limit')
            row={**descriptor,'id':uuid4().hex,'status':'queued','cancel_requested':False,'created_at':utcnow(),'collected_at':None,'final_url':None,'title':'','content_hash':None,'paragraphs':[],'error_code':None,'limitations':[],'version_match':'unverified'}
            self.db.put('web_documents',row['id'],row)
            if idempotency_key:self.db.put('document_keys',idempotency_key,{'descriptor':descriptor,'id':row['id']})
            return row
    def cancel(self,document_id):
        with self.db.atomic():
            row=self.db.get('web_documents',document_id)
            if row['status'] in {'queued','running'}:
                row['cancel_requested']=True
                if row['status']=='queued':row['status']='cancelled'
                self.db.put('web_documents',document_id,row)
            return row
    def build(self,document_id,stopping=lambda:False):
        with self.db.atomic():
            row=self.db.get('web_documents',document_id)
            if row['status']!='queued':return row
            row['status']='running';self.db.put('web_documents',document_id,row)
        def cancelled():return stopping() or self.db.get('web_documents',document_id)['cancel_requested']
        try:
            deadline=time.monotonic()+self.settings.document_timeout
            fetcher=DocumentFetcher(self.settings,deadline,cancelled)
            response=fetcher.fetch(row['url']);title,paragraphs=extract(response['body'],response['content_type'])
            limitations=[]
            if row['render']:
                try:
                    from repolens.document_render import render_document
                    rendered=render_document(self.settings,fetcher,response)
                    title,paragraphs=extract(rendered.encode(),'text/plain')
                    title=rendered.splitlines()[0][:300] if rendered else title
                except DocumentError as exc:limitations.append('static_fallback:'+str(exc))
            if not paragraphs:raise DocumentError('document_text_empty')
            if len('\n'.join(paragraphs))<120:limitations.append('document_text_short')
            if cancelled():raise DocumentError('document_cancelled')
            row.update(status='ready',final_url=response['url'],title=title,collected_at=utcnow(),paragraphs=paragraphs,content_hash=digest(paragraphs),raw_hash=hashlib.sha256(response['body']).hexdigest(),limitations=limitations,requests=fetcher.requests,download_bytes=fetcher.bytes)
        except LeaseLost:raise
        except Exception as exc:
            row.update(status='failed',error_code=str(exc) if isinstance(exc,DocumentError) else 'document_collection_failed')
        with self.db.atomic():
            current=self.db.get('web_documents',document_id)
            if current['status']!='running':return current
            if current['cancel_requested']:row.update(status='cancelled',cancel_requested=True,paragraphs=[],content_hash=None)
            self.db.put('web_documents',document_id,row)
        return row
