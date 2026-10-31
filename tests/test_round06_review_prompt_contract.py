from support.flat_task_fixture import task_arguments
"""Final SDK instruction regression, not proof of autonomous semantic judgment."""
import json
import httpx
import pytest

from report_agent.deep_models import GLMChatOpenAI, model_async_client
from report_agent.deep_runtime import run_report
from test_deliverable_declaration_v4 import case
from test_prompt_native_sdk_inputs import completion
from test_review_work_units import configured
from test_two_file_agent_prompts import authored_rules
from report_agent.prompt_sources import load_prompt


@pytest.mark.parametrize('checked_role', ['coordinator', 'reviewer'])
async def test_final_sdk_keeps_original_outcomes_and_evidence_contract(case, checked_role, authored_rules):
    cs, _, ws, request = configured(case)
    cs.store.set('manifest', {**cs.store.manifest, 'report_prompt_profile':'concise-v1',
        'report_expression_profile':'reader-expression-v2', 'operation_identity_profile':'native-tool-runtime-v1'})
    model_args = task_arguments(cs, case[1], request['args'])
    models, bodies = {}, {}
    def factory(role):
        if role in models:
            return models[role]
        client = model_async_client(ws.store, role)
        def transport(http_request):
            bodies.setdefault(role, []).append(json.loads(http_request.content))
            delegate = role == 'coordinator' and len(bodies[role]) == 1
            return completion(http_request, 'Synthetic transport only; no acceptance asserted.',
                              ('task', model_args) if delegate else None)
        client._transport = httpx.MockTransport(transport)
        client._mounts.clear()
        models[role] = GLMChatOpenAI(model='glm-5.3', api_key='fixture-only',
            base_url='https://fixture.invalid/v1', use_responses_api=False,
            http_async_client=client, max_retries=0, disable_streaming=True)
        return models[role]
    try:
        result = await run_report(ws, factory)
        assert result['last_error'] is None, result
        text = '\n'.join(m['content'] if isinstance(m['content'], str) else
            '\n'.join(block.get('text', '') for block in m['content'])
            for m in bodies[checked_role][0]['messages'] if m['role'] == 'system')
        assert text.startswith(load_prompt('agent-common') + '\n\n' + load_prompt('agent-' + checked_role))
        captures = [cs.store.get(e['data']['capture_key']) for e in cs.store.events()
                    if e['kind'] == 'prompt_final_http_input' and e['data']['purpose'] == checked_role]
        assert captures and all(c['status'] == 'exact' for c in captures)
        assert all(next(s['files'] for s in c['sources'] if s['source'] == 'configured_role_files') ==
                   ['agent-common', 'agent-' + checked_role] for c in captures)
        assert not cs.list_objects('ReviewRecord')
    finally:
        for model in models.values():
            await model.root_async_client.close()
            model.root_client.close()
