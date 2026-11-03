"""Remaining native reader/handoff paths, using fake decisions and real tools.

These cases exercise exact registered caller paths, not real model judgment.
Only temporary synthetic workspaces are written; no application repairs.
"""
import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from report_agent.bounded_review import perform_review
from report_agent.content_export import export_snapshot
from report_agent.content_tasks import bound_actor, delegated_task
from report_agent.deep_runtime import run_report
from report_agent.task_context import exact_task_context
from report_agent.task_supervision import ReviewRequirement
from test_agent_duty_completion_resume import checkpoint
from test_agent_duty_trace_cases import action, result_value, tool_reply
from test_agent_result_delivery import run_role
from test_bounded_review import Model, review_call
from test_decision_data import activate
from test_deep_runtime import Driver, invoke
from test_hierarchical_content import seed
from test_task_supervision import ws, offline


def record(request, case, conditions, observed):
    request.node.user_properties.append(('remaining_native_evidence', json.dumps({
        'case': case, 'conditions': conditions, 'observed': observed,
        'paid_calls': 0, 'application_repairs': 0,
        'limit': 'Scripted next actions verify program delivery only; no semantic acceptance.'
    }, ensure_ascii=False, default=str)))


def receive(messages, call_id, observed):
    message = tool_reply(messages, call_id)
    observed.setdefault('next_inputs', []).append(message.model_dump())
    return message


def protected(cs, refs):
    return [deepcopy(cs.read(ref)) for ref in refs]


def unchanged(cs, originals):
    assert [cs.read(item['ref']) for item in originals] == originals


async def negative_review(ws, cs, refs, snapshot):
    """A real bounded-review save with a fake independent checker, after activation."""
    source = next(r for r in cs.read(snapshot)['payload']['refs'] if r['type'] == 'SourceArtifact')
    model = Model()
    with delegated_task(ws, 'coordinator', review_call(
            snapshot, refs, id='historical-negative', reads=[source])) as (_, reviewer):
        result = await perform_review(ws, reviewer, model, 'historical-negative-review', ['rule-comparison'])
    saved = cs.read(result['review_ref'])
    assert saved['payload']['items'][0]['verdict'] == 'not_satisfied'
    assert len(model.calls) == 1
    return saved


@pytest.mark.parametrize('populated', [False, True], ids=['empty-project-history', 'cross-author-handling'])
async def test_writer_reads_project_handling_without_inventing_owner_filter(ws, request, populated):
    cs, owner, refs, snapshot, members = seed(ws)
    activate(ws)
    originals = protected(cs, [*members, snapshot])
    expected = []
    if populated:
        result = cs.handoff(owner, 'co-feedback', refs['claim'],
            'Scope B remains unresolved.', ['synthetic source s'],
            'Keep the conditional claim; this record does not resolve it.')
        expected = [cs.read(result['result']['handling_ref'])]
    observed = {'populated': populated, 'expected_records': expected}

    def inspect(messages):
        message = receive(messages, 'read_feedback', observed)
        assert message.status == 'success'
        value = result_value(message)
        assert value['result']['records'] == expected
        assert value['result']['total'] == len(expected)
        assert value['result']['next_offset'] is None
        assert value['receipt_id']
        if populated:
            assert expected[0]['owner_id'] != exact_task_context(ws, 'writer')['actor_id']
            assert expected[0]['payload']['handling_state'] == 'open'
        return AIMessage(content='Project history observed; scope B remains unresolved.')

    try:
        await run_role(ws, 'writer', [invoke('read_feedback', offset=0, limit=1), inspect], refs, snapshot)
        unchanged(cs, originals)
        assert cs.list_objects('HandlingRecord') == expected
        assert not cs.list_objects('ReviewRecord')
    finally:
        record(request, 'reader-feedback', ['P09.C1', 'P01.C1'], observed)


