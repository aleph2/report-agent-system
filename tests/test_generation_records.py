"""Real tool/receipt/export boundary tests with a fake text service, not semantics."""
import json
from copy import deepcopy
from io import BytesIO

import pytest
from docx import Document
from jsonschema import Draft202012Validator
from langchain_core.messages import ToolMessage
from langchain_core.tools import StructuredTool

from report_agent.content_export import export_snapshot
from report_agent.content_models import ContentNode, Evidence
from report_agent.content_tasks import delegated_task
from report_agent.deep_runtime import business_tools
from report_agent.errors import ActionForbidden, ActionRejected
from report_agent.store import digest
from report_agent.task_context import TaskContext, read_observation
from report_agent.text_work import produce, adopt, output_contract, parse_output, receipt_digest
from test_bounded_review import Model
from test_decision_data import activate
from test_hierarchical_content import seed
from test_task_supervision import ws, offline


def payload():
    return {'kind':'block','body':{'text':'Actual source conflict remains unresolved.'},
        'qualifiers':{'technical_uncertainty':'The groundwater interval is not established.'},'claim_kind':'inference'}


def call(name='generation-record'):
    return {'id':name,'args':{'subagent_type':'writer','description':'Produce selected evidence-grounded content.'}}


def envelope(note='Parser processing event only.'):
    return {'payloads':[payload()],'generation_notes':[{'output_index':0,'text':note}]}


async def test_actual_producer_schema_receipt_adoption_and_word_preserve_the_boundary(ws):
    cs,_,refs,_,_=seed(ws)
    answer=envelope()
    model=Model(json.dumps(answer))
    with delegated_task(ws,'coordinator',call()) as (_,actor):
        registered={t.__name__:t for t in business_tools(ws,'writer',None,model)}
        tool=StructuredTool.from_function(coroutine=registered['process_report_content'])
        result=await tool.ainvoke({'operation_id':'produce','objective':'Use the supplied evidence',
            'object_type':'ContentNode','input_refs':[refs['claim']]})
        actual_input=json.loads(model.calls[0][1][1])
        Draft202012Validator.check_schema(actual_input['output_schema'])
        Draft202012Validator(actual_input['output_schema']).validate(answer)
        assert 'rendered in Word/Excel' in str(actual_input['output_schema'])
        stored=ws.store.get('text_work_receipt:'+result['text_work_id'])
        assert stored['result']['generation_notes']==answer['generation_notes']
        assert result['text_work_id']==receipt_digest(actor.__dict__,stored['request_hash'],[payload()],answer['generation_notes'])
        assert result['text_work_id']!=receipt_digest(actor.__dict__,stored['request_hash'],[payload()],[])
        adopted=adopt(ws,actor,result['text_work_id'],'ContentNode')
        assert adopted==payload() and 'generation_notes' not in adopted
        saved=StructuredTool.from_function(registered['save_text_node']).invoke({
            'operation_id':'adopt','text_work_id':result['text_work_id']})['result']['refs']['text']
        objects=cs.commit(actor,'save',[
            {'client_key':'root','type':'ContentNode','payload':{'kind':'report','body':{'text':'Report'},'qualifiers':{},'claim_kind':'structure'}},
            {'client_key':'edge','type':'Relation','payload':{'subject_ref':{'client_key':'root'},'object_ref':saved,'predicate':'contains','position':0,'provenance_kind':'adopted_during_generation'}}])['result']['refs']
        objects['body']=saved
        snap=cs.freeze(actor,'freeze',objects['root'],list(objects.values()))['result']['snapshot_ref']
        exported=export_snapshot(cs,actor,'export',snap)['result']
        export=cs.read(exported['export_ref'])['payload']
        document=Document(BytesIO((ws.store.root/export['file_ref']).read_bytes()))
        text='\n'.join(p.text for p in document.paragraphs)
        assert payload()['body']['text'] in text
        assert payload()['qualifiers']['technical_uncertainty'] in text
        assert answer['generation_notes'][0]['text'] not in text
        assert cs.read(objects['body'])['payload']==payload()
    with delegated_task(ws,'coordinator',call('other')) as (_,other):
        with pytest.raises(ActionForbidden,match='another task'):
            adopt(ws,other,result['text_work_id'],'ContentNode')


