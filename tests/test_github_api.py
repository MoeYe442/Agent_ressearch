import threading
import time
import httpx
import pytest
from fastapi.testclient import TestClient
from repolens.api import create_app
from repolens.github_client import GitHubClient
from repolens.models import RepositorySnapshot
from tests.github_fixtures import COMMIT, GitHubFixture, public_dns, response
from tests.scripted_model import ScriptedModel


def github_app(indexed, handler=None):
    return create_app(indexed[0], model=ScriptedModel(), github_client_factory=lambda settings: GitHubClient(settings, transport=httpx.MockTransport(handler or GitHubFixture()), resolve_host=public_dns))


def wait_import(client, snapshot_id):
    for _ in range(500):
        snapshot = client.get(f"/repositories/{snapshot_id}").json()
        if snapshot["status"] != "importing":
            return snapshot
        time.sleep(.01)
    raise AssertionError("import timed out")


def test_local_import_request_remains_compatible(indexed):
    with TestClient(github_app(indexed), client=("127.0.0.1", 1)) as client:
        result = client.post("/repositories", json={"path": indexed[2].source})
        assert result.status_code == 202
        assert wait_import(client, result.json()["id"])["source_type"] == "local"


@pytest.mark.parametrize("body", [{}, {"path": "x", "github_url": "https://github.com/example/demo"}, {"path": "x", "ref": "main"}, {"github_url": "https://evil.test/x/y"}])
def test_rejects_ambiguous_source_and_local_ref(indexed, body):
    with TestClient(github_app(indexed), client=("127.0.0.1", 1)) as client:
        assert client.post("/repositories", json=body).status_code in {400, 422}


def test_github_import_returns_before_download_completes(indexed):
    fixture, gate, entered = GitHubFixture(), threading.Event(), threading.Event()
    def handler(request):
        if request.url.host == "codeload.github.com":
            entered.set()
            gate.wait(5)
        return fixture(request)
    with TestClient(github_app(indexed, handler), client=("127.0.0.1", 1)) as client:
        started = time.monotonic()
        result = client.post("/repositories", json={"github_url": "https://github.com/example/demo", "ref": "main"})
        assert result.status_code == 202 and time.monotonic() - started < 1
        try:
            assert entered.wait(3)
            assert client.get("/repositories/" + result.json()["id"]).json()["status"] == "importing"
        finally:
            gate.set()
        assert wait_import(client, result.json()["id"])["status"] == "ready"


def test_idempotency_covers_url_and_ref(indexed):
    with TestClient(github_app(indexed), client=("127.0.0.1", 1)) as client:
        body = {"github_url": "https://github.com/Example/demo.git", "ref": "main", "idempotency_key": "public-import"}
        first = client.post("/repositories", json=body)
        body["github_url"] = "https://github.com/example/demo/"
        assert client.post("/repositories", json=body).json()["id"] == first.json()["id"]
        body["ref"] = "tag"
        assert client.post("/repositories", json=body).status_code == 409
        assert client.post("/repositories", json={"path": indexed[2].source, "idempotency_key": "public-import"}).status_code == 409


def test_import_error_is_persisted(indexed):
    with TestClient(github_app(indexed, lambda r: response(429)), client=("127.0.0.1", 1)) as client:
        result = client.post("/repositories", json={"github_url": "https://github.com/example/demo"})
        assert result.status_code == 202
        saved = wait_import(client, result.json()["id"])
        assert saved["status"] == "failed" and saved["error_code"] == "github_rate_limited"


def test_restart_marks_network_import_interrupted(indexed):
    settings, db, _, _, _, _ = indexed
    snapshot = RepositorySnapshot(id="d" * 32, source="https://github.com/example/demo", source_type="github", root=settings.data_dir / "snapshots" / ("d" * 32))
    db.put_snapshot(snapshot)
    with TestClient(github_app(indexed), client=("127.0.0.1", 1)) as client:
        assert client.get("/repositories/" + snapshot.id).json()["error_code"] == "interrupted_import"


def test_old_snapshot_json_loads_with_defaults(indexed):
    raw = indexed[2].model_dump(mode="json")
    for field in ["source_type", "requested_ref", "archive_hash"]:
        raw.pop(field, None)
    assert RepositorySnapshot.model_validate(raw).source_type == "local"


def test_github_report_citation_preserves_commit(indexed):
    with TestClient(github_app(indexed), client=("127.0.0.1", 1)) as client:
        result = client.post("/repositories", json={"github_url": "https://github.com/example/demo", "ref": "main"})
        snapshot = wait_import(client, result.json()["id"])
        assert snapshot["commit_sha"] == COMMIT
        task_id = client.post("/tasks", json={"snapshot_id": snapshot["id"], "question": "Question"}).json()["id"]
        for _ in range(300):
            task = client.get("/tasks/" + task_id).json()
            if task["status"] not in {"queued", "running"}:
                break
            time.sleep(.01)
        report = client.get(f"/tasks/{task_id}/report").json()
        assert report["status"] == "succeeded"
        evidence_id = report["claims"][0]["evidence_ids"][0]
        assert client.get("/evidence/" + evidence_id).json()["commit_sha"] == COMMIT
