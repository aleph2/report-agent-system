"""Offline contracts plus opt-in checks against the dedicated new graph.

REPORT_GRAPH_TEST_URI=bolt://127.0.0.1:17687 enables graph tests.
REPORT_TEST_EMBEDDINGS=1 additionally enables the real pinned local model.
Synthetic test projects remain isolated and retained for inspection.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from uuid import uuid4

import pytest

from report_agent.embeddings import LocalEmbedding, MODEL_REVISION
from report_agent.errors import ActionForbidden, ActionRejected
from report_agent.knowledge import Knowledge


def test_description_and_embedding_are_lazy(monkeypatch):
    monkeypatch.setenv("REPORT_GRAPH_URI", "bolt://127.0.0.1:17687")
    k = Knowledge("offline")
    assert k._driver is None
    assert k.uri.endswith(":17687")
    assert k.describe()["embedding"]["dimensions"] == 384
    assert MODEL_REVISION in k.describe()["embedding"]["model_id"]
    assert "not source completeness" in k.describe()["coverage_note"]
    assert "512" in LocalEmbedding.coverage_note


@pytest.mark.parametrize("project", ["", " ", None, 3, "x\x00y"])
def test_bad_namespace(project):
    with pytest.raises(ActionRejected):
        Knowledge(project)


def test_untrusted_owner_and_readonly_are_rejected_before_connecting():
    k = Knowledge("offline", embedding=False)
    with pytest.raises(ActionForbidden):
        k.put("a", "b", [], owner="writer")
    with pytest.raises(ActionForbidden):
        Knowledge("offline", writable=False).put("a", "b", [])
    assert k._driver is None


def test_provenance_normalization_and_namespace():
    k = Knowledge("p", embedding=False)
    assert k._provenance(["s", {"id": "s2", "locator": "page 7", "project_id": "p"}]) == [
        {"source_id": "s", "locator": ""}, {"source_id": "s2", "locator": "page 7"}]
    with pytest.raises(ActionForbidden):
        k.put("t", "b", [{"source_id": "s", "project_id": "other"}])
    with pytest.raises(ActionRejected):
        k.put("t", "b", [{"source_id": "s", "id": "different"}])
    with pytest.raises(ActionRejected):
        k.put("t", "b", "s")
    assert k._driver is None


@pytest.mark.parametrize("kwargs", [{"limit": 0}, {"limit": 101}, {"offset": -1},
                                     {"offset": True}, {"limit": 1.5}, {"mode": "invented"}])
def test_invalid_search_options_are_explicit(kwargs):
    with pytest.raises(ActionRejected):
        Knowledge("p", embedding=False).search("q", **kwargs)


def test_no_fake_vector_fallback():
    with pytest.raises(ActionRejected, match="EMBEDDING_DISABLED"):
        Knowledge("p", embedding=False)._vector("q")


def test_read_many_empty_is_lazy():
    k = Knowledge("offline", embedding=False, writable=False)
    assert k.read_many([]) == []
    assert k._driver is None


@pytest.mark.parametrize("ids", [None, "fact-id", {"id": "fact-id"}, [""], ["valid", None]])
def test_read_many_invalid_input_before_connecting(ids):
    k = Knowledge("offline", embedding=False)
    with pytest.raises(ActionRejected):
        k.read_many(ids)
    assert k._driver is None


@pytest.fixture
def graph():
    uri = os.environ.get("REPORT_GRAPH_TEST_URI")
    if not uri:
        pytest.skip("Set REPORT_GRAPH_TEST_URI to the dedicated prototype graph")
    project = "test-knowledge-" + str(uuid4())
    with Knowledge(project, uri=uri, embedding=False) as k:
        yield k


def test_real_graph_versions_receipts_and_provenance(graph):
    one = graph.put("Initial", "alpha full body", [{"source_id": "src-v1", "locator": "page 2"}], operation_id="create")
    assert graph.put("Initial", "alpha full body", [{"source_id": "src-v1", "locator": "page 2"}], operation_id="create")["reused"]
    assert graph.receipt("create")["id"] == one["id"]
    assert graph.read(one["id"])["provenance"][0]["locator"] == "page 2"
    with pytest.raises(ActionRejected, match="PAYLOAD_CONFLICT"):
        graph.put("Initial", "changed", [], operation_id="create")
    two = graph.put("Revision", "beta revised body", ["src-v2"], replaces_id=one["id"])
    assert two["revision"] == 2 and two["root_id"] == one["id"]
    assert graph.read(one["id"])["body"] == "alpha full body"
    assert graph.read(one["id"])["status"] == "superseded"
    assert not graph.read(one["id"])["current"]
    assert graph.read(one["id"])["replaced_by"] == two["id"]
    assert graph.read(two["id"])["current"]
    assert not graph.search("alpha", mode="text")["matches"]
    with pytest.raises(ActionRejected, match="ACTIVE_VERSION"):
        graph.put("Conflict", "competing replacement", [], replaces_id=one["id"])
    assert graph.retract(two["id"], reason="incorrect")["status"] == "retracted"
    assert graph.retract(two["id"], reason="incorrect")["reused"]
    assert graph.read(two["id"])["body"] == "beta revised body"
    assert not graph.read(two["id"])["current"]
    assert not graph.search("beta", mode="text")["matches"]


def test_real_graph_read_many_versions_order_and_single_session(graph):
    old = graph.put("Initial", "synthetic original", [{"source_id": "source-v1", "locator": "page 2"}])
    current = graph.put("Revised", "synthetic revised", ["source-v2"], replaces_id=old["id"])
    withdrawn = graph.put("Withdrawn", "synthetic withdrawn", [])
    graph.retract(withdrawn["id"], reason="synthetic correction")
    ids = [current["id"], old["id"], withdrawn["id"], current["id"]]
    with Knowledge(graph.project_id, graph.uri, embedding=False, producer="reader", writable=False) as reader:
        with patch.object(reader.driver, "session", wraps=reader.driver.session) as sessions:
            rows = reader.read_many(ids)
            assert sessions.call_count == 1
        assert not reader._schema_ready
    assert [row["id"] for row in rows] == ids
    assert [row["status"] for row in rows] == ["active", "superseded", "retracted", "active"]
    assert rows == [graph.read(id) for id in ids]
    assert rows[1]["replaced_by"] == current["id"]
    assert rows[1]["provenance"] == [{"source_id": "source-v1", "locator": "page 2"}]
    assert rows[0]["current"] and not rows[1]["current"] and not rows[2]["current"]


def test_real_graph_read_many_rejects_partial_missing_and_foreign(graph):
    local = graph.put("Local", "synthetic local fact", [])
    with Knowledge(graph.project_id + "-foreign", graph.uri, embedding=False) as other:
        foreign = other.put("Foreign", "synthetic foreign fact", [])
    for absent_id in ("nonexistent", foreign["id"]):
        with pytest.raises(ActionRejected, match="KNOWLEDGE_NOT_FOUND_IN_PROJECT") as failure:
            graph.read_many([local["id"], absent_id])
        assert absent_id in str(failure.value)
    assert graph.read(local["id"])["current"]


def test_real_graph_cross_project_and_producer_boundaries(graph):
    first = graph.put("visible", "isolated alpha", ["source"])
    with Knowledge(graph.project_id + "-other", graph.uri, embedding=False) as other:
        foreign = other.put("private", "isolated alpha secret", [])
        assert not other.search("visible", mode="text")["matches"]
        for action in (lambda: graph.read(foreign["id"]), lambda: graph.retract(foreign["id"]),
                       lambda: graph.put("t", "b", [], replaces_id=foreign["id"]),
                       lambda: graph.link(first["id"], foreign["id"], "refers_to"),
                       lambda: graph.traverse(foreign["id"])):
            with pytest.raises(ActionRejected, match="NOT_FOUND_IN_PROJECT"):
                action()
    with Knowledge(graph.project_id, graph.uri, embedding=False, producer="other-producer") as other_owner:
        for action in (lambda: other_owner.put("t", "b", [], owner="other-producer", replaces_id=first["id"]),
                       lambda: other_owner.retract(first["id"], owner="other-producer"),
                       lambda: other_owner.link(first["id"], first["id"], "ref", owner="other-producer")):
            with pytest.raises(ActionForbidden, match="ANOTHER_PRODUCER"):
                action()
        assert other_owner.read(first["id"])["id"] == first["id"]


def test_real_graph_links_traversal_and_text_paging(graph):
    nodes = [graph.put(f"common title {i}", f"common fact {i}", []) for i in range(4)]
    for n in nodes[1:]:
        one = graph.link(nodes[0]["id"], n["id"], "supports")
        assert graph.link(nodes[0]["id"], n["id"], "supports")["id"] == one["id"]
    first = graph.search("common", mode="text", limit=2)
    second = graph.search("common", mode="text", limit=2, offset=first["next_offset"])
    assert len(first["matches"]) == 2 and second["next_offset"] is None
    assert {m["id"] for m in first["matches"] + second["matches"]} == {n["id"] for n in nodes}
    paths = graph.traverse(nodes[0]["id"], limit=2)
    tail = graph.traverse(nodes[0]["id"], limit=2, offset=paths["next_offset"])
    assert len(paths["paths"]) == 2 and len(tail["paths"]) == 1
    assert paths["paths"][0]["relations"][0]["relation"] == "supports"
    graph.retract(nodes[1]["id"])
    assert len(graph.traverse(nodes[0]["id"])["paths"]) == 2


def test_real_graph_atomic_rollback(graph):
    def fail(tx):
        tx.run("CREATE (:RAFact {project_id:$project,id:'rolled-back'})", project=graph.project_id).consume()
        raise RuntimeError("injected failure before receipt")
    with pytest.raises(RuntimeError, match="injected failure"):
        graph._write("probe", {}, "failed-operation", fail)
    assert graph.receipt("failed-operation") is None
    with pytest.raises(ActionRejected):
        graph.read("rolled-back")


def test_real_graph_recovery_does_not_repeat_embedding(graph):
    one = graph.put("retry", "saved before response lost", [], operation_id="uncertain")
    class UnavailableEmbedding:
        model_id = "unavailable"
        dimensions = 384
        def embed_documents(self, _):
            raise RuntimeError("model unavailable")
    graph.embedding = UnavailableEmbedding()
    replay = graph.put("retry", "saved before response lost", [], operation_id="uncertain")
    assert replay["reused"] and replay["id"] == one["id"]


def test_real_graph_concurrent_duplicate_write(graph):
    graph._schema()
    def put(_):
        return graph.put("concurrent", "same operation", [], operation_id="concurrent")
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(put, range(2)))
    assert len({r["id"] for r in results}) == 1
    assert sum(not r["reused"] for r in results) == 1


def test_real_local_multilingual_vector_and_hybrid(graph):
    if os.environ.get("REPORT_TEST_EMBEDDINGS") != "1":
        pytest.skip("Set REPORT_TEST_EMBEDDINGS=1 for local model download/inference")
    graph.embedding = LocalEmbedding()
    # Chinese paraphrase, not exact text overlap; no hashing/mock embeddings.
    bridge = graph.put("\u6865\u6881\u517b\u62a4", "\u8de8\u6cb3\u6865\u7684\u6df7\u51dd\u571f\u8868\u9762\u51fa\u73b0\u88c2\u7f1d\uff0c\u9700\u8981\u4fee\u590d\u52a0\u56fa\u3002", ["synthetic-bridge"])
    graph.put("Lunch", "The restaurant serves noodles and fresh vegetables.", ["synthetic-menu"])
    query = "\u8fc7\u6cb3\u901a\u9053\u7ed3\u6784\u635f\u574f\u540e\u5982\u4f55\u68c0\u4fee"
    for mode in ("vector", "hybrid"):
        hits = graph.search(query, mode=mode, limit=1)
        assert hits["matches"][0]["id"] == bridge["id"]
        assert "vector" in hits["matches"][0]["scores"]
    assert graph.read(bridge["id"])["embedding_dimensions"] == 384
    with Knowledge(graph.project_id + "-private", graph.uri) as other:
        other.put(query, query, [])
    assert graph.search(query, mode="vector", limit=1)["matches"][0]["id"] == bridge["id"]
    graph.retract(bridge["id"])
    assert all(m["id"] != bridge["id"] for m in graph.search(query, mode="vector")["matches"])
