"""Opt-in, task-bound content judgments. No separate agent or hidden review loop."""
from .prompt_sources import load_prompt
import json
from typing import Literal

from pydantic import Field

from .content_models import Contract, Coverage, Finding, ReviewItem, CheckResult, Ref
from .content_store import ContentStore
from .content_tasks import bound_actor
from .content_selection import ContentSelection
from .errors import ActionForbidden, ActionRejected
from .evidence_analysis import SourceSelection, selected_evidence, analyze_evidence_packet, model_identity
from .store import digest, encode
from .task_supervision import (assignment, validate_requirements, missing_required_materials,
                               required_source_spans,
                               source_extents_in_observation)
from .review_input import review_material_context
from .output_contract import received_output



class ToolObservation(Contract):
    evidence_index: int = Field(ge=0)
    locator: str = Field(min_length=1)
    observation: str = Field(min_length=1)
    limitations: str = ""


class ToolCheckResult(CheckResult):
    # The general saved-record contract supports older optional accounts. A new
    # checker must explicitly provide links, including [] for unperformed work.
    observation_indexes: list[int] = Field(
        description="Zero-based indexes into this item's observations. Required; completed checks need actual links.")


class ToolFinding(Finding):
    requirement_index: int = Field(ge=0)
    observation_indexes: list[int] = Field(min_length=1,
        description="Indexes into this item's observations that support this finding.")
    basis_kind: Literal['supplied_content', 'snapshot_structure', 'input_gap']


class Assessment(Contract):
    scope_id: str
    checked_requirement_indexes: list[int]
    execution_state: Literal["not_started", "running", "completed", "blocked"]
    verdict: Literal["satisfied", "not_satisfied", "undetermined"] | None
    observations: list[ToolObservation]
    check_results: list[ToolCheckResult] = Field(min_length=1)
    outside_assignment_notes: list[str] = Field(default_factory=list)
    coverage: Coverage
    reason: str = Field(min_length=1)
    findings: list[ToolFinding] = Field(default_factory=list)


class Assessments(Contract):
    items: list[Assessment] = Field(min_length=1)


TOOL_PROMPT = load_prompt('legacy-bounded-review')


ORGANIZER_PROMPT = load_prompt('legacy-review-organizer')


