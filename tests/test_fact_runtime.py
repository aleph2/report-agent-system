from copy import deepcopy
from io import BytesIO

from docx import Document
import pytest

from report_agent.catalog import Catalog
from report_agent.deep_runtime import business_tools
from report_agent.errors import ActionForbidden, ActionRejected
from report_agent.exporting import export_docx
from report_agent.store import digest
from test_fact_adoption import ws


class Graph:
    def __init__(self):
        self.calls = 0
        self.fail = False
        self.current = True

    def read_many(self, ids):
        self.calls += 1
        if self.fail:
            raise ConnectionError("unavailable")
        if ids != ["fact"]:
            raise ActionRejected("KNOWLEDGE_NOT_FOUND_IN_PROJECT")
        return [{"id": "fact", "current": self.current,
                 "provenance": [{"source_id": "source", "locator": "page 1"}]}]

    def close(self):
        pass


def bound(ws, graph, name):
    return next(t for t in business_tools(ws, "writer", graph, None) if t.__name__ == name)


def args(**kwargs):
    return {"kind": "draft", "title": "Report", "body": "Evidence-based content",
            "source_ids": [], "input_ids": [], "fact_ids": ["fact"], **kwargs}


def test_lost_submit_response_recovers_receipt_without_graph_or_new_task(ws):
    graph = Graph()
    submit = bound(ws, graph, "submit_result")
    result = submit(**args())
    assert result["source_ids"] == ["source"]
    graph.fail = True
    ws.store.set("context_revision", 8)
    before = ws.store.events()
    assert submit(**args()) == result
    assert graph.calls == 1
    assert len(ws.tasks()) == len(ws.results()) == 1
    assert ws.store.events() == before


def test_fact_source_versions_enter_existing_update_impact_chain(ws):
    graph = Graph()
    result = bound(ws, graph, "submit_result")(**args())
    Catalog(ws.store).import_file("source.txt", b"Corrected source evidence", replaces_id="source")
    assert result["id"] in ws.impact()["affected_result_ids"]


def test_invalid_fact_rejected_before_any_commit(ws):
    with pytest.raises(ActionRejected, match="NOT_FOUND"):
        bound(ws, Graph(), "submit_result")(**args(fact_ids=["foreign"]))
    assert not ws.results()


def test_read_result_and_export_expose_unknown_currentness(ws, monkeypatch):
    graph = Graph()
    result = bound(ws, graph, "submit_result")(**args())
    ws.store.set("knowledge_project_id", "project")
    monkeypatch.setattr("report_agent.knowledge.Knowledge", lambda *a, **kw: graph)
    graph.fail = True
    read = bound(ws, graph, "read_result")(result["id"])
    assert not read["current"]
    assert read["knowledge"]["status"] == "unknown"
    text = "\n".join(p.text for p in Document(BytesIO(
        export_docx(ws, result["id"], include_execution_record=True))).paragraphs)
    assert "current validity is unknown" in text
    assert "[source]" in text  # Commit retained provenance even when graph is down.
    uncertainty = 'The original groundwater record is missing; its level remains unresolved.'
    ws.issue('source_missing', uncertainty, ['source'])
    customer = "\n".join(p.text for p in Document(BytesIO(export_docx(ws, result['id']))).paragraphs)
    assert uncertainty in customer and '[source]' in customer
    assert result['body'] in customer
    assert result['id'] not in customer and 'Knowledge validity at export:' not in customer


def test_revision_removes_only_explicit_predecessor_before_task_creation(ws):
    graph = Graph()
    submit = bound(ws, graph, "submit_result")
    base = submit(**args(title="Original draft", fact_ids=[]))
    other = submit(**args(title="Other adopted result", fact_ids=[]))
    original = ws.result(base["id"])
    request = args(title="Revised draft", body="Updated supported content",
                   input_ids=[base["id"], other["id"], base["id"]], replaces_id=base["id"])
    before = deepcopy(request)

    result = submit(**request)

    assert request == before
    assert result["replaces_id"] == base["id"]
    assert result["input_ids"] == [other["id"]]
    assert result["source_ids"] == ["source"] and result["fact_ids"] == ["fact"]
    task = ws.task(ws.result(result["id"])["task_id"])
    assert task["goal"] == request["title"] + ": " + digest({
        "body": request["body"], "facts": ["fact"], "sources": ["source"], "inputs": [other["id"]]})
    assert task["owner"] == result["owner"] == "writer"
    assert task["replaces_id"] == base["id"]
    assert ws.result(base["id"]) == original
    assert ws.impact()["replacements"] == {base["id"]: result["id"]}
    assert result["id"] not in ws.impact()["affected_result_ids"]


def test_without_explicit_replaces_id_keeps_predecessor_as_adopted_input(ws):
    submit = bound(ws, Graph(), "submit_result")
    base = submit(**args(title="Existing draft", fact_ids=[]))
    result = submit(**args(title="Separate draft", input_ids=[base["id"]], fact_ids=[]))
    assert result["input_ids"] == [base["id"]]
    assert not result.get("replaces_id")
    assert not ws.impact()["replacements"]


