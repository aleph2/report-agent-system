"""Synthetic offline completed-state recovery; no real report or semantic-model claims."""
import hashlib
import importlib.util
import json
from pathlib import Path
import socket
import sqlite3
import sys

import httpx
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
import pytest

from report_agent import deep_runtime
from report_agent.acceptance import active_criteria, criteria_rules
from report_agent.catalog import Catalog
from report_agent.knowledge_state import project_state
from report_agent.store import Store, encode
from report_agent.workspace import Workspace
from test_acceptance_runtime import save_standards, save_draft, select, verdict
from test_deep_runtime import Driver, invoke


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
spec = importlib.util.spec_from_file_location("prepare_review_trial017", SCRIPTS / "prepare_review_trial017.py")
primitives = importlib.util.module_from_spec(spec)
sys.modules.setdefault("prepare_review_trial017", primitives)
spec.loader.exec_module(primitives)
spec = importlib.util.spec_from_file_location("completed_recovery", SCRIPTS / "prepare_completed_feedback_recovery.py")
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    monkeypatch.delenv("REPORT_API_KEY", raising=False)

    def forbidden(*args, **kwargs):
        raise AssertionError("NETWORK_OR_CONFIGURED_MODEL_FORBIDDEN")

    monkeypatch.setattr(httpx.Client, "send", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(deep_runtime, "configured_model", forbidden)


EARLY_VALIDATION_MUTATIONS = {"hash", "target", "source", "foreign_source_path", "graph", "resume", "interrupt", "error"}


def historical_public_state_fixture(tmp_path, monkeypatch):
    """Dated data-format fixture only: no model run or terminal graph is asserted."""
    store = Store(tmp_path / "baseline")
    source = store.root / "sources/access.txt"
    source.parent.mkdir()
    source.write_bytes(b"Daytime access only.")
    store.initialize({"goal": "Historical public-state validation fixture; no executed model history.",
        "sources": [{"id": "s", "title": "Access notice", "content": "Daytime access only.",
            "coverage": "complete", "copied_path": "sources/access.txt",
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}]})
    workspace = Workspace(store)
    Catalog(store)
    draft = {"id": "historical-fixture-draft", "kind": "draft", "body": "Anytime access [s].",
        "source_ids": ["s"], "fact_ids": [], "origin": "dated-format-static-test-fixture"}
    with store.connect() as db:
        db.execute("INSERT INTO results VALUES (?,?,?)", (draft["id"], "historical-fixture", encode(draft)))
    for key,value in {"acceptance_mode": recovery.MODE, "knowledge_enabled": False,
            "delivery": {"draft_id": draft["id"]}, "rubric_status": "satisfied",
            "report_status": "completed"}.items():
        store.set(key,value)
    # Explicit synthetic public-state input, never evidence of an executed run.
    store.event("deep_run_finished", {"fixture_only": True, "executed": False})
    (store.root / "run.lock").touch()
    with sqlite3.connect(store.root / "checkpoints.db") as db:
        db.execute("CREATE TABLE non_executable_fixture(note TEXT)")
        db.execute("INSERT INTO non_executable_fixture VALUES ('Not a native checkpoint or terminal-state proof')")
    feedback = tmp_path / "feedback.txt"
    feedback.write_text("Check the historical source restriction.",encoding="utf-8")
    def forbidden_graph(*args, **kwargs):
        pytest.fail("PREVALIDATION_MUST_NOT_BUILD_OR_READ_GRAPH")
    monkeypatch.setattr(recovery, "project_agent", forbidden_graph)
    return workspace,draft,feedback


def historical_standard_projection_fixture(tmp_path, monkeypatch):
    """Dated stored projection only; no executed review or native checkpoint claim."""
    from report_agent.acceptance import (
        AcceptanceCriterionInput, active_criteria, criteria_identity,
        criteria_rules, requirement_basis,
    )
    from report_agent.acceptance_review import contract_identity as acceptance_contract
    from report_agent.review import review_delivery, export_configuration, observation_version
    from report_agent.store import digest, encode

    workspace, draft, feedback = historical_public_state_fixture(tmp_path, monkeypatch)
    store = workspace.store
    basis = requirement_basis(workspace)
    criterion = AcceptanceCriterionInput.model_validate({
        "id": "dated-static-criterion-1",
        "requirement_refs": ["commission: source access restrictions"],
        "condition": "The adopted access restriction agrees with the source.",
        "scope": "Access recommendation",
        "evidence_expectation": "Locate supporting source statement.",
        "allowed_limitations": "Genuine uncertainty may remain explicitly attributed.",
    }).model_dump()
    acceptance = {
        "id": "dated-static-acceptance-1", "kind": "acceptance",
        "body": encode({"version": recovery.MODE, "requirement_basis": basis,
            "basis_hash": digest(basis), "criteria": [criterion],
            "reason": "Historical format fixture only; not an executed model review."}),
        "source_ids": ["s"], "input_ids": [], "fact_ids": [],
        "origin": "dated-format-static-test-fixture",
    }
    draft = {**draft, "input_ids": [acceptance["id"]]}
    with store.connect() as db:
        db.execute("INSERT INTO results VALUES (?,?,?)",
            (acceptance["id"], "dated-static-acceptance", encode(acceptance)))
        db.execute("UPDATE results SET data=? WHERE id=?", (encode(draft), draft["id"]))

    # No experiment/search-view configuration: this is the existing historical format.
    assert store.get("review_context_experiment") is None
    assert store.get("source_search_view") is None
    current = active_criteria(workspace)
    assert current["id"] == acceptance["id"] and current["current"] is True
    assert draft["input_ids"] == [current["id"]]
    prompt_hash = digest("Synthetic dated prompt identity; never asserted to have run")
    store.set("active_reviewer_prompt_hash", prompt_hash)
    store.set("active_rubric_hash", digest(criteria_rules(current)))
    target = {
        "draft_id": draft["id"],
        "draft_body_sha256": hashlib.sha256(draft["body"].encode()).hexdigest(),
        "rubric_hash": digest(criteria_rules(current)),
        "reviewer_prompt_hash": prompt_hash,
        "review_context_experiment": None, "source_search_view": None,
        "review_response_contract": acceptance_contract(),
        "acceptance_criteria": criteria_identity(current),
        "export_configuration_hash": export_configuration(workspace),
        "observation_version": observation_version(workspace, draft["id"]),
    }
    record = {
        "grading_run_id": "dated-static-never-executed", "iteration": 0,
        "result": "satisfied", "unverified": False,
        "explanation": "Synthetic historical record for version projection only.",
        "criteria": [{"name": criterion["id"], "passed": True,
            "status": "satisfied", "evidence": [],
            "explanation": "Stored historical fixture; no semantic correctness claim.",
            "needed_outcome": "No runtime or engineering acceptance is asserted."}],
        "target": target, "origin": "dated-format-static-test-fixture",
    }
    store.set("rubric_reviews", [record])
    assert review_delivery(workspace, draft["id"])["status"] == "reviewed_draft"
    return workspace, draft, feedback


def test_historical_public_state_control_is_valid_without_claiming_checkpoint_completion(tmp_path, monkeypatch):
    workspace,draft,feedback = historical_public_state_fixture(tmp_path,monkeypatch)
    before = recovery.tree_hashes(workspace.store.root)
    feedback_bytes = feedback.read_bytes()
    public = recovery.read_public_state(workspace.store.root / "state.db")
    sources = recovery.validate_baseline(workspace.store.root,public,draft["id"],
        hashlib.sha256(draft["body"].encode()).hexdigest())
    assert sources == workspace.store.manifest["sources"]
    assert recovery.tree_hashes(workspace.store.root) == before and feedback.read_bytes() == feedback_bytes


def test_historical_standard_projection_valid_control_does_not_claim_execution(tmp_path, monkeypatch):
    from report_agent.review import review_delivery
    workspace, draft, feedback = historical_standard_projection_fixture(tmp_path, monkeypatch)
    before = recovery.tree_hashes(workspace.store.root)
    feedback_bytes = feedback.read_bytes()
    public = recovery.read_public_state(workspace.store.root / "state.db")
    sources = recovery.validate_baseline(workspace.store.root, public, draft["id"],
        hashlib.sha256(draft["body"].encode()).hexdigest())
    assert sources == workspace.store.manifest["sources"]
    assert active_criteria(workspace)["current"] is True
    assert review_delivery(workspace, draft["id"])["status"] == "reviewed_draft"
    assert recovery.tree_hashes(workspace.store.root) == before
    assert feedback.read_bytes() == feedback_bytes


@pytest.fixture
async def completed(tmp_path, request, monkeypatch):
    mutation = getattr(getattr(request.node,"callspec",None),"params",{}).get("mutation")
    if mutation == "standard":
        return historical_standard_projection_fixture(tmp_path, monkeypatch)
    if (mutation in EARLY_VALIDATION_MUTATIONS or mutation == "preview"
            or request.node.name == "test_existing_nested_live_and_symlink_destinations_are_refused"):
        result = historical_public_state_fixture(tmp_path,monkeypatch)
        if mutation == "preview":
            from docx import Document
            workspace,_,_ = result
            folder = workspace.store.root / "previews/static-fixture"
            folder.mkdir(parents=True)
            docx = folder / "report.docx"
            document = Document()
            document.add_paragraph("Historical preview fixture; no executed model review.")
            document.save(docx)
            (folder / "summary.json").write_text(encode({"docx": {
                "path": str(docx.resolve()), "sha256": recovery.file_hash(docx)}}),encoding="utf-8")
        return result

    store = Store(tmp_path / "baseline")
    source = store.root / "sources/access.txt"
    source.parent.mkdir()
    source.write_bytes(b"Daytime access only.")
    store.initialize({"goal": "Compile a faithful source access summary.", "sources": [{
        "id": "s", "title": "Access notice", "content": "Daytime access only.", "coverage": "complete",
        "copied_path": "sources/access.txt", "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}]})
    store.set("knowledge_enabled", False)
    Catalog(store)
    workspace = Workspace(store)
    driver = Driver(coordinator=[save_standards(), save_draft(workspace, "Anytime access [s]."),
                                 select, AIMessage(content="Saved synthetic draft.")],
                    rubric_grader=[lambda messages: verdict(workspace, ["satisfied"])])
    # Explicit test-only graph dependency: preparation still reads a real same-topology historical checkpoint.
    monkeypatch.setattr(recovery, "project_agent", _historical_completed_agent)
    result = await _historical_completed_run(workspace, driver)
    assert result["status"] == "reviewed_draft", result
    draft = next(r for r in workspace.results() if r["kind"] == "draft")
    feedback = tmp_path / "feedback.txt"
    feedback.write_text("The source says daytime only; assess the report's unrestricted-access claim and its consequences.",
                        encoding="utf-8")
    (store.root / "trial-freeze.json").write_text('{"fixture":"completed synthetic trial"}', encoding="utf-8")
    return workspace, draft, feedback


def arguments(completed, destination):
    workspace, draft, feedback = completed
    return (workspace.store.root, destination, feedback, draft["id"],
            hashlib.sha256(draft["body"].encode()).hexdigest())


async def test_completed_copy_receives_feedback_and_normal_new_run_revises_with_fresh_review(completed, tmp_path):
    baseline, original, feedback = completed
    original_tree = recovery.tree_hashes(baseline.store.root)
    original_results = baseline.results()
    original_reviews = baseline.store.get("rubric_reviews")
    destination = tmp_path / "recovery"
    receipt = await recovery.prepare(*arguments(completed, destination))
    assert recovery.tree_hashes(baseline.store.root) == original_tree
    workspace = Workspace(Store(destination))
    assert workspace.results() == original_results
    assert workspace.store.get("rubric_reviews") == original_reviews
    assert workspace.store.get("checkpoint_resume") is False
    assert workspace.store.get("feedback") is None
    assert receipt["state_keys_changed"] == ["corrections"]
    assert receipt["review_projection_before"] == "reviewed_draft"
    assert receipt["review_projection_after"] == "needs_attention"
    assert receipt["checkpoint"]["next"] == [] and receipt["checkpoint"]["interrupt_count"] == 0
    assert receipt["model_calls"] == 0
    assert recovery.file_hash(destination / "checkpoints.db") == receipt["copied_checkpoint_sha256"]
    assert (destination / "trial-freeze.json").read_bytes() == (baseline.store.root / "trial-freeze.json").read_bytes()
    assert project_state(workspace)["status"] == "needs_attention"
    description = workspace.store.get("corrections")[0]["description"]
    assert description == recovery.PREFIX + feedback.read_text()
    for change in receipt["path_changes"]:
        assert Path(change["new"]).is_relative_to(destination)
        assert Path(change["new"]).is_file()
    received, graded = [], []

    def inspect_new_call(messages):
        from report_agent.task_state_delivery import business_messages
        newest = next(m for m in reversed(business_messages(workspace.store, messages))
                      if isinstance(m, HumanMessage))
        current = json.loads(newest.content)
        assert any(c["description"] == description and c["result_id"] == original["id"]
                   for c in current["corrections"])
        received.append(True)
        return invoke("read_source_page", source_id="s")

    def grade(messages):
        text = str([m.content for m in messages])
        assert description in text or "read_review_context" in text
        graded.append(True)
        return verdict(workspace, ["satisfied"])

    # Retained synthetic history has four coordinator AI messages. Test the new
    # invocation and immutable replacement, not any required business-tool plan.
    driver = Driver(coordinator=[None] * 4 + [inspect_new_call,
                    save_draft(workspace, "Daytime access only [s].", original["id"]), select,
                    AIMessage(content="Saved corrected synthetic report.")], rubric_grader=[grade])
    result = await _historical_completed_run(workspace, driver)
    assert result["last_error"] is None and result["status"] == "reviewed_draft", result
    assert driver.calls[0][0] == "coordinator" and received and graded
    new_reviews = workspace.store.get("rubric_reviews")
    assert new_reviews[:-1] == original_reviews
    assert new_reviews[-1]["grading_run_id"] != original_reviews[-1]["grading_run_id"]
    assert new_reviews[-1]["iteration"] == 0
    replacement = workspace.result(result["delivery"]["draft_id"])
    assert replacement["id"] != original["id"] and replacement["replaces_id"] == original["id"]
    assert replacement["body"] == "Daytime access only [s]."
    assert new_reviews[-1]["target"]["draft_id"] == replacement["id"]
    assert workspace.result(original["id"]) == original
    assert [r for r in workspace.results() if r["kind"] == "acceptance"] == [
        r for r in original_results if r["kind"] == "acceptance"]
    assert workspace.store.get("corrections")[0]["status"] == "addressed"
    assert recovery.tree_hashes(baseline.store.root) == original_tree


@pytest.mark.parametrize("mutation,error", [
    ("hash", "DRAFT_BODY_HASH_MISMATCH"),
    ("target", "EXACT_SELECTED_DRAFT_REQUIRED"),
    ("source", "SOURCE_HASH_MISMATCH"),
    ("foreign_source_path", "SOURCE_PATH_NOT_PROJECT_BOUND"),
    ("graph", "REQUIREMENT_ACCEPTANCE_WITHOUT_GRAPH_REQUIRED"),
    ("resume", "COMPLETED_SUCCESSFUL_BASELINE_REQUIRED"),
    ("interrupt", "COMPLETED_SUCCESSFUL_BASELINE_REQUIRED"),
    ("error", "COMPLETED_SUCCESSFUL_BASELINE_REQUIRED"),
    ("standard", "EXACT_HISTORICAL_SATISFIED_REVIEW_REQUIRED"),
    ("preview", "PREVIEW_PATH_NOT_BASELINE_BOUND"),
])
async def test_refuses_unsafe_preparation_without_changing_baseline(completed, tmp_path, mutation, error):
    workspace, draft, feedback = completed
    args = list(arguments(completed, tmp_path / "refused"))
    if mutation == "hash":
        args[-1] = "0" * 64
    elif mutation == "target":
        args[-2] = "different-draft"
    elif mutation == "source":
        (workspace.store.root / "sources/access.txt").write_text("Changed.")
    elif mutation == "foreign_source_path":
        manifest = workspace.store.manifest
        manifest["sources"][0]["copied_path"] = "../outside.txt"
        workspace.store.set("manifest", manifest)
    elif mutation == "graph":
        draft["fact_ids"] = ["unavailable-graph-fact"]
        with workspace.store.connect() as db:
            db.execute("UPDATE results SET data=? WHERE id=?", (encode(draft), draft["id"]))
    elif mutation in {"resume", "interrupt", "error"}:
        key, value = {"resume": ("checkpoint_resume", True), "interrupt": ("native_interrupts", [{"id": "pending"}]),
                      "error": ("report_error", {"type": "Unresolved"})}[mutation]
        workspace.store.set(key, value)
    elif mutation == "standard":
        record = next(r for r in workspace.results() if r["kind"] == "acceptance")
        body = json.loads(record["body"])
        body["criteria"][0]["condition"] = "Different standard."
        record["body"] = encode(body)
        with workspace.store.connect() as db:
            db.execute("UPDATE results SET data=? WHERE id=?", (encode(record), record["id"]))
    else:
        path = next((workspace.store.root / "previews").glob("*/summary.json"))
        data = json.loads(path.read_text())
        data["docx"]["path"] = str(tmp_path / "foreign/report.docx")
        path.write_text(encode(data))
    if mutation == "standard":
        from report_agent.review import review_delivery
        assert active_criteria(workspace)["current"] is True
        assert review_delivery(workspace, draft["id"])["status"] != "reviewed_draft"
    before = recovery.tree_hashes(workspace.store.root)
    feedback_before = feedback.read_bytes()
    with pytest.raises(ValueError, match=error):
        await recovery.prepare(*args)
    assert recovery.tree_hashes(workspace.store.root) == before
    if mutation in EARLY_VALIDATION_MUTATIONS:
        assert feedback.read_bytes() == feedback_before
        assert not args[1].exists()
    elif mutation in {"preview", "standard"}:
        assert feedback.read_bytes() == feedback_before
        assert (args[1] / "feedback-recovery-incomplete.json").is_file()
        assert not (args[1] / "feedback-recovery-receipt.json").exists()


async def test_native_pending_checkpoint_is_refused_even_when_public_flags_say_complete(completed, tmp_path):
    workspace, _, _ = completed
    async with _historical_completed_agent(workspace, lambda role: recovery.NoCallModel(),
                                         rules=criteria_rules(active_criteria(workspace))) as agent:
        await agent.aupdate_state({"configurable": {"thread_id": "report"}}, {},
                                  as_node="TodoListMiddleware.after_model")
    before = recovery.tree_hashes(workspace.store.root)
    target = tmp_path / "pending"
    with pytest.raises(ValueError, match="TERMINAL_CHECKPOINT_REQUIRED"):
        await recovery.prepare(*arguments(completed, target))
    assert recovery.tree_hashes(workspace.store.root) == before
    assert (target / "feedback-recovery-incomplete.json").is_file()
    assert not (target / "feedback-recovery-receipt.json").exists()


async def test_existing_nested_live_and_symlink_destinations_are_refused(completed, tmp_path):
    import fcntl

    workspace, _, feedback = completed
    before = recovery.tree_hashes(workspace.store.root)
    feedback_before = feedback.read_bytes()
    existing = tmp_path / "existing"
    existing.mkdir()
    for destination in (existing, workspace.store.root, workspace.store.root / "child", tmp_path):
        with pytest.raises(ValueError, match="NEW_ISOLATED_DESTINATION_REQUIRED"):
            await recovery.prepare(*arguments(completed, destination))
    parent = tmp_path / "link"
    parent.symlink_to(existing, target_is_directory=True)
    with pytest.raises(ValueError, match="SYMLINK_OR_JUNCTION_NOT_ALLOWED"):
        await recovery.prepare(*arguments(completed, parent / "new"))
    with (workspace.store.root / "run.lock").open("rb") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(RuntimeError, match="BASELINE_ALREADY_RUNNING"):
            await recovery.prepare(*arguments(completed, tmp_path / "live"))
    assert recovery.tree_hashes(workspace.store.root) == before
    assert feedback.read_bytes() == feedback_before
    assert not (tmp_path / "live").exists()


def test_backup_reads_committed_wal_without_creating_baseline_sidecars(tmp_path):
    baseline = tmp_path / "wal"
    baseline.mkdir()
    source = baseline / "state.db"
    with sqlite3.connect(source) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE evidence(value TEXT)")
        db.execute("INSERT INTO evidence VALUES ('committed in WAL')")
        db.commit()
        before = recovery.tree_hashes(baseline)
        recovery.backup(source, tmp_path / "copied.db")
        with sqlite3.connect(tmp_path / "copied.db") as copied:
            assert copied.execute("SELECT value FROM evidence").fetchone()[0] == "committed in WAL"
        assert recovery.tree_hashes(baseline) == before


from contextlib import asynccontextmanager


@asynccontextmanager
async def _historical_completed_agent(workspace, model_factory, *, rules=""):
    """Real historical topology for component tests; construction/inspection is read-only."""
    from inspect import iscoroutinefunction
    from langchain.agents import create_agent
    from langchain.agents.middleware import TodoListMiddleware
    from langchain_core.tools import StructuredTool
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from report_agent.review import native_review
    from report_agent.prompt_provenance import AgentPromptBoundary

    tools = [StructuredTool.from_function(coroutine=t) if iscoroutinefunction(t)
             else StructuredTool.from_function(t)
             for t in deep_runtime.business_tools(workspace, "coordinator", None, None)]
    async with AsyncSqliteSaver.from_conn_string(str(workspace.store.root / "checkpoints.db")) as saver:
        graph = create_agent(model=model_factory("coordinator"), tools=tools,
            system_prompt=SystemMessage(content=[
                {'type':'text','text':deep_runtime.COORDINATOR},
                {'type':'text','text':"\n" + deep_runtime.ACCEPTANCE_GUIDANCE}]),
            middleware=[TodoListMiddleware(), deep_runtime.BusinessBoundary(workspace, "coordinator"),
                native_review(workspace, model_factory("rubric_grader"), [], rules=rules),
                AgentPromptBoundary(workspace, "coordinator")],
            checkpointer=saver, name="report_coordinator")
        yield graph


async def _historical_completed_run(workspace, driver):
    from report_agent.acceptance import MODE, bind_mode
    from report_agent.review import reconcile_review, reviewer_prompt
    from report_agent.store import digest

    with workspace.store.run_lock():
        workspace.initialize()
        workspace.store.set("acceptance_default", MODE)
        assert bind_mode(workspace) == MODE
        workspace.store.set("active_reviewer_prompt_hash", digest(reviewer_prompt(requirement_acceptance=True)))
        criteria = active_criteria(workspace)
        rules = criteria_rules(criteria) if criteria else ""
        config = {"configurable": {"thread_id": "report"}}
        async with _historical_completed_agent(workspace, driver, rules=rules) as graph:
            await graph.ainvoke({"messages": [HumanMessage(content=encode(deep_runtime.project_view(workspace)))],
                "rubric": rules}, config)
            state = await graph.aget_state(config)
            assert not state.next and not state.interrupts
            workspace.store.set("checkpoint_resume", bool(state.next))
            workspace.store.set("native_interrupts", [{"id": i.id, "value": i.value} for i in state.interrupts])
            reconcile_review(workspace, state.values)
            result = project_state(workspace)
        # Truthful fixture provenance only after actual graph termination; never emitted by inspection.
        workspace.store.event("deep_run_finished", {"component_fixture": "historical-completed-recovery",
            "executed": True, "status": result["status"]})
        return result
