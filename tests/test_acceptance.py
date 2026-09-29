"""Offline identity/permission/recovery evidence, not model-quality validation."""
import json

import pytest

from report_agent import acceptance
from report_agent.errors import ActionForbidden, ActionRejected
from report_agent.store import Store
from report_agent.workspace import Workspace


@pytest.fixture
def ws(tmp_path):
    store = Store(tmp_path)
    store.initialize({"goal": "Compile the office opening schedule.", "document_uses": {"s": "Schedule evidence"},
                      "sources": [{"id": "s", "title": "Schedule", "coverage": "complete",
                                   "content": "The office opens in daytime."}]})
    workspace = Workspace(store)
    workspace.initialize()
    return workspace


def request(**changes):
    return {"actor": "coordinator", "title": "Office schedule acceptance",
            "criteria": [{"condition": "The reported opening time agrees with the source.",
                          "requirement_refs": ["manifest.goal; source s: Schedule, opening-time statement"],
                          "allowed_limitations": "No unprovided holiday timetable is inferred."}],
            "source_ids": ["s"], "input_ids": [], "reason": "Derived from commission.", **changes}


def draft(ws, input_ids):
    task = ws.request_task("draft", "Office draft", input_ids)
    return ws.submit(task["id"], actor="writer", title="Schedule", body="Daytime opening.",
                     source_ids=["s"], input_ids=input_ids)


def test_save_replay_recovers_original_before_new_ids_and_current_basis(ws, monkeypatch):
    record = acceptance.save_criteria(ws, **request())
    before = ws.result(record["id"])
    ws.store.add_feedback("Use the schedule only as a pending-confirmation draft.")
    monkeypatch.setattr(acceptance, "uuid4", lambda: pytest.fail("Replay generated a new identity"))
    assert acceptance.save_criteria(ws, **request()) == record == before
    assert not acceptance.active_criteria(ws)["basis_current"]
    with pytest.raises(ActionRejected, match="BASIS_CHANGED"):
        acceptance.required_criteria(ws)
    assert len([r for r in ws.results() if r["kind"] == "acceptance"]) == 1


@pytest.mark.parametrize("actor", ["writer", "reviewer", "knowledge", "purpose"])
def test_only_coordinator_can_commit_and_replay(ws, actor):
    record = acceptance.save_criteria(ws, **request())
    with pytest.raises(ActionForbidden, match="OWNER_MISMATCH"):
        acceptance.save_criteria(ws, **request(actor=actor))
    assert acceptance.active_criteria(ws)["id"] == record["id"]


def test_generated_ids_history_and_exact_draft_binding(ws):
    first = acceptance.save_criteria(ws, **request())
    first_view = acceptance.active_criteria(ws)
    criterion = first_view["criteria"][0]
    assert criterion["id"].startswith("criterion_")
    original = draft(ws, [first["id"]])
    assert acceptance.draft_criteria(ws, original)["id"] == first["id"]
    second = acceptance.save_criteria(ws, **request(
        replaces_id=first["id"], reason="Clarify evidence expectation without changing the requirement.",
        criteria=[{**criterion, "evidence_expectation": "Located opening-time evidence."}]))
    assert second["replaces_id"] == first["id"]
    assert acceptance.active_criteria(ws)["criteria"][0]["id"] == criterion["id"]
    assert ws.result(first["id"]) == first
    assert acceptance.save_criteria(ws, **request()) == first
    with pytest.raises(ActionRejected, match="VERSION_MISMATCH"):
        acceptance.draft_criteria(ws, original)
    with pytest.raises(ActionRejected, match="REQUIRES_ACTIVE_VERSION"):
        acceptance.save_criteria(ws, **request(replaces_id=first["id"], reason="Stale edit"))
    with pytest.raises(ActionRejected, match="REVISION_REASON_REQUIRED"):
        acceptance.save_criteria(ws, **request(replaces_id=second["id"], reason=""))


@pytest.mark.parametrize("criterion", [
    {"condition": "Valid text", "requirement_refs": []},
    {"condition": "Valid text", "requirement_refs": [" "]},
    {"condition": " ", "requirement_refs": ["manifest.goal"]},
    {"id": "invented", "condition": "Valid text", "requirement_refs": ["manifest.goal"]},
])
def test_invalid_or_model_assigned_identity_rejected(ws, criterion):
    with pytest.raises(ActionRejected):
        acceptance.save_criteria(ws, **request(criteria=[criterion]))
    assert acceptance.active_criteria(ws) is None


def test_operator_decision_changes_basis_but_new_agent_issue_does_not(ws):
    record = acceptance.save_criteria(ws, **request())
    issue = ws.issue("source_conflict", "The holiday timetable is unclear.", ["s"])
    assert acceptance.required_criteria(ws)["id"] == record["id"]
    ws.decide_issue(issue["id"], "Holiday timetable is outside the commission.", resolved=True)
    with pytest.raises(ActionRejected, match="BASIS_CHANGED"):
        acceptance.required_criteria(ws)
    second = acceptance.save_criteria(ws, **request(replaces_id=record["id"], reason="Apply operator scope clarification."))
    assert acceptance.required_criteria(ws)["id"] == second["id"]


def test_source_replacement_exposes_stale_active_version(ws):
    from report_agent.catalog import Catalog
    record = acceptance.save_criteria(ws, **request())
    Catalog(ws.store).import_file("schedule.txt", b"New confirmed daytime schedule.", replaces_id="s")
    active = acceptance.active_criteria(ws)
    assert active["id"] == record["id"] and active["stale"] and not active["current"]
    with pytest.raises(ActionRejected, match="INPUTS_CHANGED"):
        acceptance.required_criteria(ws)


