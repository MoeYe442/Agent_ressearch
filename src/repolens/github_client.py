"""Fixed-destination public GitHub HTTP reads; never runs Git or repository code."""
import asyncio
import hashlib
import json
import re
import os
import ssl
import time
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit

import certifi
import httpx
from pydantic import BaseModel, Field, ValidationError
from repolens.github_network import GitHubError, GitHubTransport, HOSTS, check_addresses, public_addresses
from repolens.repositories import is_link

SHA = re.compile(r"^[0-9a-f]{40}$")


class GitHubSource(BaseModel):
    url: str
    owner: str
    repo: str
    requested_ref: str | None = None

    @classmethod
    def parse(cls, url: str, ref: str | None = None):
        try:
            parsed = urlsplit(url)
            parts = parsed.path.rstrip("/").split("/")
            if parsed.scheme != "https" or parsed.netloc.lower() != "github.com" or parsed.query or parsed.fragment or len(parts) != 3 or parts[0]:
                raise ValueError
            owner, repo = parts[1:]
            if repo.endswith(".git"):
                repo = repo[:-4]
            if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", owner) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", repo) or repo in {".", ".."}:
                raise ValueError
            if any(ord(c) <= 32 or ord(c) == 127 for c in url) or "\\" in url:
                raise ValueError
        except (ValueError, TypeError):
            raise GitHubError("invalid_github_url") from None
        if ref is not None:
            ref = ref.strip() or None
        if ref is not None and (len(ref) > 255 or any(ord(c) < 32 or ord(c) == 127 for c in ref) or "\\" in ref):
            raise GitHubError("invalid_github_ref")
        owner, repo = owner.lower(), repo.lower()
        return cls(url=f"https://github.com/{owner}/{repo}", owner=owner, repo=repo, requested_ref=ref)


class GitTreeEntry(BaseModel):
    path: str
    mode: str
    type: str
    sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    size: int | None = Field(default=None, ge=0)


class ResolvedGitHubSource(BaseModel):
    source: GitHubSource
    commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    tree_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    entries: dict[str, GitTreeEntry]


