"""Native graph -> actual SDK serializer -> MockTransport public input capture."""
import json
from collections import Counter

import httpx
import pytest
from langchain_core.messages import HumanMessage,AIMessage
from openai import AsyncOpenAI

from report_agent import deep_runtime
from report_agent.deep_models import GLMChatOpenAI,model_async_client,model_sync_client
from report_agent.prompt_provenance import prompt_call,bind_wire_payload
from report_agent.prompt_sources import load_prompt
from report_agent.working_summary import working_summary
from report_agent.vision import observe_source_image
from test_hierarchical_content import ws,seed
from test_reviewer_native_profile import native,commission,candidate
from test_document_tools import workspace as image_workspace


def completion(request,content='Fixture response.',tool=None):
    body=json.loads(request.content)
    message={'role':'assistant','content':content}
    if tool:
        name,args=tool
        message['tool_calls']=[{'id':'fixture-'+name,'type':'function','function':{'name':name,'arguments':json.dumps(args)}}]
    return httpx.Response(200,json={'id':'fixture-completion','model':body['model'],
        'choices':[{'index':0,'message':message,'finish_reason':'tool_calls' if tool else 'stop'}],
        'usage':{'prompt_tokens':8,'completion_tokens':2,'total_tokens':10}})


async def test_actual_native_reviewer_wire_contains_configured_role_schema_and_saved_result(ws):
    """P01/P04/P07/E01: no FakeDriver boundary between role and final HTTP."""
    native(ws);cs,_,refs,snap,_=seed(ws);models={};counts=Counter();wires=[]
    from report_agent.prompt_instructions import configure_report
    from test_prompt_instructions import candidate as instruction_candidate, release
    ws.store.set('context_policy', 'stateful-tools-v1')
    configure_report(ws.store, 'sdk-fixture-report')
    instruction = instruction_candidate(ws, text='Fixture authority: preserve declared uncertainty.')
    release(ws, instruction)
    def factory(role):
        if role in models:return models[role]
        client=model_async_client(ws.store,role)
        async def transport(request):
            body=json.loads(request.content);wires.append((role,body));step=counts[role];counts[role]+=1
            if role=='coordinator':
                if step==0:return completion(request,'',('task',commission(snap,refs)))
                return completion(request,'Retained actual scoped review result.')
            assert role=='reviewer'
            if step==0:return completion(request,'',('read_context',{'target_ref':refs['claim']}))
            last=json.loads(next(m['content'] for m in reversed(body['messages']) if m['role']=='tool'))
            if step==1:return completion(request,'',('submit_review',{'operation_id':'sdk-native-save',
                'review':candidate(snap,refs,[last['receipt_id']])}))
            assert last['ok'];return completion(request,json.dumps(last))
        client._transport=httpx.MockTransport(transport);client._mounts.clear()
        model=GLMChatOpenAI(model='glm-5.3',api_key='fixture-sdk-key-canary',base_url='https://fixture.invalid/v1',
            use_responses_api=False,http_async_client=client,max_retries=0,disable_streaming=True)
        models[role]=model;return model
    try:
        result=await deep_runtime.run_report(ws,factory)
        assert result['last_error'] is None,result
        assert len(cs.list_objects('ReviewRecord'))==1
        reviewer=next(body for role,body in wires if role=='reviewer')
        system='\n'.join(m['content'] if isinstance(m['content'],str) else '\n'.join(b.get('text','') for b in m['content'])
            for m in reviewer['messages'] if m['role']=='system')
        expected = '\n\n'.join(t for t in [load_prompt('agent-common'), load_prompt('agent-reviewer')] if t.strip())
        if expected:
            assert system.startswith(expected)
        tools={t['function']['name']:t['function'] for t in reviewer['tools']}
        assert {'submit_review','write_todos','analyze_evidence'}<=tools.keys()
        assert not {'perform_assigned_review','commit_objects','task'}&tools.keys()
        assert 'review' in tools['submit_review']['parameters']['properties']
        captures=[ws.store.get(e['data']['capture_key']) for e in ws.store.events() if e['kind']=='prompt_final_http_input']
        assert len(captures)==len(wires)
        assert {v['purpose'] for v in captures}=={'coordinator','reviewer'}
        assert all(v['expected_wire_available'] for v in captures)
        assert 'fixture-sdk-key-canary' not in json.dumps(captures)
        for capture, (_, wire) in zip(captures, wires):
            manifest = capture['source_manifest']
            assert capture['public_input'] == wire
            from report_agent.store import digest
            assert manifest['offered_tool_schema_sha256'] == digest(next(
                ws.store.get(e['data']['capture_key'])['public_input']['tools'] for e in ws.store.events()
                if e['kind'] == 'prompt_model_input' and e['data']['call_id'] == capture['call_id']))
            assert capture['final_tool_schema_sha256'] == digest(wire['tools'])
            runtime = ws.store.get(capture['runtime_version_ref'])
            assert runtime['source_files']['deep_runtime.py']
            assert runtime['import_root'].endswith('/src/report_agent')
            names = {f['name'] for f in manifest['files']}
            assert {'agent-common', 'agent-' + capture['purpose']} <= names
            authored = next(s for s in capture['sources'] if s.get('files') == ['agent-common', 'agent-' + capture['purpose']])
            import hashlib
            assert authored['sha256'] == hashlib.sha256('\n\n'.join(t for t in [load_prompt(n) for n in authored['files']] if t.strip()).encode()).hexdigest()
            offered = next(ws.store.get(e['data']['capture_key']) for e in ws.store.events()
                if e['kind'] == 'prompt_model_input' and e['data']['call_id'] == capture['call_id'])
            assert offered['source_manifest'] == manifest
            source = next(s for s in capture['sources'] if s['source'] == 'task_context/current_server_bound_state')
            assert source['references']['instruction_refs'] == [instruction['ref']]
            receipt = next(e['data'] for e in ws.store.events() if e['kind'] == 'prompt_context_offered'
                and e['data']['instruction_digest'] == source['references']['instruction_digest'])
            saved = ws.store.get('prompt_context_snapshot:' + receipt['snapshot_id'])
            assert saved['scoped_instructions']['effective'] == [instruction]
    finally:
        for model in models.values():
            await model.root_async_client.close();model.root_client.close()


