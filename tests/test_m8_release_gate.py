"""Application release is unavailable until the approved 9a integration."""
from uuid import uuid4

import pytest

from report_agent import assertions
from report_agent.assertion_host import AssertionHost, Grant


@pytest.mark.parametrize('role', ['coordinator', 'owner'])
@pytest.mark.parametrize('entry', ['issue', 'issue_once', 'bind'])
def test_formal_release_attempt_is_refused_without_a_record(tmp_path, role, entry):
    host = AssertionHost(tmp_path)
    grant = Grant(str(uuid4()), role, 'task', 'attempt', 'plan', {'report'}, {'scope'}, {'release'})
    if entry == 'bind':
        host.authorize(grant)
        ctx = host.bind(grant, native_call_id='release-attempt', action='release')
    else:
        ctx = getattr(host, entry)(grant, 'release', 'release-attempt')
    # The refusal is at action time, including a context issued before the attempt.
    with pytest.raises(PermissionError, match='FORMAL_RELEASE_DEFERRED_TO_9A'):
        assertions.release(ctx, subject='report', claim={
            'kind': 'decision', 'effect': 'release', 'target': 'scope', 'reason': 'Try formal release'})
    assert host.recover_receipt(ctx.operation_id) is None
    assert not host.commission.produced_ids(actor=grant.principal, task='task', subject='report', kind='decision')
