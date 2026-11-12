"""Run authority restricts native tools without changing ordinary report catalogs."""
from types import SimpleNamespace
import json

import pytest
from langchain.agents.middleware.types import ModelRequest

from report_agent.fake_planning_probe import PROBE_UNAVAILABLE_TOOLS
from report_agent.tool_selection import tool_scope, scope_catalog, reject_unoffered
from test_context_editing import offered
from test_deep_runtime import Driver


def test_catalog_is_request_local_and_resets_after_scope_failure():
    original = ModelRequest(model=Driver()('coordinator'), messages=[], state={'messages': []},
        tools=[offered('read_source_page'), offered('analyze_source_image'), offered('task')])
    assert scope_catalog(original) is original
    with pytest.raises(RuntimeError, match='synthetic'):
        with tool_scope({'glm-5.3'}, {'vision':'not-approved','text_tool':'not-approved'}, excluded=PROBE_UNAVAILABLE_TOOLS):
            outgoing = scope_catalog(original)
            assert [t['function']['name'] for t in outgoing.tools] == ['read_source_page']
            assert len(original.tools) == 3
            raise RuntimeError('synthetic')
    assert scope_catalog(original) is original


@pytest.mark.parametrize('name', ['analyze_source_image', 'inspect_rendered_page', 'analyze_text',
    'analyze_evidence', 'process_report_content', 'perform_assigned_review',
    'perform_assigned_artifact_review', 'task', 'export_content_snapshot',
    'export_content_workbook', 'render_content_export', 'select_delivery',
    'request_system_delivery', 'select_content_delivery'])
def test_guessed_unauthorized_tool_is_rejected_before_binding_even_with_selector_off(name):
    workspace = SimpleNamespace(store=SimpleNamespace(manifest={'tool_selection_mode': 'off'}))
    request = SimpleNamespace(tool_call={'name': name, 'id': 'not-executed', 'args': {}}, runtime=None)
    with tool_scope({'glm-5.3'}, {'vision':'not-approved','text_tool':'not-approved'}, excluded=PROBE_UNAVAILABLE_TOOLS):
        result = reject_unoffered(workspace, 'coordinator', request)
        assert result.status == 'error' and result.tool_call_id == 'not-executed'
        assert json.loads(result.content)['code'] == 'TOOL_NOT_AUTHORIZED_FOR_RUN'
        assert json.loads(result.content)['execution_state'] == 'not_executed'
    assert reject_unoffered(workspace, 'coordinator', request) is None


async def test_ordinary_native_report_still_offers_visual_and_delegation_tools(tmp_path):
    from test_fake_draft_flow import checkpoint
    _, _, driver, _ = await checkpoint(tmp_path)
    names = {t['name'] for t in driver.bindings['coordinator'][0]}
    assert {'analyze_source_image', 'task', 'analyze_text'} <= names
