"""Writer judgment tools bind scope, sources and locations without model calls."""
from report_agent import issue_state, report_state
from copy import deepcopy
import pytest
from pydantic import ValidationError
from report_agent import plan_authority
from report_agent import writer_issues as api
from report_agent.errors import ActionRejected
from report_agent.store import digest, encode
from test_m1_g3_integration import method_commission, section_plan
from test_m1_commission_plan import save, approve, writer


@pytest.fixture
def writers(method_commission, request):
    return _writers(method_commission, getattr(request, 'param', None))


@pytest.fixture
def reviewed_writers(method_commission):
    return _writers(method_commission, reviewed=True)


def _writers(f, option=None, *, reviewed=False):
    if reviewed:
        from test_writer_indicator_outcomes import attach_ranks
        attach_ranks(f)
    plan = section_plan(f)
    second = deepcopy(plan['objects'][0]); second.update(object_id='S2', label='Slope 2')
    plan['objects'].append(second)
    derived = next(s for s in plan['sections'] if s['section_id']=='5')
    derived['sources'] = [f.cite('template', 'Objects {COUNT}; level II {II_COUNT}; level III {III_COUNT}.')]
    derived['result_bindings'] = [{'old':marker,'object_id':None,'field':field,**extra}
        for marker,field,extra in [('{COUNT}','object_count',{}),('{II_COUNT}','level_count',{'level':'II'}),('{III_COUNT}','level_count',{'level':'III'})]]
    if option=='25-required':
        plan['reconciliations'][0]['differences']=['Retained discrepancy '+str(n) for n in range(25)]
    if option=='inventory-conflict':
        plan['objects'][0]['attributes'][0]['values'].append({'value':'31 m','source':f.cite('design'),'reason':'Conflicting synthetic record.'})
    if reviewed:
        from report_agent.catalog import Catalog
        from test_ingestion import pdf_bytes
        from support.judgment_inputs import install_test_judgment_inputs, save_reviewed_score
        quotes = {o['object_id']: o['object_id'] + ' survey records the synthetic observation.' for o in plan['objects']}
        source = Catalog(f.ws.store).import_file('issue-survey.pdf', pdf_bytes([' '.join(quotes.values())]))['source']
        from report_agent.commission_imports import install_source_roles, source_roles
        install_source_roles(f.ws.store, {**source_roles(f.ws.store), 'issue-survey.pdf': {
            'id': source['id'], 'purpose': 'source_or_applicable_standard'}})
        ref, = f.cs.capture_sources(f.co, 'capture-issue-survey', [source['id']])['result']['source_refs']
        section = next(s for s in plan['sections'] if s['section_id'] == '4')
        for obj in plan['objects']:
            citation = dict(source_ref=ref, locator='page 1', quote=quotes[obj['object_id']])
            section['sources'].append(citation)
            obj['sources'].append(citation)
    f.writer_plan = plan
    saved = save(f, plan); approve(f, saved)
    f.ws.store.set('manifest', {**f.ws.store.manifest, 'assembly_contract': 'system-assembler-v1'})
    f.plan_ref = saved['plan_ref']; f.actors = []
    for obj in ('S1', 'S2'):
        actor = writer(f, saved, section_ids=['4'], operation='write-' + obj, assessment_object_id=obj)
        f.actors.append(actor)
        if reviewed:
            install_test_judgment_inputs(f, obj, source['id'], 1, quotes[obj])
            save_reviewed_score(f, actor, obj, quotes[obj])
    return f


def issue(kind='conflict'):
    return dict(kind=kind, basis='Drawing height needs designer clarification.',
        quotes=['S1 is a design object with a 30 metre height.'], visual_pages=[],
        adopted_value='30 metres', question='Designer to clarify the competing record.', affects_level=False)


def test_object_prose_is_isolated_and_native_replay_is_stable(writers):
    f=writers
    refs=[]
    for n, actor in enumerate(f.actors):
        payload=dict(text='Slope '+str(n+1)+' context.', quotes=['S1 is a design object with a 30 metre height.'])
        result=api.save_section_prose(f.cs,actor,'prose-'+str(n),payload)
        assert api.save_section_prose(f.cs,actor,'prose-'+str(n),payload)==result
        refs.append(result['result']['refs']['prose'])
    assert refs[0]!=refs[1]
    assert report_state.prose_ref(f.ws.store, 'prose:' + encode([f.plan_ref, '4', None])) is None
    for obj,ref in zip(('S1','S2'),refs):
        assert report_state.prose_ref(f.ws.store, 'prose:' + encode([f.plan_ref, '4', obj])) == ref
    changed=dict(text='Changed context.',quotes=['S1 is a design object with a 30 metre height.'])
    with pytest.raises(ActionRejected,match='OPERATION_CONFLICT'):
        api.save_section_prose(f.cs,f.actors[0],'prose-0',changed)


