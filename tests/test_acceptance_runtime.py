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


@pytest.fixture
def native_access_ws(tmp_path, ws):
    # Reuse only the original synthetic commission/source, not old runtime state.
    store = Store(tmp_path / "native")
    store.initialize({"goal": ws.store.manifest["goal"], "sources": ws.store.manifest["sources"],
        "content_contract": "hierarchical-review-v1", "review_entrypoint": "delegated-reviewer-v1"})
    return Workspace(store)


def native_access_driver(ws):
    captured = {}
    body = {"kind": "block", "body": {"text": "Daytime access only [s]."},
            "qualifiers": {}, "claim_kind": "fact"}
    def commit_standard(messages):
        inputs = observation(messages, "import_source_versions")["result"]
        payload = {"requirement_refs": [inputs["requirement_ref"]],
            "purpose": "Faithful compilation of the commissioned access restrictions",
            "scope": "Access recommendation",
            "expected_outcome": "The adopted access restriction agrees with the source.",
            "evidence_expectation": "Locate supporting source statement.",
            "allowed_limits": "Genuine uncertainty may remain explicitly attributed."}
        captured["payload"] = payload
        return invoke("commit_objects", operation_id="access-criterion", objects=[{
            "client_key": "criterion", "type": "Criterion", "payload": payload}])
    def delegate(messages):
        ref = observation(messages, "commit_objects")["result"]["refs"]["criterion"]
        captured["ref"] = ref
        captured["description"] = ("Compile the supplied access restriction using Criterion Ref "
            f"type={ref['type']} id={ref['id']} version={ref['version']}.")
        return invoke("task", subagent_type="writer", description=captured["description"])
    def read_standard(messages):
        assert captured["description"] in "\n".join(str(m.content) for m in messages)
        return invoke("read_context", target_ref=captured["ref"])
    def produce(messages):
        returned = observation(messages, "read_context")["result"]
        assert returned["loaded_refs"] == [captured["ref"]]
        assert returned["objects"][0]["payload"] == captured["payload"]
        return invoke("process_report_content", operation_id="access-produce",
            objective="Compile the supplied access restriction using the selected criterion.",
            object_type="ContentNode", input_refs=[captured["ref"]], source_selections=[{"source_id": "s"}])
    def independent_producer(messages):
        packet = json.loads(messages[-1].content)
        selected = [item["object"] for item in packet["evidence"] if item["kind"] == "saved_object"]
        criterion = next(obj for obj in selected if obj["ref"] == captured["ref"])
        assert criterion["payload"] == captured["payload"]
        source_blocks = [block["text"] for item in packet["evidence"] if item["kind"] == "source_blocks"
                         for block in item["observation"]["blocks"]]
        assert source_blocks == ["Daytime access only."]
        captured["producer_observed"] = True
        return AIMessage(content=json.dumps(body))
    def adopt(messages):
        work = observation(messages, "process_report_content")
        return invoke("save_text_node", operation_id="access-adopt", text_work_id=work["text_work_id"])
    driver = Driver(coordinator=[invoke("import_source_versions", operation_id="access-inputs", source_ids=["s"]),
        commit_standard, delegate, AIMessage(content="Saved writer output; independent review remains open.")],
        writer=[read_standard, produce, adopt, AIMessage(content="Saved selected-criterion content.")],
        text_tool=[independent_producer])
    return driver, captured, body


def assert_native_access_result(ws, driver, captured, body):
    from report_agent.content_store import ContentStore
    cs = ContentStore(ws.store)
    criteria, nodes = cs.list_objects("Criterion"), cs.list_objects("ContentNode")
    assert len(criteria) == len(nodes) == 1
    assert criteria[0]["ref"] == captured["ref"] and criteria[0]["payload"] == captured["payload"]
    assert criteria[0]["owner_id"] == "content:coordinator"
    assert nodes[0]["owner_id"].startswith("content:writer:") and nodes[0]["payload"] == body
    assert captured["producer_observed"]
    assert sum(role == "text_tool" for role, _, _ in driver.calls) == 1
    assert not cs.list_objects("ReviewRecord") and ws.store.get("content_delivery") is None
    assert not any(role == "rubric_grader" for role, _, _ in driver.calls)
    assert ws.store.manifest["sources"][0]["content"] == "Daytime access only."


