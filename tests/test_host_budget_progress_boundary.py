"""A host refusal closes a recovery window without becoming its own limit."""
import pytest

from report_agent import deep_runtime
from report_agent.execution_progress import authorize_recovery, EPISODES
from report_agent.learning import LearningLibrary
from report_agent.model_recovery import activate_recovery
from report_agent.prompt_instructions import configure_report
from report_agent.request_budget import (
    RequestBudget, RequestBudgetExceeded, request_budget, request_reservation_observer,
)
from report_agent.token_budget import TokenBudget, token_budget
from test_execution_progress import sdk_case, episodes
from test_hierarchical_content import ws
from test_prompt_instructions import candidate, release


@pytest.mark.parametrize('reason', ['HOST_TOKEN_BUDGET_REACHED', 'HOST_ADMISSION_WINDOW_ENDED'])
async def test_outer_host_limit_keeps_primary_reason_consumed_window_and_no_new_resume_permission(ws, monkeypatch, tmp_path, reason):
    ledger = TokenBudget(tmp_path / 'limit.db', 60000, {'glm-5.3': 1000})
    old_id = ledger.reserve('glm-5.3')
    with ledger.connect() as db:
        old = db.execute('SELECT * FROM attempts WHERE id=?', (old_id,)).fetchone()
    library = tmp_path / 'isolated-learning'
    LearningLibrary(library)
    ws.store.set('learning_config', {'library_path': str(library), 'customer_id': 'host-cap-fixture'})
    with token_budget(ledger):
        async with sdk_case(ws, monkeypatch) as case:
            activate_recovery(ws.store, authorization='Synthetic fixture bounded recovery authority')
            await deep_runtime.run_report(ws, case['factory'])
            episode, = episodes(ws)
            configure_report(ws.store, 'host-cap-fixture')
            instruction = candidate(ws, text='New fixture condition; observe current remaining work.')
            release(ws, instruction)

            def refuse():
                raise RequestBudgetExceeded(reason)

            with request_budget(RequestBudget(10)), request_reservation_observer(refuse):
                authorize_recovery(ws, episode['episode_id'],
                    {'kind': 'effective_instruction', 'ref': instruction['ref']},
                    authorization_basis='Direct synthetic host authority',
                    reason='One bounded observation; no unknown replay.', max_http_attempts=1)
                sent_before = len(case['wires'])
                await deep_runtime.run_report(ws, case['factory'])
            assert len(case['wires']) == sent_before
            limited = ws.store.get(EPISODES + episode['episode_id'])
            assert limited['state'] == 'observation_limit'
            assert limited['stop_origin'] == 'outer_admission'
            assert limited['stop_reason_code'] == reason
            assert limited['resume_boundary'] is None
            grant = ws.store.get(limited['recovery_key'])
            assert grant['state'] == 'consumed' and grant['used'] == 0
            error = ws.store.get('report_error')
            assert ws.store.get('report_status') == 'needs_attention'
            assert error['message'] == reason and error['failure_kind'] == 'host_admission_blocked'
            assert error['automatic_resume'] is False
            event = next(e for e in reversed(ws.store.events())
                         if e['kind'] == 'execution_progress_observation_limit')
            assert event['data']['stop_origin'] == 'outer_admission'
            assert event['data']['reason_code'] == reason
    with ledger.connect() as db:
        assert db.execute('SELECT * FROM attempts WHERE id=?', (old_id,)).fetchone() == old
