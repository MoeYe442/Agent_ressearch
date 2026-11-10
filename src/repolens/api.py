import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse
from fastapi import FastAPI, Request, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware
from repolens.evidence import EvidenceStore
from repolens.model_client import configured_model
from repolens.storage import Database
from repolens.tasks import TaskService, TERMINAL


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=2000)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=100)


class TaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snapshot_id: str = Field(min_length=1, max_length=100)
    question: str = Field(min_length=1, max_length=10000, pattern=r"\S")
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=100)


def create_app(settings, model=None):
    db = Database(settings.data_dir / "repolens.sqlite")
    service = TaskService(settings, db, model if model is not None else configured_model(settings))

    @asynccontextmanager
    async def lifespan(app):
        service.start()
        yield
        await asyncio.to_thread(service.stop)

    app = FastAPI(title="RepoLens", version="0.1.0", lifespan=lifespan)
    app.state.service, app.state.db = service, db
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "[::1]", "testserver"])

    @app.middleware("http")
    async def local_only(request, call_next):
        if request.client and request.client.host not in {"127.0.0.1", "::1", "localhost"}:
            return JSONResponse({"error_code": "local_access_only"}, status_code=403)
        origin = request.headers.get("origin")
        if request.method == "POST" and origin and origin != str(request.base_url).rstrip("/"):
            return JSONResponse({"error_code": "cross_origin_forbidden"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        return response

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        return JSONResponse({"error_code": "not_found"}, status_code=404)

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        code = str(exc)
        return JSONResponse({"error_code": code}, status_code=409 if code in {"idempotency_conflict", "snapshot_not_ready"} else 400)

    @app.exception_handler(RequestValidationError)
    async def bad_request(request, exc):
        return JSONResponse({"error_code": "invalid_request"}, status_code=422)

    @app.get("/health")
    def health():
        return {"status": "ok", "model_configured": service.model is not None, "test_environment": settings.test_environment, "workspace_root": str(settings.workspace_root.resolve()), "version": "0.1.0"}

    @app.post("/repositories", status_code=202)
    def import_repository(body: ImportRequest):
        return service.import_repository(Path(body.path), body.idempotency_key)

    @app.get("/repositories")
    def repositories():
        return db.all("snapshots")

    @app.get("/repositories/{snapshot_id}")
    def repository(snapshot_id: str):
        snapshot = db.get_snapshot(snapshot_id)
        result = snapshot.model_dump(mode="json")
        if snapshot.status == "ready":
            try:
                result["index"] = db.get("indexes", snapshot_id)
            except KeyError:
                result["status"] = "importing"
        return result

    @app.post("/tasks", status_code=202)
    def submit(body: TaskRequest):
        # Index is committed before a snapshot becomes eligible for analysis.
        db.get("indexes", body.snapshot_id)
        return service.submit(body.snapshot_id, body.question.strip(), body.idempotency_key)

    @app.get("/tasks")
    def tasks():
        return db.all("tasks")

    @app.get("/tasks/{task_id}")
    def task(task_id: str):
        return service.get(task_id)

    @app.post("/tasks/{task_id}/cancel")
    def cancel(task_id: str):
        return service.cancel(task_id)

    @app.get("/tasks/{task_id}/report")
    def report(task_id: str):
        task = service.get(task_id)
        try:
            result = db.get("reports", task_id)
            if task.status not in TERMINAL or result["status"] != task.status:
                return JSONResponse({"error_code": "report_not_ready"}, status_code=409)
            return result
        except KeyError:
            return JSONResponse({"error_code": "report_not_ready"}, status_code=409)

    @app.get("/evidence/{evidence_id}")
    def evidence(evidence_id: str):
        return EvidenceStore(db).get(evidence_id)

    @app.get("/tasks/{task_id}/events")
    async def events(task_id: str, request: Request, after: int = 0):
        service.get(task_id)
        try:
            cursor = max(0, after, int(request.headers.get("Last-Event-ID", "0")))
        except ValueError:
            raise ValueError("invalid_event_cursor")

        async def stream():
            nonlocal cursor
            while True:
                if await request.is_disconnected():
                    return
                batch = await asyncio.to_thread(service.events, task_id, cursor)
                for event in batch:
                    cursor = event.sequence
                    yield f"id: {event.sequence}\nevent: task\ndata: {event.model_dump_json()}\n\n"
                current = await asyncio.to_thread(service.get, task_id)
                if current.status in TERMINAL:
                    # Flush events committed between first read and terminal state read.
                    for event in await asyncio.to_thread(service.events, task_id, cursor):
                        cursor = event.sequence
                        yield f"id: {event.sequence}\nevent: task\ndata: {event.model_dump_json()}\n\n"
                    yield f"event: end\ndata: {{\"status\":\"{current.status}\"}}\n\n"
                    return
                yield ": keepalive\n\n"
                await asyncio.sleep(0.25)
        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # Frontend files are added in Task 5.
    assets = Path(__file__).parent
    if (assets / "static").exists():
        app.mount("/static", StaticFiles(directory=assets / "static"), name="static")
    templates = Jinja2Templates(directory=assets / "templates")

    @app.get("/")
    def workspace(request: Request):
        return templates.TemplateResponse(request=request, name="workspace.html", context={})

    return app
