"""Expression release routing at the actual SDK boundary, without model quality claims."""
import hashlib
import json
import shutil
from copy import deepcopy

import httpx
import pytest
from langchain_core.messages import HumanMessage

from report_agent import deep_runtime, prompt_sources
from report_agent.content_store import ContentStore
from report_agent.content_models import ContentNode
from report_agent.deep_models import GLMChatOpenAI, model_async_client
from report_agent.errors import ActionRejected
from report_agent.hierarchical_tools import actor_for
from report_agent.text_work import produce, adopt
from test_hierarchical_content import ws
from test_prompt_native_sdk_inputs import completion
from test_reviewer_native_profile import native


LEGACY = 'report-expression-v1'
READER = 'reader-expression-v2'
SOURCES = ('content-writer', 'text-work', 'qualifier-work')
NODE = {'kind': 'block', 'body': {'text': 'A qualified finding for the report reader.'},
        'claim_kind': 'inference', 'qualifiers': {'technical': 'Condition remains unverified.'}}


@pytest.fixture(scope='module')
def expression_rule_tree(tmp_path_factory):
    original = {name: (prompt_sources.RULES / (name + '.md')).read_bytes() for name in SOURCES}
    rules = tmp_path_factory.mktemp('expression-source') / 'expression-rules'
    shutil.copytree(prompt_sources.RULES, rules)
    for name in SOURCES:
        (rules / (name + '-v2.md')).write_bytes(original[name] +
            b'\nReader expression release fixture: preserve real limits and exact provenance.\n')
    yield rules
    assert {name: (rules / (name + '.md')).read_bytes() for name in SOURCES} == original


@pytest.fixture
def expression_sources(expression_rule_tree, monkeypatch):
    monkeypatch.setattr(prompt_sources, 'RULES', expression_rule_tree)
    return expression_rule_tree


def set_expression(ws, profile):
    if profile is not None:
        ws.store.set('manifest', {**ws.store.manifest, 'report_expression_profile': profile})


def sdk_model(ws, role, handler):
    client = model_async_client(ws.store, role)
    client._transport = httpx.MockTransport(handler)
    client._mounts.clear()
    model = GLMChatOpenAI(model='glm-5.3', api_key='fixture-only', base_url='https://fixture.invalid/v1',
        use_responses_api=False, http_async_client=client, max_retries=0, disable_streaming=True)
    return model, client


def final_captures(ws, purpose=None):
    values = [ws.store.get(e['data']['capture_key']) for e in ws.store.events()
              if e['kind'] == 'prompt_final_http_input']
    return [v for v in values if purpose is None or v['purpose'] == purpose]


@pytest.mark.parametrize('profile', [None, LEGACY, READER], ids=['absent-legacy', 'explicit-legacy', 'reader'])
@pytest.mark.parametrize('revision', [False, True], ids=['ordinary', 'qualifier-only'])
async def test_expression_source_reaches_sdk_and_matches_declared_file(ws, expression_sources, profile, revision):
    set_expression(ws, profile)
    actor = actor_for('writer')
    spec = None
    if revision:
        ref = ContentStore(ws.store).commit(actor, 'base', [
            {'client_key': 'node', 'type': 'ContentNode', 'payload': NODE}])['result']['refs']['node']
        spec = {'scope': 'qualifiers', 'targets': [ref]}
    payload = {'qualifiers': NODE['qualifiers']} if revision else NODE
    wires = []
    def transport(request):
        wires.append(json.loads(request.content))
        return completion(request, json.dumps(payload))
    model, client = sdk_model(ws, 'text_tool', transport)
    source = ('qualifier-work' if revision else 'text-work') + ('-v2' if profile == READER else '')
    expected = prompt_sources.load_prompt(source)
    try:
        result = await produce(ws, actor, model, 'expression-work', 'Retain the qualified finding.',
            'ContentNode', source_selections=[{'source_id': 's'}], revision=spec)
        assert len(wires) == 1
        assert wires[0]['messages'][0]['content'] == expected
        capture, = final_captures(ws)
        assert capture['purpose'] == source and capture['public_input'] == wires[0]
        files = {f['name']: f for f in capture['source_manifest']['files']}
        assert set(files) == {source}
        assert files[source]['text_sha256'] == hashlib.sha256(expected.encode()).hexdigest()
        assert files[source]['offered_match'] == 'literal'
        assert capture['source_manifest']['unresolved_sources'] == []
        assert result['payload']['body'] == NODE['body']
        assert result['payload']['qualifiers'] == NODE['qualifiers']
    finally:
        await client.aclose()
        model.root_client.close()


