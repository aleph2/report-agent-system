"""No-plan reviewer SDK wire and real saved scoped partial, mock model only."""
from collections import Counter
import json

import httpx
import pytest
from report_agent.deep_runtime import run_report
from report_agent.deep_models import GLMChatOpenAI, model_async_client
from test_deliverable_declaration_v4 import case
from test_review_work_units import configured
from test_prompt_native_sdk_inputs import completion
from test_review_scope_selectors import CONTRACT


@pytest.mark.parametrize('with_todo', [False, True])
async def test_optional_reviewer_reads_and_saves_without_a_plan(case, with_todo):
    cs, output, ws, task_call = configured(case)
    manifest = {**cs.store.manifest, 'review_plan_contract':'optional-v1',
        'history_projection_profile':'exact-history-v1', 'review_submission_contract':CONTRACT, 'report_prompt_profile':'concise-v1',
        'report_expression_profile':'reader-expression-v2', 'operation_identity_profile':'native-tool-runtime-v1'}
    ws.store.set('manifest', manifest)
    models, wires, counts, emitted = {}, {}, Counter(), []
    def factory(role):
        if role in models: return models[role]
        client = model_async_client(ws.store, role)
        def transport(http_request):
            body = json.loads(http_request.content)
            wires.setdefault(role, []).append(body)
            step = counts[role]
            counts[role] += 1
            text, tool = 'Scoped partial and its gaps retained.', None
            if role == 'coordinator' and step == 0:
                tool = ('task', task_call['args'])
            elif role == 'reviewer' and with_todo and step == 0:
                tool = ('write_todos', {'todos':[{'content':'Optional note','status':'pending'}]})
            elif role == 'reviewer' and step == int(with_todo):
                tool = ('read_context', {'target_ref':output['refs']['a']})
            elif role == 'reviewer' and step == 1 + int(with_todo):
                tool = ('read_context', {'target_ref':output['refs']['a-body']})
            elif role == 'reviewer' and step == 2 + int(with_todo):
                task = [t for t in cs.list_objects('DelegatedTask') if t['payload'].get('role') == 'reviewer'][-1]['payload']
                requirement = task['review_requirements'][0]
                observations = []
                for message in body['messages']:
                    if message['role'] != 'tool': continue
                    try: reply = json.loads(message['content'])
                    except (ValueError, TypeError): continue
                    if isinstance(reply, dict) and reply.get('receipt_id'):
                        observations.append({'receipt_id':reply['receipt_id'], 'locator':'Exact fixture object',
                                             'observation':'Read object; original support remains to be compared.'})
                assert len(observations) == 2
                item = {'scope':'Partial comparison','execution_state':'running','verdict':None,
                    'observations':observations,'checked_requirement_indexes':[],
                    'check_results':[{'requirement_index':0,'execution_state':'partial',
                        'result':'Read saved text; support comparison remains.','observation_indexes':[0,1],
                        'remaining':'Compare original support before conclusion.'}],
                    'coverage':{'checked':[],'unchecked':requirement['required_checks'],'blocked':[],
                                'basis':'Actual reads do not complete independent verification.'},
                    'reason':'Real partial check, not acceptance.','assigned_scope_index':0}
                value = {'target_ref':requirement['target_ref'],'snapshot_ref':task['review_snapshot_ref'],
                    'scope':'Partial assigned comparison','criteria_refs':[requirement['criterion_ref']],
                    'dependency_refs':[],'items':[item]}
                tool = ('submit_review', {'review':value})
            if tool: emitted.append((role, tool[0]))
            response = completion(http_request,text,tool)
            payload = response.json()
            if tool: payload['choices'][0]['message']['tool_calls'][0]['id'] = f'fixture-{role}-{step}-{tool[0]}'
            return httpx.Response(200,json=payload)
        client._transport = httpx.MockTransport(transport)
        client._mounts.clear()
        models[role] = GLMChatOpenAI(model='glm-5.3',api_key='fixture-only',base_url='https://fixture.invalid/v1',
            use_responses_api=False,http_async_client=client,max_retries=0,disable_streaming=True)
        return models[role]
    try:
        result = await run_report(ws, factory)
        assert result['last_error'] is None, result
        reviewer = wires['reviewer']
        assert len(reviewer) == 4 + int(with_todo)
        reviewer_calls = [name for role, name in emitted if role == 'reviewer']
        assert reviewer_calls == (['write_todos'] if with_todo else []) + ['read_context','read_context','submit_review']
        system = json.dumps([m['content'] for m in reviewer[0]['messages'] if m['role']=='system'])
        assert 'before substantive verification' not in system
        assert 'Choose whether to plan' in system
        assert 'Use this tool for complex objectives' not in system
        assert 'You may use write_todos' in system
        record, = cs.list_objects('ReviewRecord')
        item = record['payload']['items'][0]
        assert item['execution_state'] == 'running' and item['verdict'] is None
        assert item['coverage']['unchecked'] and len(item['observations']) == 2
        captures = [ws.store.get(e['data']['capture_key']) for e in ws.store.events()
                    if e['kind'] == 'prompt_final_http_input']
        for captured in [c for c in captures if c['purpose'] == 'reviewer']:
            assert captured['status'] == 'exact', captured['sources']
            names = {f['name']:f['offered_match'] for f in captured['source_manifest']['files']}
            assert names['content-reviewer-v4'] == 'derived_optional_plan'
            assert names['review-basis-v4-concise'] == 'derived_optional_plan'
            assert names['reviewer-optional-plan'] == 'literal'
            assert names['review-basis-optional-plan'] == 'literal'
            assert names['reviewer-optional-todo'] in {'literal', 'trimmed_literal'}
    finally:
        for model in models.values():
            await model.root_async_client.close()
            model.root_client.close()
