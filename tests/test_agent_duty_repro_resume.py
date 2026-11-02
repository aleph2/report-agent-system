"""R01/R02: retained failure oracles against real native handoffs/compaction.

No product patch. Correctly retained original goals are not themselves errors.
The two oracles distinguish authority conflict from loss of the current request.
"""
import json
from copy import deepcopy

import pytest
from langchain_core.messages import AIMessage
from langchain_core.messages import messages_to_dict
from langchain_core.runnables import RunnableLambda
from langchain_openai.chat_models.base import _convert_message_to_dict

from report_agent.deep_runtime import run_report
from report_agent.task_context import exact_task_context
from report_agent.working_summary import WorkingSummary, PROMPT
from test_agent_duty_trace_cases import action, result_value, tool_reply
from test_decision_data import activate
from test_deep_runtime import Driver, invoke
from test_hierarchical_content import seed
from test_task_supervision import ws, offline


def goals(role):
    old = ('Use right margin 15mm.' if role == 'layout' else
           'Generate a paragraph for the synthetic report.')
    new = (('The next revision replaces 15mm with 20mm.' if role == 'layout' else
            'Replace the previous request: investigate the missing class evidence; do not generate a paragraph yet.')
           + ' Preserve source facts, original identities and the existing permissions. '
           + 'The following requirement is necessary for this invocation only. ' * 50
           + 'TAIL_CURRENT_COMMISSION: retain the complete table footnote and leave Q unresolved.')
    return old, new


def trace(request, case, value):
    request.node.user_properties.append(('repro_case', json.dumps(
        {'case':case, **value, 'paid_calls':0, 'model_semantic_behavior_proven':False},
        ensure_ascii=False, default=str)))


def wire(messages):
    return [_convert_message_to_dict(m) for m in messages]


@pytest.mark.parametrize('role', ['writer', 'layout'])
@pytest.mark.parametrize('managed', [False, True])
@pytest.mark.parametrize('changed', [False, True], ids=['same-request', 'new-request'])
async def test_r01_resumed_instruction_has_no_unqualified_old_current_authority(ws, role, managed, changed, request):
    cs, _, _, snapshot, _ = seed(ws)
    if managed:
        activate(ws)
    old, new = goals(role)
    current = new if changed else old
    captures = []

    def child(messages):
        captures.append({'messages':messages_to_dict(messages), 'wire':wire(messages),
                         'state':exact_task_context(ws, role)})
        return AIMessage(content='Observed synthetic commission; no report change.')

    def resume(messages):
        task = cs.list_objects('DelegatedTask')[0]
        return action('task', 'second-commission', subagent_type=role,
                      description=current, resume_content_task_id=task['ref']['id'])

    args = {'subagent_type':role, 'description':old}
    if role == 'layout':
        args['layout_snapshot_ref'] = snapshot
    driver = Driver(coordinator=[action('task','original-commission',**args), resume,
                                 AIMessage(content='No acceptance claimed.')],
                    **{role:[child]})
    result = await run_report(ws, driver)
    assert result['last_error'] is None, result
    assert len(captures) == 2
    before, after = captures
    assert current in json.dumps(after['wire'], ensure_ascii=False)
    assert before['state']['actor_id'] == after['state']['actor_id']
    assert before['state']['assignment'] == after['state']['assignment']
    tasks = cs.list_objects('DelegatedTask')
    assert len(tasks) == 1 and tasks[0]['ref']['version'] == 1
    assert tasks[0]['payload']['goal'] == old
    if role == 'layout':
        assert after['state']['assignment']['layout_snapshot_ref'] == snapshot
    systems = '\n'.join(str(m['content']) for m in after['wire'] if m['role']=='system')
    # This detects the *observed combined authority claim*, not mere retention
    # of history. R02 separately prevents a label-only change hiding request loss.
    conflict = bool(changed and managed and
        'Current task bindings and navigation previews. Incomplete fields expose read_decision_state paths; previews do not establish complete instruction or evidence coverage' in systems and
        after['state']['note'].startswith('Current task/state overrides conversational recollection.') and
        after['state']['assignment']['goal'] == old and current not in systems)
    trace(request, 'R01', {'role':role,'managed':managed,'changed':changed,
          'original_goal':old,'current_instruction':current,'captures':captures,
          'unqualified_current_authority_conflict':conflict})
    assert not conflict, 'R01_OLD_GOAL_PROMOTED_TO_CURRENT_AUTHORITY: latest Human arrived but authoritative System still promotes the replaced original goal'


