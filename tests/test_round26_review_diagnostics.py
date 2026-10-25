"""R26 exact corrective diagnostics preserve original rejection and permissions."""
from copy import deepcopy

import pytest

from report_agent.content_tasks import delegated_task
from report_agent.errors import ActionRejected
from report_agent.review_coverage import validate_accounting
from test_deep_runtime import call
from test_hierarchical_content import ws, seed
from test_reviewer_native_profile import native, commission, candidate


def test_missing_body_feedback_keeps_code_names_scope_and_exact_missing_root(ws):
    native(ws)
    cs, _, refs, snapshot, _ = seed(ws)
    request = commission(snapshot, refs)
    requirement = request['review_requirements'][0]
    requirement['required_materials'] = []
    requirement['content_check_scopes'] = [{'requirement_index': 0, 'kind': 'subtree_bodies', 'node_ref': refs['root']}]
    with delegated_task(ws, 'coordinator', call('task', request, 'diagnostic-task')) as (_, actor):
        receipt = cs.read_context(actor, refs['claim'])['receipt_id']
        value = candidate(snapshot, refs, [receipt])
        original = deepcopy(value)
        with pytest.raises(ActionRejected, match='^COMPLETED_CHECK_MISSING_BODY_EXTENT$') as first:
            cs.submit_review(actor, 'diagnostic-save', value, {})
        diagnostic = first.value.diagnostic
        assert diagnostic['scope_id'] == 'delivery'
        assert diagnostic['requirement_index'] == 0
        assert diagnostic['missing_body_refs'] == [refs['root']]
        assert diagnostic['parameter_path'] == ['review', 'items', 0, 'check_results', 0, 'observation_indexes']
        saved = cs.receipt(actor, 'diagnostic-save')
        assert saved['state'] == 'known_failure'
        assert saved['response']['diagnostic'] == diagnostic
        with pytest.raises(ActionRejected) as repeated:
            cs.submit_review(actor, 'diagnostic-save', value, {})
        assert repeated.value.diagnostic == diagnostic
        assert cs.receipt(actor, 'diagnostic-save') == saved
        assert value == original and not cs.list_objects('ReviewRecord')
        root_receipt = cs.read_context(actor, refs['root'])['receipt_id']
        accepted = cs.submit_review(actor, 'diagnostic-corrected', candidate(snapshot, refs, [receipt, root_receipt]), {})
        assert cs.read(accepted['result']['review_ref'])['payload']['items'][0]['execution_state'] == 'completed'


@pytest.mark.parametrize('kind', ['Evidence', 'Relation', 'SourceArtifact'])
def test_coverage_wrong_slot_is_not_misreported_as_missing_snapshot_object(kind):
    ref = {'type': kind, 'id': 'actual-member', 'version': 1}
    snapshot = {'payload': {'refs': [ref]}}
    review = {'items': [{'verdict': 'satisfied', 'observations': [{'receipt_id': 'fixture'}]}],
              'coverage_accounting': [{'target_refs': [ref], 'item_indexes': [0], 'state': 'assessed'}]}
    before = deepcopy(review)
    with pytest.raises(ActionRejected, match='^COVERAGE_OBJECT_OUTSIDE_SNAPSHOT$') as error:
        validate_accounting(snapshot, review)
    assert error.value.diagnostic['reason'] == 'unsupported_coverage_object_type'
    assert error.value.diagnostic['allowed_object_types'] == ['ContentNode', 'Requirement']
    assert error.value.diagnostic['parameter_path'] == ['review', 'coverage_accounting', 0, 'target_refs', 0]
    assert review == before


@pytest.mark.parametrize('args', [(), ('FIRST', 'SECOND')])
def test_rejection_retains_valueerror_constructor_compatibility(args):
    error = ActionRejected(*args)
    assert error.args == args
    assert str(error) == str(ValueError(*args))
    assert error.diagnostic is None


