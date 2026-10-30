"""Current reviewed prose at the native boundary, with prior interfaces preserved."""
from copy import deepcopy
import json

import httpx
import pytest
from langchain_core.messages import HumanMessage

from report_agent.deep_runtime import build_agent
from report_agent.deep_models import GLMChatOpenAI, model_async_client
from report_agent.hierarchical_tools import role_prompt
from report_agent.prompt_sources import load_prompt
from report_agent.workspace import Workspace
from test_deliverable_declaration_v4 import case
from test_prompt_native_sdk_inputs import completion
from test_review_binding_v4 import prepared, review_call
from test_task_supervision import ws


@pytest.fixture(autouse=True)
def only_mock_transport(monkeypatch):
    monkeypatch.setenv('LANGSMITH_TRACING', 'false')
    def deny(*args, **kwargs):
        pytest.fail('Real network is forbidden in prompt regression')
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', deny)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, 'handle_async_request', deny)


@pytest.mark.parametrize('role,marker', [
    ('coordinator', 'Coordinate the commissioned report'),
    ('writer', 'Own the assigned report content'),
    ('reviewer', 'Own accurate evidence-based judgments'),
    ('layout', 'Improve readable presentation'),
])
def test_current_role_uses_reviewed_prose_without_changing_legacy_sources(role, marker):
    optimized = role_prompt(role, expression_profile='reader-expression-v2', interface_profile='review-interfaces-v4', prompt_profile='concise-v1')
    assert marker in optimized
    legacy = role_prompt(role, expression_profile='report-expression-v1', interface_profile='review-interfaces-v1')
    assert legacy == load_prompt('content-common') + '\n\n' + load_prompt('content-'+role)


async def test_final_current_sdk_tools_and_parameter_sources_are_optimized(case):
    cs, _, criteria, _ = prepared(case)
    cs.store.set('context_policy', 'stateful-tools-v2')
    cs.store.set('manifest', {**cs.store.manifest, 'report_expression_profile':'reader-expression-v2', 'report_prompt_profile':'concise-v1'})
    review = review_call(criteria)['args']
    models, wires = {}, []
    def factory(role):
        if role not in models:
            client = model_async_client(cs.store, role)
            def transport(request):
                body = json.loads(request.content)
                first = role == 'coordinator' and not any(r == role for r, _ in wires)
                wires.append((role, body))
                return completion(request, '', ('task', review)) if first else completion(
                    request, 'Offline interface fixture; no semantic acceptance claimed.')
            client._transport = httpx.MockTransport(transport)
            client._mounts.clear()
            models[role] = GLMChatOpenAI(model='glm-5.3', api_key='synthetic-only',
                base_url='https://fixture.invalid/v1', use_responses_api=False,
                http_async_client=client, max_retries=0, disable_streaming=True)
        return models[role]
    try:
        graph = build_agent(Workspace(cs.store), factory, None)
        cs.store.set('manifest', {**cs.store.manifest, 'report_prompt_profile':'legacy-v1'})
        await graph.ainvoke({'messages':[HumanMessage('Inspect the scoped fixture.')]})
        coordinator = next(body for role,body in wires if role=='coordinator')
        functions = {t['function']['name']:t['function'] for t in coordinator['tools']}
        assert 'runtime supplies' in functions['commit_objects']['description']
        assert 'operation_id' not in functions['commit_objects']['parameters']['properties']
        assert "['assignment'" not in functions['read_decision_state']['description']
        assert 'another role' in functions['read_decision_state']['description']
        serialized = json.dumps(functions['commit_objects']['parameters'], ensure_ascii=False)
        assert 'use labels and wording' in serialized
        assert '1-based physical PDF page' in serialized
        task = functions['task']
        assert 'Delegate an authorized objective' in task['description']
        assert 'check_results' not in task['description']
        assert set(task['parameters']['required']) >= {'description','subagent_type'}
        captures = [cs.store.get(e['data']['capture_key']) for e in cs.store.events()
                    if e['kind']=='prompt_final_http_input']
        actual = next(c for c in captures if c['purpose']=='coordinator')
        assert actual['public_input']['tools'] == coordinator['tools']
        for name in ('tool-commit-objects','tool-read-decision-state','content-qualifiers-description'):
            source = next(f for f in actual['source_manifest']['files'] if f['name']==name)
            assert source['offered_match'] in {'literal','trimmed_literal'}
            assert any(m['role']=='tool_definition' for m in source['matched_locations'])
        assert any(role=='reviewer' for role,_ in wires)
    finally:
        for model in models.values():
            await model.root_async_client.close()
            model.root_client.close()


