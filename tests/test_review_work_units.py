"""Native behavior contracts, not proof of autonomous planning quality."""
import json
import pytest
from langchain_core.messages import AIMessage, HumanMessage

from report_agent.deep_runtime import build_agent
from report_agent.errors import ActionRejected
from report_agent.handoff_release import release
from report_agent.content_tasks import delegated_task
from report_agent.workspace import Workspace
from test_deep_runtime import Driver, invoke, observation, call
from test_deliverable_declaration_v4 import case
from test_review_binding_v4 import prepared, review_call


def unit_todo(ref):
    return {'content': 'Compare the assigned saved item and recompute the fixture amount.',
            'status': 'pending', 'review_unit': {'assigned_scope_indexes': [0],
                'material_refs': [ref],
                'material_needs': 'Read the saved item and the supplied calculation inputs.',
                'method': 'Independently sum the two supplied products and compare the saved amount.',
                'decision_conditions': 'Record a match, discrepancy, or unresolved missing input.',
                'remaining_work': 'Perform the comparison and retain its evidence.'}}


def configured(case):
    cs, output, criteria, _ = prepared(case)
    cs.store.set('manifest', {**cs.store.manifest, 'context_policy': 'stateful-tools-v2',
        'context_projection': 'review-materials-v1', 'review_plan_contract': 'work-units-v1'})
    request = review_call(criteria, scope={'kind': 'mapped', 'items': [{
        'criterion_ref': criteria[0], 'target_ref': output['refs']['a'], 'assessment_kind': 'content'}]})
    return cs, output, Workspace(cs.store), request


@pytest.mark.parametrize('enabled', [False, True])
@pytest.mark.parametrize('tool_name', ['observe_evidence', 'calculate'])
async def test_native_first_calculation_needs_plan_only_under_explicit_contract(case, enabled, tool_name):
    cs, output, criteria, _ = prepared(case)
    manifest = {**cs.store.manifest, 'context_policy': 'stateful-tools-v2',
                'context_projection': 'review-materials-v1'}
    if enabled:
        manifest['review_plan_contract'] = 'work-units-v1'
    cs.store.set('manifest', manifest)
    assert ('review_plan_contract' in manifest) is enabled
    ws = Workspace(cs.store)
    request = review_call(criteria, scope={'kind': 'mapped', 'items': [{
        'criterion_ref': criteria[0], 'target_ref': output['refs']['a'],
        'assessment_kind': 'content'}]})
    feedback = []

    def after_calculation(messages):
        feedback.append(observation(messages, tool_name))
        return AIMessage('Retained this synthetic protocol result; no semantic acceptance.')

    driver = Driver(coordinator=[AIMessage('', tool_calls=[{**request, 'type': 'tool_call'}]),
                                 AIMessage('End isolated protocol fixture.')],
                    reviewer=[invoke(tool_name, **({'kind': 'calculation'} if tool_name == 'observe_evidence' else {}),
                                     terms=[['9', '120'], ['6', '180']]), after_calculation])
    graph = build_agent(ws, driver, None)
    await graph.ainvoke({'messages': [HumanMessage('Only this synthetic scoped verification.')]})
    assert len(feedback) == 1
    with cs.store.connect() as db:
        observations = db.execute('SELECT count(*) FROM content_observations').fetchone()[0]
    if enabled:
        assert feedback[0].get('code') == 'REVIEW_PLAN_REQUIRED', feedback[0]
        assert feedback[0].get('ok') is False
        assert observations == 0, 'Refused verification must not create evidence'
    else:
        assert feedback[0]['ok'], feedback[0]
        assert observations == 1
    assert not cs.list_objects('ReviewRecord')


def test_plan_contract_absence_is_compatible_and_opt_in_is_release_bound(case):
    cs, *_ = case
    before = release(cs.store.manifest)
    assert 'review_plan_contract' not in before
    opted_in = {**cs.store.manifest, 'context_policy': 'stateful-tools-v2',
                'context_projection': 'review-materials-v1', 'review_plan_contract': 'work-units-v1'}
    bound = release(opted_in)
    assert bound['review_plan_contract'] == 'work-units-v1'
    assert bound['digest'] != before['digest']
    assert release(cs.store.manifest) == before


def test_unknown_plan_contract_cannot_silently_be_ignored(case):
    cs, *_ = case
    with pytest.raises(ActionRejected, match='UNKNOWN_REVIEW_PLAN_CONTRACT'):
        release({**cs.store.manifest, 'review_plan_contract': 'unknown-contract'})


