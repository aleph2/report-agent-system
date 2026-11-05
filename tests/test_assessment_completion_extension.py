"""Known budget-denial continuation retains its original Writer and cumulative scope."""
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from report_agent import assessment_completion as api
from report_agent.request_budget import RequestBudgetExceeded
from test_assessment_completion import ledger, reserve


def write(path, value):
    path.write_text(json.dumps(value))


@pytest.fixture
def extension(tmp_path):
    evidence = tmp_path / 'evidence'; evidence.mkdir()
    folder = evidence / 'extension-1'; folder.mkdir()
    case = tmp_path / 'case'; case.mkdir()
    (case / 'assessment-completion-checkpoints.db').write_bytes(b'existing synthetic checkpoint')
    binding = {'case': str(case), 'code_sha256': 'old-code', 'authority_sha256': 'owner10M',
        'source_db_sha256': 'frozen-source', 'writer_model': 'writer-model',
        'writer_endpoint_sha256': 'endpoint', 'decision_ref': 'decision-v1'}
    budget = ledger(tmp_path)
    baseline = api.read_finance(budget.path)
    for used in [2_000_000] * 4 + [97_818]:
        budget.settle(budget.reserve('writer-model'), {'total_tokens': used})
    prior = {'status': 'blocked', 'error_type': 'RequestBudgetExceeded', 'maximum_tokens': api.LIMIT,
        'binding': binding, 'pid': 999999999, 'uid': 1000, 'process_start_ticks': '0',
        'writer_actor': {'id': 'content:writer:same', 'role': 'writer', 'task_id': 'same'},
        'budget': {'recorded_tokens': 8_097_818, 'reserved_or_unknown_upper_bounds': 0,
            'maximum_tokens': api.LIMIT}}
    write(evidence / 'writer-launch.json', prior)
    write(evidence / 'completion-budget-baseline.json', {'binding': binding, 'baseline': baseline})
    authority = {'turn_id': 'owner-turn', 'message_id': 'owner-message', 'additional_tokens': api.LIMIT,
        'maximum_tokens': 2 * api.LIMIT, 'prior_launch_path': str(evidence / 'writer-launch.json'),
        'prior_launch_sha256': api._sha(evidence / 'writer-launch.json'),
        'original_baseline_path': str(evidence / 'completion-budget-baseline.json'),
        'original_baseline_sha256': api._sha(evidence / 'completion-budget-baseline.json'),
        'original_owner_authority_sha256': 'owner10M', 'grant_limit_unchanged': api.GRANT_LIMIT,
        'code_sha256': 'new-code'}
    path = folder / 'owner-approval.json'; write(path, authority)
    return SimpleNamespace(evidence=evidence, path=path, folder=folder, case=case, budget=budget,
        original=baseline, prior=prior, authority=authority, binding={**binding, 'code_sha256': 'new-code'})


def check(f):
    return api.require_extension(f.case, f.evidence, f.path, f.binding, api.read_finance(f.budget.path))


def test_extension_uses_original_scope_and_additional_reservations(extension):
    f = extension
    authority, original, prior = check(f)
    assert original['baseline'] == f.original and prior['writer_actor']['task_id'] == 'same'
    guard = api.CompletionBudget(lambda: api.read_finance(f.budget.path), original['baseline'], f.original,
        f.budget.model_bounds, writer_model='writer-model', maximum_tokens=authority['maximum_tokens'])
    reserve(f.budget, guard)
    assert guard.observation()['recorded_tokens'] == 8_097_818
    assert guard.observation()['reserved_or_unknown_upper_bounds'] == 2_000_000
    assert guard.observation()['remaining_for_new_reservations'] == 9_902_182
    assert guard.observation()['maximum_tokens'] == 20_000_000


@pytest.mark.parametrize('field,value', [('status','incomplete'), ('error_type','ReadTimeout')])
def test_only_known_budget_denial_can_continue(extension, field, value):
    f = extension; f.prior[field] = value
    write(f.evidence / 'writer-launch.json', f.prior)
    f.authority['prior_launch_sha256'] = api._sha(f.evidence / 'writer-launch.json'); write(f.path, f.authority)
    with pytest.raises(ValueError, match='KNOWN_BUDGET_DENIAL'): check(f)


