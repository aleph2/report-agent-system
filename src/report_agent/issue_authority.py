"""Trusted human replies to actual runtime questions, separate from their case projection."""
import json
from uuid import NAMESPACE_URL, uuid5

from . import assertions, issue_state
from .assertion_host import AssertionHost, Grant
from .assertions.launch import Commission
from .content_store import Actor, ContentStore
from .errors import ActionRejected
from .operation_identity import bound_native_id
from .store import encode


def _context(store, issue_id, action, operation, target=None):
    role = 'owner' if action in {'decide', 'retract'} else 'coordinator'
    identity = 'operator' if role == 'owner' else 'content:coordinator'
    subject = 'runtime-issue/' + issue_id
    grant = Grant(str(uuid5(NAMESPACE_URL, identity)), role, subject, operation,
                  subject, frozenset([subject]), frozenset([target] if target else []), frozenset([action]))
    return AssertionHost(store.root).issue_once(grant, action, operation)


def record_answer(store, issue, message, resolved):
    """Caller has validated the operator reply; each committed step is independently redoable."""
    identity = issue['id']
    subject = 'runtime-issue/' + identity
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        ref = issue_state._save('IssueAnswer', db, identity, {'decision': message,
            'decision_origin': 'operator', 'resolved': resolved},
            actor=Actor('operator', 'operator', subject))
    ctx = _context(store, identity, 'ask', 'm6-question:' + identity)
    question = assertions.ask(ctx, subject=subject,
        claim={'kind': 'question', 'text': issue['description'], 'affects': 'other'})
    operation = 'm6-answer:' + identity + ':' + str(ref['version'])
    host = AssertionHost(store.root)
    ctx = _context(store, identity, 'decide', operation, question['id'])
    if host.recover_receipt(ctx.operation_id) is None:
        retract_operation = 'm6-retract:' + identity + ':' + str(ref['version'])
        receipt = host.recover_receipt(bound_native_id(ctx.binding['actor'], 'retract', retract_operation))
        if receipt:
            target = receipt['result']['claim']['target']
        else:
            active = [body for action, body, state in Commission.issue_actions(store.root)
                      if action == 'decide' and body['subject'] == subject and state['active']]
            if len(active) > 1:
                raise ActionRejected('ISSUE_MULTIPLE_ACTIVE_ANSWERS: ' + identity)
            target = active[0]['id'] if active else None
        if target:
            ctx = _context(store, identity, 'retract', retract_operation, target)
            assertions.retract(ctx, subject=subject, claim={'kind': 'act', 'effect': 'retract',
                'target': target, 'reason': 'Revised reply: ' + encode(ref)})
    ctx = _context(store, identity, 'decide', operation, question['id'])
    return assertions.decide(ctx, subject=subject, claim={'kind': 'decision', 'effect': 'answer',
        'target': question['id'], 'reason': encode(ref)})


def answers(storage):
    from .plan_authority import _directory
    directory = _directory(storage)
    if directory is None:
        return {}
    rows = Commission.issue_actions(directory)
    selected = {body['subject'].split('/', 1)[1]: None for action, body, _ in rows if action == 'ask'}
    questions = {body['id'] for action, body, state in rows if action == 'ask'
                 and state['active'] and not state['stale'] and not state['challenged']}
    for action, body, state in rows:
        if (action == 'decide' and state['active'] and not state['stale'] and not state['challenged']
                and body['claim']['target'] in questions):
            identity = body['subject'].split('/', 1)[1]
            if selected[identity] is not None:
                raise ActionRejected('ISSUE_MULTIPLE_ACTIVE_ANSWERS: ' + identity)
            selected[identity] = json.loads(body['claim']['reason'])
    if not selected:
        return {}
    if hasattr(storage, 'connect'):
        with storage.connect() as db:
            return {key: ContentStore._read(db, ref)['payload'] if ref else None for key, ref in selected.items()}
    return {key: ContentStore._read(storage, ref)['payload'] if ref else None for key, ref in selected.items()}