async def test_receipt_notes_have_bounded_presence_and_exact_owned_recovery(ws):
    import hashlib
    _,_,refs,_,_=seed(ws);activate(ws)
    answer=envelope('Long parser diagnostic. '*900)
    model=Model(json.dumps(answer))
    with delegated_task(ws,'coordinator',call()) as (_,actor):
        result=await produce(ws,actor,model,'produce','Use evidence','ContentNode',[refs['claim']])
        raw=json.dumps(result)
        shown=TaskContext(ws,'writer').bound_result(ToolMessage(content=raw,name='process_report_content',tool_call_id='work'))
        packet=json.loads(shown.content)
        assert packet['representation'] == 'exact-public-result-v2'
        meta=packet['metadata']
        assert meta['generation_notes'] == answer['generation_notes']
        assert meta['text_work_id'] == result['text_work_id']
        assert meta['output_count'] == 1 and meta['details_deferred']
        entry=meta['outputs']['entries'][0]
        assert entry['payload_digest'] == digest(payload())
        assert entry['qualifiers'] == payload()['qualifiers']
        assert entry['body_deferred'] and 'body' not in entry
        assert packet['sha256'] == hashlib.sha256(raw.encode('utf-8')).hexdigest()
        restored=ws.store.get('tool_observation:'+packet['observation_ref'])
        assert restored['text']==raw and restored['owner']==actor.id
        chunks,offset=[],0
        while True:
            page=read_observation(ws,'writer',packet['observation_ref'],offset,6000)
            assert page['sha256'] == packet['sha256'] and len(page['text']) <= 6000
            chunks.append(page['text'])
            if page['next_offset'] is None:
                break
            offset=page['next_offset']
        assert len(chunks) > 1 and ''.join(chunks) == raw
        assert ws.store.get('tool_observation:'+packet['observation_ref']) == restored
    with delegated_task(ws,'coordinator',call('different-observation-owner')):
        with pytest.raises(ActionForbidden,match='observation owner'):
            read_observation(ws,'writer',packet['observation_ref'],0,6000)


@pytest.mark.parametrize('bad',[{'output_index':1,'text':'Note'}, {'output_index':True,'text':'Note'}, {'output_index':0,'text':'  '}])
async def test_invalid_note_index_or_text_is_rejected_once_with_raw_response_preserved(ws,bad):
    _,_,refs,_,_=seed(ws)
    answer={'payloads':[payload()],'generation_notes':[bad]}
    assert list(Draft202012Validator(output_contract(ContentNode,1)).iter_errors(answer))
    model=Model(json.dumps(answer))
    with delegated_task(ws,'coordinator',call()) as (_,actor):
        with pytest.raises(ActionRejected,match='OUTPUT_CONTRACT_INVALID'):
            await produce(ws,actor,model,'bad','Use evidence','ContentNode',[refs['claim']])
        saved=ws.store.get('text_work:'+actor.id+':bad')
        assert saved['state']=='known_failed' and saved['raw_response_received']
        with pytest.raises(ActionRejected,match='PREVIOUS_OUTPUT_REJECTED'):
            await produce(ws,actor,model,'bad','Use evidence','ContentNode',[refs['claim']])
        assert len(model.calls)==1


async def test_actual_issue_workbook_retains_technical_qualifier_without_process_note(ws):
    from report_agent.content_workbook import export_workbook,read_workbook
    cs,_,refs,_,_=seed(ws)
    table={'kind':'table','body':{'columns':['Issue'], 'rows':[['Conflicting groundwater levels.']]},
        'qualifiers':{'technical_uncertainty':'Original field records require reconciliation.'},'claim_kind':'inference'}
    answer={'payloads':[table],'generation_notes':[{'output_index':0,'text':'Tool tokenization diagnostic.'}]}
    with delegated_task(ws,'coordinator',call()) as (_,actor):
        result=await produce(ws,actor,Model(json.dumps(answer)),'produce','Identify actual issues','ContentNode',[refs['claim']])
        registered={t.__name__:t for t in business_tools(ws,'writer',None,Model())}
        saved=registered['save_text_node']('adopt',result['text_work_id'])['result']['refs']['text']
        root=cs.commit(actor,'root',[{'client_key':'root','type':'ContentNode','payload':{
            'kind':'report','body':{'text':'Report'},'qualifiers':{},'claim_kind':'structure'}}])['result']['refs']['root']
        snap=cs.freeze(actor,'freeze',root,[root,saved],workbook_refs=[saved])['result']['snapshot_ref']
        exported=export_workbook(cs,actor,'excel',snap,[{'name':'Issues','table_ref':saved}])['result']
        observed=read_workbook((ws.store.root/exported['file_ref']).read_bytes())
        assert 'Conflicting groundwater levels.' in str(observed)
        assert table['qualifiers']['technical_uncertainty'] in str(observed)
        assert answer['generation_notes'][0]['text'] not in str(observed)
        assert cs.read(saved)['payload']==table


