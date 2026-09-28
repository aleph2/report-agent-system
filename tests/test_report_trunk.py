import json
from pathlib import Path
from typing import Any

import pytest
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types
from pydantic import Field

from report_agent.store import Store
from report_agent.workspace import Workspace
from report_agent.report_runtime import run_report, worker_tools


def workspace(tmp_path):
    manifest = json.loads((Path(__file__).parents[1] / "examples/materials-reuse.json").read_text())
    manifest["document_uses"] = {"brief": "Scope", "access": "Facts", "notice": "Limits"}
    store = Store(tmp_path)
    store.initialize(manifest)
    result = Workspace(store)
    result.initialize()
    return result


def save(ws, kind, inputs=None, **kwargs):
    task = ws.request_task(kind, "Synthetic " + kind, inputs or [])
    ws.record_read(task["id"], result_ids=inputs or [])
    return ws.submit(task["id"], actor=task["owner"], title="Synthetic " + kind,
                     body="Protocol fixture [access].", source_ids=["access"], input_ids=[], **kwargs)


def baseline(ws):
    purpose = next(r for r in ws.results() if r["kind"] == "purpose")
    material = next(r for r in ws.results() if r["kind"] == "materials")
    plan = save(ws, "plan", [purpose["id"]])
    draft = save(ws, "draft", [plan["id"], material["id"]])
    return draft


def test_no_automatic_roster_and_operator_purpose_reuse(tmp_path):
    ws = workspace(tmp_path)
    assert not ws.tasks()
    assert {r["kind"] for r in ws.results()} == {"purpose", "materials"}
    old = ws.results()
    ws.initialize()
    assert ws.results() == old


def test_permissions_and_project_reference_boundaries(tmp_path):
    ws = workspace(tmp_path / "one")
    other = workspace(tmp_path / "two")
    task = ws.request_task("draft", "Write report", [])
    with pytest.raises(PermissionError, match="OWNER"):
        ws.submit(task["id"], actor="materials", title="Overwrite", body="Wrong", source_ids=[], input_ids=[])
    with pytest.raises(ValueError, match="RESULT_NOT_IN_PROJECT"):
        ws.request_task("draft", "Foreign", [other.results()[0]["id"]])
    with pytest.raises(ValueError, match="INVALID_TASK"):
        ws.request_task("administrator", "Grant me SQL", [])
    tools = worker_tools(ws, task["id"], None)
    assert not {"request_task", "run_requested_task", "select_delivery"} & {t.__name__ for t in tools}
    assert {r["kind"] for r in ws.results()} == {"purpose", "materials"}


def test_plan_can_adopt_raw_sources_without_a_purpose_artifact(tmp_path):
    ws = workspace(tmp_path)
    result = save(ws, "plan")
    assert result["kind"] == "plan"
    assert result["input_ids"] == [] and result["source_ids"] == ["access"]
    assert not any(t["kind"] == "purpose" for t in ws.tasks())


def test_commit_recovery_and_exact_version_review(tmp_path):
    ws = workspace(tmp_path)
    draft = baseline(ws)
    review = save(ws, "review", [draft["id"]], target_id=draft["id"], outcome="accepted")
    assert ws.select_delivery(draft["id"], review["id"])["status"] == "reviewed_draft"
    new_task = ws.request_task("draft", "Revise synthetic report", draft["input_ids"] + [draft["id"]])
    ws.record_read(new_task["id"], result_ids=new_task["input_ids"])
    new_draft = ws.submit(new_task["id"], actor="writer", title="Revised", body="Updated [access]",
                          source_ids=["access"], input_ids=[])
    with pytest.raises(ValueError, match="VERSION_MISMATCH"):
        ws.select_delivery(new_draft["id"], review["id"])
    assert ws.delivery(new_draft["id"])["status"] == "unreviewed_draft"
    reopened = Workspace(Store(tmp_path))
    assert reopened.task(new_task["id"])["result_id"] == new_draft["id"]
    again = reopened.submit(new_task["id"], actor="writer", title="Revised", body="Updated [access]",
                             source_ids=["access"], input_ids=[])
    assert again["id"] == new_draft["id"]


def test_issue_and_correction_do_not_mutate_upstream(tmp_path):
    ws = workspace(tmp_path)
    draft = baseline(ws)
    before = ws.results()
    ws.request_correction(before[0]["id"], "Check the purpose of this source")
    issue = ws.issue("source_conflict", "Two arrangements conflict", ["access"])
    ws.decide_issue(issue["id"], "Use the source version explicitly dated for this scope.")
    assert ws.results() == before
    assert not ws.status()["issues"][0]["resolved"]
    assert ws.status()["issues"][0]["decision_origin"] == "operator"
    review = save(ws, "review", [draft["id"]], outcome="accepted", target_id=draft["id"])
    assert ws.delivery(draft["id"], review["id"])["status"] == "needs_human"