async def test_standards_before_draft_same_version_in_actual_native_grader(native_access_ws):
    # The shared protocol retains every original same-Criterion/assertion check.
    from hierarchical_fixtures import current_native_access_review
    await current_native_access_review(native_access_ws)


async def test_delegated_author_gets_criteria_before_first_generation(native_access_ws):
    driver, captured, body = native_access_driver(native_access_ws)
    result = await deep_runtime.run_report(native_access_ws, driver)
    assert result["last_error"] is None, result
    assert_native_access_result(native_access_ws, driver, captured, body)


async def test_unknown_only_is_terminal_without_author_rewrite(ws):
    # Explicit historical component integration: host fixture replaces the old
    # three setup calls. Runtime still makes exactly one root+grader call per
    # explicit invocation, no author rewrite or automatic follow-up investigation.
    from copy import deepcopy
    from langchain.agents import create_agent
    from langchain_core.messages import HumanMessage
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from report_agent.acceptance import MODE, criteria_rules, criteria_identity
    from report_agent.review import native_review, reviewer_prompt, reconcile_review, review_delivery
    from report_agent.store import digest
    ws.initialize()
    assert bind_mode(ws) == MODE and not ws.results()
    acceptance = save_criteria(ws, actor="coordinator", title="Historical explicit reassessment",
        criteria=standards(), source_ids=["s"], input_ids=[], reason="Synthetic original unknown-outcome protocol.")
    criteria = active_criteria(ws)
    task = ws.request_task("draft", "Historical artifact selected for reassessment", [acceptance["id"]])
    draft = ws.submit(task["id"], actor="writer", title="Synthetic report", body="Daytime access only [s].",
        source_ids=["s"], input_ids=[acceptance["id"]])
    ws.select_delivery(draft["id"], "")
    originals = deepcopy(ws.results()), deepcopy(ws.tasks()), deepcopy(ws.store.manifest["sources"])
    commits = deepcopy([e for e in ws.store.events() if e["kind"] == "result_committed"])
    rules = criteria_rules(criteria)
    ws.store.set("active_rubric_hash", digest(rules))
    ws.store.set("active_reviewer_prompt_hash", digest(reviewer_prompt(requirement_acceptance=True)))
    driver = Driver(coordinator=[AIMessage(content="Retain this saved artifact without rewriting.")],
        rubric_grader=[lambda messages: verdict(ws, ["undetermined"])])
    path = str(ws.store.root / "historical-explicit-reassessment.db")
    config = {"configurable": {"thread_id": "historical-explicit-reassessment"}}
    async with AsyncSqliteSaver.from_conn_string(path) as saver:
        graph = create_agent(model=driver("coordinator"),
            middleware=[native_review(ws, driver("rubric_grader"), [], rules)], checkpointer=saver)
        await graph.ainvoke({"messages": [HumanMessage(content="Assess the selected historical report once.")],
            "rubric": rules}, config)
        first = await graph.aget_state(config)
        assert not first.next and not first.interrupts and first.values["_rubric_status"] == "undetermined"
        assert len(first.values["_rubric_evaluations"]) == 1
        reconcile_review(ws, first.values)
    record = deepcopy(ws.store.get("rubric_reviews")[0])
    assert record["result"] == "undetermined" and not record["unverified"]
    delivery = review_delivery(ws, draft["id"])
    assert delivery["status"] == "needs_attention" and delivery["acceptance_status"] == "undetermined"
    assert len([r for r in ws.results() if r["kind"] == "draft"]) == 1
    assert [r for r, _, _ in driver.calls] == ["coordinator", "rubric_grader"]
    assert (ws.results(), ws.tasks(), ws.store.manifest["sources"]) == originals
    reopened = Workspace(Store(ws.store.root))
    fresh = Driver(coordinator=[AIMessage(content="Unused old step"), AIMessage(content="Explicitly reassess the same saved draft.")],
        rubric_grader=[lambda messages: verdict(reopened, ["satisfied"])])
    async with AsyncSqliteSaver.from_conn_string(path) as saver:
        graph = create_agent(model=fresh("coordinator"),
            middleware=[native_review(reopened, fresh("rubric_grader"), [], rules)], checkpointer=saver)
        stored = await graph.aget_state(config)
        assert stored.values["_rubric_evaluations"] == first.values["_rubric_evaluations"]
        # A new explicit user invocation, not replay of an unknown provider call.
        await graph.ainvoke({"messages": [HumanMessage(content="Now explicitly assess the same saved report again.")],
            "rubric": rules}, config)
        final = await graph.aget_state(config)
        assert not final.next and not final.interrupts
        assert final.values["_rubric_status"] == "satisfied"
        reconcile_review(reopened, final.values)
    reviews = reopened.store.get("rubric_reviews")
    assert len(reviews) == 2 and reviews[0] == record
    assert reviews[0]["grading_run_id"] != reviews[1]["grading_run_id"]
    assert [r["iteration"] for r in reviews] == [0, 0]
    assert [r["result"] for r in reviews] == ["undetermined", "satisfied"]
    assert all(r["target"]["draft_id"] == draft["id"] and
        r["target"]["acceptance_criteria"] == criteria_identity(criteria) for r in reviews)
    assert review_delivery(reopened, draft["id"])["status"] == "reviewed_draft"
    assert fresh.calls[0][:2] == ("coordinator", 1)
    assert [r for r, _, _ in fresh.calls] == ["coordinator", "rubric_grader"]
    reconcile_review(reopened, final.values)
    assert reopened.store.get("rubric_reviews") == reviews
    assert (reopened.results(), reopened.tasks(), reopened.store.manifest["sources"]) == originals
    assert [e for e in reopened.store.events() if e["kind"] == "result_committed"] == commits