def test_issue_before_prose_has_system_id_and_deterministic_binding(writers):
    f=writers
    for n,kind in enumerate(('conflict','missing')):
        response=api.propose_material_issue(f.cs,f.actors[n],'issue-'+kind,issue(kind))
        key='g6_issue_record:'+digest([f.plan_ref,response['result']['issue_id']])
        saved=issue_state.get_g6_issue_record(f.ws.store, key.split(':', 1)[1])
        assert saved['binding']==({'section_id':'4','object_id':'S1'} if kind=='conflict' else {'section_id':'4'})
        assert saved['issue']['object_label']=='Slope '+str(n+1)
        assert saved['issue']['anchor']=={'paragraph_index':0,'start':0,'end':None}
        assert saved['source_citations'][0]['source_ref']==f.sources['design']
        assert 'node_ref' not in saved
        assert response['result']['proposal_digest']==digest(saved)
        assert api.propose_material_issue(f.cs,f.actors[n],'issue-'+kind,issue(kind))==response


@pytest.mark.parametrize('field,value',[('anchor',{'text':'manual'}),('node_ref',{}),('id','invented'),('object_label','other'),('section_id','5'),('sources',[])])
def test_public_models_reject_manual_identifiers_and_locations(writers,field,value):
    with pytest.raises(ValidationError):
        api.propose_material_issue(writers.cs,writers.actors[0],'manual-'+field,{**issue(),field:value})
    functions=api.tool_functions(writers.cs,lambda:writers.actors[0])
    model=next(t for t in functions if t.__name__=='propose_material_issue').message_model
    with pytest.raises(ValidationError): model.model_validate({**issue(),field:value})


def test_typed_issue_receipt_tampering_blocks_assembly(writers):
    from report_agent.system_assembler import _prepare, _current_selections
    f=writers
    result=api.propose_material_issue(f.cs,f.actors[0],'issue',issue())['result']
    key='g6_issue_record:'+digest([f.plan_ref,result['issue_id']])
    proposal=issue_state.get_g6_issue_record(f.ws.store, key.split(':', 1)[1]);proposal['issue']['basis']='Forged basis'
    issue_state.set_g6_issue_record(f.ws.store, key.split(':', 1)[1],proposal)
    with f.ws.store.connect() as db:
        report=_prepare(f.cs,db,f.co,**_current_selections(f.cs,db),current=True)[0]
    assert any(p['code']=='issue_proposal_invalid' for p in report['problems'])


