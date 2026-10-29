"""Discovery uses supplied role metadata; search grants no execution authority."""
import pytest
from report_agent.tool_discovery import ToolCatalog

TOOLS = [
    {"name": "export_word", "description": "Export a report as a Word document 导出报告"},
    {"name": "read_source", "description": "Read source text blocks 读取资料"},
    {"name": "submit_review", "description": "Submit an independent review 审核报告"},
]

def test_exact_name_bilingual_match_and_empty_browse():
    c = ToolCatalog(TOOLS[:2])
    assert c.search("export_word")["matches"][0]["name"] == "export_word"
    assert "export_word" in [x["name"] for x in c.search("导出报告")["matches"]]
    one = c.search("", offset=0, limit=1)
    two = c.search("", offset=one["next_offset"], limit=1)
    assert [x["name"] for x in one["matches"] + two["matches"]] == ["export_word", "read_source"]
    assert one["total"] == 2 and two["next_offset"] is None

def test_missing_does_not_invent_capability_or_include_other_role():
    c = ToolCatalog(TOOLS[:2])
    result = c.search("submit_review")
    assert result["matches"] == [] and result["total"] == 0
    assert "submit_review" not in [x["name"] for x in c.search("")["matches"]]

def test_input_validation_and_duplicate_names():
    with pytest.raises(ValueError): ToolCatalog([TOOLS[0], TOOLS[0]])
    c=ToolCatalog(TOOLS)
    for kwargs in ({"query":"x"*501},{"query":"x","limit":0},{"query":"x","offset":-1}):
        with pytest.raises(ValueError): c.search(**kwargs)


def test_query_is_data_and_unicode_names_are_stable():
    c=ToolCatalog(TOOLS)
    assert c.search("ＯＲ")["matches"] == []
    assert c.search("*\"()：")["matches"] == []
    assert c.search("ｅｘｐｏｒｔ＿ｗｏｒｄ")["matches"][0]["name"] == "export_word"
    assert c.search("现场施工")["matches"] == []

def test_ranking_and_pagination_do_not_depend_on_registration_order():
    left=ToolCatalog(TOOLS);right=ToolCatalog(list(reversed(TOOLS)))
    assert left.search("报告") == right.search("报告")
    assert left.search("读取资料")["matches"][0]["name"] == "read_source"
    assert left.search("",limit=1)["next_offset"] == 1

def test_bool_offsets_and_limits_are_not_integers():
    c=ToolCatalog(TOOLS)
    with pytest.raises(ValueError): c.search("",offset=True)
    with pytest.raises(ValueError): c.search("",limit=True)


@pytest.mark.asyncio
async def test_native_tool_node_can_search_concurrently_without_shared_connection():
    import asyncio
    from langchain_core.messages import AIMessage, ToolMessage
    from langchain_core.tools import StructuredTool
    from langgraph.prebuilt import ToolNode
    from langgraph.graph import StateGraph, MessagesState, START, END
    c=ToolCatalog(TOOLS)
    search=StructuredTool.from_function(c.search,name="search_tools",description="Search role tools.")
    node=ToolNode([search])
    graph=StateGraph(MessagesState).add_node("tools",node).add_edge(START,"tools").add_edge("tools",END).compile()
    async def invoke(query, call_id):
        state={"messages":[AIMessage(content="",tool_calls=[{"name":"search_tools","args":{"query":query},"id":call_id,"type":"tool_call"}])]}
        result=await graph.ainvoke(state)
        return {"messages":[result["messages"][-1]]}
    a,b=await asyncio.gather(invoke("export_word","a"),invoke("读取资料","b"))
    assert isinstance(a["messages"][0],ToolMessage) and a["messages"][0].status=="success"
    assert isinstance(b["messages"][0],ToolMessage) and b["messages"][0].status=="success"
    assert "export_word" in a["messages"][0].content and "read_source" in b["messages"][0].content


def test_query_with_too_many_unique_terms_is_rejected_explicitly():
    c=ToolCatalog(TOOLS)
    query=" ".join("x"+str(i) for i in range(110))
    assert len(query) <= 500
    with pytest.raises(ValueError,match="terms"): c.search(query)


def test_bm25_uses_document_term_frequency():
    c=ToolCatalog([{"name":"a","description":"风险 工作"},{"name":"z","description":"风险 风险 风险 风险 风险 工作"}])
    assert c.search("风险")["matches"][0]["name"] == "z"

def test_exposed_tool_schema_has_primitive_argument_types():
    from langchain_core.tools import StructuredTool
    search=StructuredTool.from_function(ToolCatalog(TOOLS).search,name="search_tools",description="Search tools")
    schema=search.tool_call_schema.model_json_schema()["properties"]
    assert schema["query"]["type"] == "string"
    assert schema["offset"]["type"] == "integer" and schema["limit"]["type"] == "integer"


def test_registered_duplicate_identity_deduplicates_but_conflict_rejects():
    def check():
        """Check something."""
    catalog=ToolCatalog.from_registered([check,check])
    assert catalog.search("")["total"] == 1
    def different():
        """Check something."""
    different.__name__="check"
    with pytest.raises(ValueError,match="duplicate"): ToolCatalog.from_registered([check,different])


