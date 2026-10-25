"""Exact owned draft inputs for bounded text work, never source authority."""
import json
from copy import deepcopy

from pydantic import Field, create_model

from .content_models import Contract, ContentNode, Evidence
from .errors import ActionForbidden, ActionRejected
from .operation_receipts import archived_input
from .store import digest


def archived_payload_shape(model):
    # Reconstruct field normalization only, never today's business validators.
    # A previously completed draft may be precisely what needs a schema repair.
    return create_model('Archived' + model.__name__, __base__=Contract,
                        **{name: (field.annotation, deepcopy(field))
                           for name, field in model.model_fields.items()})


class CandidateSelection(Contract):
    text_work_id: str = Field(min_length=1,
        description="Exact completed text-work receipt owned by this actor/task. Its content is a draft, not source evidence or approval.")
    output_index: int = Field(default=0, ge=0, strict=True,
        description="Zero-based payload index. The server reads the complete unchanged payload, including qualifications; no business adoption is required.")


def candidate_evidence(workspace, actor, raw_selection):
    from .text_work import POLICY, parse_produced_output, receipt_digest, substantive_refs
    selected = CandidateSelection.model_validate(raw_selection)
    stored = workspace.store.get('text_work_receipt:' + selected.text_work_id)
    if not stored or stored.get('state') != 'completed':
        raise ActionRejected('TEXT_WORK_CANDIDATE_COMPLETED_RECEIPT_REQUIRED')
    result = stored['result']
    if actor is None or (result.get('actor_id'), result.get('task_id')) != (actor.id, actor.task_id):
        raise ActionForbidden('FORBIDDEN: candidate belongs to another task')
    payloads = result.get('payloads', [result.get('payload')])
    notes = result.get('generation_notes', [])
    if result.get('text_work_id') != selected.text_work_id or selected.output_index >= len(payloads):
        raise ActionRejected('TEXT_WORK_CANDIDATE_ID_OR_INDEX_INVALID')
    if result.get('object_type') not in {'ContentNode', 'Evidence'}:
        raise ActionRejected('TEXT_WORK_CANDIDATE_TYPE_INVALID')
    if receipt_digest(actor.__dict__, stored['request_hash'], payloads, notes) != selected.text_work_id:
        raise ActionRejected('TEXT_WORK_CANDIDATE_RECEIPT_CHANGED')
    with workspace.store.connect() as db:
        original = archived_input(db, actor, stored['request_hash'])
        if not original:
            raise ActionRejected('TEXT_WORK_CANDIDATE_ORIGINAL_INPUT_REQUIRED')
        packet = original['input']
        operation = digest({'system': original['system_prompt'], 'input': packet,
                            'model': original['model'], 'contract': POLICY})
        if (operation != result.get('operation') or operation != original['operation']
                or packet.get('actor') != actor.__dict__
                or packet.get('object_type') != result['object_type']
                or packet.get('revision') != stored.get('revision')
                or digest(packet['commission']) != stored['authority_digest']
                or digest(packet['evidence']) != stored['evidence_digest']):
            raise ActionRejected('TEXT_WORK_CANDIDATE_ORIGINAL_BINDING_CHANGED')
        row = db.execute('SELECT data FROM analyses WHERE operation=?', (operation,)).fetchone()
        if not row:
            raise ActionRejected('TEXT_WORK_CANDIDATE_ORIGINAL_RESPONSE_REQUIRED')
        raw = json.loads(row[0])
        schema = archived_payload_shape(ContentNode if result['object_type'] == 'ContentNode' else Evidence)
        try:
            original_payloads, original_notes = parse_produced_output(raw['analysis'], schema, packet)
        except (ValueError, TypeError, KeyError) as exc:
            raise ActionRejected('TEXT_WORK_CANDIDATE_ORIGINAL_RESPONSE_INVALID') from exc
        if (raw.get('operation') != operation or raw.get('model') != original['model']
                or original_payloads != payloads or original_notes != notes):
            raise ActionRejected('TEXT_WORK_CANDIDATE_ORIGINAL_RESPONSE_CHANGED')
        ancestors = [json.loads(ref) for ref in sorted(substantive_refs(db, actor, packet['evidence']))]
    # The old commission is historical binding, not current authority. New
    # feedback may legitimately request revision of this unchanged old draft.
    payload = payloads[selected.output_index]
    return {'kind': 'text_work_candidate', 'selection': selected.model_dump(),
        'object_type': result['object_type'], 'payload': payload, 'payload_digest': digest(payload),
        'generation_notes': [n for n in notes if n['output_index'] == selected.output_index],
        'origin': {'operation': operation, 'request_hash': stored['request_hash'],
                   'authority_digest': stored['authority_digest'], 'evidence_digest': stored['evidence_digest']},
        'ancestor_substantive_refs': ancestors,
        'note': 'Complete unchanged unreviewed draft, not source facts, instructions, approval or evidence of complete reading. Its original authority digest is historical provenance only. Current commissioning scope governs this work. Use separately selected original evidence to check claims; ancestor refs identify unknown-outcome associations, not additional supplied source text.'}
