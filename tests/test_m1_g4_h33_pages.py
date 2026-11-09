"""Bounded planning observations; large saved drafts remain server-side."""
import json
import pytest
from copy import deepcopy
from report_agent import commission_planning as planning, plan_inputs
from report_agent.errors import ActionRejected
from report_agent.store import encode
from test_m1_g4_planning_steps import (method_commission, anchored, required_case, entries, linked, draft_case, text_source, offline_only)


def read(f, **args):
    tool = next(t for t in planning.planning_tools(f.cs, lambda: f.co) if t.__name__ == 'read_planning_draft')
    return tool(**args)


def large(f):
    # Same failure shape as the real draft: large fixed text before trailing gaps.
    section = deepcopy(f.plan['sections'][0])
    section['text'] = 'Retained source text. ' * 9000
    with f.cs.store.connect() as db:
        plan_inputs.save_draft(db, {'revision': 7, 'items': {'section': {section['section_id']: section}}}, actor=f.co)
    return section


def test_large_draft_default_exposes_all_gaps_before_any_details(draft_case):
    f = draft_case
    large(f)
    original = planning.read_draft(f.cs, f.co)
    assert len(encode(original)) > 80000
    result = read(f)
    assert next(iter(result)) == 'gaps'
    assert result['gap_count'] == len(original['gaps']) > 0
    assert [(g['anchor_id'], g['path'], g['code']) for g in result['gaps']] == [
        (g.get('anchor_id'), g['path'], g['code']) for g in original['gaps']]
    assert result['next_gap_page'] is None
    assert len(json.dumps(result, ensure_ascii=False)) < 16000
    assert 'plan' not in result and result['page_data'] is None


def test_paging_preserves_large_fixed_text_and_citations_exactly(draft_case):
    f = draft_case
    section = large(f)
    summary = read(f)
    parts, offset = [], 0
    while offset is not None:
        result = read(f, collection='sections', item_id=section['section_id'],
                      offset=offset, view_ref=summary['view_ref'])
        page = result['page_data']
        parts.append(page['text'])
        assert len(json.dumps(result, ensure_ascii=False)) < 16000
        offset = page['next_offset']
    assert json.loads(''.join(parts)) == section


def test_anchor_ids_and_exact_quotes_available_by_page_and_id(draft_case):
    f = draft_case
    summary = read(f)
    found = []
    page = 1
    while page is not None:
        result = read(f, collection='requirements', page=page, page_size=1, view_ref=summary['view_ref'])
        data = result['page_data']
        assert data['next_offset'] is None
        row = json.loads(data['text'])[0]['value']
        found.append(row['anchor']['id'])
        by_id = read(f, collection='requirements', item_id=row['anchor']['id'], view_ref=summary['view_ref'])
        assert json.loads(by_id['page_data']['text']) == row
        assert row['anchor']['source']['quote']
        page = data['next_page']
    assert found == [a['id'] for a in planning.read_draft(f.cs, f.co)['requirements']['payload']['anchors']]


def test_stale_pages_and_unknown_selection_are_refused(draft_case):
    f = draft_case
    before = read(f)['view_ref']
    large(f)
    with pytest.raises(ActionRejected, match='PLANNING_VIEW_CHANGED'):
        read(f, collection='sections', view_ref=before)
    with pytest.raises(ActionRejected):
        read(f, collection='requirements', item_id='nonexistent')
    with pytest.raises(ActionRejected):
        read(f, collection='requirements', page=9999)


def test_many_gaps_have_explicit_bounded_continuation(draft_case, monkeypatch):
    gaps = [{'anchor_id': str(i), 'path': 'sections.' + str(i), 'code': 'MISSING', 'message': 'Required'} for i in range(1000)]
    monkeypatch.setattr(planning, '_gaps', lambda *a: gaps)
    page, seen = 1, []
    view = read(draft_case)['view_ref']
    while page is not None:
        result = read(draft_case, gap_page=page, view_ref=view)
        assert result['gap_count'] == 1000
        assert len(json.dumps(result, ensure_ascii=False)) < 16000
        seen.extend(g['anchor_id'] for g in result['gaps'])
        page = result['next_gap_page']
    assert seen == [str(i) for i in range(1000)]


async def test_large_draft_gaps_reach_actual_native_model_input(draft_case):
    from langchain_core.messages import AIMessage, ToolMessage
    from test_deep_runtime import Driver, call, run
    from test_m1_g4_planning_steps import current_native_profiles
    f = draft_case
    current_native_profiles(f)
    large(f)
    expected = [(g.get('anchor_id'), g['path'], g['code']) for g in planning.read_draft(f.cs, f.co)['gaps']]
    def inspect(messages):
        message = next(m for m in reversed(messages) if isinstance(m, ToolMessage) and m.name == 'read_planning_draft')
        value = json.loads(message.content)
        assert next(iter(value)) == 'gaps'
        assert [(g['anchor_id'], g['path'], g['code']) for g in value['gaps']] == expected
        assert value['gap_count'] == len(expected)
        assert value['page_data'] is None and len(message.content) < 16000
        return AIMessage(content='', tool_calls=[call('ask_human', {
            'category': 'requirement', 'description': 'Synthetic planning decision.', 'source_ids': [], 'pause': True}, 'owner')])
    driver = Driver(coordinator=[AIMessage(content='', tool_calls=[call('read_planning_draft', {}, 'large-read')]), inspect])
    result = await run(f.ws, driver)
    assert result['status'] == 'needs_human' and result['last_error'] is None, result
    assert len(driver.calls) == 2



def test_requirement_update_invalidates_view_even_without_draft_edit(draft_case):
    f = draft_case
    old = read(f)
    anchor = f.anchors[0]
    planning.set_requirement_status(f.cs, f.co, 'h33-change-interpretation', anchor['id'],
        'required', 'Updated interpretation must invalidate prior pages.')
    fresh = read(f)
    assert fresh['revision'] == old['revision'] and fresh['view_ref'] != old['view_ref']
    with pytest.raises(ActionRejected, match='PLANNING_VIEW_CHANGED') as error:
        read(f, collection='requirements', view_ref=old['view_ref'])
    assert error.value.diagnostic['fields'][0]['field'] == 'view_ref'


def test_compact_gap_details_and_invalid_selection_keep_precise_fields(draft_case):
    f = draft_case
    summary = read(f)
    gap = summary['gaps'][0]
    detail = read(f, collection='gaps', item_id=gap['detail_id'], view_ref=summary['view_ref'])
    assert json.loads(detail['page_data']['text'])['code'] == gap['code']
    with pytest.raises(ActionRejected) as error:
        read(f, collection='sections', item_id='unknown')
    assert error.value.diagnostic['fields'][0]['field'] == 'item_id'