async def test_summary_shared_coordinator_service_and_visual_actual_sdk_have_distinct_purposes(ws,tmp_path):
    """Summary Human is not Co role; vision public capture hashes image bytes."""
    client=model_async_client(ws.store,'coordinator');client._transport=httpx.MockTransport(lambda r:completion(r,'Synthetic working notes.'));client._mounts.clear()
    model=GLMChatOpenAI(model='glm-5.3',api_key='fixture-only',base_url='https://fixture.invalid/v1',
        use_responses_api=False,http_async_client=client,max_retries=0,disable_streaming=True)
    try:
        summary=working_summary(model,ws.store,role='coordinator')
        assert await summary._acreate_summary([HumanMessage(content='Current exact fixture goal.')])=='Synthetic working notes.'
        value=next(ws.store.get(e['data']['capture_key']) for e in ws.store.events() if e['kind']=='prompt_final_http_input')
        assert value['purpose']=='working_summary'
        assert value['public_input']['messages'][0]['role']=='user'
        assert {f['name'] for f in value['source_manifest']['files']} == {'working-summary'}
        assert not value['source_manifest']['unresolved_sources']
    finally:await client.aclose();model.root_client.close()
    visual=image_workspace(tmp_path/'visual');vclient=model_async_client(visual.store,'reviewer')
    vclient._transport=httpx.MockTransport(lambda r:completion(r,'Synthetic visual observation, not an accepted fact.'));vclient._mounts.clear()
    sdk=AsyncOpenAI(api_key='fixture-visual-key-canary',base_url='https://fixture.invalid/v1',max_retries=0,http_client=vclient)
    try:
        result=await observe_source_image(visual,'original','Inspect supplied synthetic page.',client=sdk)
        assert result['status']=='observed',result
        value=next(visual.store.get(e['data']['capture_key']) for e in visual.store.events() if e['kind']=='prompt_final_http_input')
        assert value['purpose']=='source_vision' and value['expected_wire_available']
        public=json.dumps(value)
        assert 'fixture-visual-key-canary' not in public and 'data:image' not in public
        assert 'image_url_metadata' in public and len(value['body_sha256'])==64
        assert {f['name'] for f in value['source_manifest']['files']} == {'source-vision'}
    finally:await sdk.close()


