import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from report_agent.store import Store, encode
from report_agent.workspace import Workspace


@pytest.fixture
def ws(tmp_path):
    store = Store(tmp_path)
    store.initialize({
        "goal": "Compile a synthetic access report", "document_uses": {"scope": "Report scope"},
        "sources": [
            {"id": "scope", "title": "Scope", "content": "Daytime access only", "coverage": "complete"},
            {"id": "facts", "title": "Facts", "content": "East entrance", "coverage": "partial"},
            {"id": "other", "title": "Other", "content": "Unrelated observation", "coverage": "complete"},
        ],
    })
    workspace = Workspace(store)
    workspace.initialize()
    return workspace


def commit(ws, task, *, sources=(), inputs=(), body="Synthetic result", **kwargs):
    return ws.submit(task["id"], actor=task["owner"], title=task["kind"], body=body,
                     source_ids=list(sources), input_ids=list(inputs), **kwargs)


def produce(ws, kind, goal, inputs=(), sources=(), observed=(), observed_sources=(), **kwargs):
    task = ws.request_task(kind, goal, list(inputs))
    ws.record_read(task["id"], result_ids=list(inputs) + list(observed), source_ids=observed_sources)
    return commit(ws, task, sources=sources, **kwargs)


def trunk(ws):
    purpose = next(r for r in ws.results() if r["kind"] == "purpose")
    material = produce(ws, "materials", "Summarize access", sources=["facts"])
    plan = produce(ws, "plan", "Plan report", inputs=[purpose["id"]])
    draft = produce(ws, "draft", "Draft report", inputs=[plan["id"], material["id"]])
    review = produce(ws, "review", "Review report", inputs=[draft["id"]],
                     outcome="accepted", target_id=draft["id"])
    ws.select_delivery(draft["id"], review["id"])
    return material, plan, draft, review


def add_source(ws, source_id="facts-v2", replaces_id="facts"):
    """Install the catalog contract directly; parser/import tests belong to Main."""
    source = {"id": source_id, "title": source_id, "coverage": "partial", "content": "New source text",
              "replaces_id": replaces_id, "document_id": replaces_id or source_id,
              "limitations": ["Synthetic partial source"]}
    with ws.store.connect() as db:
        db.execute("INSERT INTO source_versions VALUES (?, ?, ?, ?)",
                   (source_id, source_id, encode(source), b"New source text"))
    changes = ws.store.get("source_changes", [])
    change = {"id": "change-" + source_id, "source_id": source_id,
              "replaces_id": replaces_id, "assessment": None}
    ws.store.set("source_changes", changes + [change])
    return change


def test_producer_correction_is_addressed_not_resolved_and_remains_scoped(ws):
    material, plan, draft, review = trunk(ws)
    unrelated = produce(ws, "materials", "Unrelated materials", sources=["other"])
    before = ws.results()
    correction = ws.request_correction(material["id"], "Correct the entrance")
    assert correction["status"] == "pending" and not correction["resolved"]
    assert ws.request_correction(material["id"], "Correct the entrance") == correction
    task = ws.request_revision(material["id"], "Correct the entrance")
    assert task["kind"] == material["kind"] and task["owner"] == material["owner"]
    assert task["replaces_id"] == material["id"] and task["input_ids"] == []
    assert correction["id"] in task["correction_ids"]
    assert "Correct the entrance" in task["feedback"]
    assert ws.request_revision(material["id"], "Correct the entrance") == task
    ws.record_read(task["id"], result_ids=[material["id"]], source_ids=["facts"])
    replacement = commit(ws, task, sources=["facts"])
    assert replacement["replaces_id"] == material["id"]
    assert replacement["input_ids"] == replacement["observed_result_ids"] == []
    assert replacement["observed_history_result_ids"] == [material["id"]]
    assert ws.results()[:len(before)] == before
    resolved = ws.request_correction(material["id"], "Correct the entrance")
    assert resolved["id"] == correction["id"] and resolved["status"] == "addressed"
    assert resolved["resolved"] is False
    assert resolved["replacement_id"] == replacement["id"]
    assert resolved["resolution"] == "replacement_committed_pending_review"
    events = ws.store.events()
    assert sum(e["kind"] == "correction_addressed" for e in events) == 1
    assert not any(e["kind"] == "correction_resolved" for e in events)
    impact = ws.impact()
    assert impact["superseded_result_ids"] == [material["id"]]
    assert set(impact["stale_result_ids"]) == {draft["id"], review["id"]}
    assert set(impact["affected_task_ids"]) == {material["task_id"], draft["task_id"], review["task_id"]}
    assert {r["id"] for r in ws.current_results()} >= {replacement["id"], plan["id"], unrelated["id"]}
    assert ws.store.get("context_revision", 0) == 0
    assert len(ws.tasks()) == 6  # Only the explicitly requested revision was added.
    status = ws.status()
    by_id = {r["id"]: r for r in status["results"]}
    assert by_id[material["id"]]["superseded"]
    assert by_id[draft["id"]]["stale"] and not by_id[draft["id"]]["reusable"]
    assert by_id[replacement["id"]]["current"]
    assert status["delivery"]["status"] == "reviewed_draft"
    assert status["delivery"]["changes"]["pending_corrections"] == ws.store.get("corrections")
    assert draft["id"] in status["delivery"]["changes"]["changed_result_ids"]


