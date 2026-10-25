"""Pending regression contract; synthetic fixtures only, no live-run mutation."""
import json

import pytest
from langchain_core.messages import ToolMessage
from langchain_core.tools import StructuredTool

from report_agent import request_budget as resource_module
from report_agent.content_tasks import delegated_task
from report_agent.decision_state import read_state
from report_agent.errors import ActionForbidden, ActionRejected
from report_agent.prompt_instructions import configure_report, save_instruction, release_instruction
from report_agent.request_budget import RequestBudget, request_budget
from report_agent.task_context import TaskContext, exact_task_context
from report_agent.token_budget import TokenBudget, token_budget
from test_hierarchical_content import seed
from test_task_supervision import ws


def continue_page(ws, first, role='coordinator'):
    return read_state(ws, role, ['goal'], offset=first['next_offset'], characters=10,
                      expected_state_digest=first['state_digest'])


@pytest.mark.parametrize('change', ['clock', 'http', 'token_reservation', 'token_settlement'])
def test_unchanged_business_page_survives_live_resource_changes(ws, tmp_path, monkeypatch, change):
    seed(ws)
    monkeypatch.setattr(resource_module, 'monotonic', lambda: 100.0)
    http = RequestBudget(10, deadline_monotonic=200.0)
    tokens = TokenBudget(tmp_path/'budget.db', 100, {'synthetic': 40})
    with request_budget(http), token_budget(tokens):
        reserved = tokens.reserve('synthetic') if change == 'token_settlement' else None
        first = read_state(ws, 'coordinator', ['goal'], characters=10)
        before = exact_task_context(ws, 'coordinator')
        if change == 'clock':
            monkeypatch.setattr(resource_module, 'monotonic', lambda: 101.0)
        elif change == 'http':
            http.reserve()  # Local observation only; no network call.
        elif change == 'token_reservation':
            tokens.reserve('synthetic')
        else:
            tokens.settle(reserved, {'total_tokens': 10})
        after = exact_task_context(ws, 'coordinator')
        assert (before['execution_resources'], before['execution_token_resources']) != (
            after['execution_resources'], after['execution_token_resources'])
        second = continue_page(ws, first)
        assert first['value'] + second['value'] == ws.store.manifest['goal'][:20]
        assert second['state_digest'] == first['state_digest']


@pytest.mark.parametrize('change', ['goal', 'scope', 'content_head', 'instruction'])
def test_business_and_authority_changes_still_reject_stale_page(ws, change):
    cs, owner, refs, _, _ = seed(ws)
    ws.store.set('context_policy', 'stateful-tools-v1')
    configure_report(ws.store, 'paging-regression')
    with request_budget(RequestBudget(10)):
        first = read_state(ws, 'coordinator', ['goal'], characters=10)
        if change in {'goal', 'scope'}:
            key = 'goal' if change == 'goal' else 'scope_instruction'
            ws.store.set('manifest', {**ws.store.manifest, key: 'Changed synthetic authority'})
        elif change == 'content_head':
            cs.commit(owner, 'paging-new-head', [{'client_key': 'claim', 'type': 'ContentNode',
                'previous_ref': refs['claim'], 'payload': {**cs.read(refs['claim'])['payload'],
                    'body': {'text': 'Changed synthetic source-supported node'}}}])
        else:
            record = save_instruction(ws.store, {'id': 'paging-policy', 'scope': 'system',
                'topic': 'fixture', 'text': 'Changed synthetic instruction',
                'source_decision': 'Offline regression fixture only'})
            release_instruction(ws.store, record['ref']['id'], record['ref']['version'],
                expected_active=None, reason='Offline fixture')
        with pytest.raises(ActionRejected, match='STATE_CHANGED_READ_CURRENT_PACKET'):
            continue_page(ws, first)


def test_assignment_identity_and_unbound_permissions_remain_strict(ws):
    seed(ws)
    def task(name):
        return {'id': name, 'args': {'subagent_type': 'writer', 'description': name}}
    with delegated_task(ws, 'coordinator', task('first-assignment')):
        first = read_state(ws, 'writer', ['goal'], characters=10)
    with pytest.raises(ActionForbidden):
        continue_page(ws, first, 'writer')
    with delegated_task(ws, 'coordinator', task('second-assignment')):
        with pytest.raises(ActionRejected, match='STATE_CHANGED_READ_CURRENT_PACKET'):
            continue_page(ws, first, 'writer')


def test_offloaded_navigation_names_actual_reader_and_cursor_units(ws):
    seed(ws)
    middleware = TaskContext(ws, 'coordinator')
    raw = json.dumps({'goal': 'Exact Unicode 原文' * 1000}, ensure_ascii=False)
    message = ToolMessage(raw, name='read_decision_state', tool_call_id='nav')
    presented = middleware.bound_result(message)
    first = json.loads(presented.content)
    assert first['tool'] == 'read_decision_state'  # Historical producer identity preserved.
    assert first['exact_data_tool'] == 'read_tool_observation'
    assert first['cursor_unit'] == 'unicode_characters'
    reader = StructuredTool.from_function(next(tool for tool in middleware.tools
        if tool.__name__ == first['exact_data_tool']))
    second = reader.invoke({'observation_ref': first['observation_ref'],
                            'offset': first['next_offset'], 'characters': 6000})
    assert second['text'] == raw[6000:12000]
    assert first['sha256'] == second['sha256']
    assert second['exact_data_tool'] == first['exact_data_tool']
    assert second['cursor_unit'] == first['cursor_unit']
