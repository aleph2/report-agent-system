"""Writer-only completion boundaries use real admission/ledger state and fake models."""
import json
from copy import deepcopy
from types import SimpleNamespace

import httpx
import pytest

from report_agent.assessment_completion import (
    CompletionBudget, AssessmentCompletionStop, claim_launch, read_finance,
    selected_tools, saved_assessments,
)
from report_agent.request_budget import RequestBudgetExceeded, account_request_sync, request_reservation_observer
from report_agent.store import digest
from report_agent.token_budget import TokenBudget, token_budget


def ledger(tmp_path):
    budget=TokenBudget(tmp_path/'tokens.db',500_000_000,{'writer-model':2_000_000})
    return budget


def reserve(budget,guard):
    with token_budget(budget), request_reservation_observer(guard.check):
        account_request_sync(httpx.Request('POST','https://example.invalid/v1/chat/completions',
            json={'model':'writer-model'}))


def test_old_holds_are_preserved_and_not_charged_to_completion(tmp_path):
    budget=ledger(tmp_path)
    old=budget.reserve('writer-model')
    before=read_finance(budget.path)
    guard=CompletionBudget(lambda:read_finance(budget.path),before,before,budget.model_bounds,writer_model='writer-model')
    reserve(budget,guard)
    assert guard.observation()['reserved_or_unknown_upper_bounds']==2_000_000
    now=read_finance(budget.path)
    assert next(r for r in now['rows'] if r[0]==old)==before['rows'][0]


def test_cap_refuses_before_send_and_cancels_only_unsent_reservation(tmp_path):
    budget=ledger(tmp_path);baseline=read_finance(budget.path)
    for _ in range(5):
        identity=budget.reserve('writer-model');budget.settle(identity,{'total_tokens':1_800_000})
    guard=CompletionBudget(lambda:read_finance(budget.path),baseline,baseline,budget.model_bounds,writer_model='writer-model')
    with pytest.raises(RequestBudgetExceeded,match='ASSESSMENT_COMPLETION_TOKEN_LIMIT'):
        reserve(budget,guard)
    now=read_finance(budget.path)
    assert sum(r[3] or 0 for r in now['rows'])==9_000_000
    assert sum(r[2] for r in now['rows'] if r[4] in ('reserved','unknown'))==0
    assert sum(r[4]=='known_not_sent' for r in now['rows'])==1


def test_preserved_grant_includes_prior_report_spend(tmp_path):
    budget=ledger(tmp_path);grant=read_finance(budget.path)
    with budget.connect() as db:
        db.executemany("insert into attempts values (?,'writer-model',2000000,1990000,'settled',NULL,NULL,'past')",
            [('prior'+str(i).zfill(3),) for i in range(100)])
    phase=read_finance(budget.path)
    guard=CompletionBudget(lambda:read_finance(budget.path),phase,grant,budget.model_bounds,writer_model='writer-model')
    with pytest.raises(RequestBudgetExceeded,match='ASSESSMENT_COMPLETION_GRANT_LIMIT'):
        reserve(budget,guard)
    current={r[0]:r for r in read_finance(budget.path)['rows']}
    assert all(current[row[0]]==row for row in phase['rows'])


@pytest.mark.parametrize('state',['reserved','unknown'])
def test_an_unresolved_new_attempt_blocks_automatic_recovery(tmp_path,state):
    budget=ledger(tmp_path);before=read_finance(budget.path)
    identity=budget.reserve('writer-model')
    if state=='unknown':budget.settle(identity,None)
    guard=CompletionBudget(lambda:read_finance(budget.path),before,before,budget.model_bounds,writer_model='writer-model')
    with pytest.raises(RequestBudgetExceeded,match='ASSESSMENT_COMPLETION_UNRESOLVED_ATTEMPT'):
        reserve(budget,guard)
    now=read_finance(budget.path)
    original=next(r for r in now['rows'] if r[0]==identity)
    assert original[4]==state and original[3] is None
    assert sum(r[4]=='known_not_sent' for r in now['rows'])==1


