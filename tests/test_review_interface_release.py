"""Explicit metadata release; no migration or weakening of historical wire tests."""
from copy import deepcopy
import json

import httpx
import pytest
from langchain_core.messages import HumanMessage

from report_agent import deep_runtime
from report_agent.deep_models import GLMChatOpenAI, model_async_client
from report_agent.errors import ActionRejected
from test_deep_runtime import Driver
from test_hierarchical_content import ws, seed
from test_prompt_native_sdk_inputs import completion
from test_reviewer_native_profile import native

V1, V2 = 'review-interfaces-v1', 'review-interfaces-v2'


@pytest.mark.parametrize('value,mode,entry,contract', [
    ('unknown', 'native-reviewer-v2', 'delegated-reviewer-v1', 'hierarchical-review-v1'),
    (None, 'native-reviewer-v2', 'delegated-reviewer-v1', 'hierarchical-review-v1'),
    (V2, 'bounded-tool-v1', 'delegated-reviewer-v1', 'hierarchical-review-v1'),
    (V2, 'native-reviewer-v2', 'native-rubric-v1', 'hierarchical-review-v1'),
    (V2, 'native-reviewer-v2', 'delegated-reviewer-v1', 'other-contract'),
])
def test_invalid_review_interface_rejected_before_model_or_manifest_write(ws, value, mode, entry, contract):
    native(ws)
    before = {**ws.store.manifest, 'review_interface_profile': value,
              'review_execution_mode': mode, 'review_entrypoint': entry, 'content_contract': contract}
    ws.store.set('manifest', before)
    driver = Driver()
    with pytest.raises(ActionRejected, match='REVIEW_INTERFACE_PROFILE'):
        deep_runtime.build_agent(ws, driver, None)
    assert driver.created == []
    assert ws.store.manifest == before


async def test_two_constructed_graphs_keep_their_own_review_interface_and_provenance(ws):
    native(ws)
    seed(ws)
    ws.store.set('manifest', {**ws.store.manifest, 'delegation_prompt_profile': 'separate-description-v1',
                             'review_interface_profile': V1})
    wires, models = [], {}

    def factory(role):
        if role in models:
            return models[role]
        client = model_async_client(ws.store, role)

        def transport(request):
            wires.append((role, json.loads(request.content)))
            return completion(request, 'Unaccepted synthetic observation only.')

        client._transport = httpx.MockTransport(transport)
        client._mounts.clear()
        models[role] = GLMChatOpenAI(model='glm-5.3', api_key='fixture-only',
            base_url='https://fixture.invalid/v1', use_responses_api=False,
            http_async_client=client, max_retries=0, disable_streaming=True)
        return models[role]

    try:
        first = deep_runtime.build_agent(ws, factory, None)
        ws.store.set('manifest', {**ws.store.manifest, 'review_interface_profile': V2})
        second = deep_runtime.build_agent(ws, factory, None)
        # Later mutable Store configuration must not relabel either built graph.
        ws.store.set('manifest', {**ws.store.manifest, 'review_interface_profile': V1})
        for graph in [first, second]:
            await graph.ainvoke({'messages': [HumanMessage('Observe this synthetic interface.')]})
        co = [body for role, body in wires if role == 'coordinator']
        assert len(co) == 2
        tasks = [next(t['function'] for t in body['tools'] if t['function']['name'] == 'task') for body in co]
        before = tasks[0]['parameters']['properties']['review_requirements']['anyOf'][0]['items']['properties']['target_ref']
        after = tasks[1]['parameters']['properties']['review_requirements']['anyOf'][0]['items']['properties']['target_ref']
        assert 'description' not in before
        assert 'artifact_refs' in after['description']
        captures = [ws.store.get(e['data']['capture_key']) for e in ws.store.events()
                    if e['kind'] == 'prompt_final_http_input']
        sources = [{f['name'] for f in c['source_manifest']['files']} for c in captures]
        assert 'native-review-handoff' in sources[0] and 'native-review-handoff-v2' not in sources[0]
        assert 'native-review-handoff-v2' in sources[1] and 'native-review-handoff' not in sources[1]
        assert all(c['status'] == 'exact' for c in captures)
    finally:
        for model in models.values():
            await model.root_async_client.close()
            model.root_client.close()


@pytest.mark.parametrize('profile', ['unknown', None, 42, {}, []])
def test_cli_rejects_invalid_interface_before_manifest_initialization(tmp_path, monkeypatch, profile):
    from report_agent.cli import main
    from report_agent.store import Store
    manifest = tmp_path / 'input.json'
    manifest.write_text(json.dumps({'goal': 'Synthetic init only', 'sources': [
        {'id': 's', 'title': 'Fixture', 'content': 'Supplied fixture text.', 'coverage': 'complete'}],
                                    'review_interface_profile': profile}))
    root = tmp_path / 'new-case'
    monkeypatch.setattr('sys.argv', ['report-agent', 'init', '--project', str(root), '--manifest', str(manifest)])
    with pytest.raises(ActionRejected, match='REVIEW_INTERFACE_PROFILE'):
        main()
    assert Store(root).get('manifest') is None


def test_reinitialization_preserves_explicit_interface_without_migrating_absent_release(tmp_path, monkeypatch, capsys):
    from report_agent.cli import main
    from report_agent.store import Store
    for selected in [None, V2]:
        root = tmp_path / ('explicit' if selected else 'old-default')
        manifest = tmp_path / ('explicit.json' if selected else 'old.json')
        data = {'goal': 'Synthetic native initialization', 'sources': [
            {'id': 's', 'title': 'Fixture', 'content': 'Supplied fixture text.', 'coverage': 'complete'}]}
        if selected:
            data['review_interface_profile'] = selected
        manifest.write_text(json.dumps(data))
        monkeypatch.setattr('sys.argv', ['report-agent', 'init', '--project', str(root), '--manifest', str(manifest)])
        assert main() == 0
        before = Store(root).manifest
        data.pop('review_interface_profile', None)
        manifest.write_text(json.dumps(data))
        assert main() == 0
        assert Store(root).manifest == before
        assert before.get('review_interface_profile') == selected
    capsys.readouterr()


def test_v2_changes_only_task_documentation_and_preserves_all_original_contracts(ws):
    from langchain_core.utils.function_calling import convert_to_openai_tool
    from report_agent.content_tasks import task_tool
    from report_agent.prompt_sources import NATIVE_REVIEW
    from test_native_task_error_boundary import registered_task
    from test_native_review_handoff import handoff
    native(ws)
    _, _, refs, snapshot, _ = seed(ws)
    tools = [task_tool(registered_task(), review_profile=NATIVE_REVIEW, interface_profile=p) for p in [V1, V2]]

    def structural(value):
        if isinstance(value, dict):
            return {k: structural(v) for k, v in value.items() if k not in {'description', 'title'}}
        return [structural(v) for v in value] if isinstance(value, list) else value

    assert structural(convert_to_openai_tool(tools[0])) == structural(convert_to_openai_tool(tools[1]))
    args = handoff(snapshot, refs)
    assert tools[0].tool_call_schema.model_validate(args).model_dump() == tools[1].tool_call_schema.model_validate(args).model_dump()
    bad = deepcopy(args)
    bad['review_requirements'][0]['required_materials'] = [
        {'requirement_index': 999, 'purpose': 'Invalid outside check', 'refs': [refs['claim']]}]
    for tool in tools:
        with pytest.raises(ValueError, match='REQUIRED_MATERIAL_CHECK_OUTSIDE_ASSIGNMENT'):
            tool.tool_call_schema.model_validate(bad)