@pytest.mark.parametrize('reference_delivery', [False, True])
async def test_native_graph_adopts_enveloped_batch_and_exports_actual_word_and_excel(ws,monkeypatch,reference_delivery):
    import test_text_work as existing
    from report_agent.content_store import ContentStore
    from report_agent.content_workbook import read_workbook
    original_driver=existing.Driver
    process_note='Unique diagnostic for the native envelope test.'
    def driver_with_receipt_notes(*args,**kwargs):
        outputs=kwargs['text_tool']
        kwargs['text_tool']=[m.model_copy(update={'content':json.dumps({
            'payloads':json.loads(m.content),
            'generation_notes':[{'output_index':i,'text':process_note} for i in range(3)]})}) for m in outputs]
        return original_driver(*args,**kwargs)
    monkeypatch.setattr(existing,'Driver',driver_with_receipt_notes)
    await existing.test_native_scoped_trunk_adopts_batch_and_exports_same_snapshot_word_and_xlsx(ws,reference_delivery)
    cs=ContentStore(ws.store)
    for record in cs.list_objects('ExportArtifact'):
        p=record['payload'];raw=(ws.store.root/p['file_ref']).read_bytes()
        if p['file_ref'].endswith('.docx'):
            text='\n'.join(p.text for p in Document(BytesIO(raw)).paragraphs)
            assert 'Only the selected material was used.' in text
        else:text=str(read_workbook(raw))
        assert process_note not in text
    with ws.store.connect() as db:
        receipts=[json.loads(row[0]) for row in db.execute("SELECT value FROM state WHERE key LIKE 'text_work_receipt:%'")]
    assert len(receipts)==1
    assert len(receipts[0]['result']['generation_notes'])==3


@pytest.mark.parametrize('count',[1,2])
def test_legacy_and_enveloped_shapes_are_both_actual_schema_valid(count):
    schema=output_contract(ContentNode,count)
    Draft202012Validator.check_schema(schema)
    legacy=payload() if count==1 else [payload()]*count
    wrapped={'payloads':[payload()]*count,'generation_notes':[{'output_index':count-1,'text':'Process note'}]}
    for value in (legacy,wrapped):Draft202012Validator(schema).validate(value)
    assert parse_output(json.dumps(legacy),ContentNode,count)==([payload()]*count,[])
    assert parse_output(json.dumps(wrapped),ContentNode,count)==(wrapped['payloads'],wrapped['generation_notes'])
    assert receipt_digest({},'request',[payload()],[])==digest({'actor':{},'request':'request','payloads':[payload()]})


def test_evidence_schema_refs_resolve_and_notes_do_not_become_source_receipts():
    evidence={'source_refs':[{'type':'SourceArtifact','id':'source','version':1}],'locator':'p1','excerpt':'Text'}
    schema=output_contract(Evidence,1)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate({'payloads':[evidence],'generation_notes':[]})
    parsed,notes=parse_output(json.dumps(evidence),Evidence,1)
    assert parsed[0]['tool_receipt']=='' and notes==[]


@pytest.mark.parametrize('use_notes',[False,True])
async def test_completed_exact_response_reused_after_schema_only_change(ws,monkeypatch,use_notes):
    import report_agent.text_work as module
    _,_,refs,_,_=seed(ws)
    answer=envelope() if use_notes else payload()
    model=Model(json.dumps(answer))
    with delegated_task(ws,'coordinator',call()) as (_,actor):
        first=await produce(ws,actor,model,'once','Use evidence','ContentNode',[refs['claim']])
        original=module.output_contract
        def changed(schema,count):
            value=deepcopy(original(schema,count));value['description']+=' Schema-only clarification.'
            return value
        monkeypatch.setattr(module,'output_contract',changed)
        second=await produce(ws,actor,model,'once','Use evidence','ContentNode',[refs['claim']])
        assert second['reused'] and second['text_work_id']==first['text_work_id']
        assert second.get('generation_notes',[])==first.get('generation_notes',[])
        assert len(model.calls)==1
