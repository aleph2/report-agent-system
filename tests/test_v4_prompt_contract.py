from report_agent.co_review_message import CoTaskMessage
"""V4 final prompt and provenance regressions. Offline protocol, not autonomy."""
from copy import deepcopy
import json
from pathlib import Path

import httpx
import pytest
from langchain_core.messages import HumanMessage
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from report_agent.content_tasks import task_tool
from report_agent.prompt_sources import load_prompt, source_manifest
from test_deliverable_declaration_v4 import case
from test_review_binding_v4 import prepared, review_call


@pytest.mark.parametrize('branch', ['properties', '$defs', 'anyOf', 'items'])
def test_configured_parameter_source_has_exact_nested_location(tmp_path, monkeypatch, branch):
    from report_agent import prompt_sources
    note = 'Independent task objective; saved assignment supplies the versioned basis.'
    (tmp_path/'parameter-note.md').write_text(note+'\n', encoding='utf-8')
    monkeypatch.setattr(prompt_sources, 'RULES', tmp_path)
    leaf = {'type': 'string', 'description': note}
    node = {branch: {'entry': leaf}} if branch in {'properties', '$defs'} else {branch: [leaf]} if branch == 'anyOf' else {branch: leaf}
    offered = {'messages': [], 'tools': [{'function': {'name': 'task', 'description': 'Delegate.', 'parameters': node}}]}
    before = deepcopy(offered)
    manifest = source_manifest(None, ['parameter-note'], offered)
    entry, = manifest['files']
    assert entry['offered_match'] == 'trimmed_literal'
    assert not manifest['unresolved_sources']
    location, = entry['matched_locations']
    assert location['role'] == 'tool_definition'
    assert location['path'].startswith('tools/0/function/parameters/'+branch+'/')
    assert location['path'].endswith('/description')
    assert offered == before


def test_user_quote_and_schema_examples_cannot_claim_parameter_source(tmp_path, monkeypatch):
    from report_agent import prompt_sources
    note = 'This configured instruction is not actually installed.'
    (tmp_path/'parameter-note.md').write_text(note, encoding='utf-8')
    monkeypatch.setattr(prompt_sources, 'RULES', tmp_path)
    offered = {'messages': [{'role': 'user', 'content': note}], 'tools': [{'function': {
        'name': 'task', 'parameters': {'type': 'object', 'properties': {'data': {'type': 'object',
            'default': {'description': note}, 'examples': [{'description': note}],
            'enum': [{'description': note}], 'const': {'description': note}}}}}}]}
    manifest = source_manifest(None, ['parameter-note'], offered)
    entry, = manifest['files']
    assert entry['offered_match'] == 'not_observed'
    assert manifest['unresolved_sources'] == ['parameter-note']
    assert all(m['role'] == 'user' for m in entry['matched_locations'])


class NativeArgs(BaseModel):
    description: str = Field(min_length=3, description='Include all necessary context.')
    subagent_type: str


def native_tool():
    def task(description: str, subagent_type: str) -> str:
        return description
    return StructuredTool.from_function(task, args_schema=NativeArgs,
        description='Native task help. Put full detail in the prompt.')


def test_v4_field_override_preserves_original_schema_constraints():
    original = native_tool()
    before = deepcopy(original.args_schema.model_json_schema())
    projected = task_tool(original, review_profile='native-reviewer-v2', interface_profile='review-interfaces-v4')
    schema = projected.args_schema.model_json_schema()
    field = schema['properties']['description']
    assert 'Include all necessary context' not in field['description']
    assert field['description'] == CoTaskMessage.model_fields['description'].description
    assert field['minLength'] == 3 and field['type'] == 'string'
    assert 'description' in schema['required'] and 'default' not in field
    assert original.args_schema.model_json_schema() == before
    assert projected.func is original.func
    with pytest.raises(ValueError):
        projected.args_schema(description='x', subagent_type='reviewer')


def test_v4_help_lists_the_supplied_registered_descriptions_only():
    projected = task_tool(native_tool(), review_profile='native-reviewer-v2',
        interface_profile='review-interfaces-v4',
        subagent_descriptions=(('registered-specialist', 'A uniquely registered capability.'),))
    assert '- registered-specialist: A uniquely registered capability.' in projected.description
    assert '- writer:' not in projected.description
    assert 'Put full detail in the prompt' not in projected.description


