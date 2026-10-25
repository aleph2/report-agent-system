"""Invalid review dependencies identify the exact ref without relaxing isolation."""
import json

import pytest

from test_hierarchical_content import ws, seed, submission, review_item
from report_agent.errors import ActionRejected
from report_agent.hierarchical_tools import actor_for


def test_previous_review_dependency_is_identified_and_does_not_persist(ws):
    cs, actor, refs, snapshot, _ = seed(ws)
    reviewer = actor_for('reviewer')
    receipt = cs.read_context(reviewer, snapshot)['receipt_id']
    data = submission(snapshot, refs, review_item(snapshot, refs['k'], receipt))
    prior = cs.submit_review(reviewer, 'first', data, {})['result']['review_ref']
    before = cs.list_objects('ReviewRecord')
    data['dependency_refs'].append(prior)
    with pytest.raises(ActionRejected, match='REVIEW_VERSION_OUTSIDE_SNAPSHOT') as failure:
        cs.submit_review(reviewer, 'invalid-dependency', data, {})
    detail = json.loads(str(failure.value).split(': ', 1)[1])
    assert detail['received'] == prior
    assert detail['snapshot_ref'] == snapshot
    assert cs.list_objects('ReviewRecord') == before
    assert cs.read(snapshot)['ref'] == snapshot