async def _historical_acceptance_identity_component(ws, grade):
    """Retained middleware/real saver, not retired run_report or current retry policy."""
    import hashlib
    from copy import deepcopy
    from langchain.agents import create_agent
    from langchain_core.messages import HumanMessage
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from report_agent.acceptance import MODE, criteria_rules, criteria_identity, draft_criteria
    from report_agent.acceptance_review import contract_identity
    from report_agent.review import native_review, reviewer_prompt, reconcile_review, review_delivery
    from report_agent.store import digest
    ws.initialize()
    assert not ws.results() and bind_mode(ws) == MODE
    acceptance = save_criteria(ws, actor="coordinator", title="Historical two-criterion compatibility",
        criteria=standards(True), source_ids=["s"], input_ids=[], reason="Original coverage-correction protocol fixture.")
    criteria = active_criteria(ws)
    assert criteria["current"] and len(criteria["criteria"]) == 2
    task = ws.request_task("draft", "Historical selected artifact", [acceptance["id"]])
    draft = ws.submit(task["id"], actor="writer", title="Synthetic saved report", body="Daytime access only [s].",
        source_ids=["s"], input_ids=[acceptance["id"]])
    ws.select_delivery(draft["id"], "")
    assert draft["input_ids"] == [acceptance["id"]] and draft_criteria(ws, draft)["id"] == acceptance["id"]
    originals = deepcopy(ws.results()), deepcopy(ws.tasks()), deepcopy(ws.store.manifest["sources"])
    commits = deepcopy([e for e in ws.store.events() if e["kind"] == "result_committed"])
    assert not ws.store.get("rubric_reviews") and not ws.store.get("rubric_targets")
    rules = criteria_rules(criteria)
    prompt_hash = digest(reviewer_prompt(requirement_acceptance=True))
    ws.store.set("active_rubric_hash", digest(rules))
    ws.store.set("active_reviewer_prompt_hash", prompt_hash)
    driver = Driver(coordinator=[AIMessage(content="Review the existing historical artifact; no rewrite.")], rubric_grader=[grade])
    config = {"configurable": {"thread_id": "historical-identity-component"}}
    path = str(ws.store.root / "historical-identity-checkpoints.db")
    async with AsyncSqliteSaver.from_conn_string(path) as saver:
        graph = create_agent(model=driver("coordinator"),
            middleware=[native_review(ws, driver("rubric_grader"), [], rules)], checkpointer=saver)
        await graph.ainvoke({"messages": [HumanMessage(content="Check exact adopted historical acceptance IDs.")],
            "rubric": rules}, config)
        native = await graph.aget_state(config)
        assert not native.next and not native.interrupts
        assert len(native.values["_rubric_evaluations"]) == 1
        reconcile_review(ws, native.values)
    records = ws.store.get("rubric_reviews")
    assert len(records) == 1
    record = records[0]
    evaluation = native.values["_rubric_evaluations"][0]
    assert record["origin"] == "native_rubric_checkpoint" and record["iteration"] == evaluation["iteration"] == 0
    assert record["grading_run_id"] == evaluation["grading_run_id"]
    assert set(ws.store.get("rubric_targets")) == {record["grading_run_id"] + ":0"}
    target = record["target"]
    assert target["draft_id"] == draft["id"] and target["draft_body_sha256"] == hashlib.sha256(draft["body"].encode()).hexdigest()
    assert target["acceptance_criteria"] == criteria_identity(criteria)
    assert target["rubric_hash"] == digest(rules) and target["reviewer_prompt_hash"] == prompt_hash
    assert target["review_response_contract"] == contract_identity() and target["preview_version"] and target["docx_sha256"]
    assert sum(r == "rubric_grader" for r, _, _ in driver.calls) == 2
    assert sum(r == "coordinator" for r, _, _ in driver.calls) == 1
    reopened = Workspace(Store(ws.store.root))
    async with AsyncSqliteSaver.from_conn_string(path) as saver:
        persisted = await saver.aget_tuple(config)
        assert persisted.checkpoint["channel_values"]["_rubric_evaluations"] == [evaluation]
        reconcile_review(reopened, persisted.checkpoint["channel_values"])
    assert reopened.store.get("rubric_reviews") == records
    assert (reopened.results(), reopened.tasks(), reopened.store.manifest["sources"]) == originals
    assert [e for e in reopened.store.events() if e["kind"] == "result_committed"] == commits
    assert len([r for r in reopened.results() if r["kind"] == "draft"]) == 1
    return record, review_delivery(reopened, draft["id"]), driver


