from report_agent import report_state
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
    from report_agent.errors import ActionRejected
    from report_agent.deep_runtime import business_tools
    from test_task_supervision import ws as native_ws

    # Retirement is not evidence of current native caller ownership enforcement.
    with pytest.raises(ActionRejected, match="HISTORICAL_AGENT_EXECUTION_INACTIVE"):
        worker_tools(ws, task["id"], None)
    current = native_ws.__wrapped__(tmp_path / "native")
    tools = business_tools(current, "writer", None, None)
    assert not {"task", "select_content_delivery", "execute"} & {tool.__name__ for tool in tools}
    # Actual native adversarial controls supplement this factory-list assertion.
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
    from copy import deepcopy
    from io import BytesIO
    from docx import Document
    from langchain_core.messages import AIMessage
    from report_agent import deep_runtime
    from report_agent.content_store import ContentStore
    from report_agent.content_export import _bytes
    from test_deep_runtime import Driver, invoke, observation
    from test_task_supervision import ws as native_ws
    from test_bounded_review import review_call

    ws = native_ws.__wrapped__(tmp_path)
    original_sources = deepcopy(ws.store.manifest["sources"])
    body = {"kind": "claim", "body": {"text": "For adopted class B use 70."},
            "qualifiers": {"condition": "class B"}, "claim_kind": "inference"}
    captured = {}
    def criterion(messages):
        inputs = observation(messages, "import_source_versions")["result"]
        return invoke("commit_objects", operation_id="scope-rule", objects=[{
            "client_key": "k", "type": "Criterion", "payload": {
                "requirement_refs": [inputs["requirement_ref"]], "purpose": "Faithful comparison",
                "scope": "selected claim only", "expected_outcome": "Adopted value agrees with the rule.",
                "evidence_expectation": "Read the selected claim and original rule.",
                "allowed_limits": "No whole-report assessment."}}])
    def adopt(messages):
        work = observation(messages, "process_report_content")
        return invoke("commit_objects", operation_id="adopt-body", objects=[
            {"client_key": "root", "type": "ContentNode", "payload": {"kind": "report",
                "body": {"text": "Synthetic scoped report"}, "qualifiers": {}, "claim_kind": "structure"}},
            {"client_key": "claim", "type": "ContentNode", "text_work_id": work["text_work_id"]},
            {"client_key": "edge", "type": "Relation", "payload": {
                "subject_ref": {"client_key": "root"}, "object_ref": {"client_key": "claim"},
                "predicate": "contains", "position": 0, "provenance_kind": "adopted_during_generation"}}])
    def writer_return(messages):
        return AIMessage(content=json.dumps({"saved_refs": observation(messages, "commit_objects")["result"]["refs"]}))
    def freeze(messages):
        saved = observation(messages, "task")["saved_refs"]
        inputs = observation(messages, "import_source_versions")["result"]
        criteria = observation(messages, "commit_objects")["result"]["refs"]
        captured.update(saved=saved, source=inputs["source_refs"][0], criterion=criteria["k"])
        return invoke("freeze_snapshot", operation_id="freeze-scoped", root_ref=saved["root"],
            refs=[*saved.values(), criteria["k"], inputs["requirement_ref"], *inputs["source_refs"]])
    def review(messages):
        snapshot = observation(messages, "freeze_snapshot")["result"]["snapshot_ref"]
        return AIMessage(content="", tool_calls=[review_call(snapshot,
            {"claim": captured["saved"]["claim"], "k": captured["criterion"]}, reads=[captured["source"]])])
    def checker(messages):
        packet = json.loads(messages[-1].content)
        indexes = [next(i for i,e in enumerate(packet["evidence"])
            if e.get("object", {}).get("ref") == ref)
            for ref in (captured["saved"]["claim"], captured["source"])]
        assert packet["evidence"][indexes[0]]["object"]["payload"] == body
        assert packet["evidence"][indexes[1]]["object"]["payload"]["content"] == original_sources[0]["content"]
        captured["packet"] = deepcopy(packet)
        return AIMessage(content=json.dumps({"items": [{"scope_id": "rule-comparison",
            "checked_requirement_indexes": [0], "execution_state": "completed", "verdict": "not_satisfied",
            "observations": [{"evidence_index": indexes[0], "locator": "claim", "observation": "Adopted B uses 70."},
                {"evidence_index": indexes[1], "locator": "rule", "observation": "B permits 75 to 100."}],
            "check_results": [{"requirement_index": 0, "execution_state": "completed",
                "result": "70 is outside the selected rule interval.", "observation_indexes": [0,1], "remaining": ""}],
            "coverage": {"checked": ["selected claim comparison"], "unchecked": [], "blocked": [],
                "basis": "Exact claim and original rule; no whole-report assessment."},
            "reason": "Local defect retained; no engineering acceptance.", "findings": []}]}))
    def export(messages):
        return invoke("export_content_snapshot", operation_id="word-scoped",
            snapshot_ref=observation(messages, "freeze_snapshot")["result"]["snapshot_ref"])
    def select(messages):
        return invoke("select_content_delivery", operation_id="select-scoped", ending_reason="preserve_unresolved",
            snapshot_ref=observation(messages, "freeze_snapshot")["result"]["snapshot_ref"],
            export_ref=observation(messages, "export_content_snapshot")["result"]["export_ref"])
    driver = Driver(coordinator=[invoke("import_source_versions", operation_id="inputs", source_ids=["s"]),
        criterion, invoke("task", subagent_type="writer", description="Produce the selected claim as a draft."),
        freeze, review, export, select, AIMessage(content="Scoped draft and local defect retained; no overall approval.")],
        writer=[invoke("process_report_content", operation_id="produce-body", objective="Compile the selected class B value",
            object_type="ContentNode", source_selections=[{"source_id": "s"}]), adopt, writer_return],
        reviewer=[invoke("perform_assigned_review", operation_id="compare", scope_ids=["rule-comparison"],
            source_selections=[], content_selections=[]), AIMessage(content="Saved local finding returned unchanged.")],
        text_tool=[lambda messages: checker(messages) if "assignment" in json.loads(messages[-1].content)
                   else AIMessage(content=json.dumps(body))])
    first = await deep_runtime.run_report(ws, driver)
    assert first["last_error"] is None, first
    cs = ContentStore(ws.store)
    records = cs.list_objects("ReviewRecord")
    assert len(records) == 1 and records[0]["payload"]["items"][0]["verdict"] == "not_satisfied"
    assert records[0]["owner_id"] == "content:reviewer:" + records[0]["task_id"]
    claim = cs.read(captured["saved"]["claim"])
    assert claim["payload"] == body and claim["owner_id"].startswith("content:writer:")
    assert sum(role == "text_tool" for role, _, _ in driver.calls) == 2
    selected = deepcopy(report_state.selected_delivery(ws.store))
    saved_export = cs.read(selected["export_ref"])["payload"]
    word = _bytes(ws.store, saved_export["file_ref"], saved_export["file_digest"])
    assert body["body"]["text"] in "\n".join(p.text for p in Document(BytesIO(word)).paragraphs)
    objects = deepcopy(cs.list_objects())
    with ws.store.connect() as db:
        operations = db.execute("SELECT * FROM content_operations ORDER BY actor_id, operation_id").fetchall()
    def read_selected(messages):
        actual = observation(messages, "content_status")
        assert actual["delivery"] == selected
        assert actual["current_review"]["overall_verdict"] != "satisfied"
        return invoke("read_context", target_ref=actual["delivery"]["snapshot_ref"])
    def finish_reuse(messages):
        returned = observation(messages, "read_context")
        assert returned["result"]["target_ref"] == selected["snapshot_ref"]
        assert any(o["ref"] == captured["saved"]["claim"] and o["payload"] == body
                   for o in returned["result"]["objects"])
        return AIMessage(content="Existing exact scoped draft reused; its local defect is unresolved.")
    prior_steps = max(step for role, step, _ in driver.calls if role == "coordinator") + 1
    reused = Driver(coordinator=[None] * prior_steps + [invoke("content_status"), read_selected, finish_reuse])
    second = await deep_runtime.run_report(Workspace(Store(ws.store.root)), reused)
    assert second["last_error"] is None, second
    assert all(role == "coordinator" for role, _, _ in reused.calls)
    assert cs.list_objects() == objects and report_state.selected_delivery(ws.store) == selected
    with ws.store.connect() as db:
        assert db.execute("SELECT * FROM content_operations ORDER BY actor_id, operation_id").fetchall() == operations
    assert _bytes(ws.store, saved_export["file_ref"], saved_export["file_digest"]) == word
    assert ws.store.manifest["sources"] == original_sources


