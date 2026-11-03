"""Business tools bound by the server to a project and a responsible actor."""
from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal
from pydantic import Field
from langchain.tools import ToolRuntime

from .content_models import Ref, ReviewSubmission, SCHEMA_VERSION, SnapshotReplacement
from .content_inputs import CommitObject
from .content_store import Actor, ContentStore
from .errors import ActionForbidden, ActionRejected
from .store import encode, digest
from .content_delivery import current_delivery
from .content_layout import LayoutOptions
from .content_workbook import WorkbookSheet
from .content_selection import ContentSelection, content_index, selected_content
from .deliverables import DeliverableSelection, DeliverableHandle
from .review_binding import ReuseMapping
from .handoff_release import manifest as bound_manifest
from .commission_plan import CommissionPlan
from .risk_scoring import Assessment


def enabled(workspace):
    return hasattr(workspace, "store") and bound_manifest(workspace.store).get("content_contract") == SCHEMA_VERSION


def role_prompt(role, *, expression_profile=None, interface_profile=None, prompt_profile='legacy-v1',
                review_submission_contract=None):
    from .prompt_sources import load_prompt, role_sources, REPORT_EXPRESSION_V1
    return '\n\n'.join(text for source in role_sources(role,
        expression_profile or REPORT_EXPRESSION_V1, interface_profile, prompt_profile, review_submission_contract)
        if (text := load_prompt(source)).strip())


def actor_for(role):
    # Stable top-level producer / final grader identities. Delegated tools resolve
    # their actual task identity through the server binding; no shared fallback.
    return Actor("content:" + role, role, "content-task:" + role)


