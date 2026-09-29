"""Real native graph with synthetic offline models; no claim of semantic quality."""
import json

import httpx
import pytest
from langchain_core.messages import AIMessage, ToolMessage

from report_agent import deep_runtime
from report_agent.acceptance import active_criteria, save_criteria, bind_mode
from report_agent.acceptance_review import GraderResponse
from report_agent.errors import ActionRejected
from report_agent.knowledge_state import project_state
from report_agent.store import Store
from report_agent.workspace import Workspace
from test_deep_runtime import Driver, invoke, call, observation


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    def denied(*a, **k):
        pytest.fail("Network forbidden in acceptance integration tests")
    monkeypatch.setattr(httpx.Client, "send", denied)
    monkeypatch.setattr(httpx.AsyncClient, "send", denied)
    store = Store(tmp_path)
    store.initialize({"goal": "Compile the source access restrictions, accurately and with citations.",
                      "sources": [{"id": "s", "title": "Access notice", "content": "Daytime access only.", "coverage": "complete"}]})
    return Workspace(store)


def standards(two=False):
    result = [{"requirement_refs": ["commission: source access restrictions"],
               "condition": "The adopted access restriction agrees with the source.",
               "scope": "Access recommendation", "evidence_expectation": "Locate supporting source statement.",
               "allowed_limitations": "Genuine uncertainty may remain explicitly attributed."}]
    if two:
        result.append({**result[0], "condition": "The report provides a locatable source citation."})
    return result


def save_standards(two=False):
    return invoke("save_acceptance_criteria", title="Access acceptance", criteria=standards(two),
                  source_ids=["s"], input_ids=[], reason="Derive outcomes from the commissioned purpose.")


def save_draft(ws, body="Daytime access only [s].", replaces=""):
    def action(messages):
        active = active_criteria(ws)
        assert active["id"] in str(messages[0].content)
        assert "Use each criterion's id verbatim as its criterion name" not in str(messages[0].content)
        return invoke("submit_result", title="Report", body=body, source_ids=["s"], input_ids=[],
                      criteria_id=active["id"], replaces_id=replaces() if callable(replaces) else replaces)
    return action


def select(messages):
    return invoke("select_delivery", draft_id=observation(messages, "submit_result")["id"])


def verdict(ws, statuses, names=None):
    criteria = active_criteria(ws)["criteria"]
    rows = []
    for i, status in enumerate(statuses):
        item = {"name": names[i] if names else criteria[i]["id"], "passed": status == "satisfied",
                "status": status, "evidence": [{"locator": "s", "observation": "Daytime access only."}],
                "explanation": "Synthetic observation; no real semantic model used.",
                "needed_outcome": "No change." if status == "satisfied" else "Explain or correct only the established issue."}
        if status != "satisfied":
            item["gap"] = "Unresolved verification." if status == "undetermined" else "Correct the access restriction."
        rows.append(item)
    result = "needs_revision" if "not_satisfied" in statuses else "undetermined" if "undetermined" in statuses else "satisfied"
    return AIMessage(content="", tool_calls=[call("GraderResponse", {"result": result,
                     "explanation": "Synthetic acceptance.", "criteria": rows})])


async def test_standards_before_draft_same_version_in_actual_native_grader(ws):
    def grade(messages):
        active = active_criteria(ws)
        text = str(messages)
        assert active["id"] in text and active["criteria"][0]["id"] in text
        assert "selected report" in str(messages[0].content)
        assert "every criterion you cannot positively confirm should be marked failed" not in text
        return verdict(ws, ["satisfied"])
    driver = Driver(coordinator=[save_standards(), save_draft(ws), select, AIMessage(content="Saved.")],
                    rubric_grader=[grade])
    result = await deep_runtime.run_report(ws, driver)
    assert result["last_error"] is None, result
    assert result["status"] == "reviewed_draft", result
    active = active_criteria(ws)
    draft = next(r for r in ws.results() if r["kind"] == "draft")
    assert active["id"] in draft["input_ids"]
    review = ws.store.get("rubric_reviews")[0]
    assert review["target"]["acceptance_criteria"]["criteria_id"] == active["id"]
    assert review["target"]["docx_sha256"]
    assert project_state(Workspace(Store(ws.store.root)))["status"] == "reviewed_draft"
    assert "reviewer" not in [role for role, _, _ in driver.calls]
    grader_tools = {t["name"] for t in driver.bindings["rubric_grader"][0]}
    assert {"analyze_text", "analyze_source_image", "calculate"} <= grader_tools
    assert "save_acceptance_criteria" not in grader_tools