@pytest.mark.parametrize('role', ['writer', 'layout'])
@pytest.mark.parametrize('resumed', [False, True], ids=['original-current-control', 'resumed-current'])
async def test_r02_current_commission_survives_real_native_compaction(ws, monkeypatch, role, resumed, request):
    cs, _, _, snapshot, _ = seed(ws)
    activate(ws)
    old, new = goals(role)
    current = new if resumed else old
    summaries, captured, live_calls = [], [], []
    counts = {'child':0, 'active':0}

    async def summary(prompt):
        summaries.append(str(prompt))
        # Deliberately lossy working notes, NOT a new instruction or source.
        return AIMessage(content='Historical notes: ' + old)

    def summary_factory(model, store, task_role=None):
        return WorkingSummary(model=RunnableLambda(summary), store=store, role=task_role,
            trigger=('messages',3 if task_role == role else 1000), keep=('messages',1),
            token_counter=lambda messages:len(messages), trim_tokens_to_summarize=None,
            summary_prompt=PROMPT)

    monkeypatch.setattr('report_agent.working_summary.working_summary', summary_factory)

    def child(messages):
        counts['child'] += 1
        if resumed and counts['child'] == 1:
            return AIMessage(content='Original task retained; no file changed.')
        counts['active'] += 1
        state = exact_task_context(ws, role)
        from support.task_state_contract import native_model_call_record
        live_call = native_model_call_record(role, messages, driver.bindings[role][-1])
        live_calls.append(live_call)
        captured.append({'turn':counts['active'],'call_id':live_call['call_id'],'messages':messages_to_dict(messages),
                         'wire':wire(messages),'state':state})
        if counts['active'] == 1:
            assert current in json.dumps(wire(messages),ensure_ascii=False)
            # Real registered tool response provides enough history to compact.
            return action('read_decision_state','before-summary',path=['assignment'])
        if counts['active'] == 2:
            assert summaries, 'FIXTURE_INVALID: native summarization did not execute'
            assert any(m.additional_kwargs.get('lc_source')=='summarization' for m in messages)
            # Test the documented full state recovery path; do not search hidden
            # DB request digests or guess a new current_invocation field.
            return action('read_decision_state','recover-current-state',path=[])
        assert counts['active'] == 3, 'FIXTURE_INVALID: unexpected extra model turn'
        return AIMessage(content='Captured current-state recovery; no semantic acceptance.')

    def resume(messages):
        task = cs.list_objects('DelegatedTask')[0]
        return action('task','second-commission',subagent_type=role,
                      description=new,resume_content_task_id=task['ref']['id'])

    args = {'subagent_type':role,'description':old}
    if role == 'layout':
        args['layout_snapshot_ref']=snapshot
    parents = [action('task','original-commission',**args)]
    if resumed:
        parents.append(resume)
    parents.append(AIMessage(content='No artifacts or acceptance.'))
    # Compaction changes historical AI-message count, so every graph step uses
    # the same callback and a separate fixture-only invocation counter.
    driver = Driver(coordinator=parents, **{role:[child]*8})
    outcome = await run_report(ws,driver)
    trace(request,'R02',{'role':role,'resumed':resumed,'original_goal':old,
        'current_instruction':current,'summary_inputs':summaries,
        'summary_response':'Historical notes: '+old,'captures':captured,'outcome':outcome})
    assert outcome['last_error'] is None, outcome
    assert len(captured)==3 and summaries
    first_after = captured[1]['wire']
    # Original Human must have left the retained window: otherwise this is not
    # the designed recovery counterexample. Summary-role Humans remain allowed.
    from support.task_state_contract import current_public_capture, authenticated_state_frame
    from langchain_core.messages import HumanMessage, ToolMessage
    _, actor = current_public_capture(ws.store, live_calls[1])
    frames = [m for m in live_calls[1]['messages'] if authenticated_state_frame(ws.store, m, actor)]
    assert frames, 'Real compaction must retain or rebuild an authenticated state base'
    assert not authenticated_state_frame(ws.store, frames[-1], actor + '-foreign')
    assert not authenticated_state_frame(ws.store,
        frames[-1].model_copy(update={'content':frames[-1].text + ' '}), actor)
    assert not authenticated_state_frame(ws.store, ToolMessage(content=frames[-1].content,
        tool_call_id='copied-frame', additional_kwargs=deepcopy(frames[-1].additional_kwargs)), actor)
    assert not any(isinstance(m, HumanMessage) and current in json.dumps(m.content, ensure_ascii=False)
                   and not m.additional_kwargs.get('lc_source')
                   and not authenticated_state_frame(ws.store, m, actor)
                   for m in live_calls[1]['messages']), 'FIXTURE_INVALID: original business Human was never compacted'
    _, recovered_actor = current_public_capture(ws.store, live_calls[2])
    assert recovered_actor == actor
    full_recovery = captured[2]['wire']
    assert current in json.dumps(first_after+full_recovery,ensure_ascii=False), (
        'R02_CURRENT_COMMISSION_LOST: real compaction removed current Human; '
        'next effective wire and registered full-state recovery do not contain current instruction/tail')
    tasks=cs.list_objects('DelegatedTask')
    assert len(tasks)==1 and tasks[0]['payload']['goal']==old
    assert captured[0]['state']['actor_id']==captured[-1]['state']['actor_id']
    if role=='layout':
        assert captured[-1]['state']['assignment']['layout_snapshot_ref']==snapshot


