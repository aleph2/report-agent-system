"""Phase 3 mechanical retention through native middleware and actual SDK inputs.

Scripted replies do not demonstrate model autonomy or report quality.
"""
import json
from types import SimpleNamespace
from collections import Counter

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableLambda
from langgraph.graph.message import add_messages

from report_agent.task_context import TaskContext, exact_task_context, read_observation, save_observation, enabled
from report_agent.summary_recovery import capture, recovery_tool
from report_agent.content_tasks import delegated_task
from report_agent.errors import ActionForbidden
from report_agent.store import Store, encode, digest
from report_agent.workspace import Workspace
from test_hierarchical_content import ws, seed
from test_reviewer_native_profile import native, commission

POLICY = 'stateful-tools-v2'


def activate(ws):
    native(ws)
    manifest = ws.store.manifest
    manifest['context_policy'] = POLICY
    ws.store.set('manifest', manifest)


def host_requirements(cs, actor, count):
    # Host fixture import only. The model-facing commit API intentionally cannot
    # create Requirement authority; use its canonical storage primitive here.
    with cs.store.connect() as db:
        return [cs._insert(db, actor, 'Requirement', {'text':'Independent original '+str(i),
            'origin':'human fixture import','scope':'outside frozen criteria'}) for i in range(count)]


def exchange(mw, ident, text=None, name='read_file', args=None, status='success', artifact=None):
    call = {'id': ident, 'name': name, 'args': args or {'file_path': '/notes.json'}, 'type': 'tool_call'}
    message = ToolMessage(text or ('Exact returned qualifier. '*500), name=name,
        tool_call_id=ident, id='return-'+ident, status=status, artifact=artifact)
    return [AIMessage('', id='action-'+ident, tool_calls=[call]), mw.bound_result(message)]


async def presented(mw, messages):
    request = SimpleNamespace(messages=messages, system_message=SystemMessage('Role remains authoritative.'))
    request.override = lambda **kw: SimpleNamespace(**{**request.__dict__, **kw})
    seen = []
    async def handler(value):
        seen.append(value)
        return AIMessage('Synthetic observation, no acceptance.')
    await mw.awrap_model_call(request, handler)
    return json.loads(seen[0].system_message.content[-1]['text'].split('\n', 1)[1])


def test_v2_reuses_context_policy_without_migrating_v1(ws):
    activate(ws)
    assert enabled(ws)
    assert ws.store.get('context_policy') is None


async def test_before_clearing_retains_identity_and_does_not_change_authority_token(ws):
    activate(ws); seed(ws); mw = TaskContext(ws, 'coordinator')
    state_before = exact_task_context(ws, 'coordinator')['state_digest']
    history = sum((exchange(mw, str(i), ('Exact returned qualifier. '+str(i))*500) for i in range(3)), [])
    update = await mw.abefore_model({'messages': history}, None)
    if update:
        history = add_messages(history, update['messages'])
    assert not history[1].additional_kwargs.get('report_preview_cleared')
    packet = await presented(mw, history)
    index = packet['received_returns']
    assert index['total'] == 3
    first = index['recent'][0]
    assert first['call_id'] == '0' and first['selection']['file_path'] == '/notes.json'
    assert first['delivery']['original_delivery']['end'] == 6000
    assert first['sha256'] == ws.store.get('tool_observation:'+first['observation_ref'])['sha256']
    assert read_observation(ws, 'coordinator', first['observation_ref'])['text'].startswith('Exact returned qualifier.')
    assert exact_task_context(ws, 'coordinator')['state_digest'] == state_before
    records_before = recovery_tool(ws, 'coordinator')()['observations']
    event_count = len(ws.store.events())
    assert await mw.abefore_model({'messages': history}, None) is None
    assert recovery_tool(ws, 'coordinator')()['observations'] == records_before
    assert len(ws.store.events()) == event_count


async def test_recent_twenty_reopen_and_exact_paging_preserve_older_returns(ws):
    activate(ws); seed(ws); mw = TaskContext(ws, 'coordinator')
    history = sum((exchange(mw, str(i), 'Public return '+str(i)) for i in range(23)), [])
    await mw.abefore_model({'messages': history}, None)
    reopened = Workspace(Store(ws.store.root))
    packet = await presented(TaskContext(reopened, 'coordinator'), [HumanMessage('Continue saved work.')])
    index = packet['received_returns']
    # The approved total-size bound may display fewer than twenty. All original
    # entries still have an exact paged path; recent omission is explicit.
    assert index['total'] == 23 and 0 < len(index['recent']) <= 20
    assert index['recent'][0]['index_offset'] == 23-len(index['recent'])
    assert index['recent'][-1]['call_id'] == '22' and index['projection_complete'] is False
    assert index['all_entries_tool'] == 'read_summary_observations'
    assert 'read_state_path' not in index
    old = recovery_tool(reopened, 'coordinator')(offset=0, limit=3)
    assert old['observations'][0]['call_id'] == '0' and old['next_offset'] == 3
    assert read_observation(reopened, 'coordinator', old['observations'][0]['observation_ref'])['text'] == 'Public return 0'


