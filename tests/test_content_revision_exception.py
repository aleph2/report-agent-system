import json
import pytest
from test_hierarchical_content import ws, seed
from report_agent.content_store import Actor
from report_agent.errors import ActionForbidden, ActionRejected
from report_agent.store import digest


def prepare(ws):
    cs, actor, refs, _, _ = seed(ws)
    ws.store.set('content_revision_limit', 1)
    payload = {**cs.read(refs['claim'])['payload'], 'body': {'text': 'First correction'}}
    v2 = cs.commit(actor, 'first', [{'client_key': 'n', 'type': 'ContentNode',
        'previous_ref': refs['claim'], 'payload': payload}])['result']['refs']['n']
    proposed = {**payload, 'body': {'text': 'Approved citation wording'}}
    grant = {'previous_ref': v2, 'owner_id': actor.id,
        'previous_payload_digest': cs.read(v2)['payload_digest'],
        'approved_payload_digest': digest(proposed),
        'authorization_id': 'verified-message', 'authorization_sha256': 'a' * 64}
    ws.store.set('content_revision_exceptions', [grant])
    obj = {'client_key': 'n', 'type': 'ContentNode', 'previous_ref': v2, 'payload': proposed}
    return cs, actor, refs, v2, grant, obj


def test_exact_exception_once_and_idempotent_receipt(ws):
    cs, actor, _, v2, _, obj = prepare(ws)
    result = cs.commit(actor, 'exception', [obj])
    v3 = result['result']['refs']['n']
    assert v3 == {**v2, 'version': 3}
    assert cs.commit(actor, 'exception', [obj]) == result
    assert ws.store.get('content_revision_limit') == 1
    with pytest.raises(ActionRejected, match='CONTENT_REVISION_LIMIT_REACHED'):
        cs.commit(actor, 'later', [{**obj, 'previous_ref': v3}])
    with ws.store.connect() as db:
        rows = db.execute("SELECT data FROM events WHERE kind='content_revision_exception_used'").fetchall()
    assert len(rows) == 1 and json.loads(rows[0][0])['resulting_ref'] == v3


@pytest.mark.parametrize('field,value', [
    ('previous_ref', {'type': 'ContentNode', 'id': 'different', 'version': 2}),
    ('owner_id', 'another-owner'), ('previous_payload_digest', 'wrong'),
    ('approved_payload_digest', 'wrong'), ('authorization_id', ''),
    ('authorization_sha256', '')])
def test_grant_must_match_every_constraint(ws, field, value):
    cs, actor, _, _, grant, obj = prepare(ws)
    ws.store.set('content_revision_exceptions', [{**grant, field: value}])
    with pytest.raises(ActionRejected, match='CONTENT_REVISION_LIMIT_REACHED'):
        cs.commit(actor, 'wrong-grant', [obj])


def test_payload_change_and_other_owner_remain_rejected(ws):
    cs, actor, _, _, _, obj = prepare(ws)
    with pytest.raises(ActionRejected, match='CONTENT_REVISION_LIMIT_REACHED'):
        cs.commit(actor, 'changed', [{**obj, 'payload': {**obj['payload'], 'body': {'text': 'Different'}}}])
    with pytest.raises(ActionForbidden):
        cs.commit(Actor('other', 'writer', 'other-task'), 'other', [obj])


def test_failed_batch_rolls_back_exception_and_audit(ws):
    cs, actor, refs, v2, _, obj = prepare(ws)
    bad = {'client_key': 'bad', 'type': 'Evidence', 'payload': {'source_refs': [], 'locator': 'x', 'excerpt': 'x'}}
    with pytest.raises(ActionRejected):
        cs.commit(actor, 'atomic-bad', [obj, bad])
    with ws.store.connect() as db:
        assert db.execute("SELECT version FROM content_heads WHERE type='ContentNode' AND id=?", (v2['id'],)).fetchone()[0] == 2
        assert not db.execute("SELECT data FROM events WHERE kind='content_revision_exception_used'").fetchall()
    assert cs.commit(actor, 'after-contained-failure', [obj])['result']['refs']['n']['version'] == 3