def test_real_role_registration_remains_separate_in_fake_workspace(tmp_path):
    from report_agent.store import Store
    from report_agent.workspace import Workspace
    from report_agent.deep_runtime import business_tools
    s=Store(tmp_path); s.initialize({
        "goal":"Synthetic test", "content_contract":"hierarchical-review-v1",
        "review_entrypoint":"delegated-reviewer-v1", "review_execution_mode":"native-reviewer-v2",
        "review_interface_profile":"review-interfaces-v4", "delegation_prompt_profile":"separate-description-v1",
        "operation_identity_profile":"native-tool-runtime-v1", "context_policy":"stateful-tools-v2",
        "sources":[{"id":"fake","title":"Synthetic","content":"Synthetic data only","coverage":"complete"}]})
    ws=Workspace(s)
    co=ToolCatalog.from_registered(business_tools(ws,"coordinator",None,None))
    reviewer_tools=business_tools(ws,"reviewer",None,None)
    reviewer=ToolCatalog.from_registered(reviewer_tools)
    from report_agent.tool_discovery import ToolDiscovery
    assert set(ToolDiscovery(reviewer_tools).fingerprints) == set(reviewer.tools)
    assert "select_content_delivery" in co.tools and "select_content_delivery" not in reviewer.tools
    assert "submit_review" in reviewer.tools and "submit_review" not in co.tools
    assert len(reviewer.tools) > 0


def test_registered_parameter_names_are_searchable_without_full_schema():
    def inspect_result(*, export_reference: str):
        """Examine an artifact."""
    c=ToolCatalog.from_registered([inspect_result])
    assert c.search("export_reference")["matches"][0]["name"] == "inspect_result"
    assert "export_reference" not in c.search("")["matches"][0]["description"]


def test_structured_tool_parameter_metadata_does_not_invoke_tool():
    from langchain_core.tools import StructuredTool
    calls=[]
    def inspect_artifact(*, evidence_ref: str):
        """Inspect an artifact."""
        calls.append(evidence_ref)
    tool=StructuredTool.from_function(inspect_artifact)
    c=ToolCatalog.from_registered([tool])
    assert c.search("evidence_ref")["matches"][0]["name"] == "inspect_artifact"
    assert calls == []


def test_injected_tool_arguments_are_not_search_metadata():
    from typing import Annotated
    from langchain_core.tools import StructuredTool, InjectedToolCallId
    def inspect_item(*, document_ref: str, private_injected_marker: Annotated[str, InjectedToolCallId]):
        """Inspect an item."""
    tool=StructuredTool.from_function(inspect_item)
    c=ToolCatalog.from_registered([tool])
    assert c.search("document_ref")["matches"][0]["name"] == "inspect_item"
    assert c.search("private_injected_marker")["matches"] == []


def test_search_indexes_actual_wire_properties_even_if_model_has_alias():
    from pydantic import BaseModel,Field
    from langchain_core.tools import StructuredTool
    class Args(BaseModel):
        internal_ref: str=Field(alias="public_evidence_key")
    def inspect_item(**kwargs):
        """Inspect an item."""
    tool=StructuredTool.from_function(inspect_item,args_schema=Args)
    c=ToolCatalog.from_registered([tool])
    from langchain_core.utils.function_calling import convert_to_openai_tool
    exposed=convert_to_openai_tool(tool)["function"]["parameters"]["properties"]
    assert set(exposed) == {"internal_ref"}
    assert c.search("internal_ref")["matches"][0]["name"] == "inspect_item"
    assert c.search("public_evidence_key")["matches"] == []


def test_hybrid_search_can_suggest_cross_language_candidate_without_executing():
    class FakeEmbedding:
        def embed_documents(self,texts):
            return [[1.0,0.0] if "Export" in text else [0.0,1.0] for text in texts]
        def embed_query(self,text): return [1.0,0.0]
    c=ToolCatalog(TOOLS[:2],embedder=FakeEmbedding())
    assert c.search("生成文档",mode="lexical")["matches"] == []
    result=c.search("生成文档",mode="hybrid")
    assert result["matches"][0]["name"] == "export_word"
    assert result["semantic_candidates_are_not_proof"] is True

def test_hybrid_search_unavailable_or_invalid_vectors_are_explicit():
    class BrokenEmbedding:
        def embed_documents(self,texts): raise OSError("offline")
    c=ToolCatalog(TOOLS,embedder=BrokenEmbedding())
    with pytest.raises(ValueError,match="SEMANTIC_SEARCH_UNAVAILABLE"):
        c.search("anything",mode="hybrid")
    assert c.search("export_word")["matches"][0]["name"] == "export_word"


def test_local_embedding_missing_cache_never_downloads_when_local_only(tmp_path,monkeypatch):
    import huggingface_hub
    from huggingface_hub.errors import LocalEntryNotFoundError
    from report_agent.embeddings import LocalEmbedding,_load
    calls=[]
    def missing(**kwargs):
        calls.append(kwargs.get("local_files_only"))
        raise LocalEntryNotFoundError("synthetic missing cache")
    monkeypatch.setattr(huggingface_hub,"snapshot_download",missing)
    _load.cache_clear()
    try:
        with pytest.raises(LocalEntryNotFoundError):
            LocalEmbedding(cache_dir=str(tmp_path),local_only=True).embed_query("fake")
        assert calls == [True]
    finally:
        _load.cache_clear()


def test_hybrid_distinguishes_semantic_candidates_from_lexical_hits():
    class FakeEmbedding:
        def embed_documents(self,texts): return [[1.0,0.0] for _ in texts]
        def embed_query(self,text): return [0.0,1.0]
    c=ToolCatalog(TOOLS,embedder=FakeEmbedding())
    result=c.search("unrelateduniquequery",mode="hybrid")
    assert result["lexical_match_count"] == 0
    assert result["semantic_candidates_are_not_proof"] is True
    assert result["matches"]

def test_search_rejects_non_string_mode():
    with pytest.raises(ValueError): ToolCatalog(TOOLS).search("x",mode=[])
