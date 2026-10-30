"""Model-visible contracts and graph releases, without paid calls."""
from copy import deepcopy

import pytest
from langchain_core.runnables.config import var_child_runnable_config
from langchain_core.tools import StructuredTool

from report_agent.content_tasks import task_tool, delegated_task
from report_agent.errors import ActionRejected
from report_agent.workspace import Workspace
from test_deliverable_declaration_v4 import case
from test_review_binding_v4 import prepared, review_call, task_record


def test_v4_schema_exposes_three_choices_without_raw_version_manifest(case):
    def task(description: str, subagent_type: str) -> str:
        """Native delegation."""
        return description
    tool = task_tool(StructuredTool.from_function(task), review_profile='native-reviewer-v2',
                     interface_profile='review-interfaces-v4')
    schema = tool.args_schema.model_json_schema()
    assert 'review' in schema['properties']
    assert not {'review_requirements', 'review_snapshot_ref'} & schema['properties'].keys()
    assert set(schema['$defs']['ReviewSelection']['properties']) == {'deliverable','standards','scope'}
    assert 'scope_id' not in schema['$defs']['MappedItem']['properties']


def test_bound_graph_uses_its_release_and_commission_after_store_changes(case):
    from report_agent.handoff_release import release
    cs, output, criteria, _ = prepared(case)
    original = deepcopy(cs.store.manifest)
    bound = release(original)
    cs.store.set('manifest', {**original, 'goal': 'Different commission',
        'review_interface_profile': 'review-interfaces-v1', 'operation_identity_profile': 'caller-operation-v1'})
    token = var_child_runnable_config.set({'metadata': {'report_handoff_release': bound,
        'report_review_interface_profile': 'review-interfaces-v4',
        'report_operation_identity_profile': 'native-tool-runtime-v1'}})
    try:
        with delegated_task(Workspace(cs.store), 'coordinator', review_call(criteria[:1])) as (_, actor):
            assert task_record(cs, actor)['payload']['review_commission_basis']['commission_origin']['goal'] == original['goal']
    finally:
        var_child_runnable_config.reset(token)


def test_bound_release_rejects_conflicting_runtime_profile_before_registration(case):
    from report_agent.handoff_release import release
    cs, _, criteria, _ = prepared(case)
    token = var_child_runnable_config.set({'metadata': {'report_handoff_release': release(cs.store.manifest),
        'report_review_interface_profile': 'review-interfaces-v3'}})
    try:
        with pytest.raises(ActionRejected, match='HANDOFF_RELEASE_METADATA_MISMATCH'):
            with delegated_task(Workspace(cs.store), 'coordinator', review_call(criteria[:1])):
                pytest.fail('Conflicting graph release must never dispatch')
    finally:
        var_child_runnable_config.reset(token)


def test_v4_role_sources_remove_co_preparation_without_replacing_writer_body_rules(case):
    from report_agent.hierarchical_tools import role_prompt
    from report_agent.prompt_sources import load_prompt
    co = role_prompt('coordinator', interface_profile='review-interfaces-v4')
    assert 'For a reviewer task provide review_snapshot_ref and review_requirements' not in co
    assert 'review.deliverable' in co and 'review.standards' in co and 'review.scope' in co
    for expression in ['report-expression-v1', 'reader-expression-v2']:
        original = role_prompt('writer', expression_profile=expression)
        v4 = role_prompt('writer', expression_profile=expression, interface_profile='review-interfaces-v4')
        assert v4.startswith(original+'\n\n')
        assert load_prompt('deliverable-declaration-v4') in v4


async def test_registered_v4_graph_final_sdk_input_and_source_provenance(case):
    import json
    import httpx
    from pathlib import Path
    from langchain_core.messages import HumanMessage
    from report_agent.deep_runtime import build_agent
    from report_agent.deep_models import GLMChatOpenAI, model_async_client
    from test_prompt_native_sdk_inputs import completion
    cs = case[0]
    models, wires = {}, []
    def factory(role):
        if role not in models:
            client = model_async_client(cs.store, role)
            def transport(request):
                wires.append({'role':role, 'body':json.loads(request.content)})
                return completion(request, 'Synthetic wire observation only; no acceptance.')
            client._transport = httpx.MockTransport(transport)
            client._mounts.clear()
            models[role] = GLMChatOpenAI(model='glm-5.3', api_key='fixture-only',
                base_url='https://fixture.invalid/v1', use_responses_api=False,
                http_async_client=client, max_retries=0, disable_streaming=True)
        return models[role]
    try:
        agent = build_agent(Workspace(cs.store), factory, None)
        await agent.ainvoke({'messages':[HumanMessage('Observe the synthetic V4 interface only.')]})
        body = next(w['body'] for w in wires if w['role']=='coordinator')
        task = next(t['function'] for t in body['tools'] if t['function']['name']=='task')
        assert 'read_decision_state' in {t['function']['name'] for t in body['tools']}
        assert 'review' in task['parameters']['properties']
        assert 'review_requirements' not in task['parameters']['properties']
        assert 'For a reviewer task provide review_snapshot_ref and review_requirements' not in json.dumps(body)
        from report_agent.prompt_sources import load_prompt
        commit = next(t['function'] for t in body['tools'] if t['function']['name']=='commit_objects')
        assert load_prompt('deliverable-save-tool-v4').strip() in commit['description']
        captures = [cs.store.get(e['data']['capture_key']) for e in cs.store.events() if e['kind']=='prompt_final_http_input']
        assert captures and all(c['status']=='exact' for c in captures)
        sources = {f['name'] for c in captures for f in c['source_manifest']['files']}
        assert {'content-coordinator-v4','native-review-handoff-v4'} <= sources
        declaration_sources = [f for c in captures for f in c['source_manifest']['files'] if f['name']=='deliverable-save-tool-v4']
        assert declaration_sources and all(f['offered_match'] != 'not_observed' for f in declaration_sources)
        destination = case[0].store.root / 'effective-input-v4.json'
        destination.write_text(json.dumps({'synthetic_only':True, 'wire':body,
            'sources':[c['source_manifest'] for c in captures]},ensure_ascii=False,indent=2), encoding='utf-8')
    finally:
        for model in models.values():
            await model.root_async_client.close()
            model.root_client.close()
