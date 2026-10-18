"""Registered source views and unknown admission; synthetic models, no provider."""
import hashlib
import json

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from report_agent.catalog import Catalog
from report_agent.content_models import Evidence
from report_agent.content_tasks import delegated_task
from report_agent.deep_runtime import run_report
from report_agent.evidence_analysis import SourceSelection, selected_evidence
from report_agent.errors import ActionRejected
from report_agent.source_materials import issue, block_material
from report_agent.source_tables import present_source_tables, with_source_tables
from report_agent.source_search import search_observation
from report_agent.store import digest, encode
from report_agent.text_work import produce
from test_task_supervision import ws, offline
from test_text_work import writer_call, content
from test_prepared_material import setup, payload
from test_deep_runtime import Driver, invoke, observation
from test_bounded_review import Model


def test_default_selection_and_actual_full_packet_are_unchanged(ws):
    setup(ws)
    raw = Catalog(ws.store).read('s', 0, 1)
    old = with_source_tables(ws, raw)
    assert present_source_tables(ws, raw) == old
    assert present_source_tables(ws, raw, 'full') == old
    assert SourceSelection(source_id='s').packet_selection() == {'source_id':'s','offset':0,'limit':10}
    actual = selected_evidence(ws, [{'source_id':'s','offset':0,'limit':1}], [])
    expected = [{'kind':'source_blocks','selection':{'source_id':'s','offset':0,'limit':1},
                 'selection_units':'zero-based text blocks','observation':old,'observation_sha256':digest(old)}]
    assert encode(actual) == encode(expected)


def test_references_keep_exact_blocks_and_do_not_extract_tables(ws, monkeypatch):
    setup(ws)
    import report_agent.source_tables as module
    monkeypatch.setattr(module, 'source_tables', lambda *a, **k: pytest.fail('References must not extract PDF tables'))
    raw = Catalog(ws.store).read('s',0,1)
    value = present_source_tables(ws,raw,'references')
    assert value['blocks'] == raw['blocks'] and value['next_offset'] == raw['next_offset']
    assert 'source_table_views' not in value and value['table_detail']=='references'
    assert 'not evidence that tables or information are absent' in value['table_view_note']
    search = Catalog(ws.store).search('Class')
    assert search_observation(ws,search,'references')['matches'] == search['matches']
    with pytest.raises(ActionRejected,match='SOURCE_TABLE_DETAIL'):
        present_source_tables(ws,raw,'summary')


@pytest.mark.parametrize('route',['source_selection','owned_observation'])
async def test_native_references_material_producer_adoption(ws, route):
    cs, source = setup(ws)
    manifest=ws.store.manifest
    manifest['decision_data_policy']='reference-data-v1'
    ws.store.set('manifest',manifest)
    ws.store.set('context_policy','stateful-tools-v1')
    def request(messages):
        result=observation(messages,'read_source_page')
        stored=ws.store.get('tool_observation:'+result['observation_ref'])
        raw=json.loads(stored['text'])
        assert raw['table_detail']=='references' and 'source_table_views' not in raw
        assert raw['blocks']==Catalog(ws.store).read('s',0,1)['blocks']
        return invoke('process_report_content', operation_id='work', objective='Preserve selected rule',
            object_type='Evidence', source_version_refs=[source],
            **({'source_selections':[{'source_id':'s','offset':0,'limit':1,'table_detail':'references'}]}
               if route=='source_selection' else {'observation_refs':[result['observation_ref']]}))
    def save(messages):
        result=observation(messages,'process_report_content')['metadata']
        return invoke('commit_objects',operation_id='save',objects=[{
            'client_key':'rule','type':'Evidence','text_work_id':result['text_work_id']}])
    def done(messages):
        result=observation(messages,'commit_objects')
        assert cs.read(result['result']['refs']['rule'])['payload']==Evidence.model_validate(payload(source)).model_dump()
        return AIMessage(content='Saved exact evidence.')
    driver=Driver(coordinator=[AIMessage(content='',tool_calls=[writer_call()]),AIMessage(content='Done.')],
        writer=[invoke('read_source_page',source_id='s',offset=0,limit=1,table_detail='references'),request,save,done],
        text_tool=[AIMessage(content=json.dumps(payload(source)))])
    result=await run_report(ws,driver)
    assert result['last_error'] is None
    packets=[json.loads(messages[-1].content) for role,_,messages in driver.calls if role=='text_tool']
    assert len(packets)==1 and 'references' in encode(packets[0]['evidence'])
    for bound in driver.bindings['writer']:
        read=next(t for t in bound if t['name']=='read_source_page')
        assert 'table_detail' in read['parameters']['properties']
        producer=next(t for t in bound if t['name']=='process_report_content')
        assert 'table_detail' in encode(producer['parameters']['properties']['source_selections'])