async def test_delegated_author_gets_criteria_before_first_generation(ws):
    def deliver(messages):
        draft = next(r for r in ws.results() if r["kind"] == "draft")
        return invoke("select_delivery", draft_id=draft["id"])
    driver = Driver(coordinator=[save_standards(), invoke("task", subagent_type="writer",
                         description="Produce the source access report using the shared standards."),
                         deliver, AIMessage(content="Saved.")],
                    writer=[save_draft(ws), AIMessage(content="Draft saved.")],
                    rubric_grader=[lambda m: verdict(ws, ["satisfied"])])
    result = await deep_runtime.run_report(ws, driver)
    assert result["last_error"] is None, result
    assert result["status"] == "reviewed_draft", result
    assert len([r for r in ws.results() if r["kind"] == "acceptance"]) == 1
    assert len([r for r in ws.results() if r["kind"] == "draft"]) == 1


async def test_unknown_only_is_terminal_without_author_rewrite(ws):
    driver = Driver(coordinator=[save_standards(), save_draft(ws), select, AIMessage(content="Saved.")],
                    rubric_grader=[lambda m: verdict(ws, ["undetermined"])])
    result = await deep_runtime.run_report(ws, driver)
    assert result["last_error"] is None, result
    assert result["status"] == "needs_attention"
    assert result["delivery"]["acceptance_status"] == "undetermined"
    assert len([r for r in ws.results() if r["kind"] == "draft"]) == 1
    assert len(driver.calls) == 5
    record = ws.store.get("rubric_reviews")[0]
    assert record["result"] == "undetermined" and not record["unverified"]
    # A later explicit invocation can assess again, without erasing the old run.
    driver = Driver(coordinator=[*([AIMessage(content="unused")] * 4), AIMessage(content="Reassess saved draft.")],
                    rubric_grader=[lambda m: verdict(ws, ["satisfied"])])
    resumed = await deep_runtime.run_report(ws, driver)
    assert resumed["status"] == "reviewed_draft", resumed
    reviews = ws.store.get("rubric_reviews")
    assert len(reviews) == 2 and reviews[0]["grading_run_id"] != reviews[1]["grading_run_id"]


@pytest.mark.parametrize("bad_names", ["duplicate", "unknown", "omitted"])
async def test_exact_identity_coverage_uses_native_correction_retry(ws, bad_names):
    seen = []
    def grade(messages):
        seen.append(messages)
        ids = [c["id"] for c in active_criteria(ws)["criteria"]]
        if len(seen) == 1:
            names = [ids[0], ids[0]] if bad_names == "duplicate" else [ids[0], "invented"] if bad_names == "unknown" else [ids[0]]
            return verdict(ws, ["satisfied"] * len(names), names)
        assert "without replacements, omissions or duplicates" in str(messages)
        return verdict(ws, ["satisfied", "satisfied"])
    driver = Driver(coordinator=[save_standards(True), save_draft(ws), select, AIMessage(content="Saved.")], rubric_grader=[grade])
    result = await deep_runtime.run_report(ws, driver)
    assert result["last_error"] is None, result
    assert result["status"] == "reviewed_draft" and len(seen) == 2


async def test_repeated_incomplete_coverage_is_unverified_not_an_author_defect(ws):
    seen = []
    def grade(messages):
        seen.append(messages)
        return verdict(ws, ["satisfied"], ["invented_id"])
    driver = Driver(coordinator=[save_standards(True), save_draft(ws), select, AIMessage(content="Saved.")], rubric_grader=[grade])
    result = await deep_runtime.run_report(ws, driver)
    assert result["last_error"] is None, result
    assert result["status"] == "needs_attention" and len(seen) == 2
    record = ws.store.get("rubric_reviews")[0]
    assert record["result"] == "undetermined" and record["unverified"]
    assert "not evidence of a report defect" in record["explanation"]
    assert len([r for r in ws.results() if r["kind"] == "draft"]) == 1


async def test_changed_standards_start_new_native_run_and_do_not_relabel_old_draft(ws):
    observed = []
    def grade(messages):
        observed.append(active_criteria(ws)["id"])
        return verdict(ws, ["not_satisfied"] if len(observed) == 1 else ["satisfied"])
    def clarify(messages):
        old = active_criteria(ws)
        return invoke("save_acceptance_criteria", title="Clarified acceptance", criteria=old["criteria"],
                      source_ids=["s"], input_ids=[], replaces_id=old["id"],
                      reason="Clarify citation evidence within the unchanged commission.")
    def revised(messages):
        assert project_state(ws)["delivery"]["status"] == "needs_attention"
        draft = next(r for r in ws.results() if r["kind"] == "draft")
        return save_draft(ws, replaces=draft["id"])(messages)
    driver = Driver(coordinator=[save_standards(), save_draft(ws, "Anytime access."), select,
                                 AIMessage(content="Saved."), clarify, revised, select, AIMessage(content="Corrected.")],
                    rubric_grader=[grade])
    result = await deep_runtime.run_report(ws, driver)
    assert result["last_error"] is None, result
    assert result["status"] == "reviewed_draft", result
    reviews = ws.store.get("rubric_reviews")
    assert len(reviews) == 2 and reviews[0]["grading_run_id"] != reviews[1]["grading_run_id"]
    assert [r["iteration"] for r in reviews] == [0, 0]
    assert observed[0] != observed[1]
    assert reviews[0]["target"]["acceptance_criteria"]["criteria_id"] == observed[0]
    assert reviews[1]["target"]["acceptance_criteria"]["criteria_id"] == observed[1]


