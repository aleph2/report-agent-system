"""Offline native-input captures for the approved four R5 probe cases.

Synthetic historical reviews are explicitly fixtures. No live model is called,
no production prompt is changed, and returned provider examples prove shape only.
"""
import json
from copy import deepcopy
from pathlib import Path

from langchain_core.messages import AIMessage, ToolMessage, messages_to_dict

from report_agent import deep_runtime
from report_agent.content_tasks import delegated_task
from report_agent.task_supervision import reconcile
from test_agent_duty_trace_cases import result_value
from report_agent.bounded_review import perform_review
from test_bounded_review import Model, review_call
from test_decision_data import activate
from test_deep_runtime import Driver, invoke
from test_hierarchical_content import seed


def provider_call(name, args):
    return {'role': 'assistant', 'content': None, 'tool_calls': [{
        'id': 'synthetic-r5-response', 'type': 'function',
        'function': {'name': name, 'arguments': json.dumps(args, ensure_ascii=False)}}]}


async def capture_r5(ws, case, folder):
    """Return final actual native messages/tools after real local tools ran."""
    if case not in {'co-criteria-full', 'co-criteria-conflict',
                    'reviewer-reuse-local', 'reviewer-reuse-expanded'}:
        raise ValueError(case)
    if case.startswith('co-'):
        captured = await _criteria(ws, case)
    else:
        captured = await _review_reuse(ws, case)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    durable = {**captured, 'messages': messages_to_dict(captured['messages'])}
    (folder / 'native-capture.json').write_text(json.dumps(durable, ensure_ascii=False, indent=2), encoding='utf-8')
    return captured


def _capture(driver, role, observations, fake_response):
    selected = [messages for name, _, messages in driver.calls if name == role]
    messages = selected[-1]
    errors = [m for m in messages if isinstance(m, ToolMessage) and m.status == 'error']
    assert not errors, [m.model_dump() for m in errors]
    tools = [{'type': 'function', 'function': t} for t in driver.bindings[role][-1]]
    observations = {**observations, 'native_tool_results': [
        {'tool': m.name, 'result': result_value(m)} for m in messages if isinstance(m, ToolMessage)],
        'real_model_calls': 0, 'application_repairs': 0,
        'capture_boundary': 'next actual agent input after real local reads; no answer hint appended',
        'acceptance': 'structure only; no full-duty or semantic acceptance'}
    return {'role': role, 'messages': messages, 'tools': tools,
            'observations': observations, 'fake_response': fake_response}


async def _criteria(ws, case):
    clauses = ['Assess both objects A and B in one report.',
        'Reproduce all four table columns and the original footnote.',
        'Use the supplied layout requirements and export a separate issues workbook.']
    if case == 'co-criteria-conflict':
        clauses.append('A second current instruction of equal stated authority excludes object B. The conflict has not been resolved.')
    goal = 'Establish criteria for this commission from its actual requirements.\n' + '\n'.join(clauses)
    ws.store.set('manifest', {**ws.store.manifest, 'goal': goal,
        'sources': [{'id': 's', 'title': 'Synthetic background', 'content': 'Object A and object B are distinct.',
                     'coverage': 'complete'}]})
    cs, _, refs, _, members = seed(ws)
    activate(ws)
    requirement = next(r for r in members if r['type'] == 'Requirement')
    original = deepcopy(cs.read(requirement))
    driver = Driver(coordinator=[invoke('read_context', target_ref=requirement),
                                AIMessage(content='Offline native capture only.')])
    result = await deep_runtime.run_report(ws, driver)
    assert result['last_error'] is None, result
    assert cs.read(requirement) == original
    if case == 'co-criteria-full':
        fake_response = provider_call('commit_objects', {'operation_id': 'r5-criteria', 'objects': [{
            'client_key': 'criteria', 'type': 'Criterion', 'payload': {
                'requirement_refs': [requirement], 'purpose': 'Faithful synthetic compilation',
                'scope': 'Objects A and B; report, full table and issues workbook.',
                'expected_outcome': 'Both objects covered, four columns and footnote retained, requested layout applied.',
                'evidence_expectation': 'Compare the commissioned coverage, source table, report and workbook.',
                'allowed_limits': 'No engineering or whole-report acceptance established by this probe.'}}]})
    else:
        fake_response = provider_call('ask_human', {'category': 'requirement',
            'description': 'The current instructions both include and exclude B; which scope applies?',
            'source_ids': [], 'pause': False})
    return _capture(driver, 'coordinator', {'case': case, 'requirement': original,
        'independent_clauses': clauses, 'fixture_existing_criterion': cs.read(refs['k']),
        'pending_action': 'Real first response may investigate, retain uncertainty or propose criteria; no fixed workflow.'}, fake_response)


