"""Exercise native ingestion, scripted plan/owner and the real Writer assignment without dispatch."""
from pathlib import Path
import shutil

import pytest

from report_agent.content_store import ContentStore
from report_agent.content_tasks import delegated_task
from report_agent.document_tools import source_page_info
from report_agent.errors import ActionRejected
from report_agent.mini_commission import INPUT_SHA256, METHOD_SOURCE_NAME, prepare_mini_commission
from report_agent.store import Store
from report_agent.workspace import Workspace
from report_agent.writer_assessment import read_indicator_step


INPUTS = Path(__file__).parent / 'fake_data/mini_commission/inputs'


def test_prepared_writer_receives_facts_ranks_and_object_pages_without_judgments(tmp_path):
    case = tmp_path/'case'
    receipt = prepare_mini_commission(INPUTS, case)
    store = Store(case)
    ws, cs = Workspace(store), ContentStore(store)
    assert receipt['fixture_sha256'] == INPUT_SHA256
    assert receipt['object_ids'] == ['A', 'B'] and receipt['assessment_section_id'] == '3'
    decision = cs.read(receipt['decision_ref'])
    assert decision['owner_id'] == 'operator' and decision['payload']['plan_ref'] == receipt['plan_ref']
    assert [r['object_id'] for r in decision['payload']['reductions']] == ['C']
    plan = cs.read(receipt['plan_ref'])['payload']
    assert plan['sections'][0]['text'] == '本报告仅用于青禾路堑工程模拟委托的验证。'
    assert cs.list_objects('Assessment') == [] and cs.list_objects('DelegatedTask') == []
    by_name = {s.get('filename', s['title']):s for s in store.source_catalog()}
    assert set(by_name) == set(INPUT_SHA256) | {METHOD_SOURCE_NAME}
    assert all(by_name[name]['sha256'] == sha for name, sha in INPUT_SHA256.items())
    empty = source_page_info(ws, by_name['06_drawing.pdf']['id'], 1)
    assert not empty['native_text'].strip() and not empty['frozen_text_blocks']
    for oid, height, length, page in [('A','18','120',1), ('B','25','80',2)]:
        call = {'name':'task','id':'assign-'+oid,'args':{'subagent_type':'writer','description':'Isolated verification.',
                'section_ids':['3'],'assessment_object_id':oid}}
        with delegated_task(ws,'coordinator',call) as (_, actor):
            step = read_indicator_step(cs, actor)
            assert step['indicator_id'] == 'X11' and step['rank'] == 1 and step['progress'] == {'recorded':0,'total':11}
            assert any('设计与地勘不一致时以设计为主' in row['interpretation'] for row in step['owner_conventions'])
            facts = {row['name']:row['values'] for row in step['inventory_facts']}
            assert (facts['坡高（m）'][0]['value'], facts['坡长（m）'][0]['value']) == (height,length)
            assert facts['施工开始日期'][0]['value'] == '2026-04-15'
            assert '2026-03-01' in facts['施工开始日期'][0]['source']['quote']
            assert f'page {page}' in facts['坡高（m）'][0]['source']['location']
            if oid=='B':
                assert facts['地下水调查记录'][0]['value'] is None
                assert '未提供地下水调查记录' in facts['地下水调查记录'][0]['source']['quote']
            assert {obj['label'] for obj in step['boundary']['excluded_objects']} == {'坡段 C'}
    with pytest.raises(ActionRejected):
        call['id']='out-of-range';call['args']['assessment_object_id']='C'
        with delegated_task(ws,'coordinator',call):
            pytest.fail('An excluded object was assigned')
    assert cs.list_objects('Assessment') == []


def test_scripted_owner_rejects_modified_or_extra_inputs_before_case_creation(tmp_path):
    copied = tmp_path/'inputs'
    shutil.copytree(INPUTS, copied)
    (copied/'expected.json').write_text('{}')
    with pytest.raises(ValueError,match='UNEXPECTED_OR_MISSING_INPUT'):
        prepare_mini_commission(copied, tmp_path/'case')
    (copied/'expected.json').unlink()
    (copied/'04_design.pdf').write_bytes(b'replaced')
    with pytest.raises(ValueError,match='DIGEST_MISMATCH'):
        prepare_mini_commission(copied, tmp_path/'case')
    assert not (tmp_path/'case').exists()
