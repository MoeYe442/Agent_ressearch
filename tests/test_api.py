import threading
import time
from fastapi.testclient import TestClient
from repolens.api import create_app
from tests.scripted_model import ScriptedModel


def client_for(indexed, model):
    settings, db, _, _, _, _ = indexed
    return TestClient(create_app(settings, model=model), client=("127.0.0.1", 1234))


def test_submit_returns_before_model_finishes(indexed):
    gate = threading.Event()
    class Slow(ScriptedModel):
        def complete(self, *args, **kwargs):
            gate.wait(5)
            return super().complete(*args, **kwargs)
    with client_for(indexed, Slow()) as client:
        start = time.monotonic()
        response = client.post("/tasks", json={"snapshot_id": indexed[2].id, "question": "Question"})
        assert response.status_code == 202 and time.monotonic() - start < 1
        task_id = response.json()["id"]
        assert client.get(f"/tasks/{task_id}").json()["status"] in {"queued", "running"}
        gate.set()


def test_import_report_evidence_and_sse(indexed):
    with client_for(indexed, ScriptedModel()) as client:
        response = client.post("/repositories", json={"path": indexed[2].source})
        assert response.status_code == 202
        imported_id = response.json()["id"]
        for _ in range(300):
            imported = client.get(f"/repositories/{imported_id}").json()
            if imported["status"] != "importing":
                break
            time.sleep(0.01)
        assert imported["status"] == "ready"
        response = client.post("/tasks", json={"snapshot_id": imported_id, "question": "Question", "idempotency_key": "api-key"})
        task_id = response.json()["id"]
        assert client.post("/tasks", json={"snapshot_id": imported_id, "question": "Other", "idempotency_key": "api-key"}).status_code == 409
        for _ in range(300):
            task = client.get(f"/tasks/{task_id}").json()
            if task["status"] not in {"queued", "running"}:
                break
            time.sleep(0.01)
        report = client.get(f"/tasks/{task_id}/report").json()
        evidence_id = report["claims"][0]["evidence_ids"][0]
        assert 'self.store.save' in client.get(f"/evidence/{evidence_id}").json()["excerpt"]
        sse = client.get(f"/tasks/{task_id}/events", headers={"Last-Event-ID": "2"}).text
        assert "id: 1\n" not in sse and "id: 3\n" in sse and "event: end" in sse


def test_api_rejects_external_path_and_cross_origin(indexed):
    with client_for(indexed, None) as client:
        assert client.post("/repositories", json={"path": "C:/Windows"}).status_code == 400
        assert client.post("/tasks", json={"snapshot_id": indexed[2].id, "question": "Q"}, headers={"Origin": "https://evil.example"}).status_code == 403
        assert client.get("/tasks/missing").json()["error_code"] == "not_found"


def test_repository_import_retry_is_idempotent(indexed):
    with client_for(indexed, None) as client:
        body = {"path": indexed[2].source, "idempotency_key": "import-intent"}
        first = client.post("/repositories", json=body)
        second = client.post("/repositories", json=body)
        assert first.status_code == second.status_code == 202
        assert first.json()["id"] == second.json()["id"]