async def test_recovery_after_criteria_commit_keeps_one_version(ws):
    driver = Driver(coordinator=[save_standards(), save_draft(ws), select, AIMessage(content="Saved.")],
                    rubric_grader=[lambda m: verdict(ws, ["satisfied"])])
    driver.fail_once = ("coordinator", 1)
    first = await deep_runtime.run_report(ws, driver)
    assert first["status"] == "failed"
    identity = active_criteria(ws)["id"]
    resumed = await deep_runtime.run_report(Workspace(Store(ws.store.root)), driver)
    assert resumed["status"] == "reviewed_draft", resumed
    assert active_criteria(ws)["id"] == identity
    assert len([r for r in ws.results() if r["kind"] == "acceptance"]) == 1


async def test_missing_preconditions_expose_recoverable_limitation_without_grader(ws):
    first = await deep_runtime.run_report(ws, Driver(coordinator=[AIMessage(content="Finished.")]))
    assert first["status"] == "needs_attention" and first["last_error"] is None
    assert first["acceptance_limitation"]["reason"] == "SELECTED_DRAFT_REQUIRED_FOR_ACCEPTANCE"
    assert deep_runtime.project_view(ws)["acceptance_limitation"] == first["acceptance_limitation"]
    assert not ws.store.get("rubric_reviews")
    driver = Driver(coordinator=[AIMessage(content="unused"), save_standards(), save_draft(ws),
                                 select, AIMessage(content="Saved.")],
                    rubric_grader=[lambda m: verdict(ws, ["satisfied"])])
    resumed = await deep_runtime.run_report(ws, driver)
    assert resumed["status"] == "reviewed_draft", resumed
    assert not ws.store.get("acceptance_limitation")
    assert "acceptance_limitation" not in resumed


async def test_mixed_feedback_fixes_defect_and_preserves_unresolved_assessment(ws):
    calls = []
    def grade(messages):
        calls.append(messages)
        return verdict(ws, ["not_satisfied", "undetermined"] if len(calls) == 1 else ["satisfied", "undetermined"])
    def revise(messages):
        feedback = next(m.content for m in reversed(messages) if m.name == "rubric_grader")
        unknown_id = active_criteria(ws)["criteria"][1]["id"]
        assert unknown_id not in feedback.split("Public acceptance observations")[0]
        assert "unresolved verification" in feedback
        draft = next(r for r in ws.results() if r["kind"] == "draft")
        return save_draft(ws, replaces=draft["id"])(messages)
    driver = Driver(coordinator=[save_standards(True), save_draft(ws, "Anytime access."), select,
                                 AIMessage(content="Saved."), revise, select, AIMessage(content="Corrected.")],
                    rubric_grader=[grade])
    result = await deep_runtime.run_report(ws, driver)
    assert result["last_error"] is None, result
    assert result["status"] == "needs_attention"
    assert [r["result"] for r in ws.store.get("rubric_reviews")] == ["needs_revision", "undetermined"]
    assert len([r for r in ws.results() if r["kind"] == "draft"]) == 2


def test_ownership_binding_and_preproduction_requirements(ws):
    bind_mode(ws)
    tools = {t.__name__: t for t in deep_runtime.business_tools(ws, "writer", None, None)}
    assert "save_acceptance_criteria" not in tools
    with pytest.raises(ActionRejected):
        tools["submit_result"]("Draft", "Text", ["s"], [])
    first = save_criteria(ws, actor="coordinator", title="Acceptance", criteria=standards(),
                          source_ids=["s"], input_ids=[], reason="Original commission.")
    draft = tools["submit_result"]("Draft", "Text", ["s"], [], criteria_id=first["id"])
    second = save_criteria(ws, actor="coordinator", title="Acceptance clarified", criteria=standards(True),
                           source_ids=["s"], input_ids=[], reason="Clarify existing citation requirement.", replaces_id=first["id"])
    with pytest.raises(ActionRejected):
        tools["submit_result"]("Revised", "Text", ["s"], [], criteria_id=first["id"], replaces_id=draft["id"])
    replay = tools["submit_result"]("Draft", "Text", ["s"], [], criteria_id=first["id"])
    assert replay["id"] == draft["id"]  # Historical write receipt remains recoverable.
    assert second["id"] != first["id"]


@pytest.mark.parametrize("statuses,result", [(["undetermined"], "satisfied"), (["undetermined"], "needs_revision"), (["not_satisfied"], "undetermined")])
def test_domain_status_cannot_be_confused_with_pass_or_revision(ws, statuses, result):
    bind_mode(ws)
    save_criteria(ws, actor="coordinator", title="Acceptance", criteria=standards(),
                  source_ids=["s"], input_ids=[], reason="Commission.")
    data = verdict(ws, statuses).tool_calls[0]["args"]
    data["result"] = result
    with pytest.raises(ValueError):
        GraderResponse.model_validate(data)
