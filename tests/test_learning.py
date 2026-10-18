"""Offline boundary and version tests, not evidence of model learning quality."""
import pytest

from report_agent.errors import ActionRejected
from report_agent.learning import LearningLibrary, LearningScope
from report_agent.learning_runtime import evaluate_strategy_pair, optimize_with_gepa


@pytest.fixture
def library(tmp_path):
    return LearningLibrary(tmp_path / "learning")


def proposal(library, scope, kind="customer_preference", **kwargs):
    f = library.feedback(scope, {"id": "snapshot", "version": 1}, {"id": "table", "version": 1},
                         "Use customer table format", "old format", [{"id": "style", "version": 1}])
    return library.propose(scope, [f["id"]], kind, "Table format", "Use the specified format",
                           "This customer's requested tables", "Compare exported tables", **kwargs)


def test_candidate_release_cross_project_isolation_and_revoke(library):
    a, b, other = LearningScope("customer-a", "one"), LearningScope("customer-a", "two"), LearningScope("customer-b", "one")
    candidate = proposal(library, a)
    assert not library.search(a)
    library.release(a, candidate["id"], 1, "Operator checked preference")
    assert library.search(b)[0]["id"] == candidate["id"]
    assert not library.search(other)
    with pytest.raises(ActionRejected):
        library.use(other, candidate["id"], 1, {}, "use", "writer")
    library.use(b, candidate["id"], 1, {}, "Customer matches", "writer")
    library.release(a, candidate["id"], None, "Customer revoked")
    assert not library.search(b)
    with pytest.raises(ActionRejected, match="NOT_ACTIVE"):
        library.use(b, candidate["id"], 1, {}, "cached", "writer")


def test_project_fact_never_shared_and_scope_cannot_expand(library):
    a, b = LearningScope("customer", "one"), LearningScope("customer", "two")
    fact = proposal(library, a, "project_fact")
    library.release(a, fact["id"], 1, "Confirmed project fact")
    assert not library.search(b)
    with pytest.raises(ActionRejected, match="SCOPE_IMMUTABLE"):
        proposal(library, a, "general_skill", experience_id=fact["id"], expected_version=1)
    with pytest.raises(ActionRejected):
        library.release(b, fact["id"], None, "attempt")


def test_revision_does_not_publish_and_rollback_is_explicit(library):
    scope = LearningScope("customer", "one")
    first = proposal(library, scope)
    library.release(scope, first["id"], 1, "Publish")
    proposal(library, scope, experience_id=first["id"], expected_version=1)
    assert library.search(scope)[0]["version"] == 1
    with pytest.raises(ActionRejected, match="VERSION_CONFLICT"):
        proposal(library, scope, experience_id=first["id"], expected_version=1)
    library.release(scope, first["id"], 2, "Approve new revision")
    library.release(scope, first["id"], 1, "Regression; roll back")
    assert [x["version"] for x in library.list_versions(scope)] == [1, 2]
    assert library.search(scope)[0]["version"] == 1


def test_feedback_identity_cannot_cross_scope(library):
    a, b = LearningScope("a", "one"), LearningScope("b", "one")
    item = proposal(library, a)
    with pytest.raises(ActionRejected, match="FEEDBACK_OUTSIDE_PROJECT"):
        library.propose(b, item["feedback_ids"], "general_skill", "Title", "Strategy", "Scope", "Check")


def test_evaluation_reports_regression_without_releasing():
    cases = [{"id": "holdout-a"}, {"id": "holdout-b"}]
    def evaluator(strategy, case):
        return {"score": 0 if strategy == "new" and case["id"] == "holdout-b" else 1,
                "feedback": "synthetic only"}
    result = evaluate_strategy_pair("old", "new", cases, evaluator)
    assert result["regressions"] == ["holdout-b"]
    assert result["automatic_release"] is False


def test_gepa_rejects_train_validation_leakage_before_import_or_calls():
    with pytest.raises(ValueError, match="SPLIT_INVALID"):
        optimize_with_gepa(None, [{"case_id": "same"}], [{"case_id": "same"}], None, None, max_metric_calls=10)


