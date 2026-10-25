"""Existing state entry points expose local waiting facts without a new monitor."""
import json

from report_agent.model_invocation import model_invocation
from test_task_supervision import ws, offline


async def test_native_status_and_cli_share_read_only_wait_projection(ws, monkeypatch, capsys):
    from report_agent.cli import main
    from report_agent.deep_runtime import project_view
    from report_agent.knowledge_state import project_state
    async with model_invocation(ws.store, 'coordinator') as trace:
        for state in (project_state(ws), project_view(ws)):
            row, = state['model_calls']['calls']
            assert row['call_id'] == trace.call_id
            assert not row['local_terminal'] and row['provider_unknown']
        monkeypatch.setattr('sys.argv', ['report-agent', 'report-status', '--project', str(ws.store.root)])
        main()
        row, = json.loads(capsys.readouterr().out)['model_calls']['calls']
        assert row['call_id'] == trace.call_id
        assert row['latest_known_phase'] is None and row['provider_unknown']
    before = ws.store.events()
    state = project_state(ws)
    assert state['model_calls']['calls'][0]['local_terminal']
    assert state['model_calls']['calls'][0]['provider_unknown']  # No actual HTTP completed.
    assert ws.store.events() == before
