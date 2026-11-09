"""Trusted human replies to actual runtime questions, separate from their case projection."""
import json
from uuid import NAMESPACE_URL, uuid5

from . import assertions, issue_state
from .assertion_host import AssertionHost, Grant
from .assertions.launch import Commission
from .content_store import Actor, ContentStore
from .store import encode


def _context(store, issue_id, action, operation, target=None):
    role = 'owner' if action == 'decide' else 'coordinator'
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
    # A later revised reply revisits the actual question; S2 never answers a closed question twice.
    ctx = _context(store, identity, 'ask', 'm6-question:' + identity + ':' + str(ref['version']))
    question = assertions.ask(ctx, subject=subject,
        claim={'kind': 'question', 'text': issue['description'], 'affects': 'other'})
    operation = 'm6-answer:' + identity + ':' + str(ref['version'])
    ctx = _context(store, identity, 'decide', operation, question['id'])
    return assertions.decide(ctx, subject=subject, claim={'kind': 'decision', 'effect': 'answer',
        'target': question['id'], 'reason': encode(ref)})


def answers(storage):
    from .plan_authority import _directory
    directory = _directory(storage)
    if directory is None:
        return {}
    selected = {}
    for action, body, state in Commission.issue_actions(directory):
        if action == 'decide' and state['active'] and not state['stale'] and not state['challenged']:
            selected[body['subject'].split('/', 1)[1]] = json.loads(body['claim']['reason'])
    if not selected:
        return {}
    if hasattr(storage, 'connect'):
        with storage.connect() as db:
            return {key: ContentStore._read(db, ref)['payload'] for key, ref in selected.items()}
    return {key: ContentStore._read(storage, ref)['payload'] for key, ref in selected.items()}
