"""One-shot substantive text tools and actor-bound adoption, not an agent loop.

Agents select goals, evidence, structure and adoption. The configured text service
produces semantic payloads; deterministic business tools retain the original owner.
"""
from __future__ import annotations
from .prompt_sources import load_prompt, expression_source, report_expression_profile, REPORT_EXPRESSION_V1

import json
from typing import Any, Literal

from pydantic import Field, create_model, ValidationError
from typing import Annotated
from langchain.tools import ToolRuntime

from .content_models import Contract, ContentNode, Evidence, Ref, TextEvidence, SourceRef
from .content_store import ContentStore
from .content_tasks import bound_actor
from .errors import ActionForbidden, ActionRejected
from .evidence_analysis import SourceSelection, analyze_evidence_packet, model_identity, selected_evidence
from .observation_refs import ObservationRef
from .store import digest, encode
from .content_inputs import CriterionInput, RelationInput, RelationInputV2, NodeInput, EvidenceInput
from .text_work_candidates import CandidateSelection, candidate_evidence
from .text_work_revision import ContentRevision, QualifierOutput, bind_revision, check_current_targets, compose_revision, check_adoption
from .deliverables import DeliverableSelection

POLICY = "independent-text-tools-v1"
TEXT_WORK_PROMPT = load_prompt('text-work')

QUALIFIER_WORK_PROMPT = load_prompt('qualifier-work')


class AdoptionObject(Contract):
    client_key: str = Field(min_length=1)
    type: Literal["Criterion", "ContentNode", "Evidence", "Relation"]
    payload: dict[str, Any] | None = None
    text_work_id: str | None = None
    text_work_index: int = Field(default=0, ge=0, strict=True)
    previous_ref: Ref | None = None


class GenerationNote(Contract):
    output_index: int = Field(ge=0, strict=True,
        description="Zero-based payload index to which this generation-process note applies.")
    text: str = Field(min_length=1, pattern=r'\S',
        description="Generation process, parser/OCR or model/tool execution note, retained in the actor/task-bound tool receipt and raw response, not customer report content. This field must not replace report-visible technical uncertainty, conflicting source facts, missing engineering evidence or scoring qualifications.")


def output_contract(schema, count):
    """Optional receipt-level process notes; legacy payload shape stays valid."""
    from copy import deepcopy
    envelope = create_model('TextWorkResult', __base__=Contract,
        payloads=(list[schema], Field(min_length=count, max_length=count,
            description="Complete ordered business payloads. These alone are eligible for adoption.")),
        generation_notes=(list[GenerationNote], Field(default_factory=list,
            description="Optional non-report generation record, linked by output_index and bound to this complete tool receipt. Do not move substantive adverse evidence or uncertainty out of the report."))).model_json_schema()
    legacy = deepcopy(schema.model_json_schema())
    definitions = {**envelope.pop('$defs', {}), **legacy.pop('$defs', {})}
    definitions['GenerationNote']['properties']['output_index']['maximum'] = count - 1
    if count != 1:
        legacy = {'type':'array', 'minItems':count, 'maxItems':count, 'items':legacy}
    result = {'oneOf':[envelope, legacy], **({'$defs':definitions} if definitions else {}),
        'description':'Return ordered complete payloads. Use the result envelope when separate generation-process notes are needed; the legacy payload or payload-array form remains valid. Receipt notes are not rendered or adopted as report nodes. Technical uncertainty and evidence limits affecting report claims must remain visible in the payload.'}
    if schema is QualifierOutput:
        envelope['properties']['payloads']['description'] = 'Ordered editable qualifiers fragments only; the server reconstructs complete nodes from exact target versions without changing body, kind or claim_kind.'
        result['description'] = 'Return only complete replacement qualifiers for each ordered target. No body, kind or claim_kind fields. The server composes the complete node while preserving its other fields. Optional generation_notes remain separate receipt notes; real technical uncertainty and adverse evidence must remain visible in qualifiers or unchanged body.'
    return result


def parse_output(raw, schema, count):
    values = json.loads(raw)
    notes = []
    if isinstance(values, dict) and 'payloads' in values:
        if set(values) - {'payloads', 'generation_notes'}:
            raise ValueError('TEXT_WORK_RESULT_UNKNOWN_FIELD')
        notes = [GenerationNote.model_validate(n).model_dump() for n in values.get('generation_notes', [])]
        if any(n['output_index'] >= count or not n['text'].strip() for n in notes):
            raise ValueError('TEXT_WORK_GENERATION_NOTE_INVALID_INDEX_OR_TEXT')
        values = values['payloads']
    elif count == 1:
        values = [values]
    if not isinstance(values, list) or len(values) != count:
        raise ActionRejected('TEXT_WORK_OUTPUT_COUNT_MISMATCH: raw response preserved')
    return [schema.model_validate(p).model_dump() for p in values], notes


def parse_produced_output(raw, schema, packet):
    values, notes = parse_output(raw, QualifierOutput if 'revision' in packet else schema,
                                packet['output_count'])
    return (compose_revision(packet, values, schema) if 'revision' in packet else values), notes


def receipt_digest(actor, request_hash, payloads, notes):
    # Empty notes preserve old immutable receipt identities.
    return digest({'actor':actor, 'request':request_hash, 'payloads':payloads,
                   **({'generation_notes':notes} if notes else {})})