def test_revision_cannot_duplicate_ids_or_adopt_a_downstream_report(ws):
    first = acceptance.save_criteria(ws, **request())
    criterion = acceptance.active_criteria(ws)["criteria"][0]
    with pytest.raises(ActionRejected, match="DUPLICATE_ACCEPTANCE_CRITERION_ID"):
        acceptance.save_criteria(ws, **request(replaces_id=first["id"], criteria=[criterion, criterion]))
    saved = draft(ws, [first["id"]])
    with pytest.raises(ActionRejected, match="UPSTREAM_REQUIREMENT_INPUTS"):
        acceptance.save_criteria(ws, **request(replaces_id=first["id"], input_ids=[saved["id"]]))
    assert acceptance.active_criteria(ws)["id"] == first["id"]


@pytest.mark.parametrize("historic", ["runtime", "draft", "experiment"])
def test_policy_binding_preserves_historical_projects(ws, historic):
    if historic == "runtime":
        ws.store.set("runtime", "deepagents-0.7.19")
    elif historic == "draft":
        draft(ws, [])
    else:
        ws.store.set("review_context_experiment", "artifact_grounded_calibrated_compact_contract")
    assert acceptance.bind_mode(ws) == acceptance.LEGACY
    assert not acceptance.enabled(ws)
    with pytest.raises(ActionRejected, match="HISTORICAL_PROJECT"):
        acceptance.save_criteria(ws, **request())


@pytest.mark.parametrize("inspection", ["empty_file", "native_inspection"])
async def test_inspecting_new_project_does_not_disable_acceptance(ws, inspection):
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    checkpoint_path = ws.store.root / "checkpoints.db"
    if inspection == "empty_file":
        checkpoint_path.touch()
    else:
        async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
            assert await saver.aget_tuple({"configurable": {"thread_id": "inspection"}}) is None
    before = checkpoint_path.read_bytes()
    assert acceptance.bind_mode(ws) == acceptance.MODE
    assert checkpoint_path.read_bytes() == before
    with pytest.raises(ActionRejected, match="REQUIRED_BEFORE_DRAFT"):
        acceptance.required_criteria(ws)


async def test_actual_native_checkpoint_keeps_unbound_project_historical(ws):
    from langgraph.checkpoint.base import empty_checkpoint
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    checkpoint_path = ws.store.root / "checkpoints.db"
    async with AsyncSqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
        config = {"configurable": {"thread_id": "historical-run", "checkpoint_ns": ""}}
        await saver.aput(config, empty_checkpoint(), {"source": "input", "step": -1, "parents": {}}, {})
        # The read-only check must see committed WAL state while the saver is open.
        assert acceptance.bind_mode(ws) == acceptance.LEGACY
    assert not acceptance.enabled(ws)


def test_unreadable_checkpoint_does_not_silently_disable_new_acceptance(ws):
    (ws.store.root / "checkpoints.db").write_bytes(b"not a sqlite database")
    with pytest.raises(ActionRejected, match="CHECKPOINT_HISTORY_UNREADABLE"):
        acceptance.bind_mode(ws)
    assert ws.store.get("acceptance_mode") is None


def test_first_criteria_must_precede_draft_and_draft_needs_explicit_version(ws):
    assert acceptance.bind_mode(ws) == acceptance.MODE
    assert acceptance.bind_mode(ws) == acceptance.MODE
    with pytest.raises(ActionRejected, match="REQUIRED_BEFORE_DRAFT"):
        acceptance.required_criteria(ws)
    with pytest.raises(ActionRejected, match="ONE_EXPLICIT_ACCEPTANCE_VERSION"):
        draft(ws, [])
    # Even a trusted caller forcibly changing a historical mode cannot manufacture
    # evidence that criteria existed before this earlier report.
    ws.store.set("acceptance_mode", acceptance.LEGACY)
    old = draft(ws, [])
    ws.store.set("acceptance_mode", acceptance.MODE)
    with pytest.raises(ActionRejected, match="ONE_EXPLICIT_ACCEPTANCE_VERSION"):
        acceptance.draft_criteria(ws, old)
    with pytest.raises(ActionRejected, match="PRECEDE_FIRST_DRAFT"):
        acceptance.save_criteria(ws, **request())


def test_old_empty_workspace_without_creation_marker_stays_legacy(ws):
    with ws.store.connect() as db:
        db.execute("DELETE FROM state WHERE key='acceptance_default'")
    assert acceptance.bind_mode(ws) == acceptance.LEGACY


def test_references_are_project_scoped_and_rules_use_saved_criterion_id(ws):
    with pytest.raises(ActionRejected, match="SOURCE_NOT_IN_PROJECT"):
        acceptance.save_criteria(ws, **request(source_ids=["foreign"]))
    with pytest.raises(ActionRejected, match="RESULT_NOT_IN_PROJECT"):
        acceptance.save_criteria(ws, **request(input_ids=["foreign"]))
    record = acceptance.save_criteria(ws, **request())
    rules = acceptance.criteria_rules(record)
    criterion = json.loads(record["body"])["criteria"][0]
    assert criterion["id"] in rules and criterion["condition"] in rules
    assert acceptance.criteria_identity(record) == acceptance.criteria_identity(ws.result(record["id"]))
