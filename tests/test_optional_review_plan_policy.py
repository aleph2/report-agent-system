import pytest
from langchain_core.messages import AIMessage

from report_agent import deep_runtime
from report_agent.cli import FRESH_NATIVE_DEFAULTS
from report_agent.content_tasks import delegated_task
from report_agent.errors import ActionRejected
from report_agent.handoff_release import release
from test_deep_runtime import Driver, call, invoke, observation
from test_deliverable_declaration_v4 import case
from test_review_work_units import configured


def test_fresh_defaults_do_not_force_review_plan():
    assert FRESH_NATIVE_DEFAULTS.get('review_plan_contract') != 'work-units-v1'


def test_optional_review_contract_is_captured_without_reinterpreting_old_default(case):
    cs, _, ws, _ = configured(case)
    from report_agent.prompt_sources import validate_review_plan_contract
    base = {k:v for k,v in cs.store.manifest.items() if k != 'review_plan_contract'}
    old = release(base)
    optional = release({**base, 'review_plan_contract':'optional-v1', 'history_projection_profile':'exact-history-v1'})
    strict = release({**base, 'review_plan_contract':'work-units-v1'})
    assert 'review_plan_contract' not in old
    assert optional['review_plan_contract'] == 'optional-v1'
    assert len({old['digest'], optional['digest'], strict['digest']}) == 3
    assert validate_review_plan_contract({**base,'review_plan_contract':'optional-v1', 'history_projection_profile':'exact-history-v1'}) == 'optional-v1'


@pytest.mark.parametrize('with_todo', [False, True])
async def test_native_reviewer_can_observe_without_prior_plan(case, with_todo):
    cs, _, ws, request = configured(case)
    cs.store.set('manifest',{**cs.store.manifest,'review_plan_contract':'optional-v1', 'history_projection_profile':'exact-history-v1'})
    seen = []
    def finish(messages):
        seen.append(observation(messages, 'observe_evidence'))
        return AIMessage('Partial synthetic verification; no conclusion asserted.')
    steps = ([invoke('write_todos',todos=[{'content':'Optional working note','status':'pending'}])] if with_todo else [])
    class CountingDriver(Driver):
        async def respond(self, role, messages):
            from langchain_core.outputs import ChatGeneration, ChatResult
            step = sum(existing_role == role for existing_role, _, _ in self.calls)
            self.calls.append((role, step, list(messages)))
            item = self.scripts[role][step]
            response = item(messages) if callable(item) else item
            return ChatResult(generations=[ChatGeneration(message=response)])
    driver = CountingDriver(coordinator=[AIMessage('',tool_calls=[{**request,'type':'tool_call'}]),AIMessage('End.')],
        reviewer=[*steps, invoke('observe_evidence',kind='calculation',terms=[['9','120']]),finish])
    graph = deep_runtime.build_agent(ws, driver, None)
    from langchain_core.messages import HumanMessage
    await graph.ainvoke({'messages':[HumanMessage('Independent fixture review.')]})
    assert len(seen) == 1 and seen[0]['ok'], seen
    assert not cs.list_objects('ReviewRecord')


@pytest.mark.parametrize('prompt_profile',['legacy-v1','concise-v1'])
def test_optional_reviewer_prompt_preserves_evidence_without_forcing_plan(prompt_profile):
    from report_agent.hierarchical_tools import role_prompt
    options = dict(expression_profile='reader-expression-v2', interface_profile='review-interfaces-v4',
                   prompt_profile=prompt_profile, review_submission_contract='task-scope-selectors-v1')
    optional = role_prompt('reviewer', review_plan_contract='optional-v1', **options)
    strict = role_prompt('reviewer', review_plan_contract='work-units-v1', **options)
    assert 'before substantive verification' not in optional
    assert 'make a concise acceptance plan' not in optional
    assert 'Plan work units linking' not in optional
    assert 'acceptance-plan and independent-verification' not in optional
    assert 'before substantive verification' in strict
    assert 'independent evidence' in optional
    assert 'actual saved' in optional
    assert 'reviewer-optional-plan' not in optional


def test_optional_prompt_provenance_tracks_derived_and_fragment_sources(case):
    from report_agent.hierarchical_tools import role_prompt
    from report_agent.prompt_sources import role_sources, source_manifest
    opts = ('reviewer','reader-expression-v2','review-interfaces-v4','concise-v1',
            'task-scope-selectors-v1','optional-v1')
    names = role_sources(*opts)
    prompt = role_prompt('reviewer', expression_profile=opts[1], interface_profile=opts[2],
        prompt_profile=opts[3], review_submission_contract=opts[4], review_plan_contract=opts[5])
    captured = source_manifest(None, names, {'messages':[{'role':'system','content':prompt}], 'tools':[]})
    observed = {f['name']:f['offered_match'] for f in captured['files']}
    assert observed['content-reviewer-v4'] == 'derived_optional_plan'
    assert observed['review-basis-v4-concise'] == 'derived_optional_plan'
    assert observed['reviewer-optional-plan'] == 'literal'
    assert observed['review-basis-optional-plan'] == 'literal'


