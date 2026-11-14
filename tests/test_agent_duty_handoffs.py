"""Responsibility handoffs through native agents; fake decisions, real boundaries."""
import json

import pytest
from langchain_core.messages import AIMessage

from report_agent.deep_runtime import run_report
from test_agent_result_delivery import packet, reply
from test_bounded_review import Model, review_call
from test_decision_data import activate
from test_deep_runtime import Driver, invoke
from test_hierarchical_content import seed
from test_task_supervision import ws, offline


@pytest.mark.parametrize('role', ['writer', 'reviewer', 'layout'])
@pytest.mark.parametrize('managed', [False, True])
async def test_explicit_assignment_and_child_limits_reach_next_decision(ws, role, managed):
    cs, _, refs, snapshot, _ = seed(ws)
    if managed:
        activate(ws)
    requirement = ('Synthetic context. ' * 40 +
                   'TAIL_REQUIREMENT: retain the complete table, including its unresolved footnote.')
    child_result = json.dumps({'selected_ref': refs['claim'], 'complete': False,
                              'remaining': 'TAIL_RETURN: original table has not been verified.'})
    args = {'subagent_type': role, 'description': requirement}
    if role == 'reviewer':
        args = {**review_call(snapshot, refs)['args'], 'description': requirement}
        args.pop('supervision_plugin', None)
    elif role == 'layout':
        args['layout_snapshot_ref'] = snapshot
    inspected = []

    def child(messages):
        # Only explicitly sent task text is required; no imaginary inherited C1.
        assert requirement in '\n'.join(str(m.content) for m in messages)
        inspected.append('child')
        return AIMessage(content=child_result)

    def parent(messages):
        returned = reply(messages, 'task')
        assert child_result in str(returned.content)
        assert 'TAIL_RETURN' in str(returned.content)
        inspected.append('parent')
        return AIMessage(content='Unfinished work is recorded, without claiming acceptance.')

    driver = Driver(coordinator=[invoke('task', **args), parent], **{role: [child]})
    result = await run_report(ws, driver)
    assert result['last_error'] is None, result
    assert inspected == ['child', 'parent']
    tasks = cs.list_objects('DelegatedTask')
    assert len(tasks) == 1 and tasks[0]['payload']['goal'] == requirement
    assert not cs.list_objects('ReviewRecord')


@pytest.mark.parametrize('managed', [False, True])
async def test_writer_selected_criterion_and_source_reach_independent_text_tool(ws, managed):
    cs, _, refs, snapshot, _ = seed(ws)
    if managed:
        activate(ws)
    source = next(r for r in cs.read(snapshot)['payload']['refs'] if r['type'] == 'SourceArtifact')
    selected = [refs['k'], source]
    objective = 'Use the selected synthetic class table; preserve the exact constraint.'
    answer = {'kind': 'block', 'body': {'text': 'Class B permits 75 to 100.'},
              'qualifiers': {'limit': 'Synthetic example only; no engineering acceptance.'},
              'claim_kind': 'fact'}
    model = Model(json.dumps(answer))

    def inspect(messages):
        returned = packet(reply(messages, 'process_report_content'))
        value = returned.get('metadata', returned)
        assert value['semantic_correctness_verified'] is False
        wire = json.loads(model.calls[0][1][1])
        encoded = json.dumps(wire, ensure_ascii=False)
        assert objective in encoded
        # IDs alone are insufficient: the exact selected local payloads must arrive.
        for ref in selected:
            delivered = [item['object'] for item in wire['evidence']
                         if item.get('kind') == 'saved_object' and item['object']['ref'] == ref]
            assert len(delivered) == 1
            assert delivered[0]['payload'] == cs.read(ref)['payload']
        return AIMessage(content='Produced candidate only; adoption remains a separate action.')

    driver = Driver(coordinator=[invoke('task', subagent_type='writer', description=objective),
                                 AIMessage(content='Candidate result received.')],
                    writer=[invoke('process_report_content', operation_id='explicit-inputs',
                                   objective=objective, object_type='ContentNode', input_refs=selected), inspect])
    result = await run_report(ws, lambda role: model if role == 'text_tool' else driver(role))
    assert result['last_error'] is None, result
    assert len(model.calls) == 1
    assert len(cs.list_objects('ContentNode')) == 2