def test_snapshot_bound_feedback_and_local_api(tmp_path):
    from fastapi.testclient import TestClient
    from report_agent.store import Store
    from report_agent.workspace import Workspace
    from report_agent.learning import submit_feedback
    from report_agent.webapp import create_app
    from test_hierarchical_content import seed
    ws = Workspace(Store(tmp_path / "project"))
    ws.store.initialize({"goal": "Test", "content_contract": "hierarchical-review-v1", "sources": [
        {"id": "s", "title": "Rule", "content": "Class B permits 75 to 100.", "coverage": "complete"}]})
    ws.store.set("learning_config", {"library_path": str(tmp_path / "library"), "customer_id": "a"})
    cs, _, refs, snapshot, _ = seed(ws)
    body = dict(snapshot_ref=snapshot, target_ref=refs["claim"], correction="Check adopted class",
                evidence_refs=[refs["evidence"]])
    item = submit_feedback(ws, **body)
    assert item["before"] == cs.read(refs["claim"])["payload"]
    client = TestClient(create_app(ws.store.root))
    assert "no-cache" in client.get("/").headers["cache-control"]
    assert "no-cache" in client.get("/static/learning.js").headers["cache-control"]
    reports = client.get("/api/learning/reports").json()["reports"]
    selected = next(r for r in reports if r["ref"] == snapshot)
    evidence = client.get("/api/learning/evidence").json()["items"]
    assert any(e["ref"] == refs["evidence"] for e in evidence)
    assert all(e["ref"]["type"] in {"Evidence", "SourceArtifact"} for e in evidence)
    assert all(len(e["excerpt"]) <= 1200 for e in evidence)
    assert any(t["ref"] == refs["claim"] and t["payload"] == item["before"] for t in selected["targets"])
    assert len({str(t["ref"]) for t in selected["targets"]}) == len(selected["targets"])
    assert client.post("/api/learning/feedback", json=body).status_code == 403
    assert client.post("/api/learning/feedback", json=body, headers={"x-report-action": "1"}).status_code == 201
    assert len(client.get("/api/learning").json()["feedback"]) == 1  # Same payload is idempotent.
    assert client.get("/api/learning").json()["feedback"][0]["evidence"] == [refs["evidence"]]
    from report_agent.learning import binding
    library, scope = binding(ws)
    candidate = library.propose(scope, [item["id"]], "customer_preference", "Title", "Original", "Scope", "Check")
    library.release(scope, candidate["id"], 1, "Approved original")
    revision = dict(expected_version=1, title="Edited", strategy="Revised", conditions="Scope", verification="Check")
    url = f"/api/learning/experience/{candidate['id']}/revision"
    assert client.post(url, json=revision).status_code == 403
    assert client.post(url, json=revision, headers={"x-report-action": "1"}).status_code == 201
    assert library.search(scope)[0]["strategy"] == "Original"  # Editing does not publish.
    assert client.post(url, json=revision, headers={"x-report-action": "1"}).status_code == 409


def test_optimizer_has_no_publication_or_report_write_tools(tmp_path):
    from report_agent.store import Store
    from report_agent.workspace import Workspace
    from report_agent.learning_runtime import optimizer_tools
    ws = Workspace(Store(tmp_path / "project"))
    ws.store.set("learning_config", {"library_path": str(tmp_path / "library"), "customer_id": "a"})
    assert {t.__name__ for t in optimizer_tools(ws)} == {
        "read_learning_feedback", "read_learning_evidence", "read_experience_candidates", "propose_experience", "record_feedback_disposition"}


@pytest.mark.asyncio
async def test_actual_background_graph_saves_candidate_without_publishing(tmp_path):
    from report_agent.store import Store
    from report_agent.workspace import Workspace
    from report_agent.learning import binding
    from report_agent.learning_runtime import run_optimizer
    from test_deep_runtime import Driver, invoke
    from langchain_core.messages import AIMessage
    ws = Workspace(Store(tmp_path / "project"))
    ws.store.set("learning_config", {"library_path": str(tmp_path / "library"), "customer_id": "a"})
    library, scope = binding(ws)
    f = library.feedback(scope, {}, {}, "Prefer narrow table", "wide", [{"id": "source"}])
    driver = Driver(optimizer=[invoke("propose_experience", feedback_ids=[f["id"]],
        kind="customer_preference", title="Table", strategy="Use requested format",
        conditions="Customer tables", verification="Inspect export"), AIMessage(content="Candidate saved.")])
    await run_optimizer(ws, driver("optimizer"), max_steps=10)
    assert len(library.list_versions(scope)) == 1
    assert not library.search(scope)
    names = {t["name"] for batch in driver.bindings["optimizer"] for t in batch}
    assert not names & {"execute", "task", "release", "commit_objects"}
    assert names == {"read_learning_feedback", "read_learning_evidence",
                     "read_experience_candidates", "propose_experience", "record_feedback_disposition", "analyze_learning_material"}
    propose = next(t for batch in driver.bindings["optimizer"] for t in batch if t['name'] == 'propose_experience')
    assert set(propose['parameters']['properties']['kind']['enum']) == {
        'project_fact', 'customer_preference', 'general_skill'}


