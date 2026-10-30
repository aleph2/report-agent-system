"""Scoped instruction delivery/cache identity, not semantic model validation."""
import json
from types import SimpleNamespace

import pytest

from report_agent.artifact_review import bounded_artifact_review_tool
from report_agent.bounded_review import perform_review, TOOL_PROMPT
from report_agent.content_tasks import delegated_task
from report_agent.errors import ActionRejected
from report_agent.prompt_instructions import configure_report, instruction_context, review_commission
from report_agent.store import digest
from test_artifact_review import setup as artifact_setup, payload as artifact_payload
from test_bounded_review import Model, review_call
from test_hierarchical_content import seed
from test_prompt_instructions import candidate, release
from test_review_target_capability import bounded
from test_task_supervision import ws, offline


def setup(ws, kind):
    if kind == 'content':
        cs, _, refs, snap, _ = seed(ws)
        bounded(ws)
        source = next(r for r in cs.read(snap)['payload']['refs'] if r['type']=='SourceArtifact')
        call = review_call(snap,refs,reads=[source])
        model = Model()
        async def invoke(actor, operation):
            return await perform_review(ws,actor,model,operation,['rule-comparison'])
    else:
        cs, refs, snap, export, _, _, call = artifact_setup(ws,kind='export',reference=False)
        model = Model()
        async def invoke(actor, operation):
            # The exact same saved observation must survive operation identity tests.
            if not hasattr(invoke,'receipt'):
                invoke.receipt = cs.observe(actor,{'export_ref':export,'structure':{'paragraphs':[]}})['receipt_id']
            model.response = artifact_payload(snap,refs,export,[invoke.receipt],kind='export').model_dump_json()
            return await bounded_artifact_review_tool(ws,model)(operation,['rule-comparison'],[invoke.receipt])
    ws.store.set('context_policy','stateful-tools-v1')
    configure_report(ws.store,'report-a')
    return cs, call, model, invoke


@pytest.mark.parametrize('kind',['content','artifact'])
async def test_checkers_receive_only_applicable_released_versions_and_unresolved_conflicts(ws,kind):
    cs, call, model, invoke = setup(ws,kind)
    manifest_before = digest(ws.store.manifest)
    with delegated_task(ws,'coordinator',call) as (_,actor):
        good = candidate(ws,'good',scope='report',report_id='report-a',roles=['reviewer'],topic='scope',text='完整客户原文；不删限定。')
        release(ws,good)
        for r in [candidate(ws,'wrong-role',roles=['writer']),
                  candidate(ws,'wrong-report',scope='report',report_id='report-b'),
                  candidate(ws,'wrong-task',scope='assignment',report_id='report-a',task_id='other'),
                  candidate(ws,'conflict-a',topic='conflict',text='留待客户决定A'),
                  candidate(ws,'conflict-b',topic='conflict',text='留待客户决定B')]:
            release(ws,r)
        candidate(ws,'inactive',topic='candidate',text='候选未发布不适用')
        await invoke(actor,'instructions')
        actual = json.loads(model.calls[0][1][1])['commission']['scoped_instructions']
        assert actual == instruction_context(ws.store,'reviewer',task_id=actor.task_id)
        assert actual['effective'] == [good]
        assert len(actual['conflicts']) == 1
        assert {r['ref']['id'] for r in actual['conflicts'][0]['instructions']} == {'conflict-a','conflict-b'}
        assert 'conflicts remain unresolved' in model.calls[0][0][1]
        assert len(cs.list_objects('SourceArtifact')) == 1
    assert digest(ws.store.manifest) == manifest_before


@pytest.mark.parametrize('kind',['content','artifact'])
async def test_changed_instruction_cannot_reuse_prior_operation_or_judgment(ws,kind):
    _, call, model, invoke = setup(ws,kind)
    first = candidate(ws,text='版本1原文')
    release(ws,first)
    with delegated_task(ws,'coordinator',call) as (_,actor):
        await invoke(actor,'same-operation')
        from report_agent.prompt_instructions import save_instruction
        second = save_instruction(ws.store,{**first['payload'],'text':'版本2新客户要求'},expected_version=1)
        release(ws,second,expected=1)
        with pytest.raises(ActionRejected,match='OPERATION_CONFLICT'):
            await invoke(actor,'same-operation')
        assert len(model.calls) == 1
        await invoke(actor,'new-explicit-operation')
        assert len(model.calls) == 2
        assert json.loads(model.calls[1][1][1])['commission']['scoped_instructions']['effective'] == [second]


def test_no_instruction_configuration_preserves_commission_and_prompt_exactly(ws):
    actor = SimpleNamespace(role='reviewer',task_id='bound-task')
    commission,prompt = review_commission(ws.store,actor,TOOL_PROMPT)
    assert commission == {k:ws.store.manifest.get(k) for k in ('goal','scope_instruction')}
    assert prompt == TOOL_PROMPT and 'scoped_instructions' not in commission