def test_baseline_mutation_is_not_rebased(tmp_path):
    budget=ledger(tmp_path);identity=budget.reserve('writer-model');before=read_finance(budget.path)
    budget.settle(identity,{'total_tokens':1})
    guard=CompletionBudget(lambda:read_finance(budget.path),before,before,budget.model_bounds,writer_model='writer-model')
    with pytest.raises(RequestBudgetExceeded,match='HOST_BASELINE_CHANGED'):guard.check()


def test_launch_is_exclusive_and_does_not_silently_resume(tmp_path):
    path=tmp_path/'launch.json';claim_launch(path,{'binding':'a'})
    original=path.read_bytes()
    with pytest.raises(FileExistsError):claim_launch(path,{'binding':'a'})
    assert path.read_bytes()==original


def test_tools_exclude_all_other_model_and_business_writes():
    def named(name):return SimpleNamespace(name=name)
    offered=[named(n) for n in ['read_context','search_sources','calculate_assessment','export_content_snapshot',
        'process_report_content','analyze_source_image','task','save_section_prose','commit_objects','request_system_delivery']]
    assert [t.name for t in selected_tools(offered)]==['read_context','search_sources','calculate_assessment']


class Saved:
    def __init__(self):self.values={};self.records={};self.store=self
    def get(self,key,default=None):return self.values.get(key,default)
    def read(self,ref):return self.records[digest(ref)]
    def add(self,plan,obj,owner='writer'):
        ref={'type':'Assessment','id':obj,'version':1}
        self.values['g6_assessment:'+digest([plan,obj])]=ref
        self.values['assessment_receipt:'+digest(ref)]={'assessment_ref':ref}
        self.records[digest(ref)]={'ref':ref,'owner_id':owner,'payload':{'object_id':obj,'commission_plan_ref':plan}}


@pytest.mark.parametrize('invalid',['plan','owner','receipt'])
def test_only_current_plan_writer_canonical_receipts_count(invalid):
    cs=Saved();plan={'type':'CommissionPlan','id':'approved','version':2};ids=['S'+str(i) for i in range(5)]
    for obj in ids[:4]:cs.add(plan,obj)
    assert len(saved_assessments(cs,plan,ids,'writer'))==4
    cs.add(plan,ids[4]);assert len(saved_assessments(cs,plan,ids,'writer'))==5
    first=cs.values['g6_assessment:'+digest([plan,ids[0]])]
    if invalid=='plan':cs.records[digest(first)]['payload']['commission_plan_ref']={**plan,'version':1}
    elif invalid=='owner':cs.records[digest(first)]['owner_id']='other-writer'
    else:cs.values.pop('assessment_receipt:'+digest(first))
    with pytest.raises(ValueError,match='ASSESSMENT_COMPLETION_SELECTION_INVALID'):
        saved_assessments(cs,plan,ids,'writer')


@pytest.mark.asyncio
async def test_native_guard_stops_before_an_extra_model_call_after_five_saves():
    from langchain.agents import create_agent
    from langchain_core.messages import AIMessage,HumanMessage
    from test_deep_runtime import Driver
    saved=[]
    def record_assessment(object_id:str)->dict:
        """Save a fake assessment for this guard-only test."""
        saved.append(object_id);return {'saved':object_id}
    calls=[{'name':'record_assessment','args':{'object_id':'S'+str(i)},'id':'call'+str(i),'type':'tool_call'} for i in range(5)]
    driver=Driver(writer=[AIMessage(content='',tool_calls=calls)])
    agent=create_agent(driver('writer'),tools=[record_assessment],middleware=[AssessmentCompletionStop(lambda:len(saved)==5)])
    await agent.ainvoke({'messages':[HumanMessage(content='Save five assessments.')]})
    assert len(saved)==5
    assert len(driver.calls)==1 and driver.calls[0][0]=='writer'