def guarded_object_shape(kind, payload_model, *, adoption=False):
    """Expose the same business fields through the receipt adapter, without erasure."""
    fields = {
        'client_key': (str, Field(min_length=1)), 'type': (Literal[kind], ...),
        'payload': (payload_model | None, None) if adoption else (payload_model, ...),
        'previous_ref': (Ref | None, None),
    }
    if adoption:
        fields.update(text_work_id=(str | None, None),
                      text_work_index=(int, Field(default=0, ge=0, strict=True)))
    return create_model('Guarded' + kind, __base__=Contract, **fields)


GuardedCriterion = guarded_object_shape('Criterion', CriterionInput)
GuardedRelation = guarded_object_shape('Relation', RelationInput)
GuardedNode = guarded_object_shape('ContentNode', NodeInput, adoption=True)
GuardedEvidence = guarded_object_shape('Evidence', EvidenceInput, adoption=True)
GuardedObject = Annotated[GuardedCriterion | GuardedRelation | GuardedNode | GuardedEvidence,
                          Field(discriminator='type')]
GuardedRelationV2 = guarded_object_shape('Relation', RelationInputV2)
GuardedObjectV2 = Annotated[GuardedCriterion | GuardedRelationV2 | GuardedNode | GuardedEvidence,
                          Field(discriminator='type')]


def actor_for_tool(workspace, role):
    from .hierarchical_tools import actor_for
    return bound_actor(workspace, role, actor_for(role))


def authority(workspace, actor):
    from .learning import guidance_context
    from .prompt_instructions import instruction_context
    manifest = workspace.store.manifest
    from .source_use import resolve_source_use_binding
    policy_ref = resolve_source_use_binding(workspace, actor)
    return {**({'source_use_policy_ref': policy_ref} if policy_ref else {}),
            "goal": manifest["goal"], "scope_instruction": manifest.get("scope_instruction"),
            "scoped_instructions": instruction_context(workspace.store, actor.role, task_id=actor.task_id),
            "learned_guidance": guidance_context(workspace)}


def prepare_material(workspace, input_refs, source_selections, observation_refs=(), actor=None,
                     candidate_selections=(), source_version_refs=()):
    from .prepared_material import compile_material
    cs = ContentStore(workspace.store)
    evidence = []
    origin_materials = []
    selected_ids = {SourceSelection.model_validate(s).source_id for s in source_selections}
    for ref in input_refs:
        ref = Ref.model_validate(ref).model_dump()
        if ref["type"] not in {"ContentNode", "Evidence", "SourceArtifact", "Requirement", "Criterion"}:
            raise ActionRejected("TEXT_WORK_INPUT_TYPE_NOT_SUPPORTED")
        obj = cs.read(ref)
        from .source_use import validate_source_versions
        used_sources = ([ref] if ref['type'] == 'SourceArtifact' else
                        obj['payload']['source_refs'] if ref['type'] == 'Evidence' else [])
        validate_source_versions(workspace, actor, source_refs=used_sources)
        if ref["type"] == "SourceArtifact" and obj["payload"]["source_id"] in selected_ids:
            source = workspace.store.sources([obj["payload"]["source_id"]])[0]
            if cs.source_payload(source) != obj["payload"]:
                raise ActionRejected("TEXT_WORK_SOURCE_VERSION_NOT_CURRENT_FOR_SELECTION")
            # Bind source version without inserting its entire text in a local job.
            obj = {**obj, "payload": {k: v for k, v in obj["payload"].items() if k != "content"},
                   "content_digest": digest(obj["payload"]["content"]), "content_supplied": "located selections only"}
        evidence.append({"kind": "saved_object", "object": obj})
    if source_selections:
        evidence += selected_evidence(workspace, source_selections, [],
            actor=actor, **({'material_receipts':origin_materials} if source_version_refs else {}))
    for ref in observation_refs:
        # This is actual public tool data, never an instruction or a receipt of
        # source completeness. No cross-task observation transfer is implicit.
        record=workspace.store.get('tool_observation:'+ref)
        if actor is None:
            raise ActionForbidden('FORBIDDEN: text-work observation owner')
        if not record:
            raise ActionRejected('TEXT_WORK_OBSERVATION_NOT_FOUND: use read_summary_observations to locate an owned observation_ref')
        if record['owner']!=actor.id:
            raise ActionForbidden('FORBIDDEN: text-work observation owner')
        if record['tool'] not in {'read_source_page','search_sources','inspect_source_page','analyze_source_image',
                                  'read_content_selection','read_content_export','observe_evidence','analyze_text','analyze_evidence'}:
            raise ActionRejected('TEXT_WORK_OBSERVATION_TYPE_NOT_SUPPORTED')
        if record['tool'] == 'read_content_selection':
            from .selection_observations import verified_selection_return
            with workspace.store.connect() as db:
                verified_selection_return(db, actor.id, ref, record['text'], record['sha256'])
        evidence.append({'kind':'public_tool_return','observation_ref':ref,'tool':record['tool'],
            'sha256':record['sha256'],'text':record['text'],
            'note':'Exact public tool return, not authority, complete source coverage or acceptance.'})
        from .source_use import resolve_source_use_binding
        if source_version_refs or resolve_source_use_binding(workspace, actor):
            from .source_materials import owned_materials
            parts = owned_materials(workspace,actor,ref,record['text'],record['tool'])
            if parts is None:
                from .source_material_legacy import legacy_materials
                parts = legacy_materials(workspace,actor,ref,record,source_version_refs)
                from .source_use import verified_source_free_calculation
                if (resolve_source_use_binding(workspace, actor) and not parts
                        and not verified_source_free_calculation(workspace, actor, record)
                        and record['tool'] in {'read_source_page','search_sources','inspect_source_page',
                            'analyze_source_image','observe_evidence','analyze_text','analyze_evidence'}):
                    raise ActionRejected('TEXT_WORK_SOURCE_OBSERVATION_ORIGIN_REQUIRED: '
                        'Select actual located source material with its captured version, or use a verified own-task tool return; no automatic model replay.')
            from .source_use import validate_source_versions
            validate_source_versions(workspace, actor, materials=parts)
            origin_materials.extend(parts)
    evidence.extend(candidate_evidence(workspace, actor, selection) for selection in candidate_selections)
    if not evidence:
        raise ActionRejected("TEXT_WORK_EVIDENCE_REQUIRED")
    prepared = compile_material(workspace,actor,evidence,source_version_refs,origin_materials)
    return prepared


