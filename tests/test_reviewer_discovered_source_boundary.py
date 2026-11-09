"""Native fake-model discovery/handoff contrasts; no semantic acceptance claim.

The positive oracle is unchanged by the initial optional pool: an explicitly
authorized project original selected for the same assigned question must reach
the checker. A different project's source remains inaccessible. No app patches.
"""
from copy import deepcopy
import json
import os
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from report_agent.content_store import ContentStore
from report_agent.deep_runtime import run_report
from report_agent.store import Store
from report_agent.task_supervision import ReviewRequirement
from report_agent.workspace import Workspace
from test_agent_duty_trace_cases import action, result_value, tool_reply
from test_bounded_review import Model, review_call
from test_decision_data import activate
from test_deep_runtime import Driver
from test_hierarchical_content import seed
from test_task_supervision import ws, offline


ORIGINAL = 'Synthetic corrigendum: class B permits 75 to 100; retain this condition.'
GOAL = ('Check the existing adopted-class claim. All supplied project sources are '
        'authorized for investigation and selection for this same question, including '
        'sources not prelisted by the Coordinator. Do not change the report or task scope.')


def prepare(ws, prelisted):
    # Set the actual commission before importing Requirement; no later goal rewrite.
    ws.store.set('manifest', {**ws.store.manifest, 'goal': GOAL, 'sources': [
        *ws.store.manifest['sources'],
        {'id': 'g2', 'title': 'Synthetic corrigendum', 'content': ORIGINAL, 'coverage': 'complete'}]})
    from test_source_use_authority import approved_policy
    approved_policy(ws.store, [s['id'] for s in ws.store.manifest['sources']])
    cs, owner, refs, snapshot, _ = seed(ws)
    eligible = cs.capture_sources(owner, 'known-project-original', ['g2'])['result']['source_refs'][0]
    task = review_call(snapshot, refs, id='discover-source-task')
    task['args'].pop('supervision_plugin')
    task['args']['description'] = GOAL
    requirement = task['args']['review_requirements'][0]
    if prelisted:
        requirement.update(material_refs=[eligible], source_ranges=[{
            'source_ref': eligible, 'offset': 0, 'limit': 1}])
    activate(ws)
    return cs, refs, snapshot, eligible, task


class SelectedOriginalChecker(Model):
    async def ainvoke(self, messages):
        packet = json.loads(messages[-1][1])
        claim_index = next(i for i, e in enumerate(packet['evidence'])
                           if e['kind'] == 'saved_object' and e['object']['ref']['type'] == 'ContentNode')
        source_index, source = next((i, e) for i, e in enumerate(packet['evidence'])
                                    if e['kind'] == 'source_blocks')
        assert source['selection'] == {'source_id': 'g2', 'offset': 0, 'limit': 1}
        assert [b['text'] for b in source['observation']['blocks']] == [ORIGINAL]
        self.response = json.dumps({'items': [{
            'scope_id': 'rule-comparison', 'execution_state': 'completed', 'verdict': 'not_satisfied',
            'checked_requirement_indexes': [0],
            'observations': [
                {'evidence_index': claim_index, 'locator': 'original claim', 'observation': 'Adopted B, value 70.'},
                {'evidence_index': source_index, 'locator': 'g2 block 0', 'observation': ORIGINAL}],
            'check_results': [{'requirement_index': 0, 'execution_state': 'completed',
                'result': 'Synthetic 70 is outside the supplied interval.',
                'observation_indexes': [0, 1], 'remaining': ''}],
            'coverage': {'checked': ['Assigned rule comparison'], 'unchecked': [], 'blocked': [],
                         'basis': 'Exact selected originals; synthetic fixture only.'},
            'reason': 'Synthetic comparison only; not engineering acceptance.', 'findings': []}]})
        # Retained runner records the real independent-tool packet and this output.
        return await super().ainvoke(messages)


