"""One-shot artifact comparisons with synthetic observations; no visual acceptance."""
import json

import pytest

from report_agent.artifact_review import bounded_artifact_review_tool
from report_agent.content_tasks import delegated_task
from report_agent.errors import ActionRejected
from report_agent.task_supervision import reconcile
from test_artifact_review import setup, visual, payload
from test_bounded_review import Model
from test_task_supervision import ws, offline


async def test_independent_tool_saves_exact_owned_artifact_judgment_once(ws):
    cs, refs, snap, export, render, source, requested = setup(ws, pages=1)
    with delegated_task(ws, 'coordinator', requested) as (_, reviewer):
        receipt = visual(cs, reviewer, render, export, source, 1)
        expected = payload(snap, refs, render, [receipt])
        model = Model(expected.model_dump_json())
        tool = bounded_artifact_review_tool(ws, model)
        first = await tool('artifact', ['rule-comparison'], [receipt])
        second = await tool('artifact', ['rule-comparison'], [receipt])
        assert second['reused'] and len(model.calls) == 1
        saved = cs.read(first['result']['review_ref'])
        assert saved['owner_id'] == reviewer.id
        assert saved['payload']['items'] == expected.model_dump()['items']
        assert reconcile(cs, reviewer.task_id)['execution_complete']
        assert json.loads(model.calls[0][1][1])['evidence'][0]['receipt_id'] == receipt


async def test_model_cannot_invent_receipts_or_close_missing_pages(ws):
    cs, refs, snap, export, render, source, requested = setup(ws, pages=2)
    with delegated_task(ws, 'coordinator', requested) as (_, reviewer):
        receipt = visual(cs, reviewer, render, export, source, 1)
        incomplete = payload(snap, refs, render, [receipt])
        model = Model(incomplete.model_dump_json())
        with pytest.raises(ActionRejected, match='COVERAGE_INCOMPLETE'):
            await bounded_artifact_review_tool(ws, model)('incomplete', ['rule-comparison'], [receipt])
        forged = incomplete.model_dump()
        forged['items'][0]['observations'][0]['receipt_id'] = 'fabricated'
        forged_model = Model(json.dumps(forged))
        forged_model.model_name = 'distinct-forged-fixture-service'
        with pytest.raises(ActionRejected, match='INVENTED_OBSERVATION'):
            await bounded_artifact_review_tool(ws, forged_model)(
                'forged', ['rule-comparison'], [receipt])
        assert not cs.list_objects('ReviewRecord')


async def test_foreign_task_receipt_rejected_before_text_model(ws):
    cs, refs, snap, export, render, source, requested = setup(ws, pages=1)
    with delegated_task(ws, 'coordinator', requested) as (_, reviewer):
        foreign = cs.observe(type(reviewer)('foreign', 'reviewer', 'foreign'), {'observation': 'other task'})['receipt_id']
        model = Model()
        with pytest.raises(ActionRejected, match='CURRENT_TASK_RECEIPT'):
            await bounded_artifact_review_tool(ws, model)('foreign', ['rule-comparison'], [foreign])
        assert not model.calls


async def test_partial_artifact_findings_preserve_missing_coverage(ws):
    cs, refs, snap, export, render, source, requested = setup(ws, pages=2)
    with delegated_task(ws, 'coordinator', requested) as (_, reviewer):
        receipt = visual(cs, reviewer, render, export, source, 1)
        partial = payload(snap, refs, render, [receipt], complete=False)
        await bounded_artifact_review_tool(ws, Model(partial.model_dump_json()))(
            'partial', ['rule-comparison'], [receipt])
        assert not reconcile(cs, reviewer.task_id)['execution_complete']