def test_other_model_is_refused_before_send_without_changing_old_rows(tmp_path):
    budget=TokenBudget(tmp_path/'tokens.db',500_000_000,{'writer-model':2_000_000,'other-model':2_000_000})
    before=read_finance(budget.path)
    guard=CompletionBudget(lambda:read_finance(budget.path),before,before,budget.model_bounds,writer_model='writer-model')
    with token_budget(budget),request_reservation_observer(guard.check):
        with pytest.raises(RequestBudgetExceeded,match='ASSESSMENT_COMPLETION_WRITER_MODEL_ONLY'):
            account_request_sync(httpx.Request('POST','https://example.invalid/v1/chat/completions',json={'model':'other-model'}))
    assert read_finance(budget.path)['rows'][0][4]=='known_not_sent'


@pytest.mark.asyncio
async def test_actual_writer_builder_reaches_first_model_with_unmodified_role_prompt(tmp_path):
    from langchain_core.messages import AIMessage,HumanMessage
    from langgraph.checkpoint.memory import InMemorySaver
    from report_agent.content_tasks import delegated_task
    from report_agent.content_store import ContentStore
    from report_agent.store import Store
    from report_agent.workspace import Workspace
    from report_agent.assessment_completion import build_writer_agent
    from test_deep_runtime import Driver
    store=Store(tmp_path/'case')
    store.initialize({'goal':'Synthetic Writer-only assessment completion.',
        'content_contract':'hierarchical-review-v1','review_interface_profile':'review-interfaces-v4',
        'review_entrypoint':'delegated-reviewer-v1','review_execution_mode':'native-reviewer-v2',
        'delegation_prompt_profile':'separate-description-v1','operation_identity_profile':'native-tool-runtime-v1',
        'report_expression_profile':'reader-expression-v2',
        'report_prompt_profile':'concise-v1','assembly_contract':'system-assembler-v1',
        'sources':[{'id':'source','title':'Synthetic source','coverage':'complete','content':'Synthetic design fact.'}]})
    workspace=Workspace(store);ContentStore(store)
    driver=Driver(writer=[AIMessage(content='Synthetic first request reached; no judgments generated.')])
    with delegated_task(workspace,'coordinator',{'name':'task','id':'writer-only-test',
        'args':{'subagent_type':'writer','description':'Complete only the authorized assessments.'}}):
        agent=build_writer_agent(workspace,driver('writer'),[],lambda:False,InMemorySaver())
        await agent.ainvoke({'messages':[HumanMessage(content='Bounded operator assignment; unverified suggestions.')]},
            {'configurable':{'thread_id':'first-writer-input'}})
    assert len(driver.calls)==1 and driver.calls[0][0]=='writer'
    tools={tool['name'] for schema in driver.bindings['writer'] for tool in schema}
    assert 'task' not in tools


@pytest.mark.parametrize('field',['ref','payload_digest'])
def test_owner_decision_pin_refuses_changed_identity_or_payload(field):
    from report_agent.assessment_completion import require_decision_pin
    approved={'ref':{'type':'CommissionDecision','id':'owner','version':1},'payload_digest':'approved'}
    require_decision_pin(deepcopy(approved),approved)
    changed=deepcopy(approved);changed[field]='changed'
    with pytest.raises(ValueError,match='ASSESSMENT_COMPLETION_DECISION_CHANGED'):
        require_decision_pin(changed,approved)


@pytest.mark.parametrize('changed',['model_name','model_retries','sync_retries','async_retries'])
def test_actual_writer_client_must_match_model_and_zero_retries(changed):
    from report_agent.assessment_completion import require_writer_model
    model=SimpleNamespace(model_name='writer-model',max_retries=0,
        root_client=SimpleNamespace(max_retries=0),root_async_client=SimpleNamespace(max_retries=0))
    require_writer_model(model,'writer-model')
    if changed=='model_name':model.model_name='other-model'
    elif changed=='model_retries':model.max_retries=1
    elif changed=='sync_retries':model.root_client.max_retries=1
    else:model.root_async_client.max_retries=1
    with pytest.raises(ValueError,match='ASSESSMENT_COMPLETION_WRITER_MODEL_OR_RETRIES_CHANGED'):
        require_writer_model(model,'writer-model')
