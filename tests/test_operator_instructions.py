"""Normal CLI/restart/native-input verification, no paid models."""
import json
import os
import subprocess
import sys
from pathlib import Path
import pytest
from langchain_core.messages import AIMessage
from report_agent.operator_instructions import sync_operator_instructions
from report_agent.prompt_instructions import instruction_context
from report_agent.store import Store
from report_agent.workspace import Workspace
from report_agent.errors import ActionRejected

CATEGORY='construction_safety_risk_assessment'
TEXT='报告排版参考报告自己的《报告编制格式标准》，保留完整相关段落/图表。'

def pack(path):
    value={'policy':'confirmed-operator-instructions-v1','id':'customer-direct','version':1,
        'authority':'direct_user_confirmed','provenance':'Offline direct operator fixture',
        'instructions':[{'id':'category-rule','topic':'format-and-evidence','scope':'report_category',
            'report_category':CATEGORY,'text':TEXT,'source_decision':'Exact direct fixture'}],
        'active':[{'id':'category-rule','version':1}]}
    path.write_text(json.dumps(value),encoding='utf-8')
    return value

def initialize(path,pack_path,category, *, context_policy=None):
    manifest={'goal':'Build one source-faithful report','content_contract':'hierarchical-review-v1',
        'review_entrypoint':'delegated-reviewer-v1',
        'sources':[{'id':'s','title':'Material','content':'Original fact','coverage':'complete'}]}
    if context_policy is not None:
        manifest['context_policy'] = context_policy
    source=path.parent/(path.name+'-manifest.json');source.write_text(json.dumps(manifest),encoding='utf-8')
    args=[sys.executable,'-m','report_agent.cli','init','--project',str(path),
        '--manifest',str(source),'--instruction-pack',str(pack_path),'--report-id',path.name]
    if category: args+=['--report-category',category]
    env={**os.environ,'PYTHONPATH':str(Path(__file__).resolve().parents[1]/'src')}
    result=subprocess.run(args,capture_output=True,text=True,env=env)
    assert result.returncode==0,result.stderr
    return Store(path)

@pytest.mark.parametrize('category',[CATEGORY,'design_quality_consultation',None])
async def test_cli_restart_normal_runtime_delivers_only_matching_category(tmp_path,category):
    from report_agent.deep_runtime import run_report
    from test_deep_runtime import Driver
    p=tmp_path/'pack.json';pack(p)
    store=initialize(tmp_path/'case',p,category)
    driver=Driver(coordinator=[AIMessage(content='Evidence pending; no acceptance.')])
    await run_report(Workspace(Store(store.root)),driver)
    receipt=Store(store.root).get('operator_instruction_binding')
    assert receipt['authority']=='direct_user_confirmed'
    contexts=[e['data'] for e in store.events() if e['kind']=='prompt_context_offered']
    snapshot=store.get('prompt_context_snapshot:'+contexts[0]['snapshot_id'])
    effective=snapshot['scoped_instructions']['effective']
    assert bool(effective)==(category==CATEGORY)
    from support.task_state_contract import current_task
    visible = current_task(driver.calls[0][2])['scoped_instructions']['effective']
    assert visible == effective
    assert any(TEXT in record['payload']['text'] for record in visible) == (category == CATEGORY)
    # Pack/category selects instruction scope, not a legacy runtime version.
    assert store.manifest['context_policy']=='stateful-tools-v2'
    with store.run_lock():sync_operator_instructions(Store(store.root))
    assert len(store.get('prompt_instruction_registry')['versions'])==1

@pytest.mark.parametrize('category',[CATEGORY,'design_quality_consultation',None])
async def test_explicit_legacy_context_keeps_category_instruction_routing(tmp_path, category):
    from report_agent.deep_runtime import run_report
    from test_deep_runtime import Driver
    p = tmp_path/'pack.json'; pack(p)
    store = initialize(tmp_path/'legacy', p, category, context_policy='stateful-tools-v1')
    driver = Driver(coordinator=[AIMessage(content='Scoped evidence only, not acceptance.')])
    result = await run_report(Workspace(Store(store.root)), driver)
    assert result['last_error'] is None
    assert store.manifest['context_policy'] == 'stateful-tools-v1'
    assert bool(instruction_context(store, 'coordinator')['effective']) == (category == CATEGORY)
    from support.task_state_contract import current_task
    visible = current_task(driver.calls[0][2])['scoped_instructions']['effective']
    assert visible == instruction_context(store, 'coordinator')['effective']
    assert any(TEXT in record['payload']['text'] for record in visible) == (category == CATEGORY)


