"""Real middleware projections and exact owned recovery; zero model calls."""
import hashlib
import json
from copy import deepcopy

import pytest
from langchain_core.messages import ToolMessage

from report_agent.decision_data import refresh_history_observations
from report_agent.task_context import TaskContext, read_observation
from report_agent.store import encode
from test_hierarchical_content import ws, seed
from test_decision_data import activate
from test_deep_runtime import Driver, invoke, observation
from report_agent.deep_runtime import run_report
from langchain_core.messages import AIMessage


def identity(i):
    return {'type':'ContentNode','id':f'00000000-0000-4000-a000-{i:012d}','version':1}


def bounded(ws,tool,raw):
    message=ToolMessage(content=encode(raw),name=tool,tool_call_id='real-call',id='real-message')
    shown=TaskContext(ws,'coordinator').bound_result(message)
    return message,shown,json.loads(shown.content)


@pytest.mark.parametrize('tool', ['read_context','observe_evidence','read_content_export','read_result'])
def test_shared_large_envelope_keeps_receipt_and_honest_identity_navigation(ws,tool):
    seed(ws);activate(ws)
    refs=[identity(i) for i in range(197)]
    raw={'ok':True,'receipt_id':'saved-read-receipt','result':{
        'target_ref':{'type':'DocumentSnapshot','id':'actual-snapshot','version':1},
        'objects':[{'ref':r,'payload':{'body':{'text':'Actual source text. '*2000}}} for r in refs[:50]],
        'loaded_refs':refs[:50],'unreturned_refs':refs[50:],'total':197,'next_offset':50}}
    original,shown,packet=bounded(ws,tool,raw)
    meta=packet['metadata']; assert meta['ok'] is True and meta['receipt_id']=='saved-read-receipt'
    nav=meta['result']; assert nav['total']==197 and nav['next_offset']==50
    assert nav['target_ref']==raw['result']['target_ref']
    for field,expected in [('loaded_refs',refs[:50]),('unreturned_refs',refs[50:])]:
        assert nav[field]==expected
    assert nav==raw['result'] and packet['complete_original_in_decision'] is True
    saved=ws.store.get('tool_observation:'+packet['observation_ref'])
    assert saved['text']==original.content
    assert saved['sha256']==hashlib.sha256(original.content.encode()).hexdigest()==packet['sha256']


def test_field_recovery_uses_original_result_path_and_identity_never_truncated(ws):
    seed(ws);activate(ws)
    text='Actual text. '*2000
    # A long but complete identity must not become a literal-fragment dictionary.
    target={'type':'ContentNode','id':'x'*1250,'version':2}
    raw={'ok':True,'receipt_id':'r','result':{'target_ref':target,'text':text}}
    _,_,packet=bounded(ws,'read_context',raw)
    result=packet['metadata']['result'];assert result['target_ref']==target
    assert result['text']==text
    recovery={'observation_ref':packet['observation_ref'],'field_path':['result','text'],
              'offset':1200,'characters':6000}
    recovered=read_observation(ws,'coordinator',**recovery)
    assert recovered['text']==text[recovery['offset']:recovery['offset']+recovery['characters']]


def test_failed_envelope_preserves_code_and_no_success_semantics(ws):
    seed(ws);activate(ws)
    raw={'ok':False,'receipt_id':'failure-r','code':'INCOMPLETE_REFERENCE_CLOSURE',
         'message':'Actual missing dependency','retryable':False}
    _,_,packet=bounded(ws,'read_context',raw)
    meta=packet['metadata'];assert meta['ok'] is False and meta['retryable'] is False
    assert meta['code']==raw['code'] and meta['receipt_id']==raw['receipt_id']


def test_empty_old_envelope_refresh_preserves_identity_raw_and_read_receipt(ws):
    cs,actor,refs,_,_=seed(ws);activate(ws)
    raw=cs.read_context(actor,refs['claim'])
    _,shown,packet=bounded(ws,'read_context',raw)
    old=deepcopy(packet);old['metadata']={}
    old.pop('representation',None)
    legacy_delivery={**shown.additional_kwargs['report_observation_delivery'],
                     'representation':'metadata_and_literal_fragments'}
    old_message=shown.model_copy(update={'content':encode(old),'artifact':None,
        'additional_kwargs':{**shown.additional_kwargs,'report_observation_delivery':legacy_delivery}})
    before=ws.store.get('tool_observation:'+packet['observation_ref'])
    with ws.store.connect() as db:
        count=db.execute('SELECT COUNT(*) FROM content_observations').fetchone()[0]
    refreshed=refresh_history_observations(ws,'coordinator',[old_message])[0]
    assert refreshed.tool_call_id==old_message.tool_call_id and refreshed.id==old_message.id
    meta=json.loads(refreshed.content)['metadata'];assert meta['receipt_id']==raw['receipt_id']
    assert meta['result']['target_ref']==refs['claim']
    assert ws.store.get('tool_observation:'+packet['observation_ref'])==before
    with ws.store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM content_observations').fetchone()[0]==count
    assert refresh_history_observations(ws,'coordinator',[refreshed])[0] is refreshed
    tampered=deepcopy(old);tampered['sha256']='wrong'
    invalid=old_message.model_copy(update={'content':encode(tampered)})
    assert refresh_history_observations(ws,'coordinator',[invalid])[0] is invalid


