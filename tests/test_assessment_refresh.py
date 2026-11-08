"""The trusted host refreshes a selected draft only after its immutable inputs are reviewed."""
from uuid import NAMESPACE_URL, uuid5

import pytest

from report_agent import assertions
from report_agent.assertion_host import AssertionHost, Grant
from report_agent.errors import ActionRejected
from report_agent.store import digest
from report_agent.writer_assessment import read_indicator_step, save_indicator_outcome
from test_fake03_qualitative_steps import mini
from test_m1_g3_integration import method_commission
from test_writer_indicator_outcomes import ranked, evidence


def act(host, plan, subject, target, effect):
    grant = Grant(str(uuid5(NAMESPACE_URL, 'test/review-owner')), 'owner', 'review', effect + target,
                  digest(plan), frozenset([subject]), frozenset([target]), frozenset([effect]))
    ctx = host.issue_once(grant, effect, effect + target)
    getattr(assertions, effect)(ctx, subject=subject,
        claim=dict(kind='act', target=target, effect=effect, reason='Reviewed project evidence'))


@pytest.mark.parametrize('method_commission', ['with-owner-ranks'], indirect=True)
def test_reviewed_refresh_is_explicit_idempotent_and_preserves_draft(ranked, capsys):
    import json
    from report_agent.assessment_refresh import main, refresh_selected_assessment
    from report_agent.assessment_projection import assessment_receipt, selected_assessment
    f = ranked
    host = AssertionHost(f.cs.store.root)
    for indicator in 'ABCD':
        step = read_indicator_step(f.cs, f.actor)
        out = save_indicator_outcome(f.cs, f.actor, 'save-' + indicator, indicator, evidence(f, step))['result']
    ref = out['assessment_ref']
    archived = f.cs.read(ref)
    claim = host.recover_receipt(archived['payload']['derive_operation_id'])['result']['claim']
    with pytest.raises(ActionRejected):
        refresh_selected_assessment(f.cs, 'S1')
    for target in claim['inputs']:
        act(host, f.plan_ref, 'S1', target, 'confirm')
    assert read_indicator_step(f.cs, f.actor)['assessment_ref'] == ref
    assert main([str(f.cs.store.root), 'S1']) == 0
    refreshed = json.loads(capsys.readouterr().out)
    assert refreshed['previous_ref'] == ref and refreshed['status'] == 'scored'
    with f.cs.store.connect() as db:
        new = selected_assessment(db, f.plan_ref, 'S1')
        assert new == refreshed['assessment_ref'] and new != ref
        assert assessment_receipt(db, ref)['derivation_status'] == 'pending_review'
        assert assessment_receipt(db, new)['derivation_status'] == 'scored'
    assert f.cs.read(ref) == archived
    assert refresh_selected_assessment(f.cs, 'S1')['assessment_ref'] == new
    assert len(f.cs.list_objects('Assessment')) == 2

def test_committed_projection_recovers_after_a_packet_source_is_retracted(mini, monkeypatch):
    from report_agent import risk_scoring
    from report_agent.content_store import ContentStore
    from report_agent.errors import LocalStorageBusy
    from report_agent.writer_fact_packet import _writer_key
    from report_agent.writer_assignments import bound_assignment
    from report_agent.writer_runtime import writer_session
    from report_agent.writer_judgments import read_progress
    from support.fake03 import install
    ws, binding, _ = mini
    install(ws, binding.plan_ref)
    cs = ContentStore(ws.store)
    host = AssertionHost(ws.store.root)
    with writer_session(ws, '坡段 A', None, assessment_only=True, indicator_steps=True, section_id='3') as writer:
        for i in range(8):
            step = read_indicator_step(cs, writer.actor)
            indicator = step['indicator_id']
            outcome = dict(kind='gap', missing='Missing site observation', question='Which site observation?')
            if i == 0:
                outcome['fact_ids'] = ['F03-A-WEATHERING']
            if i < 7:
                save_indicator_outcome(cs, writer.actor, 'step-' + indicator, indicator, outcome)
        with monkeypatch.context() as patch:
            def fail_projection(*args, **kwargs):
                raise ActionRejected('projection temporarily unavailable')
            patch.setattr(risk_scoring, 'record_assessment_projection', fail_projection)
            with pytest.raises(LocalStorageBusy):
                save_indicator_outcome(cs, writer.actor, 'step-' + indicator, indicator, outcome)
        draft = read_progress(cs.store, step['assignment_digest'])
        target = draft['rows']['X21']['grounds'][0]['assertion_id']
        act(host, binding.plan_ref, 'A', target, 'retract')
        with cs.store.connect() as db:
            scope = bound_assignment(cs, db, writer.actor)
        grant = host.lookup(_writer_key(writer.actor, scope))
        host.revoke(grant)
        with pytest.raises(ActionRejected, match='PACKET_REQUIRED'):
            read_indicator_step(cs, writer.actor)
        host.authorize(grant)
        final = read_indicator_step(cs, writer.actor)
        assert final['complete'] and final['assessment_status'] == 'stale'
        assert cs.receipt(writer.actor, 'step-' + indicator)['state'] == 'known_success'
        assert len(cs.list_objects('Assessment')) == 1

@pytest.mark.parametrize('method_commission', ['with-owner-ranks'], indirect=True)
def test_committed_review_refresh_replays_as_stale_after_a_withdrawal(ranked, monkeypatch):
    from report_agent import risk_scoring
    from report_agent.assessment_refresh import refresh_selected_assessment
    from report_agent.assessment_projection import selected_assessment
    f = ranked
    host = AssertionHost(f.cs.store.root)
    for indicator in 'ABCD':
        step = read_indicator_step(f.cs, f.actor)
        out = save_indicator_outcome(f.cs, f.actor, 'draft-' + indicator, indicator, evidence(f, step))['result']
    ref = out['assessment_ref']
    payload = f.cs.read(ref)['payload']
    original = host.recover_receipt(payload['derive_operation_id'])['result']
    for key in original['claim']['inputs']:
        act(host, f.plan_ref, 'S1', key, 'confirm')
    with monkeypatch.context() as patch:
        def crash(*args, **kwargs):
            raise RuntimeError('lost task projection')
        patch.setattr(risk_scoring, 'record_assessment_projection', crash)
        with pytest.raises(RuntimeError, match='lost task projection'):
            refresh_selected_assessment(f.cs, 'S1')
    with f.cs.store.connect() as db:
        assert selected_assessment(db, f.plan_ref, 'S1') == ref
    act(host, f.plan_ref, 'S1', original['claim']['inputs'][0], 'retract')
    recovered = refresh_selected_assessment(f.cs, 'S1')
    assert recovered['previous_ref'] == ref and recovered['status'] == 'stale'
    with pytest.raises(ActionRejected, match='INELIGIBLE'):
        refresh_selected_assessment(f.cs, 'S1')
    assert len(f.cs.list_objects('Assessment')) == 2