async def test_native_todo_preserves_unit_metadata_before_valid_calculation(case):
    cs, output, ws, request = configured(case)
    todo = unit_todo(output['refs']['a-body'])
    observed, visible = [], []

    def calculate(messages):
        visible.append(messages[0].text)
        return invoke('observe_evidence', kind='calculation', terms=[['9', '120'], ['6', '180']])

    def finish(messages):
        observed.append(observation(messages, 'observe_evidence'))
        return AIMessage('End this synthetic state-retention test, not semantic acceptance.')

    driver = Driver(coordinator=[AIMessage('', tool_calls=[{**request, 'type': 'tool_call'}]), AIMessage('Done.')],
                    reviewer=[invoke('write_todos', todos=[todo]), calculate, finish])
    await build_agent(ws, driver, None).ainvoke({'messages': [HumanMessage('Synthetic unit retention.')]})
    assert len(observed) == 1 and observed[0]['ok'], observed
    assert len(visible) == 1
    assert todo['review_unit']['method'] in visible[0]
    assert '"_binding"' in visible[0], 'Accepted units retain their server-generated task binding'
    assert not cs.list_objects('ReviewRecord')


async def test_public_structured_plan_and_calculation_can_share_one_decision(case):
    cs, output, ws, request = configured(case)
    todo = unit_todo(output['refs']['a-body'])
    seen = []

    def finish(messages):
        seen.append(observation(messages, 'observe_evidence'))
        return AIMessage('End synthetic same-decision declaration test.')

    declaration = AIMessage(content=json.dumps({'review_plan': {'todos': [todo]}}),
        tool_calls=[call('observe_evidence', {'kind': 'calculation', 'terms': [['9', '120']]}, 'same-decision')])
    driver = Driver(coordinator=[AIMessage('', tool_calls=[{**request, 'type': 'tool_call'}]), AIMessage('Done.')],
                    reviewer=[declaration, finish])
    await build_agent(ws, driver, None).ainvoke({'messages': [HumanMessage('Synthetic same-turn plan.')]})
    assert len(seen) == 1 and seen[0]['ok'], seen
    assert not cs.list_objects('ReviewRecord')


def test_a_different_task_cannot_borrow_same_index_plan_but_can_redeclare(case):
    from report_agent.review_work_units import validate_todos
    cs, output, ws, first = configured(case)
    todo = unit_todo(output['refs']['a-body'])
    with delegated_task(ws, 'coordinator', first):
        stamped = validate_todos(ws, [todo], declaration=True)
        assert validate_todos(ws, stamped, declaration=False) == stamped
    second = {**first, 'id': 'another-independent-task'}
    with delegated_task(ws, 'coordinator', second):
        with pytest.raises(ActionRejected, match='REVIEW_PLAN_BINDING_MISMATCH'):
            validate_todos(ws, stamped, declaration=False)
        current = validate_todos(ws, [todo], declaration=True)
        assert current[0]['review_unit']['_binding'] != stamped[0]['review_unit']['_binding']
    assert not cs.list_objects('ReviewRecord')


@pytest.mark.parametrize('text, allowed', [
    ('{"review_\\u0070lan":{"todos":[]}}', False),
    ('{"note":"review_plan"}', True),
])
async def test_public_json_keys_not_raw_substrings_decide_plan_intent(case, text, allowed):
    cs, output, ws, request = configured(case)
    seen = []

    def verify(messages):
        return AIMessage(content=text, tool_calls=[call('calculate', {'terms': [['9', '120']]}, 'after-json')])

    def finish(messages):
        seen.append(observation(messages, 'calculate'))
        return AIMessage('End JSON intent boundary fixture.')

    driver = Driver(coordinator=[AIMessage('', tool_calls=[{**request, 'type': 'tool_call'}]), AIMessage('Done.')],
        reviewer=[invoke('write_todos', todos=[unit_todo(output['refs']['a-body'])]), verify, finish])
    await build_agent(ws, driver, None).ainvoke({'messages': [HumanMessage('Only this synthetic parser case.')]})
    assert len(seen) == 1
    assert seen[0]['ok'] is allowed, seen
    if not allowed:
        assert seen[0]['code'] == 'REVIEW_PLAN_REQUIRED'
    with cs.store.connect() as db:
        assert db.execute('SELECT count(*) FROM content_observations').fetchone()[0] == int(allowed)