async def perform_review(workspace, actor, model, operation_id, scope_ids,
                         source_selections=(), content_selections=(), original_requirement_refs=(),
                         source_version_refs=()):
    if actor.role != "reviewer":
        raise ActionForbidden("FORBIDDEN: bounded review belongs to delegated reviewer")
    cs = ContentStore(workspace.store)
    task = assignment(cs, actor.task_id)
    if actor.id != "content:reviewer:" + actor.task_id or task["role"] != "reviewer":
        raise ActionForbidden("FORBIDDEN: review task binding")
    if not isinstance(operation_id, str) or not operation_id.strip():
        raise ActionRejected("OPERATION_ID_REQUIRED")
    requirements = task.get("review_requirements", [])
    snapshot = task.get("review_snapshot_ref")
    readiness = validate_requirements(cs, snapshot, requirements)
    selected = [r for r in requirements if r["scope_id"] in scope_ids]
    if not scope_ids or len(set(scope_ids)) != len(scope_ids) or len(selected) != len(scope_ids):
        raise ActionRejected("REQUESTED_SCOPES_MUST_IDENTIFY_DISTINCT_ASSIGNED_OUTCOMES")
    from .task_supervision import content_review_capability_issue
    for requirement in selected:
        capability = content_review_capability_issue(requirement)
        if capability:
            raise ActionRejected(capability['code'] + ': ' + encode(capability))
    from .input_capacity import review_capacity, admit_review_packet, review_capacity_scope
    capacity = review_capacity(workspace.store)
    # Agent controls source exploration, not the original target, requirements or
    # criteria. Those materials are fetched by the tool from server-owned refs.
    issues = [i for i in readiness['issues'] if i['scope_id'] in scope_ids]
    unresolved = [{k: i[k] for k in ('requirement_index', 'purpose', 'missing_refs', 'state', 'scope_id', 'path')}
                  for i in issues if i['kind'] in {'undeclared', 'unresolved'}]
    if unresolved:
        gap = {"ok": False, "code": "REQUIRED_REVIEW_MATERIAL_UNRESOLVED", "task_id": actor.task_id,
               "scope_ids": scope_ids, "missing_required_materials": unresolved, "model_called": False,
               "review_ref": None, "execution_state": "blocked", "readiness_issues": issues,
               "limitation": "Required task-linked evidence is not bound. This is not proof the project lacks it and not a model verdict."}
        cs.observe(actor, gap)
        return gap
    required = [ref for r in selected for m in r.get("required_materials", []) for ref in m["refs"]]
    spans = required_source_spans(selected)
    refs = {encode(ref): ref for r in selected for ref in [r["target_ref"], *r["required_read_refs"]]}
    refs.update({encode(ref): ref for ref in required})
    oversized_sources = list({encode(i['ref']): {'ref': i['ref'], 'characters': i['characters']}
                              for i in issues if i['kind'] == 'oversized_source'}.values())
    if oversized_sources:
        gap = {"ok": False, "code": "REVIEW_SOURCE_RANGE_REQUIRED", "task_id": actor.task_id,
            "scope_ids": scope_ids, "oversized_source_bindings": oversized_sources,
            "model_called": False, "review_ref": None, "execution_state": "blocked", "readiness_issues": issues,
            "limitation": "The task requires a large whole-source body. Bind located Evidence objects and source selections instead; no summary or partial selection satisfies this existing whole-body read requirement."}
        cs.observe(actor, gap)
        return gap
    pool = {encode(ref): ref for r in selected for ref in [r["target_ref"], *r["required_read_refs"], *r.get("material_refs", [])]}
    pool.update(refs)
    source_ranges = [s for r in selected for s in r.get("source_ranges", [])] + spans
    pool.update({encode(s["source_ref"]): s["source_ref"] for s in source_ranges})
    if any(encode(ContentSelection.model_validate(s).ref.model_dump()) not in pool for s in content_selections):
        raise ActionRejected("REVIEW_MATERIAL_OUTSIDE_ASSIGNED_POOL")
    from .source_use import resolve_source_use_binding, validate_source_versions
    from .content_inputs import SourceRef
    policy_ref = resolve_source_use_binding(workspace, actor)
    supplemental_refs = {}
    for raw_ref in source_version_refs:
        ref = SourceRef.model_validate(raw_ref).model_dump()
        supplemental_refs.setdefault(encode(ref), ref)
    from .source_use import case_sources
    if supplemental_refs and not policy_ref and case_sources(workspace.store) is None:
        raise ActionRejected('REVIEW_SUPPLEMENT_REQUIRES_BOUND_SOURCE_USE_AUTHORITY')
    validate_source_versions(workspace, actor, source_refs=supplemental_refs.values())
    supplemental_ids = set()
    for ref in supplemental_refs.values():
        payload = cs.read(ref)['payload']
        source = workspace.store.sources([payload['source_id']])[0]
        if not source.get('current', True) or cs.source_payload(source) != payload:
            raise ActionRejected('REVIEW_SOURCE_VERSION_CHANGED')
        supplemental_ids.add(payload['source_id'])
    if not supplemental_ids <= {SourceSelection.model_validate(s).source_id for s in source_selections}:
        raise ActionRejected('REVIEW_SUPPLEMENT_REQUIRES_EXPLICIT_SOURCE_SELECTION')
    source_ids = set(supplemental_ids)
    for ref in pool.values():
        obj = cs.read(ref)
        if ref["type"] == "SourceArtifact":
            source = workspace.store.sources([obj["payload"]["source_id"]])[0]
            if not source.get("current", True) or cs.source_payload(source) != obj["payload"]:
                raise ActionRejected("REVIEW_SOURCE_VERSION_CHANGED")
            source_ids.add(obj["payload"]["source_id"])
        elif ref["type"] == "Evidence":
            for source_ref in obj["payload"]["source_refs"]:
                captured = cs.read(source_ref)["payload"]
                source = workspace.store.sources([captured["source_id"]])[0]
                if not source.get("current", True) or cs.source_payload(source) != captured:
                    raise ActionRejected("REVIEW_SOURCE_VERSION_CHANGED")
                source_ids.add(captured["source_id"])
    if any(SourceSelection.model_validate(s).source_id not in source_ids for s in source_selections):
        from .task_supervision import source_selection_bindings
        raise ActionRejected("REVIEW_SOURCE_OUTSIDE_ASSIGNED_POOL: " + encode({
            "model_called": False, "allowed_source_ids": sorted(source_ids),
            "source_selection_bindings": source_selection_bindings(cs, selected),
            "correction": "SourceSelection.source_id is the file's payload.source_id, not SourceArtifact.ref.id. An invalid argument is not evidence of an unavailable file or contradictory task binding. A later successful selection supersedes that argument error; original-source conflicts remain separate."}))
    eligible_spans = [(cs.read(s["source_ref"])["payload"]["source_id"], s["offset"], s["offset"]+s["limit"])
        for s in source_ranges]
    for raw_selection in source_selections:
        selection = SourceSelection.model_validate(raw_selection)
        if selection.source_id not in supplemental_ids and not any(source_id == selection.source_id and start <= selection.offset
                and selection.offset+selection.limit <= end for source_id,start,end in eligible_spans):
            raise ActionRejected("REVIEW_SOURCE_RANGE_OUTSIDE_TASK: bind exact eligible spans before selecting source blocks")
    evidence = [{"kind": "saved_object", "object": cs.read(ref)} for ref in refs.values()]
    # Optional inventory is not material consumption. Check actual packet refs.
    for entry in evidence:
        obj = entry['object']
        used = ([obj['ref']] if obj['ref']['type'] == 'SourceArtifact' else
                obj['payload']['source_refs'] if obj['ref']['type'] == 'Evidence' else [])
        validate_source_versions(workspace, actor, source_refs=used)
    source_origins, materials = {}, []
    if spans or supplemental_refs:
        mandatory = [SourceSelection(source_id=cs.read(s['source_ref'])['payload']['source_id'],
            offset=s['offset'], limit=s['limit'], table_detail=s.get('table_detail')).packet_selection() for s in spans]
        # Deduplicate identical actual views, not semantically similar material.
        selections = {}
        for s in [*mandatory, *source_selections]:
            s = SourceSelection.model_validate(s).packet_selection()
            selections.setdefault(encode({**s, 'table_detail': s.get('table_detail') or 'full'}), s)
        additional = selected_evidence(workspace, list(selections.values()), [], snapshot, content_selections,
            material_receipts=materials, actor=actor, source_receipts=source_origins)
        source_refs = {encode(s['source_ref']): s['source_ref'] for s in spans}
        # Eligible additional source ranges retain exact version identity too.
        source_refs.update({encode(s['source_ref']): s['source_ref'] for s in source_ranges
            if cs.read(s['source_ref'])['payload']['source_id'] in {v['source_id'] for v in selections.values()}
            and cs.read(s['source_ref'])['payload']['source_id'] not in supplemental_ids})
        source_refs.update(supplemental_refs)
        for index, origin in source_origins.items():
            entry = additional[index]
            entry['source_material_receipt'] = origin
            entry['source_version_refs'] = [ref for ref in source_refs.values()
                if cs.read(ref)['payload']['source_id'] == entry['selection']['source_id']]
    else:
        additional = selected_evidence(workspace, source_selections, [], snapshot, content_selections, actor=actor) if (source_selections or content_selections) else []
    # Validate selected ranges, then avoid replaying an already supplied whole node.
    evidence += [e for e in additional if e["kind"] != "content_node_selection" or encode(e["selection"]["ref"]) not in refs]
    context = review_material_context(cs, snapshot, selected, evidence, pool)
    if context['missing_body_extents']:
        gap = {'ok':False, 'code':'REVIEW_REQUIRED_BODIES_NOT_SUPPLIED',
            'task_id':actor.task_id, 'scope_ids':scope_ids, 'model_called':False,
            'review_ref':None, 'execution_state':'blocked', 'material_context':context,
            'limitation':'Missing task-required full bodies, not a report defect. Select eligible bodies or correct the saved task binding; no scope/permission expansion.'}
        cs.observe(actor,gap)
        return gap
    evidence.append({'kind':'snapshot_structure','structure':context})
    if spans or supplemental_refs:
        from .prepared_material import compile_material
        prepared = compile_material(workspace, actor, evidence, source_refs.values(), materials)
        evidence = prepared.evidence
        extents = source_extents_in_observation(cs, actor.id, {'evidence': evidence})
        gaps = [dict(scope_id=r['scope_id'], **gap) for r in selected
            for gap in missing_required_materials(r, set(refs), source_extents=extents)]
        if gaps:
            raise ActionRejected('REVIEW_REQUIRED_SOURCE_SPANS_NOT_SUPPLIED: ' + encode({
                'model_called': False, 'missing_required_materials': gaps}))
        dependencies = {}
        for index, entry in enumerate(evidence):
            bound = [entry['object']['ref']] if entry['kind'] in {'saved_object', 'source_version_binding'} else entry.get('source_version_refs', [])
            dependencies[index] = [{'scope_id': r['scope_id'], 'requirement_index': m['requirement_index'],
                'purpose': m['purpose']} for r in selected for m in r.get('required_materials', [])
                if any(ref in bound for ref in [*m['refs'], *[s['source_ref'] for s in m.get('source_spans', [])]])]
    criteria = {encode(r["criterion_ref"]): cs.read(r["criterion_ref"]) for r in selected}
    from .prepared_material import compile_material
    # Eligibility preserves the existing task/immutable snapshot boundary. It is
    # not a relevance decision: only the Agent's explicit exact refs are loaded.
    linked = {encode(ref) for criterion in criteria.values()
              for ref in criterion["payload"]["requirement_refs"]}
    members = {encode(ref) for ref in cs.read(snapshot)["payload"]["refs"]}
    originals = {}
    for raw_ref in original_requirement_refs:
        ref = Ref.model_validate(raw_ref).model_dump()
        key = encode(ref)
        if ref["type"] != "Requirement" or key not in linked or key not in members:
            raise ActionRejected("REVIEW_ORIGINAL_REQUIREMENT_OUTSIDE_ASSIGNED_SNAPSHOT")
        originals.setdefault(key, ref)
    original_material = compile_material(workspace, actor,
        [{"kind": "saved_object", "object": cs.read(ref)} for ref in originals.values()])
    # Preserve all selected originals. Only the complete native request boundary
    # owns capacity; no material-only byte or character gate is applied here.
    original_dependencies = {i: [{"requirement_ref": ref, "purpose": "Explicitly selected original Requirement."}]
                            for i, ref in enumerate(originals.values())}
    evidence += original_material.evidence
    refs.update(originals)
    from .prompt_instructions import review_commission
    commission, prompt = review_commission(workspace.store, actor, TOOL_PROMPT)
    inputs = {"task_id": actor.task_id, "assignment": {
        "review_snapshot_ref": snapshot, "review_requirements": selected},
        "commission": commission,
        "requested_scope_ids": scope_ids, "criteria": list(criteria.values()),
        "selected_original_requirement_refs": list(originals.values()),
        "evidence": evidence, "output_schema": Assessments.model_json_schema()}
    if policy_ref:
        inputs['source_use_policy_ref'] = policy_ref
    if supplemental_refs:
        inputs['selected_source_version_refs'] = list(supplemental_refs.values())
    contract = ('assigned-review-supplement-v1' if supplemental_refs else
                'assigned-review-source-spans-v2' if spans else 'assigned-review-v6')
    request_hash = digest({"input": inputs, "model": model_identity(model),
        "system": prompt, "contract": contract})
    key = "bounded_review_result:" + actor.task_id + ":" + operation_id
    if not operation_id.strip():
        raise ActionRejected("OPERATION_ID_REQUIRED")
    prior = workspace.store.get(key)
    if prior:
        if prior["request_hash"] != request_hash:
            raise ActionRejected("OPERATION_CONFLICT")
        admit_review_packet(workspace.store, capacity, model, inputs, prompt, cached=True)
        return {**prior["result"], "reused": True}
    completed_key = "bounded_review_completed:" + request_hash
    completed = workspace.store.get(completed_key)
    if completed:
        # All material access/currentness and scope checks above still execute.
        # A new operation ID is not a new assessment of identical saved inputs.
        workspace.store.set(key, completed)
        admit_review_packet(workspace.store, capacity, model, inputs, prompt, cached=True)
        return {**completed["result"], "reused": True}
    admit_review_packet(workspace.store, capacity, model, inputs, prompt)
    with review_capacity_scope(workspace.store, capacity):
        raw = await analyze_evidence_packet(workspace, model, inputs, prompt,
                                           contract, reserve_attempt=True, owner=actor, caller_operation_id=operation_id)
    text = raw["analysis"]
    if isinstance(text, str) and text.strip().startswith("```"):
        text = "\n".join(text.strip().splitlines()[1:-1])
    with received_output('REVIEW_OUTPUT_CONTRACT_INVALID', raw['operation']):
        assessments = Assessments.model_validate_json(text)
    if len(assessments.items) != len(scope_ids) or {i.scope_id for i in assessments.items} != set(scope_ids):
        raise ActionRejected("REVIEW_TOOL_RETURNED_DIFFERENT_SCOPE: raw response preserved")
    by_scope = {r["scope_id"]: r for r in selected}
    # Receipts describe the exact material supplied to this model invocation.
    receipt_ids, dependencies = [], list(refs.values())
    material_dependencies = list(refs.values())
    for index, entry in enumerate(evidence):
        if entry["kind"] == "saved_object":
            observed = {"objects": [entry["object"]]}
        elif entry["kind"] == "content_node_selection":
            observed = {"selections": [entry]}
            dependencies.append(entry["selection"]["ref"])
            material_dependencies.append(entry["selection"]["ref"])
        elif entry['kind']=='snapshot_structure':
            observed = {'snapshot_structure':entry['structure']}
            dependencies.append(snapshot)
        elif entry['kind']=='source_version_binding':
            observed = {'source_version_binding':entry}
            dependencies.append(entry['object']['ref'])
            material_dependencies.append(entry['object']['ref'])
        else:
            observed = {"evidence": [entry]}
            source_id = entry["selection"]["source_id"]
            source_payload = cs.source_payload(workspace.store.sources([source_id])[0])
            if supplemental_refs:
                # Already compiled against the actual own-task material receipt.
                # Do not choose a saved alias or silently capture another version.
                exact_refs = entry.get('source_version_refs', [])
                if not exact_refs:
                    raise ActionRejected('REVIEW_SOURCE_MATERIAL_VERSION_BINDING_MISSING')
                dependencies.extend(exact_refs)
                material_dependencies.extend(exact_refs)
            else:
                existing = next((r for r in cs.list_objects("SourceArtifact") if r["payload_digest"] == digest(source_payload)), None)
                ref = existing["ref"] if existing else cs.capture_sources(actor,
                    "review-source:" + raw["operation"] + ":" + str(index), [source_id])["result"]["source_refs"][0]
                dependencies.append(ref)
                material_dependencies.append(ref)
        observed.update(analysis_operation=raw["operation"], evidence_index=index)
        receipt_ids.append(cs.observe(actor, observed)["receipt_id"])
    items = []
    for assessment in assessments.items:
        req = by_scope[assessment.scope_id]
        indexes = [c.requirement_index for c in assessment.check_results]
        if len(indexes) != len(set(indexes)) or set(indexes) != set(range(len(req["required_checks"]))):
            raise ActionRejected("REVIEW_TOOL_REQUIRES_EVERY_ASSIGNED_CHECK_RESULT: raw response preserved")
        if any(i >= len(req["required_checks"]) or i < 0 for i in assessment.checked_requirement_indexes):
            raise ActionRejected("REVIEW_TOOL_CHECK_INDEX_OUTSIDE_ASSIGNMENT")
        observations = []
        for obs in assessment.observations:
            if obs.evidence_index >= len(receipt_ids):
                raise ActionRejected("REVIEW_TOOL_CITATION_OUTSIDE_INPUT")
            observations.append({**obs.model_dump(exclude={"evidence_index"}), "receipt_id": receipt_ids[obs.evidence_index]})
        item = {**assessment.model_dump(exclude={"observations"}), "observations": observations,
            "target_ref": req["target_ref"], "criterion_ref": req["criterion_ref"],
            "scope": "; ".join(req["required_checks"]), "assessment_kind": "content"}
        local_checks = {extent['requirement_index'] for extent in req.get('content_check_scopes', [])
                        if extent['kind'] == 'local_body'}
        structure_used = (any(evidence[obs.evidence_index]['kind'] == 'snapshot_structure'
                              for obs in assessment.observations)
                          or any(finding.basis_kind == 'snapshot_structure' for finding in assessment.findings))
        if (local_checks == set(range(len(req['required_checks'])))
                and all(extent['kind'] == 'local_body' for extent in req.get('content_check_scopes', []))
                and not structure_used):
            # Only the automatic structure context is excluded; keep every
            # actual material dependency, whether cited in a finding or not.
            item['dependency_refs'] = list({encode(ref): ref for ref in material_dependencies}.values())
        with received_output('REVIEW_OUTPUT_CONTRACT_INVALID', raw['operation']):
            item = ReviewItem.model_validate(item).model_dump()
        for finding in assessment.findings:
            if finding.requirement_index >= len(req['required_checks']):
                raise ActionRejected('REVIEW_FINDING_OUTSIDE_ASSIGNED_CHECK')
            linked = assessment.check_results[next(i for i,c in enumerate(assessment.check_results)
                if c.requirement_index==finding.requirement_index)].observation_indexes
            if not set(finding.observation_indexes).issubset(linked):
                raise ActionRejected('REVIEW_FINDING_OUTSIDE_CHECK_OBSERVATIONS')
            entries = [evidence[assessment.observations[i].evidence_index] for i in finding.observation_indexes]
            if finding.basis_kind=='supplied_content' and not any(e['kind']!='snapshot_structure' for e in entries):
                raise ActionRejected('STRUCTURE_METADATA_IS_NOT_CONTENT_EVIDENCE')
            if finding.basis_kind=='snapshot_structure' and not any(e['kind']=='snapshot_structure' for e in entries):
                raise ActionRejected('STRUCTURE_FINDING_REQUIRES_SNAPSHOT_EVIDENCE')
            if finding.locator_state=='absent' and finding.basis_kind=='snapshot_structure' and not context['inventory_complete']:
                raise ActionRejected('INCOMPLETE_INVENTORY_CANNOT_ESTABLISH_ABSENCE')
        for check in assessment.check_results:
            if check.execution_state != "completed":
                continue
            if any(i >= len(assessment.observations) for i in check.observation_indexes):
                raise ActionRejected("REVIEW_CHECK_CITATION_OUTSIDE_OBSERVATIONS")
            cited, cited_entries = set(), []
            for i in check.observation_indexes:
                entry = evidence[assessment.observations[i].evidence_index]
                cited_entries.append(entry)
                ref = entry.get("object", {}).get("ref") or entry.get("selection", {}).get("ref")
                if ref and (entry['kind']=='saved_object' or entry.get('complete_body_selection')):
                    cited.add(encode(ref))
            cited_extents = source_extents_in_observation(cs, actor.id, {'evidence': cited_entries})
            if missing_required_materials(req, cited, {check.requirement_index}, cited_extents):
                raise ActionRejected("COMPLETED_CHECK_MISSING_REQUIRED_MATERIAL: raw response preserved")
            extent_refs = [r for e in context['body_extents'] if e['scope_id']==req['scope_id']
                and e['requirement_index']==check.requirement_index for r in e['required_body_refs']]
            if any(encode(r) not in cited for r in [req['target_ref'], *extent_refs]):
                raise ActionRejected('COMPLETED_CHECK_MISSING_TARGET_OR_BODY_EXTENT: raw response preserved')
        items.append(item)
    saved = cs.submit_review(actor, "bounded-review:" + actor.task_id + ":" + operation_id,
        {"snapshot_ref": snapshot, "target_ref": selected[0]["target_ref"],
         "scope": "Assigned content scopes: " + ", ".join(scope_ids),
         "criteria_refs": [v["ref"] for v in criteria.values()],
         "dependency_refs": list({encode(r): r for r in dependencies}.values()), "items": items},
        {"mode": "bounded-review-v1", "analysis_operation": raw["operation"], "model": raw["model"],
         "request_hash": request_hash, "prompt_hash": digest(prompt)})
    result = {"review_ref": saved["result"]["review_ref"], "analysis_operation": raw["operation"],
        "items": items, "reused": raw["reused"],
        "limitation": "Scoped model judgments with actual inputs. No inferred whole-report acceptance."}
    workspace.store.set(key, {"request_hash": request_hash, "result": result})
    workspace.store.set(completed_key, {"request_hash": request_hash, "result": result})
    return result


