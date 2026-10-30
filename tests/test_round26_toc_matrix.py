"""Controlled actual LibreOffice matrix; no LLM and no historical case writes."""
from copy import deepcopy
from io import BytesIO
import re
import pytest
from docx import Document
from report_agent.content_export import export_snapshot, render_export
from report_agent.layout_capabilities import capabilities
from report_agent.office_finalize import snapshot
from test_hierarchical_content import ws,seed

@pytest.mark.parametrize('mode',['original','refresh','reuse','missing_nodes'])
def test_actual_directory_refresh_preserves_six_explicit_headings(ws,monkeypatch,mode,record_property):
    from report_agent import layout_capabilities
    if not capabilities()['directory_refresh']['available']:
        pytest.skip('Native LibreOffice/UNO unavailable; no refresh success claim')
    cs,actor,refs,_,members=seed(ws)
    ws.store.set('layout_revision_limit',None)
    nodes=[]
    for i in range(6):
        nodes.extend([
            {'client_key':'block'+str(i),'type':'ContentNode','payload':{'kind':'block',
                'body':{'text':f'{i+1} 模拟核查章节\n保留数据 {i+1}；仅为模拟，资料缺口仍保留。'},
                'qualifiers':{},'claim_kind':'structure'}},
            {'client_key':'edge'+str(i),'type':'Relation','payload':{'subject_ref':refs['root'],
                'object_ref':{'client_key':'block'+str(i)},'predicate':'contains','position':i+1,
                'provenance_kind':'adopted_during_generation'}}])
    added=cs.commit(actor,'matrix-blocks',nodes)['result']['refs']
    frozen=cs.freeze(actor,'matrix-snapshot',refs['root'],[*members,*added.values()])['result']['snapshot_ref']
    layout={'toc_depth':2,'nodes':[{'node_ref':added['block'+str(i)],'heading_level':2} for i in range(6)]}
    if mode=='reuse': layout['refresh_toc']=True
    calls=[]
    original=layout_capabilities.refresh_directory
    def refresh(store,data):
        calls.append(True)
        return original(store,data)
    monkeypatch.setattr(layout_capabilities,'refresh_directory',refresh)
    baseline=export_snapshot(cs,actor,'matrix-original',frozen,layout)['result']
    if mode=='refresh':
        changed=deepcopy(layout);changed['refresh_toc']=True
        result=export_snapshot(cs,actor,'matrix-changed',frozen,changed)['result']
    elif mode=='reuse':
        result=export_snapshot(cs,actor,'matrix-reused',frozen,layout_from_export_ref=baseline['export_ref'])['result']
    elif mode=='missing_nodes':
        result=export_snapshot(cs,actor,'matrix-incomplete-layout',frozen,{'toc_depth':2,'nodes':[]})['result']
    else: result=baseline
    payload=cs.read(result['export_ref'])['payload']
    config=payload['export_config']
    assert len(calls)=={'original':0,'refresh':1,'reuse':2,'missing_nodes':0}[mode]
    path=ws.store.root/result['file_ref']
    document=Document(BytesIO(path.read_bytes()))
    headings=[p.text for p in document.paragraphs if p.style.name=='Heading 2']
    assert len(headings)==(0 if mode=='missing_nodes' else 6)
    before,after=snapshot(ws.store.root/baseline['file_ref']),snapshot(path)
    if mode=='missing_nodes':
        assert ''.join(before['paragraphs'])==''.join(after['paragraphs'])
        assert before['tables']==after['tables']
    else: assert before==after
    if mode in {'refresh','reuse'}:
        receipt=config['finalization']
        assert receipt['owned_processes_exited'] and receipt['toc']
        entries='\n'.join(receipt['toc'])
        for heading in receipt['heading_pages']:
            if '模拟核查章节' in heading['text']:
                assert re.search(re.escape(heading['text'])+r'\s+'+str(heading['page'])+r'(?:\s|$)',entries)
        assert all(str(i+1)+' 模拟核查章节' in entries for i in range(6))
    else: assert config['finalization'] is None
    rendered=render_export(cs,actor,'matrix-render',result['export_ref'])['result']
    record_property('case_root',str(ws.store.root))
    record_property('mode',mode)
    record_property('export_ref',result['export_ref']['id'])
    assert rendered['render_ref']
