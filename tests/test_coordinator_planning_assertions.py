"""Offline scripted planning through the real Coordinator and imported PDF pages."""
import json
from uuid import NAMESPACE_URL, uuid5

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from report_agent.assertion_host import AssertionHost, Grant
from report_agent.catalog import Catalog
from report_agent.commission_planning import save_item
from report_agent.content_store import ContentStore
from report_agent.deep_runtime import build_agent
from support.source_policy import configure_source_use
from report_agent.source_use import immutable_version_digest
from test_deep_runtime import Driver, call
from test_ingestion import pdf_bytes
from test_m1_g4_planning_steps import (anchored, current_native_profiles, draft_case, entries,
    method_commission, offline_only, required_case)


async def test_coordinator_offers_page_proposals_not_value_extraction(draft_case):
    f=draft_case
    from test_m1_g4_planning_steps import save_draft_parts, planning
    save_draft_parts(f)
    submitted=planning().submit_plan(f.cs,f.co,"native-binding-plan")["result"]["plan_ref"]
    current_native_profiles(f)
    subject=f.plan["objects"][0]["object_id"]
    indicator=f.plan["method_pack"]["indicators"][0]["id"]
    driver=Driver(coordinator=[
        AIMessage(content="",tool_calls=[call("propose_page_binding",
            dict(items=[dict(subject=subject,indicator_ids=[indicator],pages=[])]),"native-page-proposal")]),
        AIMessage(content='', tool_calls=[call('ask_human',
            dict(category='requirement',description='Planning checkpoint',source_ids=[],pause=True),'pause')])])
    await build_agent(f.ws,driver,None).ainvoke({'messages':[HumanMessage('Plan this commission.')]})
    from report_agent.page_bindings import records
    proposed=[row for row,state in records(f.ws.store,submitted,subject) if row["claim"]["kind"]=="convention"]
    assert len(proposed)==1 and proposed[0]["claim"]["page_binding"]["indicator_id"]==indicator
    assert proposed[0]["was_generated_by"]==f.co.task_id
    observed = next(m for m in driver.calls[-1][2] if isinstance(m, ToolMessage) and m.tool_call_id == 'native-page-proposal')
    assert json.loads(observed.content) == {'binding_ids': [proposed[0]['id']]}
    schemas={s['name']:s for s in driver.bindings['coordinator'][0]}
    assert 'assert_source' not in schemas
    assert 'propose_page_binding' in schemas
    for name in ('propose_page_binding','ask','record_conflict'):
        assert not {'runtime','operation_id','actor','packet','task','source_version'} & schemas[name]['parameters']['properties'].keys()


def test_planning_tool_closure_cannot_escalate_from_delegated_task(method_commission):
    import pytest
    from report_agent.content_store import Actor
    from report_agent.content_tasks import _native_binding
    from report_agent.errors import ActionForbidden
    from report_agent.planning_assertions import planning_assertion_tools

    f = method_commission
    tools = {t.__name__: t for t in planning_assertion_tools(f.cs, lambda: f.co)}
    writer = Actor('content:writer:example-task', 'writer', 'example-task')
    with _native_binding(f.ws, writer, {'id':'delegate', 'args':{'description':'Writer assignment'}}, False):
        with pytest.raises(ActionForbidden, match='COORDINATOR_REQUIRED'):
            tools['ask']('S1', 'Can I inherit the coordinator binding?', 'other')


def test_binding_proposal_batch_expands_indicators_and_pins_the_ordered_request(draft_case):
    import pytest
    from report_agent import page_bindings
    from report_agent.errors import ActionRejected
    from test_m1_g4_planning_steps import save_draft_parts, planning
    f = draft_case
    save_draft_parts(f)
    ref = planning().submit_plan(f.cs, f.co, 'batch-binding-plan')['result']['plan_ref']
    subject = f.plan['objects'][0]['object_id']
    indicators = [row['id'] for row in f.plan['method_pack']['indicators']]
    assert len(indicators) >= 3
    items = [dict(subject=subject, indicator_ids=indicators[:2], pages=[])]
    result = page_bindings.propose_many(f.cs, f.co, 'binding-batch', items)
    assert {row['claim']['page_binding']['indicator_id'] for row in result['bindings']} == set(indicators[:2])
    assert page_bindings.propose_many(f.cs, f.co, 'binding-batch', items) == result
    with pytest.raises(ActionRejected):
        page_bindings.propose_many(f.cs, f.co, 'binding-batch',
            [dict(subject=subject, indicator_ids=indicators[:3], pages=[])])
    with pytest.raises(ActionRejected) as caught:
        page_bindings.propose_many(f.cs, f.co, 'invalid-binding-batch',
            [dict(subject=subject, indicator_ids=[indicators[2]], pages=[]),
             dict(subject=subject, indicator_ids=['missing-indicator'], pages=[]),
             dict(subject='missing-object', indicator_ids=[indicators[2]], pages=[])])
    assert {item['index'] for item in caught.value.diagnostic['items']} == {1, 2}
    assert len([row for row, _ in page_bindings.records(f.ws.store, ref)
                if row['claim']['kind'] == 'convention']) == 2
