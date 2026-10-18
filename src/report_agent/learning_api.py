"""Local operator endpoints; protected by the workbench's same-origin middleware."""
from fastapi import HTTPException
from pydantic import BaseModel, Field

from .content_models import Ref
from .learning import binding, submit_feedback


class FeedbackInput(BaseModel):
    snapshot_ref: Ref
    target_ref: Ref
    correction: str = Field(min_length=1)
    evidence_refs: list[Ref] = Field(min_length=1)


class ReleaseInput(BaseModel):
    version: int | None = Field(default=None, ge=1)
    reason: str = Field(min_length=1)


class RevisionInput(BaseModel):
    expected_version: int = Field(ge=1)
    title: str = Field(min_length=1)
    strategy: str = Field(min_length=1)
    conditions: str = Field(min_length=1)
    verification: str = Field(min_length=1)


def register_learning_routes(app, workspace):
    def configured():
        result = binding(workspace)
        if not result:
            raise HTTPException(409, "LEARNING_NOT_CONFIGURED")
        return result

    @app.get("/api/learning")
    def learning_state():
        library, scope = configured()
        return {"feedback": library.feedback_items(scope), "experience": library.list_versions(scope),
                "queue": library.queue_status(scope), "job": workspace.store.get("learning_job")}

    @app.get("/api/learning/reports")
    def reports():
        configured()
        from .content_store import ContentStore
        from .content_models import refs_in
        contents = ContentStore(workspace.store)
        result = []
        for snapshot in contents.list_objects("DocumentSnapshot"):
            targets, seen = [], set()
            for ref in [snapshot["ref"], *[r.model_dump() for r in refs_in(snapshot["payload"])]]:
                key = (ref["type"], ref["id"], ref["version"])
                if key in seen:
                    continue
                seen.add(key)
                payload = contents.read(ref)["payload"]
                label = (payload.get("title") or payload.get("text") or payload.get("body", {}).get("text")
                         or payload.get("purpose") or payload.get("excerpt") or ref["type"])
                targets.append({"ref": ref, "label": str(label)[:160],
                                "payload": payload})
            result.append({"ref": snapshot["ref"], "created_at": snapshot["created_at"], "targets": targets})
        return {"reports": result}

    @app.get("/api/learning/evidence")
    def evidence():
        configured()
        from .content_store import ContentStore
        contents = ContentStore(workspace.store)
        items = []
        for kind in ("Evidence", "SourceArtifact"):
            for record in contents.list_objects(kind):
                payload = record["payload"]
                metadata = payload.get("source_metadata", {})
                label = (payload.get("locator") or metadata.get("title") or payload.get("source_id") or kind)
                items.append({"ref": record["ref"], "label": str(label),
                              "excerpt": str(payload.get("excerpt") or payload.get("content") or "")[:1200]})
        return {"items": items}

    @app.post("/api/learning/feedback", status_code=201)
    def feedback(body: FeedbackInput):
        configured()
        try:
            return submit_feedback(workspace, body.snapshot_ref.model_dump(), body.target_ref.model_dump(),
                                   body.correction, [r.model_dump() for r in body.evidence_refs])
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None

    @app.post("/api/learning/experience/{identifier}/revision", status_code=201)
    def revise(identifier: str, body: RevisionInput):
        library, scope = configured()
        candidates = [item for item in library.list_versions(scope) if item["id"] == identifier]
        if not candidates:
            raise HTTPException(404, "EXPERIENCE_NOT_FOUND")
        current = max(candidates, key=lambda item: item["version"])
        if current["version"] != body.expected_version:
            raise HTTPException(409, "EXPERIENCE_VERSION_CONFLICT")
        try:
            return library.propose(scope, current["feedback_ids"], current["kind"], body.title,
                                   body.strategy, body.conditions, body.verification,
                                   experience_id=identifier, expected_version=body.expected_version)
        except ValueError as exc:
            raise HTTPException(409 if str(exc) == "EXPERIENCE_VERSION_CONFLICT" else 400, str(exc)) from None

    @app.post("/api/learning/experience/{identifier}/release")
    def release(identifier: str, body: ReleaseInput):
        library, scope = configured()
        try:
            return library.release(scope, identifier, body.version, body.reason)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from None