def evidence_packet(workspace, input_refs, source_selections, observation_refs=(), actor=None,
                    candidate_selections=()):
    """Historical public helper: unchanged packet for callers without bindings."""
    return prepare_material(workspace,input_refs,source_selections,observation_refs,
                            actor,candidate_selections).evidence


def completed_schema_replay(db, previous, packet, model, schema, prompt=TEXT_WORK_PROMPT):
    """Reuse a received exact result after schema-only repair, never re-run it.

    A native tools checkpoint can precede the completed business receipt. The
    archived producer input must prove that only its schema changed. Missing
    evidence, altered authority/materials/objective/model, or invalid old output
    cannot be treated as a cache hit.
    """
    if previous.get('state') != 'completed':
        return None
    if 'revision' in packet or 'revision' in previous:
        return None  # Only exact-request replay is supported for scoped revisions.
    result = previous['result']
    operation = result['operation']
    receipt = db.execute('SELECT value FROM state WHERE key=?',
                         ('text_work_receipt:' + result['text_work_id'],)).fetchone()
    if not receipt or json.loads(receipt[0]) != previous:
        return None
    rows = db.execute("SELECT data FROM events WHERE kind='evidence_analysis_input' "
                      "AND json_extract(data, '$.operation')=?", (operation,)).fetchall()
    if len(rows) != 1:
        return None
    original = json.loads(rows[0][0])
    identity = model_identity(model)
    original_packet = original['input']
    if (original['system_prompt'] != prompt or original['model'] != identity
            or digest({'packet': original_packet, 'model': identity, 'prompt': prompt}) != previous['request_hash']
            or digest({'system': prompt, 'input': original_packet,
                       'model': identity, 'contract': POLICY}) != operation
            or {k: v for k, v in original_packet.items() if k != 'output_schema'}
               != {k: v for k, v in packet.items() if k != 'output_schema'}):
        return None
    archived = db.execute('SELECT data FROM analyses WHERE operation=?', (operation,)).fetchone()
    if not archived:
        return None
    raw = json.loads(archived[0])
    if raw.get('operation') != operation or raw.get('model') != identity:
        return None
    try:
        payloads, notes = parse_output(raw['analysis'], schema, packet['output_count'])
    except (ValueError, TypeError):
        return None
    if (len(payloads) != packet['output_count'] or payloads != result.get('payloads', [result['payload']])
            or result['actor_id'] != packet['actor']['id']
            or result['task_id'] != packet['actor']['task_id']
            or result['object_type'] != packet['object_type']
            or notes != result.get('generation_notes', [])
            or result['text_work_id'] != receipt_digest(packet['actor'], previous['request_hash'], payloads, notes)
            or previous['authority_digest'] != digest(packet['commission'])
            or previous['evidence_digest'] != digest(packet['evidence'])):
        return None
    return {**result, 'reused': True}


def material_identity(evidence):
    """Exact material set, not semantic task equivalence or new-work authority."""
    # Reordering/repeating identical inputs or issuing another observation ID
    # for the same exact public text does not introduce new material.
    values = [{k:item[k] for k in ('kind','tool','sha256','text')}
        if item['kind'] == 'public_tool_return' else item for item in evidence
        if item['kind'] != 'source_version_binding']
    return digest(sorted({encode(item) for item in values}))


def substantive_refs(db, actor, evidence):
    """Candidate association, not a claim that input references are output targets."""
    result = set()
    for item in evidence:
        if item['kind'] == 'text_work_candidate':
            selected = item['selection']
            result.add(encode({'type': 'TextWorkCandidate', 'id': selected['text_work_id'],
                               'output_index': selected['output_index']}))
            result.update(encode(ref) for ref in item['ancestor_substantive_refs'])
        if item['kind'] == 'public_tool_return' and item['tool'] == 'read_content_selection':
            from .selection_observations import verified_selection_return
            selected = verified_selection_return(db, actor.id, item['observation_ref'],
                                                 item['text'], item['sha256'])
            for entry in selected['selections']:
                ref = Ref.model_validate(entry['selection']['ref']).model_dump()
                if ref['type'] == 'Evidence' or (ref['type'] == 'ContentNode'
                        and entry.get('claim_kind') != 'structure'):
                    result.add(encode(ref))
        if item['kind'] != 'saved_object':
            continue
        obj = item['object']
        ref = obj['ref']
        if ref['type'] == 'Evidence' or (ref['type'] == 'ContentNode'
                and obj['payload'].get('claim_kind') != 'structure'):
            result.add(encode(ref))
    return result


