"""Reviewed prompt release, actual native SDK interface and explicit compatibility.

Offline scripted replies exercise transport/delegation, not autonomous decisions
or engineering correctness. Existing tests remain unchanged.
"""
import json
import hashlib
from collections import Counter
from pathlib import Path

import httpx
import pytest
from langchain_core.messages import AIMessage

from report_agent import deep_runtime
from report_agent.deep_models import GLMChatOpenAI, model_async_client
from report_agent.errors import ActionRejected
from report_agent.hierarchical_tools import role_prompt
from report_agent.prompt_sources import load_prompt
from test_hierarchical_content import ws, seed
from test_reviewer_native_profile import native, commission
from test_deep_runtime import Driver
from test_prompt_native_sdk_inputs import completion

NEW = 'separate-description-v1'
OLD = 'full-role-description-v1'
DESCRIPTIONS = {
    'writer': 'Creates and revises the assigned versioned report content using authorized requirements and sources. Owns its content and returns saved versions, supporting references, limitations and remaining work. Use for authorship and revisions; independent review is Reviewer work.',
    'reviewer': 'Independently assesses assigned deliverable versions against acceptance criteria. Chooses and performs verification, finds authorized evidence, checks conclusions and missing outcomes, and saves scoped judgments with their evidence and remaining work. Does not rewrite report content, change acceptance criteria, or decide overall project continuation.',
    'layout': 'Improves the presentation of an assigned immutable report snapshot when layout work is useful. Uses available export and rendering capabilities to inspect readability and returns exact artifact versions and limitations. Report content, criteria, reviews and final delivery selection remain outside its ownership.',
}
LEGACY = json.loads((Path(__file__).parent/'fixtures/delegation-prompt-full-role-v1.json').read_text(encoding='utf-8'))


def profile(ws, value):
    manifest = ws.store.manifest
    if value is None:
        manifest.pop('delegation_prompt_profile', None)
    else:
        manifest['delegation_prompt_profile'] = value
    ws.store.set('manifest', manifest)


async def sdk_run(ws, role, release):
    native(ws)
    profile(ws, release)
    _, _, refs, snapshot, _ = seed(ws)
    task = commission(snapshot, refs) if role == 'reviewer' else {
        'subagent_type':role, 'description':'Inspect assigned synthetic work; preserve actual limitations.'}
    if role == 'layout':
        task['layout_snapshot_ref'] = snapshot
    models, steps, wires = {}, Counter(), []
    def factory(selected):
        if selected in models:
            return models[selected]
        client = model_async_client(ws.store, selected)
        def transport(request):
            body = json.loads(request.content)
            wires.append((selected, body))
            step = steps[selected]
            steps[selected] += 1
            if selected == 'coordinator' and step == 0:
                return completion(request, '', ('task', task))
            return completion(request, 'Actual assigned work remains unaccepted; fixture only.')
        client._transport = httpx.MockTransport(transport)
        client._mounts.clear()
        models[selected] = GLMChatOpenAI(model='glm-5.3', api_key='fixture-only',
            base_url='https://fixture.invalid/v1', use_responses_api=False,
            http_async_client=client, max_retries=0, disable_streaming=True)
        return models[selected]
    try:
        result = await deep_runtime.run_report(ws, factory)
        assert result['last_error'] is None, result
        return wires
    finally:
        for model in models.values():
            await model.root_async_client.close()
            model.root_client.close()


def system(body):
    return '\n'.join(m['content'] if isinstance(m['content'], str) else
        '\n'.join(b.get('text', '') for b in m['content']) for m in body['messages'] if m['role'] == 'system')