@pytest.mark.parametrize('invalid', ['unknown-expression', 7])
async def test_invalid_expression_profile_rejects_before_text_model_dispatch(ws, invalid):
    set_expression(ws, invalid)
    wires = []
    def transport(request):
        wires.append(json.loads(request.content))
        return completion(request, json.dumps(NODE))
    model, client = sdk_model(ws, 'text_tool', transport)
    try:
        with pytest.raises(ActionRejected, match='UNKNOWN_REPORT_EXPRESSION_PROFILE'):
            await produce(ws, actor_for('writer'), model, 'invalid-profile', 'Retain source qualifications.',
                'ContentNode', source_selections=[{'source_id': 's'}])
        assert not wires
    finally:
        await client.aclose()
        model.root_client.close()


@pytest.mark.parametrize('profile,mutate', [(LEGACY, False), (READER, False), (READER, True)],
    ids=['legacy-writer', 'reader-writer', 'reader-graph-pinned'])
async def test_writer_graph_expression_source_is_frozen_and_not_role_pollution(ws, expression_sources, profile, mutate):
    native(ws)
    set_expression(ws, profile)
    ws.store.set('manifest', {**ws.store.manifest, 'delegation_prompt_profile': 'separate-description-v1'})
    models, clients, wires, counts = {}, [], [], {}
    def factory(role):
        if role not in models:
            def transport(request):
                wires.append((role, json.loads(request.content)))
                step = counts.get(role, 0)
                counts[role] = step + 1
                task = ('task', {'subagent_type': 'writer', 'description': 'Inspect the synthetic commission.'})
                return completion(request, 'Synthetic observation only; no acceptance.',
                                  task if role == 'coordinator' and step == 0 else None)
            models[role], client = sdk_model(ws, role, transport)
            clients.append(client)
        return models[role]
    source = 'content-writer' + ('-v2' if profile == READER else '')
    try:
        async with deep_runtime.project_agent(ws, factory) as graph:
            if mutate:
                set_expression(ws, LEGACY)
            await graph.ainvoke({'messages': [HumanMessage('Inspect the synthetic commission without writes.')]},
                {'configurable': {'thread_id': 'expression-writer'}})
        writer, = [body for role, body in wires if role == 'writer']
        content = writer['messages'][0]['content']
        text = content if isinstance(content, str) else ''.join(
            part['text'] for part in content if isinstance(part, dict) and part.get('type') == 'text')
        assert prompt_sources.load_prompt(source).strip() in text
        capture, = final_captures(ws, 'writer')
        assert capture['public_input'] == writer
        files = {f['name']: f for f in capture['source_manifest']['files']}
        assert source in files
        assert ('content-writer' if profile == READER else 'content-writer-v2') not in files
        assert files[source]['offered_match'] in {'literal', 'trimmed_literal'}
        assert source not in capture['source_manifest']['unresolved_sources']
        assert not final_captures(ws, 'reviewer')
    finally:
        for client in clients:
            await client.aclose()
        for model in models.values():
            model.root_client.close()


def test_packaged_expression_release_extends_legacy_files_without_rewriting_them():
    expected = {
        'text-work': 'non-structural qualifier labels and values',
        'qualifier-work': 'change their values only when the revision objective explicitly targets that display text',
        'content-writer': 'When adopting, also consider whether the candidate',
    }
    for source, clause in expected.items():
        old = (prompt_sources.RULES / (source + '.md')).read_bytes()
        new = (prompt_sources.RULES / (source + '-v2.md')).read_bytes()
        assert new.startswith(old + b'\n')
        assert clause in new[len(old):].decode()
    # Source selection is intentionally independent of all other release axes.
    assert prompt_sources.expression_source('content-reviewer', READER) == 'content-reviewer'
    assert prompt_sources.expression_source('text-work') == 'text-work'