@pytest.mark.parametrize("bad_names", ["duplicate", "unknown", "omitted"])
async def test_exact_identity_coverage_uses_native_correction_retry(ws, bad_names):
    # Preserve native two-call correction using the retained historical component.
    seen = []
    def grade(messages):
        seen.append(messages)
        ids = [c["id"] for c in active_criteria(ws)["criteria"]]
        if len(seen) == 1:
            names = [ids[0], ids[0]] if bad_names == "duplicate" else [ids[0], "invented"] if bad_names == "unknown" else [ids[0]]
            return verdict(ws, ["satisfied"] * len(names), names)
        assert "without replacements, omissions or duplicates" in str(messages)
        assert all(identity in str(messages) for identity in ids)
        return verdict(ws, ["satisfied", "satisfied"])
    record, delivery, _ = await _historical_acceptance_identity_component(ws, grade)
    assert delivery["status"] == "reviewed_draft" and len(seen) == 2
    assert record["result"] == "satisfied" and not record["unverified"]
    assert [c["name"] for c in record["criteria"]] == [c["id"] for c in active_criteria(ws)["criteria"]]


async def test_repeated_incomplete_coverage_is_unverified_not_an_author_defect(ws):
    seen = []
    def grade(messages):
        seen.append(messages)
        if len(seen) == 2:
            assert "without replacements, omissions or duplicates" in str(messages)
            assert all(c["id"] in str(messages) for c in active_criteria(ws)["criteria"])
        return verdict(ws, ["satisfied"], ["invented_id"])
    record, delivery, _ = await _historical_acceptance_identity_component(ws, grade)
    assert delivery["status"] == "needs_attention" and len(seen) == 2
    assert delivery["acceptance_status"] == "undetermined"
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
    result = await _historical_acceptance_behavior(ws, driver)
    assert result["last_error"] is None, result
    assert result["status"] == "reviewed_draft", result
    reviews = ws.store.get("rubric_reviews")
    assert len(reviews) == 2 and reviews[0]["grading_run_id"] != reviews[1]["grading_run_id"]
    assert [r["iteration"] for r in reviews] == [0, 0]
    assert observed[0] != observed[1]
    assert reviews[0]["target"]["acceptance_criteria"]["criteria_id"] == observed[0]
    assert reviews[1]["target"]["acceptance_criteria"]["criteria_id"] == observed[1]


