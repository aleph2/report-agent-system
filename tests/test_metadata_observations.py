"""Recovery and identity returns stay visible; C2 never restores or deduplicates them."""
import json
from copy import deepcopy

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.graph.message import add_messages

from report_agent.content_store import ContentStore
from report_agent.hierarchical_tools import actor_for
from report_agent.store import encode
from report_agent.task_context import TaskContext, save_observation, read_observation, actor_id
from test_context_editing import edited
from report_agent.deep_runtime import run_report
from test_hierarchical_content import ws
from test_decision_data import activate
from test_deep_runtime import Driver, invoke


def committed(ws, operation='commit-metadata', count=45):
    result = ContentStore(ws.store).commit(actor_for('coordinator'), operation, [
        {'client_key': 'section-' + str(n), 'type': 'ContentNode',
         'payload': {'kind': 'chapter', 'body': {'text': 'Section ' + str(n)},
                     'claim_kind': 'structure', 'qualifiers': {}}} for n in range(count)])
    assert result['ok'], result
    ref, saved = save_observation(ws, 'coordinator', ToolMessage(encode(result),
        name='commit_objects', tool_call_id=operation))
    return ref, saved


def page(ws, ref, start, length=2000, ident=None):
    ident = ident or str(start)
    return TaskContext(ws, 'coordinator').bound_result(ToolMessage(
        encode(read_observation(ws, 'coordinator', ref, start, length)),
        name='read_tool_observation', tool_call_id='call-' + ident, id='message-' + ident))


def cleared(message):
    packet = json.loads(message.content)
    delivery = message.additional_kwargs['report_observation_delivery']
    value = {k:v for k,v in packet.items() if k not in {'text','offset','end','next_offset','complete_tool_result'}}
    value.update(preview_cleared=True, previously_presented_range=delivery)
    return message.model_copy(update={'content': encode(value),
        'additional_kwargs': {**message.additional_kwargs, 'report_preview_cleared': True}})


def pairs(messages):
    result=[]
    for m in messages:
        packet=json.loads(m.content)
        delivery=m.additional_kwargs['report_observation_delivery']
        result += [AIMessage(content='',id='ai-'+m.id,tool_calls=[{'id':m.tool_call_id,
            'name':'read_tool_observation','args':{'observation_ref':packet['observation_ref'],
            'offset':delivery['offset'],'characters':max(1,delivery['end']-delivery['offset'])}}]),m]
    return result


async def test_all_identity_ranges_remain_visible_without_restore_or_duplicate_archive(ws):
    activate(ws)
    ref, saved = committed(ws)
    history = [page(ws, ref, start) for start in range(0, len(saved['text']), 2000)]
    assert len(history) > 2
    history = pairs(history)
    before = deepcopy(ws.store.get('tool_observation:' + ref))
    mw = TaskContext(ws, 'coordinator')
    update = await mw.abefore_model({'messages': history}, None)
    updated = add_messages(history, (update or {}).get('messages', []))
    updated = (await edited(ws, updated)).messages
    shown=[m for m in updated if isinstance(m,ToolMessage)]
    assert ''.join(json.loads(m.content)['text'] for m in shown) == saved['text']
    assert [(m.id,getattr(m,'tool_call_id',None)) for m in updated] == [(m.id,getattr(m,'tool_call_id',None)) for m in history]
    assert all(not m.additional_kwargs.get('report_preview_cleared') for m in shown)
    assert await mw.abefore_model({'messages': updated}, None) is None
    assert ws.store.get('tool_observation:' + ref) == before
    assert not any(e['kind']=='identity_metadata_ranges_represented' for e in ws.store.events())


async def test_duplicate_identity_ranges_keep_pairing_and_both_visible_copies(ws):
    activate(ws)
    ref, saved = committed(ws)
    history = pairs([page(ws, ref, 0, ident='first'), page(ws, ref, 2000), page(ws, ref, 0, ident='last')])
    mw = TaskContext(ws, 'coordinator')
    update = await mw.abefore_model({'messages': history}, None)
    updated = add_messages(history, (update or {}).get('messages', []))
    updated = (await edited(ws, updated)).messages
    shown=[m for m in updated if isinstance(m,ToolMessage)]
    first = json.loads(shown[0].content)
    assert first['text'] == json.loads(shown[2].content)['text'] == saved['text'][:2000]
    assert all(not m.additional_kwargs.get('report_preview_cleared') for m in shown)
    assert [(m.id,getattr(m,'tool_call_id',None)) for m in history] == [(m.id,getattr(m,'tool_call_id',None)) for m in updated]
    assert await mw.abefore_model({'messages': updated}, None) is None


@pytest.mark.parametrize('tamper', ['owner','tool','sha','ref','response','missing_operation','operation_owner',
    'extra_body','invalid_ref','failure','range','cleared_range','message_sha','altered_text'])