def unknown_material_conflicts(workspace, db, actor, packet):
    """Find conservative conflicts; changed evidence is not retry authority."""
    from .operation_receipts import archived_input
    prefix = 'text_work:' + actor.id + ':'
    identity = material_identity(packet['evidence'])
    from .source_materials import representation_identity
    source_identity = representation_identity(workspace, actor, packet['evidence'])
    current_refs = substantive_refs(db, actor, packet['evidence'])
    conflicts = []
    for key, encoded in db.execute('SELECT key,value FROM state WHERE substr(key,1,?)=?',
                                   (len(prefix), prefix)).fetchall():
        previous = json.loads(encoded)
        if previous['state'] in {'completed', 'known_failed', 'not_dispatched'}:
            continue
        original = archived_input(db, actor, previous['request_hash'])
        old_identity = previous.get('material_identity')
        old_type = previous.get('object_type')
        shared = set()
        same_source_selection = False
        raw_operation = original['operation'] if original else None
        if original:
            # Length/refusal is a received rejection, not an unknown response.
            if db.execute("SELECT 1 FROM events WHERE kind='evidence_analysis_rejected_response' "
                          "AND json_extract(data,'$.operation')=?", (raw_operation,)).fetchone():
                continue
            if db.execute('SELECT 1 FROM analyses WHERE operation=?', (raw_operation,)).fetchone():
                # A fully archived response may precede a local parse/save failure.
                # It is not an unknown provider outcome; exact replay/cache and
                # ordinary receipt/contract guards retain their responsibility.
                continue
            old_identity = material_identity(original['input']['evidence'])
            if source_identity is not None:
                same_source_selection = source_identity == representation_identity(
                    workspace, actor, original['input']['evidence'])
            old_type = original['input']['object_type']
            shared = current_refs & substantive_refs(db, actor, original['input']['evidence'])
        same = old_type == packet['object_type'] and (old_identity == identity or same_source_selection)
        if old_identity is None or old_type is None or same or (
                old_type == packet['object_type'] and shared):
            detail = {'original_operation_id':key[len(prefix):], 'raw_operation':raw_operation,
                'original_request_hash':previous['request_hash'],
                'previous_stored_state':previous['state'],
                'same_material_established':bool(same),
                'same_source_selection_established':bool(same_source_selection),
                'original_input_verified':original is not None,
                'shared_substantive_refs':[json.loads(r) for r in sorted(shared)],
                'producer_invoked':False,
                'note':'Conservative candidate association while an earlier outcome is unresolved, not a semantic judgment that goals are identical. Same trusted source/range with only table-view expansion changed is not new-work authority, even when representation digests differ. Input refs are evidence, not trusted output targets. A different material digest or additional page does not authorize a retry. Read/inspect existing work or choose independent work; genuinely distinct work requires an evidenced host disposition for the exact request. Prior outcomes and spending reservations remain unknown.'}
            conflicts.append(detail)
    return conflicts


def guard_unknown_material(workspace, db, actor, packet, operation_id=None, request_hash=None):
    conflicts = unknown_material_conflicts(workspace, db, actor, packet)
    if not conflicts:
        return
    if operation_id is not None and request_hash is not None:
        from .text_work_disposition import consume_disposition
        if consume_disposition(db, actor, operation_id, request_hash,
                               material_identity(packet['evidence']), conflicts):
            return
    code = ('TEXT_WORK_SAME_EVIDENCE_OUTCOME_UNRESOLVED'
            if any(c['same_material_established'] or not c['original_input_verified'] for c in conflicts)
            else 'TEXT_WORK_RELATED_OUTCOME_UNRESOLVED')
    # Preserve the existing first-conflict fields as well as all exact bindings.
    detail = {**conflicts[0], 'conflicts':conflicts,
        'candidate_request_hash':request_hash,
        'candidate_material_identity':material_identity(packet['evidence'])}
    raise ActionRejected(code+': '+encode(detail))


def _payload_schema(object_type):
    return ContentNode if object_type == "ContentNode" else TextEvidence