async def test_recovery_after_criteria_commit_keeps_one_version(native_access_ws):
    from report_agent.content_store import ContentStore
    from test_deep_runtime import snapshot as checkpoint
    ws = native_access_ws
    driver, captured, body = native_access_driver(ws)
    driver.fail_once = ("coordinator", 2)
    first = await deep_runtime.run_report(ws, driver)
    assert first["status"] == "failed"
    assert first["last_error"]["message"] == "MODEL_REQUEST_TIMEOUT"
    cs = ContentStore(ws.store)
    before = cs.list_objects("Criterion")
    assert len(before) == 1 and before[0]["ref"]["version"] == 1
    assert not cs.list_objects("DelegatedTask") and not cs.list_objects("ContentNode")
    assert not any(role in {"writer", "text_tool"} for role, _, _ in driver.calls)
    assert (await checkpoint(ws, driver)).next
    calls_before = len(driver.calls)
    resumed = await deep_runtime.run_report(Workspace(Store(ws.store.root)), driver)
    assert resumed["last_error"] is None, resumed
    assert driver.calls[calls_before][:2] == ("coordinator", 2)
    assert cs.list_objects("Criterion") == before
    assert_native_access_result(ws, driver, captured, body)
    with ws.store.connect() as db:
        assert db.execute("SELECT count(*) FROM content_operations WHERE operation_id='access-criterion'").fetchone()[0] == 1
    assert sum(role == "coordinator" and step == 1 for role, step, _ in driver.calls) == 1


async def test_missing_preconditions_expose_recoverable_limitation_without_grader(ws):
    first = await _historical_acceptance_behavior(ws, Driver(coordinator=[AIMessage(content="Finished.")]))
    assert first["status"] == "needs_attention" and first["last_error"] is None
    assert first["acceptance_limitation"]["reason"] == "SELECTED_DRAFT_REQUIRED_FOR_ACCEPTANCE"
    assert deep_runtime.project_view(ws)["acceptance_limitation"] == first["acceptance_limitation"]
    assert not ws.store.get("rubric_reviews")
    driver = Driver(coordinator=[None, save_standards(), save_draft(ws),
                                 select, AIMessage(content="Saved.")],
                    rubric_grader=[lambda m: verdict(ws, ["satisfied"])])
    resumed = await _historical_acceptance_behavior(ws, driver)
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
    result = await _historical_acceptance_behavior(ws, driver)
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


async def _historical_acceptance_behavior(ws, driver):
    """Real retained acceptance tools and native feedback, not a production wrapper."""
    from inspect import iscoroutinefunction
    from langchain.agents import create_agent
    from langchain_core.messages import HumanMessage
    from langchain_core.tools import StructuredTool
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from report_agent.acceptance import MODE
    from report_agent.review import native_review, reconcile_review, reviewer_prompt
    from report_agent.store import digest

    ws.initialize()
    ws.store.set("acceptance_default", MODE)
    assert bind_mode(ws) == MODE
    ws.store.set("active_reviewer_prompt_hash", digest(reviewer_prompt(requirement_acceptance=True)))
    config = {"configurable": {"thread_id": "historical-acceptance-behavior"}}
    path = str(ws.store.root / "checkpoints.db")
    tools = [StructuredTool.from_function(coroutine=t) if iscoroutinefunction(t)
             else StructuredTool.from_function(t)
             for t in deep_runtime.business_tools(ws, "coordinator", None, None)]
    async with AsyncSqliteSaver.from_conn_string(path) as saver:
        graph = create_agent(model=driver("coordinator"), tools=tools,
            system_prompt=deep_runtime.COORDINATOR + "\n" + deep_runtime.ACCEPTANCE_GUIDANCE,
            middleware=[deep_runtime.BusinessBoundary(ws, "coordinator"),
                native_review(ws, driver("rubric_grader"), [], rules="")], checkpointer=saver)
        prior = await graph.aget_state(config)
        prior_steps = sum(isinstance(m, AIMessage) for m in prior.values.get("messages", []))
        await graph.ainvoke({"messages": [HumanMessage(content="Carry out the commissioned acceptance work.")],
            "rubric": ""}, config)
        state = await graph.aget_state(config)
        assert not state.next and not state.interrupts
        assert next(step for role, step, _ in driver.calls if role == "coordinator") == prior_steps
        reconcile_review(ws, state.values)
        result = project_state(ws)
    async with AsyncSqliteSaver.from_conn_string(path) as saver:
        saved = await saver.aget_tuple(config)
        assert saved.checkpoint["channel_values"].get("_rubric_evaluations", []) == state.values.get("_rubric_evaluations", [])
    return result