@pytest.mark.parametrize('initial,current', [(LEGACY, LEGACY), (READER, READER), (LEGACY, READER)],
    ids=['legacy-replay', 'reader-replay', 'no-cross-source-replay'])
async def test_completed_schema_replay_uses_the_exact_original_expression_source(ws, expression_sources,
                                                                              monkeypatch, initial, current):
    set_expression(ws, initial)
    actor = actor_for('writer')
    wires = []
    def transport(request):
        wires.append(json.loads(request.content))
        return completion(request, json.dumps(NODE))
    model, client = sdk_model(ws, 'text_tool', transport)
    original_schema = ContentNode.model_json_schema
    def old_schema(*args, **kwargs):
        result = deepcopy(original_schema(*args, **kwargs))
        result.pop('allOf', None)
        return result
    args = (ws, actor, model, 'schema-replay', 'Retain the qualified finding.', 'ContentNode')
    try:
        with monkeypatch.context() as patch:
            patch.setattr(ContentNode, 'model_json_schema', old_schema)
            first = await produce(*args, source_selections=[{'source_id': 's'}])
        set_expression(ws, current)
        if initial != current:
            with pytest.raises(ActionRejected, match='OPERATION_CONFLICT'):
                await produce(*args, source_selections=[{'source_id': 's'}])
        else:
            repeated = await produce(*args, source_selections=[{'source_id': 's'}])
            assert repeated == {**first, 'reused': True}
            assert any(e['kind'] == 'text_work_completed_schema_reused' for e in ws.store.events())
        assert len(wires) == 1  # Completed replay/conflict never authorizes a second dispatch.
    finally:
        await client.aclose()
        model.root_client.close()


@pytest.mark.parametrize('revise_title', [False, True], ids=['retain-structure', 'explicit-display-revision'])
async def test_v2_qualifier_revision_keeps_structural_entries_and_does_not_filter_machine_format(ws, revise_title):
    """A supplied fixture proves routing/adoption invariants, not language quality."""
    set_expression(ws, READER)
    actor = actor_for('writer')
    table = {'kind': 'table', 'body': {'title': 'Assessment', 'columns': ['Finding'],
             'rows': [['A condition remains unverified.']]}, 'claim_kind': 'inference',
             'qualifiers': {'title': 'Original caption', '表号': 'T-1', 'document_type': 'report',
                            'technical': 'A condition remains unverified.', 'source_refs': 's:1'}}
    cs = ContentStore(ws.store)
    ref = cs.commit(actor, 'table', [{'client_key': 'node', 'type': 'ContentNode', 'payload': table}])['result']['refs']['node']
    qualifiers = {**table['qualifiers'], 'technical': 'The supplied evidence does not resolve the condition.'}
    if revise_title:
        qualifiers['title'] = 'Explicitly revised caption'
    wires = []
    def transport(request):
        wires.append(json.loads(request.content))
        return completion(request, json.dumps({'qualifiers': qualifiers}))
    model, client = sdk_model(ws, 'text_tool', transport)
    objective = ('Revise title display to the commissioned caption and retain remaining structural entries.'
                 if revise_title else 'Clarify the limitation, retaining caption and numbering.')
    objective += ' Retain the explicitly requested source_refs machine format.'
    try:
        work = await produce(ws, actor, model, 'qualifier-revision', objective, 'ContentNode',
            source_selections=[{'source_id': 's'}], revision={'scope': 'qualifiers', 'targets': [ref]})
        payload = adopt(ws, actor, work['text_work_id'], 'ContentNode', previous_ref=ref)
        saved = cs.commit(actor, 'adopt', [{'client_key': 'node', 'type': 'ContentNode',
                                          'payload': payload, 'previous_ref': ref}])['result']['refs']['node']
        assert saved == {**ref, 'version': 2}
        assert cs.read(ref)['payload'] == table
        assert cs.read(saved)['payload'] == {**table, 'qualifiers': qualifiers}
        assert payload['body'] == table['body'] and payload['claim_kind'] == table['claim_kind']
        assert payload['qualifiers']['source_refs'] == 's:1'
        assert wires[0]['messages'][0]['content'] == prompt_sources.load_prompt('qualifier-work-v2')
        assert len(wires) == 1
    finally:
        await client.aclose()
        model.root_client.close()