async def produce(workspace, actor, model, operation_id, objective, object_type,
                  input_refs=(), source_selections=(), output_count=1, observation_refs=(),
                  candidate_selections=(), source_version_refs=(), revision=None):
    if actor.role not in {"writer", "coordinator"}:
        raise ActionForbidden("FORBIDDEN: text production role")
    if object_type == "ContentNode" and actor.role != "writer":
        raise ActionForbidden("FORBIDDEN: report authorship belongs to writer")
    if object_type not in {"ContentNode", "Evidence"}:
        raise ActionRejected("TEXT_WORK_OUTPUT_TYPE_NOT_SUPPORTED")
    if not operation_id.strip() or not objective.strip():
        raise ActionRejected("TEXT_WORK_ID_AND_OBJECTIVE_REQUIRED")
    if type(output_count) is not int or not 1 <= output_count <= 32:
        raise ActionRejected("TEXT_WORK_OUTPUT_COUNT_INVALID")
    refs = [Ref.model_validate(r).model_dump() for r in input_refs]
    binding = bind_revision(workspace, actor, revision, object_type, output_count) if revision is not None else None
    if binding:
        for target in binding['targets']:
            if target['ref'] not in refs:
                refs.append(target['ref'])
    selections = [SourceSelection.model_validate(s).packet_selection() for s in source_selections]
    candidates = [CandidateSelection.model_validate(s).model_dump() for s in candidate_selections]
    bindings = [SourceRef.model_validate(r).model_dump() for r in source_version_refs]
    schema = _payload_schema(object_type)
    context = authority(workspace, actor)
    material = prepare_material(workspace,refs,selections,observation_refs,actor,candidates,bindings)
    if object_type == 'Evidence':
        material.require_source()
    packet = {"actor": actor.__dict__, "objective": objective, "object_type": object_type,
              "commission": context, "evidence": material.evidence,
              "output_count": output_count,
              "output_schema": output_contract(QualifierOutput if binding else schema, output_count),
              **({'revision': binding} if binding else {})}
    from . import prompt_sources
    if (prompt_sources.review_interface_profile(workspace.store) == prompt_sources.REVIEW_INTERFACE_V4
            and prompt_sources.report_prompt_profile(workspace.store) == prompt_sources.CONCISE_PROMPTS):
        packet['output_schema'], _ = prompt_sources.describe_content_schema(packet['output_schema'])
    expression_profile = report_expression_profile(workspace.store)
    prompt = (QUALIFIER_WORK_PROMPT if binding else TEXT_WORK_PROMPT) if expression_profile == REPORT_EXPRESSION_V1 else load_prompt(
        expression_source('qualifier-work' if binding else 'text-work', expression_profile))
    request_hash = digest({"packet": packet, "model": model_identity(model), "prompt": prompt})
    key = "text_work:" + actor.id + ":" + operation_id
    with workspace.store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        if row:
            previous = json.loads(row[0])
            if previous["request_hash"] != request_hash:
                reused = completed_schema_replay(db, previous, packet, model, schema, prompt)
                if reused is not None:
                    db.execute('INSERT INTO events(kind,data) VALUES (?,?)', (
                        'text_work_completed_schema_reused', encode({
                            'actor_id': actor.id, 'operation_id': operation_id,
                            'text_work_id': reused['text_work_id'], 'raw_operation': reused['operation'],
                            'original_request_hash': previous['request_hash'],
                            'current_request_hash': request_hash, 'paid_calls': 0})))
                    return reused
                raise ActionRejected("OPERATION_CONFLICT")
            if previous["state"] == "known_failed":
                raise ActionRejected("TEXT_WORK_PREVIOUS_OUTPUT_REJECTED: raw_operation=" + previous["operation"] + "; inspect preserved response; no automatic retry")
            if previous['state'] == 'not_dispatched':
                raise ActionRejected('TEXT_WORK_NOT_DISPATCHED: ' + encode({
                    'admission_proof': previous['admission_proof'], 'provider_outcome': 'not_dispatched',
                    'raw_response_received': False, 'usage': None,
                    'note': 'Original local refusal before any HTTP dispatch. Inspect original reason and current authorization before explicitly choosing a new operation; this receipt grants no additional budget.'}))
            if previous["state"] != "completed":
                raise ActionRejected("TEXT_WORK_OUTCOME_UNRESOLVED: inspect the original attempt; no automatic retry")
            return {**previous["result"], "reused": True}
        if binding:
            check_current_targets(db, binding)
        guard_unknown_material(workspace, db, actor, packet, operation_id, request_hash)
        db.execute("INSERT INTO state VALUES (?,?)", (key, encode({
            "request_hash": request_hash, "state": "reserved", "actor": actor.__dict__,
            "object_type":object_type, "material_identity":material_identity(packet['evidence'])})))
    raw = await analyze_evidence_packet(workspace, model, packet, prompt,
                                        POLICY, reserve_attempt=True,
                                        parent_reservation=(key, {'request_hash': request_hash, 'actor': actor.__dict__}),
                                        owner=actor, caller_operation_id=operation_id)
    try:
        payloads, notes = parse_produced_output(raw['analysis'], schema, packet)
        for payload in payloads if object_type == "Evidence" else []:
            material.check_returned_refs(payload)
    except (ValueError, TypeError) as exc:
        # The service has already returned and its exact raw response is saved.
        # Do not let native tool-argument error handling misclassify this phase.
        if isinstance(exc, ValidationError):
            detail = [{"path": list(e["loc"]), "type": e["type"], "message": e["msg"]}
                      for e in exc.errors(include_input=False, include_url=False)]
        elif isinstance(exc, json.JSONDecodeError):
            detail = {"message": exc.msg, "line": exc.lineno, "column": exc.colno}
        else:
            detail = {"type": type(exc).__name__, "message": str(exc)}
        failure = {"request_hash": request_hash, "state": "known_failed", "actor": actor.__dict__,
            "raw_response_received": True, "operation": raw["operation"],
            "failure_phase": "output_contract_validation", "diagnostic": detail,
            "usage": raw.get("usage"), "duration_seconds": raw.get("duration_seconds")}
        workspace.store.set(key, failure)
        workspace.store.event("text_work_output_rejected", failure)
        raise ActionRejected("TEXT_WORK_OUTPUT_CONTRACT_INVALID: raw_operation=" + raw["operation"] +
            "; received response retained, output rejected before adoption; " + encode(detail)) from exc
    receipt = receipt_digest(actor.__dict__, request_hash, payloads, notes)
    result = {"text_work_id": receipt, "object_type": object_type, "payload": payloads[0], "payloads": payloads,
              "actor_id": actor.id, "task_id": actor.task_id, "operation": raw["operation"],
              "model": raw["model"], "usage": raw["usage"], "duration_seconds": raw["duration_seconds"],
              "state": "completed", "semantic_correctness_verified": False,
              **({'revision': binding} if binding else {}),
              **({"generation_notes":notes} if notes else {}),
              "limitation": "Received validated tool output for these selections; not review or engineering acceptance."}
    stored = {"request_hash": request_hash, "state": "completed", "result": result,
              "authority_digest": digest(context), "evidence_digest": material.evidence_digest,
              "input_refs": refs, "source_selections": selections,"observation_refs":list(observation_refs),
              **({'revision': binding} if binding else {}),
              **({'candidate_selections': candidates} if candidates else {}),
              **({'source_version_refs': bindings} if bindings else {})}
    with workspace.store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        receipt_key = "text_work_receipt:" + receipt
        existing = db.execute("SELECT value FROM state WHERE key=?", (receipt_key,)).fetchone()
        if existing and encode(json.loads(existing[0])) != encode(stored):
            raise ActionRejected("TEXT_WORK_RECEIPT_IDENTITY_CONFLICT")
        db.execute("UPDATE state SET value=? WHERE key=?", (encode(stored), key))
        if not existing:
            db.execute("INSERT INTO state VALUES (?,?)", (receipt_key, encode(stored)))
    workspace.store.event("text_work_completed", {"text_work_id": receipt, "actor_id": actor.id,
        "operation": raw["operation"], "object_type": object_type, "payload_digest": digest(payloads)})
    return {**result, "reused": False}


