"""Chapter-five projections keep every open outcome and never invent a risk level."""
from report_agent.assessment_results import unscored_result
from report_agent.commission_results import composed_nodes
from test_m1_g3_method_pack import pack_data


def test_unscored_summary_lists_all_indicators_and_defers_special_assessment_selection():
    pack=pack_data()
    result=unscored_result(pack,'rank-lookup',[r['id'] for r in pack['indicators']],{}, {})
    plan=dict(method_pack=pack,objects=[dict(object_id='A',label='Synthetic slope A')])
    section=dict(section_id='5',sources=[],result_composition=[
        dict(section_id='5.2',kind='assessment_summary'),
        dict(section_id='5.3',kind='indicator_list'),
        dict(section_id='5.4',kind='special_assessments')])
    nodes=composed_nodes(plan,section,{'A':result})
    tables=[n['body'] for n in nodes if n['kind']=='table']
    assert tables[0]['rows'][0][2:4] == ['未评分','未确定']
    assert len(tables[1]['rows']) == len(pack['indicators'])
    assert all(row[3]=='未评分' for row in tables[1]['rows'])
    assert tables[2]['rows'][0][1:3] == ['未评分','未确定']
    assert '待复核' in tables[2]['rows'][0][3]
    assert 'adopted' not in result
