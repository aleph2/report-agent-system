"""Native return preservation, explicit release and final SDK provenance, offline only."""
import json
from copy import deepcopy

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.types import Command

from report_agent import content_tasks, deep_runtime
from report_agent.content_store import ContentStore
from report_agent.deep_models import GLMChatOpenAI, model_async_client
from report_agent.prompt_sources import load_prompt
from test_deep_runtime import Driver, invoke
from test_hierarchical_content import ws, seed
from test_prompt_native_sdk_inputs import completion
from test_reviewer_native_profile import native
from test_saved_reference_receipts import saved

V3 = 'review-interfaces-v3'


def activate(workspace):
    native(workspace)
    workspace.store.set('manifest', {**workspace.store.manifest,
        'delegation_prompt_profile':'separate-description-v1', 'review_interface_profile':V3,
        'context_policy':'stateful-tools-v2'})


def test_command_channels_original_error_and_prose_survive_program_metadata(saved):
    _, cs, co, _, task, _, _ = saved
    message = ToolMessage('Writer prose contains a made-up ID, not authority.', id='original-message',
        name='task', tool_call_id='native-call', status='error', artifact={'original':True})
    original = Command(graph=Command.PARENT, goto='continuation', resume={'unchanged':1},
        update={'messages':[message], 'files':{'saved':'bytes'}, 'todos':[{'status':'pending'}]})
    result = content_tasks.attach_saved_reference_metadata(cs, co, task, original, 'native-call')
    assert result.graph == original.graph and result.goto == original.goto and result.resume == original.resume
    assert result.update['files'] == original.update['files'] and result.update['todos'] == original.update['todos']
    updated, = result.update['messages']
    assert (updated.id, updated.name, updated.tool_call_id, updated.status) == (
        message.id, message.name, message.tool_call_id, message.status)
    assert message.content in updated.content and 'opaque-work' in updated.content
    assert updated.artifact['original'] is True
    assert updated.artifact['saved_reference_metadata']['semantic_acceptance'] is False
    assert original.update['messages'][0].content == message.content


def test_metadata_failure_never_relabels_paid_child_result_or_mints_trusted_ids(saved, monkeypatch):
    _, cs, co, _, task, _, _ = saved
    def unavailable(*args): raise OSError('Synthetic metadata IO failure')
    monkeypatch.setattr(cs, 'saved_reference_summary', unavailable)
    message = ToolMessage('Partial original work retained.', name='task', tool_call_id='call', status='error')
    result = content_tasks.attach_saved_reference_metadata(cs, co, task, message, 'call')
    assert result.status == 'error' and message.content in result.content
    assert result.artifact['saved_reference_metadata']['status'] == 'unavailable'
    assert 'receipts' not in result.artifact['saved_reference_metadata']


@pytest.mark.parametrize('proof', ['decision_metadata', 'focused_capability_delivery', 'report_public_delivery'])
def test_content_bound_proof_does_not_become_a_false_hash_after_append(saved, proof):
    _, cs, co, _, task, _, _ = saved
    message = ToolMessage('Original proof-bound content.', name='task', tool_call_id='call',
        artifact={proof:{'original_sha256':'proof'}})
    result = content_tasks.attach_saved_reference_metadata(cs, co, task, message, 'call')
    assert result.content == message.content
    assert result.artifact[proof] == message.artifact[proof]
    assert result.artifact['saved_reference_metadata']['status'] == 'unavailable'


async def test_real_native_writer_return_carries_program_refs_without_an_extra_model_call(ws):
    activate(ws)
    def received(messages):
        message = next(m for m in reversed(messages) if isinstance(m, ToolMessage) and m.name=='task')
        metadata = message.artifact['saved_reference_metadata']
        record, = metadata['receipts']
        assert record['counts'] == {'ContentNode':1}
        assert record['receipt_id'] == 'owned-save'
        assert 'Writer summary' in message.content
        return AIMessage('Preserved saved work; no acceptance claim.')
    driver = Driver(coordinator=[invoke('task', subagent_type='writer', description='Save one structural report heading.'), received],
        writer=[invoke('commit_objects', operation_id='owned-save', objects=[{'client_key':'root', 'type':'ContentNode',
            'payload':{'kind':'report','body':{'text':'Heading'},'qualifiers':{},'claim_kind':'structure'}}]),
            AIMessage('Writer summary with shortened IDs is not the reference authority.')])
    result = await deep_runtime.run_report(ws, driver)
    assert result['last_error'] is None, result
    assert [r for r,_,_ in driver.calls] == ['coordinator','writer','writer','coordinator']
    assert len(ContentStore(ws.store).list_objects('ContentNode')) == 1