def test_optional_plan_still_enforces_exact_export_actor_and_versions(case):
    from report_agent.content_export import export_snapshot, read_export
    from report_agent.content_store import Actor
    from report_agent.errors import ActionForbidden
    from report_agent.review_binding import validate_basis
    from test_review_binding_v4 import review_call
    from copy import deepcopy

    cs, output, ws, _ = configured(case)
    cs.store.set('manifest', {**cs.store.manifest, 'review_plan_contract':'optional-v1', 'history_projection_profile':'exact-history-v1'})
    co = case[1]
    assigned = export_snapshot(cs, co, 'optional-assigned', None,
        deliverable={'kind':'deliverable','operation_id':'published'})['result']['export_ref']
    unassigned = export_snapshot(cs, co, 'optional-unassigned',
        cs.read(assigned)['payload']['snapshot_ref'])['result']['export_ref']
    criterion = cs.list_objects('Criterion')[0]['ref']
    request = review_call([criterion], scope={'kind':'mapped','items':[{
        'criterion_ref':criterion, 'target_ref':output['refs']['a'], 'assessment_kind':'export',
        'artifact_refs':[assigned], 'extent':{'kind':'export_structure','artifact_ref':assigned}}]})
    with delegated_task(ws,'coordinator',request) as (_, reviewer):
        task = cs.read({'type':'DelegatedTask','id':reviewer.task_id,'version':1})['payload']
        assert task['review_plan_contract'] == 'optional-v1'
        assert read_export(cs, reviewer, assigned)['ok']
        with pytest.raises(ActionForbidden):
            read_export(cs, reviewer, unassigned)
        with pytest.raises(ActionForbidden):
            read_export(cs, reviewer, {**assigned,'version':assigned['version']+1})
        with pytest.raises(ActionForbidden):
            read_export(cs, Actor('foreign-reviewer','reviewer','foreign-task'), assigned)
        bad = deepcopy(task)
        bad['review_commission_basis']['digest'] = '0' * 64
        with cs.store.connect() as db:
            with pytest.raises(ActionRejected):
                validate_basis(cs, db, bad)
    assert not cs.list_objects('ReviewRecord')


@pytest.mark.parametrize('failure', ['no_receipts','foreign_receipt','wrong_snapshot','missing_body','none'])
def test_no_plan_cannot_replace_receipts_or_assigned_body_extent(case, failure):
    from report_agent.content_store import Actor
    from report_agent.review_scope_selectors import expand_submission, CONTRACT
    from test_review_binding_v4 import review_call

    cs, output, ws, _ = configured(case)
    cs.store.set('manifest', {**cs.store.manifest, 'review_plan_contract':'optional-v1',
                              'history_projection_profile':'exact-history-v1', 'review_submission_contract':CONTRACT})
    criterion = cs.list_objects('Criterion')[0]['ref']
    task = review_call([criterion], scope={'kind':'mapped','items':[{
        'criterion_ref':criterion, 'target_ref':output['refs']['a'], 'assessment_kind':'content',
        'extent':'subtree_bodies'}]})
    with delegated_task(ws, 'coordinator', task) as (_, reviewer):
        assignment = cs.read({'type':'DelegatedTask','id':reviewer.task_id,'version':1})['payload']
        requirement = assignment['review_requirements'][0]
        receipt = cs.read_context(reviewer, output['refs']['a-body'])['receipt_id']
        receipt_ids = [receipt]
        if failure in ('foreign_receipt', 'none'):
            receipt_ids = [cs.read_context(reviewer, output['refs']['a'])['receipt_id'], receipt]
            if failure == 'foreign_receipt':
                receipt_ids.append(cs.observe(Actor('other','reviewer','other-task'), {'fact':'foreign'})['receipt_id'])
        observations = [] if failure == 'no_receipts' else [
            {'receipt_id':r,'locator':'Fixture object','observation':'A scoped observation.'} for r in receipt_ids]
        value = {'target_ref':requirement['target_ref'],
            'snapshot_ref':({**assignment['review_snapshot_ref'],'version':999} if failure == 'wrong_snapshot'
                            else assignment['review_snapshot_ref']),
            'scope':'Fixture review','criteria_refs':[requirement['criterion_ref']],'dependency_refs':[],
            'items':[{'assigned_scope_index':0,'scope':'Fixture check','execution_state':'completed',
                'verdict':'satisfied','observations':observations,'checked_requirement_indexes':[0],
                'check_results':[{'requirement_index':0,'execution_state':'completed',
                    'result':'Claimed completion.','observation_indexes':list(range(len(observations))),
                    'remaining':''}],
                'coverage':{'checked':requirement['required_checks'],'unchecked':[],'blocked':[],
                            'basis':'Only provided observations.'},
                'reason':'The declared scoped check.'}]}
        expanded = expand_submission(cs, reviewer, value)
        if failure == 'none':
            saved = cs.submit_review(reviewer, 'completed-with-evidence', expanded, {})
            assert cs.read(saved['result']['review_ref'])['payload']['items'][0]['execution_state'] == 'completed'
        else:
            expected = {
                'no_receipts':'COMPLETED_CHECK_REQUIRES_LINKED_OBSERVATIONS_AND_NO_REMAINING_WORK',
                'foreign_receipt':'OBSERVATION_RECEIPT_NOT_FROM_THIS_REVIEWER',
                'wrong_snapshot':'REVIEW_SNAPSHOT_OUTSIDE_ASSIGNMENT',
                'missing_body':'COMPLETED_CHECK_MISSING_BODY_EXTENT'}[failure]
            with pytest.raises((ActionRejected, ValueError), match=expected):
                cs.submit_review(reviewer, 'unproven-'+failure, expanded, {})
    assert len(cs.list_objects('ReviewRecord')) == (1 if failure == 'none' else 0)


