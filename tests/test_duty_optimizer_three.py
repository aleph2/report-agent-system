"""UNEXECUTED DRAFT: exact three-feedback accounting and one omitted disposition.

Target after explicit release: tests/test_duty_optimizer_three.py. The paired
control removes only the F2 disposition call; F1/F3, read results and final text
remain identical except isolated identities. This does not prescribe live strategy.
"""
import json
import os
from pathlib import Path

import httpx
import pytest
from langchain_core.messages import AIMessage

from duty_probe_agent_decisions import dump
from duty_probe_optimizer_outcome import CONDITIONS, MISSING, PREFERENCE, STRATEGY, SUSPICION
from duty_probe_optimizer_three import FINAL, PRESERVE_CORRECTION, TECHNICAL_UNKNOWN, capture_optimizer_three
from report_agent.store import digest
from test_agent_duty_trace_cases import result_value, tool_reply
from test_deep_runtime import Driver
from test_duty_optimizer_single import no_external_network
from test_task_supervision import ws


def three_optimizer_script(omit_f2, held):
    def unused_preparation(messages):
        raise AssertionError('The twelve native read calls must come from the explicit preparation hook')

    def after_reads(messages):
        pages, feedback = {}, {}
        for label in ('f1', 'f2', 'f3'):
            feedback[label] = {}
            for field in ('correction', 'before', 'evidence'):
                raw = tool_reply(messages, label + '-' + field)
                page = result_value(raw)
                assert raw.status == 'success' and page['next_offset'] is None
                assert page['offset'] == 0 and len(page['text']) == page['total_chars']
                value = page['text'] if field == 'correction' else json.loads(page['text'])
                assert page['digest'] == digest(value)
                feedback[label][field] = value
                feedback[label].setdefault('id', page['feedback_id'])
                assert feedback[label]['id'] == page['feedback_id']
                pages[label + '-' + field] = page
        assert len({f['id'] for f in feedback.values()}) == 3
        assert feedback['f1']['correction'] == PREFERENCE
        assert feedback['f2']['correction'] == SUSPICION
        assert feedback['f2']['before'] == {'report_available': False}
        assert feedback['f2']['evidence'] == [MISSING]
        assert feedback['f3']['correction'] == PRESERVE_CORRECTION
        assert feedback['f3']['before']['body']['text'] == TECHNICAL_UNKNOWN
        assert feedback['f3']['before']['qualifiers']['technical_uncertainty'] == TECHNICAL_UNKNOWN
        sources = {}
        for label, expected in (('f1', PREFERENCE), ('f3', TECHNICAL_UNKNOWN)):
            raw = tool_reply(messages, label + '-source')
            page = result_value(raw)
            assert raw.status == 'success' and page['next_offset'] is None
            assert page['offset'] == 0 and len(page['text']) == page['total_chars']
            record = json.loads(page['text'])
            assert record['ref'] == page['ref'] == feedback[label]['evidence'][0]['source_ref']
            assert record['payload']['content'] == expected and page['digest'] == digest(record)
            sources[label] = page
        raw = tool_reply(messages, 'f1-existing-candidate')
        page = result_value(raw)
        assert raw.status == 'success' and page['next_offset'] is None
        assert page['offset'] == 0 and len(page['text']) == page['total_chars']
        candidate = json.loads(page['text'])
        assert (candidate['id'], candidate['version']) == (page['id'], page['version'])
        assert candidate['version'] == 1 and candidate['feedback_ids'] == [feedback['f1']['id']]
        assert candidate['strategy'] == STRATEGY and candidate['conditions'] == CONDITIONS
        assert not candidate['active'] and page['digest'] == digest(candidate)
        held.update(pages=pages, feedback=feedback, sources=sources, candidate_page=page, candidate=candidate)
        f1 = {'name': 'record_feedback_disposition', 'id': 'dispose-f1', 'type': 'tool_call', 'args': {
            'feedback_id': feedback['f1']['id'], 'outcome': 'candidate',
            'experience_id': candidate['id'], 'experience_version': candidate['version'],
            'rationale': 'The exact existing inactive candidate is linked to this feedback. No publication, report correction or quality approval is claimed.'}}
        f2 = {'name': 'record_feedback_disposition', 'id': 'dispose-f2', 'type': 'tool_call', 'args': {
            'feedback_id': feedback['f2']['id'], 'outcome': 'insufficient_evidence',
            'rationale': 'No report version or locator establishes a missing title. The absence allegation remains unverified.'}}
        f3 = {'name': 'record_feedback_disposition', 'id': 'dispose-f3', 'type': 'tool_call', 'args': {
            'feedback_id': feedback['f3']['id'], 'outcome': 'no_change',
            'rationale': 'This separate Site T paragraph already preserves its source technical uncertainty. Retain the unknown groundwater level; no report change or new reusable candidate is needed for this control.'}}
        held['intended_disposition_calls'] = [f1, f2, f3]
        calls = [f1, f3] if omit_f2 else [f1, f2, f3]
        held['actual_disposition_calls'] = calls
        return AIMessage(content='', tool_calls=calls)

    def finish(messages):
        records = {}
        for label in ('f1', 'f3') if omit_f2 else ('f1', 'f2', 'f3'):
            raw = tool_reply(messages, 'dispose-' + label)
            value = result_value(raw)
            assert raw.status == 'success' and value['feedback_id'] == held['feedback'][label]['id']
            assert value['quality_verified'] is False
            records[label] = value
        assert records['f1']['candidate'] == {'id': held['candidate']['id'], 'version': 1}
        assert records['f3']['outcome'] == 'no_change'
        if not omit_f2:
            assert records['f2']['outcome'] == 'insufficient_evidence'
        held['public_dispositions'] = records
        held['final_text'] = FINAL
        return AIMessage(content=FINAL)

    return [unused_preparation, after_reads, finish]


