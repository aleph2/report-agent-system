from copy import deepcopy
from report_agent.offline_export import export_offline, hashes
from test_system_assembler import assembly_input
from test_m1_g3_integration import method_commission


def test_trusted_offline_assembler_exports_a_pair_and_keeps_source(assembly_input,tmp_path):
    f=assembly_input
    before=hashes(f.ws.store.root)
    args={k:deepcopy(f.inputs[k]) for k in ('prose_bindings','assessment_refs','issue_bindings')}
    output=tmp_path.parent/(tmp_path.name+'-assembled')
    result=export_offline(f.ws.store.root,output,assembly_input=args)
    assert result['status']=='exported; verification pending',result
    assert result['assembly_result']['assembly_contract']=='system-assembler-v1'
    assert (output/'G5-report.docx').is_file() and (output/'G5-clarifications.xlsx').is_file()
    assert hashes(f.ws.store.root)==before


def test_offline_incomplete_assembly_retains_exact_missing_input_diagnostic(assembly_input,tmp_path):
    f=assembly_input
    args={k:deepcopy(f.inputs[k]) for k in ('prose_bindings','assessment_refs','issue_bindings')}
    args['assessment_refs']=[]
    output=tmp_path.parent/(tmp_path.name+'-blocked')
    result=export_offline(f.ws.store.root,output,assembly_input=args)
    assert result['status']=='blocked' and result['source_unchanged']
    assert result['diagnostic']['missing_assessments']==['S1']
    assert not (output/'G5-report.docx').exists()