def test_revision_consumers_use_latest_replacement_inputs_without_old_dependency(ws):
    material, plan, draft, review = trunk(ws)
    task = ws.request_revision(material["id"], "Update facts")
    first = commit(ws, task, sources=["facts"])
    task = ws.request_revision(first["id"], "Further update")
    second = commit(ws, task, sources=["facts"])
    revision = ws.request_revision(draft["id"], "Apply corrected facts")
    assert set(revision["input_ids"]) == {plan["id"], second["id"]}
    ws.record_read(revision["id"], result_ids=revision["input_ids"] + [draft["id"], material["id"]])
    new_draft = commit(ws, revision)
    assert set(new_draft["observed_history_result_ids"]) == {draft["id"], material["id"]}
    assert new_draft["id"] not in ws.impact()["affected_result_ids"]
    assert ws.delivery(new_draft["id"])["status"] == "unreviewed_draft"
    check = ws.request_revision(review["id"], "Review the exact updated draft")
    assert check["input_ids"] == [new_draft["id"]]
    ws.record_read(check["id"], result_ids=check["input_ids"])
    new_review = commit(ws, check, outcome="accepted", target_id=new_draft["id"])
    assert ws.select_delivery(new_draft["id"], new_review["id"])["status"] == "reviewed_draft"


def test_only_adopted_dependencies_and_unfinished_tasks_are_affected(ws):
    root = produce(ws, "materials", "Root", sources=["facts"])
    observed = produce(ws, "materials", "Observed only", sources=["other"], observed=[root["id"]])
    child = produce(ws, "materials", "Transitive child", sources=["other"], inputs=[observed["id"]])
    pending = ws.request_task("materials", "Work still pending", [])
    ws.record_read(pending["id"], result_ids=[child["id"]])
    adopted = produce(ws, "materials", "Adopted root", inputs=[root["id"]])
    dependent = ws.request_task("draft", "Work adopting the root", [root["id"]])
    snapshot = ws.tasks()
    revision = ws.request_revision(root["id"], "Root correction")
    commit(ws, revision, sources=["facts"])
    impact = ws.impact()
    assert impact["stale_result_ids"] == [adopted["id"]]
    assert pending["id"] not in impact["affected_task_ids"]
    assert dependent["id"] in impact["affected_task_ids"]
    assert ws.tasks()[:len(snapshot)] == snapshot
    assert ws.request_task("materials", "Observed only", [])["result_id"] == observed["id"]
    task = ws.request_task("materials", "Adopt old output", [adopted["id"]])
    assert task["input_changes"]["changed_result_ids"] == [adopted["id"]]
    assert ws.request_task("materials", "Adopted root", [root["id"]])["result_id"] == adopted["id"]
    assert ws.request_revision(observed["id"], "Improve independent result")["input_ids"] == []


