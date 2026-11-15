"""Bounded anonymous HTTPS GETs; DNS pins reach only checked public numeric IPs."""
import asyncio
from concurrent.futures import Future
import ipaddress
import socket
import ssl
import threading
import time
from urllib.parse import urlsplit,urlunsplit,urljoin
import certifi
import httpcore
import httpx
from repolens.github_network import ResponseStream,core_errors


class DocumentError(ValueError):pass


def canonical_url(value,hosts):
    try:
        if not isinstance(value,str) or len(value)>2048 or any(ord(c)<=32 or ord(c)==127 for c in value) or '\\' in value:raise ValueError()
        parts=urlsplit(value);host=(parts.hostname or '').encode('idna').decode().lower()
        if parts.scheme!='https' or parts.username is not None or parts.password is not None or parts.port not in {None,443}:raise ValueError()
        if not hosts:raise DocumentError('document_fetch_disabled')
        if host not in hosts:raise DocumentError('document_host_denied')
        try:ipaddress.ip_address(host)
        except ValueError:pass
        else:raise ValueError()
        return str(httpx.URL(urlunsplit(('https',host,parts.path or '/',parts.query,''))))
    except DocumentError:raise
    except (ValueError,UnicodeError,httpx.InvalidURL):raise DocumentError('invalid_document_url') from None


_dns_lock=threading.Lock()
_dns_jobs={}


async def resolve(host):
    with _dns_lock:
        job=_dns_jobs.get(host)
        if job is None or job.done():
            for old in list(_dns_jobs):
                if _dns_jobs[old].done():_dns_jobs.pop(old)
            if len(_dns_jobs)>=32:raise DocumentError('document_dns_busy')
            job=Future();_dns_jobs[host]=job
            def lookup():
                try:job.set_result(list({item[4][0] for item in socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)}))
                except BaseException:job.set_exception(DocumentError('document_dns_failed'))
            threading.Thread(target=lookup,daemon=True,name='repolens-document-dns').start()
    values=await asyncio.shield(asyncio.wrap_future(job))
    if not values or len(values)>32:raise DocumentError('document_network_destination')
    for address in values:
        ip=ipaddress.ip_address(address)
        if not ip.is_global or ip.is_multicast:raise DocumentError('document_network_destination')
    return values


class Backend(httpcore.AsyncNetworkBackend):
    def __init__(self,host,addresses):self.host,self.addresses,self.inner=host,addresses,httpcore.AnyIOBackend()
    async def connect_tcp(self,host,port,timeout=None,local_address=None,socket_options=None):
        if host!=self.host or port!=443:raise DocumentError('document_network_destination')
        end=time.monotonic()+(timeout or 15);failure=None
        for index,address in enumerate(self.addresses):
            remaining=end-time.monotonic()
            if remaining<=0:raise httpcore.ConnectTimeout('document_timeout')
            try:return await self.inner.connect_tcp(address,443,timeout=remaining/(len(self.addresses)-index),socket_options=socket_options)
            except (httpcore.NetworkError,httpcore.TimeoutException) as exc:failure=exc
        raise failure
    async def connect_unix_socket(self,*args,**kwargs):raise DocumentError('document_network_destination')
    async def sleep(self,seconds):await asyncio.sleep(seconds)


class Transport(httpx.AsyncBaseTransport):
    def __init__(self,context,host,addresses):
        self.pool=httpcore.AsyncConnectionPool(ssl_context=context,network_backend=Backend(host,addresses),max_connections=1,max_keepalive_connections=0)
    async def handle_async_request(self,request):
        core=httpcore.Request(method=request.method,url=httpcore.URL(scheme=request.url.raw_scheme,host=request.url.raw_host,port=request.url.port,target=request.url.raw_path),headers=request.headers.raw,content=request.stream,extensions=request.extensions)
        with core_errors():response=await self.pool.handle_async_request(core)
        return httpx.Response(response.status,headers=response.headers,stream=ResponseStream(response.stream),extensions=response.extensions)
    async def aclose(self):await self.pool.aclose()


PAGE_TYPES={'text/html','application/xhtml+xml','text/plain','text/markdown'}
RESOURCE_TYPES=PAGE_TYPES|{'application/javascript','text/javascript','application/x-javascript','text/css','application/json'}


class DocumentFetcher:
    def __init__(self,settings,deadline,cancelled=lambda:False):
        self.settings,self.deadline,self.cancelled=settings,deadline,cancelled
        self.context=ssl.create_default_context(cafile=certifi.where())
        self.requests=0;self.bytes=0
    def check(self):
        if self.cancelled():raise DocumentError('document_cancelled')
        if time.monotonic()>=self.deadline:raise DocumentError('document_timeout')
    def fetch(self,url,*,resource=False):
        self.check()
        try:return asyncio.run(self._fetch(url,resource))
        except (TimeoutError,httpx.TimeoutException):raise DocumentError('document_timeout') from None
        except (httpx.HTTPError,OSError):raise DocumentError('document_network_error') from None
    async def _fetch(self,url,resource):
        async with asyncio.timeout(max(.001,self.deadline-time.monotonic())):
            for redirect in range(4):
                self.check();self.requests+=1
                if self.requests>20:raise DocumentError('document_request_limit')
                url=canonical_url(url,self.settings.document_hosts);host=urlsplit(url).hostname
                addresses=await resolve(host)
                transport=Transport(self.context,host,addresses)
                async with httpx.AsyncClient(transport=transport,trust_env=False,follow_redirects=False,timeout=max(.001,self.deadline-time.monotonic()),headers={'Accept-Encoding':'identity','User-Agent':'RepoLens/0.7 document-reader'}) as client:
                    async with client.stream('GET',url) as response:
                        if response.status_code in {301,302,303,307,308}:
                            location=response.headers.get('location','')
                            if not location or redirect==3:raise DocumentError('document_redirect_limit')
                            url=canonical_url(urljoin(url,location),self.settings.document_hosts);continue
                        if response.status_code!=200:raise DocumentError('document_http_error')
                        content_type=response.headers.get('content-type','').split(';',1)[0].strip().lower()
                        if content_type not in (RESOURCE_TYPES if resource else PAGE_TYPES):raise DocumentError('document_content_type')
                        if response.headers.get('content-encoding','identity').lower()!='identity':raise DocumentError('document_encoding_denied')
                        chunks=[];size=0
                        async for chunk in response.aiter_raw():
                            self.check();size+=len(chunk);self.bytes+=len(chunk)
                            if size>self.settings.document_max_bytes or self.bytes>8*1024*1024:raise DocumentError('document_size_limit')
                            chunks.append(chunk)
                        return {'url':url,'content_type':content_type,'body':b''.join(chunks)}
