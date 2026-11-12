import asyncio
import httpcore
import httpx
import pytest
from repolens.github_network import PinnedBackend, GitHubTransport, GitHubError


def test_connection_uses_checked_ip_while_preserving_sni_and_host():
    class Stream(httpcore.AsyncNetworkStream):
        def __init__(self):
            self.sni=None
            self.sent=b""
            self.reads=0
        async def read(self,*args,**kwargs):
            self.reads+=1
            return b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}" if self.reads==1 else b""
        async def write(self,data,**kwargs):
            self.sent+=data
        async def start_tls(self,ssl_context,server_hostname=None,timeout=None):
            self.sni=server_hostname
            return self
        async def aclose(self):
            pass
        def get_extra_info(self,key):
            return ("140.82.112.4",443) if key=="server_addr" else None
    class Backend(httpcore.AsyncNetworkBackend):
        def __init__(self):
            self.host=None
            self.stream=Stream()
        async def connect_tcp(self,host,port,**kwargs):
            self.host=host
            return self.stream
    backend=Backend()
    pins={"api.github.com":["140.82.112.4"]}
    transport=GitHubTransport(None,pins,backend=backend)
    async def request():
        async with httpx.AsyncClient(transport=transport,trust_env=False) as client:
            return await client.get("https://api.github.com/repos/example/demo")
    result=asyncio.run(request())
    assert result.json()=={}
    assert backend.host=="140.82.112.4"
    assert backend.stream.sni=="api.github.com"
    assert b"Host: api.github.com\r\n" in backend.stream.sent


def test_pinned_backend_refuses_unchecked_or_private_addresses():
    async def attempt(pins,host):
        await PinnedBackend(pins).connect_tcp(host,443)
    for pins,host in [({},"api.github.com"),({"api.github.com":["127.0.0.1"]},"api.github.com"),({"evil.test":["8.8.8.8"]},"evil.test")]:
        with pytest.raises(GitHubError):
            asyncio.run(attempt(pins,host))


def test_pinned_backend_falls_back_between_valid_public_addresses():
    class Backend(httpcore.AsyncNetworkBackend):
        def __init__(self):
            self.addresses=[]
        async def connect_tcp(self,host,port,**kwargs):
            self.addresses.append(host)
            if host=="2606:4700:4700::1111":
                raise httpcore.ConnectError("IPv6 route unavailable")
            return "connected"
    backend=Backend()
    pins={"api.github.com":["2606:4700:4700::1111","140.82.112.4"]}
    assert asyncio.run(PinnedBackend(pins,backend).connect_tcp("api.github.com",443,timeout=1))=="connected"
    assert backend.addresses==pins["api.github.com"]