async def test_native_checkpoint_resume_and_actual_summary_keep_exact_saved_receipt(ws):
    from langchain_core.runnables import RunnableLambda
    from report_agent.store import Store
    from report_agent.workspace import Workspace
    from report_agent.working_summary import WorkingSummary
    from report_agent.summary_recovery import key
    from report_agent.task_context import read_observation
    activate(ws)
    def received(messages):
        message = next(m for m in reversed(messages) if isinstance(m, ToolMessage) and m.name=='task')
        assert message.artifact['saved_reference_metadata']['receipts'][0]['receipt_id']=='saved-exact'
        assert message.content.endswith(json.dumps(message.artifact['saved_reference_metadata'], ensure_ascii=False, sort_keys=True))
        return AIMessage('No acceptance claimed.')
    driver=Driver(coordinator=[invoke('task',subagent_type='writer',description='Save a heading.'),received],
        writer=[invoke('commit_objects',operation_id='saved-exact',objects=[{'client_key':'root','type':'ContentNode',
            'payload':{'kind':'report','body':{'text':'Heading'},'qualifiers':{},'claim_kind':'structure'}}]), AIMessage('Saved partial draft.')])
    driver.fail_once=('coordinator',1)
    await deep_runtime.run_report(ws,driver)
    assert driver.failed
    await deep_runtime.run_report(ws,driver)
    assert sum(r=='writer' for r,_,_ in driver.calls)==2
    history=driver.calls[-1][2][1:]
    async def notes(prompt): return AIMessage('Historical notes omit all saved IDs.')
    summary=WorkingSummary(model=RunnableLambda(notes),store=ws.store,role='coordinator',
        trigger=('messages',2),keep=('messages',1),token_counter=lambda m:len(m),trim_tokens_to_summarize=None)
    update=await summary.abefore_model({'messages':history},None)
    assert update is not None
    reopened=Workspace(Store(ws.store.root))
    records=reopened.store.get(key(reopened,'coordinator'))
    record=next(r for r in records if r['tool']=='task')
    text=read_observation(reopened,'coordinator',record['observation_ref'],0,6000)['text']
    assert 'saved-exact' in text and 'program_saved_reference_metadata' in text
    assert 'Historical notes omit' not in text


async def test_built_v2_and_v3_graphs_keep_distinct_actual_sdk_schemas_sources_and_paths(ws):
    activate(ws)
    wires, models = [], {}
    def factory(role):
        if role not in models:
            client = model_async_client(ws.store, role)
            def transport(request):
                wires.append((role,json.loads(request.content)))
                return completion(request,'Synthetic observation only.')
            client._transport=httpx.MockTransport(transport);client._mounts.clear()
            models[role]=GLMChatOpenAI(model='glm-5.3',api_key='fixture-only',base_url='https://fixture.invalid/v1',
                use_responses_api=False,http_async_client=client,max_retries=0,disable_streaming=True)
        return models[role]
    try:
        first = deep_runtime.build_agent(ws,factory,None)
        ws.store.set('manifest',{**ws.store.manifest,'review_interface_profile':'review-interfaces-v2'})
        old = deep_runtime.build_agent(ws,factory,None)
        ws.store.set('manifest',{**ws.store.manifest,'review_interface_profile':'review-interfaces-v1'})
        for graph in (first,old): await graph.ainvoke({'messages':[HumanMessage('Inspect synthetic interface.')]})
        co = [body for role,body in wires if role=='coordinator']
        tools = [{x['function']['name']:x['function'] for x in body['tools']} for body in co]
        assert 'saved_receipt_ids' in tools[0]['freeze_snapshot']['parameters']['properties']
        assert 'saved_receipt_ids' not in tools[1]['freeze_snapshot']['parameters']['properties']
        assert "['assignment'," not in tools[0]['read_decision_state']['description']
        assert "['assignment'," in tools[1]['read_decision_state']['description']
        captures=[ws.store.get(e['data']['capture_key']) for e in ws.store.events() if e['kind']=='prompt_final_http_input']
        assert all(c['status']=='exact' for c in captures)
        files=[{f['name'] for f in c['source_manifest']['files']} for c in captures]
        assert all('saved-reference-handoff' not in names for names in files)
        assert all(next(s['files'] for s in c['sources'] if s['source'] == 'configured_role_files') ==
                   ['agent-common', 'agent-coordinator'] for c in captures)
        assert load_prompt('saved-reference-handoff') not in json.dumps(co[0],ensure_ascii=False).replace('\\n','\n')
    finally:
        for model in models.values():
            await model.root_async_client.close(); model.root_client.close()


async def test_v3_registered_freeze_uses_saved_receipts_in_the_native_tool_node(saved):
    from test_deep_runtime import observation
    workspace, cs, _, _, _, refs, all_refs = saved
    activate(workspace)
    def frozen(messages):
        result=observation(messages,'freeze_snapshot')
        assert result['ok'] is True
        snapshot=cs.read(result['result']['snapshot_ref'])['payload']
        assert {json.dumps(r,sort_keys=True) for r in snapshot['refs']} == {json.dumps(r,sort_keys=True) for r in all_refs}
        return AIMessage('Snapshot assembled; review remains pending.')
    driver=Driver(coordinator=[invoke('freeze_snapshot',operation_id='registered-freeze',
        root_ref=refs['root'],refs=[],saved_receipt_ids=['criteria','opaque-work']),frozen])
    result=await deep_runtime.run_report(workspace,driver)
    assert result['last_error'] is None, result
    assert len(driver.calls)==2


def test_v3_inherits_exact_v2_review_task_and_submission_schemas(ws):
    from langchain_core.utils.function_calling import convert_to_openai_tool
    from report_agent.content_tasks import task_tool
    from report_agent.prompt_sources import NATIVE_REVIEW
    from report_agent.hierarchical_tools import content_tools
    from test_native_task_error_boundary import registered_task
    activate(ws)
    tasks=[task_tool(registered_task(),review_profile=NATIVE_REVIEW,interface_profile=p)
           for p in ('review-interfaces-v2',V3)]
    assert convert_to_openai_tool(tasks[0]) == convert_to_openai_tool(tasks[1])
    schemas=[]
    for profile in ('review-interfaces-v2',V3):
        ws.store.set('manifest',{**ws.store.manifest,'review_interface_profile':profile})
        tool=next(t for t in content_tools(ws,'reviewer') if t.__name__=='submit_review')
        schemas.append(convert_to_openai_tool(tool))
    assert schemas[0] == schemas[1]