def review_tool(workspace, model):
    from .content_inputs import SourceRef
    async def perform_assigned_review(operation_id: str, scope_ids: list[str],
            source_selections: list[SourceSelection], content_selections: list[ContentSelection],
            original_requirement_refs: list[Ref] | None = None,
            source_version_refs: list[SourceRef] | None = None) -> dict:
        """Perform and save content judgments for selected saved task scopes.

        Saved target_ref must be a ContentNode, including a report root when
        explicitly assigned. review_snapshot_ref binds versions; a DocumentSnapshot
        is not a supported content target. Only the Coordinator can correct the
        saved assignment; changing these selections cannot change its target.
        Root scope does not load all child bodies: retain explicit subtree extents
        and task-linked material refs. Missing bodies remain a reported input gap.
        Readiness describes all scopes; inspect issue.scope_id for this selection.
        A supported selected scope may execute while other scopes remain unfinished.

        Each assigned check needs required_materials with exact bound refs or
        source_spans (exact source version, original block offset/limit and view).
        Required refs load whole local payloads; required source_spans load their
        declared original text automatically and completed checks must cite them.
        Metadata bindings and extra eligible ranges alone do not satisfy them. Unresolved
        bindings return a gap without a model call. Target, criteria and declared required
        bodies load automatically. Select additional portions only from material_refs,
        required_read_refs and required_materials in this saved task;
        content_check_scopes declares per-question local/subtree full-body extents.
        Missing full bodies return a pre-call gap; eligible extra descendant bodies
        still require selection. Snapshot metadata is not a body-read receipt.
        large whole-source body requirements return a pre-call gap rather than
        embedding a complete document. Use located Evidence and explicit ranges.
        Additional source_selections fit source_ranges declared in this task, or
        explicitly selected source_version_refs enrolled in this task's trusted
        source-use binding (see read_task_assignment). These supplement the same
        question only; no required material, original target or write permission
        changes. Pass actual captured SourceArtifact refs and located selections;
        capture/read access alone does not grant supplemental checker use.
        Legacy tasks without this binding retain their original range limits;
        use each captured SourceArtifact.payload.source_id as source_id, not its
        Ref.id. read_task_assignment exposes the exact ID/range mapping.
        owning a source file does not authorize selecting arbitrary blocks from it.
        original_requirement_refs optionally selects exact Requirement versions linked
        by the selected Criteria and contained in the assigned snapshot. Discover refs
        through read_context on the Criterion; only explicit choices load original bodies.
        Omission/empty selects none. Snapshot-bound old versions remain valid; no latest
        version substitution, permission expansion or automatic linked-body loading.
        empty lists are allowed only when no additional material is necessary.
        Returns actual model findings and incomplete work, with immutable review IDs.
        Multiple related scopes may share one call; there is no per-node call limit.
        This does not edit content, expand permission, learn or complete the project.
        """
        from .hierarchical_tools import actor_for
        actor = bound_actor(workspace, "reviewer", actor_for("reviewer"))
        return await perform_review(workspace, actor, model, operation_id, scope_ids,
                                    source_selections, content_selections,
                                    original_requirement_refs or (), source_version_refs or ())
    return perform_assigned_review
