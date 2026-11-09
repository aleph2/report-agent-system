from report_agent import issue_state, report_state
import pytest
from report_agent.errors import ActionRejected, ActionForbidden
from report_agent.store import digest, encode
from report_agent.section_writing import save_section_prose, propose_material_issue
from test_m1_g3_integration import method_commission, section_plan
from test_m1_commission_plan import save, approve, writer

@pytest.fixture
def writing(method_commission):
    f = method_commission
    saved = save(f, section_plan(f)); approve(f, saved)
    f.writer = writer(f, saved, section_ids=['4'])
    f.plan_ref = saved['plan_ref']
    f.ws.store.set('manifest', {**f.ws.store.manifest, 'assembly_contract': 'system-assembler-v1'})
    return f

def test_save_revision_replaces_citations_and_keeps_old_record(writing):
    f = writing
    first = save_section_prose(f.cs,f.writer,'p1','4','Height is 30 metres.',[f.cite('design')])['result']['refs']['prose']
    old = f.cs.read(first)
    changed = f.cite('design','S1 K1+200-K1+400.')
    second = save_section_prose(f.cs,f.writer,'p2','4','S1 lies at K1+200-K1+400.',[changed],first)['result']['refs']['prose']
    assert f.cs.read(first) == old
    assert f.cs.read(second)['payload']['citations'] == [changed]
    assert report_state.prose_ref(f.ws.store, 'prose:' + encode([f.plan_ref, '4', None])) == second
    with pytest.raises(ActionRejected,match='PROSE_CURRENT_VERSION_REQUIRED'):
        save_section_prose(f.cs,f.writer,'new-overwrite','4','Another draft.',[changed])

@pytest.mark.parametrize('text,citations,reason',[
    ('Valid project fact.',[], 'planned_citation_missing'),
    ('Before source_id: secret after', ['design'], 'internal_content'),
    ('Project OLD.', ['design','template'], 'template_is_not_project_fact_evidence')])
def test_exact_span_checks(writing,text,citations,reason):
    f=writing
    with pytest.raises(ActionRejected,match='SECTION_PROSE_CHECK_FAILED') as exc:
        save_section_prose(f.cs,f.writer,'bad','4',text,[f.cite(x) for x in citations])
    spans=exc.value.diagnostic['spans'];assert any(s['reason']==reason for s in spans)
    assert all(0<=s['start']<s['end']<=len(text) for s in spans)
    assert report_state.prose_ref(f.ws.store, 'prose:' + encode([f.plan_ref, '4', None])) is None

def test_scope_and_manual_structure_are_rejected(writing):
    f=writing
    with pytest.raises(ActionRejected,match='PROSE_ASSIGNED_EXTRACTED_SECTION_REQUIRED'):
        save_section_prose(f.cs,f.writer,'fixed','1.1','Wrong section.',[f.cite('design')])
    with pytest.raises(ActionRejected,match='RELATIONS_ARE_SYSTEM_OWNED'):
        f.cs.commit(f.writer,'rel',[{'client_key':'x','type':'Relation','payload':{}}])
    with pytest.raises(ActionRejected,match='SNAPSHOTS_ARE_SYSTEM_OWNED'):
        f.cs.freeze(f.co,'snapshot',{},[])

def test_issue_proposal_has_system_anchor_and_no_content_mutation(writing):
    f=writing
    ref=save_section_prose(f.cs,f.writer,'p','4','Height is 30 metres.',[f.cite('design')])['result']['refs']['prose']
    old=f.cs.read(ref)
    issue=dict(id='MI-test',kind='missing',object_label='S1',basis='Review needed',sources=[],adopted_value='30 metres',question='Confirm design height.',affects_level=False)
    propose_material_issue(f.cs,f.writer,'issue',ref,issue)
    saved=issue_state.get_g6_issue_record(f.ws.store,digest([f.plan_ref,issue['id']]))
    assert saved['issue']['anchor']=={'paragraph_index':0,'start':0,'end':None}
    assert f.cs.read(ref)==old
    with pytest.raises(ActionRejected,match='ISSUE_ANCHOR_IS_SYSTEM_OWNED'):
        propose_material_issue(f.cs,f.writer,'manual',ref,{**issue,'anchor':{'text':'30'}})
    with pytest.raises(ActionForbidden):
        propose_material_issue(f.cs,f.co,'foreign',ref,issue)

def test_g6_tools_expose_prose_not_snapshot_assembly(writing):
    from report_agent.hierarchical_tools import content_tools
    names={f.__name__ for f in content_tools(writing.ws,'writer')}
    assert {'save_section_prose','calculate_assessment','propose_material_issue'}<=names
    assert not names.intersection({'commit_objects','save_text_node','freeze_snapshot','derive_snapshot','materialize_planned_section','export_content_snapshot','export_content_workbook'})
    names={f.__name__ for f in content_tools(writing.ws,'coordinator')}
    assert 'request_system_delivery' in names

@pytest.fixture
def reviewed_writing(method_commission):
    from support.judgment_inputs import save_reviewed_score
    from test_writer_indicator_outcomes import attach_ranks, make_assignment

    f = method_commission
    f.plan = section_plan(f)
    attach_ranks(f)
    make_assignment(f)
    f.writer = writer(f, {'plan_ref': f.plan_ref}, section_ids=['4'])
    save_reviewed_score(f, f.actor, 'S1', f.evidence_quote)
    return f