def test_revision_receipt_keeps_original_request_hash_and_replays_before_validation(ws):
    graph = Graph()
    submit = bound(ws, graph, "submit_result")
    base = submit(**args(title="Receipt base", fact_ids=[]))
    other = submit(**args(title="Receipt adopted input", fact_ids=[]))
    request = args(title="Receipt revision", input_ids=[base["id"], other["id"], base["id"]],
                   replaces_id=base["id"])
    original_request = deepcopy(request)
    original_hash_data = {
        "role": "writer", "kind": "draft", "title": request["title"], "body": request["body"],
        "sources": [], "inputs": sorted({base["id"], other["id"]}), "facts": ["fact"],
        "outcome": "", "target": "", "replaces": base["id"],
    }
    original_hash = digest(original_hash_data)
    normalized_hash = digest({**original_hash_data, "inputs": [other["id"]]})

    result = submit(**request)

    assert request == original_request
    saved = ws.result(result["id"])
    assert saved["submission_id"] == original_hash
    assert ws.submission_receipt(original_hash) == saved
    assert ws.submission_receipt(normalized_hash) is None
    assert saved["input_ids"] == [other["id"]] and saved["source_ids"] == ["source"]
    assert graph.calls == 1
    graph.fail = True
    ws.store.set("context_revision", 8)
    before = (ws.tasks(), ws.results(), ws.store.events())

    # A fresh binding replays the original request despite its now-expired base,
    # changed context and unavailable graph, without creating a replacement task.
    assert bound(ws, graph, "submit_result")(**original_request) == result
    assert graph.calls == 1
    assert (ws.tasks(), ws.results(), ws.store.events()) == before
    assert ws.result(result["id"]) == saved


def test_normalization_does_not_allow_replacing_a_foreign_producer_result(ws):
    task = ws.request_task("plan", "Planner-owned result", [])
    foreign = ws.submit(task["id"], actor="planner", title="Plan", body="Synthetic plan",
                        source_ids=[], input_ids=[])
    submit = bound(ws, Graph(), "submit_result")
    before = (ws.tasks(), ws.results(), ws.store.events())
    with pytest.raises(ActionForbidden, match="REPLACEMENT_OWNER_MISMATCH"):
        submit(**args(replaces_id=foreign["id"], input_ids=[foreign["id"]], fact_ids=[]))
    assert (ws.tasks(), ws.results(), ws.store.events()) == before
    assert not ws.impact()["replacements"]


def test_normalization_does_not_allow_a_new_revision_of_a_superseded_base(ws):
    submit = bound(ws, Graph(), "submit_result")
    base = submit(**args(title="Expired base", fact_ids=[]))
    first = submit(**args(title="Current revision", replaces_id=base["id"],
                          input_ids=[base["id"]], fact_ids=[]))
    before = (ws.tasks(), ws.results(), ws.store.events())
    with pytest.raises(ActionRejected, match="REVISION_REQUIRES_CURRENT_RESULT"):
        submit(**args(title="Conflicting new revision", body="Different request, not a receipt replay",
                      replaces_id=base["id"], input_ids=[base["id"]], fact_ids=[]))
    assert (ws.tasks(), ws.results(), ws.store.events()) == before
    assert ws.impact()["replacements"] == {base["id"]: first["id"]}


def test_normalization_preserves_changed_input_evidence_without_rejection(ws):
    submit = bound(ws, Graph(), "submit_result")
    base = submit(**args(title="Unchanged base", fact_ids=[]))
    other = submit(**args(title="Adopted old version", fact_ids=[]))
    other_revision = submit(**args(title="Adopted new version", replaces_id=other["id"], fact_ids=[]))
    result = submit(**args(title="Revision with changed evidence", replaces_id=base["id"],
                          input_ids=[base["id"], other["id"]], fact_ids=[]))
    assert result["input_ids"] == [other["id"]]
    assert result["input_changes"]
    assert ws.impact()["replacements"] == {other["id"]: other_revision["id"], base["id"]: result["id"]}


def test_direct_workspace_submission_still_rejects_predecessor_as_dependency(ws):
    base = bound(ws, Graph(), "submit_result")(**args(title="Workspace base", fact_ids=[]))
    revision = ws.request_revision(base["id"], "Direct Workspace revision")
    before = (ws.tasks(), ws.results(), ws.store.events())
    with pytest.raises(ActionRejected, match="PREDECESSOR_IS_NOT_AN_INPUT_DEPENDENCY"):
        ws.submit(revision["id"], actor="writer", title="Direct revision", body="Synthetic revision",
                  source_ids=[], input_ids=[base["id"]])
    assert (ws.tasks(), ws.results(), ws.store.events()) == before
    assert not ws.impact()["replacements"]