def test_r01_resume_identity_permission_and_binding_controls(ws, request):
    from report_agent.content_tasks import delegated_task, bound_actor
    from report_agent.errors import ActionRejected, ActionForbidden
    cs, _, refs, snapshot, _ = seed(ws)
    initial={'name':'task','id':'bound-first','args':{'subagent_type':'layout',
        'description':'Use margin15.', 'layout_snapshot_ref':snapshot}}
    with delegated_task(ws,'coordinator',initial) as (native, actor):
        original_actor=actor
        with delegated_task(ws,'coordinator',initial) as (_, repeated):
            assert repeated==original_actor
        assert bound_actor(ws,'layout',None)==original_actor
    resume={'name':'task','id':'bound-resume','args':{'subagent_type':'layout',
        'description':'Use margin20.', 'resume_content_task_id':actor.task_id}}
    with delegated_task(ws,'coordinator',resume) as (_, actor2):
        assert actor2==original_actor
        altered=deepcopy(resume);altered['args']['description']='Use margin30.'
        with pytest.raises(ActionRejected,match='OPERATION_CONFLICT'):
            with delegated_task(ws,'coordinator',altered):
                pass
        wrong=deepcopy(resume);wrong['id']='wrong-role';wrong['args']['subagent_type']='writer'
        with pytest.raises(ActionForbidden,match='resumption scope'):
            with delegated_task(ws,'coordinator',wrong):
                pass
        assert bound_actor(ws,'layout',None)==original_actor
    with pytest.raises(ActionForbidden,match='binding required'):
        bound_actor(ws,'layout',None)
    # Exception must reset current runtime binding as well as normal return.
    with pytest.raises(RuntimeError,match='synthetic cancellation boundary'):
        with delegated_task(ws,'coordinator',resume):
            raise RuntimeError('synthetic cancellation boundary')
    with pytest.raises(ActionForbidden,match='binding required'):
        bound_actor(ws,'layout',None)
    trace(request,'R01-controls',{'retained_task':cs.read({'type':'DelegatedTask','id':original_actor.task_id,'version':1}),
          'same_call_reused':True,'changed_same_call_rejected':True,'wrong_role_rejected':True,'binding_reset':True})