@pytest.mark.parametrize('state', ['reserved', 'unknown'])
def test_unresolved_attempt_is_not_replayed(extension, state):
    f = extension
    identity = f.budget.reserve('writer-model')
    if state == 'unknown': f.budget.settle(identity, None)
    with pytest.raises(ValueError, match='PENDING'): check(f)
    assert next(row for row in api.read_finance(f.budget.path)['rows'] if row[0] == identity)[4] == state


@pytest.mark.parametrize('field', ['source_db_sha256', 'writer_model', 'writer_endpoint_sha256', 'decision_ref', 'code_sha256'])
def test_extension_rechecks_source_decision_model_and_code_pins(extension, field):
    f = extension; f.binding[field] = 'changed'
    with pytest.raises(ValueError, match='PIN'): check(f)


def test_extension_account_authorization_cannot_change(extension):
    f = extension
    with f.budget.connect() as db: db.execute('update authorization set maximum=maximum+1 where id=1')
    with pytest.raises(RequestBudgetExceeded, match='BASELINE_CHANGED'): check(f)


def test_extension_requires_absent_original_process(extension):
    f = extension
    import os
    f.prior.update(pid=os.getpid(), uid=os.getuid(),
        process_start_ticks=Path('/proc/self/stat').read_text().rpartition(')')[2].split()[19])
    write(f.evidence / 'writer-launch.json', f.prior)
    f.authority['prior_launch_sha256'] = api._sha(f.evidence / 'writer-launch.json'); write(f.path, f.authority)
    with pytest.raises(ValueError, match='PROCESS'): check(f)


def test_duplicate_extension_receipt_is_exclusive(extension):
    f = extension
    api.claim_launch(f.folder / 'writer-launch.json', {'status': 'unknown'})
    with pytest.raises(FileExistsError): check(f)


@pytest.mark.parametrize('next_nodes,error', [(('tools',),"RequestBudgetExceeded('ASSESSMENT_COMPLETION_TOKEN_LIMIT')"),
    (('model',),"ReadTimeout('unknown')"), ((),None)])
def test_checkpoint_must_be_failed_model_only(next_nodes, error):
    state = SimpleNamespace(next=next_nodes, tasks=(SimpleNamespace(name='model', id='native-call', error=error),),
        config={'configurable': {'thread_id':'bounded-assessment-completion', 'checkpoint_id':'saved'}})
    with pytest.raises(ValueError, match='CHECKPOINT'): api.require_continuation_checkpoint(state)


def test_method_context_copies_approved_contract_without_proposed_judgments(method_commission):
    context = api.approved_method_context({'payload': method_commission.plan})
    method = method_commission.plan['method_pack']
    assert context['method_id'] == method['method_id'] and context['version'] == method['version']
    assert context['sources'] == method['sources']
    assert context['indicators'] == [{key: row[key] for key in ('id','label','grades','notes')} for row in method['indicators']]
    assert 'proposed_grade' not in json.dumps(context)


