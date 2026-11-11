import asyncio
import hashlib
import time
import httpx
import pytest
from repolens.config import Settings
from repolens.github_client import GitHubSource, GitHubClient, GitHubError
from tests.github_fixtures import COMMIT, GitHubFixture, public_dns, response


def client(tmp_path, handler=None, **updates):
    settings = Settings(workspace_root=tmp_path, data_dir=tmp_path / "data", **updates)
    return GitHubClient(settings, transport=httpx.MockTransport(handler or GitHubFixture()), resolve_host=public_dns)


@pytest.mark.parametrize("url", ["https://github.com/Example/demo", "https://github.com/example/demo.git/", "https://GitHub.com/example/demo/"])
def test_accepts_only_public_github_url_forms(url):
    assert GitHubSource.parse(url).url == "https://github.com/example/demo"


@pytest.mark.parametrize("url", ["git@github.com:example/demo.git", "http://github.com/example/demo", "https://github.com@127.0.0.1/demo", "https://github.com.evil.test/example/demo", "https://user:secret@github.com/example/demo", "https://github.com/example/demo?url=x", "https://github.com/example/demo/tree/main", "https://github.com/example/../demo", "https://github.com:8080/example/demo", "https://github.com/example/%2e%2e", "https://github.com/example/demo#x"])
def test_rejects_other_url_forms(url):
    with pytest.raises(ValueError, match="invalid_github_url"):
        GitHubSource.parse(url)


@pytest.mark.parametrize("ref", [None, "v1.0", COMMIT, "feature/parser"])
def test_resolves_default_branch_tag_and_sha(tmp_path, ref):
    fixture = GitHubFixture()
    resolved = client(tmp_path, fixture).resolve(GitHubSource.parse("https://github.com/example/demo", ref))
    assert resolved.commit_sha == COMMIT and resolved.entries["app.py"].sha
    assert fixture.requests[-1].url.path.endswith("b" * 40)


def test_ref_with_slash_is_encoded_once(tmp_path):
    fixture = GitHubFixture()
    client(tmp_path, fixture).resolve(GitHubSource.parse("https://github.com/example/demo", "feature/parser"))
    assert b"feature%2Fparser" in fixture.requests[1].url.raw_path


@pytest.mark.parametrize("private,truncated", [(True, False), (False, True)])
def test_rejects_private_repo_and_truncated_tree(tmp_path, private, truncated):
    fixture = GitHubFixture()
    def handler(request):
        if request.url.path == "/repos/example/demo":
            return response(json={"private": private, "default_branch": "main"})
        result = fixture(request)
        if "/git/trees/" in request.url.path:
            data = result.json()
            data["truncated"] = truncated
            return response(json=data)
        return result
    with pytest.raises(GitHubError, match="github_private_unsupported|github_tree_truncated"):
        client(tmp_path, handler).resolve(GitHubSource.parse("https://github.com/example/demo"))


def test_redirect_allowlist_and_token_isolation(tmp_path):
    fixture = GitHubFixture()
    adapter = client(tmp_path, fixture, github_token="local-test-token")
    resolved = adapter.resolve(GitHubSource.parse("https://github.com/example/demo"))
    destination = tmp_path / "archive.zip"
    digest = adapter.download_archive(resolved, destination)
    assert digest == hashlib.sha256(destination.read_bytes()).hexdigest()
    assert all(r.headers.get("Authorization") == "Bearer local-test-token" for r in fixture.requests if r.url.host == "api.github.com")
    assert all("Authorization" not in r.headers for r in fixture.requests if r.url.host == "codeload.github.com")
    adapter = client(tmp_path, lambda r: response(302, headers={"Location": "https://127.0.0.1/secret"}))
    with pytest.raises(GitHubError):
        adapter.download_archive(resolved, tmp_path / "other.zip")


@pytest.mark.parametrize("status,headers,expected", [(429, {}, "github_rate_limited"), (403, {"X-RateLimit-Remaining": "0"}, "github_rate_limited"), (404, {}, "github_repository_not_found"), (403, {}, "github_forbidden")])
def test_rate_limit_and_not_found_are_explicit(tmp_path, status, headers, expected):
    with pytest.raises(GitHubError, match=expected) as exc:
        client(tmp_path, lambda r: response(status, headers=headers, text="do not leak local-test-token")).resolve(GitHubSource.parse("https://github.com/example/demo"))
    assert "local-test-token" not in str(exc.value)


def test_download_counts_actual_bytes(tmp_path):
    resolved = client(tmp_path).resolve(GitHubSource.parse("https://github.com/example/demo"))
    adapter = client(tmp_path, lambda r: response(content=b"x" * 50), github_max_download_bytes=10)
    with pytest.raises(GitHubError, match="github_download_limit"):
        adapter.download_archive(resolved, tmp_path / "archive.zip")
    assert not (tmp_path / "archive.zip").exists()


def test_metadata_size_limit(tmp_path):
    with pytest.raises(GitHubError, match="github_metadata_limit"):
        client(tmp_path, github_max_metadata_bytes=10).resolve(GitHubSource.parse("https://github.com/example/demo"))


def test_trickling_response_hits_total_deadline(tmp_path):
    class Trickle(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(100):
                await asyncio.sleep(.03)
                yield b" "
    started = time.monotonic()
    with pytest.raises(GitHubError, match="github_import_timeout"):
        client(tmp_path, lambda r: response(stream=Trickle()), github_import_timeout=.15).resolve(GitHubSource.parse("https://github.com/example/demo"))
    assert time.monotonic() - started < 1


def test_retries_share_import_deadline(tmp_path):
    requests = []
    async def handler(request):
        requests.append(request)
        await asyncio.sleep(.06)
        return response(503)
    with pytest.raises(GitHubError, match="github_import_timeout"):
        client(tmp_path, handler, github_import_timeout=.14).resolve(GitHubSource.parse("https://github.com/example/demo"))
    assert len(requests) <= 3


def test_private_dns_and_connected_peer_are_rejected(tmp_path):
    adapter = client(tmp_path)
    async def private_dns(host):
        return ["127.0.0.1"]
    adapter.resolve_host = private_dns
    with pytest.raises(GitHubError, match="github_network_destination"):
        adapter.resolve(GitHubSource.parse("https://github.com/example/demo"))
