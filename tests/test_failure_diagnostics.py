import json
import sqlite3

from report_agent.failure_diagnostics import FailureDiagnostics
from report_agent.store import Store


def test_database_failure_saves_callsite_and_sqlite_code_without_text_or_locals(tmp_path):
    store = Store(tmp_path)
    audit = FailureDiagnostics(store)
    private_value = 'private-engineering-body-and-api-key'
    try:
        with sqlite3.connect(':memory:') as db:
            db.execute('SELECT * FROM absent_table')
    except sqlite3.OperationalError as error:
        first = audit.record(error)
        assert audit.record(error) == first
    files = list((tmp_path / 'diagnostics' / 'private').glob('*.json'))
    assert len(files) == 1
    data = json.loads(files[0].read_text())
    assert data['exceptions'][0]['sqlite_errorname'] == 'SQLITE_ERROR'
    assert data['exceptions'][0]['frames'][-1]['function'] == 'test_database_failure_saves_callsite_and_sqlite_code_without_text_or_locals'
    assert private_value not in files[0].read_text()
    assert 'absent_table' not in files[0].read_text()
    assert list(first) == ['diagnostic_id']


async def test_native_graph_callback_records_root_failure(tmp_path):
    from langgraph.graph import StateGraph, START
    from typing import TypedDict
    import pytest
    class State(TypedDict):
        value: int
    def failed(state):
        raise RuntimeError('private-provider-body')
    graph = StateGraph(State).add_node('failed', failed).add_edge(START, 'failed').compile()
    audit = FailureDiagnostics(Store(tmp_path))
    with pytest.raises(RuntimeError):
        await graph.ainvoke({'value': 1}, {'callbacks': [audit]})
    files = list((tmp_path / 'diagnostics' / 'private').glob('*.json'))
    assert len(files) == 1
    assert 'private-provider-body' not in files[0].read_text()


def test_failed_diagnostic_write_does_not_replace_original_error(tmp_path, monkeypatch):
    from pathlib import Path
    audit = FailureDiagnostics(Store(tmp_path))
    def denied(*args, **kwargs):
        raise OSError('disk unavailable')
    monkeypatch.setattr(Path, 'open', denied)
    assert audit.record(RuntimeError('original')) is None


async def test_build_agent_direct_native_call_inherits_diagnostic_callback(tmp_path, monkeypatch):
    from report_agent.deep_runtime import build_agent
    from report_agent.workspace import Workspace
    from langchain_core.messages import AIMessage
    from test_deep_runtime import Driver
    import pytest
    monkeypatch.setenv('LANGSMITH_TRACING', 'false')
    store = Store(tmp_path)
    store.initialize({'goal': 'Synthetic diagnostic test', 'sources': [
        {'id': 's', 'content': 'Synthetic', 'coverage': 'complete'}]})
    store.set('knowledge_enabled', False)
    driver = Driver(coordinator=[AIMessage(content='Unreached')])
    driver.fail_once = ('coordinator', 0)
    agent = build_agent(Workspace(store), driver, None, rules='')
    with pytest.raises(Exception):
        await agent.ainvoke({'messages': [('user', 'Synthetic offline task')]})
    files = list((tmp_path / 'diagnostics' / 'private').glob('*.json'))
    assert len(files) == 1
    assert json.loads(files[0].read_text())['public_error']['message'] == 'MODEL_REQUEST_TIMEOUT'