@pytest.mark.parametrize('profile', ['review-interfaces-v1', 'review-interfaces-v2', 'review-interfaces-v3'])
def test_old_profiles_retain_native_parameter_help(profile):
    original = native_tool()
    before = deepcopy(original.args_schema.model_json_schema())
    projected = task_tool(original, review_profile='native-reviewer-v2', interface_profile=profile)
    assert 'Put full detail in the prompt.' in projected.description
    assert projected.args_schema.model_json_schema()['properties']['description'] == before['properties']['description']
    assert original.args_schema.model_json_schema() == before


async def test_final_native_sdk_prompt_and_short_description_keep_complete_binding(case):
    from report_agent.deep_runtime import build_agent
    from report_agent.deep_models import GLMChatOpenAI, model_async_client
    from report_agent.workspace import Workspace
    from report_agent.decision_state import read_state
    from test_prompt_native_sdk_inputs import completion
    cs, _, criteria, original = prepared(case)
    cs.store.set('context_policy', 'stateful-tools-v2')
    from support.flat_task_fixture import task_arguments
    args = task_arguments(cs, case[1], review_call(criteria)['args'])
    args['description'] = 'Independently verify this saved draft; retain unresolved findings.'
    models, wires = {}, []
    def factory(role):
        if role not in models:
            client = model_async_client(cs.store, role)
            def transport(request):
                body = json.loads(request.content)
                first_co = role == 'coordinator' and not any(r == role for r, _ in wires)
                wires.append((role, body))
                return completion(request, '', ('task', args)) if first_co else completion(
                    request, 'Protocol fixture only; no semantic assessment was performed.')
            client._transport = httpx.MockTransport(transport)
            client._mounts.clear()
            models[role] = GLMChatOpenAI(model='glm-5.3', api_key='fixture-only',
                base_url='https://fixture.invalid/v1', use_responses_api=False,
                http_async_client=client, max_retries=0, disable_streaming=True)
        return models[role]
    try:
        await build_agent(Workspace(cs.store), factory, None).ainvoke({'messages': [HumanMessage('Offline protocol fixture.')]})
        co = next(body for role, body in wires if role == 'coordinator')
        task = next(t['function'] for t in co['tools'] if t['function']['name'] == 'task')
        assert 'Put full detail in the prompt' not in task['description']
        assert 'the agent sees only the prompt you give it' not in task['description']
        assert 'Include all necessary context' not in task['parameters']['properties']['description']['description']
        assert CoTaskMessage.model_fields['description'].description == task['parameters']['properties']['description']['description']
        for role in ('writer', 'reviewer', 'layout'):
            assert load_prompt('content-'+role+'-description').strip() in task['description']
        assert 'review' not in task['parameters']['properties']
        assert 'snapshot_scope' in task['parameters']['properties']
        assert not {'review_requirements', 'review_snapshot_ref'} & task['parameters']['properties'].keys()
        capture = next(cs.store.get(e['data']['capture_key']) for e in cs.store.events()
            if e['kind'] == 'prompt_final_http_input' and cs.store.get(e['data']['capture_key'])['purpose'] == 'coordinator')
        assert capture['source_manifest']['offered_tool_schema_sha256']
        assert any(role == 'reviewer' for role, _ in wires)
        # The writer fixture task precedes the independently saved Reviewer task.
        saved = next(t for t in cs.list_objects('DelegatedTask') if t['payload']['role'] == 'reviewer')
        payload = saved['payload']
        assert payload['goal'] == args['description']
        assert {json.dumps(r, sort_keys=True) for r in payload['review_commission_basis']['criterion_refs']} == {json.dumps(r, sort_keys=True) for r in criteria}
        assert payload['review_commission_basis']['original_requirement_refs'] == original
        assert len(payload['review_requirements']) == 7
        for item in payload['review_requirements']:
            assert item['required_checks'] == [cs.read(item['criterion_ref'])['payload']['expected_outcome']]
        from report_agent.content_tasks import delegated_task
        resume = {'name': 'task', 'id': 'read-assignment', 'args': {'subagent_type': 'reviewer',
            'description': 'Read the exact saved assignment.', 'resume_content_task_id': saved['ref']['id']}}
        with delegated_task(Workspace(cs.store), 'coordinator', resume):
            assert read_state(Workspace(cs.store), 'reviewer', ['assignment', 'review_commission_basis'])['value'] == payload['review_commission_basis']
        assert not cs.list_objects('ReviewRecord')
        target = case[0].store.root / 'effective-sdk-inputs.json'
        target.write_text(json.dumps({'offline_scripted_protocol_only': True, 'wires': wires,
            'co_capture': capture}, ensure_ascii=False, indent=2), encoding='utf-8')
    finally:
        for model in models.values():
            await model.root_async_client.close()
            model.root_client.close()
