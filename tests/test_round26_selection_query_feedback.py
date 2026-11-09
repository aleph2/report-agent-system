"""Status explains incomplete query scope without inferring or approving a pair."""
from report_agent import report_state
import json
from collections import Counter

import httpx
from langchain_core.messages import HumanMessage

from report_agent.content_export import export_snapshot
from report_agent.content_workbook import export_workbook
from report_agent.content_models import Ref
from report_agent.review_status import read_status
from test_hierarchical_content import ws
from test_selected_companion_reviews import pair, save_review


def test_missing_explicit_pair_is_not_reported_as_proven_file_change(pair):
    ws, cs, _, snap, _, _, word, excel, select = pair
    ref, before = save_review(pair)
    report_state.set_content_delivery(ws.store, None)
    status = read_status(cs, snap, word)
    item = status['objects'][0]
    assert not item['has_current_review']
    assert item['review_history'][0]['recheck_reasons'] == ['artifact_version_mismatch']
    detail = item['review_history'][0]['artifact_mismatch_details']
    assert detail['reason'] == 'query_missing_reviewed_artifacts'
    assert detail['reviewed_export_refs'] == [word, excel]
    assert detail['query_export_refs'] == [word]
    assert detail['missing_query_export_refs'] == [excel]
    context = status['artifact_query_context']
    assert context['selection_matches_snapshot'] is False
    assert context['selected_delivery_export_refs'] == []
    assert context['draft_selection_is_not_approval'] is True
    assert 'select_content_delivery' in context['note']
    assert report_state.selected_delivery(ws.store) is None
    assert cs.read(ref) == before and len(cs.list_objects('ReviewRecord')) == 1
    select('intended-draft-pair', Ref.model_validate(snap), Ref.model_validate(word),
           workbook_export_ref=Ref.model_validate(excel))
    current = read_status(cs, snap, word)['objects'][0]
    assert current['has_current_review'] and current['scopes'][0]['verdict'] == 'not_satisfied'
    assert cs.read(ref) == before and len(cs.list_objects('ReviewRecord')) == 1


def test_changed_selected_exports_are_not_mislabeled_as_missing_context(pair):
    ws, cs, actor, snap, sheets, _, word, excel, select = pair
    save_review(pair)
    replacement = export_snapshot(cs, actor, 'new-word', snap)['result']['export_ref']
    workbook = export_workbook(cs, actor, 'new-excel', snap, sheets, replacement)['result']['export_ref']
    select('different-draft', Ref.model_validate(snap), Ref.model_validate(replacement),
           workbook_export_ref=Ref.model_validate(workbook))
    status = read_status(cs, snap, export_ref=replacement, limit=100)
    entry = next(row for row in status['objects'] if row['target_ref'] == snap)
    detail = entry['review_history'][0]['artifact_mismatch_details']
    assert detail['reason'] == 'selected_or_queried_artifacts_differ_from_reviewed_set'
    assert detail['query_export_refs'] == [replacement, workbook]
    assert detail['missing_query_export_refs'] == [word, excel]
    assert not entry['has_current_review']


def test_unselected_sibling_still_cannot_borrow_selected_companion(pair):
    ws, cs, actor, snap, _, _, word, excel, _ = pair
    sibling = export_snapshot(cs, actor, 'sibling-context', snap)['result']['export_ref']
    save_review(pair, [sibling, excel])
    status = read_status(cs, snap, sibling)
    row = status['objects'][0]
    assert not row['has_current_review']
    assert row['review_history'][0]['recheck_reasons'] == ['artifact_version_mismatch']
    detail = row['review_history'][0]['artifact_mismatch_details']
    assert detail['reason'] == 'query_not_in_selected_delivery'
    assert detail['query_export_refs'] == [sibling]
    assert status['artifact_query_context']['selected_delivery_export_refs'] == [word, excel]


async def test_native_sdk_first_bounded_status_preview_explains_draft_selection(pair):
    from report_agent.deep_models import GLMChatOpenAI, model_async_client
    from report_agent.deep_runtime import build_agent
    from test_prompt_native_sdk_inputs import completion
    from test_reviewer_native_profile import native
    ws, cs, _, snap, _, _, word, _, _ = pair
    for i in range(4):
        save_review(pair, op='long-history-'+str(i))
    report_state.set_content_delivery(ws.store, None)
    native(ws)
    ws.store.set('manifest', {**ws.store.manifest, 'context_policy': 'stateful-tools-v2',
                             'context_projection': 'focused-v1'})
    models, counts, feedback = {}, Counter(), []

    def factory(role):
        if role in models:
            return models[role]
        client = model_async_client(ws.store, role)

        def transport(request):
            body = json.loads(request.content)
            step = counts[role]
            counts[role] += 1
            assert role == 'coordinator'
            if step == 0:
                return completion(request, '', ('read_review_status',
                    {'snapshot_ref': snap, 'target_ref': word, 'limit': 100}))
            value = next(m['content'] for m in reversed(body['messages']) if m['role'] == 'tool')
            while isinstance(value, str):
                value = json.loads(value)
            feedback.append(value)
            return completion(request, 'Read-only scope feedback; no delivery approval.')

        client._transport = httpx.MockTransport(transport)
        client._mounts.clear()
        models[role] = GLMChatOpenAI(model='glm-5.3', api_key='fixture-only',
            base_url='https://fixture.invalid/v1', use_responses_api=False,
            http_async_client=client, max_retries=0, disable_streaming=True)
        return models[role]

    try:
        await build_agent(ws, factory, None).ainvoke({'messages': [HumanMessage('Observe query context only.')]})
        assert len(feedback) == 1
        assert feedback[0]['complete_tool_result'] is False
        assert 'artifact_query_context' in feedback[0]['text']
        assert 'draft_selection_is_not_approval' in feedback[0]['text']
        assert 'select_content_delivery' in feedback[0]['text']
        assert report_state.selected_delivery(ws.store) is None
    finally:
        for model in models.values():
            await model.root_async_client.close()
            model.root_client.close()