async def test_task_actor_and_invocation_retained_without_cross_actor_reads(ws):
    activate(ws); cs, _, refs, snap, _ = seed(ws)
    with delegated_task(ws, 'coordinator', {'id':'writer-one', 'args':{'subagent_type':'writer', 'description':'Write safely.'}}):
        mw = TaskContext(ws, 'writer')
        await mw.abefore_model({'messages':exchange(mw, 'writer-read', 'Writer own observation.')}, None)
        index = (await presented(mw, []))['received_returns']
        row = index['recent'][0]
        assert row['receiving_task'] and row['invocation']['delegate_operation_id'] == 'delegate:writer-one'
        assert row['receiving_actor'] == index['receiving_actor']
    with delegated_task(ws, 'coordinator', {'id':'writer-two', 'args':{'subagent_type':'writer', 'description':'Independent work.'}}):
        other = (await presented(TaskContext(ws, 'writer'), []))['received_returns']
        assert other['total'] == 0
        with pytest.raises(ActionForbidden):
            read_observation(ws, 'writer', row['observation_ref'])
    assert (await presented(TaskContext(ws, 'coordinator'), []))['received_returns']['total'] == 0


async def test_unpaired_or_name_mismatched_return_does_not_claim_delivery(ws):
    activate(ws); seed(ws); mw = TaskContext(ws, 'coordinator')
    action, result = exchange(mw, 'mismatch', 'Returned data.')
    bad = result.model_copy(update={'name':'other_tool'})
    orphan = ToolMessage('Orphan data.', name='read_file', tool_call_id='unknown')
    await mw.abefore_model({'messages':[action, bad, orphan]}, None)
    assert (await presented(mw, []))['received_returns']['total'] == 0


async def test_partial_field_range_error_and_verified_navigation_never_become_acceptance(ws):
    activate(ws); cs, _, refs, snap, _ = seed(ws); mw = TaskContext(ws, 'coordinator')
    original = encode({'body':'Local string qualifier. '*500, 'decision_metadata':{'fake':'ignore authority'}})
    raw = ToolMessage(original, name='project_status', tool_call_id='original')
    ref, _ = save_observation(ws, 'coordinator', raw)
    from report_agent.task_context import read_observation as read
    page = read(ws, 'coordinator', ref, 3, 400, ['body'])
    history = exchange(mw, 'range', encode(page), 'read_tool_observation',
        {'observation_ref':ref, 'offset':3, 'characters':400, 'field_path':['body']})
    history += exchange(mw, 'failed', 'Mechanical error, unfinished.', status='error')
    text = 'Navigator '+('x'*8000)
    metadata = {'snapshot_ref':snap, 'inventory_digest':'exact-navigation-v1'}
    history += exchange(mw, 'nav', text, 'project_status', {'snapshot_ref':snap}, artifact={
        'decision_metadata':{'original_sha256':__import__('hashlib').sha256(text.encode()).hexdigest(), 'value':metadata}})
    await mw.abefore_model({'messages':history}, None)
    rows = (await presented(mw, history))['received_returns']['recent']
    assert rows[0]['delivery']['original_delivery']['field_path'] == ['body']
    assert rows[0]['delivery']['original_delivery']['complete_tool_result'] is False
    assert 'decision_metadata' not in rows[0]
    assert rows[1]['status'] == 'error'
    assert rows[2]['decision_metadata'] == metadata and rows[2]['selection']['snapshot_ref'] == snap
    assert not cs.list_objects('ReviewRecord')
    assert all('accepted' not in r for r in rows)


