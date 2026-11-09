"""Bounded Writer conflict provenance must survive the same transaction as the row."""
from pathlib import Path
from types import SimpleNamespace
import pytest
from report_agent import plan_authority
from report_agent.content_store import ContentStore
from report_agent.writer_runtime import writer_session
from support.mini_judgments import advance_to_rainfall, gap_input, install_rainfall
from report_agent.mini_commission import prepare_mini_commission
from report_agent.store import Store, digest
from report_agent.workspace import Workspace
from report_agent.writer_issues import propose_material_issue, verify_issue_proposal
from report_agent.writer_assessment import save_indicator_outcome, read_indicator_step
from report_agent.hierarchical_tools import actor_for

INPUTS = Path(__file__).parent / 'fake_data/mini_commission/inputs'


@pytest.mark.parametrize('kind', ['evidence', 'gap'])
@pytest.mark.parametrize('explicit_first', [False, True])
@pytest.mark.parametrize('reverse_quotes', [False, True])
def test_conflict_in_an_outcome_reaches_verifiable_issue_once(tmp_path, kind, explicit_first, reverse_quotes):
    case = tmp_path/'case'
    receipt = prepare_mini_commission(INPUTS,case)
    ws = Workspace(Store(case))
    cs = ContentStore(ws.store)
    if kind == "evidence":
        install_rainfall(ws, receipt["plan_ref"])
    conflict = dict(basis='设计坡率 1:0.75，地勘实测坡率 1:1.0。',
        adopted_value='采用设计坡率 1:0.75，设计优先。',
        quotes=['设计坡率为 1:0.75，分三级开挖。','坡段 A：实测坡率为 1:1.0。'],
        question='请核对设计与调查坡率差异。',affects_level=True)
    with writer_session(ws, "坡段 A", SimpleNamespace(profile={"image_inputs": False}),
                        section_id="3", assessment_only=True, indicator_steps=True) as session:
        actor=session.actor
        if kind=="evidence":
            row={**advance_to_rainfall(cs,actor), "basis_kind":"direct_evidence"}
        else:
            save_indicator_outcome(cs,actor,"height","X11",{"kind":"gap", **gap_input("X11")})
            row={"kind":"gap", **gap_input("X12")}
        iid=read_indicator_step(cs,actor)['indicator_id']
        row['contrary_evidence']=conflict
        separate={**conflict,'quotes':list(reversed(conflict['quotes']))} if reverse_quotes else conflict
        if explicit_first:
            propose_material_issue(cs,actor,'reported-first',dict(kind='conflict',**separate))
        recorded=save_indicator_outcome(cs,actor,'with-conflict',iid,row)['result']
        assert recorded['issue_id']
        key='g6_issue_record:'+digest([receipt['plan_ref'],recorded['issue_id']])
        with cs.store.connect() as db:
            proposal=verify_issue_proposal(cs,db,ws.store.get(key),cs._read(db,receipt['plan_ref']), actor_for('coordinator'))
        assert proposal['issue']['adopted_value']==conflict['adopted_value']
        assert {s['quote'] for s in proposal['source_citations']}==set(conflict['quotes'])
        assert proposal['binding']=={'section_id':'3','object_id':'A'}
        explicit=propose_material_issue(cs,actor,'also-reported',dict(kind='conflict',**separate))['result']
        assert explicit['issue_id']==recorded['issue_id']
        with cs.store.connect() as db:
            assert db.execute("SELECT count(*) FROM state WHERE key LIKE 'g6_issue_record:%'").fetchone()[0]==1

from test_writer_issue_tools import reviewed_writers
from test_m1_g3_integration import method_commission


@pytest.mark.parametrize('method_commission', ['with-owner-ranks'], indirect=True)
def test_indicator_issue_uses_existing_word_excel_pipeline_and_deduplicates(reviewed_writers):
    from report_agent import writer_issues as api
    from report_agent.writer_assignments import bound_assignment
    from report_agent.system_assembler import assemble_current_report
    from report_agent.content_export import export_snapshot
    from zipfile import ZipFile
    from xml.etree import ElementTree as ET
    from openpyxl import load_workbook

    f = reviewed_writers
    payload = dict(basis='Two supplied synthetic statements require reconciliation.',
        adopted_value='Adopt design height 30 metres.', question='Confirm the competing description.',
        affects_level=True, quotes=['S1 is a design object with a 30 metre height.',
                                   'S1 is a design object'])
    # These distinct excerpts deliberately exercise the export binding only.
    # The real two-document conflict is tested above on the mini fixture.
    for index, actor in enumerate(f.actors):
        api.save_section_prose(f.cs,actor,'prose-'+str(index),
            dict(text='Slope '+str(index+1)+' context.',quotes=[payload['quotes'][0]]))

    actor = f.actors[0]
    def save(db):
        return api.save_indicator_conflict(f.cs,db,actor,'indicator-conflict',
                                           bound_assignment(f.cs,db,actor),payload)
    saved = f.cs.operation(actor,'indicator-conflict',{'conflict':payload},save)['result']
    again=api.propose_material_issue(f.cs,actor,'separate-conflict',dict(kind='conflict',**payload))['result']
    assert again['issue_id']==saved['issue_id']
    assembled=assemble_current_report(f.cs,f.co,'assemble-conflict')['result']
    exported=export_snapshot(f.cs,f.co,'export-conflict',assembled['snapshot_ref'],{'toc':False})['result']
    with ZipFile(f.ws.store.root/exported['file_ref']) as archive:
        comments=ET.fromstring(archive.read('word/comments.xml'))
        matches=[c for c in comments if payload['basis'] in ''.join(c.itertext())]
        assert len(matches)==1
        assert payload['adopted_value'] in ''.join(matches[0].itertext())
    book=load_workbook(f.ws.store.root/exported['workbook']['file_ref'])
    rows=list(book['资料澄清清单'].values)
    matches=[row for row in rows if payload['basis'] in str(row)]
    assert len(matches)==1 and payload['adopted_value'] in str(matches[0])
    anchors=f.cs.read(exported['workbook']['mapping_ref'])['payload']['anchor_records']
    assert len([a for a in anchors if a.get('issue_id')==saved['issue_id']])==1


