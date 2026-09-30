"""Business tools bound by the server to a project and a responsible actor."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from .content_models import Ref, ReviewSubmission, SCHEMA_VERSION
from .content_store import Actor, ContentStore
from .errors import ActionForbidden, ActionRejected
from .store import encode, digest
from .content_delivery import current_delivery


def enabled(workspace):
    return hasattr(workspace, "store") and workspace.store.manifest.get("content_contract") == SCHEMA_VERSION


def role_prompt(role):
    folder = Path(__file__).parent / "rules"
    return (folder / "content-common.md").read_text(encoding="utf-8") + "\n\n" + (folder / f"content-{role}.md").read_text(encoding="utf-8")


def actor_for(role):
    # Stable top-level producer / final grader identities. Delegated tools resolve
    # their actual task identity through the server binding; no shared fallback.
    return Actor("content:" + role, role, "content-task:" + role)


def content_tools(workspace, role, runtime_identity=None):
    contents, fallback = ContentStore(workspace.store), actor_for(role)
    def actor():
        from .content_tasks import bound_actor
        return bound_actor(workspace, role, fallback)
    identity = runtime_identity or {"contract": SCHEMA_VERSION, "runtime": "deepagents-0.7.19"}

    def content_status() -> dict:
        """List immutable object identities and current selected content delivery; not an approval."""
        return {"actor": actor().__dict__, "objects": [{k: r[k] for k in ("ref", "previous_ref", "owner_id", "task_id", "payload_digest")} for r in contents.list_objects()],
                "delivery": workspace.store.get("content_delivery"), "final_review": workspace.store.get("content_final_review"),
                "current_review": current_delivery(workspace.store),
                "goal": workspace.store.manifest["goal"], "scope_instruction": workspace.store.manifest.get("scope_instruction"),
                "sources": workspace.store.source_catalog()}

    def read_context(target_ref: Ref, offset: int = 0, limit: int = 20) -> dict:
        """Read actual saved objects or a paged snapshot, including unreturned refs and continuation.

        For local investigation read nodes, their containing snapshot's relations and needed
        parents/dependencies. Initial local scope does not restrict independent source access.
        """
        return contents.read_context(actor(), target_ref.model_dump(), offset, limit)

    def import_source_versions(operation_id: str, source_ids: list[str]) -> dict:
        """Snapshot authorized source text/metadata and the unchanged commission; no interpretation."""
        return contents.import_inputs(actor(), operation_id, source_ids)

    def capture_review_sources(operation_id: str, source_ids: list[str]) -> dict:
        """Capture exact authorized source versions discovered independently during review.
        No requirement, author evidence, content or snapshot is changed. Put adopted
        source_refs in review dependency_refs; capture alone asserts no support.
        """
        return contents.capture_sources(actor(), operation_id, source_ids)

    def commit_objects(operation_id: str, objects: list[dict]) -> dict:
        """Commit your owned typed objects atomically. Each has client_key, type, payload,
        optional previous_ref (compare-and-swap exact head). No model-generated IDs/versions.
        In payloads use {client_key: key} to refer to another new object in this batch.
        Types: Criterion (coordinator only), ContentNode, Evidence, Relation.
        Criterion: requirement_refs,purpose,scope,expected_outcome,evidence_expectation,allowed_limits.
        ContentNode: kind,body,qualifiers,claim_kind. Text body={text:...}; table={columns:[],rows:[[]]}.
        Evidence: source_refs,locator,excerpt; computation also input_refs,method,tool_receipt,result.
        Relation: subject_ref,predicate,object_ref,provenance_kind; contains also position.
        Relations are author assertions, not verification. Revise only your own records.
        """
        return contents.commit(actor(), operation_id, objects)

    def freeze_snapshot(operation_id: str, root_ref: Ref, refs: list[Ref]) -> dict:
        """Freeze an explicit complete version manifest, including criteria and reference closure.
        This validates structure, not correctness. Export need not wait for all reviews.
        """
        return contents.freeze(actor(), operation_id, root_ref.model_dump(), [r.model_dump() for r in refs])

    def submit_review(operation_id: str, review: ReviewSubmission) -> dict:
        """Save scoped observations and findings against an exact snapshot. Does not revise content,
        finish the project or trigger author actions. Observation receipts come from read_context,
        observe_evidence, read_content_export or inspect_rendered_page. Null means no judgment yet.
        """
        return contents.submit_review(actor(), operation_id, review.model_dump(), identity)

    def observe_evidence(kind: Literal["source", "calculation"], source_id: str = "", offset: int = 0,
                         limit: int = 12000, terms: list[list[str]] | None = None) -> dict:
        """Read an authorized source excerpt or independently recompute a sum of products,
        returning a saved observation receipt. No model evaluation is hidden in this tool.
        Source offset/limit are characters; continue at next_offset for unread material.
        """
        if kind == "source":
            if offset < 0 or not 1 <= limit <= 16000:
                raise ActionRejected("INVALID_PAGE")
            source = workspace.store.sources([source_id])[0]
            text = source["content"]
            result = {"source_id": source_id, "source_digest": digest(source), "text": text[offset:offset + limit],
                "range": [offset, min(offset + limit, len(text))], "total": len(text),
                "next_offset": offset + limit if offset + limit < len(text) else None,
                "coverage": source["coverage"], "limitations": source.get("limitations", [])}
        else:
            from .calculations import sum_products
            result = {"terms": terms, "result": sum_products(terms or []), "tool": "sum_products"}
        return contents.observe(actor(), result)

    def read_feedback(offset: int = 0, limit: int = 20) -> dict:
        """Query project-local versioned findings and handling history. Handled is not repaired;
        historical verdicts do not automatically apply to new snapshots. No broadcast or rerun.
        """
        return contents.feedback(actor(), offset, limit)

    def record_handoff(operation_id: str, target_ref: Ref, problem: str, evidence: list[str], impact: str,
                       handling_state: Literal["open", "in_progress", "handled"] = "open",
                       previous_ref: Ref | None = None) -> dict:
        """Append a transfer/handling record without changing any verdict. No assignee,
        next action or resume condition is required. Evidence may be empty with an honest reason.
        """
        return contents.handoff(actor(), operation_id, target_ref.model_dump(), problem, evidence, impact,
            handling_state=handling_state, previous_ref=previous_ref.model_dump() if previous_ref else None)

    def assess_change_impact(old_snapshot: Ref, new_snapshot: Ref) -> dict:
        """Return changed references and dependency candidates. You decide semantic recheck scope."""
        return contents.impact(old_snapshot.model_dump(), new_snapshot.model_dump())

    def confirm_review_reuse(operation_id: str, review_ref: Ref, new_snapshot: Ref, reason: str) -> dict:
        """Explicitly confirm that a prior local review still applies to unchanged inputs.
        Check changes, new relevance and relationships first. Whole-document judgments
        cannot be transferred to a different snapshot; changed inputs need a new review.
        """
        return contents.confirm_reuse(actor(), operation_id, review_ref.model_dump(), new_snapshot.model_dump(), reason)

    def correct_own_review(operation_id: str, review_ref: Ref, replacement_ref: Ref, reason: str) -> dict:
        """Correct your own mistaken review with an already saved evidence-based replacement.
        Preserve both records and an explicit reason; handling a finding does not withdraw it.
        """
        return contents.supersede_review(actor(), operation_id, review_ref.model_dump(), replacement_ref.model_dump(), reason)

    def get_operation_receipt(operation_id: str) -> dict:
        """Check your exact write operation before retrying after timeout; unknown is not no-write."""
        return contents.receipt(actor(), operation_id)

    def export_content_snapshot(operation_id: str, snapshot_ref: Ref) -> dict:
        """Export your immutable snapshot to DOCX with version-bound content position mapping."""
        from .content_export import export_snapshot
        return export_snapshot(contents, actor(), operation_id, snapshot_ref.model_dump())

    def render_content_export(operation_id: str, export_ref: Ref) -> dict:
        """Render this exact export to PDF/pages, or return blocked. Rendering is not visual review."""
        from .content_export import render_export
        return render_export(contents, actor(), operation_id, export_ref.model_dump())

    def read_content_export(export_ref: Ref) -> dict:
        """Read actual DOCX text and structure with identity and a receipt; not page observation."""
        from .content_export import read_export
        return read_export(contents, actor(), export_ref.model_dump())

    async def inspect_rendered_page(render_ref: Ref, page: int, question: str) -> dict:
        """Ask the configured visual model about one actual rendered page. Returns bounded
        observations with a receipt and limitations, not a verdict; consumes a model call.
        """
        from .content_export import inspect_render
        return await inspect_render(contents, actor(), render_ref.model_dump(), page, question)

    def select_content_delivery(operation_id: str, snapshot_ref: Ref, export_ref: Ref,
                                 ending_reason: Literal["continue", "preserve_unresolved", "blocked", "no_progress"] = "continue") -> dict:
        """Select the actual snapshot/export for native final review. This is not approval.
        Declare a justified stop when further work is blocked or no longer progresses;
        stopping never changes the review verdict. Local review records alone do not approve delivery.
        """
        def select(db):
            snap, export = contents._read(db, snapshot_ref.model_dump()), contents._read(db, export_ref.model_dump())
            if snapshot_ref.type != "DocumentSnapshot" or export_ref.type != "ExportArtifact" or export["payload"]["snapshot_ref"] != snap["ref"]:
                raise ActionRejected("DELIVERY_VERSION_MISMATCH")
            delivery = {"snapshot_ref": snap["ref"], "export_ref": export["ref"], "ending_reason": ending_reason}
            db.execute("INSERT OR REPLACE INTO state VALUES ('content_delivery', ?)", (encode(delivery),))
            # Retain historical final evidence; applicability is checked against the
            # exact selected snapshot/export. Reselecting cannot erase a known defect.
            return delivery
        return contents.operation(actor(), operation_id, {"select_delivery": [snapshot_ref.model_dump(), export_ref.model_dump(), ending_reason]}, select)

    common = [content_status, read_context, observe_evidence, read_feedback, record_handoff,
              assess_change_impact, get_operation_receipt, read_content_export, render_content_export, inspect_rendered_page]
    if role in {"reviewer", "rubric_grader"}:
        return common + [capture_review_sources, submit_review, confirm_review_reuse, correct_own_review]
    if role in {"coordinator", "writer"}:
        common += [import_source_versions, commit_objects, freeze_snapshot, export_content_snapshot]
    if role == "coordinator":
        common += [select_content_delivery]
    return common