@pytest.mark.parametrize('role', ['writer', 'reviewer', 'layout'])
async def test_new_release_has_short_co_description_and_unchanged_child_system(ws, role):
    wires = await sdk_run(ws, role, NEW)
    coordinator = next(body for selected, body in wires if selected == 'coordinator')
    task = next(t['function'] for t in coordinator['tools'] if t['function']['name'] == 'task')
    for selected, expected in DESCRIPTIONS.items():
        assert expected in task['description']
        assert role_prompt(selected) not in task['description']
        assert load_prompt('content-' + selected) not in task['description']
        assert load_prompt('content-' + selected + '-description') == expected + '\n'
    assert load_prompt('native-review-handoff').strip() in task['description']
    assert role_prompt('coordinator') in system(coordinator)
    assert [m for m in coordinator['messages'] if m['role'] == 'system'] == LEGACY['system_messages']
    old_task = next(t['function'] for t in LEGACY['tools'] if t['function']['name'] == 'task')
    assert {**task, 'description':old_task['description']} == old_task
    assert [t for t in coordinator['tools'] if t['function']['name'] != 'task'] == [
        t for t in LEGACY['tools'] if t['function']['name'] != 'task']
    child = next(body for selected, body in wires if selected == role)
    context = 'agent-context-reviewer' if role == 'reviewer' else 'agent-context-general'
    assert system(child).startswith(role_prompt(role) + '\n' + load_prompt(context))
    assert DESCRIPTIONS[role] not in system(child)
    names = {t['function']['name'] for t in child['tools']}
    assert 'task' not in names
    if role == 'reviewer':
        assert {'submit_review','read_context','read_source_page','read_content_index','write_todos'} <= names
        assert not {'commit_objects','save_text_node','select_content_delivery'} & names
    else:
        assert 'submit_review' not in names and 'select_content_delivery' not in names
    captures = [ws.store.get(e['data']['capture_key']) for e in ws.store.events()
        if e['kind'] == 'prompt_final_http_input']
    co_capture = next(c for c in captures if c['purpose'] == 'coordinator')
    assert all(c['status'] == 'exact' for c in captures)
    files = {f['name']:f for f in co_capture['source_manifest']['files']}
    for selected in DESCRIPTIONS:
        entry = files['content-' + selected + '-description']
        assert any(m['role'] == 'tool_definition' for m in entry['matched_locations'])
    registered = next(s for s in co_capture['sources'] if s['source'] == 'native_registered_tools')
    assert not {'content-common','content-writer','content-reviewer','content-layout'} & set(registered['files'])
    assert not any(m['role'] == 'tool_definition' for m in files['content-common']['matched_locations'])
    offered = next(ws.store.get(e['data']['capture_key']) for e in ws.store.events()
        if e['kind'] == 'prompt_model_input' and e['data']['call_id'] == co_capture['call_id'])
    assert offered['public_input']['delegation_prompt_profile'] == NEW
    assert offered['source_manifest'] == co_capture['source_manifest']


@pytest.mark.parametrize('release', [None, OLD])
async def test_old_release_keeps_full_role_descriptions_and_does_not_migrate(ws, release):
    native(ws)
    profile(ws, release)
    before = ws.store.manifest
    wires = await sdk_run(ws, 'writer', release)
    task = next(t['function'] for selected, body in wires if selected == 'coordinator'
        for t in body['tools'] if t['function']['name'] == 'task')
    for role in DESCRIPTIONS:
        assert role_prompt(role) in task['description']
    co = next(body for selected, body in wires if selected == 'coordinator')
    assert co['tools'] == LEGACY['tools']
    assert [m for m in co['messages'] if m['role'] == 'system'] == LEGACY['system_messages']
    capture = next(ws.store.get(e['data']['capture_key']) for e in ws.store.events()
        if e['kind'] == 'prompt_final_http_input' and e['data']['purpose'] == 'coordinator')
    files = {f['name']:f for f in capture['source_manifest']['files']}
    assert not any('description' in name for name in files)
    for name in ('content-common','content-writer','content-reviewer','content-layout'):
        assert any(m['role'] == 'tool_definition' for m in files[name]['matched_locations'])
    assert ws.store.manifest == before


@pytest.mark.parametrize('release', ['unknown-prompt-release', None, 42, '', {}])
def test_invalid_explicit_release_rejected_before_model_factory(ws, release):
    native(ws)
    ws.store.set('manifest', {**ws.store.manifest, 'delegation_prompt_profile':release})
    driver = Driver(coordinator=[AIMessage(content='Must not run.')])
    with pytest.raises(ActionRejected, match='DELEGATION_PROMPT_PROFILE'):
        deep_runtime.build_agent(ws, driver, None)
    assert driver.created == []