@pytest.mark.parametrize('omit_f2', [False, True], ids=['all-three-accounted', 'only-f2-omitted'])
async def test_three_feedback_existing_candidate_and_unaccounted_control(ws, request, monkeypatch, omit_f2):
    def denied(*args, **kwargs):
        pytest.fail('No HTTP is allowed in the three-feedback native fake calibration')
    monkeypatch.setattr(httpx.AsyncClient, 'send', denied)
    monkeypatch.setattr(httpx.Client, 'send', denied)
    held = {}
    driver = Driver(optimizer=three_optimizer_script(omit_f2, held))
    folder = Path(os.environ.get('REPORT_OPTIMIZER_THREE_OUT', str(ws.store.root / 'captures'))) / request.node.name
    capture = await capture_optimizer_three(ws, folder, driver)
    dump(folder / 'independent-observations.json', held)
    request.node.user_properties.append(('optimizer_three_capture', str(folder)))
    assessment, fixture = capture['assessment'], capture['fixture']
    assert fixture['targets']['f1-row'] != fixture['targets']['f3-block']
    assert fixture['feedback']['f1']['target'] == fixture['targets']['f1-row']
    assert fixture['feedback']['f3']['target'] == fixture['targets']['f3-block']
    assert fixture['feedback']['f2']['target'] == {}
    expected_ids = [fixture['feedback'][label]['id'] for label in ('f1', 'f2', 'f3')]
    assert [r['feedback_id'] for r in fixture['queue_before_claim']] == expected_ids
    assert all(r['status'] == 'queued' and r['claim_id'] is None for r in fixture['queue_before_claim'])
    assert len(fixture['feedback_originals']) == 3
    assert len(fixture['candidate_originals']) == len(assessment['candidates']) == 1
    assert assessment['candidates'][0] == fixture['existing_candidate'] == held['candidate']
    assert not assessment['new_candidates']
    assert assessment['candidate_originals_unchanged'] and assessment['feedback_originals_unchanged']
    assert assessment['business_originals_unchanged'] and assessment['source_originals_unchanged']
    assert assessment['active_assignment_after_worker'] is None
    assert assessment['all_candidates_inactive'] and not assessment['active_library']
    assert assessment['job']['quality_verified'] is False
    assert assessment['semantic_status'] == 'not_semantically_assessed'
    assert not assessment['unexpected_feedback_ids']
    assert assessment['candidate_links'] == [{'feedback_id': expected_ids[0],
        'candidate': {'id': held['candidate']['id'], 'version': 1}, 'valid': True}]
    for label, feedback in fixture['feedback'].items():
        assert held['feedback'][label]['id'] == feedback['id']
        for field in ('correction', 'before', 'evidence'):
            page = held['pages'][label + '-' + field]
            assert (page['text'] if field == 'correction' else json.loads(page['text'])) == feedback[field]
            assert page['digest'] == digest(feedback[field])
    for label in ('f1', 'f3'):
        assert json.loads(held['sources'][label]['text']) == fixture['source_originals'][label]
    assert all(d['quality_verified'] is False for d in assessment['dispositions'].values())
    assert assessment['dispositions'][expected_ids[0]] == held['public_dispositions']['f1']
    assert assessment['dispositions'][expected_ids[2]] == held['public_dispositions']['f3']
    phases = capture['preparation_phases']
    assert phases[0]['phase'] == 'explicit_fake_read_setup'
    assert phases[0]['assignment']['feedback_ids'] == expected_ids
    calls = phases[0]['action']['tool_calls']
    assert len(calls) == 12
    assert sum(c['name'] == 'read_learning_feedback' for c in calls) == 9
    assert sum(c['name'] == 'read_learning_evidence' for c in calls) == 2
    assert sum(c['name'] == 'read_experience_candidates' for c in calls) == 1
    assert {m['tool_call_id'] for m in phases[1]['native_tool_returns']} == {c['id'] for c in calls}
    assert all(m['status'] == 'success' for m in phases[1]['native_tool_returns'])
    assert all(p['phase'] == 'unchanged_consumer_handler' for p in phases[1:])
    assert len(driver.calls) == len(capture['native_model_calls']) == 2
    assert [c[0:2] for c in driver.calls] == [('optimizer', 1), ('optimizer', 2)]
    assert all(c['boundary'] == 'native_optimizer_decision' for c in capture['native_model_calls'])
    actual = phases[1]['response'][0]['data']['tool_calls']
    assert actual == held['actual_disposition_calls']
    intended = held['intended_disposition_calls']
    assert actual == ([intended[0], intended[2]] if omit_f2 else intended)
    assert phases[-1]['response'][-1]['data']['content'] == held['final_text'] == FINAL
    assert not phases[-1]['response'][-1]['data']['tool_calls']
    names = {s['name'] for s in driver.bindings['optimizer'][-1]}
    assert {'read_learning_feedback', 'read_learning_evidence', 'read_experience_candidates',
            'propose_experience', 'record_feedback_disposition', 'analyze_learning_material'} <= names
    assert not {'task', 'release', 'commit_objects'} & names
    assert capture['host_existing_candidate_preparation']
    assert not capture['host_completion_actions'] and not capture['host_candidate_publication']
    assert len(assessment['queue']) == 3
    assert {r['claim_id'] for r in assessment['queue']} == {phases[0]['assignment']['id']}
    if omit_f2:
        assert capture['raised_error'] == {'type': 'ActionRejected', 'message': 'LEARNING_FEEDBACK_UNACCOUNTED'}
        assert capture['runtime_result'] is None and assessment['job']['state'] == 'failed'
        assert assessment['missing_feedback_ids'] == [expected_ids[1]]
        assert set(assessment['dispositions']) == {expected_ids[0], expected_ids[2]}
        assert all(r['status'] == 'failed' and r['error_type'] == 'ActionRejected' for r in assessment['queue'])
    else:
        assert capture['raised_error'] is None and capture['runtime_result']['state'] == 'completed'
        assert capture['runtime_result']['claim'] == phases[0]['assignment']
        assert assessment['job']['state'] == 'completed' and assessment['job']['candidates'] == []
        assert not assessment['missing_feedback_ids'] and set(assessment['dispositions']) == set(expected_ids)
        assert assessment['dispositions'][expected_ids[1]] == held['public_dispositions']['f2']
        assert all(r['status'] == 'completed' and r['error_type'] is None for r in assessment['queue'])
    dump(folder / 'finite-oracle.json', {'scripted_control': 'only-f2-omitted' if omit_f2 else 'all-three-accounted',
        'candidate_preexisted_job': True, 'new_candidates': 0,
        'native_consumer_calls': len(driver.calls), 'paid_calls': 0,
        'same_final_text': FINAL, 'only_control_change': 'Omit the F2 disposition call.',
        'missing_feedback_ids': assessment['missing_feedback_ids'],
        'limits': 'Finite native accounting calibration; not autonomous strategy, semantic quality, report correction or publication.'})
