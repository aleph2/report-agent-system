"""Fake native controls for P05/P10 execution and independent saved-state oracle."""
import json
import os
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from report_agent.content_store import ContentStore
from duty_probe_agent_decisions import (CASES, EVIDENCE_A, CONCLUSION_B, UNREVIEWED, capture_agent_decision)
from test_agent_duty_trace_cases import action, result_value, tool_reply
from test_deep_runtime import Driver
from test_task_supervision import ws, offline


def fake_factory(ws, case, variant, held):
    cs = ContentStore(ws.store)
    def first(messages):
        fixture_nodes = cs.list_objects('ContentNode')
        if case == CASES[0]:
            by_text = {o['payload']['body'].get('text'): o['ref'] for o in fixture_nodes}
            held['root'], held['a'], held['b'] = (by_text['Synthetic dependency report'], by_text[EVIDENCE_A], by_text[CONCLUSION_B])
            return AIMessage(content='', tool_calls=[
                {'name': 'read_context', 'args': {'target_ref': held[k]}, 'id': 'read-' + k, 'type': 'tool_call'} for k in ('a', 'b')])
        exports = cs.list_objects('ExportArtifact')
        words = [o for o in exports if o['payload']['file_ref'].endswith('.docx')]
        target = words[-1] if variant == 'wrong' else words[1]
        snap = target['payload']['snapshot_ref']
        workbook = next(o for o in exports if o['payload'].get('export_config', {}).get('report_export_ref') == target['ref'])
        held['pair'] = {'snapshot_ref': snap, 'export_ref': target['ref'], 'workbook_export_ref': workbook['ref']}
        return action('read_content_export', 'read-draft', export_ref=target['ref'])

    def decide(messages):
        if variant == 'incomplete':
            return AIMessage(content='Inspection finished without saving the requested outcome; work remains incomplete.')
        if case == CASES[0]:
            assert EVIDENCE_A in json.dumps(result_value(tool_reply(messages, 'read-a')), ensure_ascii=False)
            assert CONCLUSION_B in json.dumps(result_value(tool_reply(messages, 'read-b')), ensure_ascii=False)
            ordered = ['a', 'b'] if variant == 'wrong' else ['b', 'a']
            return action('commit_objects', 'save-relations', operation_id='fake-save-relations', objects=[
                {'client_key': 'edge-' + key, 'type': 'Relation', 'payload': {
                    'subject_ref': held['root'], 'object_ref': held[key], 'predicate': 'contains',
                    'position': index, 'provenance_kind': 'adopted_during_generation'}} for index, key in enumerate(ordered)])
        assert result_value(tool_reply(messages, 'read-draft'))['ok']
        return action('select_content_delivery', 'select-draft', operation_id='fake-select-draft',
                      **held['pair'], ending_reason='preserve_unresolved')

    def save_or_record(messages):
        if case == CASES[0]:
            value = result_value(tool_reply(messages, 'save-relations'))
            assert value['ok'], value
            allowed = {'Requirement', 'SourceArtifact', 'Criterion', 'Evidence', 'ContentNode', 'Relation'}
            return action('freeze_snapshot', 'freeze-draft', operation_id='fake-freeze-draft',
                root_ref=held['root'], refs=[o['ref'] for o in cs.list_objects() if o['ref']['type'] in allowed])
        assert result_value(tool_reply(messages, 'select-draft'))['ok']
        return action('record_execution_decision', 'preserve-draft', operation_id='fake-preserve-draft',
            decision='terminate', reason='The chosen draft is retained for later independent review.',
            evidence=['Actual paired exports were read and selected.'], unresolved=[UNREVIEWED])

    def finish(messages):
        call_id = 'freeze-draft' if case == CASES[0] else 'preserve-draft'
        value = result_value(tool_reply(messages, call_id))
        assert value['ok'], value
        held['last_tool_result'] = value
        return AIMessage(content='Saved synthetic draft. ' + UNREVIEWED)

    role = 'writer' if case == CASES[0] else 'coordinator'
    driver = Driver(**{role: [first, decide] if variant == 'incomplete' else [first, decide, save_or_record, finish]})
    return driver


@pytest.mark.parametrize('case', CASES)
@pytest.mark.parametrize('variant', ['correct', 'wrong', 'incomplete'])
async def test_native_agent_decision_saved_state_has_independent_controls(ws, request, case, variant):
    held = {}
    driver = fake_factory(ws, case, variant, held)
    target = Path(os.environ.get('REPORT_AGENT_DECISIONS_OUT', str(ws.store.root / 'captures'))) / (case + '-' + variant)
    result = await capture_agent_decision(ws, case, target, driver)
    request.node.user_properties.append(('agent_decision_evidence', json.dumps({
        'case': case, 'variant': variant, 'capture_dir': str(target), 'oracle': result['oracle'],
        'paid_calls': 0, 'native_fake_actions': True, 'semantic_acceptance': False}, ensure_ascii=False)))
    assert result['raised_error'] is None, result
    assert result['runtime_result']['last_error'] is None, result['runtime_result']
    assert result['native_model_calls'], 'Actual model callback input must be retained.'
    expected = {'correct': 'finite_state_satisfied', 'wrong': 'behavior_not_met', 'incomplete': 'incomplete'}[variant]
    assert result['oracle']['status'] == expected, result['oracle']
    assert result['oracle']['original_records_preserved']
    assert result['oracle']['original_files_preserved']
    assert result['oracle']['review_state_unchanged']
    if variant != 'incomplete':
        assert held['last_tool_result']['ok'], 'The actual tool must execute before the saved-state oracle.'
    if case == CASES[0] and variant == 'wrong':
        assert result['oracle']['snapshot_audits'][0]['both_original_refs_reachable']
        assert result['oracle']['snapshot_audits'][0]['original_dependency_text_preserved']
        assert result['oracle']['snapshot_audits'][0]['b_before_a'] is False
    if case == CASES[1] and variant == 'wrong':
        assert result['oracle']['selected_delivery'] is not None
        assert result['oracle']['exact_current_b_pair'] is False
