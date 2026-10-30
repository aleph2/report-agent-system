"""Offline wiring evidence, not autonomous learning or report-quality evidence."""
import httpx
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from report_agent.errors import ActionRejected
from report_agent.hierarchical_tools import actor_for
from report_agent.learning import binding, guidance_context, report_tools
from report_agent.learning_worker import consume_pending
from report_agent.store import Store
from report_agent.webapp import create_app
from report_agent.workspace import Workspace
from test_deep_runtime import Driver, invoke, observation
from test_hierarchical_content import seed


@pytest.mark.asyncio
async def test_feedback_candidate_release_reuse_and_withdrawal(tmp_path, monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("External network is forbidden in this test")

    # TestClient uses ASGITransport; intercept only real HTTP transports.
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", no_network)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", no_network)
    projects = []
    for name, customer in (("first", "a"), ("next", "a"), ("foreign", "b")):
        ws = Workspace(Store(tmp_path / name))
        ws.store.initialize({"goal": "Synthetic report", "content_contract": "hierarchical-review-v1",
            "sources": [{"id": "s", "title": "Rule", "content": "Class B permits 75 to 100.",
                         "coverage": "complete"}]})
        ws.store.set("learning_config", {"library_path": str(tmp_path / "library"), "customer_id": customer})
        projects.append(ws)
    first, next_project, foreign = projects
    cs, _, refs, snapshot, _ = seed(first)
    before = cs.read(refs["claim"])
    headers = {"x-report-action": "1"}
    with TestClient(create_app(first.store.root)) as client:
        body = dict(snapshot_ref=snapshot, target_ref=refs["claim"],
                    correction="Include the adopted condition next to each value.", evidence_refs=[refs["evidence"]])
        response = client.post("/api/learning/feedback", json=body, headers=headers)
        assert response.status_code == 201
        feedback = response.json()
        assert client.post("/api/learning/feedback", json=body, headers=headers).json()["id"] == feedback["id"]

        def disposition(messages):
            candidate = observation(messages, "propose_experience")
            return invoke("record_feedback_disposition", feedback_id=feedback["id"], outcome="candidate",
                          rationale="Synthetic preference fixture", experience_id=candidate["id"],
                          experience_version=candidate["version"])

        driver = Driver(optimizer=[
            invoke("propose_experience", feedback_ids=[feedback["id"]], kind="customer_preference",
                   title="Show adopted conditions", strategy=body["correction"],
                   conditions="Same customer reports", verification="Inspect the generated values and conditions"),
            disposition, AIMessage(content="Candidate saved; quality unverified.")])
        result = await consume_pending(first, lambda: driver("optimizer"), max_steps=10)
        assert result["state"] == "completed"
        library, scope = binding(first)
        candidate, = library.list_versions(scope)
        assert candidate["feedback_ids"] == [feedback["id"]]
        assert not library.search(scope)
        def assert_no_released_candidate(project):
            context = guidance_context(project)
            assert not (context or {}).get('customer_preferences', [])
            assert not (context or {}).get('available_experience', [])
            assert candidate['id'] not in str(context)
            assert body['correction'] not in str(context)
        assert_no_released_candidate(next_project)
        # Learning alone neither repairs the report nor reopens its execution.
        assert cs.read(refs["claim"]) == before
        assert not first.store.get("feedback", [])
        url = f"/api/learning/experience/{candidate['id']}/release"
        assert client.post(url, json={"version": 1, "reason": "Synthetic operator approval"}, headers=headers).status_code == 200
        assert body["correction"] in str(guidance_context(next_project))
        assert_no_released_candidate(foreign)
        _, _, next_refs, _, _ = seed(next_project)
        tools = {tool.__name__: tool for tool in report_tools(next_project, lambda: actor_for("writer"))}
        assert tools["search_experience"]()["items"][0]["id"] == candidate["id"]
        receipt = tools["record_experience_use"](candidate["id"], 1, next_refs["claim"], "Synthetic use declaration")
        assert receipt["experience"]["version"] == 1
        assert client.post(url, json={"version": None, "reason": "Synthetic withdrawal"}, headers=headers).status_code == 200
        assert_no_released_candidate(next_project)
        assert tools["search_experience"]()["items"] == []
        with pytest.raises(ActionRejected, match="NOT_ACTIVE"):
            tools["record_experience_use"](candidate["id"], 1, next_refs["claim"], "Stale cached candidate")

    def no_model():
        raise AssertionError("Completed duplicate feedback must not run another model")

    assert (await consume_pending(first, no_model))["state"] == "idle"