def content_tools(workspace, role, runtime_identity=None, *, reviewer_handles=False):
    if reviewer_handles and role != 'reviewer':
        raise ActionForbidden('REVIEW_MESSAGE_TASK_BINDING_REQUIRED')
    contents, fallback = ContentStore(workspace.store), actor_for(role)
    def actor():
        from .content_tasks import bound_actor
        return bound_actor(workspace, role, fallback)
    from .prompt_sources import review_interface_profile, report_expression_profile, report_prompt_profile
    from .review_scope_selectors import validate_contract
    submission_contract = validate_contract(bound_manifest(workspace.store))
    selector_mode = role == 'reviewer' and submission_contract is not None
    effective_role = 'reviewer' if role == 'rubric_grader' else role
    role_options = ({'interface_profile':'review-interfaces-v4',
        'expression_profile':report_expression_profile(workspace.store), 'prompt_profile':report_prompt_profile(workspace.store)}
        if review_interface_profile(workspace.store) == 'review-interfaces-v4' else {})
    if selector_mode:
        role_options['review_submission_contract'] = submission_contract
    identity = runtime_identity or {"contract": SCHEMA_VERSION, "runtime": "deepagents-0.7.19",
        "role": role, "service": (workspace.store.get("role_model_services") or {}).get(role),
        "prompt_hash": digest(role_prompt(effective_role, **role_options))
            if role in {"coordinator", "writer", "reviewer", "rubric_grader", "layout"} else None}

    def content_status() -> dict:
        """Observe content state; not an approval. For pageable complete object identities,
        types, owners, versions and relations use read_object_index, even before a snapshot exists.
        """
        return {"actor": actor().__dict__, "objects": [{k: r[k] for k in ("ref", "previous_ref", "owner_id", "task_id", "payload_digest")} for r in contents.list_objects()],
                "delivery": workspace.store.get("content_delivery"), "final_review": workspace.store.get("content_final_review"),
                "current_review": current_delivery(workspace.store),
                "execution_decision": workspace.store.get("content_execution_decision"),
                "goal": bound_manifest(workspace.store)["goal"], "scope_instruction": bound_manifest(workspace.store).get("scope_instruction"),
                "sources": workspace.store.source_catalog()}

    def read_object_index(offset: Annotated[int, Field(ge=0)] = 0,
                          limit: Annotated[int, Field(ge=1, le=20)] = 20,
                          object_type: str = '', owner_id: str = '',
                          current_only: bool = False, inventory_digest: str = '') -> dict:
        """Page exact metadata for existing project objects before or after snapshot creation.
        No snapshot is required. Filter by exact object_type/owner_id or current_only.
        Returns whole refs, ownership, payload digests, node kinds/literal titles and relation
        endpoints, without report bodies. Use next_offset (may be less than limit), identical
        filters and returned inventory_digest on later pages. A changed filtered inventory
        rejects continuation; restart at zero. Project-wide available_types counts are
        auxiliary and may change independently. These refs do not grant authorship or choose a snapshot.
        """
        actor()
        from .object_index import object_index
        return object_index(contents, offset, limit, object_type, owner_id, current_only, inventory_digest)

    def read_task_supervision(offset: int = 0, limit: int = 20) -> dict:
        """Page existing reviewer assignments, matched saved checks and incomplete reasons.
        Bookkeeping is not semantic acceptance. Todos cannot remove these obligations.
        A returned follow-up consumes the task's one completion request even if still incomplete.
        """
        actor()
        from .task_supervision import task_status
        return {"ok": True, "result": task_status(contents, offset, limit)}

    def list_supervision_plugins() -> dict:
        """Inspect optional server-registered reviewer supervision plugins.
        Choose supervision_plugin on a new reviewer task, or omit it for none.
        Catalog selection does not broaden authorization or establish correctness.
        """
        actor()
        from .supervision_plugins import plugin_catalog
        return {"ok": True, "result": plugin_catalog()}

    def read_review_obligation_coverage(snapshot_ref: Ref) -> dict:
        """Compare independent criteria/requirements with actual assigned review scopes.
        This optional inventory exposes absent assignments; scope presence is not full semantic coverage.
        """
        actor()
        from .task_supervision import obligation_coverage
        return {"ok": True, "result": obligation_coverage(contents, snapshot_ref.model_dump())}

    def read_task_assignment(runtime: ToolRuntime = None) -> dict:
        """Read your server-bound delegated assignment and its saved completion requirements.
        These are scoped outcomes, not instructions hidden in source documents.
        """
        from .task_supervision import assignment, source_selection_bindings, review_readiness, readiness_metadata
        owner = actor()
        saved = assignment(contents, owner.task_id)
        from .review_scope_selectors import requirements_view
        visible = ({**saved, 'review_requirements': requirements_view(saved)}
                   if saved.get('review_submission_contract') is not None else saved)
        from .content_tasks import current_invocation, ASSIGNMENT_NOTE
        result = {"ok": True, "task_id": owner.task_id, "assignment": visible,
                  "assignment_note": ASSIGNMENT_NOTE,
                  "current_invocation": current_invocation(workspace, owner),
                  "source_selection_bindings": source_selection_bindings(contents, saved.get("review_requirements") or [])}
        from .source_use import resolve_source_use_binding, _policy
        policy_ref = resolve_source_use_binding(workspace, owner)
        if policy_ref:
            result['source_use'] = {'policy_ref': policy_ref,
                'versions': _policy(workspace.store, policy_ref)['versions'],
                'note': 'Exact enrolled source versions may supplement initial eligible materials for the same task. Choose captured refs and located selections explicitly; required materials and write permissions are unchanged.'}
        if saved.get('review_snapshot_ref') and saved.get('review_requirements'):
            result['readiness'] = review_readiness(contents, saved['review_snapshot_ref'], saved['review_requirements'],
                commission_basis=saved.get('review_commission_basis'))
            if runtime is not None:
                import hashlib
                from langchain_core.messages import ToolMessage
                text = encode(result)
                return ToolMessage(text, name='read_task_assignment', tool_call_id=runtime.tool_call_id,
                    artifact={'decision_metadata': {'original_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
                        'value': readiness_metadata(result['readiness'])}})
        return result

    def read_context(target_ref: Ref, offset: int = 0, limit: int = 20) -> dict:
        """Read actual saved objects or a paged snapshot, including unreturned refs and continuation.

        For local investigation read nodes, their containing snapshot's relations and needed
        parents/dependencies. Initial local scope does not restrict independent source access.
        """
        return contents.read_context(actor(), target_ref.model_dump(), offset, limit)

    def read_review_status(snapshot_ref: Ref, target_ref: Ref | None = None,
                           export_ref: Ref | None = None, offset: int = 0, limit: int = 20) -> dict:
        """Read version-scoped review state, including objects never reviewed, coverage,
        historical judgments, reuse/recheck candidates and independent handling chains.
        Optional target_ref selects one exact object; export_ref selects an exact export.
        This metadata grants no observation receipt or acceptance. Reviewers judge their
        declared scope; the coordinator chooses subsequent work from their feedback.
        """
        from .review_status import read_status
        actor()  # Enforce the same task binding as other delegated tools.
        return {"ok": True, "result": read_status(contents, snapshot_ref.model_dump(),
            target_ref.model_dump() if target_ref else None,
            export_ref.model_dump() if export_ref else None, offset, limit)}

    def read_content_index(snapshot_ref: Ref, offset: int = 0, limit: int = 20) -> dict:
        """Page through node identities, sizes and relations without loading report bodies.

        Returns all node kinds including parent/structure nodes and detached claims in
        manifest order; contains relations supply actual document order. Metadata is
        not an observation receipt or a claim that any node was reviewed.
        """
        owner = actor()
        index = content_index(contents, snapshot_ref.model_dump(), offset, limit)
        from .prompt_sources import native_reviewer
        if role == 'reviewer' and native_reviewer(workspace.store):
            # Actual structural observation only, never a whole-body receipt.
            return contents.observe(owner, {'snapshot_structure':index})
        return index

    def read_content_selection(snapshot_ref: Ref, selections: list[ContentSelection]) -> dict:
        """Read caller-selected exact nodes and ranges with an actor-bound receipt.

        Each selection has ref, unit=text/rows, offset, limit. Text limits are characters
        up to 16000; table limits are data rows up to 100 (headers always included).
        Returns qualifiers, exact versions, unreturned range and limits. No implicit
        descendants or sources are read; reading is not semantic review completion.
        """
        owner = actor()
        if not selections:
            raise ActionRejected("CONTENT_SELECTION_REQUIRED")
        return contents.observe(owner, {"snapshot_ref": snapshot_ref.model_dump(),
            "selections": selected_content(workspace, snapshot_ref.model_dump(), selections)})

    def import_source_versions(operation_id: str, source_ids: list[str]) -> dict:
        """Snapshot authorized source text/metadata and the unchanged commission; no interpretation."""
        return contents.import_inputs(actor(), operation_id, source_ids)

    def capture_review_sources(operation_id: str, source_ids: list[str]) -> dict:
        """Capture exact authorized source versions discovered independently during review.
        No requirement, author evidence, content or snapshot is changed. Put adopted
        source_refs in review dependency_refs; capture alone asserts no support.
        """
        return contents.capture_sources(actor(), operation_id, source_ids)

    def commit_objects(operation_id: str, objects: list[CommitObject]) -> dict:
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
        return commit_owned(operation_id, objects)

    def commit_owned(operation_id, objects, deliverable_selection=None):
        values = [obj.model_dump(exclude_unset=True) if hasattr(obj, "model_dump") else obj for obj in objects]
        if role == "coordinator" and bound_manifest(workspace.store).get("review_entrypoint") != "native-rubric-v1" and any(v["type"] == "ContentNode" for v in values):
            raise ActionForbidden("FORBIDDEN: report authorship belongs to writer; delegate or resume the content owner")
        if deliverable_selection is None:
            return contents.commit(actor(), operation_id, values)
        return contents.commit(actor(), operation_id, values, deliverable_selection=deliverable_selection)

    def save_text_node(operation_id: str, text: str,
                       kind: Literal["report", "chapter", "block", "cell", "claim"],
                       claim_kind: Literal["fact", "calculation", "inference", "recommendation", "structure"],
                       qualifications: str, previous_ref: Ref | None = None) -> dict:
        """Save one owned text node with flat arguments, avoiding a nested batch payload.
        Returns its exact ref. Qualifications describe conditions/limits. This does not
        create evidence links, publish a report or declare review acceptance. Use
        commit_objects for structured tables, evidence, relations or atomic batches.
        previous_ref revises only your own exact version; omit to create a new node.
        """
        return save_owned_text(operation_id, text, kind, claim_kind, qualifications, previous_ref)

    def save_owned_text(operation_id, text, kind, claim_kind, qualifications, previous_ref=None,
                        deliverable_selection=None):
        obj = {"client_key": "text", "type": "ContentNode", "payload": {
            "kind": kind, "body": {"text": text}, "claim_kind": claim_kind,
            "qualifiers": {"conditions": qualifications}}}
        if role == "coordinator" and bound_manifest(workspace.store).get("review_entrypoint") != "native-rubric-v1":
            raise ActionForbidden("FORBIDDEN: report authorship belongs to writer")
        if previous_ref is not None:
            obj["previous_ref"] = previous_ref.model_dump()
        if deliverable_selection is None:
            return contents.commit(actor(), operation_id, [obj])
        return contents.commit(actor(), operation_id, [obj], deliverable_selection=deliverable_selection)

    def freeze_snapshot(operation_id: str, root_ref: Ref, refs: list[Ref], workbook_refs: list[Ref] | None = None) -> dict:
        """Freeze an explicit complete version manifest, including criteria and reference closure.
        This validates structure, not correctness. Export need not wait for all reviews.
        Manifest members may only be Requirement, Criterion, SourceArtifact, Evidence,
        ContentNode or Relation, with exactly one selected version per logical object.
        Tasks, snapshots, exports and review records are not manifest members.

        root_ref and contains relations define report prose. Optional workbook_refs
        explicitly register workbook-only table or text-block nodes in the same
        manifest. They must be detached from the report tree, without contains
        parents/children; undeclared detached presentation nodes remain rejected.
        This keeps separate workbook notes outside Word without changing content
        or ownership. An XLSX export must select all and only the registered
        workbook_refs when this channel is declared. Choose applicability and
        organization from the assignment; registration is not semantic approval.
        """
        return contents.freeze(actor(), operation_id, root_ref.model_dump(), [r.model_dump() for r in refs],
                               [r.model_dump() for r in workbook_refs] if workbook_refs else None)

    def freeze_snapshot_with_receipts(operation_id: str, root_ref: Ref, refs: list[Ref],
            workbook_refs: list[Ref] | None = None, saved_receipt_ids: list[str] | None = None) -> dict:
        """Freeze exact explicit references and selected successful save receipts."""
        return contents.freeze(actor(), operation_id, root_ref.model_dump(), [r.model_dump() for r in refs],
            [r.model_dump() for r in workbook_refs] if workbook_refs else None, saved_receipt_ids)

    def derive_snapshot(operation_id: str, base_snapshot_ref: Ref, additional_refs: list[Ref],
                        replacements: list[SnapshotReplacement] | None = None,
                        workbook_refs: list[Ref] | None = None) -> dict:
        """Create a snapshot from an exact immutable base and explicit saved version deltas.

        Existing members need not be copied into arguments. additional_refs adds exact
        new members; replacements maps exact base previous_ref to new_ref of the same
        logical type/id. Explicitly replace affected relations too: no dependencies,
        current heads, content, layout or engineering choices are inferred.
        workbook_refs omitted inherits the base channel (mapped by replacements);
        an explicit list replaces its declaration. Root follows explicit replacement.
        All original freeze ownership, closure, tree and workbook constraints apply.
        No members are removed; use freeze_snapshot for a different full manifest.
        Old content ownership, snapshots, exports and reviews remain unchanged.
        This creates no export and grants no semantic or engineering acceptance.
        """
        return contents.derive_snapshot(actor(), operation_id, base_snapshot_ref.model_dump(),
            [r.model_dump() for r in additional_refs],
            [r.model_dump() for r in replacements] if replacements is not None else None,
            [r.model_dump() for r in workbook_refs] if workbook_refs is not None else None)

    def submit_review(operation_id: str, review: ReviewSubmission, delivery_export_ref: Ref | None = None) -> dict:
        """Save scoped observations and findings against an exact snapshot. Does not revise content,
        finish the project or trigger author actions. Observation receipts come from read_context,
        observe_evidence, read_content_export or inspect_rendered_page. Null means no judgment yet.
        Optional delivery_export_ref binds export provenance only.
        Excel is checked for content, version and corrections only; render/layout
        assessments apply to Word. An Excel export-fidelity check remains allowed.
        Export/page objects go in artifact_refs, not item target_ref.
        No final-snapshot submission is required.
        scope describes the judgment; optional scope_id preserves identity across wording
        changes. Optional per-item dependency_refs override batch dependencies for reuse.
        Local target_ref can be an exact ContentNode; snapshot_ref supplies its context.
        Choose the true scope and dependencies: whole-snapshot records cannot be reused
        unchanged as local findings in a different snapshot. Saving does not broaden scope.
        This persists a real assessment, not a dry run. Never submit diagnostic filler
        or placeholder verdicts to test argument formatting.
        """
        value = review.model_dump()
        if selector_mode:
            from .review_scope_selectors import expand_submission
            value = expand_submission(contents, actor(), value)
        from .live_messages import current_review_binding
        return contents.submit_review(actor(), operation_id, value, identity,
            delivery_export_ref.model_dump() if delivery_export_ref else None,
            review_message_binding=current_review_binding(workspace, actor()))

    def read_delivery_review_context(snapshot_ref: Ref, export_ref: Ref) -> dict:
        """Read criteria and object inventory for exact versions; no review tasks are generated.
        Metadata is not evidence of content or page observation. Read actual objects
        and sources using paged tools to obtain your own observations.
        """
        from .review_coverage import inventory
        actor()
        snap, export = contents.read(snapshot_ref.model_dump()), contents.read(export_ref.model_dump())
        if snapshot_ref.type != "DocumentSnapshot" or export_ref.type != "ExportArtifact" or export["payload"]["snapshot_ref"] != snap["ref"]:
            raise ActionRejected("DELIVERY_VERSION_MISMATCH")
        return {"snapshot_ref": snap["ref"], "export_ref": export["ref"],
                "criteria": [contents.read(r) for r in snap["payload"]["criteria_refs"]],
                "coverage_contract": snap["payload"].get("coverage_contract"),
                "coverage_inventory": inventory(snap),
                "limitation": "Inventory and metadata do not establish review coverage or prescribe checks. Use the authorized assignment and evidence."}

    def observe_evidence(kind: Literal["source", "calculation"], source_id: str = "", offset: int = 0,
                         limit: int = 12000, terms: list[list[str]] | None = None,
                         runtime: ToolRuntime = None) -> dict:
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
        value = contents.observe(actor(), result)
        if kind != 'source':
            return value
        from .source_materials import returned
        materials = [{'source_id':source_id,'kind':'frozen_source_character_selection',
            'selection':{'units':'zero-based Unicode characters','range':result['range']},
            'selected_value_digest':digest(result),
            'coverage':{'total_characters':len(text),'complete_frozen_text_selection':offset==0 and result['next_offset'] is None},
            'limitations':result['limitations']}] if result['text'] else []
        return returned(workspace,role,'observe_evidence',value,materials,runtime, reviewer_handles=reviewer_handles)

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

    def confirm_review_reuse(operation_id: str, review_ref: Ref, new_snapshot: Ref, reason: str, item_indexes: list[int] | None = None) -> dict:
        """Explicitly confirm that a prior local review still applies to unchanged inputs.
        Check changes, new relevance and relationships first. Whole-document judgments
        cannot be transferred to a different snapshot; changed inputs need a new review.
        Select zero-based item_indexes to reuse only those unchanged judgments; omitted
        indexes retain whole-record behavior. Per-item dependencies define exact inputs.
        """
        return contents.confirm_reuse(actor(), operation_id, review_ref.model_dump(), new_snapshot.model_dump(), reason, item_indexes)

    def correct_own_review(operation_id: str, review_ref: Ref, replacement_ref: Ref, reason: str, item_indexes: list[int] | None = None) -> dict:
        """Correct your own mistaken review with an already saved evidence-based replacement.
        Preserve both records and an explicit reason; handling a finding does not withdraw it.
        Select zero-based item_indexes to correct those findings without withdrawing other
        items or delivery checks. Match target, criterion, scope_id (or scope) and kind.
        """
        return contents.supersede_review(actor(), operation_id, review_ref.model_dump(), replacement_ref.model_dump(), reason, item_indexes)

    def get_operation_receipt(operation_id: str) -> dict:
        """Read your content-write receipt and independent text/model attempts separately.
        For a bounded review use your caller operation_id; for vision or raw analysis
        use the returned raw operation. Only server-recorded own-task attempts are shown.
        Reserved text work has an unresolved outcome, not permission to retry. A
        completed text payload does not establish adoption or semantic acceptance.
        Unknown is not no-write or no-provider-work; caller ids are namespace-bound.
        """
        from .operation_receipts import operation_receipt
        return operation_receipt(contents, actor(), operation_id)

    def export_content_snapshot(operation_id: str, snapshot_ref: Ref, layout: LayoutOptions | None = None,
                                layout_from_export_ref: Ref | None = None) -> dict:
        """Export an immutable snapshot with presentation-only options and version-bound mapping.
        Layout tasks may export only the snapshot explicitly granted at delegation.
        Node options identify exact refs: heading_level promotes the existing first text line;
        column_weights set table proportions, landscape isolates a table/figure on wide pages.
        To reuse saved layout exactly, pass layout_from_export_ref naming an exact Word
        ExportArtifact instead of layout. The server validates its saved configuration
        against this target snapshot; it never remaps node versions or chooses latest.
        This cannot replace text, numbers, conditions, evidence or criteria. A new export
        needs review of that exact file; old review does not approve a layout revision.
        """
        from .content_export import export_snapshot
        return export_snapshot(contents, actor(), operation_id, snapshot_ref.model_dump(),
            layout.model_dump(exclude_unset=True) if layout is not None else None,
            layout_from_export_ref.model_dump() if layout_from_export_ref is not None else None)

    def export_content_workbook(operation_id: str, snapshot_ref: Ref, sheets: list[WorkbookSheet], report_export_ref: Ref | None = None) -> dict:
        """Create XLSX from selected table ContentNodes in your own immutable snapshot.
        Each sheet has name, table_ref and optional note_refs. Selected text notes,
        including corrections and qualifiers, are copied verbatim after that table.
        Optional report_export_ref links the exact companion Word version, not its correctness.
        A linked Word and XLSX must use the same snapshot; a cross-snapshot link is rejected.
        For a snapshot with declared workbook_refs, sheets must select all and
        only those workbook-only table/note nodes, leaving report prose separate.
        You choose table contents and sheet organization. Read/render/review the saved export
        using the same export tools; an exported workbook is not an accepted deliverable.
        """
        from .content_workbook import export_workbook
        return export_workbook(contents, actor(), operation_id, snapshot_ref.model_dump(),
                               [s.model_dump() for s in sheets], report_export_ref.model_dump() if report_export_ref else None)

    def read_layout_capabilities() -> dict:
        """Read current controls, dependency availability and version; old inability claims may be stale.
        Paragraph controls select exact unique source lines without changing the snapshot.
        refresh_toc uses native LibreOffice/UNO and publishes a new verified export.
        """
        from .layout_capabilities import capabilities
        from .material_issues import MaterialIssue, TableMerge
        from .layout_revision import status as layout_revision_status
        with contents.store.connect() as db:
            budget = layout_revision_status(db)
        return contents.observe(actor(), {**capabilities(), 'revision_budget': budget,
            'material_issue_schema': MaterialIssue.model_json_schema(),
            'table_merge_schema': TableMerge.model_json_schema(),
            'content_annotations': 'ContentNode.body.material_issues and body.merges use these schemas. Each issue anchors the exact adopted value; Word comments and Excel clarification rows share the frozen records. ContentNode.citations are readable source references; working_notes never appear in deliverables.'})

    def request_layout_capability(operation_id: str, snapshot_ref: Ref, problem: str,
                                  attempted: list[str], requested_operation: str, evidence: list[str]) -> dict:
        """Ask development for a missing operation with attempts and page/receipt evidence.
        Saves a HandlingRecord in read_feedback, retaining the task and capability version.
        This is a handoff request, not permission to execute code or a claim of implementation.
        Coordinator can resume the task after development reports new capability evidence.
        """
        from .layout_capabilities import request_extension
        return request_extension(contents, actor(), operation_id, snapshot_ref.model_dump(),
            problem, attempted, requested_operation, evidence)

    def render_content_export(operation_id: str, export_ref: Ref) -> dict:
        """Render this exact export to PDF/pages, or return blocked. Rendering is not visual review."""
        from .content_export import render_export
        return render_export(contents, actor(), operation_id, export_ref.model_dump())

    def read_content_export(export_ref: Ref) -> dict:
        """Read actual DOCX or XLSX text and structure with identity and receipt; not page observation."""
        from .content_export import read_export
        return read_export(contents, actor(), export_ref.model_dump())

    async def inspect_rendered_page(render_ref: Ref, page: int, question: str,
                                   reference_source_id: str = "", reference_page: int = 1,
                                   crop: list[float] | None = None) -> dict:
        """Ask the configured visual model about one actual rendered page. Returns bounded
        observations with a receipt and limitations, not a verdict; consumes a model call.
        Optional project-bound customer reference source/page is supplied beside the
        actual Word page in the same request. Optional normalized [x0,y0,x1,y1]
        crop inspects a closer region on both pages; it never covers a whole page.
        Reference/page scope comes from the saved assignment, not an expanded contract.
        """
        from .content_export import inspect_render
        return await inspect_render(contents, actor(), render_ref.model_dump(), page, question,
            reference_source_id=reference_source_id, reference_page=reference_page, crop=crop)

    def select_delivery(operation_id: str, snapshot_ref: Ref, export_ref: Ref,
                                 ending_reason: Literal["continue", "preserve_unresolved", "blocked", "no_progress"] = "continue",
                                 workbook_export_ref: Ref | None = None,
                                 review_basis_assignment_ref: Ref | None = None,
                                 adopted_review_task_refs: list[Ref] | None = None) -> dict:
        """Select the actual snapshot/export to deliver. This is not approval and starts no review.
        ending_reason is historical metadata, not an execution control. Delegate review
        when useful; selection alone neither ends execution nor changes a verdict.
        Optional workbook_export_ref selects the saved XLSX companion bound to this
        exact Word export and snapshot for customer download; it does not establish parity.
        """
        def select(db):
            snap, export = contents._read(db, snapshot_ref.model_dump()), contents._read(db, export_ref.model_dump())
            if snapshot_ref.type != "DocumentSnapshot" or export_ref.type != "ExportArtifact" or export["payload"]["snapshot_ref"] != snap["ref"]:
                raise ActionRejected("DELIVERY_VERSION_MISMATCH")
            delivery = {"snapshot_ref": snap["ref"], "export_ref": export["ref"], "ending_reason": ending_reason}
            if review_interface_profile(workspace.store) == 'review-interfaces-v4':
                from .deliverables import export_allowed
                if not export_allowed(contents, db, actor(), snap):
                    raise ActionForbidden('FORBIDDEN: selected snapshot parent')
                if review_basis_assignment_ref is None and adopted_review_task_refs:
                    raise ActionRejected('REVIEW_BASIS_REQUIRED_FOR_ADOPTION')
                delivery.update(review_interface_profile='review-interfaces-v4', selected_by=actor().id,
                    review_basis_assignment_ref=None, adopted_review_task_refs=[])
            if review_basis_assignment_ref is not None:
                from .review_binding import saved_task, validate_basis
                base = saved_task(contents, db, actor(), review_basis_assignment_ref.model_dump(), None)
                basis = validate_basis(contents, db, base['payload'])
                adopted = [r.model_dump() for r in adopted_review_task_refs or []]
                if len({encode(r) for r in adopted}) != len(adopted):
                    raise ActionRejected('DUPLICATE_ADOPTED_REVIEW_TASK')
                for index, ref in enumerate(adopted):
                    other = saved_task(contents, db, actor(), ref, snap['ref'])
                    other_basis = validate_basis(contents, db, other['payload'])
                    if other_basis['digest'] != basis['digest']:
                        raise ActionRejected('REVIEW_ASSIGNMENT_BASIS_MISMATCH', diagnostic={
                            'reason': 'adopted_assignment_uses_different_basis',
                            'parameter_path': ['review_assignment_refs', index],
                            'basis_assignment_ref': base['ref'], 'provided_assignment_ref': other['ref'],
                            'expected_basis_digest': basis['digest'], 'provided_basis_digest': other_basis['digest']})
                delivery.update(review_interface_profile='review-interfaces-v4',
                    review_basis_assignment_ref=base['ref'], adopted_review_task_refs=adopted)
            if workbook_export_ref is not None:
                workbook = contents._read(db, workbook_export_ref.model_dump())
                payload = workbook['payload']
                if (workbook_export_ref.type != 'ExportArtifact' or
                        not export['payload']['file_ref'].endswith('.docx') or
                        not payload.get('file_ref', '').endswith('.xlsx') or
                        payload.get('snapshot_ref') != snap['ref'] or
                        payload.get('export_config', {}).get('report_export_ref') != export['ref']):
                    raise ActionRejected('COMPANION_EXPORT_VERSION_MISMATCH', diagnostic={
                        'reason': 'companion_must_bind_selected_word_and_snapshot',
                        'parameter_path': ['workbook_export_ref'],
                        'selected_word_export_ref': export['ref'], 'workbook_export_ref': workbook['ref'],
                        'expected_snapshot_ref': snap['ref'], 'workbook_snapshot_ref': payload.get('snapshot_ref'),
                        'workbook_report_export_ref': payload.get('export_config', {}).get('report_export_ref')})
                delivery['workbook_export_ref'] = workbook['ref']
            db.execute("INSERT OR REPLACE INTO state VALUES ('content_delivery', ?)", (encode(delivery),))
            # Retain historical final evidence; applicability is checked against the
            # exact selected snapshot/export. Reselecting cannot erase a known defect.
            return delivery
        request = {"select_delivery": [snapshot_ref.model_dump(), export_ref.model_dump(), ending_reason]}
        if workbook_export_ref is not None:
            request['workbook_export_ref'] = workbook_export_ref.model_dump()
        if review_basis_assignment_ref is not None:
            request.update(review_basis_assignment_ref=review_basis_assignment_ref.model_dump(),
                adopted_review_task_refs=[r.model_dump() for r in adopted_review_task_refs or []])
        elif review_interface_profile(workspace.store) == 'review-interfaces-v4':
            request.update(review_basis_assignment_ref=None,
                adopted_review_task_refs=[r.model_dump() for r in adopted_review_task_refs or []])
        return contents.operation(actor(), operation_id, request, select)

    def select_content_delivery(operation_id: str, snapshot_ref: Ref, export_ref: Ref,
            ending_reason: Literal['continue','preserve_unresolved','blocked','no_progress'] = 'continue',
            workbook_export_ref: Ref | None = None) -> dict:
        return select_delivery(operation_id, snapshot_ref, export_ref, ending_reason, workbook_export_ref)
    select_content_delivery.__doc__ = select_delivery.__doc__

    def record_execution_decision(operation_id: str, decision: Literal["continue", "wait", "handoff", "terminate"],
                                  reason: str, evidence: list[str], unresolved: list[str],
                                  claims_assigned_checks_complete: bool = False) -> dict:
        """Record strategy and grounds against the current selected delivery. This does not
        change verdicts, trigger actions or force the loop to stop. Subsequent native tool
        calls or your final response implement the choice. claims_assigned_checks_complete
        is verified against saved current-delivery assignments; it never establishes
        whole-report acceptance. Correction limits constrain edits, not reading/checking.
        """
        if not reason.strip():
            raise ActionRejected("DECISION_REASON_REQUIRED")
        actor()
        from .decision_state import execution_evidence, completion_state_token
        with contents.store.connect() as db:
            observed_token = completion_state_token(db) if claims_assigned_checks_complete else None
        decision_evidence = execution_evidence(contents)
        def save(db):
            import json
            # Validate only a new operation. A saved receipt remains the exact
            # historical result when replayed after the application state changes.
            if claims_assigned_checks_complete and completion_state_token(db) != observed_token:
                raise ActionRejected('DECISION_STATE_CHANGED: Refresh current state before a new completion declaration.')
            if claims_assigned_checks_complete and not decision_evidence['assigned_checks_complete']:
                raise ActionRejected('ASSIGNED_CHECKS_NOT_COMPLETE: ' + encode(decision_evidence))
            row = db.execute("SELECT value FROM state WHERE key='content_delivery'").fetchone()
            value = {"decision": decision, "reason": reason, "evidence": evidence,
                     "unresolved": unresolved, "task_supervision_remaining": remaining,
                     "claims_assigned_checks_complete": claims_assigned_checks_complete,
                     "execution_evidence": decision_evidence,
                     "delivery": json.loads(row[0]) if row else None}
            db.execute("INSERT OR REPLACE INTO state VALUES ('content_execution_decision', ?)", (encode(value),))
            return value
        from .task_supervision import task_status
        # Collect before the write transaction; retain execution gaps even when
        # an agent's final unresolved text/todos omit them.
        remaining, offset = [], 0
        while True:
            page = task_status(contents, offset)
            remaining.extend({"task_id": t["task_id"], "snapshot_ref": t["snapshot_ref"], "remaining": t["remaining"]}
                             for t in page["tasks"] if t["remaining"])
            if page["next_offset"] is None:
                break
            offset = page["next_offset"]
        request = {"execution_decision": [decision, reason, evidence, unresolved]}
        if claims_assigned_checks_complete:
            request['claims_assigned_checks_complete'] = True
        return contents.operation(actor(), operation_id, request, save)

    from .prompt_sources import native_reviewer, load_prompt, review_interface_profile, REVIEW_INTERFACE_V2, REVIEW_INTERFACE_V3, report_prompt_profile, report_rule_source, CONCISE_PROMPTS
    interface = review_interface_profile(workspace.store)
    text_profile = report_prompt_profile(workspace.store)
    if interface == 'review-interfaces-v4':
        def select_v4(operation_id: str, snapshot_ref: Ref, export_ref: Ref,
                review_basis_assignment_ref: Ref | None = None, review_assignment_refs: list[Ref] = [],
                ending_reason: Literal['continue','preserve_unresolved','blocked','no_progress'] = 'continue',
                workbook_export_ref: Ref | None = None) -> dict:
            return select_delivery(operation_id, snapshot_ref, export_ref, ending_reason,
                workbook_export_ref, review_basis_assignment_ref, review_assignment_refs)
        select_v4.__name__, select_v4.__doc__ = 'select_content_delivery', load_prompt(report_rule_source('select-content-delivery-v4', text_profile))
        select_content_delivery = select_v4
        def reuse_v4(operation_id: str, review_ref: Ref, new_snapshot: Ref, reason: str,
                     item_mappings: list[ReuseMapping]) -> dict:
            return contents.confirm_reuse(actor(), operation_id, review_ref.model_dump(),
                new_snapshot.model_dump(), reason, item_mappings=[r.model_dump() for r in item_mappings])
        reuse_v4.__name__, reuse_v4.__doc__ = 'confirm_review_reuse', load_prompt('native-review-reuse-v4')
        confirm_review_reuse = reuse_v4
        old_commit, old_save = commit_objects, save_text_node
        def commit_with_selection(operation_id: str, objects: list[CommitObject],
                                  deliverable_selection: DeliverableSelection | None = None) -> dict:
            return commit_owned(operation_id, objects, deliverable_selection)
        commit_with_selection.__name__ = 'commit_objects'
        commit_with_selection.__doc__ = old_commit.__doc__ + '\n\n' + load_prompt(report_rule_source('deliverable-save-tool-v4', text_profile))
        def save_with_selection(operation_id: str, text: str,
                kind: Literal['report', 'chapter', 'block', 'cell', 'claim'],
                claim_kind: Literal['fact', 'calculation', 'inference', 'recommendation', 'structure'],
                qualifications: str, previous_ref: Ref | None = None,
                deliverable_selection: DeliverableSelection | None = None) -> dict:
            return save_owned_text(operation_id, text, kind, claim_kind, qualifications,
                                   previous_ref, deliverable_selection)
        save_with_selection.__name__ = 'save_text_node'
        save_with_selection.__doc__ = old_save.__doc__ + '\n\n' + load_prompt(report_rule_source('deliverable-save-tool-v4', text_profile))
        commit_objects, save_text_node = commit_with_selection, save_with_selection
        def export_with_selection(operation_id: str, snapshot_ref: Ref | None = None,
                layout: LayoutOptions | None = None, layout_from_export_ref: Ref | None = None,
                deliverable: DeliverableHandle | None = None) -> dict:
            from .content_export import export_snapshot
            return export_snapshot(contents, actor(), operation_id,
                snapshot_ref.model_dump() if snapshot_ref else None,
                layout.model_dump(exclude_unset=True) if layout else None,
                layout_from_export_ref.model_dump() if layout_from_export_ref else None,
                deliverable=deliverable.model_dump() if deliverable else None)
        export_with_selection.__name__ = 'export_content_snapshot'
        export_with_selection.__doc__ = load_prompt('export-content-snapshot-v4')
        def workbook_with_selection(operation_id: str, sheets: list[WorkbookSheet],
                snapshot_ref: Ref | None = None, report_export_ref: Ref | None = None,
                deliverable: DeliverableHandle | None = None) -> dict:
            from .content_workbook import export_workbook
            return export_workbook(contents, actor(), operation_id,
                snapshot_ref.model_dump() if snapshot_ref else None,
                [s.model_dump() for s in sheets], report_export_ref.model_dump() if report_export_ref else None,
                deliverable=deliverable.model_dump() if deliverable else None)
        workbook_with_selection.__name__ = 'export_content_workbook'
        workbook_with_selection.__doc__ = load_prompt('export-content-workbook-v4')
        export_content_snapshot, export_content_workbook = export_with_selection, workbook_with_selection
        from .prompt_sources import submit_review_source
        submit_review.__doc__ = load_prompt(submit_review_source(text_profile,
            submission_contract if selector_mode else None))
    if interface == REVIEW_INTERFACE_V3:
        freeze_snapshot_with_receipts.__name__ = 'freeze_snapshot'
        freeze_snapshot_with_receipts.__doc__ = load_prompt('freeze-receipts-v3')
        freeze_snapshot = freeze_snapshot_with_receipts
    if role == 'reviewer' and native_reviewer(workspace.store):
        read_content_index.__doc__ = load_prompt('native-content-index-tool-v4' if text_profile == CONCISE_PROMPTS else 'native-content-index-tool')
        if interface in {REVIEW_INTERFACE_V2, REVIEW_INTERFACE_V3, 'review-interfaces-v4'}:
            from .content_tasks import native_review_submission_schema
            submit_review.__annotations__['review'] = native_review_submission_schema(
                v4=interface == 'review-interfaces-v4', scope_selectors=selector_mode)
    def read_commission_plan() -> dict:
        """Read the current source-linked proposal, inventory and conventions; this is not owner approval."""
        actor()
        from .commission_plan import read_plan
        return read_plan(workspace.store) or {'status': 'not_recorded'}

    def save_commission_plan(operation_id: str, plan: CommissionPlan) -> dict:
        """Save a source-linked section plan and full object inventory before writing.

        Preserve unknowns, conflicting values and every known object. Quote customer
        conventions separately from interpretations. This proposes scope; only the
        operator can approve it or reduce it through the commission checkpoint.
        """
        from .commission_plan import save_plan
        return save_plan(contents, actor(), operation_id, plan.model_dump())

    def record_assessment_outcome(operation_id: str, object_id: str, section_ref: Ref,
            score_ref: Ref, level_ref: Ref, basis_refs: list[Ref], unresolved: list[str]) -> dict:
        """Link an assigned object's saved section, score, level and evidence to the confirmed plan.

        G3 requires saved system-calculated score and level nodes. Assumptions with
        comments count as assessed, not engineering approval. Only the owning writer may
        declare its output; missing objects remain incomplete and reductions need owner action.
        """
        from .commission_plan import record_outcome
        return record_outcome(contents, actor(), operation_id, object_id,
            section_ref.model_dump(), score_ref.model_dump(), level_ref.model_dump(),
            [r.model_dump() for r in basis_refs], unresolved)

    def calculate_assessment(operation_id: str, assessment: Assessment) -> dict:
        """Save one slope's complete ranked judgments using its confirmed method pack.

        Supply a reason for every rank and a source-bound basis for every value.
        Assumptions need plausible grade IDs and a question; the system derives their
        joint extremes, all arithmetic, ranking/evaluation tables, and level text.
        No-evidence assumptions must choose the adverse grade. Template scores cannot
        be evidence. Returned immutable nodes and evidence belong in the selected snapshot.
        """
        from .risk_scoring import save_assessment
        return save_assessment(contents, actor(), operation_id, assessment.model_dump(mode='json'))

    def read_prepared_method(source_ref: Ref, template_ref: Ref | None = None) -> dict:
        """Read reviewed guideline tables bound to the exact source file hash.

        This provides method data only. The Coordinator links customer conventions
        or labelled defaults in the commission plan before owner confirmation.
        """
        from .method_pack import bind_guideline
        actor()
        if source_ref.type != 'SourceArtifact':
            raise ActionRejected('METHOD_SOURCE_ARTIFACT_REQUIRED')
        source = contents.read(source_ref.model_dump())
        if template_ref is None:
            return bind_guideline(source_ref.model_dump(), source['payload']['file_digest'])
        if template_ref.type != 'SourceArtifact':
            raise ActionRejected('METHOD_SOURCE_ARTIFACT_REQUIRED')
        template = contents.read(template_ref.model_dump())
        return bind_guideline(source_ref.model_dump(), source['payload']['file_digest'],
                             template_ref.model_dump(), template['payload']['file_digest'])

    def read_prepared_tables(source_ref: Ref, template_ref: Ref) -> dict:
        """Read the pilot's source-bound table specifications for inclusion in the plan.

        Specifications bind saved fields, never template scores. The existing owner
        checkpoint confirms the rendered headers and exact versions once per table type.
        This reads prepared specifications; it does not discover new methods or templates.
        """
        from .table_spec import read_prepared_tables as prepared
        actor()
        if source_ref.type != 'SourceArtifact' or template_ref.type != 'SourceArtifact':
            raise ActionRejected('TABLE_SPEC_SOURCE_ARTIFACT_REQUIRED')
        source = contents.read(source_ref.model_dump())
        template = contents.read(template_ref.model_dump())
        return prepared(source_ref.model_dump(), source['payload']['file_digest'],
                        template_ref.model_dump(), template['payload']['file_digest'])

    def materialize_planned_section(operation_id: str, section_id: str, assessment_refs: list[Ref]) -> dict:
        """Copy a fixed/derived section from its approved source spans and result slots.

        Use no assessment refs for fixed text. Derived summary slots insert only saved
        calculations, including the same level qualification used in the assessment.
        No rewording or template score reuse is performed.
        """
        from .risk_scoring import create_planned_section
        return create_planned_section(contents, actor(), operation_id, section_id,
            [r.model_dump() for r in assessment_refs])

    common = [content_status, read_object_index, read_context, read_content_index, read_content_selection,
              read_review_status, observe_evidence, read_feedback, record_handoff,
              assess_change_impact, get_operation_receipt, read_content_export, render_content_export, inspect_rendered_page,
              read_delivery_review_context, read_layout_capabilities]
    from .commission_plan import enabled as commission_enabled
    if commission_enabled(workspace.store):
        common.append(read_commission_plan)
        if role == 'coordinator':
            from .commission_planning import enabled as planning_enabled, planning_tools
            common += (planning_tools(contents, actor) if planning_enabled(workspace.store) else
                       [save_commission_plan, read_prepared_method, read_prepared_tables])
        if role == 'writer':
            common += [record_assessment_outcome, calculate_assessment, materialize_planned_section]
    if role == 'coordinator' and interface == 'review-interfaces-v4':
        common.remove(inspect_rendered_page)
    from .learning import report_tools
    common += report_tools(workspace, actor)
    if role in {"reviewer", "rubric_grader"}:
        if role == 'reviewer' and interface == 'review-interfaces-v4':
            from .live_messages import review_tool
            submit_review = review_tool(workspace, actor, contents, identity)
        tools = common + [capture_review_sources, submit_review, confirm_review_reuse, correct_own_review] + ([read_task_assignment] if role == "reviewer" else [])
        if reviewer_handles:
            from .review_handles import read_tools
            return read_tools(contents, actor, tools)
        return tools
    if role in {"coordinator", "writer"}:
        common += [import_source_versions, commit_objects, save_text_node, freeze_snapshot, derive_snapshot, export_content_snapshot, export_content_workbook]
    if role == "layout":
        common += [export_content_snapshot, request_layout_capability]
    if role == "coordinator":
        common += [select_content_delivery, record_execution_decision, request_layout_capability, read_task_supervision, list_supervision_plugins, read_review_obligation_coverage]
        if bound_manifest(workspace.store).get("review_entrypoint") != "native-rubric-v1":
            common.remove(save_text_node)
            commit_objects.__doc__ += "\nYour coordinator binding may commit Criterion, Evidence and Relation; delegate all ContentNode creation/revision to writer."
    return common
