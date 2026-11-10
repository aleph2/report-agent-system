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
    current_native_profiles(f)
    driver=Driver(coordinator=[AIMessage(content='', tool_calls=[call('ask_human',
        dict(category='requirement',description='Planning checkpoint',source_ids=[],pause=True),'pause')])])
    await build_agent(f.ws,driver,None).ainvoke({'messages':[HumanMessage('Plan this commission.')]})
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