def test_exact_target_and_owner_are_bound_and_replacement_cannot_fork(ws):
    old = produce(ws, "materials", "First", sources=["facts"])
    other = produce(ws, "materials", "Second", sources=["other"])
    first = ws.request_revision(old["id"], "Correction one")
    competing = ws.request_revision(old["id"], "Correction two")
    for changes in ({"owner": "writer"}, {"replaces_id": other["id"]}, {"input_ids": [other["id"]]}):
        with pytest.raises(PermissionError, match="TASK_BINDING"):
            ws.update_task(first["id"], **changes)
    with pytest.raises(PermissionError, match="OWNER"):
        ws.submit(first["id"], actor="writer", title="materials", body="Wrong owner", source_ids=["facts"], input_ids=[])
    with pytest.raises(ValueError, match="PREDECESSOR"):
        commit(ws, first, sources=["facts"], inputs=[old["id"]])
    saved = commit(ws, first, sources=["facts"])
    with pytest.raises(ValueError, match="CURRENT_RESULT"):
        commit(ws, competing, sources=["facts"])
    with pytest.raises(ValueError, match="CURRENT_RESULT"):
        ws.request_revision(old["id"], "A third correction")
    assert ws.result(other["id"]) == other
    assert ws.impact()["replacements"] == {old["id"]: saved["id"]}


def test_replay_recovers_receipt_before_freshness_checks_after_reopening(ws):
    old = produce(ws, "materials", "First", sources=["facts"])
    revision = ws.request_revision(old["id"], "Correct")
    replacement = commit(ws, revision, sources=["facts"])
    add_source(ws)
    next_revision = ws.request_revision(replacement["id"], "Use new source")
    commit(ws, next_revision, sources=["facts-v2"])
    reopened = Workspace(Store(ws.store.root))
    before = reopened.store.events()
    assert commit(reopened, revision, sources=["facts"]) == replacement
    assert reopened.request_revision(old["id"], "Correct")["result_id"] == replacement["id"]
    assert reopened.store.events() == before
    with pytest.raises(ValueError, match="ALREADY_COMMITTED"):
        commit(reopened, revision, sources=["facts"], body="Changed")


@pytest.mark.parametrize("failure", ["relation", "receipt", "correction", "audit"])
def test_replacement_rolls_back_result_relation_corrections_receipt_and_audit(ws, failure):
    old = produce(ws, "materials", "Initial", sources=["facts"])
    ws.request_correction(old["id"], "Correct")
    task = ws.request_revision(old["id"], "Correct")
    before, events = ws.status(), ws.store.events()
    trigger = {
        "relation": "BEFORE INSERT ON result_replacements",
        "receipt": "BEFORE UPDATE ON work_items",
        "correction": "BEFORE INSERT ON events WHEN NEW.kind='correction_addressed'",
        "audit": "BEFORE INSERT ON events WHEN NEW.kind='result_committed'",
    }[failure]
    with ws.store.connect() as db:
        db.execute(f"CREATE TRIGGER fail_commit {trigger} BEGIN SELECT RAISE(ABORT, 'injected'); END")
    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        commit(ws, task, sources=["facts"])
    assert ws.status() == before
    assert ws.store.events() == events
    with ws.store.connect() as db:
        db.execute("DROP TRIGGER fail_commit")
    result = commit(ws, task, sources=["facts"])
    assert ws.task(task["id"])["result_id"] == result["id"]
    assert ws.store.get("corrections")[0]["replacement_id"] == result["id"]


def test_repeated_concurrent_submissions_share_one_receipt(ws):
    old = produce(ws, "materials", "First", sources=["facts"])
    with ThreadPoolExecutor(max_workers=2) as pool:
        requests = list(pool.map(lambda _: ws.request_revision(old["id"], "Correct"), range(2)))
        assert requests[0]["id"] == requests[1]["id"]
        results = list(pool.map(lambda _: commit(ws, requests[0], sources=["facts"]), range(2)))
    assert results[0] == results[1]
    assert len(ws.impact()["replacements"]) == 1
    assert len([e for e in ws.store.events() if e["kind"] == "result_replaced"]) == 1


def test_correction_addresses_only_the_bound_result_and_captured_feedback(ws):
    old = produce(ws, "materials", "First", sources=["facts"])
    other = produce(ws, "materials", "Other", sources=["other"])
    captured = ws.request_correction(old["id"], "First finding")
    unrelated = ws.request_correction(other["id"], "Other finding")
    task = ws.request_revision(old["id"], "Apply feedback")
    later = ws.request_correction(old["id"], "New finding after assignment")
    replacement = commit(ws, task, sources=["facts"])
    corrections = {c["id"]: c for c in ws.store.get("corrections")}
    assert corrections[captured["id"]]["status"] == "addressed"
    assert corrections[captured["id"]]["resolved"] is False
    assert corrections[unrelated["id"]]["status"] == corrections[later["id"]]["status"] == "pending"
    followup = ws.request_revision(replacement["id"], "Address the late finding")
    assert later["id"] in followup["correction_ids"]
    assert "New finding after assignment" in followup["feedback"]
    newest = commit(ws, followup, sources=["facts"])
    resolved = ws.request_correction(old["id"], "New finding after assignment")
    assert resolved["result_id"] == old["id"] and resolved["replacement_id"] == newest["id"]
    assert resolved["status"] == "addressed" and resolved["resolved"] is False