async def test_report_resumes_failed_task_without_regenerating_completed_plan(tmp_path):
    from copy import deepcopy
    import httpx
    from langchain_core.messages import AIMessage, ToolMessage
    from report_agent import deep_runtime
    from report_agent.content_store import ContentStore
    from report_agent.task_context import exact_task_context
    from test_agent_duty_trace_cases import result_value
    from test_deep_runtime import Driver, call, invoke, observation
    from test_task_supervision import ws as native_ws

    ws = native_ws.__wrapped__(tmp_path)
    cs = ContentStore(ws.store)
    original_sources = deepcopy(ws.store.manifest["sources"])
    note = {"kind": "block", "body": {"text": "Source rule: class B permits 75 to 100."},
            "qualifiers": {}, "claim_kind": "fact"}
    body = {"kind": "block", "body": {"text": "The report remains subject to the supplied class B interval."},
            "qualifiers": {}, "claim_kind": "fact"}
    seen = {"failed": False}
    def child_start(messages):
        context = exact_task_context(ws, "writer")
        description = context["current_invocation"]["description"]
        if description == "Write the downstream report body." and not seen["failed"]:
            seen.update(failed=True, failed_actor=context["actor_id"], failed_assignment=deepcopy(context["assignment"]))
            raise httpx.ReadTimeout("SYNTHETIC_DOWNSTREAM_READ_TIMEOUT")
        if description == "Recover the downstream report body in the existing task.":
            assert context["actor_id"] == seen["failed_actor"]
            assert context["assignment"] == seen["failed_assignment"]
            seen["resumed_actor"] = context["actor_id"]
        return invoke("process_report_content", operation_id="produce",
            objective="Produce upstream note" if description == "Save the upstream source note." else "Produce downstream body",
            object_type="ContentNode", source_selections=[{"source_id": "s"}])
    def adopt(messages):
        work = observation(messages, "process_report_content")
        return invoke("save_text_node", operation_id=("adopt-upstream-note"
            if work["payload"] == note else "adopt-downstream-body"), text_work_id=work["text_work_id"])
    def return_work(messages):
        work = observation(messages, "process_report_content")
        return AIMessage(content=json.dumps({"saved_ref": observation(messages, "save_text_node")["result"]["refs"]["text"],
            "task_id": work["task_id"], "actor_id": work["actor_id"]}))
    def start_downstream(messages):
        public = observation(messages, "task")
        seen["upstream"] = deepcopy(public)
        return AIMessage(content="", tool_calls=[call("task", {"subagent_type": "writer",
            "description": "Write the downstream report body."}, "downstream-task")])
    def retain_failure(messages):
        error = next(m for m in reversed(messages) if isinstance(m, ToolMessage) and m.tool_call_id == "downstream-task")
        public = result_value(error)
        assert error.status == "error" and public["code"] == "DELEGATED_EXECUTION_FAILED"
        seen["error"] = deepcopy(public)
        return AIMessage(content="Downstream work failed; completed upstream note remains saved. No report acceptance.")
    def producer(messages):
        packet = json.loads(messages[-1].content)
        return AIMessage(content=json.dumps(note if packet["objective"] == "Produce upstream note" else body))
    first_driver = Driver(coordinator=[AIMessage(content="", tool_calls=[call("task", {
        "subagent_type": "writer", "description": "Save the upstream source note."}, "upstream-task")]),
        start_downstream, retain_failure], writer=[child_start, adopt, return_work], text_tool=[producer])
    first = await deep_runtime.run_report(ws, first_driver)
    assert first["last_error"] is None and seen["failed"] and seen["error"], first
    upstream = deepcopy(cs.read(seen["upstream"]["saved_ref"]))
    assert upstream["payload"] == note and upstream["owner_id"] == seen["upstream"]["actor_id"]
    assert upstream["task_id"] == seen["upstream"]["task_id"] and upstream["ref"]["version"] == 1
    with ws.store.connect() as db:
        saved_operations = db.execute("SELECT * FROM content_operations WHERE actor_id=? ORDER BY operation_id",
                                      (upstream["owner_id"],)).fetchall()
    def resume_from_public_index(messages):
        public = observation(messages, "read_object_index")
        assert public["total"] == 2 and public["next_offset"] is None
        pending, = [item for item in public["objects"] if item["ref"]["id"] != seen["upstream"]["task_id"]]
        seen["public_resume_ref"] = deepcopy(pending["ref"])
        return AIMessage(content="", tool_calls=[call("task", {"subagent_type": "writer",
            "description": "Recover the downstream report body in the existing task.",
            "resume_content_task_id": pending["ref"]["id"]}, "resume-downstream")])
    def read_saved_body(messages):
        public = observation(messages, "task")
        seen["downstream"] = deepcopy(public)
        assert public["task_id"] == seen["public_resume_ref"]["id"]
        return invoke("read_context", target_ref=public["saved_ref"])
    def finish(messages):
        actual = observation(messages, "read_context")["result"]
        assert actual["target_ref"] == seen["downstream"]["saved_ref"]
        assert actual["objects"][0]["payload"] == body
        return AIMessage(content="Original task recovered and upstream note reused; no independent review or acceptance.")
    offset = max(step for role,step,_ in first_driver.calls if role == "coordinator") + 1
    second_driver = Driver(coordinator=[None] * offset + [invoke("read_object_index", object_type="DelegatedTask"),
        resume_from_public_index, read_saved_body, finish], writer=[child_start, adopt, return_work], text_tool=[producer])
    second = await deep_runtime.run_report(Workspace(Store(ws.store.root)), second_driver)
    assert second["last_error"] is None, second
    assert seen["resumed_actor"] == seen["failed_actor"] == seen["downstream"]["actor_id"]
    assert cs.read(upstream["ref"]) == upstream
    with ws.store.connect() as db:
        assert db.execute("SELECT * FROM content_operations WHERE actor_id=? ORDER BY operation_id",
                          (upstream["owner_id"],)).fetchall() == saved_operations
    assert len(cs.list_objects("DelegatedTask")) == 2 and len(cs.list_objects("ContentNode")) == 2
    assert sum(role == "text_tool" for role,_,_ in first_driver.calls) == 1
    assert sum(role == "text_tool" for role,_,_ in second_driver.calls) == 1
    assert not {"reviewer", "rubric_grader"} & {role for role,_,_ in [*first_driver.calls,*second_driver.calls]}
    assert ws.store.manifest["sources"] == original_sources