def test_finding_missing_local_index_reports_exact_field_without_new_rules(ws):
    native(ws)
    cs, _, refs, snapshot, _ = seed(ws)
    with delegated_task(ws, 'coordinator', call('task', commission(snapshot, refs), 'finding-task')) as (_, actor):
        receipt = cs.read_context(actor, refs['claim'])['receipt_id']
        value = candidate(snapshot, refs, [receipt])
        value['items'][0]['findings'] = [{'finding_type': 'confirmed_defect', 'locator_state': 'located',
            'description': 'Fixture discrepancy', 'impact': 'Assigned check', 'needed_outcome': 'Resolve actual evidence',
            'requirement_index': None, 'observation_indexes': [0], 'basis_kind': 'supplied_content'}]
        with pytest.raises(ActionRejected, match='^REVIEW_FINDING_OUTSIDE_ASSIGNED_CHECK$') as error:
            cs.submit_review(actor, 'finding-save', value, {})
        assert error.value.diagnostic['scope_id'] == 'delivery'
        assert error.value.diagnostic['allowed_requirement_indexes'] == [0]
        assert error.value.diagnostic['parameter_path'] == ['review', 'items', 0, 'findings', 0, 'requirement_index']


@pytest.mark.parametrize('identity', ['absent', 'foreign'])
def test_unavailable_receipt_feedback_does_not_disclose_foreign_identity_or_payload(ws, identity):
    import json
    from report_agent.content_store import Actor
    native(ws)
    cs, _, refs, snapshot, _ = seed(ws)
    foreign = cs.observe(Actor('foreign-private-actor', 'reviewer', 'foreign-private-task'),
                         {'secret': 'foreign-private-payload'})['receipt_id']
    request = commission(snapshot, refs)
    request['review_requirements'][0].update(content_check_scopes=[], required_materials=[])
    with delegated_task(ws, 'coordinator', call('task', request, 'receipt-task')) as (_, actor):
        value = candidate(snapshot, refs, [foreign if identity == 'foreign' else 'nonexistent-receipt'])
        with pytest.raises(ActionRejected, match='^OBSERVATION_RECEIPT_NOT_FROM_THIS_REVIEWER$') as error:
            cs.submit_review(actor, 'receipt-save', value, {})
        diagnostic = error.value.diagnostic
        assert diagnostic['reason'] == 'observation_receipt_unavailable_to_current_reviewer'
        assert diagnostic['parameter_path'] == ['review', 'items', 0, 'observations', 0, 'receipt_id']
        assert 'foreign-private' not in json.dumps(diagnostic)
        assert not cs.list_objects('ReviewRecord')


def test_delivery_check_reports_assessment_kind_slot_not_permission_expansion():
    from report_agent.artifact_review import validate_artifact_items
    value = {'items': [], 'delivery_checks': [{'kind': 'export', 'artifact_refs': []}]}
    with pytest.raises(ActionRejected, match='^DELIVERY_CHECK_OUTSIDE_ASSIGNED_ARTIFACTS$') as error:
        validate_artifact_items(None, None, [], value)
    assert error.value.diagnostic['parameter_path'] == ['review', 'delivery_checks', 0, 'artifact_refs']
    assert error.value.diagnostic['allowed_artifact_refs'] == []
    assert error.value.diagnostic['kind'] == 'export'


async def test_native_graph_delivers_exact_body_diagnostic_to_reviewer_next_model_input(ws):
    import json
    from langchain_core.messages import AIMessage
    from report_agent import deep_runtime
    from test_deep_runtime import Driver, invoke, observation
    native(ws)
    cs, _, refs, snapshot, _ = seed(ws)
    request = commission(snapshot, refs)
    request['review_requirements'][0]['required_materials'] = []
    request['review_requirements'][0]['content_check_scopes'] = [
        {'requirement_index': 0, 'kind': 'subtree_bodies', 'node_ref': refs['root']}]
    received = []
    def submit(messages):
        receipt = observation(messages, 'read_context')['receipt_id']
        return invoke('submit_review', operation_id='graph-bad-save', review=candidate(snapshot, refs, [receipt]))
    def feedback(messages):
        result = json.loads(messages[-1].content)
        assert result['ok'] is False and result['code'] == 'COMPLETED_CHECK_MISSING_BODY_EXTENT'
        assert result['diagnostic']['missing_body_refs'] == [refs['root']]
        received.append(result['diagnostic'])
        return AIMessage(content='Fixture received a precise rejection; no semantic acceptance claimed.')
    driver = Driver(coordinator=[invoke('task', **request), AIMessage(content='Fixture ended.')],
                    reviewer=[invoke('read_context', target_ref=refs['claim']), submit, feedback])
    result = await deep_runtime.run_report(ws, driver)
    assert result['last_error'] is None, result
    assert len(received) == 1 and not cs.list_objects('ReviewRecord')