def adopt(workspace, actor, receipt, object_type, payload=None, index=0, previous_ref=None):
    stored = workspace.store.get("text_work_receipt:" + receipt)
    if not stored or stored["state"] != "completed":
        raise ActionRejected("TEXT_WORK_RECEIPT_REQUIRED")
    result = stored["result"]
    if result["actor_id"] != actor.id or result["task_id"] != actor.task_id:
        raise ActionForbidden("FORBIDDEN: text work belongs to another task")
    if result["object_type"] != object_type:
        raise ActionRejected("TEXT_WORK_OUTPUT_TYPE_MISMATCH")
    if (digest(authority(workspace, actor)) != stored["authority_digest"] or
            prepare_material(workspace,stored['input_refs'],stored['source_selections'],
                stored.get('observation_refs',()),actor,stored.get('candidate_selections',()),
                stored.get('source_version_refs',())).evidence_digest != stored['evidence_digest']):
        raise ActionRejected("TEXT_WORK_INPUT_OR_AUTHORITY_CHANGED")
    payloads = result.get("payloads", [result["payload"]])
    if not 0 <= index < len(payloads):
        raise ActionRejected("TEXT_WORK_OUTPUT_INDEX_INVALID")
    check_adoption(stored, index, previous_ref)
    if payload is not None:
        schema = _payload_schema(object_type)
        try:
            submitted = schema.model_validate(payload).model_dump()
            received = schema.model_validate(payloads[index]).model_dump()
        except ValidationError as exc:
            raise ActionRejected("TEXT_WORK_OUTPUT_CHANGED: request new text work instead of rewriting tool output") from exc
        if submitted != received:
            changed_fields = sorted(k for k in submitted.keys() | received.keys()
                                    if submitted.get(k) != received.get(k))
            diagnostic = {"object_type": object_type, "output_index": index,
                          "changed_fields": changed_fields}
            if "qualifiers" in changed_fields:
                left, right = submitted["qualifiers"], received["qualifiers"]
                diagnostic["changed_qualifier_keys"] = sorted(k for k in left.keys() | right.keys()
                    if k not in left or k not in right or left[k] != right[k])
            raise ActionRejected("TEXT_WORK_OUTPUT_CHANGED: request new text work instead of rewriting tool output",
                                 diagnostic=diagnostic)
    return json.loads(encode(payloads[index]))


def structural_node(payload):
    return (payload.get("kind") in {"report", "chapter"}
            and payload.get("claim_kind") == "structure" and payload.get("qualifiers") == {}
            and set(payload.get("body", {})) == {"text"}
            and isinstance(payload["body"]["text"], str)
            and 0 < len(payload["body"]["text"].strip()) <= 240
            and "\n" not in payload["body"]["text"] and "\r" not in payload["body"]["text"])


