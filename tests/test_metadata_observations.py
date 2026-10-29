"""Identity-only receipt representation, including the final native model boundary."""
import json
from copy import deepcopy

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.graph.message import add_messages

from report_agent.content_store import ContentStore
from report_agent.hierarchical_tools import actor_for
from report_agent.store import encode
from report_agent.task_context import TaskContext, save_observation, read_observation, actor_id
from report_agent.metadata_observations import identity_receipt, retain_identity_ranges
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


async def test_old_metadata_ranges_restore_without_new_reads_and_are_idempotent(ws):
    activate(ws)
    ref, saved = committed(ws)
    history = [page(ws, ref, start) for start in range(0, len(saved['text']), 2000)]
    assert len(history) > 2
    history[:-2] = [cleared(m) for m in history[:-2]]
    history = pairs(history)
    before = deepcopy(ws.store.get('tool_observation:' + ref))
    mw = TaskContext(ws, 'coordinator')
    from report_agent.task_context import restore_cleared_previews
    assert await mw.abefore_model({'messages': history}, None) is None
    updated = restore_cleared_previews(ws, 'coordinator', history)
    shown=[m for m in updated if isinstance(m,ToolMessage)]
    assert ''.join(json.loads(m.content)['text'] for m in shown) == saved['text']
    assert [(m.id,getattr(m,'tool_call_id',None)) for m in updated] == [(m.id,getattr(m,'tool_call_id',None)) for m in history]
    assert await mw.abefore_model({'messages': updated}, None) is None
    assert ws.store.get('tool_observation:' + ref) == before
    assert all(json.loads(m.content).get('preview_cleared') for m in history if isinstance(m,ToolMessage) and json.loads(m.content).get('preview_cleared'))


async def test_duplicates_keep_pairing_and_only_latest_exact_range(ws):
    activate(ws)
    ref, saved = committed(ws)
    history = pairs([page(ws, ref, 0, ident='first'), page(ws, ref, 2000), page(ws, ref, 0, ident='last')])
    mw = TaskContext(ws, 'coordinator')
    assert await mw.abefore_model({'messages': history}, None) is None
    shown=[m for m in history if isinstance(m,ToolMessage)]
    assert json.loads(shown[0].content)['text'] == saved['text'][:2000]
    assert json.loads(shown[2].content)['text'] == saved['text'][:2000]
    assert shown[0].tool_call_id != shown[2].tool_call_id


@pytest.mark.parametrize('tamper', ['owner','tool','sha','ref','response','missing_operation','operation_owner',
    'extra_body','invalid_ref','failure','range','cleared_range','message_sha','altered_text'])
def test_no_retention_without_exact_owned_original_operation_and_range(ws, tamper):
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
    assert retain_identity_ranges(ws, 'coordinator', [ai,message])[1] is message


def test_zero_length_and_forged_delivery_cannot_expand_range(ws):
    ref,saved=committed(ws)
    message=page(ws,ref,0)
    ai=pairs([message])[0]
    packet=json.loads(message.content)
    forged=message.model_copy(update={'content':encode({**packet,'offset':500,'end':500,'text':''})})
    assert retain_identity_ranges(ws,'coordinator',[ai,forged])[1] is forged
    old=cleared(message)
    value=json.loads(old.content)
    altered={**old.additional_kwargs['report_observation_delivery'],'offset':2000,'end':4000}
    old=old.model_copy(update={'content':encode({**value,'previously_presented_range':altered}),
        'additional_kwargs':{**old.additional_kwargs,'report_observation_delivery':altered}})
    assert retain_identity_ranges(ws,'coordinator',[ai,old])[1] is old
    eof=page(ws,ref,len(saved['text']),1,ident='eof')
    kept=retain_identity_ranges(ws,'coordinator',pairs([eof]))[1]
    assert json.loads(kept.content)['text']=='' and json.loads(kept.content)['offset']==len(saved['text'])


async def test_final_native_input_keeps_all_receipt_pages_but_only_two_body_pages(ws):
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
        assert json.loads(bodies[0].content)['preview_cleared']
        assert all('text' in json.loads(m.content) for m in bodies[1:])
        return AIMessage(content='Public identity recovery only; no report acceptance.')
    driver=Driver(coordinator=[*calls,inspect])
    await run_report(ws,driver)
    assert len(driver.calls)==len(calls)+1 and all(role=='coordinator' for role,_,_ in driver.calls)
    schema=next(t for t in driver.bindings['coordinator'][0] if t['name']=='read_summary_observations')
    props=schema['parameters']['properties']
    assert props['limit']['maximum']==20 and props['limit']['minimum']==1 and props['offset']['minimum']==0
    assert '1..20' in schema['description']