@pytest.mark.parametrize('with_projection', [False, True])
def test_absent_contract_keeps_accepted_prechange_release_golden(with_projection):
    # Derived from preserved accepted pre-contract source, not the current function.
    manifest = {'goal': 'Synthetic legacy release compatibility fixture.',
        'content_contract': 'hierarchical-review-v1', 'review_entrypoint': 'delegated-reviewer-v1',
        'review_execution_mode': 'native-reviewer-v2', 'review_interface_profile': 'review-interfaces-v4',
        'delegation_prompt_profile': 'separate-description-v1',
        'operation_identity_profile': 'native-tool-runtime-v1'}
    expected = {**manifest, 'content_input_profile': 'content-inputs-v1',
        'report_expression_profile': 'report-expression-v1',
        'digest': '74f9da6658493736f16b81faa4bf89f51bc7c3aeb7dfd93b4f84066fa3eb0ea6'}
    if with_projection:
        manifest.update(context_policy='stateful-tools-v2', context_projection='review-materials-v1')
    assert release(manifest) == expected


@pytest.mark.parametrize('representation', ['todo_model', 'unit_model'])
def test_unstamped_model_objects_are_not_rebound_as_trusted_state(case, representation):
    from report_agent.review_work_units import ReviewTodo, ReviewUnit, validate_todos
    _, output, ws, request = configured(case)
    todo = unit_todo(output['refs']['a-body'])
    if representation == 'todo_model':
        todo = ReviewTodo.model_validate(todo)
    else:
        todo['review_unit'] = ReviewUnit.model_validate(todo['review_unit'])
    with delegated_task(ws, 'coordinator', request):
        with pytest.raises(ActionRejected, match='REVIEW_PLAN_BINDING_MISMATCH'):
            validate_todos(ws, [todo], declaration=False)


def test_outside_material_feedback_points_to_ref_without_echoing_it(case):
    from report_agent.review_work_units import validate_todos
    _, output, ws, request = configured(case)
    todo = unit_todo(output['refs']['a-body'])
    forbidden = {'type': 'SourceArtifact', 'id': 'not-in-this-task', 'version': 1}
    todo['review_unit']['material_refs'].append(forbidden)
    with delegated_task(ws, 'coordinator', request):
        with pytest.raises(ActionRejected, match='REVIEW_PLAN_MATERIAL_OUTSIDE_ASSIGNMENT') as error:
            validate_todos(ws, [todo], declaration=True)
    assert error.value.diagnostic == {'todo_index': 0, 'material_ref_index': 1}
    assert forbidden['id'] not in json.dumps(error.value.diagnostic)


@pytest.mark.parametrize("replacement", [None, "unknown-contract"])
def test_reopening_cannot_drop_or_change_plan_contract(case, replacement, monkeypatch):
    cs, output, ws, request = configured(case)
    build_agent(ws, Driver(), None)
    changed = dict(cs.store.manifest)
    if replacement is None:
        changed.pop('review_plan_contract')
    else:
        changed['review_plan_contract'] = replacement
    cs.store.set('manifest', changed)
    def forbidden(*args, **kwargs):
        pytest.fail('Invalid reopen must fail before runtime-version or model creation')
    monkeypatch.setattr('report_agent.prompt_sources.record_runtime_version', forbidden)
    with pytest.raises(ActionRejected):
        build_agent(ws, forbidden, None)


def test_plan_contract_binding_reopens_same_value_without_migrating_legacy(case):
    cs, output, ws, request = configured(case)
    build_agent(ws, Driver(), None)
    assert cs.store.get('review_plan_contract_binding') == 'work-units-v1'
    build_agent(ws, Driver(), None)
    assert cs.store.get('review_plan_contract_binding') == 'work-units-v1'


@pytest.mark.parametrize('event', ['deep_model_request', 'model_transport_call', 'model_invocation_outcome'])
def test_plan_contract_cannot_be_added_after_execution(case, event):
    cs, output, ws, request = configured(case)
    from report_agent.task_context import bind_projection
    bind_projection(ws)
    cs.store.event(event, {'synthetic': True})
    with pytest.raises(ActionRejected, match='REVIEW_PLAN_REQUIRES_FRESH_PROJECT'):
        build_agent(ws, Driver(), None)
    assert cs.store.get('review_plan_contract_binding') is None
