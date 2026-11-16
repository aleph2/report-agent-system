"""Business tools bound by the server to a project and a responsible actor."""
from __future__ import annotations
from . import report_state

from typing import Annotated, Literal
from pydantic import Field
from langchain.tools import ToolRuntime

from .content_models import Ref, ReviewSubmission, SCHEMA_VERSION
from .content_inputs import CommitObject
from .content_store import Actor, ContentStore
from .errors import ActionForbidden, ActionRejected
from .store import encode, digest
from .content_layout import LayoutOptions
from .content_workbook import WorkbookSheet
from .deliverables import DeliverableSelection, DeliverableHandle
from .handoff_release import manifest as bound_manifest
from .commission_plan import CommissionPlan
from .risk_scoring import Assessment
from .content_models import SourceCitation
from .section_writing import IssueProposal


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


def general_reviewer_tool(fn):
    """Enforce the active delegation even on closures built before a task started."""
    from functools import wraps
    from inspect import iscoroutinefunction
    from .content_tasks import require_general_review_tool

    from langchain_core.tools import StructuredTool
    if isinstance(fn, StructuredTool):
        # LangChain consumes native tool objects directly, including the V4
        # MessageTool's explicit public schema and injected operation ID.
        updates = {slot: general_reviewer_tool(callback)
                   for slot in ('func', 'coroutine')
                   if (callback := getattr(fn, slot)) is not None}
        return fn.model_copy(update=updates)
    if getattr(fn, '_general_review_guard', None) is fn:
        return fn
    if iscoroutinefunction(fn):
        @wraps(fn)
        async def call_async(*args, **kwargs):
            require_general_review_tool()
            return await fn(*args, **kwargs)
        call_async._general_review_guard = call_async
        return call_async

    @wraps(fn)
    def call(*args, **kwargs):
        return fn(*args, **kwargs)
    call._general_review_guard = call
    return call