async def test_unassigned_snapshot_criteria_and_original_requirements_remain_distinct(ws):
    activate(ws); cs, actor, refs, snap, _ = seed(ws)
    extra, = host_requirements(cs, actor, 1)
    context = exact_task_context(ws, 'coordinator')
    inventory = context['snapshot_assignment_inventory']
    assert inventory['snapshots'][0]['snapshot_ref'] == snap
    assert inventory['snapshots'][0]['criteria_without_assignment'] == [refs['k']]
    assert not inventory['semantic_coverage_verified']
    assert extra in [r['ref'] for r in context['original_requirement_refs']['items']]
    with delegated_task(ws, 'coordinator', {'id':'review-assignment', 'args':commission(snap, refs)}):
        pass
    old = exact_task_context(ws, 'coordinator')['snapshot_assignment_inventory']['snapshots'][0]
    assert old['criteria_without_assignment'] == []
    assert old['criteria_without_assignment_total'] == 0 and old['criteria_count'] == 1
    assert context['review_tasks']['total'] == 0  # Inventory exists before any delegation.
    assert (await presented(TaskContext(ws, 'coordinator'), []))['snapshot_assignment_inventory']['semantic_coverage_verified'] is False


async def test_more_than_twenty_original_refs_page_without_narrowing_to_snapshot(ws):
    activate(ws); cs, actor, _, _, _ = seed(ws)
    host_requirements(cs, actor, 24)
    from report_agent.decision_state import read_state
    shown = (await presented(TaskContext(ws, 'coordinator'), []))['original_requirement_refs']
    assert shown['total'] == 25
    assert shown['items']['total'] == 25 and shown['items']['read_state_path'] == ['original_requirement_refs','items']
    page = read_state(ws, 'coordinator', shown['items']['read_state_path'], offset=20)
    assert len(page['value']) == 5 and page['complete_value'] is False


async def test_v1_projection_and_capture_policy_stay_unchanged(ws):
    seed(ws); ws.store.set('context_policy', 'stateful-tools-v1'); mw = TaskContext(ws, 'coordinator')
    history = exchange(mw, 'old', 'Old public return.')
    await mw.abefore_model({'messages':history}, None)
    packet = await presented(mw, history)
    assert 'received_returns' not in packet and 'snapshot_assignment_inventory' not in packet
    assert recovery_tool(ws, 'coordinator')()['total'] == 0


@pytest.mark.parametrize('foreign', [False, True], ids=['owned-native-receipt','foreign-receipt'])
async def test_real_reviewer_navigation_wrapper_retains_owned_receipt(ws, foreign):
    activate(ws); cs, _, refs, snap, _ = seed(ws)
    from report_agent.hierarchical_tools import content_tools
    from report_agent.content_models import Ref
    from report_agent.errors import ActionRejected
    with delegated_task(ws, 'coordinator', {'id':'structural-review', 'args':commission(snap, refs)}):
        mw = TaskContext(ws, 'reviewer')
        tool = next(t for t in content_tools(ws,'reviewer') if t.__name__=='read_content_index')
        value = tool(snapshot_ref=Ref(**snap), offset=0, limit=1)
        if foreign:
            with ws.store.connect() as db:
                db.execute('UPDATE content_observations SET actor_id=? WHERE id=?', ('foreign-actor', value['receipt_id']))
        history = exchange(mw, 'structural', encode(value), 'read_content_index', {'snapshot_ref':snap,'offset':0,'limit':1})
        with ws.store.connect() as db:
            before = db.execute('SELECT count(*) FROM content_observations').fetchone()[0]
        if foreign:
            with pytest.raises(ActionRejected, match='RETURN_NAVIGATION'):
                await mw.abefore_model({'messages':history}, None)
            assert not history[1].additional_kwargs.get('report_preview_cleared')
            assert recovery_tool(ws, 'reviewer')()['total'] == 0
        else:
            await mw.abefore_model({'messages':history}, None)
            row, = recovery_tool(ws,'reviewer')()['observations']
            assert row['navigation_page'] == value['result']['snapshot_structure']
            assert row['navigation_receipt_id'] == value['receipt_id']
            assert json.loads(read_observation(ws,'reviewer',row['observation_ref'])['text']) == value
        with ws.store.connect() as db:
            assert db.execute('SELECT count(*) FROM content_observations').fetchone()[0] == before