@pytest.mark.parametrize('role', ['writer', 'reviewer'])
@pytest.mark.parametrize('invalid', [False, True], ids=['paged-index', 'negative-offset'])
async def test_writer_and_reviewer_receive_actual_content_index(ws, request, role, invalid):
    cs, _, refs, snapshot, members = seed(ws)
    activate(ws)
    originals = protected(cs, [*members, snapshot])
    nodes = [r for r in cs.read(snapshot)['payload']['refs'] if r['type'] == 'ContentNode']
    observed = {'role': role, 'invalid': invalid, 'expected_refs': nodes, 'pages': []}

    def inspect(messages):
        message = receive(messages, 'index-first', observed)
        if invalid:
            assert message.status == 'error' and 'INVALID_PAGE' in str(message.content)
            return AIMessage(content='Invalid page retained; no content read claimed.')
        assert message.status == 'success'
        value = result_value(message)
        observed['pages'].append(value)
        assert value['returned_refs'] == nodes[:1]
        assert value['total_nodes'] == len(nodes) == 2
        assert value['next_offset'] == 1 and 'not content observation' in value['scope_note']
        return action('read_content_index', 'index-next', snapshot_ref=snapshot, offset=1, limit=1)

    def finish(messages):
        message = receive(messages, 'index-next', observed)
        assert message.status == 'success'
        value = result_value(message)
        observed['pages'].append(value)
        assert value['returned_refs'] == nodes[1:] and value['next_offset'] is None
        assert [n['ref'] for page in observed['pages'] for n in page['nodes']] == nodes
        for page in observed['pages']:
            assert page['snapshot_ref'] == snapshot
            for node in page['nodes']:
                original = cs.read(node['ref'])
                assert node['owner_id'] == original['owner_id']
                assert node['payload_digest'] == original['payload_digest']
                assert 'body' not in node
        return AIMessage(content='Exact metadata recovered; the claims remain unreviewed.')

    script = [action('read_content_index', 'index-first', snapshot_ref=snapshot,
                     offset=-1 if invalid else 0, limit=1), inspect]
    if not invalid:
        script.append(finish)
    try:
        await run_role(ws, role, script, refs, snapshot)
        unchanged(cs, originals)
        assert not cs.list_objects('ReviewRecord')
    finally:
        record(request, 'reader-index', ['P03.C2', 'P05.C1'], observed)


@pytest.mark.parametrize('missing', [False, True], ids=['assigned-checks', 'missing-path'])
async def test_reviewer_reads_server_bound_state_and_missing_path(ws, request, missing):
    cs, _, refs, snapshot, members = seed(ws)
    activate(ws)
    originals = protected(cs, [*members, snapshot])
    path = ['assignment', 'missing_field'] if missing else ['assignment', 'review_requirements', 0, 'required_checks']
    expected = deepcopy(review_call(snapshot, refs)['args']['review_requirements'][0]['required_checks'])
    observed = {'path': path, 'expected_checks': expected}

    def inspect(messages):
        message = receive(messages, 'read_decision_state', observed)
        if missing:
            assert message.status == 'error' and 'STATE_PATH_NOT_FOUND' in str(message.content)
        else:
            assert message.status == 'success'
            value = result_value(message)
            assert value['path'] == path and value['value'] == expected
            assert value['complete_value'] and value['next_offset'] is None
            assert value['semantic_acceptance'] is False and value['observation_receipt'] is None
            observed['actual_assignment'] = exact_task_context(ws, 'reviewer')['assignment']
        return AIMessage(content='State inspection only; assigned check not performed.')

    try:
        await run_role(ws, 'reviewer', [invoke('read_decision_state', path=path), inspect], refs, snapshot)
        unchanged(cs, originals)
        assert not cs.list_objects('ReviewRecord')
    finally:
        record(request, 'reader-state', ['P09.C2', 'P08.C1'], observed)