async def test_actual_sdk_receives_body_diagnostic_without_fake_model_boundary(ws):
    import json
    import httpx
    from collections import Counter
    from report_agent import deep_runtime
    from report_agent.deep_models import GLMChatOpenAI, model_async_client
    from test_prompt_native_sdk_inputs import completion
    native(ws)
    cs, _, refs, snapshot, _ = seed(ws)
    request = commission(snapshot, refs)
    request['review_requirements'][0]['required_materials'] = []
    request['review_requirements'][0]['content_check_scopes'] = [
        {'requirement_index':0,'kind':'subtree_bodies','node_ref':refs['root']}]
    counts, models, feedback = Counter(), {}, []
    def factory(role):
        if role in models: return models[role]
        client = model_async_client(ws.store, role)
        def transport(http_request):
            body = json.loads(http_request.content)
            step = counts[role]
            counts[role] += 1
            if role == 'coordinator':
                return completion(http_request, 'Fixture done.', ('task',request) if step == 0 else None)
            if step == 0:
                return completion(http_request, '', ('read_context',{'target_ref':refs['claim']}))
            last = json.loads(next(m['content'] for m in reversed(body['messages']) if m['role']=='tool'))
            if step == 1:
                return completion(http_request, '', ('submit_review',{'operation_id':'wire-rejected',
                    'review':candidate(snapshot,refs,[last['receipt_id']])}))
            assert last['code'] == 'COMPLETED_CHECK_MISSING_BODY_EXTENT'
            assert last['diagnostic']['missing_body_refs'] == [refs['root']]
            assert last['diagnostic']['parameter_path'] == ['review','items',0,'check_results',0,'observation_indexes']
            feedback.append(last)
            return completion(http_request, 'Exact corrective feedback received; unfinished.')
        client._transport = httpx.MockTransport(transport)
        client._mounts.clear()
        models[role] = GLMChatOpenAI(model='glm-5.3',api_key='fixture-only',base_url='https://fixture.invalid/v1',
            use_responses_api=False,http_async_client=client,max_retries=0,disable_streaming=True)
        return models[role]
    try:
        result = await deep_runtime.run_report(ws, factory)
        assert result['last_error'] is None, result
        assert len(feedback) == 1 and not cs.list_objects('ReviewRecord')
    finally:
        for model in models.values():
            await model.root_async_client.close()
            model.root_client.close()


@pytest.mark.parametrize('rejection',[{'ok':False},{'accepted':False}])
def test_partial_verdict_cannot_treat_explicitly_rejected_observation_as_success(ws,rejection):
    native(ws)
    cs,_,refs,snapshot,_=seed(ws)
    with delegated_task(ws,'coordinator',call('task',commission(snapshot,refs),'rejected-read-task')) as (_,actor):
        receipt=cs.observe(actor,rejection)['receipt_id']
        value=candidate(snapshot,refs,[receipt],state='running')
        with pytest.raises(ActionRejected,match='^FAILED_READS_DO_NOT_ESTABLISH_OBSERVATIONS$'):
            cs.submit_review(actor,'rejected-read-save',value,{})
        assert not cs.list_objects('ReviewRecord')



def test_partial_verdict_may_record_a_failed_read_when_other_real_observation_supports_it(ws):
    native(ws)
    cs,_,refs,snapshot,_=seed(ws)
    with delegated_task(ws,'coordinator',call('task',commission(snapshot,refs),'mixed-reads-task')) as (_,actor):
        failed=cs.observe(actor,{'ok':False})['receipt_id']
        good=cs.read_context(actor,refs['claim'])['receipt_id']
        value=candidate(snapshot,refs,[failed,good],state='running')
        saved=cs.submit_review(actor,'mixed-reads-save',value,{})
        assert saved['ok'] and len(cs.list_objects('ReviewRecord'))==1