def save_capture(ws, request, held, checker, original_objects, task, runtime, error):
    folder = Path(os.environ.get('REPORT_DISCOVERED_SOURCE_OUT', str(ws.store.root / 'captures')))
    folder.mkdir(parents=True, exist_ok=True)
    cs = ContentStore(ws.store)
    with ws.store.connect() as db:
        receipts = [{'id': row[0], 'actor_id': row[1], 'data': json.loads(row[2])}
                    for row in db.execute('SELECT id,actor_id,data FROM content_observations')]
    capture = {'test': request.node.nodeid, 'task_call': task, 'observed': held,
               'checker_calls': checker.calls, 'runtime': runtime, 'raised_error': error,
               'objects': cs.list_objects(), 'events': ws.store.events(), 'receipts': receipts,
               'originals_unchanged': all(cs.read(obj['ref']) == obj for obj in original_objects),
               'limits': 'Scripted choices and real software boundaries; no autonomous-model or engineering verdict.'}
    (folder / (request.node.name.replace('[', '-').replace(']', '') + '.json')).write_text(
        json.dumps(capture, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    return capture


@pytest.mark.parametrize('prelisted', [True, False], ids=['prelisted-original', 'discovered-authorized-original'])
async def test_selected_authorized_original_reaches_checker(ws, request, prelisted):
    cs, refs, snapshot, eligible, task = prepare(ws, prelisted)
    originals, held, checker = deepcopy(cs.list_objects()), {}, SelectedOriginalChecker()

    def reviewer(messages):
        turn = held.get('turn', 0)
        held['turn'] = turn + 1
        if turn == 0:
            return action('search_sources', 'discover', query='corrigendum')
        if turn == 1:
            held['search_return'] = tool_reply(messages, 'discover').model_dump()
            return AIMessage(content='', tool_calls=[
                action('read_source_page', 'read-original', source_id='g2', offset=0, limit=1).tool_calls[0],
                action('read_context', 'read-claim', target_ref=refs['claim']).tool_calls[0]])
        if turn == 2:
            held['read_return'] = tool_reply(messages, 'read-original').model_dump()
            return action('capture_review_sources', 'capture', operation_id='discovered-original', source_ids=['g2'])
        if turn == 3:
            held['capture_return'] = tool_reply(messages, 'capture').model_dump()
            held['captured_ref'], = result_value(tool_reply(messages, 'capture'))['result']['source_refs']
            return action('read_context', 'read-captured', target_ref=held['captured_ref'])
        if turn == 4:
            held['captured_read_return'] = tool_reply(messages, 'read-captured').model_dump()
            return action('perform_assigned_review', 'perform', operation_id='selected-original-review',
                          scope_ids=['rule-comparison'],
                          source_selections=[{'source_id': 'g2', 'offset': 0, 'limit': 1}], content_selections=[],
                          source_version_refs=[held['captured_ref']])
        assert turn == 5, 'Unexpected extra fake-model choice remains a test failure.'
        held['review_return'] = tool_reply(messages, 'perform').model_dump()
        return AIMessage(content=json.dumps({'actual_review_return': result_value(tool_reply(messages, 'perform'))}))

    def parent(messages):
        held['parent_return'] = tool_reply(messages, 'discover-source-task').model_dump()
        return AIMessage(content=json.dumps({'actual_child_return': result_value(tool_reply(messages, 'discover-source-task'))}))

    driver = Driver(coordinator=[AIMessage(content='', tool_calls=[task]), parent], reviewer=[reviewer] * 6)
    runtime, error = None, None
    try:
        runtime = await run_report(ws, lambda role: checker if role == 'text_tool' else driver(role))
    except Exception as exc:
        error = {'type': type(exc).__name__, 'message': str(exc)}
    finally:
        capture = save_capture(ws, request, held, checker, originals, task, runtime, error)
    assert error is None, error
    assert runtime['last_error'] is None, runtime
    assert capture['originals_unchanged']
    assert ORIGINAL in json.dumps(held['read_return'], ensure_ascii=False)
    captured = cs.read(held['captured_ref'])
    assert captured['payload'] == cs.read(eligible)['payload']
    assert captured['owner_id'].startswith('content:reviewer:')
    assert ORIGINAL in json.dumps(held['captured_read_return'], ensure_ascii=False)
    # Same positive oracle in both branches. Do NOT xfail or reinterpret refusal as success.
    assert len(checker.calls) == 1, held.get('review_return')
    packet = json.loads(checker.calls[0][-1][1])
    saved_task, = cs.list_objects('DelegatedTask')
    normalized = [ReviewRequirement.model_validate(req).model_dump()
                  for req in task['args']['review_requirements']]
    saved_normalized = [ReviewRequirement.model_validate(req).model_dump()
                        for req in saved_task['payload']['review_requirements']]
    assert saved_normalized == normalized
    assert packet['assignment']['review_requirements'] == saved_task['payload']['review_requirements']
    assert packet['assignment']['review_snapshot_ref'] == snapshot
    saved, = cs.list_objects('ReviewRecord')
    assert saved['payload']['items'][0]['verdict'] == 'not_satisfied'
    dependencies = [cs.read(ref) for ref in saved['payload']['dependency_refs'] if ref['type'] == 'SourceArtifact']
    assert any(obj['payload'] == captured['payload'] for obj in dependencies)
    assert any(ORIGINAL in json.dumps(receipt['data'], ensure_ascii=False) and
               'analysis_operation' in receipt['data'] for receipt in capture['receipts'])
    assert 'not_satisfied' in json.dumps(held['parent_return'], ensure_ascii=False)


async def test_foreign_project_source_is_not_discoverable_or_capturable(ws, request, tmp_path):
    cs, refs, snapshot, eligible, task = prepare(ws, False)
    foreign_marker = 'FOREIGN PROJECT ONLY: never expose these bytes to project A.'
    foreign = Workspace(Store(tmp_path / 'foreign'))
    foreign.store.initialize({'goal': 'Different project', 'sources': [
        {'id': 'foreign-only', 'title': 'Foreign source', 'content': foreign_marker, 'coverage': 'complete'}]})
    assert foreign.store.sources(['foreign-only'])[0]['content'] == foreign_marker
    originals, held, checker = deepcopy(cs.list_objects()), {}, SelectedOriginalChecker()

    def reviewer(messages):
        turn = held.get('turn', 0)
        held['turn'] = turn + 1
        if turn == 0:
            return action('read_source_page', 'foreign-read', source_id='foreign-only', offset=0, limit=1)
        if turn == 1:
            held['read_return'] = tool_reply(messages, 'foreign-read').model_dump()
            return action('capture_review_sources', 'foreign-capture', operation_id='foreign-capture', source_ids=['foreign-only'])
        assert turn == 2
        held['capture_return'] = tool_reply(messages, 'foreign-capture').model_dump()
        return AIMessage(content=json.dumps({'actual_errors': held}))

    def parent(messages):
        held['parent_return'] = tool_reply(messages, 'discover-source-task').model_dump()
        return AIMessage(content='Foreign original unavailable; no review verdict produced.')

    driver = Driver(coordinator=[AIMessage(content='', tool_calls=[task]), parent], reviewer=[reviewer] * 3)
    runtime, error = None, None
    try:
        runtime = await run_report(ws, lambda role: checker if role == 'text_tool' else driver(role))
    except Exception as exc:
        error = {'type': type(exc).__name__, 'message': str(exc)}
    finally:
        capture = save_capture(ws, request, held, checker, originals, task, runtime, error)
    assert error is None, error
    for key in ('read_return', 'capture_return'):
        assert 'SOURCE_USE_VERSION_NOT_AUTHORIZED' in json.dumps(held[key]), held[key]
    assert foreign_marker not in json.dumps(capture, ensure_ascii=False)
    assert not checker.calls and not cs.list_objects('ReviewRecord')
    assert not [obj for obj in cs.list_objects('SourceArtifact') if obj['payload']['source_id'] == 'foreign-only']
    assert capture['originals_unchanged']
