from support.flat_task_fixture import task_arguments
"""Real native graph and SDK encoding with synthetic transport, no paid model."""
import json
from collections import Counter
from pathlib import Path
import httpx
import pytest
from report_agent.deep_runtime import run_report
from report_agent.deep_models import GLMChatOpenAI, model_async_client
from report_agent.prompt_sources import load_prompt
from test_review_work_units import configured, unit_todo
from test_deliverable_declaration_v4 import case
from test_prompt_native_sdk_inputs import completion


@pytest.mark.parametrize('enabled', [False, True])
async def test_sdk_reviewer_plan_schema_prompt_and_declared_sources(case, enabled):
    cs, output, ws, request = configured(case)
    manifest = {**cs.store.manifest, 'report_prompt_profile': 'concise-v1',
                'report_expression_profile': 'reader-expression-v2',
                'operation_identity_profile': 'native-tool-runtime-v1'}
    if not enabled:
        manifest.pop('review_plan_contract')
    ws.store.set('manifest', manifest)
    model_args = task_arguments(cs, case[1], request['args'])
    models, bodies, counts = {}, {}, Counter()
    todo = unit_todo(output['refs']['a-body'])
    def factory(role):
        if role in models:
            return models[role]
        client = model_async_client(ws.store, role)
        def transport(request_http):
            body = json.loads(request_http.content)
            bodies.setdefault(role, []).append(body)
            step = counts[role]; counts[role] += 1
            if role == 'coordinator':
                return completion(request_http, 'Synthetic end.', ('task', model_args) if step == 0 else None)
            if step == 0:
                return completion(request_http, '', ('write_todos', {'todos': [todo] if enabled else [
                    {'content':'Read synthetic assignment.', 'status':'pending'}]}))
            return completion(request_http, 'Intentions saved; no completed review claimed.')
        client._transport = httpx.MockTransport(transport); client._mounts.clear()
        models[role] = GLMChatOpenAI(model='glm-5.3', api_key='fixture-only',
            base_url='https://fixture.invalid/v1', use_responses_api=False,
            http_async_client=client, max_retries=0, disable_streaming=True)
        return models[role]
    try:
        result = await run_report(ws, factory)
        assert result['last_error'] is None, result
        assert len(bodies['reviewer']) == 2
        first = bodies['reviewer'][0]
        offered = next(t['function'] for t in first['tools'] if t['function']['name'] == 'write_todos')
        schema_text = json.dumps(offered['parameters'])
        assert ('review_unit' in schema_text) is enabled
        assert '_binding' not in schema_text
        if enabled:
            assert offered['description'].startswith("Replace this task's native todo list with the complete plan;")
            assert offered['description'] == load_prompt('review-work-units-tool').strip()
            system = '\n'.join(m['content'] if isinstance(m['content'],str) else '\n'.join(b.get('text','') for b in m['content']) for m in first['messages'] if m['role'] == 'system')
            assert load_prompt('review-work-units').strip() in system
            assert todo['review_unit']['method'] in json.dumps(bodies['reviewer'][1], ensure_ascii=False)
        else:
            from langchain.agents.middleware.todo import WRITE_TODOS_TOOL_DESCRIPTION
            assert offered['description'] == WRITE_TODOS_TOOL_DESCRIPTION
            assert ws.store.get('review_plan_contract_binding') is None
        captures = [ws.store.get(e['data']['capture_key']) for e in ws.store.events()
                    if e['kind'] == 'prompt_final_http_input']
        reviewer = [c for c in captures if c['purpose'] == 'reviewer']
        assert len(reviewer) == 2
        for capture in reviewer:
            assert capture['expected_wire_available']
            assert capture['status'] != 'unexplained', capture['sources']
            names = {f['name']:f for f in capture['source_manifest']['files']}
            for name in ('review-work-units', 'review-work-units-tool'):
                assert (name in names) is enabled
                if enabled:
                    assert names[name]['offered_match'] != 'not_observed'
        assert not cs.list_objects('ReviewRecord')
    finally:
        for model in models.values():
            await model.root_async_client.close()
            model.root_client.close()