def guarded_tools(workspace, role, model, base_tools):
    """Registered-agent surface; host Store APIs remain available for dated data."""
    by_name = {t.__name__: t for t in base_tools}

    async def process_report_content(operation_id: str, objective: str,
            object_type: Literal["ContentNode", "Evidence"], input_refs: list[Ref] = [],
            source_selections: list[SourceSelection] = [],
            output_count: Annotated[int, Field(ge=1, le=32, strict=True, description="Number of related output payloads, from 1 to 32; zero-based adoption indexes.")] = 1,
            observation_refs: list[ObservationRef] = [],
            candidate_selections: list[CandidateSelection] = [],
            source_version_refs: list[SourceRef] = [],
            revision: ContentRevision | None = None) -> dict:
        """Independent one-shot text work on selected evidence. Choose the objective,
        materials and output type; do not supply a finished report or dictated verdict.
        Returns an exact actor-bound payload/receipt, without committing content.
        Optional revision={scope:'qualifiers',targets:[exact owned ContentNode refs]}
        changes only qualifiers, preserving body/kind/claim_kind exactly. Targets
        must be current owned versions, unique, ordered and equal to output_count.
        Targets are included as draft inputs, not source facts. Choose real evidence
        for factual judgments. Adopt each output only with its target previous_ref.
        To revise substantive body instead, use ordinary complete-content output.
        output_count is an integer from 1 to 32 for a related batch, with zero-based adoption indexes;
        no mandatory call per node. Pass saved SourceArtifact refs plus located source
        selections to bind exact source versions without including whole source text.
        Alternatively source_version_refs binds existing SourceArtifact versions to
        actual source_selections or your own source observations without inserting
        whole-source bodies. It does not capture versions or authorize new material.
        Evidence output needs at least one such legal supplied source reference.
        Optional candidate_selections reads your own completed unadopted text-work
        payloads by receipt and zero-based output_index. Use these draft inputs for
        revision instead of copying the draft into objective or adopting it first.
        They remain unreviewed drafts, not source facts or authority; select original
        evidence for factual checks. They preserve ancestor associations with unresolved text work.
        Optional observation_refs consumes your own exact authorized public source,
        image or content tool returns on the tool side, without copying them into
        your decision messages or objective. Scratch and another task's returns are
        not authorized evidence. output_count is an output selection-count, not a character or token limit. Evidence is preserved exactly. Complete model requests use shared service-capacity admission; material preparation does not impose an independent character limit.
        An unresolved earlier production blocks new production on the same complete
        material set, or sharing exact substantive ContentNode/Evidence refs, for
        this actor and output type. This is conservative association, not semantic
        equivalence. Adding a page, changing IDs or wording is not retry authority.
        Read existing work or choose independent work. Distinct related work needs
        an evidenced host disposition bound to that exact request, not a caller
        declaration. Inspect the original outcome; unknown reservations remain.
        The original writer may adopt it unchanged. No search, agents or publication.
        """
        return await produce(workspace, actor_for_tool(workspace, role), model, operation_id,
                             objective, object_type, input_refs, source_selections, output_count,observation_refs,
                             candidate_selections,source_version_refs,revision)

    def commit_guarded(operation_id: str, objects: list[GuardedObject], deliverable_selection=None) -> dict:
        """Commit owned decisions/structure/relations, or adopt exact text-tool payloads.
        ContentNode/Evidence substantive payloads require text_work_id; payload can
        be omitted for adoption. Only a single-line report/chapter heading with
        claim_kind=structure and empty qualifiers is an agent structure decision.
        Table cells, captions and substantive qualifiers cannot be rewritten here.
        Coordinator cannot author report nodes. Ownership/CAS/batch refs are unchanged.
        Criterion requires requirement_refs (saved Requirement Ref objects), purpose,
        scope, expected_outcome, evidence_expectation, allowed_limits. Source IDs,
        SourceArtifact refs and operator instruction IDs are not Requirement refs.
        exact current input_refs are in read_decision_state; use content_status for
        more. Relation requires subject_ref,predicate,object_ref,provenance_kind;
        contains also position. Use {client_key:key} for new refs within this batch.
        Reuse an operation_id only with identical arguments; correcting a known
        failure needs a new operation ID. Inspect unknown writes before retrying.
        """
        actor = actor_for_tool(workspace, role)
        values = []
        for raw in objects:
            # Normalize only at the deterministic handler, after exposing precise
            # per-type schemas to the native tool registration.
            if hasattr(raw, 'model_dump'):
                raw = raw.model_dump(exclude_unset=True)
            obj = AdoptionObject.model_validate(raw).model_dump(exclude_none=True)
            kind, payload, receipt = obj["type"], obj.get("payload"), obj.pop("text_work_id", None)
            index = obj.pop("text_work_index")
            if kind == "ContentNode" and role != "writer":
                raise ActionForbidden("FORBIDDEN: report authorship belongs to writer")
            if receipt:
                if kind not in {"ContentNode", "Evidence"}:
                    raise ActionRejected("TEXT_WORK_CANNOT_REPLACE_DECISION_OBJECT")
                obj["payload"] = adopt(workspace, actor, receipt, kind, payload, index, obj.get('previous_ref'))
            elif kind == "ContentNode":
                if payload is None or not structural_node(payload):
                    raise ActionRejected("SUBSTANTIVE_CONTENT_REQUIRES_TEXT_WORK")
            elif kind == "Evidence":
                # A literal selection is deterministic extraction, not agent-authored
                # synthesis. Derived explanations use the independent text tool.
                value = Evidence.model_validate(payload).model_dump()
                sources, excerpt = value["source_refs"], value["excerpt"]
                if (not sources and not excerpt and value["input_refs"] and value["method"] == "sum_products"
                        and value["tool_receipt"] and value["extraction_ref"] is None):
                    with workspace.store.connect() as db:
                        row = db.execute("SELECT actor_id,data FROM content_observations WHERE id=?",
                                         (value["tool_receipt"],)).fetchone()
                    observation = json.loads(row[1]) if row else {}
                    if (not row or row[0] != actor.id or observation.get("tool") != "sum_products"
                            or value["result"] != observation.get("result")):
                        raise ActionRejected("CALCULATION_EVIDENCE_REQUIRES_EXACT_OWNED_RECEIPT")
                    for ref in value["input_refs"]:
                        ContentStore(workspace.store).read(ref)
                    obj["payload"] = value
                    values.append(obj)
                    continue
                if (value["input_refs"] or value["method"] or value["tool_receipt"]
                        or value["result"] is not None or value["extraction_ref"] is not None
                        or not sources or not excerpt
                        or any(r["type"] != "SourceArtifact" or excerpt not in ContentStore(workspace.store).read(r)["payload"]["content"] for r in sources)):
                    raise ActionRejected("DERIVED_EVIDENCE_REQUIRES_TEXT_WORK")
                obj["payload"] = value
            elif payload is None:
                raise ActionRejected("DECISION_PAYLOAD_REQUIRED")
            values.append(obj)
        if deliverable_selection is not None:
            return by_name['commit_objects'](operation_id, values, deliverable_selection=deliverable_selection)
        return by_name["commit_objects"](operation_id, values)

    def save_guarded(operation_id: str, text_work_id: str, previous_ref: Ref | None = None,
                     text_work_index: int = 0, deliverable_selection=None) -> dict:
        """Adopt one exact independent ContentNode result with the writer's ownership.
        No body/qualifier override is accepted. previous_ref keeps ordinary CAS and
        revision limits; this does not publish or create evidence links.
        """
        return commit_guarded(operation_id, [AdoptionObject(client_key="text", type="ContentNode",
            text_work_id=text_work_id, previous_ref=previous_ref, text_work_index=text_work_index)], deliverable_selection)

    def commit_objects(operation_id: str, objects: list[GuardedObject]) -> dict:
        return commit_guarded(operation_id, objects)
    commit_objects.__doc__ = commit_guarded.__doc__

    def save_text_node(operation_id: str, text_work_id: str, previous_ref: Ref | None = None, text_work_index: int = 0) -> dict:
        return save_guarded(operation_id, text_work_id, previous_ref, text_work_index)
    save_text_node.__doc__ = save_guarded.__doc__

    from .prompt_sources import review_interface_profile, load_prompt
    if review_interface_profile(workspace.store) == 'review-interfaces-v4':
        save_note = '\n\n' + load_prompt('deliverable-save-tool-v4')
        def commit_with_selection(operation_id: str, objects: list[GuardedObject],
                                  deliverable_selection: DeliverableSelection | None = None) -> dict:
            return commit_guarded(operation_id, objects, deliverable_selection)
        commit_with_selection.__name__, commit_with_selection.__doc__ = 'commit_objects', commit_guarded.__doc__ + save_note
        def save_with_selection(operation_id: str, text_work_id: str, previous_ref: Ref | None = None,
                text_work_index: int = 0, deliverable_selection: DeliverableSelection | None = None) -> dict:
            return save_guarded(operation_id, text_work_id, previous_ref, text_work_index, deliverable_selection)
        save_with_selection.__name__, save_with_selection.__doc__ = 'save_text_node', save_guarded.__doc__ + save_note
        commit_objects, save_text_node = commit_with_selection, save_with_selection

    from .prompt_sources import content_input_profile, RELATION_ENDPOINTS_V2
    if content_input_profile(workspace.store) == RELATION_ENDPOINTS_V2:
        commit_objects.__annotations__['objects'] = list[GuardedObjectV2]
    replacements = {"commit_objects": commit_objects, "save_text_node": save_text_node}
    result = [replacements.get(t.__name__, t) for t in base_tools]
    if role in {"coordinator", "writer"}:
        from .operation_identity import profile, NATIVE, native_id
        if profile(workspace.store) == NATIVE:
            async def native_process_report_content(objective: str,
                    object_type: Literal["ContentNode", "Evidence"], input_refs: list[Ref] = [],
                    source_selections: list[SourceSelection] = [],
                    output_count: Annotated[int, Field(ge=1, le=32, strict=True, description="Number of related output payloads, from 1 to 32; zero-based adoption indexes.")] = 1,
                    observation_refs: list[ObservationRef] = [],
                    candidate_selections: list[CandidateSelection] = [],
                    source_version_refs: list[SourceRef] = [],
                    revision: ContentRevision | None = None,
                    runtime: ToolRuntime = None) -> dict:
                identity = native_id(runtime.tool_call_id if runtime is not None else None)
                work = await process_report_content(identity, objective, object_type, input_refs,
                    source_selections, output_count, observation_refs, candidate_selections,
                    source_version_refs, revision)
                return {**work, 'operation_id': identity}
            native_process_report_content.__name__ = process_report_content.__name__
            native_process_report_content.__doc__ = process_report_content.__doc__
            result.append(native_process_report_content)
        else:
            result.append(process_report_content)
    return result