def content_tools(workspace, role, runtime_identity=None, *, reviewer_handles=False, planning_result_fits=None):
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


    def read_context(target_ref: Ref, offset: int = 0, limit: int = 20) -> dict:
        """Read actual saved objects or a paged snapshot, including unreturned refs and continuation.

        For local investigation read nodes, their containing snapshot's relations and needed
        parents/dependencies. Initial local scope does not restrict independent source access.
        """
        return contents.read_context(actor(), target_ref.model_dump(), offset, limit)


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

    def observe_evidence(kind: Literal["source", "calculation"], source_id: str = "", offset: int = 0,
                         limit: int = 12000, terms: list[list[str]] | None = None,
                         runtime: ToolRuntime = None) -> dict:
        """Read an authorized source excerpt or independently recompute a sum of products,
        returning a saved observation receipt. No model evaluation is hidden in this tool.
        Source offset/limit are characters; continue at next_offset for unread material.
        """
        if kind == "source":
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


    def get_operation_receipt(operation_id: str) -> dict:
        """Read your content-write receipt and independent text/model attempts separately.
        For a bounded review use your caller operation_id; for vision or raw analysis
        use the returned raw operation. Only server-recorded own-task attempts are shown.
        Reserved text work has an unresolved outcome, not permission to retry. A
        completed text payload does not establish adoption or semantic acceptance.
        Unknown is not no-write or no-provider-work; caller ids are namespace-bound.
        """
        from .operation_receipts import operation_receipt
        from .planning_inputs import compact_write_result
        receipt = operation_receipt(contents, actor(), operation_id)
        views = [receipt]
        if isinstance(receipt.get('content_operation'), dict):
            receipt['content_operation'] = dict(receipt['content_operation'])
            views.append(receipt['content_operation'])
        for view in views:
            if 'response' in view:
                view['response'] = compact_write_result(view['response'], warning_count_only=True)
        return receipt

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
            report_state.set_content_delivery(db, delivery, actor=actor())
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


    from .prompt_sources import load_prompt, review_interface_profile, report_prompt_profile, report_rule_source
    interface = review_interface_profile(workspace.store)
    text_profile = report_prompt_profile(workspace.store)
    if interface == 'review-interfaces-v4':
        old_commit = commit_objects
        def commit_with_selection(operation_id: str, objects: list[CommitObject],
                                  deliverable_selection: DeliverableSelection | None = None) -> dict:
            return commit_owned(operation_id, objects, deliverable_selection)
        commit_with_selection.__name__ = 'commit_objects'
        commit_with_selection.__doc__ = old_commit.__doc__ + '\n\n' + load_prompt(report_rule_source('deliverable-save-tool-v4', text_profile))
        commit_objects = commit_with_selection
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
        Template scores cannot
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

    def materialize_planned_section(operation_id: str, section_id: str, assessment_refs: list[Ref]) -> dict:
        """Copy a fixed/derived section from its approved source spans and result slots.

        Use no assessment refs for fixed text. Derived compositions return an ordered section
        tree with sealed tables; include all returned refs. Derived summary slots insert only saved
        calculations, including the same level qualification used in the assessment.
        No rewording or template score reuse is performed.
        """
        from .risk_scoring import create_planned_section
        return create_planned_section(contents, actor(), operation_id, section_id,
            [r.model_dump() for r in assessment_refs])

    def save_section_prose(operation_id: str, section_id: str, text: str,
                           citations: list[SourceCitation], previous_ref: Ref | None = None) -> dict:
        """Save or revise prose for one assigned extracted section with its source citations.

        Write adopted project facts, retaining conditions and uncertainty. Supply current
        citations on every revision. Exact validation spans identify rejected text.
        Fixed text, calculations, tables, structure and comment anchors are system-owned.
        """
        from .section_writing import save_section_prose as save_prose
        return save_prose(contents, actor(), operation_id, section_id, text,
                          [c.model_dump() for c in citations], previous_ref.model_dump() if previous_ref else None)

    def propose_material_issue(operation_id: str, node_ref: Ref, issue: IssueProposal) -> dict:
        """Record a source conflict, gap or assumption for your current saved prose node.

        Supply engineering facts, adopted value and impact; the system assigns the comment
        position and the matching Excel row. This does not change scope or approve a plan.
        """
        from .section_writing import propose_material_issue as propose
        return propose(contents, actor(), operation_id, node_ref.model_dump(), issue.model_dump())

    def request_system_delivery(operation_id: str) -> dict:
        """Assemble the approved plan from saved section prose and canonical assessments,
        then export Word and Excel from the same frozen snapshot. Missing inputs are
        reported; no model, guessed judgments or automatic approval is used.
        """
        from .system_assembler import assemble_current_report
        from .content_export import export_snapshot
        assembled = assemble_current_report(contents, actor(), operation_id + ':assembly')['result']
        return export_snapshot(contents, actor(), operation_id + ':export', assembled['snapshot_ref'])

    async def assess_assigned_object() -> dict:
        """Assess the one object bound to this task, or continue its saved indicator progress. Returns the canonical assessment reference, gaps and interrupted indicators. Does not write section prose or assess other objects."""
        from .writer_runtime import assess_assigned_object as assess
        return await assess(workspace,actor())

    common = [read_object_index, read_context,
              observe_evidence, read_feedback, record_handoff,
              get_operation_receipt,
              read_layout_capabilities]
    from .commission_plan import enabled as commission_enabled
    if commission_enabled(workspace.store):
        common.append(read_commission_plan)
        if role == 'coordinator':
            from .commission_planning import enabled as planning_enabled, planning_tools
            common += (planning_tools(contents, actor, result_fits=planning_result_fits) if planning_enabled(workspace.store) else
                       [save_commission_plan, read_prepared_method])
        if role == 'writer':
            common += [record_assessment_outcome, calculate_assessment, materialize_planned_section]
    if role in {"reviewer", "rubric_grader"}:
        tools = common
        if role == "reviewer":
            async def inspect_rendered_page(render_ref: Ref, page: int, question: str) -> dict:
                """Inspect one page of the assigned render and save the observation."""
                from .content_export import inspect_render
                return await inspect_render(contents, actor(), render_ref.model_dump(), page, question)

            def submit_review(operation_id: str, review: ReviewSubmission) -> dict:
                """Save the review, including incomplete or blocked checks."""
                return contents.submit_review(actor(), operation_id, review.model_dump(), identity)

            tools = [*tools, inspect_rendered_page, submit_review]
        if reviewer_handles:
            from .review_handles import read_tools
            tools = read_tools(contents, actor, tools)
        return [general_reviewer_tool(tool) for tool in tools] if role == 'reviewer' else tools
    if role in {"coordinator", "writer"}:
        common += [commit_objects, export_content_snapshot, export_content_workbook]
    if role == "layout":
        common += [export_content_snapshot, request_layout_capability]
    if role == "coordinator":
        if bound_manifest(workspace.store).get("review_entrypoint") != "native-rubric-v1":
            commit_objects.__doc__ += "\nYour coordinator binding may commit Criterion, Evidence and Relation; delegate all ContentNode creation/revision to writer."
    from .section_writing import enabled as system_writing
    if system_writing(workspace.store):
        system_owned = {'commit_objects', 'export_content_workbook', 'materialize_planned_section',
                        'record_assessment_outcome', 'calculate_assessment'}
        if role in {'coordinator', 'writer'}:
            system_owned.add('export_content_snapshot')
        common = [tool for tool in common if tool.__name__ not in system_owned]
        if role == 'writer':
            common += [save_section_prose, propose_material_issue, assess_assigned_object]
        if role == 'coordinator':
            common += [request_system_delivery]
    return common