@pytest.mark.parametrize('role', ['writer', 'layout'])
@pytest.mark.parametrize('managed', [False, True])
async def test_resume_instruction_delivery_diagnostic(ws, role, managed, request):
    from report_agent.task_context import exact_task_context
    cs, _, _, snapshot, _ = seed(ws)
    if managed:
        activate(ws)
    old_goal = ('Use right margin 15mm.' if role == 'layout' else
                'Prepare the synthetic report paragraph as a draft.')
    new_goal = ('For this revision replace the previous 15mm right margin with 20mm; '
                'keep all other content and permissions unchanged.' if role == 'layout' else
                'For this revision replace the previous draft request: investigate the missing class evidence; '
                'do not generate a paragraph yet. Ownership and source permissions are unchanged.')
    captured = []

    def child(messages):
        state = exact_task_context(ws, role)
        human = [m.content for m in messages if m.type == 'human']
        captured.append({'human': human, 'application_state': state,
                         'system': [m.content for m in messages if m.type == 'system']})
        return AIMessage(content='Synthetic inspection only; no file changed.')

    def resume(messages):
        task = cs.list_objects('DelegatedTask')[0]
        call = invoke('task', subagent_type=role, description=new_goal,
                      resume_content_task_id=task['ref']['id'])
        call.tool_calls[0]['id'] = 'resume-same-owner'
        return call

    args = {'subagent_type': role, 'description': old_goal}
    if role == 'layout':
        args['layout_snapshot_ref'] = snapshot
    driver = Driver(coordinator=[invoke('task', **args), resume, AIMessage(content='Inspection ended.')],
                    **{role: [child]})
    result = await run_report(ws, driver)
    assert result['last_error'] is None, result
    assert len(captured) == 2
    assert old_goal in str(captured[0]['human']) and new_goal in str(captured[1]['human'])
    assert captured[0]['application_state']['actor_id'] == captured[1]['application_state']['actor_id']
    assert len(cs.list_objects('DelegatedTask')) == 1
    if role == 'layout':
        assert captured[1]['application_state']['assignment']['layout_snapshot_ref'] == snapshot
    # This diagnostic records a possible authority conflict for Neo to judge.
    # A surviving original goal alone is NOT a proof of wrong model behavior.
    request.node.user_properties.append(('resume_currentness_diagnostic', json.dumps({
        'role': role, 'managed': managed, 'initial_goal': old_goal, 'new_instruction': new_goal,
        'captured': captured, 'model_semantic_behavior_tested': False}, ensure_ascii=False)))