def test_small_raw_tools_keep_shape_and_server_terminal_offset(ws):
    seed(ws);activate(ws)
    raw={'source_id':'s','blocks':[{'ordinal':1,'text':'Exact'}],'next_offset':None}
    _,_,packet=bounded(ws,'read_source_page',raw)
    assert 'envelope_representation' not in packet['metadata']
    assert packet['metadata']['next_offset'] is None
    small={'ok':True,'receipt_id':'r','result':{'loaded_refs':[identity(0)],'unreturned_refs':[],
        'total':1,'next_offset':None}}
    _,_,packet=bounded(ws,'read_context',small)
    assert packet['metadata']['result']['unreturned_refs']==[]
    assert packet['metadata']['result']['next_offset'] is None


async def test_real_native_large_context_preserves_offload_and_exact_receipt(ws):
    cs,actor,refs,base,members=seed(ws)
    literal='Complete original body; '*3000
    extras=cs.commit(actor,'many-nodes',[{'client_key':str(i),'type':'ContentNode','payload':{
        'kind':'claim','body':{'text':literal+str(i)},'claim_kind':'fact','qualifiers':{}}}
        for i in range(65)])['result']['refs']
    snap=cs.freeze(actor,'large-real-context',refs['root'],members+list(extras.values()))['result']['snapshot_ref']
    activate(ws)
    def inspect(messages):
        reply=next(m for m in reversed(messages) if isinstance(m,ToolMessage) and m.name=='read_context')
        content=reply.content
        packet=json.loads(content if isinstance(content,str) else content[-1]['text'])
        meta=packet['metadata']
        assert meta['envelope_representation']=='business-return-v1'
        assert meta['ok'] and meta['receipt_id']
        data=meta['result'];assert data['target_ref']==snap
        assert data['total']==len(members)+65 and data['next_offset']==50
        assert len(data['loaded_refs'])==50
        assert reply.additional_kwargs['report_controls_restored']
        assert literal not in str(reply.content)
        assert packet['complete_original_in_decision'] is False
        raw=ws.store.get('tool_observation:'+packet['observation_ref'])
        assert len(raw['text'])>100000
        assert json.loads(raw['text'])['receipt_id']==meta['receipt_id']
        original=json.loads(raw['text'])['result']
        assert {k:v for k,v in data.items() if k!='objects'}=={k:v for k,v in original.items() if k!='objects'}
        for i,item in enumerate(data['objects']):
            if item['ref']['type']=='ContentNode':
                marker=item['payload']['body']
                assert marker['platform_deferred'] is True
                assert marker['observation_path']==['result','objects',i,'payload','body']
                assert item['payload']['qualifiers']==original['objects'][i]['payload']['qualifiers']
            elif item['ref']['type']=='SourceArtifact':
                assert item['payload']['content']['platform_deferred'] is True
            else:
                assert item==original['objects'][i]
        return AIMessage(content='Structural navigation inspected; no content judgment.')
    driver=Driver(coordinator=[invoke('read_context',target_ref=snap,limit=50),inspect])
    outcome=await run_report(ws,driver)
    assert outcome['last_error'] is None, outcome


def test_ordinary_source_history_does_not_reread_archives(ws,monkeypatch):
    seed(ws);activate(ws)
    _,shown,_=bounded(ws,'read_source_page',{'source_id':'s','offset':0,'next_offset':1,
        'blocks':[{'ordinal':0,'locator':{'page':1},'text':'Unchanged source body '*2000}]})
    def no_read(*args,**kwargs):
        raise AssertionError('Ordinary source projection must not access the store again')
    monkeypatch.setattr(ws.store,'get',no_read)
    assert refresh_history_observations(ws,'coordinator',[shown])[0] is shown