async def test_configuration_failure_visible_without_paid_request(tmp_path, monkeypatch):
    import httpx
    from copy import deepcopy
    from report_agent import deep_runtime
    from report_agent.content_store import ContentStore
    from test_prototype import clear_provider_configuration
    from test_task_supervision import ws as native_ws

    ws = native_ws.__wrapped__(tmp_path)
    before = deepcopy(ws.store.manifest)
    clear_provider_configuration(monkeypatch)
    sent = []
    def no_network(*args, **kwargs):
        sent.append(True)
        raise AssertionError("Missing configuration must fail before a provider request")
    monkeypatch.setattr(httpx.Client, "send", no_network)
    monkeypatch.setattr(httpx.AsyncClient, "send", no_network)
    status = await deep_runtime.run_report(ws)
    assert status["status"] == "failed"
    assert status["last_error"]["type"] == "RuntimeError"
    assert status["last_error"]["message"] == "AUTHORIZED_GLM53_CONFIGURATION_REQUIRED"
    assert ws.store.get("report_error") == status["last_error"]
    assert any(event["kind"] == "deep_run_error" for event in ws.store.events())
    assert not sent and not ContentStore(ws.store).list_objects()
    assert report_state.selected_delivery(ws.store) is None
    assert ws.store.manifest == before


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
    # Explicit current interface migration: the goal-level work item is a real
    # Writer DelegatedTask and its idempotent structural-plan adoption receipt.
    from repetition_fixtures import known_write_repetition_case
    from test_deep_runtime import snapshot
    ws, cs, driver, seen, status = await known_write_repetition_case(tmp_path)
    from langchain_core.messages import ToolMessage
    from test_agent_duty_trace_cases import assert_delegated_failure
    assert status['last_error'] is None
    message=next(m for m in driver.calls[-1][2] if isinstance(m,ToolMessage) and m.name=='task')
    failure=assert_delegated_failure(ws,message,'RuntimeError')
    assert failure['error']['message']=='REPEATED_ACTION_WITHOUT_STATE_PROGRESS'
    stopped=[e['data'] for e in ws.store.events() if e['kind']=='known_write_repetition_stopped']
    assert len(stopped)==1 and stopped[0]['attempted_write_executed'] is False
    assert len(cs.list_objects("DelegatedTask")) == 1
    assert len(cs.list_objects("ContentNode")) == 1
    assert cs.list_objects("ContentNode")[0]["ref"]["version"] == 1
    assert seen["advisory_observed"]
    assert not (await snapshot(ws, driver)).next


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