@pytest.mark.parametrize('foreign', [False, True], ids=['own-content-receipt', 'foreign-owner'])
async def test_reviewer_operation_receipt_preserves_exact_owner_boundary(ws, request, foreign):
    cs, owner, refs, snapshot, members = seed(ws)
    activate(ws)
    originals = protected(cs, [*members, snapshot])
    operation = 'receipt-owner-boundary'
    args = {'operation_id': operation, 'target_ref': refs['claim'],
            'problem': 'Selected scope B is still open.', 'evidence': ['s'],
            'impact': 'No positive report judgment follows.'}
    observed = {'foreign': foreign, 'operation': operation}
    if foreign:
        observed['foreign_response'] = cs.handoff(owner, operation, refs['claim'],
            args['problem'], args['evidence'], args['impact'])

    def get_own(messages):
        message = receive(messages, 'record_handoff', observed)
        assert message.status == 'success'
        observed['own_response'] = result_value(message)
        return invoke('get_operation_receipt', operation_id=operation)

    def inspect(messages):
        message = receive(messages, 'get_operation_receipt', observed)
        if foreign:
            assert message.status == 'error' and 'FORBIDDEN: operation owner' in str(message.content)
            assert observed['foreign_response']['result']['handling_ref']['id'] not in str(message.content)
        else:
            assert message.status == 'success'
            value = result_value(message)
            assert value['state'] == 'known_success'
            assert value['response'] == observed['own_response']
            assert value['response']['result']['handling_ref']['type'] == 'HandlingRecord'
            assert 'text_work' not in value
        return AIMessage(content='Receipt ownership preserved; no report approval.')

    script = ([invoke('get_operation_receipt', operation_id=operation), inspect] if foreign else
              [invoke('record_handoff', **args), get_own, inspect])
    try:
        await run_role(ws, 'reviewer', script, refs, snapshot)
        unchanged(cs, originals)
        assert len(cs.list_objects('HandlingRecord')) == 1 and not cs.list_objects('ReviewRecord')
        if foreign:
            assert cs.receipt(owner, operation)['response'] == observed['foreign_response']
    finally:
        record(request, 'reader-receipt', ['P20.C4', 'P09.C1'], observed)


@pytest.mark.parametrize('mismatch', [False, True], ids=['exact-export', 'different-snapshot'])
async def test_reviewer_delivery_context_binds_exact_snapshot_and_export(ws, request, mismatch):
    cs, owner, refs, snapshot, members = seed(ws)
    activate(ws)
    exported = export_snapshot(cs, owner, 'synthetic-word', snapshot, {'toc': False})['result']['export_ref']
    selected = cs.freeze(owner, 'other-snapshot', refs['root'], members)['result']['snapshot_ref'] if mismatch else snapshot
    originals = protected(cs, [*members, snapshot, exported, *([selected] if mismatch else [])])
    observed = {'selected_snapshot': selected, 'export_snapshot': snapshot, 'export_ref': exported}

    def inspect(messages):
        message = receive(messages, 'read_delivery_review_context', observed)
        if mismatch:
            assert message.status == 'error' and 'DELIVERY_VERSION_MISMATCH' in str(message.content)
        else:
            assert message.status == 'success'
            value = result_value(message)
            assert value['snapshot_ref'] == snapshot and value['export_ref'] == exported
            assert value['criteria'] == [cs.read(refs['k'])]
            assert 'do not establish review coverage' in value['limitation']
            observed['coverage_inventory'] = value['coverage_inventory']
        return AIMessage(content='Inventory alone grants no content or visual acceptance.')

    try:
        await run_role(ws, 'reviewer', [invoke('read_delivery_review_context',
            snapshot_ref=selected, export_ref=exported), inspect], refs, snapshot)
        unchanged(cs, originals)
        assert not cs.list_objects('ReviewRecord')
    finally:
        record(request, 'reader-delivery-context', ['P08.C1', 'P10.C1'], observed)