def test_source_supersession_propagates_only_adopted_sources(ws):
    material, plan, draft, review = trunk(ws)
    observed = produce(ws, "materials", "Read extra source", sources=["other"], observed_sources=["facts"])
    pending = ws.request_task("materials", "Pending source reader", [])
    ws.record_read(pending["id"], source_ids=["facts"])
    change = add_source(ws)
    impact = ws.impact()
    assert impact["superseded_source_ids"] == ["facts"]
    assert set(impact["stale_result_ids"]) == {material["id"], draft["id"], review["id"]}
    assert observed["id"] not in impact["affected_result_ids"]
    assert pending["id"] not in impact["affected_task_ids"]
    assert plan["id"] not in impact["affected_result_ids"]
    assert ws.status()["status"] == "reviewed_draft"
    assert ws.status()["delivery"]["changes"]["source_changes"] == [change]
    ws.assess_source_change(change["id"], "Relevant to the access facts")
    assert ws.impact() == impact
    assert ws.status()["status"] == "reviewed_draft"
    assert ws.store.sources(["facts"])[0]["content"] == "East entrance"
    metadata = {s["id"]: s for s in ws.status()["sources"]}
    assert not metadata["facts"]["current"] and metadata["facts-v2"]["current"]
    assert metadata["facts-v2"]["limitations"] == ["Synthetic partial source"]


def test_producer_can_compare_old_and_new_sources_without_adopting_history(ws):
    material = produce(ws, "materials", "Facts", sources=["facts"], observed_sources=["facts"])
    add_source(ws)
    task = ws.request_revision(material["id"], "Reconcile the factual update")
    assert "facts" in " ".join(task["feedback"])
    assert "not automatically remapped" in " ".join(task["feedback"])
    assert not task["used_source_ids"]
    ws.record_read(task["id"], result_ids=[material["id"]], source_ids=["facts", "facts-v2"])
    result = commit(ws, task, sources=["facts-v2"])
    assert result["source_ids"] == result["observed_source_ids"] == ["facts-v2"]
    assert result["observed_history_source_ids"] == ["facts"]
    assert result["observed_history_result_ids"] == [material["id"]]
    assert ws.task(task["id"])["used_source_ids"] == ["facts", "facts-v2"]
    assert task["id"] not in ws.impact()["affected_task_ids"]
    assert result["id"] in {r["id"] for r in ws.current_results()}
    assert ws.result(material["id"]) == material
    add_source(ws, "facts-v3", "facts-v2")
    assert result["id"] in ws.impact()["stale_result_ids"]


def test_declared_historical_input_is_saved_with_change_evidence(ws):
    old = produce(ws, "materials", "Old", sources=["facts"])
    replacement = commit(ws, ws.request_revision(old["id"], "Correct"), sources=["facts"])
    task = ws.request_task("materials", "Compare previous output", [])
    ws.record_read(task["id"], result_ids=[old["id"], replacement["id"]])
    result = commit(ws, task, sources=["facts"], inputs=[old["id"]])
    assert result["input_ids"] == [old["id"]]
    assert result["input_changes"]["result_replacements"] == {old["id"]: replacement["id"]}
    assert result["input_changes"]["changed_result_ids"] == [old["id"]]
    assert result["input_changes"]["meaning"] == "change_evidence_only_not_validity"
    assert result["observed_result_ids"] == [replacement["id"]]
    assert result["observed_history_result_ids"] == [old["id"]]
    assert task["id"] not in ws.impact()["affected_task_ids"]


