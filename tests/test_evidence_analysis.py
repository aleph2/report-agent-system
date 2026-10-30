"""Identity, permission and bounded execution checks; no semantic-quality claims."""
import json
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain_core.tools import StructuredTool
from pydantic import ValidationError

from report_agent import evidence_analysis as module
from report_agent.deep_runtime import business_tools
from report_agent.errors import ActionRejected
from report_agent.store import Store
from report_agent.workspace import Workspace


class Model:
    model_name = "offline-only"
    reasoning_effort = "high"
    max_tokens = 65536

    def __init__(self):
        self.calls = []
        self.response = AIMessage(content="A local observation, not approval.")

    async def ainvoke(self, messages):
        self.calls.append(messages)
        return self.response


@pytest.fixture
def sample(tmp_path):
    store = Store(tmp_path)
    store.initialize({"name": "Evidence controls", "goal": "Compare supplied facts.",
                      "sources": [{"id": "source", "title": "Inventory", "content": "Count: 7.",
                                   "coverage": "complete"}]})
    ws = Workspace(store)
    ws.initialize()
    task = ws.request_task("draft", "Report", [])
    report = ws.submit(task["id"], actor="writer", title="Report", body="Known count: 7. Unknown date.",
                       source_ids=["source"], input_ids=[])
    ws.select_delivery(report["id"], "")
    return ws, report, Model()


async def test_exact_selections_versions_and_business_artifacts_unchanged(sample):
    ws, report, model = sample
    before = ws.results(), ws.store.manifest, ws.store.get("delivery")
    result = await module.analyze_selected_evidence(ws, model, "Is the stated count supported?",
             [{"source_id": "source", "offset": 0, "limit": 1}],
             [{"result_id": report["id"], "offset": 6, "characters": 9}])
    assert len(model.calls) == 1
    data = json.loads(model.calls[0][1][1])
    assert data["evidence"][0]["observation"]["blocks"][0]["text"] == "Count: 7."
    selected = data["evidence"][1]
    assert selected["text"] == report["body"][6:15]
    assert selected["next_offset"] == 15
    assert selected["body_sha256"] == module._sha(report["body"])
    assert selected["selected_delivery"] is True
    assert before == (ws.results(), ws.store.manifest, ws.store.get("delivery"))
    assert result["reused"] is False
    assert "private" not in result


async def test_cache_binds_question_actual_content_parameters_and_configured_prompt(sample, monkeypatch, tmp_path):
    ws, report, model = sample
    sources = [{"source_id": "source"}]
    results = [{"result_id": report["id"]}]
    first = await module.analyze_selected_evidence(ws, model, "Compare.", sources, results)
    second = await module.analyze_selected_evidence(ws, model, "Compare.", sources, results)
    assert second["reused"] and first["operation"] == second["operation"]
    assert len(model.calls) == 1
    model.reasoning_effort = "medium"
    third = await module.analyze_selected_evidence(ws, model, "Compare.", sources, results)
    assert third["operation"] != first["operation"]
    from report_agent import prompt_sources
    rules = tmp_path / "configured-rules"
    rules.mkdir()
    (rules / "evidence-analysis.md").write_text(module.ANALYSIS_PROMPT, encoding="utf-8")
    monkeypatch.setattr(prompt_sources, "RULES", rules)
    # A byte-identical configured reload retains the content-derived identity.
    monkeypatch.setattr(module, "ANALYSIS_PROMPT", prompt_sources.load_prompt("evidence-analysis"))
    reloaded = await module.analyze_selected_evidence(ws, model, "Compare.", sources, results)
    assert reloaded["reused"] and reloaded["operation"] == third["operation"]
    assert len(model.calls) == 2
    revised = module.ANALYSIS_PROMPT + " Contract revision."
    (rules / "evidence-analysis.md").write_text(revised, encoding="utf-8")
    # Explicit reload represents a new configured process; production has no hot reload.
    monkeypatch.setattr(module, "ANALYSIS_PROMPT", prompt_sources.load_prompt("evidence-analysis"))
    fourth = await module.analyze_selected_evidence(ws, model, "Compare.", sources, results)
    assert fourth["operation"] != third["operation"]
    assert len(model.calls) == 3 and model.calls[-1][0][1] == revised
    fifth = await module.analyze_selected_evidence(ws, model, "Different question.", sources, results)
    sixth = await module.analyze_selected_evidence(ws, model, "Different question.", sources,
                                                [{"result_id": report["id"], "characters": 10}])
    assert len({r["operation"] for r in [first, third, fourth, fifth, sixth]}) == 5