def test_sync_sdk_uses_same_final_public_projection(ws):
    from openai import OpenAI
    client=model_sync_client(ws.store,'fixture-sync')
    client._transport=httpx.MockTransport(lambda r:completion(r));client._mounts.clear()
    sdk=OpenAI(api_key='fixture-sync-key',base_url='https://fixture.invalid/v1',max_retries=0,http_client=client)
    payload={'model':'glm-5.3','messages':[{'role':'system','content':'Synthetic sync role.'},{'role':'user','content':'Question'}]}
    try:
        with prompt_call(ws.store,'fixture_sync',sources=['fixture'],status='unexplained',offered=payload):
            bind_wire_payload(payload);sdk.chat.completions.create(**payload)
        value=next(ws.store.get(e['data']['capture_key']) for e in ws.store.events() if e['kind']=='prompt_final_http_input')
        assert value['purpose']=='fixture_sync' and value['expected_wire_available']
        assert value['public_input']==payload
    finally:sdk.close()


async def test_optimizer_has_its_own_configured_role_and_captured_tool_schema(ws,tmp_path):
    from report_agent.learning import LearningLibrary
    from report_agent.learning_runtime import build_optimizer
    from test_deep_runtime import Driver
    ws.store.set('learning_config',{'library_path':str(tmp_path/'library'),'customer_id':'fixture'})
    LearningLibrary(tmp_path/'library')
    driver=Driver(optimizer=[AIMessage(content='Synthetic reflection only; no release or report change.')])
    await build_optimizer(ws,driver('optimizer')).ainvoke({'messages':[HumanMessage(content='Inspect the synthetic learning scope.')]})
    value=next(ws.store.get(e['data']['capture_key']) for e in ws.store.events() if e['kind']=='prompt_model_input')
    assert value['purpose']=='experience_optimizer'
    assert load_prompt('experience-optimizer') in driver.calls[0][2][0].text
    assert value['public_input']['tools']


@pytest.mark.parametrize('contract,source,inputs', [
    ('independent-text-tools-v1', 'text-work', {}),
    ('independent-text-tools-v1', 'qualifier-work', {'revision': True}),
    ('selected-evidence-v3', 'evidence-analysis', {}),
    ('assigned-artifact-text-work-v1', 'artifact-analysis', {}),
    ('learning-evidence-text-work-v1', 'learning-analysis', {}),
    ('assigned-review-fixture-v1', 'legacy-bounded-review', {}),
])
async def test_bounded_analysis_contract_uses_actual_sdk_and_exact_declared_source(ws, contract, source, inputs):
    """Real shared analysis entry and serializer, not semantic tool/task acceptance."""
    from report_agent.evidence_analysis import analyze_evidence_packet
    from report_agent.prompt_instructions import instruction_context, configure_report
    from report_agent.store import digest
    from test_prompt_instructions import candidate as instruction_candidate, release
    ws.store.set('context_policy', 'stateful-tools-v1')
    configure_report(ws.store, 'analysis-fixture')
    instruction = instruction_candidate(ws, text='Fixture authority: preserve evidence limitations.')
    release(ws, instruction)
    packet = instruction_context(ws.store, 'reviewer')
    inputs = {**inputs, 'commission': {'scoped_instructions': packet}, 'question': 'Fixture contract only.', 'evidence': []}
    system = load_prompt(source)
    if source in {'artifact-analysis', 'legacy-bounded-review'}:
        system += load_prompt('scoped-review-channel')
    wires = []
    client = model_async_client(ws.store, 'text_tool')
    def transport(request):
        wires.append(json.loads(request.content))
        return completion(request, 'Fixture observed answer; not engineering approval.')
    client._transport = httpx.MockTransport(transport)
    client._mounts.clear()
    model = GLMChatOpenAI(model='glm-5.3', api_key='fixture-only', base_url='https://fixture.invalid/v1',
        use_responses_api=False, http_async_client=client, max_retries=0, disable_streaming=True)
    try:
        await analyze_evidence_packet(ws, model, inputs, system, contract)
        value = next(ws.store.get(e['data']['capture_key']) for e in ws.store.events()
            if e['kind'] == 'prompt_final_http_input')
        assert value['purpose'] == source and value['public_input'] == wires[0]
        files = {f['name'] for f in value['source_manifest']['files']}
        assert source in files
        if source in {'artifact-analysis', 'legacy-bounded-review'}:
            assert 'scoped-review-channel' in files
        dynamic = next(s for s in value['sources'] if isinstance(s, dict) and s['source'] == 'analysis_input/current_commission')
        assert dynamic['references']['instruction_digest'] == packet['digest']
        assert dynamic['references']['instruction_refs'] == [instruction['ref']]
        assert dynamic['references']['input_sha256'] == digest(inputs)
    finally:
        await client.aclose()
        model.root_client.close()


