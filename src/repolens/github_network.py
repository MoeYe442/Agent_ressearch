"""Bounded DNS and numeric-IP connections with the original GitHub Host and TLS SNI."""
import asyncio
from concurrent.futures import Future
from contextlib import contextmanager
import ipaddress
import socket
import threading
import time

import httpcore
import httpx

HOSTS = {"api.github.com", "codeload.github.com"}
_dns_lock = threading.Lock()
_dns_jobs = {}


class GitHubError(ValueError):
    """Stable public error codes; no upstream body or credential text."""


def check_addresses(addresses):
    try:
        if not addresses:
            raise ValueError
        for address in addresses:
            ip = ipaddress.ip_address(address)
            if not ip.is_global or ip.is_multicast:
                raise ValueError
    except ValueError:
        raise GitHubError("github_network_destination") from None


async def public_addresses(host):
    if host not in HOSTS:
        raise GitHubError("github_network_destination")
    # At most one outstanding OS lookup per fixed hostname. A cancelled caller
    # neither waits for the OS thread on asyncio.run shutdown nor starts more work.
    with _dns_lock:
        job = _dns_jobs.get(host)
        if job is None or job.done():
            job = Future()
            _dns_jobs[host] = job
            def resolve():
                try:
                    values = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
                    job.set_result(list({item[4][0] for item in values}))
                except BaseException as exc:
                    job.set_exception(exc)
            threading.Thread(target=resolve, name="repolens-github-dns", daemon=True).start()
    return await asyncio.shield(asyncio.wrap_future(job))


class PinnedBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, addresses, backend=None):
        self.addresses = addresses
        self.backend = backend or httpcore.AnyIOBackend()

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        if host not in HOSTS or port != 443:
            raise GitHubError("github_network_destination")
        pins = self.addresses.get(host, [])
        check_addresses(pins)
        # Only a checked numeric address reaches the OS connection backend; TLS
        # remains managed by httpcore using the original request origin hostname.
        deadline = time.monotonic() + (timeout if timeout is not None else 30)
        failure = None
        for index, address in enumerate(pins):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise httpcore.ConnectTimeout("GitHub connection budget exhausted")
            try:
                return await self.backend.connect_tcp(address, port, timeout=remaining / (len(pins) - index), local_address=local_address, socket_options=socket_options)
            except (httpcore.NetworkError, httpcore.TimeoutException) as exc:
                failure = exc
        raise failure

    async def connect_unix_socket(self, *args, **kwargs):
        raise GitHubError("github_network_destination")

    async def sleep(self, seconds):
        await asyncio.sleep(seconds)


@contextmanager
def core_errors():
    try:
        yield
    except httpcore.TimeoutException:
        raise httpx.TimeoutException("GitHub transport timeout") from None
    except httpcore.NetworkError:
        raise httpx.NetworkError("GitHub transport network error") from None
    except httpcore.ProtocolError:
        raise httpx.ProtocolError("GitHub transport protocol error") from None


class ResponseStream(httpx.AsyncByteStream):
    def __init__(self, stream):
        self.stream = stream

    async def __aiter__(self):
        with core_errors():
            async for chunk in self.stream:
                yield chunk

    async def aclose(self):
        with core_errors():
            await self.stream.aclose()


class GitHubTransport(httpx.AsyncBaseTransport):
    def __init__(self, ssl_context, addresses, *, backend=None):
        self.pool = httpcore.AsyncConnectionPool(ssl_context=ssl_context, network_backend=PinnedBackend(addresses, backend), max_connections=2, max_keepalive_connections=2)

    async def handle_async_request(self, request):
        core_request = httpcore.Request(method=request.method, url=httpcore.URL(scheme=request.url.raw_scheme, host=request.url.raw_host, port=request.url.port, target=request.url.raw_path), headers=request.headers.raw, content=request.stream, extensions=request.extensions)
        with core_errors():
            response = await self.pool.handle_async_request(core_request)
        return httpx.Response(response.status, headers=response.headers, stream=ResponseStream(response.stream), extensions=response.extensions)

    async def aclose(self):
        await self.pool.aclose()
