"""R12 configured SDK Mock: valid save and received-output rejection stay distinct."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys

import pytest

from report_agent.request_budget import RequestBudget, request_budget
from report_agent.token_budget import TokenBudget, token_budget
from test_duty_optimizer_adapter import no_external_network
from test_task_supervision import ws

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import probe_duty_visual as adapter


@pytest.mark.parametrize('duplicate_index', [False, True], ids=['valid-save', 'invalid-output'])
async def test_artifact_adapter_preserves_public_save_or_output_failure(ws, request, monkeypatch, duplicate_index):
    for prefix in ('REPORT_', 'REPORT_TEXT_TOOL_', 'REPORT_VISION_'):
        for key, value in {'MODEL': 'glm-5.3', 'BASE_URL': 'https://offline.invalid/v1', 'API_KEY': 'offline'}.items():
            monkeypatch.setenv(prefix + key, value)
    for name, value in {'REPORT_SDK_RETRIES': '5', 'REPORT_CONNECT_RETRIES': '0',
                        'REPORT_DEEPSEEK_STRICT': '0', 'LANGSMITH_TRACING': 'false'}.items():
        monkeypatch.setenv(name, value)
    original_fixture = adapter._artifact_fixture
    if duplicate_index:
        def invalid(packet, **kwargs):
            output = deepcopy(original_fixture(packet, **kwargs))
            assert [v['requirement_index'] for v in output['items'][0]['check_results']] == [0, 1]
            output['items'][0]['check_results'][1]['requirement_index'] = 0
            return output
        monkeypatch.setattr(adapter, '_artifact_fixture', invalid)
    folder = Path(os.environ.get('REPORT_ARTIFACT_ADAPTER_OUT', str(ws.store.root / 'adapter')))
    folder = folder / ('invalid-output' if duplicate_index else 'valid-save')
    budget = TokenBudget(ws.store.root / 'mock-token-budget.db', 1000000, {'glm-5.3': 100000})
    cap = RequestBudget(2)
    with token_budget(budget), request_budget(cap):
        result = await adapter.probe_visual_pair(ws, folder, False, case='visual-artifact-columns-complete')
    request.node.user_properties.append(('artifact_adapter_result', str(folder / 'result.json')))
    assert result['observed_http_requests'] == result['observed_http_responses'] == 2
    assert not result['observer_errors'] and not result['offline_fixture_errors']
    assert result['scripted_public_tool_actions_executed'] and not result['real_agent_actions_executed']
    raw = json.loads((folder / 'model-output.json').read_text(encoding='utf-8'))
    output = json.loads(raw['content'])
    assert [v['requirement_index'] for v in output['items'][0]['check_results']] == ([0, 0] if duplicate_index else [0, 1])
    execution = result['tool_result']
    if duplicate_index:
        assert result['status'] == 'failed'
        assert result['failure_stage'] == 'tool_execution'
        assert result['failure_category'] == 'public_native_tool_failure_requires_diagnosis'
        assert execution['failure']['stage'] == 'perform_assigned_artifact_review'
        assert execution['saved_review'] is None
        assert not execution['artifact_check_completed']
        assert execution['next_reviewer_tool_message']['status'] == 'error'
    else:
        assert result['status'] == 'passed_structure'
        assert execution['artifact_check_completed']
        assert execution['saved_review']['payload']['items'][0]['verdict'] == 'not_satisfied'
        assert execution['next_reviewer_tool_message']['status'] == 'success'
        assert all(result['receipt_binding'][k] for k in ('saved_review_actor_matches', 'snapshot_matches', 'sent_image_matches'))