async def test_optimizer_native_graph_actual_sdk_links_its_own_source_and_tools(ws, tmp_path):
    from report_agent.learning import LearningLibrary
    from report_agent.learning_runtime import build_optimizer
    ws.store.set('learning_config', {'library_path': str(tmp_path/'library'), 'customer_id':'fixture'})
    LearningLibrary(tmp_path/'library')
    client = model_async_client(ws.store, 'optimizer')
    wires = []
    def transport(request):
        wires.append(json.loads(request.content))
        return completion(request, 'No strategy proposed from the synthetic input.')
    client._transport = httpx.MockTransport(transport)
    client._mounts.clear()
    model = GLMChatOpenAI(model='glm-5.3', api_key='fixture-only', base_url='https://fixture.invalid/v1',
        use_responses_api=False, http_async_client=client, max_retries=0, disable_streaming=True)
    try:
        await build_optimizer(ws, model).ainvoke({'messages':[HumanMessage(content='Inspect fixture only.')]})
        value = next(ws.store.get(e['data']['capture_key']) for e in ws.store.events()
            if e['kind'] == 'prompt_final_http_input')
        assert value['purpose'] == 'experience_optimizer'
        assert value['public_input'] == wires[0]
        assert {f['name'] for f in value['source_manifest']['files']} == {'experience-optimizer'}
        assert value['source_manifest']['offered_tool_schema_sha256']
        assert ws.store.get(value['runtime_version_ref'])['source_files']['learning_runtime.py']
    finally:
        await client.aclose()
        model.root_client.close()


async def test_legal_strict_codec_transform_keeps_offered_and_final_schema_hashes_distinct(ws):
    from report_agent.store import digest
    tools = [{'type':'function', 'function': {'name':'fixture_read', 'description':'Read fixture.',
        'parameters':{'type':'object', 'properties':{'optional_note':{'type':'string'}}, 'required':[]}}}]
    payload = {'messages':[{'role':'system','content':load_prompt('evidence-analysis')}], 'tools':tools}
    client = model_async_client(ws.store, 'text_tool')
    client._transport = httpx.MockTransport(lambda r: completion(r))
    client._mounts.clear()
    model = GLMChatOpenAI(model='deepseek-v4-pro', api_key='fixture-only', base_url='https://fixture.invalid/beta',
        use_responses_api=False, http_async_client=client, max_retries=0, disable_streaming=True, deepseek_strict=True)
    try:
        with prompt_call(ws.store, 'evidence-analysis', sources=['evidence-analysis'], offered=payload):
            await model.bind_tools(tools).ainvoke([('system', load_prompt('evidence-analysis'))])
        value = next(ws.store.get(e['data']['capture_key']) for e in ws.store.events()
            if e['kind'] == 'prompt_final_http_input')
        assert value['source_manifest']['offered_tool_schema_sha256'] == digest(tools)
        assert value['final_tool_schema_sha256'] == digest(value['public_input']['tools'])
        assert value['final_tool_schema_sha256'] != value['source_manifest']['offered_tool_schema_sha256']
        assert value['expected_wire_available']
    finally:
        await client.aclose()
        model.root_client.close()