def test_rejected_conflict_rolls_back_indicator_row_and_issue(tmp_path):
    from report_agent.errors import ActionRejected
    case=tmp_path/'case'
    prepare_mini_commission(INPUTS,case)
    ws=Workspace(Store(case))
    cs=ContentStore(ws.store)
    with writer_session(ws, "坡段 A", SimpleNamespace(profile={"image_inputs": False}),
                        section_id="3", assessment_only=True, indicator_steps=True) as session:
        actor = session.actor
        row=dict(kind="gap", **gap_input("X11"),
                 contrary_evidence=dict(basis='Conflicting facts',adopted_value='Design prevails',
                     quotes=['设计坡率为 1:0.75，分三级开挖。','This quote does not exist.'],
                     question='Check conflict',affects_level=True))
        with pytest.raises(ActionRejected):
            save_indicator_outcome(cs,actor,'invalid-conflict','X11',row)
        assert read_indicator_step(cs,actor)['indicator_id']=='X11'
        with cs.store.connect() as db:
            assert db.execute("SELECT count(*) FROM state WHERE key LIKE 'g6_issue_record:%'").fetchone()[0]==0


@pytest.mark.parametrize('quotes', [['same','same'], [' ', 'other']])
def test_conflict_quote_refusal_names_field_and_correction(quotes):
    from report_agent.writer_assessment import _step_schema
    from report_agent.message_fields import validate_message
    from report_agent.errors import ActionRejected
    model=_step_schema(('low','high'),'gap')
    with pytest.raises(ActionRejected) as caught:
        validate_message(model,dict(missing='Natural angle',question='Provide angle?',
            contrary_evidence=dict(basis='Two values',adopted_value='Design value',
                quotes=quotes,question='Confirm?',affects_level=True)))
    field=caught.value.diagnostic['fields'][0]
    assert field['field']==['contrary_evidence','quotes']
    assert 'distinct' in field['correction'] and 'nonblank' in field['correction']


def test_reversed_quotes_preserve_confirmed_issue_source_order(method_commission):
    from test_m1_g3_integration import section_plan
    from test_m1_commission_plan import save, approve, writer
    f=method_commission
    plan=section_plan(f)
    plan['objects'][0]['attributes'][0]['values'].append({
        'value':'height not stated in scope','source':f.cite('scope'),
        'reason':'Scope names the object but does not state its height.'})
    saved=save(f,plan);approve(f,saved)
    original=f.cs.read(plan_authority.decision_ref(f.ws.store))
    required=original['payload']['required_material_issues'][0]
    actor = writer(f, saved, section_ids=['4'], assessment_object_id='S1')
    value={k:required[k] for k in ('kind','basis','question')}
    value.update(adopted_value='30 metres from design',affects_level=False)
    value['quotes']=[f.cite('scope')['quote'],f.cite('design')['quote']]
    result=propose_material_issue(f.cs,actor,'required-reverse',value)['result']
    assert result['issue_id']==required['id']
    proposal=f.ws.store.get('g6_issue_record:'+digest([saved['plan_ref'],result['issue_id']]))
    assert proposal['issue']['sources']==required['sources']
    with f.cs.store.connect() as db:
        verify_issue_proposal(f.cs,db,proposal,f.cs._read(db,saved['plan_ref']),f.co)
    assert f.cs.read(original['ref'])==original


def test_step_schema_rejects_another_indicators_grade_and_alternative():
    from pydantic import ValidationError
    from report_agent.writer_assessment import _step_schema

    offered, foreign = 'Steep [50–100]', 'Dry [0–49]'
    model = _step_schema((offered,), 'assumption')
    valid = dict(grade=offered, plausible_grades=[offered], value='60',
                 rationale='Survey suggests a steep face.', quotes=['steep face'],
                 question='What is the measured angle?')
    assert model.model_validate(valid).grade == offered
    for change, field in [({'grade': foreign}, 'grade'),
                          ({'plausible_grades': [offered, foreign]}, 'plausible_grades')]:
        with pytest.raises(ValidationError) as error:
            model.model_validate({**valid, **change})
        assert error.value.errors()[0]['loc'][0] == field