@pytest.mark.asyncio
async def test_native_checkpoint_retains_writer_files_summary_and_tool_receipts(tmp_path):
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    from langgraph.checkpoint.memory import InMemorySaver
    from report_agent.content_tasks import delegated_task
    from report_agent.content_store import ContentStore
    from report_agent.store import Store
    from report_agent.workspace import Workspace
    from test_deep_runtime import Driver, invoke
    store = Store(tmp_path / 'case')
    store.initialize({'goal':'Synthetic bounded completion', 'content_contract':'hierarchical-review-v1',
        'review_interface_profile':'review-interfaces-v4', 'review_entrypoint':'delegated-reviewer-v1',
        'review_execution_mode':'native-reviewer-v2', 'delegation_prompt_profile':'separate-description-v1',
        'operation_identity_profile':'native-tool-runtime-v1', 'report_expression_profile':'reader-expression-v2',
        'report_prompt_profile':'concise-v1', 'assembly_contract':'system-assembler-v1',
        'sources':[{'id':'source','title':'Synthetic','coverage':'complete','content':'Synthetic evidence'}]})
    ws=Workspace(store); ContentStore(store); saver=InMemorySaver()
    def deny(messages): raise RequestBudgetExceeded('ASSESSMENT_COMPLETION_TOKEN_LIMIT')
    driver=Driver(writer=[invoke('write_file',file_path='/prior-evidence.txt',content='Saved evidence'), deny])
    config={'configurable':{'thread_id':'bounded-assessment-completion'}}
    summary={'cutoff_index':0,'summary_message':HumanMessage(content='Prior verified evidence summary'), 'file_path':None}
    with delegated_task(ws,'coordinator',{'name':'task','id':'original', 'args':{
            'subagent_type':'writer','description':'Complete only five assessments.'}}) as (_, original):
        agent=api.build_writer_agent(ws,driver('writer'),[],lambda:False,saver)
        # Private native summary state cannot be supplied through public user input.
        # Seed an already-created summary before the failure, using native test setup only.
        await agent.aupdate_state(config, {'_summarization_event':summary,'_summarization_session_id':'prior-session'}, as_node='model')
        with pytest.raises(RequestBudgetExceeded):
            await agent.ainvoke({'messages':[HumanMessage(content='Original unverified suggestions retained.')]},config)
        old=await agent.aget_state(config)
        old_native=(await saver.aget_tuple(config)).checkpoint['channel_values']
    assert old_native['_summarization_event'] == summary
    assert old_native['_summarization_session_id'] == 'prior-session'
    proof=api.require_continuation_checkpoint(old)
    assert proof['next'] == ['model']
    tool_count=len([m for m in old.values['messages'] if isinstance(m,ToolMessage)])
    driver.scripts['writer'][1]=AIMessage(content='Known budget denial continued under owner20M authority.')
    with delegated_task(ws,'coordinator',{'name':'task','id':'extension-1','args':{
            'subagent_type':'writer','resume_content_task_id':original.task_id,
            'description':'Owner increases cumulative scope to20M; original task unchanged.'}}) as (_, resumed):
        assert resumed == original
        agent=api.build_writer_agent(ws,driver('writer'),[],lambda:False,saver)
        await agent.ainvoke({'messages':[HumanMessage(content='Trusted owner20M amendment')]},config)
        new=await agent.aget_state(config)
        new_native=(await saver.aget_tuple(config)).checkpoint['channel_values']
    assert (await saver.aget_tuple(old.config)).checkpoint['channel_values'] == old_native
    assert new.values['files'] == old.values['files']
    assert new_native['_summarization_event'] == old_native['_summarization_event']
    assert new_native['_summarization_session_id'] == old_native['_summarization_session_id']
    assert len([m for m in new.values['messages'] if isinstance(m,ToolMessage)]) == tool_count == 1
    assert len(driver.calls) == 3 and {role for role,_,_ in driver.calls} == {'writer'}
    assert any('Trusted owner20M amendment' in str(m.content) for m in driver.calls[-1][2])
    assert any(isinstance(m,ToolMessage) and m.name=='write_file' for m in driver.calls[-1][2])


from test_m1_g3_integration import method_commission


def test_cumulative_twenty_million_cap_cannot_be_reset_after_prior_spend(extension):
    f = extension
    authority, original, _ = check(f)
    guard = api.CompletionBudget(lambda: api.read_finance(f.budget.path), original['baseline'], f.original,
        f.budget.model_bounds, writer_model='writer-model', maximum_tokens=authority['maximum_tokens'])
    for used in [2_000_000] * 5:
        f.budget.settle(f.budget.reserve('writer-model'), {'total_tokens': used})
    assert guard.check() == (18_097_818, 0)
    with pytest.raises(RequestBudgetExceeded, match='TOKEN_LIMIT'): reserve(f.budget, guard)
    assert guard.observation()['recorded_tokens'] == 18_097_818
    assert guard.observation()['reserved_or_unknown_upper_bounds'] == 0


def test_missing_original_checkpoint_does_not_create_a_new_writer_thread(extension):
    f = extension
    (f.case / 'assessment-completion-checkpoints.db').unlink()
    with pytest.raises(ValueError, match='EXISTING_CHECKPOINT'): check(f)