async def test_two_native_graphs_keep_their_own_runtime_version_and_direct_calls_stay_unbound(ws, monkeypatch):
    import report_agent.prompt_sources as sources
    from test_deep_runtime import Driver
    native(ws)
    refs = iter(['fixture-runtime-first', 'fixture-runtime-second'])
    monkeypatch.setattr(sources, 'record_runtime_version', lambda store: next(refs))
    first = deep_runtime.build_agent(ws, Driver(coordinator=[AIMessage(content='First graph.')]), None)
    second = deep_runtime.build_agent(ws, Driver(coordinator=[AIMessage(content='Second graph.')]), None)
    # An obsolete global diagnostic pointer must not relabel either graph or a direct call.
    ws.store.set('prompt_runtime_binding', 'fixture-obsolete-global-pointer')
    for graph in (first, second):
        await graph.ainvoke({'messages':[HumanMessage(content='Fixture only; no business actions.')]})
    with prompt_call(ws.store, 'direct-fixture', offered={'messages':[]}):
        pass
    captures = [ws.store.get(e['data']['capture_key']) for e in ws.store.events()
        if e['kind'] == 'prompt_model_input']
    assert [v['runtime_version_ref'] for v in captures] == ['fixture-runtime-first', 'fixture-runtime-second', None]


@pytest.mark.parametrize('failure', ['source_read', 'snapshot_write'])
async def test_graph_version_diagnostic_failure_leaves_unbound_capture_and_preserves_execution(ws, monkeypatch, failure):
    import report_agent.prompt_sources as sources
    from test_deep_runtime import Driver
    native(ws)
    if failure == 'source_read':
        original = sources.Path.read_bytes
        def read(path):
            if path.suffix == '.py':
                raise PermissionError('Synthetic runtime source diagnostic failure')
            return original(path)
        monkeypatch.setattr(sources.Path, 'read_bytes', read)
    else:
        original = ws.store.set
        def write(key, value):
            if key.startswith('prompt_runtime_version:'):
                raise OSError('Synthetic version snapshot failure')
            return original(key, value)
        monkeypatch.setattr(ws.store, 'set', write)
    graph = deep_runtime.build_agent(ws, Driver(coordinator=[AIMessage(content='Fixture still completed.')]), None)
    result = await graph.ainvoke({'messages':[HumanMessage(content='Fixture only.')]})
    assert result['messages'][-1].content == 'Fixture still completed.'
    value = next(ws.store.get(e['data']['capture_key']) for e in ws.store.events()
        if e['kind'] == 'prompt_model_input')
    assert value['runtime_version_ref'] is None


async def test_auxiliary_source_metadata_gap_does_not_add_an_execution_gate(ws):
    from report_agent.evidence_analysis import analyze_evidence_packet
    inputs = {'question':'Fixture only.', 'evidence':[],
        'commission':{'scoped_instructions':{'digest':'synthetic-unusable-metadata', 'effective':None}}}
    client = model_async_client(ws.store, 'text_tool')
    client._transport = httpx.MockTransport(lambda r: completion(r, 'Observed fixture response.'))
    client._mounts.clear()
    model = GLMChatOpenAI(model='glm-5.3', api_key='fixture-only', base_url='https://fixture.invalid/v1',
        use_responses_api=False, http_async_client=client, max_retries=0, disable_streaming=True)
    try:
        result = await analyze_evidence_packet(ws, model, inputs, load_prompt('evidence-analysis'), 'selected-evidence-v3')
        assert result['analysis'] == 'Observed fixture response.'
        value = next(ws.store.get(e['data']['capture_key']) for e in ws.store.events()
            if e['kind'] == 'prompt_final_http_input')
        assert 'unexplained_analysis_source_metadata' in value['source_manifest']['unresolved_sources']
    finally:
        await client.aclose()
        model.root_client.close()