def test_new_release_cannot_relabel_bounded_review_as_native(ws):
    native(ws)
    ws.store.set('manifest', {**ws.store.manifest, 'review_execution_mode':'bounded-tool-v1',
        'delegation_prompt_profile':NEW})
    driver = Driver(coordinator=[AIMessage(content='Must not run.')])
    with pytest.raises(ActionRejected, match='DELEGATION_PROMPT_PROFILE'):
        deep_runtime.build_agent(ws, driver, None)
    assert driver.created == []


async def test_new_release_still_submits_real_review_through_existing_sdk_contract(ws):
    from test_prompt_native_sdk_inputs import test_actual_native_reviewer_wire_contains_configured_role_schema_and_saved_result
    profile(ws, NEW)
    await test_actual_native_reviewer_wire_contains_configured_role_schema_and_saved_result(ws)


async def test_new_release_sparse_handoff_preserves_all_seven_original_checks(ws):
    from test_native_review_handoff import test_sparse_native_handoff_reaches_reviewer_with_all_seven_checks_without_co_reads
    profile(ws, NEW)
    await test_sparse_native_handoff_reaches_reviewer_with_all_seven_checks_without_co_reads(ws)


@pytest.mark.parametrize('explicit', [None, OLD])
def test_cli_new_native_default_and_repeated_init_are_stable(tmp_path, monkeypatch, capsys, explicit):
    from report_agent.cli import main
    from report_agent.store import Store
    manifest = {'goal':'Synthetic native init', 'sources':[{
        'id':'s','title':'Fixture','content':'Fixture source.','coverage':'complete'}]}
    if explicit:
        manifest['delegation_prompt_profile'] = explicit
    path = tmp_path/'manifest.json'
    path.write_text(json.dumps(manifest))
    root = tmp_path/'project'
    monkeypatch.setattr('sys.argv', ['report-agent','init','--project',str(root),'--manifest',str(path)])
    assert main() == 0
    assert Store(root).manifest['delegation_prompt_profile'] == (explicit or NEW)
    before = Store(root).manifest
    assert main() == 0
    assert Store(root).manifest == before
    capsys.readouterr()


def test_cli_reinit_preexisting_native_without_prompt_release_does_not_add_one(tmp_path, monkeypatch, capsys):
    from report_agent.cli import main
    from report_agent.store import Store
    from report_agent.workspace import Workspace
    manifest = {'goal':'Old native case', 'content_contract':'hierarchical-review-v1',
        'review_entrypoint':'delegated-reviewer-v1', 'review_execution_mode':'native-reviewer-v2',
        'context_policy':'stateful-tools-v1','decision_data_policy':'reference-data-v1',
        'sources':[{'id':'s','title':'Fixture','content':'Fixture source.','coverage':'complete'}]}
    root = tmp_path/'project'
    store = Store(root)
    store.initialize(manifest)
    Workspace(store).initialize()
    path = tmp_path/'manifest.json'
    path.write_text(json.dumps(manifest))
    monkeypatch.setattr('sys.argv', ['report-agent','init','--project',str(root),'--manifest',str(path)])
    assert main() == 0
    assert Store(root).manifest == manifest
    capsys.readouterr()


def test_cli_new_bounded_case_does_not_inherit_native_description_release(tmp_path, monkeypatch, capsys):
    from report_agent.cli import main
    from report_agent.store import Store
    manifest = {'goal':'Synthetic explicit bounded init', 'review_execution_mode':'bounded-tool-v1',
        'sources':[{'id':'s','title':'Fixture','content':'Fixture source.','coverage':'complete'}]}
    path = tmp_path/'manifest.json'
    path.write_text(json.dumps(manifest))
    root = tmp_path/'project'
    monkeypatch.setattr('sys.argv', ['report-agent','init','--project',str(root),'--manifest',str(path)])
    assert main() == 0
    assert 'delegation_prompt_profile' not in Store(root).manifest
    capsys.readouterr()