class ProtocolModel(BaseLlm):
    """Offline ADK protocol fixture, deliberately NOT an autonomous model evaluation."""
    model: str = "scripted-report-fixture"
    ws: Any = Field(exclude=True)
    task_id: str = "report"
    script: list[str] = Field(default_factory=list)
    position: int = 0

    async def generate_content_async(self, llm_request, stream=False):
        action = self.script[self.position]
        self.position += 1
        if action == "fail":
            raise RuntimeError("SYNTHETIC_HTTP_FAILURE")
        if action == "final":
            yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text="Protocol fixture done.")]))
            return
        results = self.ws.results()
        if action.startswith("request_"):
            kind = action.removeprefix("request_")
            required = {"plan": {"purpose"}, "draft": {"plan", "materials"}, "review": {"draft"}}[kind]
            name, args = "request_task", {"kind": kind, "goal": "Synthetic " + kind,
                                           "input_ids": [r["id"] for r in results if r["kind"] in required]}
        elif action == "run_last":
            name, args = "run_requested_task", {"task_id": self.ws.tasks()[-1]["id"]}
        elif action == "select":
            name, args = "select_delivery", {"draft_id": next(r["id"] for r in results if r["kind"] == "draft"),
                                              "review_id": next(r["id"] for r in results if r["kind"] == "review")}
        elif action == "read":
            name, args = "read_sources", {"source_ids": ["access", "brief", "notice"]}
        elif action == "submit":
            task = self.ws.task(self.task_id)
            name = "submit_result"
            args = {"title": "Cedar synthetic " + task["kind"], "body": "# Access arrangements\n\nEast footpath, 08:00-17:00 during maintenance week [access].\n\nNo night-time route is established [notice].",
                    "source_ids": ["access", "notice"], "input_ids": []}
            if task["kind"] == "review":
                args.update(outcome="accepted", target_id=task["input_ids"][0])
        else:
            raise AssertionError(action)
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(
            function_call=types.FunctionCall(name=name, args=args))]))


class ModelFactory:
    def __init__(self, ws, coordinator_script=None, fail_draft=False):
        self.ws = ws
        self.created = []
        self.fail_draft = fail_draft
        self.script = coordinator_script or ["request_plan", "run_last", "request_draft", "run_last",
                                             "request_review", "run_last", "select", "final"]

    def __call__(self, kind, task_id):
        self.created.append((kind, task_id))
        script = self.script if kind == "coordinator" else ["read", "submit", "final"]
        if kind == "draft" and self.fail_draft:
            script = ["fail"]
        return ProtocolModel(ws=self.ws, task_id=task_id, script=script)


async def test_report_protocol_trunk_and_completed_reuse(tmp_path):
    ws = workspace(tmp_path)
    factory = ModelFactory(ws)
    result = await run_report(ws, factory)
    assert result["status"] == "reviewed_draft"
    assert [t["kind"] for t in result["tasks"]] == ["plan", "draft", "review"]
    assert all(t["status"] == "completed" for t in result["tasks"])
    assert not any(k in {"purpose", "materials"} for k, _ in factory.created)
    previous = list(factory.created)
    await run_report(ws, factory)
    assert factory.created == previous


async def test_report_resumes_failed_task_without_regenerating_completed_plan(tmp_path):
    ws = workspace(tmp_path)
    first = ModelFactory(ws, ["request_plan", "run_last", "request_draft", "run_last", "final"], fail_draft=True)
    failed = await run_report(ws, first)
    assert failed["tasks"][-1]["status"] == "failed"
    assert failed["tasks"][-1]["error"]["message"] == "SYNTHETIC_HTTP_FAILURE"
    plan_id = next(r["id"] for r in ws.results() if r["kind"] == "plan")
    second = ModelFactory(ws)
    result = await run_report(ws, second)
    assert result["status"] == "reviewed_draft"
    assert next(r["id"] for r in ws.results() if r["kind"] == "plan") == plan_id
    assert not any(k == "plan" for k, _ in second.created)


async def test_configuration_failure_visible_without_paid_request(tmp_path, monkeypatch):
    monkeypatch.delenv("REPORT_MODEL", raising=False)
    status = await run_report(workspace(tmp_path))
    assert status["status"] == "failed"
    assert status["last_error"]["message"] == "REPORT_MODEL_BASE_URL_AND_API_KEY_REQUIRED"