def test_new_same_class_reports_use_original_version_including_version_history(tmp_path):
    p=tmp_path/'pack.json';value=pack(p)
    first=initialize(tmp_path/'first',p,CATEGORY)
    with first.run_lock():sync_operator_instructions(first)
    original=value['instructions'][0].copy()
    value['history']={'category-rule':[original]};value['version']=2
    value['instructions'][0]['text']=TEXT+' 内容不变，尺寸分页可调。'
    value['active'][0]['version']=2;p.write_text(json.dumps(value),encoding='utf-8')
    with first.run_lock():sync_operator_instructions(first)
    second=initialize(tmp_path/'second',p,CATEGORY)
    with second.run_lock():sync_operator_instructions(second)
    for store in [first,second]:
        assert len(store.get('prompt_instruction_registry')['versions'])==2
        assert instruction_context(store,'writer')['effective'][0]['ref']['version']==2
        assert not store.get('learning_config')
    assert first.get('prompt_instruction_registry')['versions'][1]['payload_digest']==second.get('prompt_instruction_registry')['versions'][1]['payload_digest']
    value['version']=3;value['active']=[];p.write_text(json.dumps(value),encoding='utf-8')
    with first.run_lock():sync_operator_instructions(first)
    assert instruction_context(first,'writer')['effective']==[]
    third=initialize(tmp_path/'third',p,CATEGORY)
    with third.run_lock():sync_operator_instructions(third)
    assert len(third.get('prompt_instruction_registry')['versions'])==2
    assert instruction_context(third,'writer')['effective']==[]

def test_missing_default_pack_is_explicit_before_models(tmp_path,monkeypatch):
    import report_agent.operator_instructions as module
    p=tmp_path/'pack.json';pack(p)
    store=initialize(tmp_path/'case',p,CATEGORY)
    manifest=dict(store.manifest);manifest.pop('operator_instruction_pack')
    store.set('manifest',manifest)
    monkeypatch.setattr(module,'DEFAULT_PACK',tmp_path/'missing.json')
    with store.run_lock(),pytest.raises(ActionRejected,match='OPERATOR_INSTRUCTION_PACK_MISSING'):
        sync_operator_instructions(store)
    assert not store.get('operator_instruction_binding')

def test_modified_same_pack_version_or_category_drift_rejected(tmp_path):
    p=tmp_path/'pack.json';value=pack(p)
    store=initialize(tmp_path/'case',p,CATEGORY)
    with store.run_lock():sync_operator_instructions(store)
    value['instructions'][0]['text']='Mutated without version'
    p.write_text(json.dumps(value),encoding='utf-8')
    with store.run_lock(),pytest.raises(ActionRejected,match='PACK_VERSION_CONFLICT'):sync_operator_instructions(store)
    pack(p)
    store.set('manifest',{**store.manifest,'report_category':'other'})
    with store.run_lock(),pytest.raises(ActionRejected,match='BINDING_IMMUTABLE'):sync_operator_instructions(store)

def test_interrupted_import_recovers_exact_versions_without_duplicate_release(tmp_path,monkeypatch):
    import report_agent.operator_instructions as module
    p=tmp_path/'pack.json';value=pack(p)
    old=value['instructions'][0].copy()
    value['history']={'category-rule':[old]};value['version']=2
    value['instructions'][0]['text']=TEXT+' 新直接确认要求。'
    value['active'][0]['version']=2;p.write_text(json.dumps(value),encoding='utf-8')
    store=initialize(tmp_path/'case',p,CATEGORY)
    real=module.save_instruction
    def interrupted(*args,**kwargs):
        result=real(*args,**kwargs)
        if result['ref']['version']==1:raise OSError('Simulated host interruption after durable save')
        return result
    monkeypatch.setattr(module,'save_instruction',interrupted)
    with store.run_lock(),pytest.raises(OSError):sync_operator_instructions(store)
    assert store.get('operator_instruction_sync_intent') and len(store.get('prompt_instruction_registry')['versions'])==1
    monkeypatch.setattr(module,'save_instruction',real)
    with store.run_lock():sync_operator_instructions(Store(store.root))
    assert len(store.get('prompt_instruction_registry')['versions'])==2
    assert instruction_context(store,'coordinator')['effective'][0]['ref']['version']==2
    assert store.get('operator_instruction_sync_intent') is None