@pytest.mark.parametrize('assigned', [False, True], ids=['unassigned', 'assigned-not-reviewed'])
async def test_coordinator_obligation_inventory_does_not_turn_assignment_into_review(ws, request, assigned):
    cs, _, refs, snapshot, members = seed(ws)
    activate(ws)
    originals = protected(cs, [*members, snapshot])
    expected = deepcopy(review_call(snapshot, refs)['args'])
    expected.pop('supervision_plugin', None)
    observed = {'assigned': assigned, 'expected_requirement': expected['review_requirements'][0]}

    def request_coverage(messages):
        message = receive(messages, 'task', observed)
        assert message.status == 'success'
        return invoke('read_review_obligation_coverage', snapshot_ref=snapshot)

    def inspect(messages):
        message = receive(messages, 'read_review_obligation_coverage', observed)
        assert message.status == 'success'
        value = result_value(message)['result']
        assert value['snapshot_ref'] == snapshot and value['semantic_coverage_verified'] is False
        assert len(value['criteria']) == 1
        criterion = value['criteria'][0]
        assert criterion['criterion'] == cs.read(refs['k'])
        assert criterion['requirements'] == [cs.read(r) for r in cs.read(refs['k'])['payload']['requirement_refs']]
        assert criterion['assignment_present'] is assigned
        assert value['criteria_without_assignment'] == ([] if assigned else [refs['k']])
        if assigned:
            assert len(criterion['assigned_scopes']) == 1
            actual = criterion['assigned_scopes'][0]['requirement']
            original = expected['review_requirements'][0]
            # Every supplied field remains exact. Only equivalent public schema
            # defaults are allowed; no expected value is inferred from output.
            for field, value in original.items():
                assert actual[field] == value
            assert (ReviewRequirement.model_validate(actual).model_dump()
                    == ReviewRequirement.model_validate(original).model_dump())
        else:
            assert criterion['assigned_scopes'] == []
        assert not cs.list_objects('ReviewRecord')
        observed['coverage'] = value
        return AIMessage(content='No substantive review has been completed.')

    script = ([invoke('task', **expected), request_coverage, inspect] if assigned else
              [invoke('read_review_obligation_coverage', snapshot_ref=snapshot), inspect])
    driver = Driver(coordinator=script, reviewer=[AIMessage(content='Required evidence not yet compared; review remains open.')])
    try:
        result = await run_report(ws, driver)
        assert result['last_error'] is None, result
        unchanged(cs, originals)
        assert not cs.list_objects('ReviewRecord')
    finally:
        record(request, 'reader-obligation-coverage', ['P08.C1', 'P09.C1'], observed)


@pytest.mark.parametrize('role', ['coordinator', 'writer', 'reviewer', 'layout'])
@pytest.mark.parametrize('invalid', [False, True], ids=['open-scope', 'blank-problem'])
async def test_each_role_records_exact_handoff_without_rewriting_report_or_verdict(ws, request, role, invalid):
    cs, _, refs, snapshot, members = seed(ws)
    activate(ws)
    review = await negative_review(ws, cs, refs, snapshot)
    originals = protected(cs, [*members, snapshot, review['ref']])
    args = {'operation_id': 'native-handoff', 'target_ref': refs['claim'],
            'problem': ' ' if invalid else 'Class selection for scope B remains unresolved.',
            'evidence': ['s: original interval', 'scope:B; not whole report'],
            'impact': 'Scope B remains conditional; the negative review is not repaired.',
            'handling_state': 'open'}
    observed = {'role': role, 'invalid': invalid, 'arguments': deepcopy(args), 'original_review': review}

    def inspect(messages):
        message = receive(messages, 'record_handoff', observed)
        if invalid:
            assert message.status == 'error' and 'INVALID_HANDOFF' in str(message.content)
            assert not cs.list_objects('HandlingRecord')
        else:
            assert message.status == 'success'
            value = result_value(message)
            saved = cs.read(value['result']['handling_ref'])
            observed['saved'] = saved
            assert saved['owner_id'] == exact_task_context(ws, role)['actor_id']
            assert saved['payload'] == {k: args[k] for k in ('target_ref', 'problem', 'evidence', 'impact', 'handling_state')} | {'previous_handling_ref': None}
            assert saved['payload']['target_ref'] == refs['claim']
            assert cs.list_objects('HandlingRecord') == [saved]
        unchanged(cs, originals)
        return AIMessage(content='Handoff status is not a changed engineering judgment.')

    try:
        await run_role(ws, role, [invoke('record_handoff', **args), inspect], refs, snapshot)
        unchanged(cs, originals)
        assert cs.list_objects('ReviewRecord') == [review]
    finally:
        record(request, 'native-handoff', ['P09.C1', 'P09.C3'], observed)


