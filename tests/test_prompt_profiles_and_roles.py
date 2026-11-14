"""Actual native role/tool interfaces and explicit historical compatibility."""
import json
import hashlib
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from report_agent import deep_runtime
from report_agent.content_tasks import delegated_task
from report_agent.prompt_sources import load_prompt,review_profile
from report_agent.prompt_provenance import PromptCompositionError
from report_agent.hierarchical_tools import role_prompt
from report_agent.store import Store
from report_agent.workspace import Workspace
from test_hierarchical_content import ws,seed
from test_deep_runtime import Driver,invoke,call
from test_reviewer_native_profile import native,commission


@pytest.mark.parametrize('role',['writer','reviewer','layout'])
async def test_each_native_role_keeps_its_own_effective_system_and_tool_contract(ws,role):
    native(ws);_,_,refs,snap,_=seed(ws)
    task=commission(snap,refs) if role=='reviewer' else {'subagent_type':role,'description':'Inspect synthetic task; no writes requested.'}
    if role=='layout':task['layout_snapshot_ref']=snap
    seen=[]
    def inspect(messages):
        seen.append(messages[0].text)
        assert role_prompt(role) in messages[0].text
        return AIMessage(content='Synthetic scoped observation only.')
    driver=Driver(**{'coordinator':[invoke('task',**task),AIMessage(content='Retained actual outcome.')],role:[inspect]})
    result=await deep_runtime.run_report(ws,driver)
    assert result['last_error'] is None,result
    assert len(seen)==1
    event=next(e for e in ws.store.events() if e['kind']=='prompt_model_input' and e['data']['purpose']==role)
    capture=ws.store.get(event['data']['capture_key'])
    assert capture['public_input']['review_profile']=='native-reviewer-v2'
    tool_names={t['function']['name'] for t in capture['public_input']['tools']}
    if role=='reviewer':assert {'submit_review','write_todos','read_content_index'}<=tool_names
    else:assert 'submit_review' not in tool_names
    assert not any('private' in s.get('source','') for s in capture['sources'])


async def test_role_renderer_override_cannot_change_the_independent_file_baseline(ws,monkeypatch):
    """P02/P07: a forged purpose label does not legitimize replacing a role."""
    import report_agent.hierarchical_tools as tools
    native(ws);_,_,refs,snap,_=seed(ws)
    original=tools.role_prompt
    monkeypatch.setattr(tools,'role_prompt',lambda role:load_prompt('legacy-review-organizer') if role=='reviewer' else original(role))
    driver=Driver(coordinator=[invoke('task',**commission(snap,refs)),AIMessage(content='No claimed review.')],
        reviewer=[AIMessage(content='A superficially plausible fake answer must never be used.')])
    result=await deep_runtime.run_report(ws,driver)
    from langchain_core.messages import ToolMessage
    from test_agent_duty_trace_cases import assert_delegated_failure
    assert result['last_error'] is None
    message=next(m for m in driver.calls[-1][2] if isinstance(m,ToolMessage) and m.name=='task')
    failure=assert_delegated_failure(ws,message,'PromptCompositionError')
    assert failure['error']['message'].startswith('PROMPT_STATIC_ROLE_REPLACED')
    assert failure['error']['automatic_retry'] is False
    assert not [r for r,_,_ in driver.calls if r=='reviewer']


@pytest.mark.parametrize('mode',[None,'bounded-tool-v1','native-reviewer-v2'])
def test_profile_reads_never_migrate_old_cases_and_tool_lists_do_not_leak(ws,mode):
    _,_,refs,snap,_=seed(ws)
    manifest=ws.store.manifest
    if mode is None:manifest.pop('review_execution_mode',None)
    else:manifest['review_execution_mode']=mode
    ws.store.set('manifest',manifest); before=ws.store.manifest
    assert review_profile(ws.store)==(mode or 'bounded-tool-v1')
    names=lambda:{t.__name__ for t in deep_runtime.business_tools(ws,'reviewer',None,None)}
    first=names()
    assert ws.store.manifest==before
    native(ws);assert 'submit_review' in names() and 'perform_assigned_review' not in names()
    ws.store.set('manifest',before);assert names()==first
    assert ('submit_review' in first)==(mode=='native-reviewer-v2')
    ws.store.set('manifest',{**before,'review_execution_mode':'model-selected-unknown-mode'})
    from report_agent.errors import ActionRejected
    with pytest.raises(ActionRejected,match='UNKNOWN_REVIEW_EXECUTION_PROFILE'):names()


@pytest.mark.parametrize('explicit',[False,True])
def test_cli_new_case_default_is_native_but_explicit_legacy_remains_explicit(tmp_path,monkeypatch,capsys,explicit):
    from report_agent.cli import main
    manifest={'goal':'Synthetic CLI case','sources':[{'id':'s','title':'Fixture','content':'Synthetic source.','coverage':'complete'}]}
    if explicit:manifest['review_execution_mode']='bounded-tool-v1'
    path=tmp_path/'manifest.json';path.write_text(json.dumps(manifest))
    root=tmp_path/'project'
    monkeypatch.setattr('sys.argv',['report-agent','init','--project',str(root),'--manifest',str(path)])
    assert main()==0
    assert Store(root).manifest['review_execution_mode']==('bounded-tool-v1' if explicit else 'native-reviewer-v2')
    capsys.readouterr()


def test_static_helper_migration_retains_exact_legacy_string_values():
    """P09: frozen independent hashes from the before copy, no paid identity rewrite."""
    values={
        'working-summary':'f07d90b4a03aa720187ca2232802cb3fdae5c3e24f42228ab4f4ba35b1b94e8c',
        'text-work':'0de421b8c4ab0473639d522dc8dff1529a2df72c9588536dbbf4fab84909fab0',
        'qualifier-work':'443b52eec591f0831804a4ae1e07f049f8451b027211f7fd9671a251c3422808',
        'evidence-analysis':'0ec07a4337dce6222e78086aec7cb506afbfae090a1574f3f15b06703a8cdfcd',
        'legacy-bounded-review':'91b6482bdc82f44070acb20ac5172458d1278deea0d7bd0a036f5e1159af9485',
        'legacy-review-organizer':'df8689715105bbe02eb002f5e1a1cf444298c3a467ae01781a254aa7f8f71eee',
        'source-vision':'782bb938a3449861fe1b74563d8b7402387a26de0eb958b0f05094433108bb50',
        'artifact-analysis':'bd50d73fc14138da245d336aff2ac285f8dbb8b5af51998e88efcfffa75ccdb5',
        'learning-analysis':'93c38e061a971fd2fa117a2ffab260cc8ee8034b0bf453bbbf8fb5ffa8b119f6',
        'working-state-guidance':'825455abc3eeccf1a4cf6de59645dbfd9d7d1b42269438558590ce29edff969c',
        'legacy-acceptance-guidance':'9fa51629eda87c236d03ab03d38c3af678104ff8be10526564e2fb9f59ac8811',
        'repetition-notice':'94ca24f2478788290d2c8afebcf8d55d5dd3ff2e87a7ce041bad46acf6b93d32'}
    for source,sha in values.items():assert hashlib.sha256(load_prompt(source).encode()).hexdigest()==sha
    for forbidden in ('../content-reviewer','C:/secrets','reviewer.json'):
        with pytest.raises(ValueError):load_prompt(forbidden)