@pytest.mark.parametrize('method_commission', ['with-owner-ranks'], indirect=True)
def test_current_saved_work_assembles_and_exports_without_manual_snapshot(reviewed_writing):
    from report_agent.system_assembler import assemble_current_report
    from report_agent.content_export import export_snapshot
    f=reviewed_writing
    save_section_prose(f.cs,f.writer,'p','4','S1 design height is 30 metres.',[f.cite('design')])
    assembled=assemble_current_report(f.cs,f.co,'assembly')['result']
    exported=export_snapshot(f.cs,f.co,'export',assembled['snapshot_ref'],{'toc':False})['result']
    assert exported['file_ref'].endswith('.docx') and exported['workbook']['file_ref'].endswith('.xlsx')


@pytest.mark.asyncio
@pytest.mark.parametrize('method_commission', ['with-owner-ranks'], indirect=True)
async def test_business_boundary_runs_delivery_and_counts_actual_new_pair(reviewed_writing):
    from types import SimpleNamespace
    from langchain_core.messages import ToolMessage
    from report_agent.deep_runtime import BusinessBoundary
    from report_agent.hierarchical_tools import content_tools
    from report_agent.delivery_guard import KEY
    from report_agent.store import encode
    f=reviewed_writing
    save_section_prose(f.cs,f.writer,'p','4','S1 design height is 30 metres.',[f.cite('design')])
    tool=next(t for t in content_tools(f.ws,'coordinator') if t.__name__=='request_system_delivery')
    boundary=BusinessBoundary(f.ws,'coordinator')
    request=SimpleNamespace(tool=None,tool_call={'name':'request_system_delivery','id':'native-export','args':{'operation_id':'pair'}})
    async def handler(req):
        result=tool(**req.tool_call['args'])
        return ToolMessage(encode(result),tool_call_id=req.tool_call['id'],name=req.tool_call['name'])
    result=await boundary.awrap_tool_call(request,handler)
    assert result.status!='error',result.content
    assert f.ws.store.get(KEY)['consecutive_rejections']==0
    with f.ws.store.connect() as db:
        assert db.execute("SELECT count(*) FROM content_versions WHERE type='ExportArtifact'").fetchone()[0]==2


def test_registered_prose_tool_keeps_exact_text_work_adoption_boundary(writing):
    from inspect import signature
    from report_agent.hierarchical_tools import content_tools
    from report_agent.text_work import guarded_tools
    tools=guarded_tools(writing.ws,'writer',None,content_tools(writing.ws,'writer'))
    tool=next(t for t in tools if t.__name__=='save_section_prose')
    fields=signature(tool).parameters
    assert 'text_work_id' in fields and not {'text','citations'}&fields.keys()


@pytest.mark.parametrize('claim_kind',['structure','calculation','inference','recommendation'])
def test_prose_claim_labels_cannot_turn_template_into_project_evidence(writing,claim_kind):
    f=writing
    with pytest.raises(ActionRejected,match='SECTION_PROSE_CHECK_FAILED') as exc:
        f.cs.commit(f.writer,'template-label',[{'client_key':'prose','type':'ContentNode','payload':{
            'kind':'block','body':{'text':'Project OLD.','section_id':'4'},'qualifiers':{},
            'claim_kind':claim_kind,'citations':[f.cite('design'),f.cite('template')]}}])
    assert any(s['reason']=='template_is_not_project_fact_evidence' for s in exc.value.diagnostic['spans'])


@pytest.mark.parametrize('claim_kind',['structure','calculation'])
def test_guarded_adoption_rejects_template_evidence_regardless_of_label(writing,monkeypatch,claim_kind):
    from report_agent.hierarchical_tools import content_tools
    import report_agent.text_work as tw
    f=writing
    payload={'kind':'block','body':{'text':'Project OLD.'},'qualifiers':{},'claim_kind':claim_kind,
             'citations':[f.cite('design'),f.cite('template')]}
    monkeypatch.setattr(tw,'adopt',lambda *args,**kwargs:payload)
    monkeypatch.setattr(tw,'actor_for_tool',lambda *args:f.writer)
    tool=next(t for t in tw.guarded_tools(f.ws,'writer',None,content_tools(f.ws,'writer')) if t.__name__=='save_section_prose')
    with pytest.raises(ActionRejected,match='SECTION_PROSE_CHECK_FAILED'):
        tool('guarded-template','4','owned-complete-text-work')


def test_new_writing_tools_use_native_operation_identity(writing):
    from report_agent.native_operation_tools import native_write_tools
    from report_agent.hierarchical_tools import content_tools
    from report_agent.text_work import guarded_tools
    f=writing
    f.ws.store.set('manifest',{**f.ws.store.manifest,'operation_identity_profile':'native-tool-runtime-v1'})
    for role,expected in [('writer',{'save_section_prose','propose_material_issue'}),('coordinator',{'request_system_delivery'})]:
        tools=native_write_tools(f.ws,role,guarded_tools(f.ws,role,None,content_tools(f.ws,role)))
        for tool in tools:
            if getattr(tool,'name',None) in expected:
                assert 'operation_id' not in tool.tool_call_schema.model_json_schema()['properties']
                expected=expected-{tool.name}
        assert not expected


def test_prose_cannot_smuggle_an_agent_authored_scoring_table(writing):
    f=writing
    table='| Indicator | Score |\n| --- | --- |\n| Height | 48 |\n'
    text='Saved project context.\n\n'+table
    with pytest.raises(ActionRejected,match='SECTION_PROSE_CHECK_FAILED') as exc:
        save_section_prose(f.cs,f.writer,'score-table','4',text,[f.cite('design')])
    spans=[s for s in exc.value.diagnostic['spans'] if s['reason']=='system_table_required']
    assert len(spans)==1
    assert text[spans[0]['start']:spans[0]['end']]==table
    assert report_state.prose_ref(f.ws.store, 'prose:' + encode([f.plan_ref, '4', None])) is None
