"""Limits apply at native business commits, including flat text tools."""
import pytest
from test_hierarchical_content import ws, seed
from report_agent.errors import ActionRejected


def test_one_content_revision_is_cumulative_and_failed_batch_is_atomic(ws):
    cs, actor, refs, snapshot, _ = seed(ws)
    ws.store.set('content_revision_limit', 1)
    def revision(ref, text):
        return {'client_key':'claim', 'type':'ContentNode', 'previous_ref':ref,
            'payload':{**cs.read(ref)['payload'], 'body':{'text':text}}}
    v2 = cs.commit(actor, 'allowed', [revision(refs['claim'], 'Revised')])['result']['refs']['claim']
    assert v2['version'] == 2
    with pytest.raises(ActionRejected, match='CONTENT_REVISION_LIMIT_REACHED'):
        cs.commit(actor, 'exhausted', [revision(v2, 'Second revision')])
    assert cs.read(v2)['payload']['body']['text'] == 'Revised'
    # Idempotent recovery does not consume another revision.
    assert cs.commit(actor, 'allowed', [revision(refs['claim'], 'Revised')])['result']['refs']['claim'] == v2


@pytest.mark.parametrize('limit', [-1, True, '1'])
def test_invalid_content_revision_limit_does_not_write(ws, limit):
    cs, actor, refs, snapshot, _ = seed(ws)
    ws.store.set('content_revision_limit', limit)
    with pytest.raises(ActionRejected, match='INVALID_CONTENT_REVISION_LIMIT'):
        cs.commit(actor, 'bad-limit', [{'client_key':'claim','type':'ContentNode',
            'previous_ref':refs['claim'], 'payload':cs.read(refs['claim'])['payload']}])