async def test_r01_real_async_cancellation_resets_binding(ws, request):
    import asyncio
    from report_agent.content_tasks import delegated_task, bound_actor
    from report_agent.errors import ActionForbidden
    cs, _, _, snapshot, _ = seed(ws)
    started, blocked = asyncio.Event(), asyncio.Event()
    observed = []
    call={'id':'cancelled-native-scope', 'args':{'subagent_type':'layout',
          'description':'Synthetic cancel binding check.', 'layout_snapshot_ref':snapshot}}
    async def scoped():
        try:
            with delegated_task(ws,'coordinator',call) as (_, actor):
                assert bound_actor(ws,'layout',None)==actor
                started.set()
                await blocked.wait()
        finally:
            with pytest.raises(ActionForbidden,match='binding required'):
                bound_actor(ws,'layout',None)
            observed.append('reset-in-cancelled-task')
    task=asyncio.create_task(scoped())
    await asyncio.wait_for(started.wait(),timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert observed==['reset-in-cancelled-task']
    assert len(cs.list_objects('DelegatedTask'))==1
    trace(request,'R01-cancellation',{'real_async_task_cancelled':True,
         'binding_reset_in_cancelled_task':True,'original_task_retained':True})


# Approved repair controls. Original R01/R02 functions and assertions above are retained.
@pytest.mark.parametrize('role', ['writer', 'layout'])
async def test_r03_native_child_checkpoint_rebinds_actual_instruction(ws, role, request):
    from test_agent_duty_completion_resume import checkpoint
    cs, _, _, snapshot, _ = seed(ws)
    activate(ws)
    _, current = goals(role)
    captured, interrupted_states = [], []

    def finish(messages):
        state = exact_task_context(ws, role)
        captured.append({'state': state, 'wire': wire(messages)})
        assert state['current_invocation']['description'] == current
        assert current in json.dumps(wire(messages), ensure_ascii=False)
        return AIMessage(content='Recovered native child instruction; no acceptance.')

    def interrupted(messages):
        if not driver.failed:
            interrupted_states.append(deepcopy(exact_task_context(ws, role)))
            driver.failed = True
            raise RuntimeError('OFFLINE_CHECKPOINT_INTERRUPTION')
        return finish(messages)

    args = {'subagent_type': role, 'description': current}
    if role == 'layout':
        args['layout_snapshot_ref'] = snapshot
    driver = Driver(coordinator=[action('task', 'checkpoint-child', **args), AIMessage(content='Done.')],
                    **{role: [action('read_decision_state', 'child-read', path=[]), interrupted]})
    first = await run_report(ws, driver)
    assert driver.failed and first['last_error'] is not None
    assert first['last_error']['message'] == 'OFFLINE_CHECKPOINT_INTERRUPTION'
    pending = await checkpoint(ws, driver)
    assert pending['next'], 'FIXTURE_INVALID: no actual pending native checkpoint'
    tasks = cs.list_objects('DelegatedTask')
    assert len(tasks) == 1
    second = await run_report(ws, driver)
    after = await checkpoint(ws, driver)
    assert second['last_error'] is None, second
    assert not after['next'] and not after['interrupts']
    assert cs.list_objects('DelegatedTask') == tasks
    assert len(captured) == 1
    assert len(interrupted_states) == 1
    before, recovered = interrupted_states[0], captured[0]['state']
    assert before['actor_id'] == recovered['actor_id']
    assert before['assignment'] == recovered['assignment']
    assert before['current_invocation'] == recovered['current_invocation']
    assert captured[0]['state']['assignment']['goal'] == current
    if role == 'layout':
        assert captured[0]['state']['assignment']['layout_snapshot_ref'] == snapshot
    trace(request, 'R03-checkpoint', {'first': first, 'second': second,
         'pending': pending, 'after': after, 'before_interruption': interrupted_states,
         'captures': captured})


@pytest.mark.parametrize('role', ['writer', 'layout'])
async def test_r03_child_timeout_returns_to_parent_and_later_run_resumes_public_task(ws, role, request):
    from test_agent_duty_completion_resume import checkpoint
    cs, _, refs, snapshot, _ = seed(ws)
    activate(ws)
    old, current = goals(role)
    originals = {key: cs.read(ref) for key, ref in refs.items()}
    captures, parent_seen = [], []

    def child_start(messages):
        captures.append({'state': deepcopy(exact_task_context(ws, role)), 'wire': wire(messages)})
        return action('read_decision_state', 'child-state', path=[])

    def parent_error(messages):
        error = tool_reply(messages, 'timeout-child')
        value = result_value(error)
        assert error.status == 'error' and value['code'] == 'DELEGATED_EXECUTION_FAILED'
        parent_seen.append(value)
        return AIMessage(content='Child failed; its work remains unfinished. No acceptance.')

    def resume_public_task(messages):
        page = result_value(tool_reply(messages, 'read-public-task'))
        assert page['total'] == 1 and page['next_offset'] is None
        ref = page['objects'][0]['ref']
        assert ref['type'] == 'DelegatedTask'
        parent_seen.append({'public_task_ref': ref})
        args = {'subagent_type': role, 'description': current,
                'resume_content_task_id': ref['id']}
        if role == 'layout':
            args['layout_snapshot_ref'] = snapshot
        return action('task', 'resume-after-parent-finish', **args)

    def finish(messages):
        state = exact_task_context(ws, role)
        assert state['current_invocation']['description'] == current
        assert any(m['role'] == 'user' and m['content'] == current for m in wire(messages))
        return AIMessage(content='Recovered the same task; no report edits or acceptance.')

    args = {'subagent_type': role, 'description': old}
    if role == 'layout':
        args['layout_snapshot_ref'] = snapshot
    driver = Driver(coordinator=[action('task', 'timeout-child', **args), parent_error,
        action('read_object_index', 'read-public-task', object_type='DelegatedTask'),
        resume_public_task, AIMessage(content='Recovery observed; report remains unaccepted.')],
        **{role: [child_start, finish]})
    driver.fail_once = (role, 1)
    first = await run_report(ws, driver)
    ended = await checkpoint(ws, driver)
    assert driver.failed and first['last_error'] is None
    assert not ended['next'] and not ended['interrupts']
    assert len(parent_seen) == 1 and len(captures) == 1
    retained = cs.list_objects('DelegatedTask')
    assert len(retained) == 1
    second = await run_report(ws, driver)
    assert second['last_error'] is None, second
    assert len(captures) == 2
    before, after = [value['state'] for value in captures]
    assert before['actor_id'] == after['actor_id']
    assert before['assignment'] == after['assignment']
    assert before['current_invocation']['description'] == old
    assert after['current_invocation']['description'] == current
    assert before['current_invocation']['description_sha256'] != after['current_invocation']['description_sha256']
    assert after['current_invocation']['delegate_operation_id'] == 'delegate:resume-after-parent-finish'
    assert parent_seen[1]['public_task_ref'] == retained[0]['ref']
    assert cs.list_objects('DelegatedTask') == retained
    assert {key: cs.read(ref) for key, ref in refs.items()} == originals
    if role == 'layout':
        assert after['assignment']['layout_snapshot_ref'] == snapshot
    trace(request, 'R03-parent-followup', {'first': first, 'second': second,
        'ended_without_pending': ended, 'public_parent_observations': parent_seen, 'captures': captures})


async def test_r03_native_reviewer_followup_binds_each_actual_description(ws, request):
    from langchain_core.messages import ToolMessage
    from test_bounded_review import review_call
    from report_agent.decision_state import compact_context
    cs, _, refs, snapshot, _ = seed(ws)
    activate(ws)
    call = review_call(snapshot, refs)
    captured = []

    def reviewer(messages):
        state = exact_task_context(ws, 'reviewer')
        invocation = state['current_invocation']
        assert compact_context(state)['current_invocation'] == invocation
        # Inspect actual text, not the JSON-escaped serialization of that text.
        # The invocation itself includes the saved assignment's JSON quotes.
        texts = [m['content'] if isinstance(m['content'], str) else '\n'.join(
            block['text'] for block in m['content'] if block.get('type') == 'text')
            for m in wire(messages) if m['content'] is not None]
        assert any(invocation['description'] in text for text in texts)
        if not any(isinstance(m, ToolMessage) and m.name == 'read_task_assignment' for m in messages):
            captured.append({'state': state, 'wire': wire(messages)})
            return action('read_task_assignment', 'actual-assignment')
        # The exact tool response is retained even if its navigation projection is bounded.
        observed = ws.store.events()
        captured[-1]['after_reader_wire'] = wire(messages)
        return AIMessage(content='Synthetic review unfinished; no semantic judgment.')

    driver = Driver(coordinator=[AIMessage(content='', tool_calls=[call]), AIMessage(content='Incomplete.')],
                    reviewer=[reviewer] * 4)
    result = await run_report(ws, driver)
    trace(request, 'R03-followup', {'result': result, 'captures': captured})
    assert result['last_error'] is None, result
    assert len(captured) == 2
    first, second = [c['state'] for c in captured]
    assert first['assignment'] == second['assignment']
    assert first['actor_id'] == second['actor_id']
    a, b = first['current_invocation'], second['current_invocation']
    assert a['delegate_operation_id'] == b['delegate_operation_id']
    assert a['description_sha256'] != b['description_sha256']
    assert 'Completion follow-up' in b['description']
    assert cs.list_objects('DelegatedTask')[0]['payload']['goal'] == call['args']['description']


async def test_r03_current_invocation_parallel_nested_and_cancel_isolation(ws, request):
    import asyncio
    from report_agent.content_tasks import delegated_task, current_invocation, invocation_binding
    from report_agent.content_store import Actor
    from report_agent.errors import ActionForbidden
    seed(ws)
    ready, release = asyncio.Event(), asyncio.Event()
    seen = []
    async def child(label):
        call = {'id': label, 'args': {'subagent_type': 'writer', 'description': label}}
        with delegated_task(ws, 'coordinator', call) as (native, actor):
            original = current_invocation(ws, actor)
            ready.set()
            await release.wait()
            assert current_invocation(ws, actor)['description'] == label
            wrong = Actor(actor.id + 'foreign', actor.role, actor.task_id)
            with pytest.raises(ActionForbidden):
                current_invocation(ws, wrong)
            follow = {**native, 'args': {**native['args'], 'description': label + '-followup'}}
            with pytest.raises(RuntimeError):
                with invocation_binding(ws, actor, follow):
                    assert current_invocation(ws, actor)['description'] == label + '-followup'
                    raise RuntimeError('exit')
            assert current_invocation(ws, actor) == original
            seen.append((actor.id, original))
            with pytest.raises(asyncio.CancelledError):
                with invocation_binding(ws, actor, follow):
                    raise asyncio.CancelledError()
            assert current_invocation(ws, actor) == original
        with pytest.raises(ActionForbidden):
            current_invocation(ws, actor)
    tasks = [asyncio.create_task(child(v)) for v in ['parallel-a', 'parallel-b']]
    await ready.wait()
    release.set()
    await asyncio.gather(*tasks)
    assert len({a for a, _ in seen}) == 2
    assert {v['description'] for _, v in seen} == {'parallel-a', 'parallel-b'}
    trace(request, 'R03-isolation', {'observed': seen, 'nested_reset': True})