def test_description_projection_preserves_named_description_parameter_and_schema_data():
    from report_agent.prompt_sources import describe_current_tools
    value = [{'type':'function','function':{'name':'commit_objects','description':'Original help',
        'parameters':{'type':'object','properties':{
            'description':{'type':'string','default':'Do not alter this task value'},
            'payload':{'type':'object','properties':{
                'kind':{'type':'string'},'body':{'type':'object','description':'body'},
                'claim_kind':{'type':'string'},'qualifiers':{'type':'object','description':'qualifiers'}},
                'default':{'kind':'block','body':{},'claim_kind':'fact','qualifiers':{'description':'data'}},
                'examples':[{'description':'keep this example'}]}},'required':['description']}}}]
    before = deepcopy(value)
    projected, sources = describe_current_tools(value)
    assert value == before
    p = projected[0]['function']['parameters']
    assert p['properties']['description'] == before[0]['function']['parameters']['properties']['description']
    assert p['properties']['payload']['default'] == before[0]['function']['parameters']['properties']['payload']['default']
    assert p['properties']['payload']['examples'] == [{'description':'keep this example'}]
    assert p['required'] == ['description']
    assert 'tool-commit-objects' in sources and 'content-qualifiers-description' in sources
    expected = deepcopy(before[0]['function']['parameters'])
    for field in ('body', 'qualifiers'):
        expected['properties']['payload']['properties'][field]['description'] = p['properties']['payload']['properties'][field]['description']
    assert p == expected


async def test_current_text_helper_schema_sources_reach_actual_sdk_request(ws):
    from report_agent.content_tasks import delegated_task
    from report_agent.content_models import ContentNode
    from report_agent.evidence_analysis import analyze_evidence_packet
    from report_agent.prompt_sources import describe_content_schema
    from test_hierarchical_content import seed
    from test_native_operation_identity import activate
    from test_text_work import writer_call
    seed(ws)
    activate(ws)
    ws.store.set('manifest', {**ws.store.manifest, 'review_interface_profile':'review-interfaces-v4',
        'review_execution_mode':'native-reviewer-v2', 'delegation_prompt_profile':'separate-description-v1',
        'report_expression_profile':'reader-expression-v2', 'report_prompt_profile':'concise-v1'})
    schema, _ = describe_content_schema(ContentNode.model_json_schema())
    client = model_async_client(ws.store, 'text_tool')
    wires = []
    def transport(request):
        wires.append(json.loads(request.content))
        return completion(request, 'Synthetic observation; not an acceptance result.')
    client._transport = httpx.MockTransport(transport)
    client._mounts.clear()
    model = GLMChatOpenAI(model='glm-5.3', api_key='synthetic-only', base_url='https://fixture.invalid/v1',
        use_responses_api=False, http_async_client=client, max_retries=0, disable_streaming=True)
    try:
        with delegated_task(ws, 'coordinator', writer_call()):
            await analyze_evidence_packet(ws, model, {'output_schema':schema, 'evidence':[]}, load_prompt('text-work-v2'), 'independent-text-tools-v1')
        capture = next(ws.store.get(e['data']['capture_key']) for e in ws.store.events() if e['kind']=='prompt_final_http_input')
        assert capture['public_input'] == wires[0]
        assert json.loads(wires[0]['messages'][1]['content'])['output_schema'] == schema
        for name in ('content-body-description', 'content-qualifiers-description'):
            source = next(f for f in capture['source_manifest']['files'] if f['name']==name)
            assert source['offered_match'] == 'literal'
            assert any(m['role']=='output_schema' for m in source['matched_locations'])
            assert name not in capture['source_manifest']['unresolved_sources']
    finally:
        await client.aclose()
        model.root_client.close()


@pytest.mark.parametrize('profile,interface,expression', [
    ('unknown-profile', 'review-interfaces-v4', 'reader-expression-v2'),
    ('concise-v1', 'review-interfaces-v3', 'reader-expression-v2'),
    ('concise-v1', 'review-interfaces-v4', 'report-expression-v1'),
])
def test_invalid_prompt_release_is_rejected_before_model_construction(case, profile, interface, expression):
    from report_agent.errors import ActionRejected
    cs = case[0]
    cs.store.set('manifest', {**cs.store.manifest, 'review_interface_profile':interface,
        'report_expression_profile':expression, 'report_prompt_profile':profile})
    def forbidden_factory(role):
        pytest.fail('Invalid prompt release must fail before constructing any model')
    with pytest.raises(ActionRejected, match='UNKNOWN_REPORT_PROMPT_PROFILE|CONCISE_PROMPTS_REQUIRE'):
        build_agent(Workspace(cs.store), forbidden_factory, None)


@pytest.mark.parametrize('contract', ['layout-owner', 'review-fields', 'excel-scope', 'state-path'])
def test_concise_help_preserves_real_ownership_and_submission_contract(contract):
    import re
    if contract == 'layout-owner':
        text = load_prompt('content-coordinator-v4-concise')
        assert 'grant it the exact frozen snapshot' in text
        assert 'Layout owns its new exports' in text
    elif contract == 'review-fields':
        from report_agent.content_tasks import native_review_submission_schema
        text = load_prompt('native-submit-review-v4-concise')
        schema = native_review_submission_schema(v4=True)
        for name in ('scope', 'snapshot_ref', 'criteria_refs', 'dependency_refs'):
            assert schema.model_fields[name].is_required()
            assert re.search(r'(?<!\w)'+name+r'(?!\w)', text)
        assert 'artifact_check_scopes' in text and 'type/id/version' in text
        assert 'assigned extent in artifact_refs' not in text
    elif contract == 'excel-scope':
        assert 'Excel layout/render' in load_prompt('native-submit-review-v4-concise')
    else:
        text = load_prompt('select-content-delivery-v4-concise')
        assert 'read_state_path' in text
        assert "['review_tasks','tasks',index" not in text
