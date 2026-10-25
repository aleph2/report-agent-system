"""Actual source-version selection and omitted-handoff controls, no provider calls."""
from copy import deepcopy
import json
import os
from pathlib import Path

from langchain_core.messages import AIMessage, messages_from_dict
import pytest

from duty_probe_agent_decisions import dump
from duty_probe_reviewer_source_investigation import (
    CLAIM, CURRENT_RULE, LIMIT, OLD_RULE, capture_reviewer_source_investigation)
from report_agent.content_store import ContentStore
from report_agent.store import digest
from test_agent_duty_trace_cases import action, result_value, tool_reply
from test_bounded_review import Model
from test_deep_runtime import Driver
from test_task_supervision import ws, offline


class CheckerCalibration(Model):
    def __init__(self):
        super().__init__()

    async def ainvoke(self, messages):
        self.calls.append(deepcopy(messages))
        packet = json.loads(messages[-1][1])
        claim_index = next(i for i, e in enumerate(packet['evidence'])
                           if e['kind'] == 'saved_object' and e['object']['payload']['body']['text'] == CLAIM)
        sources = [(i, e) for i, e in enumerate(packet['evidence']) if e['kind'] == 'source_blocks']
        observations = [{'evidence_index': claim_index, 'locator': 'original claim', 'observation': CLAIM}]
        if sources:
            index, entry = sources[0]
            assert len(sources) == 1 and entry['selection'] == {'source_id': 's', 'offset': 0, 'limit': 1}
            assert entry['selection_units'] == 'zero-based text blocks'
            assert [b['text'] for b in entry['observation']['blocks']] == [CURRENT_RULE]
            observations.append({'evidence_index': index, 'locator': 'current synthetic source block 0',
                                 'observation': CURRENT_RULE})
            item = {'execution_state': 'completed', 'verdict': 'not_satisfied',
                    'checked_requirement_indexes': [0],
                    'check_results': [{'requirement_index': 0, 'execution_state': 'completed',
                                      'result': 'Under the synthetic adopted class, 70 lies outside 75 to 100.',
                                      'observation_indexes': [0, 1], 'remaining': ''}],
                    'coverage': {'checked': ['Original claim compared with current selected rule.'],
                                 'unchecked': [], 'blocked': [], 'basis': 'Exact supplied original bodies.'},
                    'reason': 'Current synthetic rule contradicts the adopted value; actual site class remains unestablished.'}
        else:
            assert CURRENT_RULE not in json.dumps(packet['evidence'], ensure_ascii=False)
            item = {'execution_state': 'blocked', 'verdict': None, 'checked_requirement_indexes': [],
                    'check_results': [{'requirement_index': 0, 'execution_state': 'blocked',
                                      'result': 'Current original rule text was not selected into this checker input.',
                                      'observation_indexes': [0],
                                      'remaining': 'Select the eligible current source; no assertion that the project lacks it.'}],
                    'coverage': {'checked': [], 'unchecked': ['Current-rule comparison'],
                                 'blocked': ['Selected current original text missing from this packet.'],
                                 'basis': 'The supplied target alone cannot establish the current rule.'},
                    'reason': 'Input selection is incomplete; project source absence is not established.'}
        item.update(scope_id='current-rule-comparison', observations=observations, findings=[])
        return AIMessage(content=json.dumps({'items': [item]}, ensure_ascii=False))


def investigation_script(folder, selected, held):
    def choose(messages):
        turn = held.get('turn', 0)
        held['turn'] = turn + 1
        fixture = json.loads((Path(folder) / 'fixture.json').read_text(encoding='utf-8'))
        if turn == 0:
            held['first_messages'] = [m.model_dump() for m in messages]
            return AIMessage(content='', tool_calls=[
                {'name': 'read_context', 'type': 'tool_call', 'id': 'investigation-claim',
                 'args': {'target_ref': fixture['refs']['claim']}},
                {'name': 'read_context', 'type': 'tool_call', 'id': 'investigation-structure',
                 'args': {'target_ref': fixture['snapshot_ref']}},
                {'name': 'read_source_page', 'type': 'tool_call', 'id': 'investigation-current-original',
                 'args': {'source_id': 's', 'offset': 0, 'limit': 1}}])
        if turn == 1:
            held['initial_returns'] = {name: tool_reply(messages, name).model_dump() for name in
                ['investigation-claim', 'investigation-structure', 'investigation-current-original']}
            return action('capture_review_sources', 'investigation-capture',
                          operation_id='investigation-capture', source_ids=['s'])
        if turn == 2:
            held['capture_return'] = tool_reply(messages, 'investigation-capture').model_dump()
            ref, = result_value(tool_reply(messages, 'investigation-capture'))['result']['source_refs']
            held['captured_ref'] = ref
            return action('read_context', 'investigation-captured-version', target_ref=ref)
        if turn == 3:
            held['captured_version_return'] = tool_reply(messages, 'investigation-captured-version').model_dump()
            held['perform_args'] = {'operation_id': 'investigation-check-current',
                'scope_ids': ['current-rule-comparison'],
                'source_selections': [{'source_id': 's', 'offset': 0, 'limit': 1}] if selected else [],
                'content_selections': []}
            return action('perform_assigned_review', 'investigation-perform', **held['perform_args'])
        assert turn == 4, 'Unexpected extra Reviewer choice must remain visible.'
        held['review_return'] = tool_reply(messages, 'investigation-perform').model_dump()
        held['final_messages'] = [m.model_dump() for m in messages]
        return AIMessage(content=json.dumps({'limitation': LIMIT,
            'scoped_result': result_value(tool_reply(messages, 'investigation-perform'))}, ensure_ascii=False))
    return choose