async def _review_reuse(ws, case):
    cs, owner, refs, base, members = seed(ws)
    prior_call = review_call(base, refs, 'r5-prior-review')
    prior_requirement = prior_call['args']['review_requirements'][0]
    prior_requirement.update(target_ref=refs['root'], material_refs=[refs['claim']],
        required_materials=[{'requirement_index': 0, 'purpose': 'Exact local body and associated claim.',
                             'refs': [refs['root'], refs['claim']]}],
        content_check_scopes=[{'requirement_index': 0, 'node_ref': refs['root'], 'kind': 'local_body'}])
    historical_raw = {'items': [{'scope_id': 'rule-comparison', 'checked_requirement_indexes': [0],
        'execution_state': 'completed', 'verdict': 'undetermined',
        'observations': [{'evidence_index': 0, 'locator': 'root local body',
                          'observation': 'Synthetic local root body read; descendants are outside this historical check.'},
                         {'evidence_index': 1, 'locator': 'claim', 'observation': 'Synthetic exact claim read.'}],
        'check_results': [{'requirement_index': 0, 'execution_state': 'completed',
            'result': 'Historical synthetic local-body check; not a subtree check.',
            'observation_indexes': [0, 1], 'remaining': ''}],
        'coverage': {'checked': ['Local body and associated claim.'], 'unchecked': [], 'blocked': [],
                     'basis': 'Exact selected objects; no subtree conclusion.'},
        'reason': 'Historical synthetic fixture; not a semantic acceptance.', 'findings': []}]}
    historical_model = Model(json.dumps(historical_raw))
    with delegated_task(ws, 'coordinator', prior_call) as (_, prior_actor):
        old_review = (await perform_review(ws, prior_actor, historical_model,
            'r5-historical-fixture', ['rule-comparison']))['review_ref']
        assert reconcile(cs, prior_actor.task_id)['execution_complete']
    assert len(historical_model.calls) == 1
    original = deepcopy(cs.read(old_review))
    additions = cs.commit(owner, 'r5-new-child', [
        {'client_key': 'child', 'type': 'ContentNode', 'payload': {'kind': 'block',
         'body': {'text': 'New child outside the historical local-body extent.'}, 'qualifiers': {}, 'claim_kind': 'structure'}},
        {'client_key': 'edge', 'type': 'Relation', 'payload': {'subject_ref': refs['root'],
         'object_ref': {'client_key': 'child'}, 'predicate': 'contains', 'position': 1,
         'provenance_kind': 'adopted_during_generation'}}])['result']['refs']
    new = cs.freeze(owner, 'r5-new-snapshot', refs['root'], members + list(additions.values()))['result']['snapshot_ref']
    current_call = review_call(new, refs, 'r5-current-review')
    current = current_call['args']['review_requirements'][0]
    current.update(deepcopy(prior_requirement))
    current['content_check_scopes'][0]['kind'] = 'subtree_bodies' if case.endswith('expanded') else 'local_body'
    current_call['args'].pop('supervision_plugin', None)
    current_call['args']['description'] = ('Assess whether the saved historical local review applies to the current assigned extent. '
        'Old review: ' + json.dumps(old_review) + '. Compare the saved assignment and change evidence. '
        'Execution completeness and semantic correctness are separate.')
    activate(ws)
    driver = Driver(coordinator=[AIMessage(content='', tool_calls=[current_call]), AIMessage(content='Offline capture ended.')],
        reviewer=[invoke('read_task_assignment'), invoke('read_context', target_ref=old_review),
                  invoke('assess_change_impact', old_snapshot=base, new_snapshot=new), AIMessage(content='Offline native capture only.')])
    result = await deep_runtime.run_report(ws, driver)
    assert result['last_error'] is None, result
    assert cs.read(old_review) == original
    fake_response = provider_call('read_review_status', {'snapshot_ref': new, 'target_ref': refs['root']})
    return _capture(driver, 'reviewer', {'case': case, 'old_review': original, 'base_snapshot': base,
        'new_snapshot': new, 'current_assignment': current_call['args']['review_requirements'],
        'new_nodes': additions, 'historical_record_origin': 'Real bounded checker pipeline with one fake response; no paid verdict.',
        'historical_fake_response': historical_raw, 'historical_checker_input': historical_model.calls[0],
        'pending_action': 'No confirm_review_reuse or new semantic review has run.'}, fake_response)
