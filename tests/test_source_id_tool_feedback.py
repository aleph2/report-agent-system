"""Source selection stays exact while guiding callers to the catalog identity."""
import pytest
from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_core.tools import StructuredTool
from report_agent.deep_runtime import business_tools
from report_agent.errors import ActionRejected
from test_source_search_view import ws


def test_source_page_describes_catalog_id_and_rejects_other_ids(ws):
    from report_agent.tool_discovery import bind_profile
    bind_profile(ws.store, "agent-search-v2")
    tool = next(t for t in business_tools(ws, "reviewer", None, None)
                if t.__name__ == "read_source_page")
    description = convert_to_openai_tool(StructuredTool.from_function(tool))["function"]["parameters"]["properties"]["source_id"]["description"]
    assert "SourceArtifact" in description and "source_id" in description
    assert tool("original")["source"]["id"] == "original"
    for wrong_id in ("source-artifact-object-id", "other-project-source-id"):
        with pytest.raises(ActionRejected) as exc:
            tool(wrong_id)
        assert str(exc.value).startswith("SOURCE_NOT_IN_PROJECT:")
        assert "SourceArtifact" in str(exc.value)


async def test_native_boundary_guides_object_id_then_reads_catalog_id(tmp_path):
    import json
    from langchain.agents import create_agent
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    from report_agent.content_store import ContentStore
    from report_agent.hierarchical_tools import actor_for
    from report_agent.deep_runtime import BusinessBoundary
    from report_agent.store import Store
    from report_agent.workspace import Workspace
    from test_deep_runtime import Driver, invoke

    store = Store(tmp_path)
    store.initialize({"goal": "Read the original source", "content_contract": "hierarchical-review-v1",
                      "sources": [{"id": "catalog-source", "title": "Synthetic",
                                   "content": "Synthetic source text", "coverage": "complete"}]})
    workspace = Workspace(store)
    content = ContentStore(store)
    imported = content.import_inputs(actor_for("coordinator"), "inputs", ["catalog-source"])["result"]
    source_ref = imported["source_refs"][0]
    source = content.read(source_ref)
    catalog_id = source["payload"]["source_id"]
    assert source_ref["id"] != catalog_id
    read = next(t for t in business_tools(workspace, "coordinator", None, None)
                if t.__name__ == "read_source_page")
    observed = []

    def after_bad(messages):
        result = next(m for m in reversed(messages) if isinstance(m, ToolMessage) and m.name == "read_source_page")
        value = json.loads(result.content)
        observed.append(value)
        return invoke("read_source_page", source_id=catalog_id)

    def after_good(messages):
        result = next(m for m in reversed(messages) if isinstance(m, ToolMessage) and m.name == "read_source_page")
        observed.append(json.loads(result.content))
        return AIMessage(content="Source read.")

    driver = Driver(coordinator=[invoke("read_source_page", source_id=source_ref["id"]),
                                 after_bad, after_good])
    agent = create_agent(model=driver("coordinator"), tools=[read],
                         middleware=[BusinessBoundary(workspace, "coordinator")])
    await agent.ainvoke({"messages": [HumanMessage(content="Read the source.")]})
    assert observed[0]["code"] == "SOURCE_NOT_IN_PROJECT"
    assert "SourceArtifact.ref.id" in observed[0]["message"]
    assert observed[1]["source"]["id"] == catalog_id
    assert observed[1]["blocks"][0]["text"] == "Synthetic source text"

