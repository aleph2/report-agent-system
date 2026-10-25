"""Native C5 contracts and a missing-target sensitivity control; zero models."""
from copy import deepcopy
import json
import os
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from duty_probe_agent_decisions import dump
from duty_probe_coordinator_review_commission import (
    CHILD_FINAL, PARENT_FINAL, capture_coordinator_review_commission,
)
from report_agent.content_store import ContentStore
from report_agent.task_context import read_observation
from test_agent_duty_trace_cases import action, result_value, tool_reply
from test_deep_runtime import Driver
from test_task_supervision import ws, offline


def commission_script(folder, variant, held):
    def choose(messages):
        turn = held.get('turn', 0)
        held['turn'] = turn + 1
        if turn == 0:
            fixture = json.loads((Path(folder) / 'fixture.json').read_text())
            call = deepcopy(fixture['task_call'])
            call['id'] = 'c5-review-task'
            if variant == 'omit-second':
                call['args']['review_requirements'] = call['args']['review_requirements'][:1]
            held['actual_fake_model_choice'] = deepcopy(call)
            held['first_coordinator_messages'] = [m.model_dump() for m in messages]
            return AIMessage(content='', tool_calls=[call])
        if turn == 1:
            returned = tool_reply(messages, 'c5-review-task')
            held['native_child_return'] = returned.model_dump()
            assert CHILD_FINAL in str(returned.content)
            return action('read_task_supervision', 'c5-supervision')
        message = next(m for m in reversed(messages) if isinstance(m, ToolMessage))
        value = result_value(message)
        if message.name == 'read_task_supervision' and value.get('complete_tool_result') is False:
            assert value['exact_data_tool'] == 'read_tool_observation'
            held['supervision_advertisement'] = deepcopy(value)
            held['supervision_pages'] = []
            return action('read_tool_observation', 'c5-supervision-page-0',
                          observation_ref=value['observation_ref'], offset=0, characters=6000)
        if message.name == 'read_tool_observation':
            assert value['observation_ref'] == held['supervision_advertisement']['observation_ref']
            pages = held['supervision_pages']
            assert value['offset'] == sum(len(p['text']) for p in pages)
            pages.append(deepcopy(value))
            if value['next_offset'] is not None:
                return action('read_tool_observation', 'c5-supervision-page-' + str(value['next_offset']),
                              observation_ref=value['observation_ref'], offset=value['next_offset'], characters=6000)
            value = json.loads(''.join(p['text'] for p in pages))
        assert value['ok'] is True and len(value['result']['tasks']) == 1
        held['actual_supervision'] = deepcopy(value['result']['tasks'][0])
        return AIMessage(content=PARENT_FINAL)
    return [choose] * 10


def missing_commission_targets(fixture, tasks):
    """Independent semantic calibration, not a production acceptance guard."""
    expected = list(zip(fixture['evidence_refs'][:2], fixture['criterion_refs'], strict=True))
    assert len(expected) == 2
    assert len({json.dumps(pair, sort_keys=True) for pair in expected}) == 2
    actual = [(r['target_ref'], r['criterion_ref']) for t in tasks
              for r in t['payload'].get('review_requirements', [])]
    return [pair for pair in expected if pair not in actual]