@pytest.mark.parametrize('selected', [True, False], ids=['selected-current-source', 'omit-current-tool-selection'])
async def test_reviewer_investigation_preserves_source_version_and_actual_checker_material(ws, request, selected):
    root = Path(os.environ.get('REPORT_REVIEWER_SOURCE_OUT', str(ws.store.root / 'captures')))
    folder = root / ('selected' if selected else 'omitted')
    held, checker = {}, CheckerCalibration()
    choose = investigation_script(folder, selected, held)
    driver = Driver(reviewer=[choose] * 5)
    capture = await capture_reviewer_source_investigation(ws, folder,
        lambda role: checker if role == 'text_tool' else driver(role))
    dump(folder / 'scripted-choices.json', held)
    assert capture['raised_error'] is None, capture['raised_error']
    assert capture['runtime']['last_error'] is None, capture['runtime']
    assert capture['originals_unchanged'] and not capture['host_completion_actions']
    assert held['turn'] == 5 and len(checker.calls) == 1
    fixture = capture['fixture']
    assert fixture['old_source_payload']['content'] == OLD_RULE
    assert fixture['current_source_payload']['content'] == CURRENT_RULE
    assert fixture['old_source_payload'] != fixture['current_source_payload']
    original_read = result_value(tool_reply(messages_from_dict(capture['phase_events'][1]['messages']),
                                           'investigation-current-original'))
    transition = fixture['catalog_transition']
    assert transition['old_block_rows'][0][3] == OLD_RULE
    assert transition['current_block_rows'] == [['s', 0, 'current synthetic rule v2; block 0', CURRENT_RULE]]
    expected_page = transition['current_source_page']
    actual_page = {key: original_read[key] for key in expected_page}
    assert actual_page == expected_page
    assert digest(actual_page) == transition['current_page_digest']
    payload = fixture['current_source_payload']
    assert {k: v for k, v in payload['source_metadata'].items() if k != 'text_digest'} == actual_page['source']
    assert payload['source_metadata']['text_digest'] == payload['file_digest'] == digest(CURRENT_RULE)
    assert fixture['eligible_current_source_ref'] not in ContentStore(ws.store).read(fixture['snapshot_ref'])['payload']['refs']
    task, = ContentStore(ws.store).list_objects('DelegatedTask')
    assert task['owner_id'] == task['payload']['delegated_by'] == 'content:coordinator'
    assert task['payload']['role'] == 'reviewer' and task['payload']['goal'] == fixture['goal']
    assert task['payload']['write_scope'] == 'Only artifacts produced by this task; read other project artifacts.'
    expected_actor = 'content:reviewer:' + task['ref']['id']
    for phase in capture['phase_events']:
        assert phase['server_context']['role'] == 'reviewer'
        assert phase['server_context']['actor_id'] == expected_actor
        assert phase['server_context']['assignment'] == task['payload']
    captured, = capture['reviewer_captured_sources']
    assert captured['owner_id'] == expected_actor
    assert captured['ref'] == held['captured_ref']
    assert captured['payload'] == fixture['current_source_payload']
    version_return = result_value(tool_reply(messages_from_dict(capture['phase_events'][3]['messages']),
                                           'investigation-captured-version'))
    assert version_return['result']['objects'] == [captured]
    packet = json.loads(checker.calls[0][-1][1])
    assert packet['task_id'] == task['ref']['id']
    assert packet['assignment']['review_snapshot_ref'] == fixture['snapshot_ref']
    assert packet['criteria'][0]['ref'] == fixture['refs']['criterion']
    if selected:
        source_entry, = [e for e in packet['evidence'] if e['kind'] == 'source_blocks']
        assert source_entry['observation']['source'] == actual_page['source']
        assert source_entry['observation']['blocks'] == actual_page['blocks']
        assert digest({key: source_entry['observation'][key] for key in expected_page}) == transition['current_page_digest']
    assert OLD_RULE not in json.dumps(packet['evidence'], ensure_ascii=False)
    review, = capture['saved_reviews']
    assert review['owner_id'] == expected_actor
    item, = review['payload']['items']
    assert item['target_ref'] == fixture['refs']['claim']
    if selected:
        assert item['execution_state'] == 'completed' and item['verdict'] == 'not_satisfied'
        current_dependencies = [ContentStore(ws.store).read(r) for r in review['payload']['dependency_refs']
                                if r['type'] == 'SourceArtifact']
        assert current_dependencies and all(r['payload'] == fixture['current_source_payload'] for r in current_dependencies)
        assert capture['task_status'][0]['execution_complete']
    else:
        assert item['execution_state'] == 'blocked' and item['verdict'] is None
        assert item['checked_requirement_indexes'] == []
        assert 'not established' in item['reason']
        assert capture['task_status'][0]['remaining']
        assert not [r for r in review['payload']['dependency_refs'] if r['type'] == 'SourceArtifact']
    assert LIMIT in json.dumps(capture['fake_parent_events'][-1]['actual_child_return'], ensure_ascii=False)
    assert 'scoped_result' in json.dumps(capture['fake_parent_events'][-1]['actual_child_return'], ensure_ascii=False)
    assert all(m['role'] == 'reviewer' for m in capture['native_model_calls'])
    assert len(capture['native_model_calls']) == 5