@pytest.mark.parametrize('change', ['text','range','cleared'])
async def test_valid_owned_reference_cannot_certify_tampered_delivery(ws, change):
    activate(ws); seed(ws); mw = TaskContext(ws,'coordinator')
    ref,_ = save_observation(ws,'coordinator',ToolMessage('Original qualifier. '*600,name='read_source',tool_call_id='raw'))
    page = read_observation(ws,'coordinator',ref,10,300)
    kwargs = {'report_observation_ref':ref, 'report_observation_delivery':{
        'representation':'exact_owned_range','offset':10,'end':310,'characters':300,'complete_tool_result':False}}
    if change == 'text': page['text'] = 'FORGED'
    if change == 'range': page['offset'] = 11
    if change == 'cleared':
        kwargs['report_preview_cleared'] = True
        page = {'observation_ref':ref,'sha256':page['sha256'],'preview_cleared':True,
            'previously_presented_range':{**kwargs['report_observation_delivery'],'offset':999}}
    call = {'id':'tampered','name':'read_tool_observation','args':{'observation_ref':ref,'offset':10,'characters':300},'type':'tool_call'}
    history = [AIMessage('',tool_calls=[call]), ToolMessage(encode(page),name=call['name'],tool_call_id=call['id'],additional_kwargs=kwargs)]
    from report_agent.errors import ActionRejected
    with pytest.raises(ActionRejected, match='RETURN_DELIVERY'):
        await mw.abefore_model({'messages':history}, None)
    assert recovery_tool(ws,'coordinator')()['total'] == 0


async def test_current_index_has_total_bound_and_no_fictitious_recovery_arguments(ws):
    activate(ws); cs, actor, refs, snap, _ = seed(ws); mw=TaskContext(ws,'coordinator')
    from report_agent.content_selection import content_index
    history=[]
    # Distinct real returned snapshot pages; a dense relation page is legitimate
    # navigation, but not a license to expand every following System indefinitely.
    for i in range(25):
        new=cs.freeze(actor,'snapshot-'+str(i),refs['root'],cs.read(snap)['payload']['refs'])['result']['snapshot_ref']
        value=content_index(cs,new,0,20)
        history += exchange(mw,'index-'+str(i),encode(value),'read_content_index',{'snapshot_ref':new,'offset':0,'limit':20})
    await mw.abefore_model({'messages':history},None)
    index=(await presented(mw,[]))['received_returns']
    assert len(encode(index)) <= 12000 and index['total']==25
    assert index['projection_complete'] is False
    assert 'value_path' not in encode(index) and 'read_state_path' not in encode(index)
    assert all(r['index_offset'] < 25 for r in index['recent'])


async def test_capture_time_delivery_is_immutable_and_host_index_not_model_notes_in_v2(ws):
    activate(ws); seed(ws); mw=TaskContext(ws,'coordinator')
    history=sum((exchange(mw,str(i),('Qualifier '+str(i))*1100) for i in range(3)),[])
    update=await mw.abefore_model({'messages':history},None)
    if update:
        history=add_messages(history,update['messages'])
    assert not history[1].additional_kwargs.get('report_preview_cleared')
    before=recovery_tool(ws,'coordinator')()['observations'][0]
    assert before['delivery']['capture_phase']=='before_preview_clear'
    from report_agent.working_summary import WorkingSummary
    async def summary(prompt): return AIMessage('Model hypothesis, unverified; exact returns remain available.')
    result=await WorkingSummary(model=RunnableLambda(summary),store=ws.store,role='coordinator',
        token_counter=lambda messages:len(messages))._acreate_summary(history)
    assert 'Public return recovery index' not in result
    assert recovery_tool(ws,'coordinator')()['observations'][0] == before
    assert (await presented(mw,[HumanMessage(result)]))['received_returns']['total']==3


def test_v2_accepts_same_operator_instruction_pack_without_policy_downgrade(ws, tmp_path):
    activate(ws)
    from test_operator_instructions import pack, CATEGORY
    from report_agent.operator_instructions import sync_operator_instructions
    path=tmp_path/'operator-pack.json'; pack(path)
    manifest=ws.store.manifest
    manifest.update(operator_instruction_pack=str(path.resolve()), report_category=CATEGORY)
    ws.store.set('manifest',manifest)
    sync_operator_instructions(ws.store)
    assert ws.store.manifest['context_policy']==POLICY
    assert ws.store.get('operator_instruction_binding')['authority']=='direct_user_confirmed'


