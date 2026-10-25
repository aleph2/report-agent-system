from report_agent.knowledge_state import delivery_state, inspect_evidence, project_state


class Workspace:
    def __init__(self, ids):
        self.ids = ids

    def collect_fact_ids(self, results):
        return self.ids

    def delivery(self, draft, review=""):
        return {"draft_id": draft, "review_id": review or "r", "status": "reviewed_draft"}

    def status(self):
        return {"delivery": self.delivery("d"), "status": "reviewed_draft", "last_error": None}


class Knowledge:
    def __init__(self, current=True, error=False):
        self.current, self.error, self.calls = current, error, []

    def read_many(self, ids):
        self.calls.append(ids)
        if self.error:
            raise ConnectionError("private endpoint must not escape")
        return [{"id": i, "current": self.current, "provenance": []} for i in ids]


def test_without_graph_refs_does_not_connect():
    graph = Knowledge(error=True)
    assert inspect_evidence(Workspace([]), ["d"], graph)["status"] == "not_used"
    assert graph.calls == []


def test_adopted_versions_batch_check_preserves_review():
    graph = Knowledge()
    state, evidence = delivery_state(Workspace(["f1", "f2"]), "d", knowledge=graph)
    assert state["status"] == "reviewed_draft"
    assert evidence["status"] == "current"
    assert graph.calls == [["f1", "f2"]]


def test_changed_versions_need_assessment_not_forced_rewrite():
    state, evidence = delivery_state(Workspace(["f"]), "d", knowledge=Knowledge(current=False))
    assert state["status"] == "needs_attention"
    assert state["review_id"] == "r"
    assert evidence["changed_fact_ids"] == ["f"]


def test_graph_failure_is_unknown_system_failure_not_missing_source():
    state = project_state(Workspace(["f"]), Knowledge(error=True))
    assert state["status"] == "system_error"
    assert state["delivery"]["knowledge"]["status"] == "unknown"
    assert state["last_error"]["message"] == "KNOWLEDGE_VALIDITY_CHECK_FAILED"
    assert "private" not in str(state)
