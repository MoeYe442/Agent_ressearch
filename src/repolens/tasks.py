import queue
import threading
import json
from datetime import datetime, timezone
from uuid import uuid4
from repolens.agent import AgentRunner
from repolens.indexing import build_index
from repolens.models import AnalysisTask, AnalysisResult, RepositorySnapshot, TaskEvent, ToolContext, Usage
from repolens.repositories import checked_repo, create_snapshot
from repolens.tools import ToolRegistry
from repolens.github_client import GitHubClient, GitHubSource
from repolens.github_import import import_github_snapshot
from repolens.import_storage import cleanup_import
from repolens.orchestration import CollaborativeRunner
from repolens.retrieval import RetrievalService
from repolens.execution_store import WorkerLease,ExecutionSession,WorkerPaused,LeaseLost,RecoveryRejected,digest
from repolens.recovery import signature,eligibility,current_usage,paused_report,saved_run
from repolens.checkpoints import checkpoint_exists
from repolens.single_graph import DurableSingleRunner
from repolens.review import render_report
from repolens.dispatch import DurableQueue
from repolens.documents import DocumentService,DocumentStore

TERMINAL = {"succeeded", "partial", "failed", "cancelled"}


def now():
    return datetime.now(timezone.utc).isoformat()


class TaskService:
    def __init__(self, settings, db, model, github_client_factory=None, retrieval_factory=None):
        self.settings, self.db, self.model = settings, db, model
        self.retrieval = (retrieval_factory or RetrievalService)(settings, db)
        self.registry = ToolRegistry(db, retrieval=self.retrieval)
        self.queue = queue.Queue()
        self.lock = threading.RLock()
        self.stopping = threading.Event()
        self.worker = None
        self.github_client_factory = github_client_factory or GitHubClient
        self.lease=WorkerLease(db,on_lost=self.stopping.set)
        self.documents=DocumentService(settings,db)
        self.durable=settings.execution_mode!='embedded'
        if self.durable:self.queue=DurableQueue(db,settings,self.lease)

    def start(self):
        if self.settings.execution_mode=='api':return
        if self.db.backend=='postgres':
            from repolens.postgres_checkpoints import setup_postgres
            setup_postgres(self.db)
        with self.lock,self.db.atomic():
            if self.worker is not None:
                return
            self.lease.acquire();self.db.worker_guard=self.lease.guard;self.lease.start_heartbeat()
            self.retrieval.interrupt_unfinished(pending=self.queue.is_pending if self.durable else lambda kind,key:False)
            for document in self.db.all('web_documents'):
                if document['status']=='running':
                    document.update(status='failed',error_code='document_interrupted')
                    self.db.put('web_documents',document['id'],document)
                elif document['status']=='queued':self.queue.put(('document',document['id']))
            # Fresh process startup is explicit failure of interrupted work, never a fake resume.
            for payload in self.db.all("tasks"):
                task = AnalysisTask.model_validate(payload)
                if task.status == "running":
                    if task.recovery_enabled and saved_run(self.db,task.id) and checkpoint_exists(self.db,task.id):
                        self._pause(task.id)
                        continue
                    task.status, task.error_code = "failed", "interrupted"
                    try:
                        graph = self.db.get("graphs", task.id)
                        graph = {**graph, "status": "failed", "issues": [*graph.get("issues", []), "interrupted"]}
                    except KeyError:
                        graph = None
                    self._save(task, "task_finished", {"status": "failed", "error_code": "interrupted"}, graph=graph)
                elif task.status == "queued":
                    self.queue.put(("task", task.id))
                elif task.status=='partial' and task.error_code=='interrupted':
                    available,error=eligibility(self.db,task,self.settings,retrieval=self.retrieval)
                    if (task.resume_available,task.recovery_error)!=(available,error):
                        task.resume_available,task.recovery_error=available,error
                        self._save(task,'recovery_checked',{'resume_available':available,'error_code':error})
            for payload in self.db.all("snapshots"):
                snapshot = RepositorySnapshot.model_validate(payload)
                try:
                    self.db.get("indexes", snapshot.id)
                    has_index = True
                except KeyError:
                    has_index = False
                if snapshot.status == "importing" or (snapshot.status == "ready" and not has_index):
                    if self.durable and snapshot.status=='importing' and self.queue.is_pending('import',snapshot.id):continue
                    snapshot.status, snapshot.error_code = "failed", "interrupted_import"
                    if not cleanup_import(self.settings, snapshot.id, snapshot=True, download=True):
                        snapshot.error_code = "interrupted_import_cleanup_failed"
                    self.db.put_snapshot(snapshot)
                elif snapshot.status == "ready":
                    cleanup_import(self.settings, snapshot.id, download=True)
            if self.durable:self.queue.abandon_claimed()
            self.worker = threading.Thread(target=self._work, name="repolens-worker", daemon=True)
            self.worker.start()

    def stop(self):
        self.stopping.set()
        if self.worker:
            self.worker.join()  # drain/cancel active work; no old worker may publish after return
        if self.lease.epoch:
            self.db.worker_guard=None
            self.lease.release()
        if self.durable:self.queue.close()

    def _save(self, task, type, payload=None, report=None, graph=None,execution_epoch=None,extra_entities=None):
        task.updated_at = now()
        if graph is None and task.mode=='collaborative':
            try:graph=self.db.get('graphs',task.id)
            except KeyError:pass
        if graph is not None:graph={**graph,'status':task.status}
        def guard(conn):
            self.lease.guard(conn)
            if execution_epoch is not None:
                row=conn.execute("SELECT payload FROM entities WHERE kind='tasks' AND id=?",(task.id,)).fetchone()
                raw=json.loads(row['payload']) if row else {}
                if raw.get('execution_epoch',0)!=execution_epoch or raw.get('status')!='running':raise LeaseLost()
        return self.db.save_task_event(task, TaskEvent(type=type, payload=payload or {}), report=report, graph=graph,guard=guard if self.lease.epoch else None,extra_entities=extra_entities)

    def _pause(self,task_id,runner=None):
        with self.lock,self.db.atomic():
            task=self.get(task_id)
            graph=getattr(runner,'last_view',None)
            if graph is None:
                try:graph=self.db.get('graphs',task_id)
                except KeyError:pass
            report=paused_report(self.db,task,graph)
            task.status=report.status;task.usage=report.usage
            run=saved_run(self.db,task_id)
            task.recovery_deadline=run['deadline'] if run else None
            task.error_code=None if task.cancel_requested else 'interrupted'
            task.resume_available,task.recovery_error=eligibility(self.db,task,self.settings,retrieval=self.retrieval) if not task.cancel_requested else (False,None)
            if graph is not None:graph={**graph,'issues':[*graph.get('issues',[]),'interrupted']}
            self._save(task,'task_finished',{'status':task.status,'error_code':task.error_code,'resume_available':task.resume_available,'usage':task.usage.model_dump()},report=report,graph=graph,execution_epoch=task.execution_epoch)

    def resume(self,task_id,idempotency_key):
        with self.lock,self.db.atomic():
            if self.stopping.is_set():raise ValueError('service_stopping')
            task=self.get(task_id)
            try:
                prior=self.db.get('resume_keys',idempotency_key)
                if prior['task_id']!=task_id:raise ValueError('idempotency_conflict')
                return task
            except KeyError:pass
            if task.cancel_requested:raise ValueError('task_not_resumable')
            if task.status in {'queued','running'} and task.attempt>1:
                self._save(task,'resume_replayed',{'attempt':task.attempt},extra_entities=[('resume_keys',idempotency_key,{'task_id':task_id,'attempt':task.attempt})])
                return task
            if not saved_run(self.db,task_id) or not checkpoint_exists(self.db,task_id):raise KeyError('recovery_checkpoint_missing')
            if task.status!='partial' or task.error_code!='interrupted' or task.cancel_requested:raise ValueError('task_not_resumable')
            available,error=eligibility(self.db,task,self.settings,validate_sources=True,retrieval=self.retrieval)
            if not available:raise ValueError(error)
            task.status='queued';task.attempt+=1;task.resume_available=False;task.recovery_error=None;task.error_code=None
            # Task/event/graph and the resume key share the same authoritative transaction.
            self._save(task,'task_resumed',{'attempt':task.attempt,'status':'queued'},extra_entities=[('resume_keys',idempotency_key,{'task_id':task_id,'attempt':task.attempt})])
            self.queue.put(('task',task_id))
            return task

    def import_repository(self, path, idempotency_key=None):
        source = checked_repo(path, self.settings)
        return self._register_import(str(source), "local", None, idempotency_key)

    def import_github_repository(self, url, ref=None, idempotency_key=None):
        source = GitHubSource.parse(url, ref)
        return self._register_import(source.url, "github", source.requested_ref, idempotency_key)

    def _register_import(self, source, source_type, ref, idempotency_key):
        snapshot_id = uuid4().hex
        snapshot = RepositorySnapshot(id=snapshot_id, source=source, source_type=source_type, requested_ref=ref, root=self.settings.data_dir.resolve() / "snapshots" / snapshot_id)
        with self.lock,self.db.atomic():
            if self.stopping.is_set():
                raise ValueError("service_stopping")
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
                if self.lease.epoch:self.lease.guard(conn)
                conn.execute("INSERT INTO entities VALUES ('snapshots',?,?)", (snapshot.id, snapshot.model_dump_json()))
                if idempotency_key:
                    conn.execute("INSERT INTO entities VALUES ('import_idempotency',?,?)", (idempotency_key, json.dumps({"source": source, "source_type": source_type, "ref": ref, "snapshot_id": snapshot.id})))
            self.queue.put(("import", snapshot_id))
        return snapshot

    def submit(self, snapshot_id, question, idempotency_key=None, *, mode="single", retrieval_mode="keyword", rerank=False,document_ids=None):
        document_ids=sorted(set(document_ids or []))
        if len(document_ids)>10:raise ValueError('document_attachment_limit')
        if mode not in {"single", "collaborative"}:
            raise ValueError("invalid_mode")
        if retrieval_mode not in {"keyword", "hybrid"} or (rerank and retrieval_mode != "hybrid"):
            raise ValueError("invalid_retrieval_mode")
        with self.lock,self.db.atomic():
            if self.stopping.is_set():raise ValueError('service_stopping')
            if idempotency_key:
                try:
                    prior = self.db.get("idempotency", idempotency_key)
                    if prior["snapshot_id"] != snapshot_id or prior["question"] != question or prior.get("mode", "single") != mode or prior.get("retrieval_mode", "keyword") != retrieval_mode or prior.get("rerank", False) != rerank or prior.get('document_ids',[])!=document_ids:
                        raise ValueError("idempotency_conflict")
                    return self.get(prior["task_id"])
                except KeyError:
                    pass
            if self.db.get_snapshot(snapshot_id).status != "ready":
                raise ValueError("snapshot_not_ready")
            DocumentStore(self.db).summaries(document_ids,snapshot_id)
            limits = {key: getattr(self.settings, key) for key in ("max_model_calls", "max_tool_calls", "max_tokens", "max_seconds", "max_output_tokens")}
            identifier = ("synthetic:" + type(self.model).__name__) if self.settings.test_environment else self.settings.model_name or None
            configuration = {}
            if retrieval_mode == "hybrid":
                index = self.retrieval.ready(snapshot_id)
                if rerank and not self.retrieval.rerank_configured:
                    raise ValueError("rerank_not_configured")
                configuration = {**index["configuration"], "index_id": index["id"], "rerank_model": self.settings.rerank_model if rerank else None}
            task = AnalysisTask(id=uuid4().hex, snapshot_id=snapshot_id, question=question, mode=mode, created_at=now(), updated_at=now(), budget_limits=limits, model_identifier=identifier, prompt_version="repolens-0.7-" + mode, retrieval_mode=retrieval_mode, rerank=rerank, retrieval_configuration=configuration,recovery_enabled=True)
            task.document_ids=document_ids
            task.recovery_config_hash=digest(signature(task,self.settings,self.db))
            # Single process submission lock; key, task and first event share one transaction.
            with self.db.connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                if self.lease.epoch:self.lease.guard(conn)
                conn.execute("INSERT INTO entities VALUES ('tasks',?,?)", (task.id, task.model_dump_json()))
                event = TaskEvent(task_id=task.id, sequence=1, type="task_queued", timestamp=now(), payload={"status": "queued"})
                conn.execute("INSERT INTO events VALUES (?,?,?)", (task.id, 1, event.model_dump_json()))
                if idempotency_key:
                    import json
                    conn.execute("INSERT INTO entities VALUES ('idempotency',?,?)", (idempotency_key, json.dumps({"snapshot_id": snapshot_id, "question": question, "task_id": task.id, "mode": mode, "retrieval_mode": retrieval_mode, "rerank": rerank,'document_ids':document_ids})))
            self.queue.put(("task", task.id))
            return task

    def get(self, task_id):
        return AnalysisTask.model_validate(self.db.get("tasks", task_id))

    def events(self, task_id, after_sequence=0):
        self.get(task_id)
        return self.db.task_events(task_id, after_sequence)

    def cancel(self, task_id):
        with self.lock,self.db.atomic():
            task = self.get(task_id)
            if task.status=='partial' and task.resume_available:
                task.cancel_requested=True;task.status='cancelled';task.resume_available=False
                report=paused_report(self.db,task)
                self._save(task,'task_finished',{'status':'cancelled'},report=report)
                return task
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
                elif kind == "retrieval":
                    self.retrieval.build(key, self.stopping.is_set)
                elif kind=='document':
                    self.documents.build(key,self.stopping.is_set)
                else:
                    self._execute(key)
            except LeaseLost:
                self.stopping.set()
            except RecoveryRejected as exc:
                with self.lock,self.db.atomic():
                    task=self.get(key);task.status='failed';task.error_code=exc.code;task.resume_available=False
                    task.usage=current_usage(self.db,key)
                    report=AnalysisResult(status='failed',mode=task.mode,usage=task.usage,limitations=[exc.code])
                    self._save(task,'task_finished',{'status':'failed','error_code':exc.code},report=report,execution_epoch=task.execution_epoch)
            except Exception:
                # An individual job must not kill the queue or expose exception text/secrets.
                if kind == "task":
                    with self.lock,self.db.atomic():
                        task = self.get(key)
                        task.status = "cancelled" if task.cancel_requested else "failed"
                        task.error_code = "worker_error"
                        task.usage = task.usage or Usage(estimated=True)
                        graph = None
                        if task.mode == "collaborative":
                            try:
                                graph = self.db.get("graphs", task.id)
                            except KeyError:
                                graph = {"task_id": task.id, "mode": task.mode, "plan": [], "subtasks": [], "reviews": [], "round": 0, "issues": []}
                            graph = {**graph, "status": task.status, "issues": [*graph.get("issues", []), "worker_error"]}
                        report = AnalysisResult(status=task.status, mode=task.mode, usage=task.usage, limitations=["worker_error"], markdown="# RepoLens investigation\n\n- worker_error", role_usage=(graph or {}).get("role_usage", {}))
                        self._save(task, "task_finished", {"status": task.status, "error_code": "worker_error", "usage": task.usage.model_dump()}, report=report, graph=graph)
            finally:
                self.queue.task_done()

    def _import(self, snapshot_id):
        snapshot = self.db.get_snapshot(snapshot_id)
        if snapshot.status!='importing':return
        archive_path = None
        download_owned = False
        try:
            if self.stopping.is_set():
                raise ValueError("import_interrupted")
            if snapshot.source_type == "github":
                adapter = self.github_client_factory(self.settings)
                adapter.cancelled = self.stopping.is_set
                resolved = adapter.resolve(GitHubSource.parse(snapshot.source, snapshot.requested_ref))
                snapshot.commit_sha = resolved.commit_sha
                self.db.put_snapshot(snapshot)
                archive_path = self.settings.data_dir.resolve() / "downloads" / f"{snapshot_id}.zip"
                adapter.download_archive(resolved, archive_path)
                download_owned = True
                snapshot = import_github_snapshot(resolved, archive_path, self.settings, snapshot_id, cancelled=self.stopping.is_set)
            else:
                snapshot = create_snapshot(snapshot.source, self.settings, snapshot_id)
            snapshot.status = "importing"
            self.db.put_snapshot(snapshot)
            build_index(snapshot, self.db, cancelled=self.stopping.is_set)
            if self.stopping.is_set():
                raise ValueError("import_interrupted")
        except Exception as exc:
            snapshot.status = "failed"
            snapshot.error_code = str(exc) if isinstance(exc, ValueError) else "import_failed"
            if not cleanup_import(self.settings, snapshot_id, snapshot=True, download=download_owned):
                snapshot.error_code = "import_cleanup_failed"
            self.db.put_snapshot(snapshot)
        finally:
            if download_owned:
                cleanup_import(self.settings, snapshot_id, download=True)

    def _execute(self, task_id):
        with self.lock,self.db.atomic():
            task = self.get(task_id)
            if task.status != "queued":
                return
            task.status = "running"
            task.execution_epoch+=1;task.resume_available=False
            self._save(task, "task_started", {"status": "running"})
            epoch=task.execution_epoch

        def cancelled():
            return (self.stopping.is_set() and not task.recovery_enabled) or self.get(task_id).cancel_requested

        def emit(event):
            with self.lock,self.db.atomic():
                current = self.get(task_id)
                if "usage" in event.payload:
                    usage = Usage.model_validate(event.payload["usage"])
                    if current.usage is None or usage.revision >= current.usage.revision:
                        current.usage = usage
                graph = event.payload.get("graph")
                payload = event.payload
                if graph is not None:
                    graph = {**graph, "status": current.status}
                    payload = {**payload, "graph": graph}
                self._save(current, event.type, payload, graph=graph,execution_epoch=epoch)

        runner = CollaborativeRunner(self.model, self.registry, self.settings) if task.mode == "collaborative" else DurableSingleRunner(self.model,self.registry,self.settings) if task.recovery_enabled else AgentRunner(self.model, self.registry, self.settings)
        context = ToolContext(snapshot_id=task.snapshot_id, task_id=task_id, retrieval_mode=task.retrieval_mode, rerank=task.rerank, retrieval_index_id=task.retrieval_configuration.get("index_id"))
        context.document_ids=task.document_ids
        result = None
        if task.retrieval_mode == "hybrid":
            try:
                if self.retrieval.ready(task.snapshot_id)["id"] != context.retrieval_index_id:
                    raise ValueError("retrieval_configuration_changed")
            except ValueError as exc:
                result = AnalysisResult(status="failed", usage=Usage(), mode=task.mode, limitations=[str(exc)])
                if task.recovery_enabled and saved_run(self.db,task_id):
                    try:runner.last_view=self.db.get('graphs',task_id)
                    except KeyError:pass
                    result=paused_report(self.db,task,runner.last_view)
                    result.status='failed';result.limitations=[str(exc)]
                    result.markdown=render_report(result.claims,result.limitations)
        if result is None:
            try:
                if task.recovery_enabled:
                    current=signature(task,self.settings,self.db)
                    if digest(current)!=task.recovery_config_hash:raise RecoveryRejected('recovery_configuration_changed')
                    session=ExecutionSession(self.db,task_id,epoch,self.lease,current,seconds=self.settings.max_seconds,stopping=self.stopping.is_set)
                    result=runner.run(task.question,context,emit,cancelled,session=session)
                else:result = runner.run(task.question, context, emit, cancelled)
            except WorkerPaused:
                self._pause(task_id,runner);return
        with self.lock,self.db.atomic():
            task = self.get(task_id)
            task.status = "cancelled" if task.cancel_requested else result.status
            result.status = task.status
            task.usage = result.usage
            task.resume_available=False;task.recovery_error=None
            if result.status == "failed":
                task.error_code = result.limitations[0] if result.limitations else "analysis_failed"
            graph = getattr(runner, "last_view", None)
            if graph is not None:
                graph = {**graph, "status": task.status}
            self._save(task, "task_finished", {"status": task.status, "error_code": task.error_code, "usage": task.usage.model_dump()}, report=result, graph=graph,execution_epoch=epoch)