@pytest.mark.parametrize('fault', ['source_240', 'producer_limits_removed'])
async def test_existing_oracle_detects_historical_information_loss(ws, monkeypatch, fault, request):
    from copy import deepcopy
    import traceback
    from langchain_core.messages import ToolMessage
    from test_agent_duty_trace_cases import result_value,assert_delegated_failure
    from report_agent import decision_data
    from test_agent_result_delivery import (
        test_each_report_agent_receives_source_tail_or_recovers_exact_field as source_oracle,
        test_writer_generation_qualifications_reach_next_model_and_exact_save as producer_oracle)
    original = decision_data.public_value
    original_respond = Driver.respond
    injected = []
    assertion_sites = []
    assertion_messages,failed_tasks,parent_failures=[],[],[]

    def lose_information(tool, value):
        metadata, complete = original(tool, value)
        target = 'read_source_page' if fault == 'source_240' else 'process_report_content'
        if tool != target:
            return metadata, complete
        metadata = deepcopy(metadata)
        if fault == 'source_240':
            metadata['blocks'][0]['text'] = metadata['blocks'][0]['text'][:240]
        else:
            metadata['outputs']['entries'][0]['qualifiers'] = {}
        injected.append(tool)
        return metadata, complete

    async def observe_original_assertion(self, role, messages):
        if role=='coordinator':
            parent_failures.extend(m for m in messages if isinstance(m,ToolMessage) and m.name=='task' and m.status=='error' and
                result_value(m).get('code')=='DELEGATED_EXECUTION_FAILED')
        try:
            return await original_respond(self, role, messages)
        except AssertionError as exc:
            from report_agent.content_tasks import bound_actor
            failed_tasks.append(bound_actor(ws,role,None).task_id)
            assertion_messages.append(str(exc))
            # Native execution turns child exceptions into last_error. Capture
            # the untouched oracle's assertion before that normal handling.
            assertion_sites.extend({'function': frame.name, 'line': frame.line,
                                    'file': frame.filename, 'lineno': frame.lineno}
                                   for frame in traceback.extract_tb(exc.__traceback__))
            raise

    monkeypatch.setattr(decision_data, 'public_value', lose_information)
    monkeypatch.setattr(Driver, 'respond', observe_original_assertion)
    if fault=='source_240':
        await source_oracle(ws,monkeypatch,'reviewer',False)
        assert len(parent_failures)==1 and assertion_messages
        error=assert_delegated_failure(ws,parent_failures[0],'AssertionError',actor_task_ids=failed_tasks)
        assert error['error']['message']=='EXECUTION_FAILED'
        outer_error=assertion_messages[0]
    else:
        with pytest.raises(AssertionError) as failure:
            await producer_oracle(ws,monkeypatch,False)
        outer_error=str(failure.value)
    assert injected
    expected_function, expected_expression = (
        ('inspect_source', "assert shown['metadata']['blocks'][0]['text'] == literal")
        if fault == 'source_240' else
        ('inspect_generation', "assert value['outputs']['entries'][0]['qualifiers'] == payload['qualifiers']"))
    assert any(site['function'] == expected_function and site['line'] == expected_expression
               for site in assertion_sites), assertion_sites
    request.node.user_properties.append(('oracle_sensitivity', json.dumps({
        'fault': fault, 'injected_at': 'decision_data.public_value, memory only',
        'unchanged_original_oracle_failed': True, 'assertion_sites': assertion_sites,
        'outer_error': outer_error[:1000],
        'application_files_modified': False})))


def test_existing_oracle_detects_incompatible_completion_reuse(ws, monkeypatch, request):
    import inspect
    import traceback
    from report_agent import task_supervision
    import test_task_supervision as retained

    # Recreate only the historical missing comparison, in memory. Keep source
    # receipts, versions, ownership and all other independent checks enabled.
    source = inspect.getsource(task_supervision.reconcile)
    comparison = '"source_ranges", "content_check_scopes", "artifact_check_scopes"'
    assert source.count(comparison) == 1
    changed = source.replace(comparison, '"source_ranges", "artifact_check_scopes"')
    namespace = dict(task_supervision.__dict__)
    exec(compile(changed, '<test-only-incompatible-completion>', 'exec'), namespace)
    mutated = namespace['reconcile']
    observed = []

    def observe(contents, task_id):
        result = mutated(contents, task_id)
        observed.append(result)
        return result

    monkeypatch.setattr(task_supervision, 'reconcile', observe)
    monkeypatch.setattr(retained, 'reconcile', observe)
    with pytest.raises(AssertionError) as failure:
        retained.test_saved_completion_reuse_requires_same_content_body_extent(
            ws, 'local_body', 'subtree_bodies', 'root', False)
    site = traceback.extract_tb(failure.value.__traceback__)[-1]
    assert site.name == 'test_saved_completion_reuse_requires_same_content_body_extent'
    assert site.line == 'assert outcome["execution_complete"] is expected_reuse'
    assert len(observed) == 2 and observed[-1]['execution_complete'] is True
    request.node.user_properties.append(('oracle_sensitivity', json.dumps({
        'fault': 'reuse_local_review_for_subtree',
        'injected_at': 'reconcile obligation comparison, memory only',
        'unchanged_original_oracle_failed': True,
        'assertion_site': {'function': site.name, 'line': site.line, 'lineno': site.lineno},
        'mutated_result': observed[-1], 'application_files_modified': False}, ensure_ascii=False)))