@pytest.mark.parametrize('invalid', [False, True], ids=['capability-request', 'missing-attempt'])
async def test_layout_capability_request_preserves_scope_and_does_not_implement_it(ws, request, invalid):
    cs, _, refs, snapshot, members = seed(ws)
    activate(ws)
    originals = protected(cs, [*members, snapshot])
    args = {'operation_id': 'native-capability', 'snapshot_ref': snapshot,
            'problem': 'Synthetic diagonal table border is not exposed.',
            'attempted': [] if invalid else ['Read current layout controls; diagonal border absent.'],
            'requested_operation': 'Support one source-bound diagonal border.',
            'evidence': ['synthetic capability observation; no report judgment']}
    observed = {'invalid': invalid, 'arguments': deepcopy(args)}

    def inspect(messages):
        message = receive(messages, 'request_layout_capability', observed)
        if invalid:
            assert message.status == 'error' and 'CAPABILITY_REQUEST_REQUIRES_ATTEMPTS_EVIDENCE_AND_OPERATION' in str(message.content)
            assert not cs.list_objects('HandlingRecord')
        else:
            assert message.status == 'success'
            value = result_value(message)
            saved = cs.read(value['result']['handling_ref'])
            observed['saved'] = saved
            payload = saved['payload']
            assert payload['target_ref'] == snapshot and payload['handling_state'] == 'open'
            assert payload['problem'] == args['problem'] and payload['evidence'] == args['evidence']
            assert payload['requested_operation'] == args['requested_operation'] and payload['attempted'] == args['attempted']
            assert payload['kind'] == 'layout_capability_request' and payload['destination'] == 'development'
            context = exact_task_context(ws, 'layout')
            assert saved['owner_id'] == context['actor_id']
            assert payload['resume_task_id'] == bound_actor(ws, 'layout', None).task_id
            folder = Path(__file__).resolve().parents[1] / 'src/report_agent'
            expected = hashlib.sha256(b''.join((folder / name).read_bytes() for name in
                ('content_layout.py', 'content_export.py', 'g3_export.py', 'material_issues.py',
                 'office_finalize.py', 'office_render.py', 'layout_capabilities.py'))).hexdigest()
            assert payload['capability_version'] == expected
        unchanged(cs, originals)
        assert not cs.list_objects('ExportArtifact') and not cs.list_objects('ReviewRecord')
        return AIMessage(content='Development request only; capability not implemented or approved.')

    try:
        await run_role(ws, 'layout', [invoke('request_layout_capability', **args), inspect], refs, snapshot)
        unchanged(cs, originals)
    finally:
        record(request, 'native-capability', ['P11.C2'], observed)