@pytest.mark.parametrize('overrides', [
    {'review_execution_mode':'bounded-tool-v1'},
    {'review_entrypoint':'native-rubric-v1'},
    {'content_contract':'unsupported-contract'},
    {'delegation_prompt_profile':'unknown-release'},
])
def test_cli_invalid_new_release_is_rejected_before_manifest_creation(tmp_path, monkeypatch, overrides):
    from report_agent.cli import main
    from report_agent.store import Store
    manifest = {'goal':'Invalid synthetic combination', 'delegation_prompt_profile':NEW, **overrides,
        'sources':[{'id':'s','title':'Fixture','content':'Fixture source.','coverage':'complete'}]}
    path = tmp_path/'manifest.json'
    path.write_text(json.dumps(manifest))
    root = tmp_path/'project'
    monkeypatch.setattr('sys.argv', ['report-agent','init','--project',str(root),'--manifest',str(path)])
    with pytest.raises(ActionRejected, match='DELEGATION_PROMPT_PROFILE'):
        main()
    assert Store(root).get('manifest') is None


def test_all_existing_execution_guidance_keeps_phase2_before_text_bytes():
    before = {
        'content-common':'6401150614c2510cd343f246db9bb12a80ec2f1accbca45cad1f09b66a22c8c3',
        'content-coordinator':'0116450f609d1905ab296f880fc8c8b0ca398c4b5d28af19b0c9121b4f9ce81b',
        'content-writer':'de687b2ecc44da9a9e5630dff20d6eb7bee7345b6a17378bb50c6b86e0b433e0',
        'content-reviewer':'27bbdd1ecd076272a7d9df6289861e233c9a5b6e2645f9b647fe076679e1fafa',
        'content-layout':'73244c7da14b0a67d698c3901b7c180fb2d6e9d88287c5561daa26752ff049a0',
        'text-work':'0de421b8c4ab0473639d522dc8dff1529a2df72c9588536dbbf4fab84909fab0',
        'native-review-handoff':'9864fa3fe729ae3d7ca11f52602f17d68593f77f84bef75264d55c42cb97d916',
        'agent-context-general':'22c4afada4c0d8326bd2c3961c41116d5ec063ad884cc3632aef7aea387d9f8a',
        'agent-context-reviewer':'d0562928db426f4ff822c0ee0fe6a91a276b95f11ba03ea27162798bba5e66a4',
    }
    for name, sha in before.items():
        assert hashlib.sha256(load_prompt(name).encode()).hexdigest() == sha


@pytest.mark.parametrize('entrypoint', [None, 'unknown-delegated-entrypoint', 'native-rubric-v1'])
def test_new_description_release_requires_the_explicit_supported_entrypoint(ws, entrypoint):
    native(ws)
    ws.store.set('manifest', {**ws.store.manifest, 'review_entrypoint':entrypoint,
        'delegation_prompt_profile':NEW})
    driver = Driver(coordinator=[AIMessage(content='Must not run.')])
    with pytest.raises(ActionRejected, match='DELEGATION_PROMPT_PROFILE'):
        deep_runtime.build_agent(ws, driver, None)
    assert driver.created == []


async def test_prompt_release_audit_follows_each_native_graph_not_the_latest_manifest(ws):
    native(ws)
    graphs = []
    for release in (OLD, NEW):
        profile(ws, release)
        driver = Driver(coordinator=[AIMessage(content='Independent synthetic observation.')])
        graphs.append(deep_runtime.build_agent(ws, driver, None))
    for graph in graphs:
        await graph.ainvoke({'messages':[{'role':'user','content':'Inspect fixture only.'}]})
    captures = [ws.store.get(e['data']['capture_key']) for e in ws.store.events()
        if e['kind'] == 'prompt_model_input']
    assert [v['public_input']['delegation_prompt_profile'] for v in captures] == [OLD, NEW]
    old_sources = next(s['files'] for s in captures[0]['sources'] if s['source'] == 'native_registered_tools')
    new_sources = next(s['files'] for s in captures[1]['sources'] if s['source'] == 'native_registered_tools')
    assert 'content-reviewer' in old_sources and 'content-reviewer-description' not in old_sources
    assert 'content-reviewer-description' in new_sources and 'content-reviewer' not in new_sources
