import queue
import threading
import json
from datetime import datetime, timezone
from uuid import uuid4
from repolens.agent import AgentRunner
from repolens.indexing import build_index
from repolens.models import AnalysisTask, RepositorySnapshot, TaskEvent, ToolContext, Usage
from repolens.repositories import checked_repo, create_snapshot
from repolens.tools import ToolRegistry
from repolens.github_client import GitHubClient, GitHubSource
from repolens.github_import import import_github_snapshot

TERMINAL = {"succeeded", "partial", "failed", "cancelled"}


def now():
    return datetime.now(timezone.utc).isoformat()


class TaskService:
    def __init__(self, settings, db, model, github_client_factory=None):
        self.settings, self.db, self.model = settings, db, model
        self.registry = ToolRegistry(db)
        self.queue = queue.Queue()
        self.lock = threading.RLock()
        self.stopping = threading.Event()
        self.worker = None
        self.github_client_factory = github_client_factory or GitHubClient

    def start(self):
        with self.lock:
            if self.worker is not None:
                return
            # Fresh process startup is explicit failure of interrupted work, never a fake resume.
            for payload in self.db.all("tasks"):
                task = AnalysisTask.model_validate(payload)
                if task.status == "running":
                    task.status, task.error_code = "failed", "interrupted"
                    self._save(task, "task_finished", {"status": "failed", "error_code": "interrupted"})
                elif task.status == "queued":
                    self.queue.put(("task", task.id))
            for payload in self.db.all("snapshots"):
                snapshot = RepositorySnapshot.model_validate(payload)
                try:
                    self.db.get("indexes", snapshot.id)
                    has_index = True
                except KeyError:
                    has_index = False
                if snapshot.status == "importing" or (snapshot.status == "ready" and not has_index):
                    snapshot.status, snapshot.error_code = "failed", "interrupted_import"
                    self.db.put_snapshot(snapshot)
            self.worker = threading.Thread(target=self._work, name="repolens-worker", daemon=True)
            self.worker.start()

    def stop(self):
        self.stopping.set()
        if self.worker:
            self.worker.join(timeout=self.settings.provider_timeout + 2)

    def _save(self, task, type, payload=None, report=None):
        task.updated_at = now()
        return self.db.save_task_event(task, TaskEvent(type=type, payload=payload or {}), report=report)

    def import_repository(self, path, idempotency_key=None):
        source = checked_repo(path, self.settings)
        return self._register_import(str(source), "local", None, idempotency_key)

    def import_github_repository(self, url, ref=None, idempotency_key=None):
        source = GitHubSource.parse(url, ref)
        return self._register_import(source.url, "github", source.requested_ref, idempotency_key)

    def _register_import(self, source, source_type, ref, idempotency_key):
        snapshot_id = uuid4().hex
        snapshot = RepositorySnapshot(id=snapshot_id, source=source, source_type=source_type, requested_ref=ref, root=self.settings.data_dir.resolve() / "snapshots" / snapshot_id)
        with self.lock:
            if idempotency_key:
                try:
                    prior = self.db.get("import_idempotency", idempotency_key)
                    if prior["source"] != source or prior.get("source_type", "local") != source_type or prior.get("ref") != ref:
                        raise ValueError("idempotency_conflict")
                    return self.db.get_snapshot(prior["snapshot_id"])
                except KeyError:
                    pass
            with self.db.connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("INSERT INTO entities VALUES ('snapshots',?,?)", (snapshot.id, snapshot.model_dump_json()))
                if idempotency_key:
                    conn.execute("INSERT INTO entities VALUES ('import_idempotency',?,?)", (idempotency_key, json.dumps({"source": source, "source_type": source_type, "ref": ref, "snapshot_id": snapshot.id})))
            self.queue.put(("import", snapshot_id))
        return snapshot

    def submit(self, snapshot_id, question, idempotency_key=None):
        with self.lock:
            if idempotency_key:
                try:
                    prior = self.db.get("idempotency", idempotency_key)
                    if prior["snapshot_id"] != snapshot_id or prior["question"] != question:
                        raise ValueError("idempotency_conflict")
                    return self.get(prior["task_id"])
                except KeyError:
                    pass
            if self.db.get_snapshot(snapshot_id).status != "ready":
                raise ValueError("snapshot_not_ready")
            task = AnalysisTask(id=uuid4().hex, snapshot_id=snapshot_id, question=question, created_at=now(), updated_at=now())
            # Single process submission lock; key, task and first event share one transaction.
            with self.db.connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("INSERT INTO entities VALUES ('tasks',?,?)", (task.id, task.model_dump_json()))
                event = TaskEvent(task_id=task.id, sequence=1, type="task_queued", timestamp=now(), payload={"status": "queued"})
                conn.execute("INSERT INTO events VALUES (?,?,?)", (task.id, 1, event.model_dump_json()))
                if idempotency_key:
                    import json
                    conn.execute("INSERT INTO entities VALUES ('idempotency',?,?)", (idempotency_key, json.dumps({"snapshot_id": snapshot_id, "question": question, "task_id": task.id})))
            self.queue.put(("task", task.id))
            return task

    def get(self, task_id):
        return AnalysisTask.model_validate(self.db.get("tasks", task_id))

    def events(self, task_id, after_sequence=0):
        self.get(task_id)
        return self.db.task_events(task_id, after_sequence)

    def cancel(self, task_id):
        with self.lock:
            task = self.get(task_id)
            if task.status in TERMINAL or task.cancel_requested:
                return task
            task.cancel_requested = True
            if task.status == "queued":
                task.status = "cancelled"
            self._save(task, "task_finished" if task.status == "cancelled" else "cancel_requested", {"status": task.status})
            return task

    def _work(self):
        while not self.stopping.is_set():
            try:
                kind, key = self.queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                if kind == "import":
                    self._import(key)
                else:
                    self._execute(key)
            except Exception:
                # An individual job must not kill the queue or expose exception text/secrets.
                if kind == "task":
                    with self.lock:
                        task = self.get(key)
                        task.status, task.error_code = "failed", "worker_error"
                        self._save(task, "task_finished", {"status": "failed", "error_code": "worker_error"})
            finally:
                self.queue.task_done()

    def _import(self, snapshot_id):
        snapshot = self.db.get_snapshot(snapshot_id)
        archive_path = None
        try:
            if snapshot.source_type == "github":
                adapter = self.github_client_factory(self.settings)
                resolved = adapter.resolve(GitHubSource.parse(snapshot.source, snapshot.requested_ref))
                snapshot.commit_sha = resolved.commit_sha
                self.db.put_snapshot(snapshot)
                archive_path = self.settings.data_dir.resolve() / "downloads" / f"{snapshot_id}.zip"
                adapter.download_archive(resolved, archive_path)
                snapshot = import_github_snapshot(resolved, archive_path, self.settings, snapshot_id)
            else:
                snapshot = create_snapshot(snapshot.source, self.settings, snapshot_id)
            snapshot.status = "importing"
            self.db.put_snapshot(snapshot)
            build_index(snapshot, self.db)
        except Exception as exc:
            snapshot.status = "failed"
            snapshot.error_code = str(exc) if isinstance(exc, ValueError) else "import_failed"
            self.db.put_snapshot(snapshot)
        finally:
            if archive_path is not None:
                archive_path.unlink(missing_ok=True)

    def _execute(self, task_id):
        with self.lock:
            task = self.get(task_id)
            if task.status != "queued":
                return
            task.status = "running"
            self._save(task, "task_started", {"status": "running"})

        def cancelled():
            return self.stopping.is_set() or self.get(task_id).cancel_requested

        def emit(event):
            with self.lock:
                current = self.get(task_id)
                if "usage" in event.payload:
                    current.usage = Usage.model_validate(event.payload["usage"])
                self._save(current, event.type, event.payload)

        result = AgentRunner(self.model, self.registry, self.settings).run(task.question, ToolContext(snapshot_id=task.snapshot_id, task_id=task_id), emit, cancelled)
        with self.lock:
            task = self.get(task_id)
            task.status = "cancelled" if task.cancel_requested else result.status
            result.status = task.status
            task.usage = result.usage
            if result.status == "failed":
                task.error_code = result.limitations[0] if result.limitations else "analysis_failed"
            self._save(task, "task_finished", {"status": task.status, "error_code": task.error_code, "usage": task.usage.model_dump()}, report=result)