@pytest.mark.parametrize('pause', [False, True], ids=['continue-with-open-issue', 'checkpoint-and-operator-resume'])
async def test_coordinator_ask_human_records_unresolved_issue_and_actual_pause(ws, request, pause):
    cs, _, refs, snapshot, members = seed(ws)
    activate(ws)
    originals = protected(cs, [*members, snapshot])
    args = {'category': 'requirement', 'description': 'Synthetic scope B needs an operator choice.',
            'source_ids': ['s'], 'pause': pause}
    answer = 'Keep scope B unresolved; continue only independently supported work.'
    observed = {'arguments': deepcopy(args), 'operator_decision': answer, 'next_inputs': []}

    def inspect(messages):
        message = receive(messages, 'ask_human', observed)
        assert message.status == 'success'
        value = result_value(message)
        issue = value.get('issue', value)
        assert issue['description'] == args['description'] and issue['source_ids'] == ['s']
        assert issue['resolved'] is False
        if pause:
            # Re-execution may return the now-saved operator issue directly.
            assert issue['decision_origin'] == 'operator' and issue['decision'] == answer
        else:
            assert value['waiting_for_human'] is True and value['execution_paused'] is False
            assert 'decision' not in issue
        return AIMessage(content='Only supported work may continue; scope B remains unresolved.')

    driver = Driver(coordinator=[invoke('ask_human', **args), inspect])
    try:
        first = await run_report(ws, driver)
        saved = await checkpoint(ws, driver)
        observed.update(first=first, first_checkpoint=saved)
        issues = ws.store.get('report_issues')
        assert len(issues) == 1 and not issues[0]['resolved']
        if pause:
            assert saved['next'] and len(saved['interrupts']) == 1
            assert saved['interrupts'][0]['value']['issue_id'] == issues[0]['id']
            assert observed['next_inputs'] == []
            ws.decide_issue(issues[0]['id'], answer, resolved=False)
            second = await run_report(ws, driver)
            after = await checkpoint(ws, driver)
            observed.update(second=second, resumed_checkpoint=after)
            assert second['last_error'] is None
            assert not after['next'] and not after['interrupts']
            assert len(ws.store.get('report_issues')) == 1
        else:
            assert first['last_error'] is None and not saved['next'] and not saved['interrupts']
        assert len(observed['next_inputs']) == 1
        unchanged(cs, originals)
        assert not cs.list_objects('HandlingRecord') and not cs.list_objects('ReviewRecord')
    finally:
        record(request, 'native-ask-human', ['P02.C4', 'P09.C1'], observed)


from test_learning_text_work import case as learning_case