def test_unselected_snapshot_catalog_is_bounded_and_has_real_existing_pagination(ws, monkeypatch):
    activate(ws); cs, actor, refs, snap, members = seed(ws)
    for i in range(25): cs.freeze(actor,'catalog-'+str(i),refs['root'],members)
    import report_agent.task_supervision as supervision
    real=supervision.obligation_coverage; calls=[]
    def observed(*args,**kwargs): calls.append(args[1]); return real(*args,**kwargs)
    monkeypatch.setattr(supervision,'obligation_coverage',observed)
    from report_agent.decision_state import snapshot_assignment_inventory
    value=snapshot_assignment_inventory(cs)
    assert value['selection']=='available_current_heads_not_selected'
    assert value['catalog_total']==26 and len(value['snapshots'])==20 and value['catalog_complete'] is False
    assert len(calls)<=20
    from report_agent.hierarchical_tools import content_tools
    lookup=value['catalog_tool']; tool=next(t for t in content_tools(ws,'coordinator') if t.__name__==lookup['name'])
    args=lookup['arguments'].copy(); returned=[]
    while True:
        page=tool(**args); returned.extend(page['objects'])
        if page['next_offset'] is None: break
        args.update(offset=page['next_offset'],inventory_digest=page['inventory_digest'])
    assert len(returned)==26
    assert all(v['ref']['type']=='DocumentSnapshot' for v in returned)


def test_many_unassigned_criteria_are_preview_only_and_other_snapshot_task_does_not_cover(ws):
    activate(ws); cs, actor, refs, snap, members=seed(ws)
    criteria=cs.commit(actor,'many-criteria',[{'client_key':str(i),'type':'Criterion',
        'payload':{**cs.read(refs['k'])['payload'],'expected_outcome':'Independent outcome '+str(i)}} for i in range(24)])['result']['refs']
    newer=cs.freeze(actor,'larger-snapshot',refs['root'],[*members,*criteria.values()])['result']['snapshot_ref']
    with delegated_task(ws,'coordinator',{'id':'old-only','args':commission(snap,refs)}): pass
    from report_agent.decision_state import snapshot_assignment_inventory
    value=snapshot_assignment_inventory(cs)
    record=next(r for r in value['snapshots'] if r['snapshot_ref']==newer)
    assert len(record['criteria_without_assignment'])==20
    assert record['criteria_without_assignment_total']==25 and record['criteria_without_assignment_partial'] is True
    assert record['coverage_tool']['arguments']=={'snapshot_ref':newer}
    assert 'criteria' not in record  # No copied criterion payloads/all assigned scopes.


async def test_same_text_with_different_execution_status_is_not_one_success_group(ws):
    activate(ws); seed(ws); mw=TaskContext(ws,'coordinator')
    history=exchange(mw,'success','Same returned bytes.',status='success')+exchange(mw,'error','Same returned bytes.',status='error')
    await mw.abefore_model({'messages':history},None)
    value=(await presented(mw,[]))['received_returns']
    assert value['distinct_returns']==2
    assert {r['status'] for r in value['recent']}=={'success','error'}


async def test_representation_label_alone_cannot_bypass_original_range_validation(ws):
    activate(ws); seed(ws); mw=TaskContext(ws,'coordinator')
    ref,_=save_observation(ws,'coordinator',ToolMessage('Original exact data.',name='read_file',tool_call_id='raw'))
    action,result=exchange(mw,'forged-public','{"text":"forged"}')
    result=result.model_copy(update={'additional_kwargs':{'report_observation_ref':ref,
        'report_observation_delivery':{'representation':'exact-public-result-v2'}}})
    from report_agent.errors import ActionRejected
    with pytest.raises(ActionRejected,match='RETURN_DELIVERY'):
        await mw.abefore_model({'messages':[action,result]},None)
    assert recovery_tool(ws,'coordinator')()['total']==0


async def test_existing_bound_public_delivery_is_still_valid_for_v2(ws):
    activate(ws); cs,actor,refs,_,_=seed(ws)
    manifest=ws.store.manifest; manifest['decision_data_policy']='reference-data-v1'; ws.store.set('manifest',manifest)
    mw=TaskContext(ws,'coordinator')
    value=cs.read_context(actor,refs['claim'])
    history=exchange(mw,'actual-context',encode(value),'read_context',{'target_ref':refs['claim']})
    assert history[1].artifact['report_public_delivery']['owner']=='content:coordinator'
    await mw.abefore_model({'messages':history},None)
    row,=recovery_tool(ws,'coordinator')()['observations']
    assert row['observation_ref']==history[1].artifact['report_public_delivery']['observation_ref']