def owned_read(ws, actor, detail, legacy=False):
    value=present_source_tables(ws,Catalog(ws.store).read('s',0,1),detail)
    text=json.dumps(value,ensure_ascii=False)
    if not legacy:
        return issue(ws,actor,'read_source_page',text,block_material(value))['body_ref']
    sha=hashlib.sha256(text.encode()).hexdigest()
    ref=digest({'owner':actor.id,'tool':'read_source_page','sha256':sha})
    ws.store.set('tool_observation:'+ref,{'owner':actor.id,'tool':'read_source_page','text':text,'sha256':sha})
    return ref


@pytest.mark.parametrize('old_route,new_route',[
    ('selection','selection'),('observation','observation'),
    ('selection','observation'),('observation','selection'),('legacy','selection')])
@pytest.mark.parametrize('first,second',[('full','references'),('references','full')])
async def test_switching_view_same_owned_source_range_cannot_repeat_unknown(ws,old_route,new_route,first,second):
    setup(ws)
    with delegated_task(ws,'coordinator',writer_call()) as (_,actor):
        def materials(route,detail):
            if route=='selection':
                return {'source_selections':[{'source_id':'s','offset':0,'limit':1,'table_detail':detail}]}
            return {'observation_refs':[owned_read(ws,actor,detail,legacy=route=='legacy')]}
        original=Model(RuntimeError('Synthetic unknown response'))
        with pytest.raises(RuntimeError,match='Synthetic unknown'):
            await produce(ws,actor,original,'old','Examine this range','ContentNode',**materials(old_route,first))
        old=ws.store.get('text_work:'+actor.id+':old')
        other=Model(json.dumps(content()))
        with pytest.raises(ActionRejected,match='SAME_EVIDENCE_OUTCOME_UNRESOLVED') as error:
            await produce(ws,actor,other,'new','Changed presentation','ContentNode',**materials(new_route,second))
        assert 'same_source_selection_established' in str(error.value)
        assert other.calls==[] and len(original.calls)==1
        assert ws.store.get('text_work:'+actor.id+':old')==old
        assert ws.store.get('text_work:'+actor.id+':new') is None


async def test_changed_source_blocks_are_not_equated_to_view_change(ws):
    setup(ws)
    with ws.store.connect() as db:
        db.execute("INSERT INTO source_blocks VALUES (?,?,?,?)",('s',1,'PDF physical page 2','A separate documented condition.'))
    with delegated_task(ws,'coordinator',writer_call()) as (_,actor):
        with pytest.raises(RuntimeError):
            await produce(ws,actor,Model(RuntimeError('Unknown')),'old','Selected first block','ContentNode',
                source_selections=[{'source_id':'s','offset':0,'limit':1}])
        model=Model(json.dumps(content()))
        result=await produce(ws,actor,model,'new','Independently selected second block','ContentNode',
            source_selections=[{'source_id':'s','offset':1,'limit':1,'table_detail':'references'}])
        assert result['state']=='completed' and len(model.calls)==1