@pytest.mark.parametrize("revision", ["code-only", "file-only"])
async def test_unmatched_prompt_revision_rejected_before_cache_or_model(sample, monkeypatch, tmp_path, revision):
    from report_agent import prompt_sources
    from report_agent.prompt_provenance import PromptCompositionError
    ws, report, model = sample
    sources, results = [{"source_id": "source"}], [{"result_id": report["id"]}]
    await module.analyze_selected_evidence(ws, model, "Compare.", sources, results)
    rules = tmp_path / "configured-rules"
    rules.mkdir()
    (rules / "evidence-analysis.md").write_text(module.ANALYSIS_PROMPT, encoding="utf-8")
    monkeypatch.setattr(prompt_sources, "RULES", rules)
    if revision == "code-only":
        monkeypatch.setattr(module, "ANALYSIS_PROMPT", module.ANALYSIS_PROMPT + " Unconfigured edit.")
    else:
        (rules / "evidence-analysis.md").write_text(module.ANALYSIS_PROMPT + " Unloaded edit.", encoding="utf-8")
    before_events = ws.store.events()
    with ws.store.connect() as db:
        before_state = db.execute("SELECT * FROM state ORDER BY key").fetchall()
        before_cache = db.execute("SELECT * FROM analyses ORDER BY operation").fetchall()
    monkeypatch.setattr(ws.store, "analysis", lambda *a: pytest.fail("Rejected prompt reached cache"))
    with pytest.raises(PromptCompositionError, match="PROMPT_STATIC_COMPOSITION_MISMATCH"):
        await module.analyze_selected_evidence(ws, model, "Compare.", sources, results)
    assert len(model.calls) == 1
    assert ws.store.events() == before_events
    with ws.store.connect() as db:
        assert db.execute("SELECT * FROM state ORDER BY key").fetchall() == before_state
        assert db.execute("SELECT * FROM analyses ORDER BY operation").fetchall() == before_cache


async def test_missing_or_invalid_selections_rejected_before_cache_and_model(sample, monkeypatch):
    ws, report, model = sample
    monkeypatch.setattr(ws.store, "analysis", lambda *a: pytest.fail("Invalid selection reached cache"))
    invalid = [([{"source_id": "other-project"}], [], ActionRejected),
               ([], [{"result_id": "other-project"}], ActionRejected),
               ([{"source_id": "source", "offset": -1}], [], ValidationError),
               ([{"source_id": "source", "offset": True}], [], ValidationError),
               ([], [{"result_id": report["id"], "role": "coordinator"}], ValidationError),
               ([], [], ActionRejected),
               ([], [{"result_id": report["id"], "offset": 1000}], ActionRejected)]
    for sources, results, error in invalid:
        with pytest.raises(error):
            await module.analyze_selected_evidence(ws, model, "Compare.", sources, results)
    assert not model.calls


async def test_historical_result_cannot_masquerade_as_current(sample):
    ws, report, model = sample
    old = await module.analyze_selected_evidence(ws, model, "Compare.", [], [{"result_id": report["id"]}])
    task = ws.request_revision(report["id"], "New version")
    new = ws.submit(task["id"], actor="writer", title="Report", body="Count: 7, date unknown.",
                    source_ids=["source"], input_ids=[])
    ws.select_delivery(new["id"], "")
    result = await module.analyze_selected_evidence(ws, model, "Compare.", [], [{"result_id": report["id"]}])
    assert result["operation"] != old["operation"]
    assert result["evidence"][0]["selected_delivery"] is False
    assert result["evidence"][0]["replaced_by"] == [new["id"]]


async def test_no_hidden_tool_execution_or_empty_success_cache(sample):
    ws, report, model = sample
    for response, code in [(AIMessage(content="", tool_calls=[{
            "id": "x", "name": "write_report", "args": {}, "type": "tool_call"}]),
            "EVIDENCE_ANALYSIS_RETURNED_TOOL_CALLS"),
            (AIMessage(content=""), "EVIDENCE_ANALYSIS_EMPTY_RESPONSE")]:
        model.response = response
        with pytest.raises(ActionRejected, match=code):
            await module.analyze_selected_evidence(ws, model, code, [{"source_id": "source"}], [])
    with ws.store.connect() as db:
        assert db.execute("SELECT count(*) FROM analyses").fetchone()[0] == 0
    assert len(ws.results()) == 1


async def test_whole_page_supplement_limits_arrive_unchanged(sample, monkeypatch):
    ws, report, model = sample
    supplement = {"source_table_views": [{"page": 9, "rows": [[None, "7"]],
                   "limitations": ["Whole page may exceed selected text blocks."]}]}
    monkeypatch.setattr(module, "with_source_tables", lambda w, page: {**page, **supplement})
    await module.analyze_selected_evidence(ws, model, "Compare.", [{"source_id": "source"}], [])
    actual = json.loads(model.calls[0][1][1])["evidence"][0]["observation"]
    assert actual["source_table_views"] == supplement["source_table_views"]


def test_tool_exposure_and_strict_selector_schema(sample):
    ws, report, model = sample
    reviewer = {t.__name__: t for t in business_tools(ws, "reviewer", None, model)}
    tool = StructuredTool.from_function(coroutine=reviewer["analyze_evidence"])
    schema = convert_to_openai_tool(tool)["function"]["parameters"]
    assert set(schema["properties"]) == {"question", "source_selections", "result_selections",
                                          "snapshot_ref", "content_selections"}
    for role in ("coordinator", "writer", "knowledge"):
        assert "analyze_evidence" not in {t.__name__ for t in business_tools(ws, role, None, model)}


async def test_native_structured_tool_accepts_json_selectors_and_records_observation(sample):
    ws, report, model = sample
    available = {t.__name__: t for t in business_tools(ws, "reviewer", None, model)}
    tool = StructuredTool.from_function(coroutine=available["analyze_evidence"])
    args = {"question": "Compare.", "source_selections": [{"source_id": "source"}],
            "result_selections": [{"result_id": report["id"], "characters": 14}]}
    first = await tool.ainvoke(args)
    second = await tool.ainvoke(args)
    assert first["evidence"][1]["text"] == report["body"][:14]
    assert second["reused"] and len(model.calls) == 1
    saved_review = available["submit_result"](title="Local review", body="Observed selected report.",
                    source_ids=["source"], target_id=report["id"], outcome="accepted")
    assert report["id"] in saved_review["observed_result_ids"]