async def test_unproved_identity_returns_are_never_cleared_or_restored(ws, tamper):
    ref, saved = committed(ws)
    message = page(ws, ref, 0)
    ai = pairs([message])[0]
    if tamper in {'owner','tool','sha'}:
        key = {'owner':'owner','tool':'tool','sha':'text'}[tamper]
        ws.store.set('tool_observation:' + ref, {**saved, key: 'altered'})
    elif tamper in {'response','missing_operation','operation_owner'}:
        with ws.store.connect() as db:
            if tamper == 'missing_operation': db.execute('DELETE FROM content_operations WHERE operation_id=?', ('commit-metadata',))
            elif tamper == 'operation_owner': db.execute('UPDATE content_operations SET actor_id=? WHERE operation_id=?', ('other','commit-metadata'))
            else: db.execute('UPDATE content_operations SET response=? WHERE operation_id=?', ('{}','commit-metadata'))
    elif tamper in {'extra_body','invalid_ref','failure'}:
        raw = json.loads(saved['text'])
        if tamper == 'extra_body': raw['result']['body'] = 'Substantive report body'
        elif tamper == 'invalid_ref': raw['result']['refs']['bad'] = {'type':'ContentNode','id':'not-valid','version':0}
        else: raw['ok'] = False
        with ws.store.connect() as db:
            db.execute('UPDATE content_operations SET response=? WHERE operation_id=?', (encode(raw),'commit-metadata'))
        ref,_ = save_observation(ws, 'coordinator', ToolMessage(encode(raw), name='commit_objects',tool_call_id='altered'))
        message = page(ws, ref, 0)
        ai = pairs([message])[0]
    else:
        packet = json.loads(message.content)
        if tamper == 'ref': packet['observation_ref'] = 'bad-ref'
        elif tamper == 'range': packet['end'] = 9000
        elif tamper == 'message_sha': packet['sha256'] = 'bad-sha'
        elif tamper == 'altered_text': packet['text'] = 'Body differs'
        elif tamper == 'cleared_range':
            message = cleared(message)
            packet = json.loads(message.content)
            packet['previously_presented_range'] = {**packet['previously_presented_range'], 'end': 9000}
        message = message.model_copy(update={'content': encode(packet)})
    assert (await edited(ws, [ai,message])).messages == [ai,message]


async def test_zero_length_and_forged_delivery_are_not_rewritten(ws):
    ref,saved=committed(ws)
    message=page(ws,ref,0)
    ai=pairs([message])[0]
    packet=json.loads(message.content)
    forged=message.model_copy(update={'content':encode({**packet,'offset':500,'end':500,'text':''})})
    assert (await edited(ws,[ai,forged])).messages == [ai,forged]
    old=cleared(message)
    value=json.loads(old.content)
    altered={**old.additional_kwargs['report_observation_delivery'],'offset':2000,'end':4000}
    old=old.model_copy(update={'content':encode({**value,'previously_presented_range':altered}),
        'additional_kwargs':{**old.additional_kwargs,'report_observation_delivery':altered}})
    assert (await edited(ws,[ai,old])).messages == [ai,old]
    eof=page(ws,ref,len(saved['text']),1,ident='eof')
    kept=(await edited(ws,pairs([eof]))).messages[1]
    assert json.loads(kept.content)['text']=='' and json.loads(kept.content)['offset']==len(saved['text'])


async def test_final_native_input_keeps_all_receipt_and_body_pages(ws):
    activate(ws)
    ref, saved = committed(ws)
    body_ref,_ = save_observation(ws,'coordinator',ToolMessage('source prose ' * 3000,
        name='read_source',tool_call_id='body'))
    calls = [invoke('read_tool_observation',observation_ref=ref,offset=o,characters=2000)
        for o in range(0,len(saved['text']),2000)]
    calls += [invoke('read_tool_observation',observation_ref=body_ref,offset=o,characters=2000)
        for o in (0,2000,4000)]
    def inspect(messages):
        pages=[m for m in messages if isinstance(m,ToolMessage) and m.name=='read_tool_observation']
        identity=[m for m in pages if json.loads(m.content)['observation_ref']==ref]
        bodies=[m for m in pages if json.loads(m.content)['observation_ref']==body_ref]
        assert ''.join(json.loads(m.content)['text'] for m in identity)==saved['text']
        assert json.loads(bodies[0].content)['text'] == ('source prose ' * 3000)[:2000]
        assert all('text' in json.loads(m.content) for m in bodies[1:])
        return AIMessage(content='Public identity recovery only; no report acceptance.')
    driver=Driver(coordinator=[*calls,inspect])
    result = await run_report(ws,driver)
    assert result["last_error"] is None, result
    assert len(driver.calls)==len(calls)+1 and all(role=='coordinator' for role,_,_ in driver.calls)
    schema=next(t for t in driver.bindings['coordinator'][0] if t['name']=='read_summary_observations')
    props=schema['parameters']['properties']
    assert props['limit']['maximum']==20 and props['limit']['minimum']==1 and props['offset']['minimum']==0
    assert '1..20' in schema['description']