def test_reference_access_restores_original_page_and_preserves_bytes(tmp_path, monkeypatch):
    from test_document_tools import workspace, snapshot
    from test_source_tables import table_pdf
    from report_agent.document_tools import source_page_info
    import report_agent.source_tables as module
    ws = workspace(tmp_path, table_pdf(), content='Complete original related paragraph.')
    Catalog(ws.store)
    with ws.store.connect() as db:
        db.execute("UPDATE source_blocks SET locator='page 1; chars 1-36' WHERE source_id='original'")
    raw = Catalog(ws.store).read('original', 0, 1)
    before = snapshot(ws)
    original_extractor = module.source_tables
    monkeypatch.setattr(module, 'source_tables', lambda *a, **k: pytest.fail('Deferred access extracted tables'))
    deferred = present_source_tables(ws, raw, 'references')
    ref, = deferred['source_table_references']
    assert all(deferred[key] == value for key, value in raw.items())
    assert ref['original_bytes_verified'] is False and ref['status']=='not_expanded'
    assert ref['inspection']=={'tool':'inspect_source_page','arguments':{'source_id':'original','page':1}}
    assert 'repeat the read' in deferred['table_view_note']
    monkeypatch.setattr(module, 'source_tables', original_extractor)
    restored = source_page_info(ws, **ref['inspection']['arguments'])
    full = present_source_tables(ws, raw, 'full')
    assert restored['table_view']['tables'] == full['source_table_views'][0]['tables']
    assert full['source_table_views'][0]['source_sha256'] == ref['source_sha256']
    assert snapshot(ws) == before


def test_search_default_does_not_change_read_or_selection_default(ws):
    setup(ws)
    from report_agent.source_search import CONFIG_KEY, BINDING_KEY, VERSION
    chosen = {'version':VERSION, 'default_table_detail':'references'}
    ws.store.set(CONFIG_KEY, chosen)
    ws.store.set(BINDING_KEY, {'configuration':chosen,'clean_import_sha256':digest(ws.store.get('clean_import'))})
    raw = Catalog(ws.store).read('s',0,1)
    assert search_observation(ws,Catalog(ws.store).search('Class'))['table_detail']=='references'
    assert present_source_tables(ws,raw)==with_source_tables(ws,raw)
    assert selected_evidence(ws,[{'source_id':'s','offset':0,'limit':1}],[])[0]['observation']==with_source_tables(ws,raw)


@pytest.mark.parametrize('old_route,new_route',[('selection','observation'),('observation','selection')])
@pytest.mark.parametrize('field,value',[('sha256','new-file-sha'),('parser','new-parser-version')])
async def test_new_source_version_not_reinterpreted_as_archived_version(ws,old_route,new_route,field,value):
    setup(ws)
    with delegated_task(ws,'coordinator',writer_call()) as (_,actor):
        def materials(route,detail):
            return ({'source_selections':[{'source_id':'s','offset':0,'limit':1,'table_detail':detail}]}
                if route=='selection' else {'observation_refs':[owned_read(ws,actor,detail)]})
        with pytest.raises(RuntimeError):
            await produce(ws,actor,Model(RuntimeError('Unknown')),'old','Previous version','ContentNode',**materials(old_route,'full'))
        unknown=ws.store.get('text_work:'+actor.id+':old')
        manifest=ws.store.manifest
        manifest['sources'][0][field]=value
        ws.store.set('manifest',manifest)
        model=Model(json.dumps(content()))
        result=await produce(ws,actor,model,'new','Independent source version','ContentNode',**materials(new_route,'references'))
        assert result['state']=='completed' and len(model.calls)==1
        assert ws.store.get('text_work:'+actor.id+':old')==unknown


@pytest.mark.parametrize('field',['text','locator'])
def test_archived_block_tamper_cannot_borrow_current_source_identity(ws,field):
    from copy import deepcopy
    from report_agent.source_materials import representation_identity
    setup(ws)
    with delegated_task(ws,'coordinator',writer_call()) as (_,actor):
        original=selected_evidence(ws,[{'source_id':'s','offset':0,'limit':1}],[])
        changed=deepcopy(original)
        changed[0]['observation']['blocks'][0][field]='Altered historical content'
        assert representation_identity(ws,actor,original) is not None
        assert representation_identity(ws,actor,changed) is None