def test_report_tools_apply_shared_preference_and_reject_revoked_version(tmp_path):
    from report_agent.store import Store
    from report_agent.workspace import Workspace
    from report_agent.learning import binding, report_tools
    from report_agent.hierarchical_tools import actor_for, content_tools
    from test_hierarchical_content import seed
    projects = []
    for name in ("first", "next"):
        ws = Workspace(Store(tmp_path / name))
        ws.store.initialize({"goal": "Test", "content_contract": "hierarchical-review-v1", "sources": [
            {"id": "s", "title": "Rule", "content": "Class B permits 75 to 100.", "coverage": "complete"}]})
        ws.store.set("learning_config", {"library_path": str(tmp_path / "shared"), "customer_id": "a"})
        projects.append(ws)
    library, first = binding(projects[0])
    candidate = proposal(library, first)
    library.release(first, candidate["id"], 1, "Confirmed format preference")
    _, _, refs, _, _ = seed(projects[1])
    tools = {t.__name__: t for t in report_tools(projects[1], lambda: actor_for("writer"))}
    assert tools["search_experience"]("Table")["items"][0]["id"] == candidate["id"]
    miss = tools["search_experience"]("Table format with words not present")
    assert miss["items"] == [] and miss["match_mode"] == "exact_substring"
    assert "empty query" in miss["hint"]
    assert tools["search_experience"]()["items"][0]["id"] == candidate["id"]
    result = tools["record_experience_use"](candidate["id"], 1, refs["claim"], "Same customer requirement")
    assert result["experience"]["version"] == 1
    assert "search_experience" in {t.__name__ for t in content_tools(projects[1], "writer")}
    library.release(first, candidate["id"], None, "Withdraw")
    with pytest.raises(ActionRejected, match="NOT_ACTIVE"):
        tools["record_experience_use"](candidate["id"], 1, refs["claim"], "stale cached version")


def test_identifier_lookup_does_not_resolve_mentions_or_unreleased_foreign_items(tmp_path):
    from report_agent.store import Store
    from report_agent.workspace import Workspace
    from report_agent.learning import binding, report_tools, LearningScope
    ws=Workspace(Store(tmp_path/'lookup'))
    ws.store.set('learning_config',{'library_path':str(tmp_path/'library'),'customer_id':'a'})
    library,scope=binding(ws)
    feedback=library.feedback(scope,{}, {},'Synthetic identity ambiguity',{},[{'synthetic':True}])
    prefix='82cb68e7'
    parent=library.propose(scope,[feedback['id']],'customer_preference','Parent',
        'Refines candidate '+prefix,'Same customer','Check actual writing')
    library.release(scope,parent['id'],1,'Synthetic fixture release')
    tools={t.__name__:t for t in report_tools(ws,lambda:None)}
    text=tools['search_experience'](prefix)
    assert text['items'][0]['id']==parent['id']
    assert text['match_details'][0]['matched_fields']==['strategy']
    miss=tools['search_experience'](prefix,match_mode='identifier')
    assert not miss['items'] and 'historical' in miss['hint']
    child=library.propose(scope,[feedback['id']],'customer_preference','Child','Independent guidance',
        'Same customer','Check actual writing',experience_id=prefix+'-0000-0000-0000-000000000000')
    assert not tools['search_experience'](prefix,match_mode='identifier')['items']
    library.release(scope,child['id'],1,'Synthetic child release')
    resolved=tools['search_experience'](prefix,match_mode='identifier')
    assert [r['id'] for r in resolved['items']]==[child['id']]
    assert resolved['match_details'][0]['matched_fields']==['id']
    other=LearningScope('other',str(tmp_path/'foreign'))
    assert not library.search(other,child['id'],match_mode='identifier')
    library.release(scope,child['id'],None,'Withdraw synthetic fixture')
    assert not tools['search_experience'](child['id'],match_mode='identifier')['items']
    with pytest.raises(ActionRejected,match='IDENTIFIER_REQUIRED'):
        tools['search_experience']('',match_mode='identifier')
    with pytest.raises(ActionRejected,match='INVALID_EXPERIENCE_MATCH_MODE'):
        library.search(scope,'anything',match_mode='unsupported')


def test_learning_reference_tools_preserve_structured_refs_on_strict_wire(tmp_path):
    from langchain_core.tools import StructuredTool
    from langchain_core.utils.function_calling import convert_to_openai_tool
    from report_agent.deepseek_strict import StrictCodec
    from report_agent.learning_runtime import optimizer_tools
    from report_agent.learning import report_tools
    from report_agent.store import Store
    from report_agent.workspace import Workspace
    ws = Workspace(Store(tmp_path / 'project'))
    ws.store.set('learning_config', {'library_path': str(tmp_path / 'library'), 'customer_id': 'a'})
    ref = {'type': 'Evidence', 'id': 'saved-object', 'version': 1}
    for tool in optimizer_tools(ws) + report_tools(ws, lambda: None):
        if tool.__name__ not in {'read_learning_evidence', 'record_experience_use'}:
            continue
        codec = StrictCodec(convert_to_openai_tool(StructuredTool.from_function(tool))['function'])
        args = {'ref': ref} if tool.__name__ == 'read_learning_evidence' else {
            'experience_id': 'candidate', 'version': 1, 'target_ref': ref, 'reason': 'Applicable'}
        wire = codec.encode(args)
        ref_key = 'ref' if tool.__name__ == 'read_learning_evidence' else 'target_ref'
        assert wire[ref_key] == ref
        assert codec.decode(wire) == args
