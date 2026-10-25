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
    from .learning_api import register_learning_routes
    register_learning_routes(app, ws)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"])

    @app.middleware("http")
    async def local_actions(request: Request, call_next):
        if request.method != "GET":
            origin = request.headers.get("origin")
            expected = f'{request.url.scheme}://{request.headers.get("host", "")}'
            if request.headers.get("x-report-action") != "1" or (origin and origin != expected):
                return Response("Explicit same-origin action required", status_code=403)
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; frame-ancestors 'none'"
        return response

    def model_configured():
        return all(os.environ.get(k) for k in ("REPORT_MODEL", "REPORT_BASE_URL", "REPORT_API_KEY"))

    def can_run():
        from .deep_runtime import require_native_runtime
        try:
            require_native_runtime(ws)
        except (ValueError, RuntimeError):
            return False
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
        from .native_trace import recent_tool_events
        # Native history supplies current tool observations. Old stored events
        # remain available for historical runs; no new transcript is persisted.
        native = recent_tool_events(ws.store.root.resolve(), ws.store.get("native_trace_thread_id"))
        if native:
            events = [e for e in events if e["kind"] not in {"deep_tool_start", "deep_tool_end", "deep_tool_rejected"}]
            events = sorted([*events, *native], key=lambda e: e["at"].replace(" ", "T"))[-100:]
        result.update(can_run=runnable,
                      runtime=ws.store.get("runtime", "deepagents-0.7.19"),
                      checkpoint_resume=ws.store.get("checkpoint_resume", False),
                      native_interrupts=ws.store.get("native_interrupts", []),
                      agent_summary=ws.store.get("agent_summary", ""),
                      model_mode=ws.store.get("model_mode") or ("configured" if model_configured() else "unconfigured"),
                      events=[{"sequence": e["sequence"], "at": e["at"], "kind": e["kind"],
                               "data": {k: e["data"][k] for k in ("task_id", "result_id", "type", "http_status", "role", "tool", "tool_call_id", "resume", "message", "observation", "source") if k in e["data"] and (k != "message" or e["kind"] in {"deep_tool_rejected", "deep_run_error"})}}
                              for e in events])
        return result

    @app.get("/api/content/review-status")
    def content_review_status(offset: int = 0, limit: int = 20):
        from .content_store import ContentStore
        from .review_status import read_status
        from .errors import ActionRejected
        selected = ws.store.get("content_delivery")
        if not selected:
            raise HTTPException(404, "NO_CONTENT_DELIVERY")
        try:
            return read_status(ContentStore(ws.store), selected["snapshot_ref"],
                               export_ref=selected["export_ref"], offset=offset, limit=limit)
        except ActionRejected as exc:
            raise HTTPException(400, str(exc)) from None

    @app.get("/api/content/delivery")
    def content_delivery_file(companion: bool = False, expected_export_id: str | None = None):
        from .content_store import ContentStore
        from .content_export import _bytes
        selected = ws.store.get("content_delivery")
        if not selected:
            raise HTTPException(404, "NO_CONTENT_DELIVERY")
        if expected_export_id is not None and expected_export_id != selected['export_ref']['id']:
            raise HTTPException(409, 'DELIVERY_SELECTION_CHANGED')
        contents = ContentStore(ws.store)
        ref = selected.get('workbook_export_ref') if companion else selected['export_ref']
        if ref is None:
            raise HTTPException(404, 'NO_COMPANION_WORKBOOK')
        artifact = contents.read(ref)['payload']
        if artifact.get('snapshot_ref') != selected['snapshot_ref'] or (companion and (
                not artifact.get('file_ref', '').endswith('.xlsx') or
                artifact.get('export_config', {}).get('report_export_ref') != selected['export_ref'])):
            raise HTTPException(409, 'DELIVERY_VERSION_MISMATCH')
        suffix = Path(artifact['file_ref']).suffix
        media = {'.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                 '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'}
        if suffix not in media:
            raise HTTPException(400, 'DELIVERY_FORMAT_UNSUPPORTED')
        return Response(_bytes(ws.store, artifact["file_ref"], artifact["file_digest"]),
            media_type=media[suffix],
            headers={"Content-Disposition": f'attachment; filename="review-draft{suffix}"'})

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
        from .deep_runtime import require_native_runtime
        try:
            require_native_runtime(ws)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
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