async def test_optional_plan_review_checkpoint_reopens_without_plan(case):
    from langchain.agents import create_agent
    from langchain.agents.middleware import TodoListMiddleware
    from langchain_core.messages import HumanMessage
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from langgraph.types import Command, interrupt
    from report_agent.deep_runtime import BusinessBoundary, business_tools
    from report_agent.hierarchical_tools import role_prompt
    from report_agent.prompt_provenance import AgentPromptBoundary
    from report_agent.prompt_sources import (context_source, load_prompt, report_expression_profile,
        report_prompt_profile, review_interface_profile)
    from report_agent.review_work_units import bind_contract
    from report_agent.store import Store
    from report_agent.task_context import TaskContext
    from report_agent.workspace import Workspace

    cs, output, ws, task = configured(case)
    cs.store.set('manifest', {**cs.store.manifest, 'review_plan_contract':'optional-v1',
                              'history_projection_profile':'exact-history-v1'})
    bind_contract(ws, ws.store.manifest)
    seen = []
    def pause(messages):
        seen.append(observation(messages, 'read_context'))
        assert interrupt({'kind':'optional-review-reopen'}) == 'continue'
        return AIMessage('Fixture resumed with scoped read, no completed review claimed.')
    scripts = [invoke('read_context', target_ref=output['refs']['a-body']), pause]
    path = str(ws.store.root / 'optional-plan-child.db')
    config = {'configurable': {'thread_id':'optional-plan-reviewer'}}
    for resumed in (False, True):
        current = Workspace(Store(ws.store.root))
        bind_contract(current,current.store.manifest)
        expression = report_expression_profile(current.store)
        interface = review_interface_profile(current.store)
        text_profile = report_prompt_profile(current.store)
        prompt = role_prompt('reviewer', expression_profile=expression, interface_profile=interface,
            prompt_profile=text_profile, review_plan_contract='optional-v1')
        prompt += '\n' + load_prompt(context_source('reviewer', interface, text_profile))
        with delegated_task(current,'coordinator',task):
            async with AsyncSqliteSaver.from_conn_string(path) as saver:
                graph = create_agent(Driver(reviewer=scripts)('reviewer'), system_prompt=prompt,
                    tools=business_tools(current,'reviewer',None,None),
                    middleware=[TodoListMiddleware(system_prompt=load_prompt('reviewer-optional-todo').strip()),TaskContext(current,'reviewer'),
                        BusinessBoundary(current,'reviewer'),AgentPromptBoundary(current,'reviewer')],
                    checkpointer=saver)
                await graph.ainvoke(Command(resume='continue') if resumed else
                    {'messages':[HumanMessage('Inspect authorized fixture.') ]}, config)
                saved = await graph.aget_state(config)
                assert bool(saved.interrupts) is (not resumed)
                assert not saved.values.get('todos')
    assert len(seen) == 2 and all(entry['ok'] for entry in seen)
    assert not cs.list_objects('ReviewRecord')


def test_optional_contract_requires_shared_history_profile(case):
    from report_agent.prompt_sources import validate_review_plan_contract
    cs, _, _, _ = configured(case)
    base = {**cs.store.manifest, 'review_plan_contract':'optional-v1'}
    for history in (None, 'agent-search-v1', 'unexpected'):
        candidate = {k:v for k,v in base.items() if k != 'history_projection_profile'}
        if history is not None: candidate['history_projection_profile'] = history
        with pytest.raises(ActionRejected, match='OPTIONAL_REVIEW_PLAN_REQUIRES_COMMON_HISTORY'):
            validate_review_plan_contract(candidate)
        expected = 'OPTIONAL_REVIEW_PLAN_REQUIRES_COMMON_HISTORY' if history is None else 'UNKNOWN_HISTORY_PROJECTION_PROFILE'
        with pytest.raises(ActionRejected, match=expected):
            release(candidate)
