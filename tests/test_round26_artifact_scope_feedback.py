"""Exact artifact declarations keep strict guards and useful original-item feedback."""
from copy import deepcopy
import json
from collections import Counter

import httpx
import pytest
from langchain_core.messages import HumanMessage

from report_agent.artifact_review import validate_artifact_items
from report_agent.content_store import Actor
from report_agent.content_tasks import delegated_task
from report_agent.errors import ActionRejected
from test_artifact_review import setup, payload
from test_hierarchical_content import ws
from test_reviewer_native_profile import native, commission, candidate

WORD = {'type': 'ExportArtifact', 'id': 'word', 'version': 1}
EXCEL = {'type': 'ExportArtifact', 'id': 'excel', 'version': 1}


def minimal(provided):
    requirement = {'target_ref': {'type': 'ContentNode', 'id': 'claim', 'version': 1},
        'criterion_ref': {'type': 'Criterion', 'id': 'rule', 'version': 1},
        'scope_id': 'scope', 'assessment_kind': 'export', 'artifact_refs': [WORD, EXCEL]}
    item = {**requirement, 'artifact_refs': provided, 'execution_state': 'running',
            'observations': [], 'check_results': []}
    return requirement, {'items': [item], 'delivery_checks': []}


@pytest.mark.parametrize('provided', [[WORD], [EXCEL], [WORD, {**EXCEL, 'version': 2}],
                                     [WORD, EXCEL, {'type': 'ExportArtifact', 'id': 'extra', 'version': 1}]])
def test_artifact_ref_set_diagnostic_names_missing_and_extra_without_new_permission(provided):
    requirement, data = minimal(provided)
    before = deepcopy(data)
    with pytest.raises(ActionRejected, match='^ARTIFACT_REVIEW_OUTSIDE_ASSIGNED_SCOPE$') as rejected:
        validate_artifact_items(None, None, [requirement], data)
    detail = rejected.value.diagnostic
    assert detail['reason'] == 'artifact_ref_set_mismatch'
    assert detail['parameter_path'] == ['review', 'items', 0, 'artifact_refs']
    assert detail['expected_artifact_refs'] == [WORD, EXCEL]
    assert detail['provided_artifact_refs'] == provided
    assert detail['missing_artifact_refs'] == [r for r in [WORD, EXCEL] if r not in provided]
    assert detail['extra_artifact_refs'] == [r for r in provided if r not in [WORD, EXCEL]]
    assert data == before


def test_unassigned_identity_diagnostic_does_not_disclose_other_scopes():
    requirement, data = minimal([WORD, EXCEL])
    data['items'][0]['scope_id'] = 'unassigned'
    with pytest.raises(ActionRejected, match='^ARTIFACT_REVIEW_OUTSIDE_ASSIGNED_SCOPE$') as rejected:
        validate_artifact_items(None, None, [requirement], data)
    assert rejected.value.diagnostic['reason'] == 'artifact_scope_identity_not_assigned'
    assert rejected.value.diagnostic['parameter_path'] == ['review', 'items', 0]
    assert 'expected_artifact_refs' not in rejected.value.diagnostic


def mixed(ws):
    cs, refs, snap, word, _, _, request = setup(ws, kind='export', reference=False)
    native(ws)
    with cs.store.connect() as db:
        excel = cs._insert(db, Actor('fixture-import', 'coordinator', 'root'), 'ExportArtifact',
                          {'snapshot_ref': snap, 'file_ref': 'fixture.xlsx'})
    export_requirement = request['args']['review_requirements'][0]
    export_requirement['artifact_refs'] = [word, excel]
    content = commission(snap, refs)['review_requirements'][0]
    request['args']['review_requirements'] = [
        {**deepcopy(content), 'scope_id': 'content-'+str(i)} for i in range(6)] + [export_requirement]
    return cs, refs, snap, word, excel, request


def mixed_review(snap, refs, word, body_receipt, export_receipts):
    data = candidate(snap, refs, [body_receipt])
    content = data['items'][0]
    data['items'] = [{**deepcopy(content), 'scope_id': 'content-'+str(i)} for i in range(6)]
    artifact = payload(snap, refs, word, export_receipts, kind='export').model_dump()['items'][0]
    artifact['checked_requirement_indexes'] = [0]
    artifact['check_results'] = [{'requirement_index': 0, 'execution_state': 'completed',
        'result': 'Protocol fixture only.', 'observation_indexes': list(range(len(export_receipts))), 'remaining': ''}]
    data['items'].append(artifact)
    return data