async def test_v1_summary_navigation_selection_matches_frozen_before_and_sdk_payload(ws,tmp_path,monkeypatch):
    from pathlib import Path
    frozen=json.loads((Path(__file__).parent/'fixtures/progress-retention-v1-summary.json').read_text(encoding='utf-8'))
    messages=exchange(TaskContext(ws,'coordinator'),'v1-summary',frozen['original'],'read_file',frozen['args'])
    from report_agent.working_summary import WorkingSummary
    async def model(prompt): return AIMessage('Exact model notes.')
    actual=await WorkingSummary(model=RunnableLambda(model),store=ws.store,role='coordinator',
        token_counter=lambda m:len(m))._acreate_summary(messages)
    expected=frozen['expected_summary']
    assert actual==expected
    from test_bounded_deadline import offline_model,close_model
    sdk=offline_model(ws,monkeypatch)
    try:
        assert sdk._get_request_payload([HumanMessage(actual)])['messages']==[
            {'role':'user','content':expected}]
    finally: await close_model(sdk)


@pytest.mark.parametrize('compact', [False, True], ids=['preview-only','native-summary'])
async def test_actual_sdk_after_clearing_and_compaction_has_navigation_not_extra_business_work(ws, monkeypatch, compact):
    activate(ws); cs, _, refs, snap, _ = seed(ws)
    members = [r for r in cs.read(snap)['payload']['refs'] if r['type']=='ContentNode']
    root_offset = members.index(refs['root'])
    from report_agent import deep_runtime
    from report_agent.deep_models import GLMChatOpenAI, model_async_client
    from report_agent.working_summary import WorkingSummary
    from test_prompt_native_sdk_inputs import completion
    summary_calls = []
    if compact:
        async def summarize(prompt):
            summary_calls.append(prompt)
            return AIMessage('Unresolved hypothesis: exact qualifier matters; do not claim acceptance.')
        monkeypatch.setattr('report_agent.working_summary.working_summary', lambda model, store, role:
            WorkingSummary(model=RunnableLambda(summarize),store=store,role=role,
                trigger=('messages',10),keep=('messages',3),token_counter=lambda messages:len(messages),trim_tokens_to_summarize=None))
    models, wires, counts = {}, [], Counter()
    def factory(role):
        if role in models: return models[role]
        client = model_async_client(ws.store, role)
        def transport(request):
            body = json.loads(request.content); wires.append((role,body)); step = counts[role]; counts[role] += 1
            tool = ('read_content_index', {'snapshot_ref':snap,'offset':root_offset,'limit':1}) if step == 0 else (
                ('write_file', {'file_path':'/working.txt','content':'Exact qualifier. '*700}) if step == 1 else (
                ('read_file', {'file_path':'/working.txt'}) if step <= 5 else None))
            result = completion(request, 'Synthetic partial work, no acceptance.', tool)
            data = json.loads(result.content)
            if tool: data['choices'][0]['message']['tool_calls'][0]['id'] += '-'+str(step)
            return httpx.Response(200, json=data)
        client._transport = httpx.MockTransport(transport); client._mounts.clear()
        models[role] = GLMChatOpenAI(model='glm-5.3',api_key='fixture-only',base_url='https://fixture.invalid/v1',
            use_responses_api=False,http_async_client=client,max_retries=0,disable_streaming=True)
        return models[role]
    try:
        result = await deep_runtime.run_report(ws, factory)
        assert result['last_error'] is None, result
        body = wires[-1][1]
        visible = json.dumps(body['messages'], ensure_ascii=False)
        assert 'received_returns' in visible and 'snapshot_assignment_inventory' in visible
        rows = recovery_tool(ws, 'coordinator')()['observations']
        assert len([r for r in rows if r['tool']=='read_file']) == 4
        assert rows[0]['observation_ref'] in visible
        nav = rows[0]['navigation_page']
        assert nav['returned_refs'] == [refs['root']] and nav['offset'] == root_offset
        assert nav['total_nodes'] == len(members)
        assert nav['nodes'][0]['kind'] == 'report' and nav['nodes'][0]['title_truncated'] is False
        assert nav['nodes'][0]['relations'][0]['ref'] == refs['edge']
        assert encode(refs['root']) in visible.replace('\\"', '"') or refs['root']['id'] in visible
        assert 'navigation_page' in visible and 'title_preview' in visible and 'relations' in visible
        assert 'Exact qualifier.' in read_observation(ws, 'coordinator', rows[2]['observation_ref'])['text']
        assert bool(summary_calls) == compact
        assert counts['coordinator'] == 7 and not cs.list_objects('ReviewRecord')
        captures = [ws.store.get(e['data']['capture_key']) for e in ws.store.events() if e['kind']=='prompt_final_http_input']
        assert len(captures) == len(wires) and captures[-1]['status'] == 'exact'
    finally:
        for model in models.values():
            await model.root_async_client.close(); model.root_client.close()