def test_human_change_is_visible_without_invalidating_exact_review(tmp_path):
    ws = workspace(tmp_path)
    draft = baseline(ws)
    review = save(ws, "review", [draft["id"]], outcome="accepted", target_id=draft["id"])
    ws.select_delivery(draft["id"], review["id"])
    issue = ws.issue("source_missing", "Missing timing", ["access"])
    assert ws.status()["status"] == "needs_human"
    ws.decide_issue(issue["id"], "Operator confirmed daytime scope", resolved=True)
    revision = ws.store.get("context_revision")
    ws.decide_issue(issue["id"], "Operator confirmed daytime scope", resolved=True)
    assert ws.store.get("context_revision") == revision
    delivery = ws.status()["delivery"]
    assert delivery["status"] == "reviewed_draft"
    assert delivery["changes"]["context_revision"] == revision
    assert delivery["changes"]["review_context_revision"] == review["context_revision"]
    assert revision != review["context_revision"]
    updated = save(ws, "review", [draft["id"]], outcome="accepted", target_id=draft["id"])
    assert updated["id"] != review["id"]
    assert ws.select_delivery(draft["id"], updated["id"])["status"] == "reviewed_draft"


async def test_exact_repetition_stops_without_a_total_call_quota(tmp_path):
    ws = workspace(tmp_path)
    factory = ModelFactory(ws, ["request_plan"] * 8)
    status = await run_report(ws, factory)
    assert status["status"] == "failed"
    assert status["last_error"]["message"] == "REPEATED_ACTION_WITHOUT_STATE_PROGRESS"
    assert len(ws.tasks()) == 1


def test_adoption_is_explicit_but_exact_review_target_must_be_observed(tmp_path):
    ws = workspace(tmp_path)
    purpose = next(r for r in ws.results() if r["kind"] == "purpose")
    task = ws.request_task("plan", "Ground this plan", [])
    plan = ws.submit(task["id"], actor="planner", title="Plan", body="Body", source_ids=[], input_ids=[purpose["id"]])
    assert plan["input_ids"] == [purpose["id"]] and plan["observed_result_ids"] == []
    draft = baseline(ws)
    task = ws.request_task("review", "Read before reviewing", [])
    with pytest.raises(ValueError, match="TARGET_NOT_OBSERVED"):
        ws.submit(task["id"], actor="reviewer", title="Review", body="Body", source_ids=[],
                  input_ids=[draft["id"]], target_id=draft["id"], outcome="accepted")


def test_human_decision_revision_and_receipt_rollback_together(tmp_path):
    import sqlite3
    ws = workspace(tmp_path)
    issue = ws.issue("source_conflict", "Conflicting timing", ["access"])
    ws.decide_issue(issue["id"], "Earlier decision", resolved=True)
    before = ws.status()
    revision = ws.store.get("context_revision")
    with ws.store.connect() as db:
        db.execute("""CREATE TRIGGER simulate_commit_failure BEFORE INSERT ON events
                      WHEN NEW.kind='human_decision' BEGIN SELECT RAISE(ABORT, 'simulated'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="simulated"):
        ws.decide_issue(issue["id"], "Changed decision", resolved=True)
    assert ws.status() == before
    assert ws.store.get("context_revision") == revision


def test_new_review_is_effective_everywhere_and_system_failure_is_not_missing_data(tmp_path):
    from io import BytesIO
    from docx import Document
    from report_agent.exporting import export_docx
    ws = workspace(tmp_path)
    draft = baseline(ws)
    first = save(ws, "review", [draft["id"]], outcome="accepted", target_id=draft["id"])
    ws.select_delivery(draft["id"], first["id"])
    task = ws.request_task("review", "New evidence in draft review", [draft["id"]])
    ws.record_read(task["id"], result_ids=[draft["id"]])
    second = ws.submit(task["id"], actor="reviewer", title="Correction required", body="Fix scope",
                       source_ids=[], input_ids=[], target_id=draft["id"], outcome="changes_required")
    assert ws.status()["delivery"]["review_id"] == second["id"]
    assert ws.status()["status"] == "changes_required"
    text = "\n".join(p.text for p in Document(BytesIO(export_docx(ws, draft["id"]))).paragraphs)
    assert "Draft requiring corrections" in text and second["id"] in text
    ws.issue("system_failure", "Retrieval failed", ["access"])
    assert ws.delivery(draft["id"])["status"] == "system_error"


async def test_new_acceptance_updates_previous_rejection_without_new_model_call(tmp_path):
    ws = workspace(tmp_path)
    draft = baseline(ws)
    first = save(ws, "review", [draft["id"]], outcome="changes_required", target_id=draft["id"])
    ws.select_delivery(draft["id"], first["id"])
    task = ws.request_task("review", "Review after response to findings", [draft["id"]])
    ws.record_read(task["id"], result_ids=[draft["id"]])
    ws.submit(task["id"], actor="reviewer", title="Reviewed", body="Concern addressed",
              source_ids=[], input_ids=[], target_id=draft["id"], outcome="accepted")
    assert ws.status()["status"] == ws.status()["delivery"]["status"] == "reviewed_draft"
    factory = ModelFactory(ws)
    assert (await run_report(ws, factory))["status"] == "reviewed_draft"
    assert not factory.created