@pytest.mark.parametrize('variant', ['both-objects', 'omit-second'])
async def test_native_coordinator_commission_is_preserved_and_omission_remains_visible(ws, tmp_path, variant):
    folder = Path(os.environ.get('REPORT_COORDINATOR_COMMISSION_OUT', tmp_path / 'evidence')) / variant
    held = {}
    driver = Driver(coordinator=commission_script(folder, variant, held))
    capture = await capture_coordinator_review_commission(ws, variant, folder, driver)
    dump(folder / 'independent-observations.json', held)
    assert capture['raised_error'] is None, capture['raised_error']
    assert capture['runtime']['last_error'] is None, capture['runtime']
    assert len(driver.calls) == len(capture['native_model_calls']) == 3 + len(held.get('supervision_pages', []))
    assert all(role == 'coordinator' for role, _, _ in driver.calls)
    assert capture['originals_unchanged'] is True
    assert capture['saved_reviews'] == [] and len(capture['saved_tasks']) == 1
    fixture, saved = capture['fixture'], capture['saved_tasks'][0]
    cs = ContentStore(ws.store)
    for i, ref in enumerate(fixture['evidence_refs'][:2]):
        assert cs.read(ref)['payload'] == fixture['original_packet']['evidence'][i]['object']['payload']
    assert len(fixture['criterion_refs']) == len({r['id'] for r in fixture['criterion_refs']}) == 2
    prepared = capture['phase_events'][0]['response']['tool_calls']
    assert prepared and {c['name'] for c in prepared} == {'read_context'}
    allowed = [o['ref'] for o in fixture['originals']
               if o['ref']['type'] in {'Requirement', 'Criterion', 'SourceArtifact', 'ContentNode', 'DocumentSnapshot'}]
    assert all(c['args']['target_ref'] in allowed for c in prepared)
    first_messages = held['first_coordinator_messages']
    serialized = json.dumps(first_messages, ensure_ascii=False)
    assert fixture['task_call']['id'] not in serialized
    assert all(r['scope_id'] not in serialized for r in fixture['task_call']['args']['review_requirements'])
    actual_returns = {m['tool_call_id']: m for m in first_messages if m['type'] == 'tool'}
    assert set(actual_returns) == {c['id'] for c in prepared}
    held['host_audited_original_reads'] = []
    for call in prepared:
        public = json.loads(actual_returns[call['id']]['content'])
        value = public.get('metadata', public)
        assert value['ok'] is True and value['result']['target_ref'] == call['args']['target_ref']
        # Public authored bodies may be deliberately deferred. This host-only
        # audit verifies their exact original recovery, not model reading.
        if public.get('observation_ref'):
            pages, offset = [], 0
            while True:
                page = read_observation(ws, 'coordinator', public['observation_ref'], offset, 6000)
                assert page['offset'] == offset
                pages.append(page)
                if page['next_offset'] is None:
                    break
                offset = page['next_offset']
            value = json.loads(''.join(p['text'] for p in pages))
        target = cs.read(call['args']['target_ref'])
        refs = target['payload']['refs'] if target['ref']['type'] == 'DocumentSnapshot' else [target['ref']]
        assert value['result']['loaded_refs'] == refs
        assert value['result']['next_offset'] is None
        assert value['result']['objects'] == [cs.read(ref) for ref in refs]
        assert all(o['ref']['type'] not in {'DelegatedTask', 'ReviewRecord'} for o in value['result']['objects'])
        held['host_audited_original_reads'].append(value)
    chosen = held['actual_fake_model_choice']
    assert saved['payload']['review_snapshot_ref'] == chosen['args']['review_snapshot_ref']
    assert saved['payload']['goal'] == chosen['args']['description']
    assert len(saved['payload']['review_requirements']) == len(chosen['args']['review_requirements'])
    for original, received in zip(chosen['args']['review_requirements'], saved['payload']['review_requirements'], strict=True):
        for field, value in original.items():
            assert received[field] == value, 'C5_FIELD_CHANGED:' + field
    assert saved['owner_id'] == 'content:coordinator'
    assert saved['payload']['role'] == 'reviewer'
    assert saved['payload']['delegated_by'] == 'content:coordinator'
    assert saved['payload']['write_scope'] == 'Only artifacts produced by this task; read other project artifacts.'
    assert saved['payload']['supervision_plugin'] is None
    for event in capture['fake_child_events']:
        assert event['server_context']['role'] == 'reviewer'
        assert event['server_context']['actor_id'] == 'content:reviewer:' + saved['ref']['id']
        assert event['server_context']['assignment'] == saved['payload']
    reads = [e['received_assignment'] for e in capture['fake_child_events'] if e.get('received_assignment')]
    assert len(reads) == 1
    assert reads[0]['task_id'] == saved['ref']['id']
    for field in ('review_snapshot_ref', 'review_requirements', 'goal'):
        assert reads[0]['assignment'][field] == saved['payload'][field], 'C5_CHILD_FIELD_CHANGED:' + field
    assert capture['saved_task_status'][0]['execution_complete'] is False
    assert held['actual_supervision']['execution_complete'] is False
    assert len(held['actual_supervision']['remaining']) == (2 if variant == 'both-objects' else 1)
    assert capture['finals'] == [PARENT_FINAL]
    missing = missing_commission_targets(fixture, capture['saved_tasks'])
    assert len(missing) == (0 if variant == 'both-objects' else 1)
    # A syntactically valid narrower assignment is not silently enlarged by the
    # program; its unsupported "both" final is exposed by the independent oracle.
    semantic_status = 'needs_semantic_review' if missing else 'not_semantically_assessed'
    assert capture['saved_tasks'] == cs.list_objects('DelegatedTask')
    dump(folder / 'independent-observations.json', held)
    dump(folder / 'oracle.json', {'mechanical_result': 'passed', 'known_fixture_semantic_status': semantic_status,
        'missing_target_criterion_pairs': missing, 'fake_coordinator_calls': len(driver.calls), 'paid_calls': 0,
        'scope': 'Default supervision=None, exact fresh delegation/child/parent transport and omission sensitivity; no completed review, old-task recovery or engineering acceptance.'})