def test_unrelated_addition_only_needs_assessment_and_does_not_invalidate_valid_delivery(ws):
    _, _, draft, review = trunk(ws)
    before, context = ws.results(), ws.store.get("context_revision", 0)
    change = add_source(ws, "unrelated-new", "")
    assert ws.status()["status"] == "reviewed_draft"
    assert ws.status()["delivery"]["changes"]["source_changes"] == [change]
    assert ws.impact()["affected_result_ids"] == []
    assessment = ws.assess_source_change(change["id"], "Outside this report's existing scope")
    assert assessment["assessment"]["meaning"] == "relevance_considered_only"
    events = ws.store.events()
    assert ws.assess_source_change(change["id"], "Outside this report's existing scope") == assessment
    assert ws.store.events() == events
    assert ws.delivery(draft["id"], review["id"])["status"] == "reviewed_draft"
    assert ws.status()["status"] == "reviewed_draft"
    assert ws.results() == before and ws.store.get("context_revision", 0) == context
    assert ws.store.manifest["goal"] == "Compile a synthetic access report"


def test_relevant_addition_marks_selected_results_and_consumers_until_replaced(ws):
    material, plan, draft, review = trunk(ws)
    change = add_source(ws, "additional-facts", "")
    before = ws.results()
    assessment = ws.assess_source_change(change["id"], "Adds information needed by the materials", [material["id"]])
    assert assessment["affected_result_ids"] == [material["id"]]
    assert set(ws.impact()["stale_result_ids"]) == {material["id"], draft["id"], review["id"]}
    assert plan["id"] not in ws.impact()["affected_result_ids"]
    assert ws.status()["status"] == "reviewed_draft"
    assert draft["id"] in ws.status()["delivery"]["changes"]["changed_result_ids"]
    assert ws.results() == before
    events = ws.store.events()
    assert ws.assess_source_change(change["id"], "Adds information needed by the materials",
                                   [material["id"], material["id"]]) == assessment
    assert ws.store.events() == events
    ws.assess_source_change(change["id"], "Assessment is not semantic validation", [])
    assert material["id"] in ws.impact()["stale_result_ids"]
    task = ws.request_revision(material["id"], "Include newly supplied facts")
    ws.record_read(task["id"], source_ids=["facts", "additional-facts"])
    replacement = commit(ws, task, sources=["facts", "additional-facts"])
    assert replacement["id"] not in ws.impact()["affected_result_ids"]
    assert {draft["id"], review["id"]} <= set(ws.impact()["stale_result_ids"])
    assert ws.store.get("context_revision", 0) == 0


def test_assessment_rejects_foreign_result_and_preserves_previous_state(ws):
    change = add_source(ws, "new", "")
    before, events = ws.status(), ws.store.events()
    with pytest.raises(ValueError, match="RESULT_NOT_IN_PROJECT"):
        ws.assess_source_change(change["id"], "Cannot adopt foreign work", ["foreign-result"])
    assert ws.status() == before and ws.store.events() == events


@pytest.mark.parametrize("category,expected", [("source_conflict", "needs_human"),
                                              ("source_missing", "needs_human"), ("system_failure", "system_error")])
def test_source_issues_take_priority_over_unassessed_additions(ws, category, expected):
    trunk(ws)
    add_source(ws, "new", "")
    ws.issue(category, "Needs explicit handling", ["facts"])
    assert ws.status()["status"] == expected


def test_review_source_change_is_evidence_not_automatic_rejection(ws):
    _, _, draft, review = trunk(ws)
    reader = ws.task(review["task_id"])
    # A separate review explicitly adopts a source, without changing the draft.
    new_review = produce(ws, "review", "Additional source check", inputs=[draft["id"]],
                         sources=["other"], observed_sources=["other"], outcome="accepted", target_id=draft["id"])
    change = add_source(ws, "other-v2", "other")
    ws.assess_source_change(change["id"], "Reviewer used this source")
    assert draft["id"] not in ws.impact()["stale_result_ids"]
    assert new_review["id"] in ws.impact()["stale_result_ids"]
    delivery = ws.delivery(draft["id"], reader["result_id"])
    assert delivery["status"] == "reviewed_draft"
    assert delivery["review_id"] == new_review["id"]
    assert delivery["changes"]["source_replacements"] == {"other": "other-v2"}


@pytest.mark.parametrize("operation,event", [("revision", "revision_requested"),
                                           ("correction", "correction_requested"),
                                           ("assessment", "source_change_assessed")])
