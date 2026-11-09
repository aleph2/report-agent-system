"""Incomplete commissioned scope cannot become a successful CLI or native result."""
from report_agent import report_state
import sys

import httpx
import pytest
from langchain_core.messages import AIMessage

from report_agent import cli, deep_runtime
from test_deep_runtime import Driver
from test_m1_commission_plan import commission, save, approve
from test_m1_commission_coverage import completed_objects


def test_cli_incomplete_delivery_overrides_optimistic_execution_flag(commission, monkeypatch):
    async def fake_run(workspace, **kwargs):
        return {'execution_status': 'completed', 'status': 'incomplete', 'last_error': None}
    monkeypatch.setattr(deep_runtime, 'run_report', fake_run)
    monkeypatch.setattr(sys, 'argv', ['report-agent', 'report-run', '--project', str(commission.ws.store.root)])
    assert cli.main() == 2


async def test_native_terminal_keeps_unassessed_object_incomplete(commission, monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail('Offline native terminal test attempted network')
    monkeypatch.setattr(httpx.Client, 'send', denied)
    monkeypatch.setattr(httpx.AsyncClient, 'send', denied)
    monkeypatch.setenv('LANGSMITH_TRACING', 'false')
    monkeypatch.setenv('LANGCHAIN_TRACING_V2', 'false')
    manifest = commission.ws.store.manifest
    manifest.update(review_entrypoint='delegated-reviewer-v1', review_execution_mode='native-reviewer-v2')
    commission.ws.store.set('manifest', manifest)
    commission.ws.store.set('knowledge_enabled', False)
    saved = save(commission)
    approve(commission, saved)
    _, _, snapshot = completed_objects(commission, saved)
    report_state.set_content_delivery(commission.ws.store, {'snapshot_ref': snapshot['ref'],
        'export_ref': {'type': 'ExportArtifact', 'id': 'unreviewed-export', 'version': 1}})
    driver = Driver(coordinator=[AIMessage(content='Finished; synthetic terminal only.')])
    result = await deep_runtime.run_report(commission.ws, driver)
    assert result['last_error'] is None, result
    assert result['status'] == 'incomplete', result
    assert commission.ws.store.get('report_status') == 'incomplete'
    assert len(driver.calls) == 1