class GitHubClient:
    def __init__(self, settings, *, transport=None, resolve_host=None):
        self.settings = settings
        self.transport = transport
        self.resolve_host = resolve_host or public_addresses
        self.ssl_context = ssl.create_default_context(cafile=certifi.where())
        self.deadline = None
        self.pins = {}
        self.cancelled = lambda: False
        self.download_bytes = 0

    def _start(self):
        if self.cancelled():
            raise GitHubError("github_import_cancelled")
        if self.deadline is None:
            self.deadline = time.monotonic() + self.settings.github_import_timeout
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise GitHubError("github_import_timeout")
        return remaining

    def resolve(self, source: GitHubSource):
        return self._run(self._resolve(source))

    def download_archive(self, resolved: ResolvedGitHubSource, destination: Path):
        destination = Path(os.path.abspath(destination))
        handle, identity = None, None
        try:
            self._check_download_parents(destination.parent)
            destination.parent.mkdir(parents=True, exist_ok=True)
            self._check_download_parents(destination.parent)
            try:
                handle = destination.open("x+b", buffering=0)
            except FileExistsError:
                raise GitHubError("github_download_exists") from None
            except OSError:
                raise GitHubError("github_download_storage") from None
            info = os.fstat(handle.fileno())
            identity = (info.st_dev, info.st_ino)
            result = self._run(self._download(resolved, handle))
            identity = None  # caller now owns the successfully completed download
            return result
        except OSError:
            raise GitHubError("github_download_storage") from None
        finally:
            if handle is not None:
                handle.close()
            if identity is not None:
                try:
                    info = destination.lstat()
                    if not is_link(destination) and (info.st_dev, info.st_ino) == identity:
                        destination.unlink()
                except FileNotFoundError:
                    pass

    @staticmethod
    def _check_download_parents(parent):
        for path in (parent, *parent.parents):
            try:
                if is_link(path):
                    raise GitHubError("github_download_storage")
            except FileNotFoundError:
                continue

    def _run(self, operation):
        try:
            return asyncio.run(self._bounded(operation))
        except GitHubError:
            raise
        except TimeoutError:
            raise GitHubError("github_import_timeout") from None
        except (httpx.HTTPError, OSError):
            raise GitHubError("github_network_error") from None
        except (KeyError, TypeError, AttributeError, ValueError, UnicodeError, ValidationError):
            raise GitHubError("github_protocol_error") from None

    async def _bounded(self, operation):
        running, cancellation = None, None
        try:
            async with asyncio.timeout(self._start()):
                running = asyncio.create_task(operation)
                cancellation = asyncio.create_task(self._watch_cancelled())
                done, _ = await asyncio.wait({running, cancellation}, return_when=asyncio.FIRST_COMPLETED)
                if cancellation in done:
                    raise GitHubError("github_import_cancelled")
                return await running
        finally:
            pending = [task for task in (running, cancellation) if task is not None]
            for task in pending:
                if not task.done():
                    task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            operation.close()

    async def _watch_cancelled(self):
        while not self.cancelled():
            await asyncio.sleep(.05)

    def _session(self):
        transport = self.transport if self.transport is not None else GitHubTransport(self.ssl_context, self.pins)
        return httpx.AsyncClient(transport=transport, verify=self.ssl_context, trust_env=False, follow_redirects=False, timeout=self.settings.github_request_timeout)

    async def _resolve(self, source):
        base = f"https://api.github.com/repos/{source.owner}/{source.repo}"
        async with self._session() as session:
            meta = json.loads(await self._read(session, base, not_found="github_repository_not_found"))
            if meta.get("private") is True:
                raise GitHubError("github_private_unsupported")
            if meta.get("private") is not False:
                raise GitHubError("github_protocol_error")
            ref = source.requested_ref or meta["default_branch"]
            if not isinstance(ref, str) or not ref:
                raise GitHubError("github_ref_not_found")
            commit = json.loads(await self._read(session, base + "/commits/" + quote(ref, safe=""), not_found="github_ref_not_found"))
            sha, tree_sha = commit["sha"], commit["commit"]["tree"]["sha"]
            if not SHA.fullmatch(sha) or not SHA.fullmatch(tree_sha) or (SHA.fullmatch(ref.lower()) and sha != ref.lower()):
                raise GitHubError("github_commit_mismatch")
            tree = json.loads(await self._read(session, base + "/git/trees/" + tree_sha + "?recursive=1"))
            if tree.get("truncated") is not False:
                raise GitHubError("github_tree_truncated")
            if tree.get("sha") != tree_sha or not isinstance(tree.get("tree"), list):
                raise GitHubError("github_protocol_error")
            if len(tree["tree"]) > self.settings.github_max_members:
                raise GitHubError("github_member_limit")
            entries = {}
            for raw in tree["tree"]:
                entry = GitTreeEntry.model_validate(raw)
                if entry.path in entries:
                    raise GitHubError("github_duplicate_tree_path")
                entries[entry.path] = entry
            return ResolvedGitHubSource(source=source, commit_sha=sha, tree_sha=tree_sha, entries=entries)

    async def _download(self, resolved, destination):
        url = f"https://api.github.com/repos/{resolved.source.owner}/{resolved.source.repo}/zipball/{resolved.commit_sha}"
        async with self._session() as session:
            return await self._read(session, url, archive=True, destination=destination)

    async def _read(self, session, url, *, not_found="github_not_found", archive=False, destination=None):
        redirects = 0
        retries = 0
        while True:
            self._start()
            try:
                parsed = urlsplit(url)
                valid = parsed.scheme == "https" and parsed.hostname in HOSTS and not parsed.username and not parsed.password and parsed.port in {None, 443} and not parsed.fragment
            except ValueError:
                valid = False
            if not valid or (not archive and parsed.hostname != "api.github.com"):
                raise GitHubError("github_network_destination")
            headers = {"User-Agent": "RepoLens/0.2", "Accept-Encoding": "identity", "Accept": "application/octet-stream" if archive else "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
            if parsed.hostname == "api.github.com" and self.settings.github_token.get_secret_value():
                headers["Authorization"] = "Bearer " + self.settings.github_token.get_secret_value()
            limit = self.settings.github_max_download_bytes if archive else self.settings.github_max_metadata_bytes
            limit_code = "github_download_limit" if archive else "github_metadata_limit"
            try:
                async with asyncio.timeout(min(self._start(), self.settings.github_request_timeout)):
                    addresses = await self.resolve_host(parsed.hostname)
                    check_addresses(addresses)
                    self.pins[parsed.hostname] = addresses
                    async with session.stream("GET", url, headers=headers) as response:
                        stream = response.extensions.get("network_stream")
                        peer = stream.get_extra_info("server_addr") if stream else None
                        if not peer:
                            raise GitHubError("github_peer_unverifiable")
                        check_addresses([peer[0]])
                        if response.status_code in {301, 302, 303, 307, 308}:
                            if not archive or redirects >= 2 or "location" not in response.headers:
                                raise GitHubError("github_unexpected_redirect")
                            next_url = urljoin(url, response.headers["location"])
                            next_parts = urlsplit(next_url)
                            if next_parts.hostname != "codeload.github.com":
                                raise GitHubError("github_network_destination")
                            url = next_url
                            redirects += 1
                            continue
                        status = response.status_code
                        if status == 429 or (status == 403 and (response.headers.get("x-ratelimit-remaining") == "0" or "retry-after" in response.headers)):
                            raise GitHubError("github_rate_limited")
                        if status == 404:
                            raise GitHubError(not_found)
                        if status in {401, 403}:
                            raise GitHubError("github_forbidden")
                        if status in {408, 500, 502, 503, 504} and retries < 2:
                            retries += 1
                            continue
                        if status != 200:
                            raise GitHubError("github_http_error")
                        if response.headers.get("content-encoding", "identity").lower() != "identity":
                            raise GitHubError("github_encoded_response_unsupported")
                        length = response.headers.get("content-length")
                        if length is not None and (not length.isdecimal() or int(length) > limit):
                            raise GitHubError(limit_code)
                        body, count, digest = bytearray(), 0, hashlib.sha256()
                        handle = destination
                        if handle is not None:
                            try:
                                handle.seek(0)
                                handle.truncate()
                            except OSError:
                                raise GitHubError("github_download_storage") from None
                        try:
                            async for chunk in response.aiter_bytes():
                                self._start()
                                count += len(chunk)
                                if archive:
                                    self.download_bytes += len(chunk)
                                    if self.download_bytes > limit:
                                        raise GitHubError(limit_code)
                                if count > limit:
                                    raise GitHubError(limit_code)
                                digest.update(chunk)
                                if handle:
                                    try:
                                        if handle.write(chunk) != len(chunk):
                                            raise GitHubError("github_download_storage")
                                    except OSError:
                                        raise GitHubError("github_download_storage") from None
                                else:
                                    body.extend(chunk)
                        finally:
                            pass  # download_archive owns and closes the exclusive file handle
                        return digest.hexdigest() if destination is not None else bytes(body)
            except (httpx.TimeoutException, httpx.NetworkError):
                if retries >= 2:
                    raise GitHubError("github_network_error") from None
                retries += 1
