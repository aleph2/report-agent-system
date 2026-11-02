"""Internal Reviewer step services; not registered in the current interface."""
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .errors import ActionForbidden, ActionRejected
from .store import digest, encode
from . import review_handles as handles
from .review_message import (ReviewMessage, assemble_check, bind_review_message,
                             validate_message_binding)
from .message_fields import validate_message


class FindingDraft(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    check: str
    kind: Literal['candidate', 'confirmed_defect', 'unresolved', 'suggestion']
    claim: str
    impact: str
    needed_outcome: str
    location: str
    basis: Literal['supplied_content', 'snapshot_structure', 'input_gap'] | None = None
    evidence: list[str]


class CheckMark(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    check: str
    execution_state: Literal['not_started', 'partial', 'completed', 'blocked']
    verdict: Literal['satisfied', 'not_satisfied', 'undetermined'] | None
    assessment: str
    evidence: list[str]
    remaining_work: str = ''
    findings: list[str] | None = None
    outside_assignment_notes: list[str] = Field(default_factory=list)
    correction_reason: str = ''


def _get(db, key, default=None):
    row = db.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()
    return json.loads(row[0]) if row else default


def _put(db, key, value):
    db.execute('INSERT OR REPLACE INTO state VALUES (?,?)', (key, encode(value)))


def _open(db, actor):
    if _get(db, 'review_finished:' + actor.task_id):
        raise ActionRejected('REVIEW_FINISHED')


def _drafts(db, actor):
    rows = db.execute("SELECT value FROM state WHERE substr(key,1,?)=? ORDER BY rowid",
                      (len('review_draft:' + actor.task_id + ':'), 'review_draft:' + actor.task_id + ':')).fetchall()
    return [json.loads(row[0]) for row in rows if json.loads(row[0])['actor_id'] == actor.id]


def _evidence(contents, actor, selected, binding):
    if len(set(selected)) != len(selected):
        raise ActionRejected('INVALID_EVIDENCE_SELECTION')
    ids = [r['receipt_id'] for r in binding['receipts']]
    return [ids.index(handles.resolve(contents, actor, 'evidence', h)) for h in selected]


def _binding(contents, actor):
    return bind_review_message(contents, actor, list(handles.evidence_handles(contents, actor).values()))


def _finding_fields(draft, evidence_indexes):
    fields = draft['fields']
    return {'finding_type': fields['kind'],
        'finding_locator_state': {'absent': 'absent', 'unclear': 'ambiguous'}.get(fields['location'], 'located'),
        'finding_description': fields['claim'], 'finding_impact': fields['impact'],
        'finding_needed_outcome': fields['needed_outcome'], 'finding_basis_kind': fields['basis'],
        'evidence_indexes': evidence_indexes}


def _validate_fields(contents, actor, model, fields):
    """Report safely decidable field and handle problems together, before saving."""
    task = handles._task(contents, actor)
    issues, value = [], None
    try:
        value = validate_message(model, fields).model_dump()
    except ActionRejected as error:
        issues.extend(error.diagnostic['fields'])
    invalid = {i['field'][0] for i in issues if i['field']}
    safe = {k: fields[k] for k in model.model_fields if k in fields and k not in invalid}
    safe.update({k: f.get_default(call_default_factory=True) for k, f in model.model_fields.items()
                 if k not in fields and not f.is_required()})
    choices = {'check': list(handles.check_handles(task)),
               'evidence': list(handles.evidence_handles(contents, actor))}
    with contents.store.connect() as db:
        drafts = {d['finding']: d for d in _drafts(db, actor)
                  if d['fields']['check'] == fields.get('check') and d['status'] != 'withdrawn'}
        old = _get(db, 'review_check:' + actor.task_id + ':' + str(fields.get('check')))
    if model is FindingDraft:
        choices['location'] = [*handles.content_handles(contents, task['payload']['review_snapshot_ref']), 'absent', 'unclear']
    else:
        choices['findings'] = list(drafts)
    for name, valid in choices.items():
        raw = fields.get(name)
        selected = raw if isinstance(raw, list) else [raw] if name in {'check', 'location'} else []
        seen = set()
        for i, handle in enumerate(selected):
            if not isinstance(handle, str) or handle not in valid or handle in seen:
                issues.append({'field': [name, i] if isinstance(raw, list) else [name],
                    'reason': 'UNKNOWN_OR_DUPLICATE_HANDLE', 'handle': handle, 'valid_handles': valid})
            if isinstance(handle, str):
                seen.add(handle)
    names = {'finding_type': 'kind', 'finding_locator_state': 'location', 'finding_description': 'claim',
             'finding_impact': 'impact', 'finding_needed_outcome': 'needed_outcome',
             'finding_basis_kind': 'basis', 'evidence_indexes': 'evidence'}
    if model is FindingDraft:
        message = {'execution_state': 'partial', 'verdict': None,
                   'assessment': 'Unsaved draft.', 'remaining_work': 'Save or withdraw.'}
        message.update({k: safe[v] for k, v in names.items() if v in safe})
        if 'location' in safe:
            message['finding_locator_state'] = {'absent': 'absent', 'unclear': 'ambiguous'}.get(safe['location'], 'located')
        # Draft text is required independently of whether its kind parsed.
        for name in ('claim', 'impact', 'needed_outcome'):
            if name in safe and not safe[name].strip():
                issues.append({'field': [name], 'reason': 'FINDING_FIELDS_REQUIRED'})
    else:
        message = {k: safe[k] for k in ('execution_state', 'verdict', 'assessment', 'remaining_work') if k in safe}
        if old and 'correction_reason' in safe and not safe['correction_reason'].strip():
            issues.append({'field': ['correction_reason'], 'reason': 'CORRECTION_REASON_REQUIRED'})
    if 'evidence' in safe:
        message['evidence_indexes'] = list(range(len(safe['evidence'])))
    selected = (safe.get('findings') if safe.get('findings') is not None else list(drafts)) if model is CheckMark and 'findings' not in invalid else []
    messages = [message, *[{**message, **_finding_fields(drafts[h], list(range(len(drafts[h]['fields']['evidence']))))}
                          for h in selected if h in drafts]]
    codes = dict.fromkeys(code for message in messages
        for code in ReviewMessage.model_construct(**message).consistency_errors(set(message)))
    for code in codes:
        related, explanation = ReviewMessage.diagnostic_errors[code]
        issues.append({'field': [names.get(k, k) for k in related], 'reason': code, 'message': explanation})
    if issues:
        raise ActionRejected('MESSAGE_FIELDS_INVALID: ' + ', '.join(str(i['field']) for i in issues),
                             diagnostic={'fields': issues})
    return task, handles.check_handles(task)[value['check']], value


def record_finding(contents, actor, operation_id, **fields):
    task, index, value = _validate_fields(contents, actor, FindingDraft, fields)
    binding = _binding(contents, actor)
    evidence = _evidence(contents, actor, value['evidence'], binding)
    location = (None if value['location'] in {'absent', 'unclear'}
                else handles.resolve_content(contents, actor, value['location']))
    validate_message(ReviewMessage, {'assigned_scope_index': index, 'execution_state': 'partial',
        'verdict': None, 'assessment': 'Unsaved finding draft; no check completion.',
        'remaining_work': 'Save the check or explicitly withdraw this draft.',
        **_finding_fields({'fields': value}, evidence)})
    def save(db):
        _open(db, actor)
        validate_message_binding(contents, db, actor, binding)
        handle = 'F' + str(len(_drafts(db, actor)) + 1)
        draft = {'finding': handle, 'actor_id': actor.id, 'task_id': actor.task_id,
            'snapshot_ref': task['payload']['review_snapshot_ref'], 'location_ref': location,
            'fields': value, 'binding': binding, 'status': 'open'}
        _put(db, 'review_draft:' + actor.task_id + ':' + handle, draft)
        return {'finding': handle}
    return contents.operation(actor, operation_id, {'record_finding': fields}, save)


def mark_check(contents, actor, operation_id, *, runtime_identity=None, **fields):
    handles._task(contents, actor)
    request = {'mark_check': fields, 'runtime_identity': runtime_identity or {}}
    with contents.store.connect() as db:
        previous = db.execute('SELECT 1 FROM content_operations WHERE operation_id=?', (operation_id,)).fetchone()
        if not previous:
            _open(db, actor)
    if previous:
        # The existing operation ledger alone decides success, conflict or unknown outcome.
        return contents.operation(actor, operation_id, request, lambda db: None)
    task, index, value = _validate_fields(contents, actor, CheckMark, fields)
    binding = _binding(contents, actor)
    with contents.store.connect() as db:
        _open(db, actor)
        drafts = {d['finding']: d for d in _drafts(db, actor)
                  if d['fields']['check'] == value['check'] and d['status'] != 'withdrawn'}
        chosen = value['findings'] if value['findings'] is not None else list(drafts)
        if len(set(chosen)) != len(chosen) or any(h not in drafts for h in chosen):
            raise ActionRejected('UNKNOWN_OR_DUPLICATE_FINDING', diagnostic={'valid_handles': list(drafts)})
        selected = [drafts[h] for h in chosen]
        for draft in selected:
            validate_message_binding(contents, db, actor, draft['binding'])
        old = _get(db, 'review_check:' + actor.task_id + ':' + value['check'])
    message = {k: value[k] for k in ('execution_state', 'verdict', 'assessment', 'remaining_work', 'outside_assignment_notes')}
    message.update(assigned_scope_index=index, evidence_indexes=_evidence(contents, actor, value['evidence'], binding))
    if value['execution_state'] == 'completed':
        target = task['payload']['review_requirements'][index]['target_ref']
        if target in binding['coverage_refs']:
            message.update(coverage_object_indexes=[binding['coverage_refs'].index(target)],
                           coverage_state='assessed', coverage_reason=value['assessment'])
    finding_values = [_finding_fields(d, _evidence(contents, actor, d['fields']['evidence'], binding)) for d in selected]
    submission = assemble_check(contents, actor, binding, message, finding_values)
    step = {'request': request, 'check': value['check'], 'old': old,
            'drafts': selected, 'correction_reason': value['correction_reason'],
            'checks': list(handles.check_handles(task))}
    return contents.submit_review(actor, operation_id, submission, runtime_identity or {},
                                  review_message_binding=binding, review_step=step)


def finalize_mark(contents, db, actor, operation_id, review_ref, step):
    """Save replacement, lineage, draft state and immutable locations in one transaction."""
    _open(db, actor)
    key = 'review_check:' + actor.task_id + ':' + step['check']
    if _get(db, key) != step['old']:
        raise ActionRejected('REVIEW_CHECK_CHANGED')
    links = []
    for index, draft in enumerate(step['drafts']):
        draft_key = 'review_draft:' + actor.task_id + ':' + draft['finding']
        if _get(db, draft_key) != draft:
            raise ActionRejected('REVIEW_DRAFT_CHANGED')
        validate_message_binding(contents, db, actor, draft['binding'])
        links.append({k: draft[k] for k in ('finding', 'actor_id', 'snapshot_ref', 'location_ref')} |
                     {'review_ref': review_ref, 'item_index': 0, 'finding_index': index})
        _put(db, draft_key, {**draft, 'status': 'saved'})
    if step['old']:
        contents._supersede_review(db, actor, step['old'], review_ref, step['correction_reason'])
    _put(db, 'review_finding_locations:' + digest(review_ref), links)
    _put(db, key, review_ref)
    return {'open_checks': [h for h in step['checks'] if not _get(db, 'review_check:' + actor.task_id + ':' + h)]}


def withdraw_finding(contents, actor, operation_id, finding, reason):
    handles._task(contents, actor)
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 500:
        raise ActionRejected('WITHDRAWAL_REASON_REQUIRED: use 1 to 500 characters')
    def save(db):
        _open(db, actor)
        drafts = {d['finding']: d for d in _drafts(db, actor)}
        if finding not in drafts:
            raise ActionRejected('UNKNOWN_REVIEW_FINDING', diagnostic={'valid_handles': list(drafts)})
        draft = drafts[finding]
        if draft['status'] == 'saved':
            raise ActionRejected('SAVED_FINDING_REQUIRES_REVIEW_CORRECTION')
        if draft['status'] == 'withdrawn' and draft['withdrawal_reason'] != reason:
            raise ActionRejected('WITHDRAWAL_REASON_CHANGED')
        _put(db, 'review_draft:' + actor.task_id + ':' + finding,
             {**draft, 'status': 'withdrawn', 'withdrawal_reason': reason})
        return {'finding': finding, 'status': 'withdrawn', 'reason': reason}
    return contents.operation(actor, operation_id, {'withdraw_finding': finding, 'reason': reason}, save)


def finish_review(contents, actor, operation_id, *, summary):
    task = handles._task(contents, actor)
    if not isinstance(summary, str) or not summary.strip():
        raise ActionRejected('REVIEW_SUMMARY_REQUIRED')
    def save(db):
        _open(db, actor)
        checks = handles.check_handles(task)
        open_checks = [h for h in checks if not _get(db, 'review_check:' + actor.task_id + ':' + h)]
        open_drafts = [d['finding'] for d in _drafts(db, actor) if d['status'] == 'open']
        if open_checks or open_drafts:
            raise ActionRejected('REVIEW_UNFINISHED: open checks ' + ', '.join(open_checks) +
                '; open drafts ' + ', '.join(open_drafts), diagnostic={'open_checks': open_checks, 'open_drafts': open_drafts})
        from .task_supervision import reconcile
        outcome = reconcile(contents, actor.task_id)
        unresolved = [h for h, i in checks.items() if outcome['requirements'][i]['state'] != 'completed']
        result = {'summary': summary, 'unresolved_checks': unresolved, 'unresolved_count': len(unresolved),
                  'whole_report_acceptance': False, 'execution_complete': outcome['execution_complete']}
        _put(db, 'review_finished:' + actor.task_id, result)
        db.execute('INSERT INTO events(kind,data) VALUES (?,?)',
                   ('review_finished', encode({'actor_id': actor.id, 'task_id': actor.task_id, **result})))
        return result
    return contents.operation(actor, operation_id, {'finish_review': summary}, save)


def metrics(store, task_id=None):
    with store.connect() as db:
        rows = db.execute("SELECT value FROM state WHERE key GLOB 'review_draft:*'").fetchall()
    drafts = [json.loads(r[0]) for r in rows if task_id is None or json.loads(r[0])['task_id'] == task_id]
    return {'drafts': len(drafts), 'withdrawals': sum(d['status'] == 'withdrawn' for d in drafts),
            'open_drafts': sum(d['status'] == 'open' for d in drafts)}


def saved_findings(contents, actor, review_ref):
    handles._task(contents, actor)
    record = contents.read(review_ref)
    if record['ref']['type'] != 'ReviewRecord' or record['owner_id'] != actor.id or record['task_id'] != actor.task_id:
        raise ActionForbidden('REVIEW_FINDINGS_NOT_AUTHORIZED')
    return contents.store.get('review_finding_locations:' + digest(review_ref), [])
