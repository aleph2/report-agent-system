from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .exporting import export_docx
from .catalog import Catalog
from .deep_models import error_data
from .deep_runtime import run_report
from .store import Store
from .workspace import Workspace
from .knowledge_state import project_state


class Decision(BaseModel):
    message: str
    resolved: bool = False


class Correction(BaseModel):
    result_id: str
    description: str


def create_app(project: Path, model_factory=None, *, allow_fixture_run=False):
    ws = Workspace(Store(project))
    worker = None

    @asynccontextmanager
    async def lifespan(app):
        yield
        if worker and not worker.done():
            worker.cancel()
            try:
                await worker
            except asyncio.CancelledError:
                pass

    app = FastAPI(lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"])

    @app.middleware("http")
    async def local_actions(request: Request, call_next):
        if request.method != "GET":
            origin = request.headers.get("origin")
            expected = f'{request.url.scheme}://{request.headers.get("host", "")}'
            if request.headers.get("x-report-action") != "1" or (origin and origin != expected):
                return Response("Explicit same-origin action required", status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; frame-ancestors 'none'"
        return response

    def model_configured():
        return all(os.environ.get(k) for k in ("REPORT_MODEL", "REPORT_BASE_URL", "REPORT_API_KEY"))

    def can_run():
        if worker and not worker.done():
            return False
        try:
            with ws.store.run_lock():
                pass
        except RuntimeError:
            return False
        if ws.store.get("model_mode") == "scripted_fixture":
            return model_factory is not None and allow_fixture_run
        return model_configured()

    @app.get("/api/status")
    def status():
        result = project_state(ws)
        runnable = can_run()
        if result["status"] == "running" and not (worker and not worker.done()):
            try:
                with ws.store.run_lock():
                    result["status"] = "interrupted"
                    result["last_error"] = {"type": "WorkerStopped", "message": "WORKER_STOPPED_RESUME_AVAILABLE"}
            except RuntimeError:
                pass
        result["last_error"] = result["last_error"] or ws.store.get("run_request_error")
        # Never return raw model prompts/reasoning or provider payloads as GUI logs.
        events = ws.store.events(limit=100)
        result.update(can_run=runnable,
                      runtime=ws.store.get("runtime", "deepagents-0.7.19"),
                      checkpoint_resume=ws.store.get("checkpoint_resume", False),
                      native_interrupts=ws.store.get("native_interrupts", []),
                      agent_summary=ws.store.get("agent_summary", ""),
                      model_mode=ws.store.get("model_mode") or ("configured" if model_configured() else "unconfigured"),
                      events=[{"sequence": e["sequence"], "at": e["at"], "kind": e["kind"],
                               "data": {k: e["data"][k] for k in ("task_id", "result_id", "type", "http_status", "role", "tool", "tool_call_id", "resume", "message") if k in e["data"] and (k != "message" or e["kind"] in {"deep_tool_rejected", "deep_run_error"})}}
                              for e in events])
        return result

    async def run_guarded():
        try:
            await run_report(ws, model_factory)
        except Exception as exc:
            # A concurrent CLI run may own the lock. Never change its execution state.
            ws.store.event("run_not_started", error_data(exc))
            ws.store.set("run_request_error", error_data(exc))

    @app.post("/api/run", status_code=202)
    async def run():
        nonlocal worker
        if worker and not worker.done():
            raise HTTPException(409, "PROJECT_ALREADY_RUNNING")
        if not can_run():
            raise HTTPException(409, "MODEL_NOT_CONFIGURED_OR_FIXTURE_READ_ONLY")
        try:
            with ws.store.run_lock():
                pass
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from None
        # Explicit user action only. Status polling never dispatches work.
        ws.store.set("run_request_error", None)
        worker = asyncio.create_task(run_guarded())
        return {"accepted": True}

    @app.post("/api/issues/{issue_id}/decision")
    def decision(issue_id: str, body: Decision):
        try:
            return ws.decide_issue(issue_id, body.message, resolved=body.resolved)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(409, str(exc)) from None

    @app.post("/api/sources")
    async def import_source(request: Request, filename: str, replaces_id: str = ""):
        # Bound the request while streaming, not after buffering untrusted bytes.
        from .ingestion import MAX_UPLOAD_BYTES
        content = bytearray()
        async for chunk in request.stream():
            if len(content) + len(chunk) > MAX_UPLOAD_BYTES:
                raise HTTPException(413, "UPLOAD_TOO_LARGE")
            content.extend(chunk)
        try:
            return await asyncio.to_thread(Catalog(ws.store).import_file, filename, bytes(content), replaces_id)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(409, str(exc)) from None

    @app.get("/api/sources/{source_id}")
    def source_page(source_id: str, offset: int = 0, limit: int = 10):
        try:
            return Catalog(ws.store).read(source_id, offset, limit)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None

    @app.get("/api/library/search")
    def search(q: str, offset: int = 0, limit: int = 10):
        try:
            return Catalog(ws.store).search(q, offset, limit)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None

    @app.post("/api/corrections")
    def correction(body: Correction):
        try:
            with ws.store.run_lock():
                return ws.request_correction(body.result_id, body.description)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(409, str(exc)) from None

    @app.get("/api/export/{draft_id}")
    def export(draft_id: str):
        try:
            data = export_docx(ws, draft_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from None
        return Response(data, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        headers={"Content-Disposition": 'attachment; filename="report-draft.docx"'})

    static = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static, check_dir=False), name="static")

    @app.get("/")
    def index():
        return FileResponse(static / "index.html")

    return app
