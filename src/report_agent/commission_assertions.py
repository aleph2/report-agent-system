"""Native Coordinator interpretations and owner answers to commission checkpoints."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from uuid import NAMESPACE_URL, uuid5

from . import assertions, legacy_state
from .assertion_host import AssertionHost, Grant
from .assertions.launch import Commission
from .content_store import ContentStore
from .errors import ActionForbidden, ActionRejected
from .plan_authority import _directory
from .store import encode


def _subject(kind, issue_id):
    if kind not in ('plan', 'requirements') or not issue_id:
        raise ValueError('A plan or requirements checkpoint and its issue ID are required')
    return f'commission-checkpoint/{kind}/{issue_id}'


def _rows(storage, subject=None):
    directory = _directory(storage)
    return Commission.planning_actions(directory, subject) if directory else []


def _require_actor(actor, role):
    if role == 'coordinator':
        authorized = actor.role == role and actor.id == 'content:coordinator'
    else:
        authorized = actor.role == 'operator' and actor.id == 'operator'
    if not authorized:
        raise ActionForbidden(f'COMMISSION_{role.upper()}_REQUIRED')


def _context(store, actor, role, operation_id, subject, ref, action, target=None):
    grant = Grant(str(uuid5(NAMESPACE_URL, actor.id)), role, actor.task_id, f'm5/{action}/{operation_id}',
                  encode(ref), frozenset([subject]), frozenset([target] if target else []), frozenset([action]))
    return AssertionHost(store.root).issue_once(grant, action, operation_id)


def record_interpretation(store, actor, operation_id, requirements_ref):
    """Publish the Coordinator's interpretation after its immutable row has committed."""
    _require_actor(actor, 'coordinator')
    with store.connect() as db:
        record = ContentStore._read(db, requirements_ref)
    if (requirements_ref['type'] != 'CommissionRequirements' or record['owner_id'] != actor.id
            or record['task_id'] != actor.task_id):
        raise ActionRejected('COMMISSION_INTERPRETATION_VERSION_REQUIRED')
    subject = requirements_ref['id']
    ctx = _context(store, actor, 'coordinator', operation_id, subject, requirements_ref, 'record_convention')
    return assertions.record_convention(ctx, subject=subject,
        claim={'kind': 'convention', 'scope': 'commission_requirements', 'rule': encode(requirements_ref)})


def _question(rows):
    return next((r for r in reversed(rows) if r[0] == 'ask'), None)


def _live(status):
    return status['active'] and not status['challenged'] and not status['stale']


def ask_checkpoint(store, actor, operation_id, kind, issue_id, checkpoint):
    _require_actor(actor, 'coordinator')
    subject = _subject(kind, issue_id)
    ref = checkpoint['plan_ref' if kind == 'plan' else 'requirements_ref']
    if ref['type'] != ('CommissionPlan' if kind == 'plan' else 'CommissionRequirements'):
        raise ActionRejected('COMMISSION_CHECKPOINT_REF_MISMATCH')
    with store.connect() as db:
        ContentStore._read(db, ref)
    ctx = _context(store, actor, 'coordinator', operation_id, subject, ref, 'ask')
    return assertions.ask(ctx, subject=subject, claim={'kind': 'question', 'text': encode(checkpoint), 'affects': 'other'})


def checkpoint(storage, kind, issue_id):
    question = _question(_rows(storage, _subject(kind, issue_id)))
    if question:
        return json.loads(question[1]['claim']['text']) if _live(question[2]) else None
    reader = legacy_state.get_commission_checkpoint if kind == 'plan' else legacy_state.get_commission_requirements_checkpoint
    if isinstance(storage, (str, Path)):
        path = Path(storage) / 'state.db'
        if not path.is_file():
            return None
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
            return reader(db, issue_id)
    return reader(storage, issue_id)


def answer_checkpoint(store, owner, operation_id, kind, issue_id, result_ref):
    _require_actor(owner, 'owner')
    subject = _subject(kind, issue_id)
    question = _question(_rows(store, subject))
    if not question:
        raise ActionRejected('COMMISSION_NATIVE_CHECKPOINT_REQUIRED')
    data = json.loads(question[1]['claim']['text'])
    ref = data['plan_ref' if kind == 'plan' else 'requirements_ref']
    with store.connect() as db:
        result = ContentStore._read(db, result_ref)
    if kind == 'plan':
        matches = result_ref['type'] == 'CommissionDecision' and result['payload'].get('plan_ref') == ref
    else:
        matches = result_ref['type'] == 'CommissionRequirements' and result['previous_ref'] == ref
    if not matches or result['owner_id'] != owner.id or result['task_id'] != owner.task_id:
        raise ActionRejected('COMMISSION_CHECKPOINT_ANSWER_MISMATCH')
    target = question[1]['id']
    ctx = _context(store, owner, 'owner', operation_id, subject, ref, 'decide', target)
    return assertions.decide(ctx, subject=subject,
        claim={'kind': 'decision', 'effect': 'answer', 'target': target, 'reason': encode(result_ref)})


def _answer(rows, question):
    if question and _live(question[2]):
        return next((r for r in reversed(rows) if r[0] == 'decide' and _live(r[2])
                     and r[1]['claim']['effect'] == 'answer' and r[1]['claim']['target'] == question[1]['id']), None)


def checkpoint_answer(storage, kind, issue_id):
    rows = _rows(storage, _subject(kind, issue_id))
    answer = _answer(rows, _question(rows))
    return json.loads(answer[1]['claim']['reason']) if answer else None


def requirements_results(storage):
    """Versions selected by a live Coordinator interpretation or an exact owner answer."""
    rows = _rows(storage)
    results = set()
    questions = {body['id'] for action, body, status in rows if action == 'ask' and _live(status)
                 and body['subject'].startswith('commission-checkpoint/requirements/')}
    for action, body, status in rows:
        if not _live(status):
            continue
        claim = body['claim']
        if action == 'record_convention':
            ref = json.loads(claim['rule'])
        elif action == 'decide' and claim['target'] in questions:
            ref = json.loads(claim['reason'])
        else:
            continue
        results.add((ref['id'], ref['version']))
    return results


def copy_planning_evidence(source, output, records, *, plan, decision):
    """Carry the authenticated acts for the imported business versions; skip other issues."""
    directory = _directory(source)
    if directory is None or not (directory / 'assertions.sqlite3').is_file():
        return
    wanted = {encode(r['ref']) for r in records if r['ref']['type'] == 'CommissionRequirements'}

    def select(rows):
        selected = []
        questions = {}
        for action, body, status in rows:
            if action == 'ask':
                questions[body['id']] = (action, body, status)
            elif action == 'record_convention' and body['claim']['rule'] in wanted and _live(status):
                selected.append(body)
            elif action == 'decide' and _live(status):
                claim = body['claim']
                question = questions.get(claim['target'])
                if not question or not _live(question[2]):
                    continue
                checkpoint = json.loads(question[1]['claim']['text'])
                if ('plan_ref' in checkpoint and checkpoint['plan_ref'] == plan and json.loads(claim['reason']) == decision
                        or 'plan_ref' not in checkpoint and claim['reason'] in wanted):
                    selected.extend([question[1], body])
        return selected

    Commission(output).import_planning_actions(directory, select)