@pytest.mark.parametrize('method_commission', ['with-owner-ranks'], indirect=True)
def test_object_prose_and_typed_issues_assemble_to_one_word_excel_pair(reviewed_writers):
    from report_agent.system_assembler import assemble_current_report
    from report_agent.content_export import export_snapshot
    f=reviewed_writers; ids=[]
    for n,actor in enumerate(f.actors):
        api.save_section_prose(f.cs,actor,'p'+str(n),dict(text='Slope '+str(n+1)+' unique prose.',
            quotes=['S1 is a design object with a 30 metre height.']))
        ids.append(api.propose_material_issue(f.cs,actor,'i'+str(n),issue(('conflict','missing')[n]))['result']['issue_id'])
    assembled=assemble_current_report(f.cs,f.co,'assembly')['result']
    records=[f.cs.read(ref) for ref in f.cs.read(assembled['snapshot_ref'])['payload']['refs']]
    nodes=[r for r in records if r['ref']['type']=='ContentNode']
    byid={i['id']:r for r in nodes for i in r['payload']['body'].get('material_issues',[])}
    assert byid[ids[0]]['payload']['body']['text']=='4.1 Slope 1'
    assert byid[ids[1]]['payload']['body']['text']=='4 Assessment'
    edges=[r['payload'] for r in records if r['ref']['type']=='Relation']
    for n in range(2):
        prose=next(r for r in nodes if r['payload']['body'].get('text')=='Slope '+str(n+1)+' unique prose.')
        parent=next(e['subject_ref'] for e in edges if e['object_ref']==prose['ref'])
        assert f.cs.read(parent)['payload']['body']['text']=='4.'+str(n+1)+' Slope '+str(n+1)
    exported=export_snapshot(f.cs,f.co,'export',assembled['snapshot_ref'],{'toc':False})['result']
    assert exported['file_ref'].endswith('.docx') and exported['workbook']['file_ref'].endswith('.xlsx')
    from zipfile import ZipFile
    from xml.etree import ElementTree as ET
    from openpyxl import load_workbook
    with ZipFile(f.ws.store.root/exported['file_ref']) as archive:
        comments=ET.fromstring(archive.read('word/comments.xml'))
    assert len([c for c in comments if c.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}author') == '待核'])==len(byid)
    book=load_workbook(f.ws.store.root/exported['workbook']['file_ref'])
    rows=list(book['资料澄清清单'].values)
    assert len(rows)-1==len(byid)
    mapping=f.cs.read(exported['workbook']['mapping_ref'])['payload']['anchor_records']
    for issue_id in ids:
        assert len([a for a in mapping if a.get('issue_id')==issue_id])==1


@pytest.mark.parametrize('writers',['25-required'],indirect=True)
def test_new_issue_does_not_replace_any_of_25_legacy_obligations_or_guess_routes(writers):
    from report_agent.system_assembler import _prepare, _current_selections
    f=writers
    decision_ref=plan_authority.decision_ref(f.ws.store)
    original=deepcopy(f.cs.read(decision_ref))
    required=original['payload']['required_material_issues']
    assert len(required)==25
    result=api.propose_material_issue(f.cs,f.actors[0],'new-issue',issue())['result']
    assert result['issue_id'] not in {i['id'] for i in required}
    with f.ws.store.connect() as db:
        report=_prepare(f.cs,db,f.co,**_current_selections(f.cs,db),current=True)[0]
    assert set(report['missing_issue_records'])=={i['id'] for i in required}
    assert set(report['missing_issue_bindings'])=={i['id'] for i in required}
    assert set(report['missing_issue_routes'])=={i['id'] for i in required}
    assert f.cs.read(decision_ref)==original


@pytest.mark.parametrize('writers',['inventory-conflict'],indirect=True)
def test_exact_required_inventory_issue_identity_is_reused_without_changing_obligation(writers):
    f=writers
    original=deepcopy(f.cs.read(plan_authority.decision_ref(f.ws.store)))
    required=original['payload']['required_material_issues'][0]
    value={**issue(),**{k:required[k] for k in ('kind','basis','question')}}
    result=api.propose_material_issue(f.cs,f.actors[0],'inventory-issue',value)['result']
    assert result['issue_id']==required['id']
    proposal=issue_state.get_g6_issue_record(f.ws.store,digest([f.plan_ref,result['issue_id']]))
    assert {k:proposal['issue'][k] for k in required}==required
    assert f.cs.read(original['ref'])==original


def test_flat_prose_schema_exposes_judgments_only_and_matches_backend(writers):
    functions=api.tool_functions(writers.cs,lambda:writers.actors[0])
    model=next(t for t in functions if t.__name__=='save_section_prose').message_model
    assert set(model.model_fields)=={'text','quotes','visual_pages'}
    with pytest.raises(ValidationError):
        api.save_section_prose(writers.cs,writers.actors[0],'manual-prose',
            {'text':'Context.','quotes':[],'section_id':'4'})
    with pytest.raises(ValidationError):
        model.model_validate({'text':'Context.','quotes':[],'section_id':'4'})


def test_source_quote_forgery_and_assignment_revocation_are_not_cached_successes(writers):
    from report_agent.system_assembler import _prepare, _current_selections
    from report_agent.errors import ActionForbidden
    f=writers
    response=api.propose_material_issue(f.cs,f.actors[0],'issue',issue())
    key='g6_issue_record:'+digest([f.plan_ref,response['result']['issue_id']])
    proposal=issue_state.get_g6_issue_record(f.ws.store, key.split(':', 1)[1])
    proposal['source_citations'][0]['quote']='Not in the source.'
    issue_state.set_g6_issue_record(f.ws.store, key.split(':', 1)[1],proposal)
    with f.ws.store.connect() as db:
        report=_prepare(f.cs,db,f.co,**_current_selections(f.cs,db),current=True)[0]
    assert any(p['code']=='issue_proposal_invalid' and 'QUOTE_NOT_AT_SOURCE' in p['reason'] for p in report['problems'])
    revised = deepcopy(f.writer_plan)
    revised['open_questions'].append('Review the revised assignment.')
    next_plan = save(f, revised, operation='supersede-assignment')
    assert next_plan['plan_ref'] != f.plan_ref
    with pytest.raises((ActionRejected,ActionForbidden)):
        api.propose_material_issue(f.cs,f.actors[0],'issue',issue())


def test_prose_receipt_pins_exact_professional_input_even_when_sources_resolve_identically(writers,monkeypatch):
    f=writers
    citation=f.cite('design','S1 is a design object with a 30 metre height.')
    monkeypatch.setattr('report_agent.writer_assessment.resolve_judgment_sources',lambda *a,**k:[citation])
    value={'text':'Context.','quotes':['first exact quote']}
    api.save_section_prose(f.cs,f.actors[0],'exact-request',value)
    with pytest.raises(ActionRejected,match='OPERATION_CONFLICT'):
        api.save_section_prose(f.cs,f.actors[0],'exact-request',{**value,'quotes':['another exact quote']})