def test_mixed_native_original_index_known_failure_and_legal_full_set(ws):
    cs, refs, snap, word, excel, request = mixed(ws)
    with delegated_task(ws, 'coordinator', request) as (_, actor):
        body = cs.read_context(actor, refs['claim'])['receipt_id']
        exported = [cs.observe(actor, {'export_ref': ref, 'structure': {'fixture': True}})['receipt_id']
                    for ref in (word, excel)]
        data = mixed_review(snap, refs, word, body, exported)
        with pytest.raises(ActionRejected, match='^ARTIFACT_REVIEW_OUTSIDE_ASSIGNED_SCOPE$') as first:
            cs.submit_review(actor, 'mixed-subset', data, {})
        assert first.value.diagnostic['parameter_path'] == ['review', 'items', 6, 'artifact_refs']
        assert first.value.diagnostic['missing_artifact_refs'] == [excel]
        saved = cs.receipt(actor, 'mixed-subset')
        with pytest.raises(ActionRejected) as cached:
            cs.submit_review(actor, 'mixed-subset', data, {})
        assert cached.value.diagnostic == first.value.diagnostic
        assert cs.receipt(actor, 'mixed-subset') == saved
        assert not cs.list_objects('ReviewRecord')
        fixed = deepcopy(data)
        fixed['items'][6]['artifact_refs'] = [word, excel]
        accepted = cs.submit_review(actor, 'mixed-corrected', fixed, {})
        assert cs.read(accepted['result']['review_ref'])['payload']['items'][6]['artifact_refs'] == [word, excel]


async def test_actual_native_sdk_returns_original_item_path_after_content_filter(ws):
    from report_agent.deep_models import GLMChatOpenAI, model_async_client
    from report_agent.deep_runtime import build_agent
    from test_prompt_native_sdk_inputs import completion
    cs, refs, snap, word, excel, request = mixed(ws)
    models, counts, feedback = {}, Counter(), []

    def factory(role):
        if role in models:
            return models[role]
        client = model_async_client(ws.store, role)

        def transport(http_request):
            body = json.loads(http_request.content)
            step = counts[role]
            counts[role] += 1
            if role == 'coordinator':
                return (completion(http_request, '', ('task', request['args'])) if step == 0
                        else completion(http_request, 'No semantic acceptance.'))
            assert role == 'reviewer'
            if step == 0:
                return completion(http_request, '', ('read_context', {'target_ref': refs['claim']}))
            last = next(m['content'] for m in reversed(body['messages']) if m['role'] == 'tool')
            while isinstance(last, str):
                last = json.loads(last)
            if step == 1:
                data = mixed_review(snap, refs, word, last['receipt_id'], [last['receipt_id']])
                return completion(http_request, '', ('submit_review', {'operation_id': 'wire-subset', 'review': data}))
            feedback.append(last)
            return completion(http_request, 'Fixture received diagnostic; no review saved.')

        client._transport = httpx.MockTransport(transport)
        client._mounts.clear()
        models[role] = GLMChatOpenAI(model='glm-5.3', api_key='fixture-only',
            base_url='https://fixture.invalid/v1', use_responses_api=False,
            http_async_client=client, max_retries=0, disable_streaming=True)
        return models[role]

    try:
        agent = build_agent(ws, factory, None)
        await agent.ainvoke({'messages': [HumanMessage('Synthetic mixed-scope feedback only.')]})
        assert len(feedback) == 1
        assert feedback[0]['code'] == 'ARTIFACT_REVIEW_OUTSIDE_ASSIGNED_SCOPE'
        assert feedback[0]['diagnostic']['parameter_path'] == ['review', 'items', 6, 'artifact_refs']
        assert feedback[0]['diagnostic']['missing_artifact_refs'] == [excel]
        assert not cs.list_objects('ReviewRecord')
    finally:
        for model in models.values():
            await model.root_async_client.close()
            model.root_client.close()