def test_human_decision_authority_survives_projection_rollback_and_redo(tmp_path):
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
    # M6 commits authority separately; only the unfinished case projection rolls back.
    from report_agent import issue_state
    assert issue_state.get_wait_projection(ws.store)[0]['decision'] == 'Earlier decision'
    assert ws.status()['issues'][0]['decision'] == 'Changed decision'
    assert {k: v for k, v in ws.status().items() if k != 'issues'} == {
        k: v for k, v in before.items() if k != 'issues'}
    assert ws.store.get("context_revision") == revision
    with ws.store.connect() as db:
        db.execute('DROP TRIGGER simulate_commit_failure')
    ws.decide_issue(issue['id'], 'Changed decision', resolved=True)
    assert issue_state.get_wait_projection(ws.store)[0]['decision'] == 'Changed decision'
    assert ws.store.get('context_revision') == revision + 1
    events = ws.store.events()
    ws.decide_issue(issue['id'], 'Changed decision', resolved=True)
    assert ws.store.events() == events


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
    text = "\n".join(p.text for p in Document(BytesIO(
        export_docx(ws, draft["id"], include_execution_record=True))).paragraphs)
    assert "Draft requiring corrections" in text and second["id"] in text
    assert first['id'] not in text
    ws.issue("system_failure", "Retrieval failed", ["access"])
    assert ws.delivery(draft["id"])["status"] == "system_error"
    assert all(issue['category'] != 'source_missing' for issue in ws.status()['issues'])
    conflict = 'Two original access records conflict; the site condition is unresolved.'
    ws.issue('source_conflict', conflict, ['access'])
    customer = "\n".join(p.text for p in Document(BytesIO(export_docx(ws, draft['id']))).paragraphs)
    assert conflict in customer and '[access]' in customer
    assert draft['body'] in customer
    assert second['id'] not in customer and first['id'] not in customer
    assert ws.status()['delivery']['review_id'] == second['id']


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
    # Explicit retired-entry migration: current public read-only consumers expose
    # the original saved positive without constructing a model or executing ADK.
    from copy import deepcopy
    before = deepcopy((ws.results(), ws.tasks(), ws.store.events()))
    with ws.store.connect() as db:
        saved_state = list(db.execute("SELECT key,value FROM state ORDER BY key"))
    assert ws.status()["status"] == ws.delivery(draft["id"])["status"] == "reviewed_draft"
    assert (ws.results(), ws.tasks(), ws.store.events()) == before
    with ws.store.connect() as db:
        assert list(db.execute("SELECT key,value FROM state ORDER BY key")) == saved_state
    assert not factory.created