@pytest.mark.parametrize('variant', [
    'no-change-valid', 'no-change-has-candidate',
    'no-change-id-only', 'no-change-version-only',
    'candidate-valid', 'candidate-wrong-feedback',
])
async def test_p18_native_candidate_disposition_link_has_independent_controls(
        learning_case, request, variant):
    """Two logical contrasts plus each OR-guard field through native input.

    Both target feedback IDs are in the same current assignment. A candidate is
    always present, so absence of a library candidate cannot explain a rejection.
    The fake chooses the calls; it does not verify learned strategy usefulness.
    """
    from report_agent.learning_runtime import build_optimizer

    workspace, library, scope, feedback_a = learning_case
    feedback_b = library.feedback(scope, {}, {}, 'Other assigned feedback',
                                  'Unresolved class C', ['Original C rule'])
    preserved = library.feedback(scope, {}, {}, 'Preserve this earlier disposition',
                                 'Unverified source', ['Source remains unavailable'])
    assignment = {'id': 'p18-link-claim',
                  'feedback_ids': [feedback_a['id'], feedback_b['id'], preserved['id']]}
    workspace.store.set('learning_active_feedback', assignment)
    original_job = deepcopy(workspace.store.get('learning_job'))
    candidate = library.propose(scope, [feedback_a['id']], 'general_skill',
        'Candidate tied only to A', 'Compare the located rule before choosing a value.',
        'Only the supplied synthetic evidence; unresolved class stays unresolved.',
        'Unpublished and unverified candidate.')
    original_candidates = deepcopy(library.list_versions(scope))
    original_feedback = deepcopy(library.feedback_items(scope))
    assert len(original_candidates) == 1 and not library.search(scope)
    preserved_args = {'feedback_id': preserved['id'], 'outcome': 'insufficient_evidence',
                      'rationale': 'Original source is unavailable; retain uncertainty.'}
    args = {'feedback_id': feedback_a['id'],
            'outcome': 'no_change' if variant.startswith('no-change') else 'candidate',
            'rationale': 'Preserve the existing synthetic feedback and uncertainty.'}
    if variant != 'no-change-valid':
        args.update(experience_id=candidate['id'], experience_version=candidate['version'])
    if variant == 'no-change-id-only':
        del args['experience_version']
    if variant == 'no-change-version-only':
        del args['experience_id']
    if variant == 'candidate-wrong-feedback':
        args['feedback_id'] = feedback_b['id']
    expected_code = {
        'no-change-has-candidate': 'NON_CANDIDATE_DISPOSITION_HAS_CANDIDATE',
        'no-change-id-only': 'NON_CANDIDATE_DISPOSITION_HAS_CANDIDATE',
        'no-change-version-only': 'NON_CANDIDATE_DISPOSITION_HAS_CANDIDATE',
        'candidate-wrong-feedback': 'CANDIDATE_FEEDBACK_MISMATCH',
    }.get(variant)
    observed = {'variant': variant, 'exact_request': deepcopy(args),
                'independent_expected_code': expected_code, 'next_inputs': []}
    expected_preserved = {**preserved_args, 'claim_id': assignment['id'], 'quality_verified': False}

    def after_preserved(messages):
        message = receive(messages, 'preserve-disposition', observed)
        assert message.status == 'success'
        assert result_value(message) == expected_preserved
        assert workspace.store.get('learning_job')['feedback_dispositions'] == {
            preserved['id']: expected_preserved}
        return action('read_experience_candidates', 'read-exact-candidate',
                      experience_id=candidate['id'], version=candidate['version'])

    def after_read(messages):
        message = receive(messages, 'read-exact-candidate', observed)
        assert message.status == 'success'
        value = result_value(message)
        assert value['next_offset'] is None
        assert json.loads(value['text']) == original_candidates[0]
        return action('record_feedback_disposition', 'target-disposition', **args)

    def finish(messages):
        message = receive(messages, 'target-disposition', observed)
        job = workspace.store.get('learning_job')
        assert job['id'] == original_job['id'] and job['state'] == original_job['state']
        assert job['feedback_dispositions'][preserved['id']] == expected_preserved
        if expected_code:
            assert message.status == 'error'
            assert message.content == expected_code
            assert job['feedback_dispositions'] == {preserved['id']: expected_preserved}
        else:
            assert message.status == 'success'
            expected = {k: args[k] for k in ('feedback_id', 'outcome', 'rationale')}
            expected.update(claim_id=assignment['id'], quality_verified=False)
            if args['outcome'] == 'candidate':
                expected['candidate'] = {'id': candidate['id'], 'version': candidate['version']}
            assert result_value(message) == expected
            assert job['feedback_dispositions'] == {
                preserved['id']: expected_preserved, feedback_a['id']: expected}
        assert library.list_versions(scope) == original_candidates
        assert library.feedback_items(scope) == original_feedback
        assert workspace.store.get('learning_active_feedback') == assignment
        assert not library.search(scope)
        return AIMessage(content='Only the recorded disposition changed; no strategy acceptance or release.')

    driver = Driver(optimizer=[
        action('record_feedback_disposition', 'preserve-disposition', **preserved_args),
        after_preserved, after_read, finish])
    try:
        result = await build_optimizer(workspace, driver('optimizer')).ainvoke(
            {'messages': [('user', 'Inspect the current synthetic feedback association; do not publish.')]},
            config={'recursion_limit': 16})
        observed['final'] = result['messages'][-1].content
        observed['final_job'] = deepcopy(workspace.store.get('learning_job'))
        assert len(observed['next_inputs']) == 3
        assert len(driver.calls) == 4
        unchanged_candidates = library.list_versions(scope)
        assert unchanged_candidates == original_candidates
    finally:
        record(request, 'P18-native-candidate-link', ['P18.C2'], observed)