def test_request_and_assessment_audit_failures_roll_back(ws, operation, event):
    old = produce(ws, "materials", "Initial", sources=["facts"])
    change = add_source(ws, "new", "")
    before, events = ws.status(), ws.store.events()
    with ws.store.connect() as db:
        db.execute(f"CREATE TRIGGER fail_audit BEFORE INSERT ON events WHEN NEW.kind='{event}' "
                   "BEGIN SELECT RAISE(ABORT, 'injected'); END")
    action = {"revision": lambda: ws.request_revision(old["id"], "Correct"),
              "correction": lambda: ws.request_correction(old["id"], "Correct"),
              "assessment": lambda: ws.assess_source_change(change["id"], "Relevant", [old["id"]])}[operation]
    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        action()
    assert ws.status() == before and ws.store.events() == events


def test_invalid_requests_preserve_state(ws):
    old = produce(ws, "materials", "Initial", sources=["facts"])
    before = ws.status()
    for action in (lambda: ws.request_revision(old["id"], " "),
                   lambda: ws.request_correction(old["id"], " "),
                   lambda: ws.request_revision("foreign-result", "Correct"),
                   lambda: ws.assess_source_change("unknown", "Considered"),
                   lambda: ws.assess_source_change("unknown", " ")):
        with pytest.raises(ValueError):
            action()
    assert ws.status() == before


def test_superseded_source_can_be_saved_without_remapping_or_losing_audit(ws):
    old = produce(ws, "materials", "Original evidence", sources=["facts"])
    task = ws.request_task("draft", "Historical comparison", [old["id"]])
    add_source(ws)
    before = ws.results()
    ws.record_read(task["id"], result_ids=[old["id"]], source_ids=["facts", "facts-v2"])
    result = commit(ws, task, sources=["facts"])
    assert result["source_ids"] == ["facts"]
    assert result["input_ids"] == [old["id"]]
    assert result["observed_history_source_ids"] == ["facts"]
    assert result["observed_source_ids"] == ["facts-v2"]
    assert result["observed_history_result_ids"] == [old["id"]]
    assert result["input_changes"]["source_replacements"] == {"facts": "facts-v2"}
    assert result["input_changes"]["changed_result_ids"] == [old["id"]]
    assert result["dependency_snapshot"]["source_versions"]["facts"] == "facts-v2"
    assert ws.results()[:len(before)] == before
    assert ws.store.sources(["facts"])[0]["content"] == "East entrance"
    reopened = Workspace(Store(ws.store.root))
    events = reopened.store.events()
    assert commit(reopened, task, sources=["facts"]) == result
    assert reopened.store.events() == events


def test_changed_sources_do_not_relax_owner_or_project_existence_checks(ws):
    old = produce(ws, "materials", "Original evidence", sources=["facts"])
    add_source(ws)
    task = ws.request_task("draft", "Historical comparison", [old["id"]])
    before, events = ws.results(), ws.store.events()
    with pytest.raises(PermissionError, match="RESULT_OWNER_MISMATCH"):
        ws.submit(task["id"], actor="reviewer", title="Wrong owner", body="Not authorized",
                  source_ids=["facts"], input_ids=[])
    with pytest.raises(ValueError, match="SOURCE_NOT_IN_PROJECT"):
        commit(ws, task, sources=["foreign-source"])
    with pytest.raises(ValueError, match="RESULT_NOT_IN_PROJECT"):
        commit(ws, task, sources=["facts"], inputs=["foreign-result"])
    with pytest.raises(ValueError, match="RESULT_NOT_IN_PROJECT"):
        ws.request_task("draft", "Foreign dependency", ["foreign-result"])
    assert ws.results() == before and ws.store.events() == events
    assert ws.task(task["id"])["result_id"] is None


def test_pending_correction_is_still_visible_and_never_blocks_saving(ws):
    _, _, draft, _ = trunk(ws)
    correction = ws.request_correction(draft["id"], "Check the scope")
    review = produce(ws, "review", "Assess pending correction", inputs=[draft["id"]],
                     target_id=draft["id"], outcome="changes_required")
    delivery = ws.delivery(draft["id"], review["id"])
    assert delivery["changes"]["pending_corrections"][0]["id"] == correction["id"]
    assert delivery["status"] == "changes_required"
    assert ws.store.get("corrections")[0]["resolved"] is False
