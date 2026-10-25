"""SQL reference/receipt tests. Graph access validation belongs to the runtime boundary."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from report_agent.store import Store, digest, encode
from report_agent.workspace import Workspace


@pytest.fixture
def ws(tmp_path):
    store = Store(tmp_path)
    store.initialize({"goal": "Compile supplied facts", "sources": [
        {"id": "source", "title": "Source", "content": "Original evidence", "coverage": "complete"},
    ]})
    workspace = Workspace(store)
    workspace.initialize()
    return workspace


def commit(ws, task, **kwargs):
    return ws.commit(task["id"], actor=task["owner"], title=task["goal"], body="Report content",
                     source_ids=[], input_ids=[], **kwargs)


def produce(ws, goal, facts=(), inputs=()):
    return commit(ws, ws.request_task("draft", goal, list(inputs)), fact_ids=facts)


def test_explicit_fact_versions_are_canonical_and_persist_with_business_receipt(ws):
    task = ws.request_task("draft", "Compile", [])
    facts = ["fact-v2", "fact-v1", "fact-v2"]
    result = commit(ws, task, fact_ids=facts)
    assert result["fact_ids"] == ["fact-v1", "fact-v2"]
    assert facts == ["fact-v2", "fact-v1", "fact-v2"]
    assert result["source_ids"] == result["input_ids"] == []
    assert "fact_snapshot" not in result
    reopened = Workspace(Store(ws.store.root))
    assert reopened.result(result["id"]) == result
    assert reopened.task(task["id"])["result_id"] == result["id"]
    assert reopened.collect_fact_ids([result["id"]]) == ["fact-v1", "fact-v2"]
    assert reopened.status()["results"][0]["fact_ids"] == ["fact-v1", "fact-v2"]


def test_reference_replay_recovers_before_changed_context_without_graph_access(ws):
    task = ws.request_task("draft", "Compile", [])
    result = commit(ws, task, fact_ids=["fact-a", "fact-b"])
    ws.store.set("context_revision", 3)
    reopened = Workspace(Store(ws.store.root))
    before = reopened.store.events()
    assert commit(reopened, task, fact_ids=["fact-b", "fact-a", "fact-b"]) == result
    assert reopened.store.events() == before
    for facts in (["different-fact"], []):
        with pytest.raises(ValueError, match="ALREADY_COMMITTED"):
            commit(reopened, task, fact_ids=facts)
    assert reopened.result(result["id"]) == result


def test_existing_submit_entrypoint_accepts_the_same_optional_references(ws):
    task = ws.request_task("draft", "Compile", [])
    args = dict(actor="writer", title="Compile", body="Report content", source_ids=[], input_ids=[],
                fact_ids=["fact-v1"])
    result = ws.submit(task["id"], **args)
    assert ws.commit(task["id"], **args) == result


def test_legacy_receipt_without_fact_field_is_replayed_without_rewriting_it(ws):
    task = ws.request_task("draft", "Old caller", [])
    saved = commit(ws, task)
    # Reconstruct the pre-fact_ids record and operation hash in this test database.
    old_data = {k: v for k, v in saved.items() if k not in {"id", "operation", "fact_ids"}}
    old = {**old_data, "id": saved["id"], "operation": digest(old_data)}
    with ws.store.connect() as db:
        db.execute("UPDATE results SET operation=?,data=? WHERE id=?", (old["operation"], encode(old), old["id"]))
    before = ws.store.events()
    assert commit(ws, task) == old
    assert commit(ws, task, fact_ids=[]) == old
    assert ws.collect_fact_ids([old["id"]]) == []
    assert ws.store.events() == before
    with pytest.raises(ValueError, match="ALREADY_COMMITTED"):
        commit(ws, task, fact_ids=["new-fact"])


def test_transitive_collection_unions_only_adopted_exact_result_versions(ws):
    root = produce(ws, "Root", ["root-fact", "shared"])
    observed = produce(ws, "Read but not adopted", ["unadopted"])
    left = produce(ws, "Left", ["left-fact"], [root["id"]])
    right = produce(ws, "Right", ["right-fact", "shared"], [root["id"]])
    task = ws.request_task("draft", "Combined report", [left["id"], right["id"]])
    ws.record_read(task["id"], result_ids=[observed["id"]])
    draft = commit(ws, task, fact_ids=["report-fact"])
    check = ws.request_task("review", "Review exact report", [draft["id"]])
    ws.record_read(check["id"], result_ids=[draft["id"], observed["id"]])
    review = commit(ws, check, fact_ids=["review-fact"], target_id=draft["id"], outcome="accepted")
    expected = ["left-fact", "report-fact", "review-fact", "right-fact", "root-fact", "shared"]
    before, events = ws.results(), ws.store.events()
    assert ws.collect_fact_ids([review["id"]]) == expected
    assert ws.collect_fact_ids([draft["id"], review["id"], draft["id"]]) == expected
    assert ws.results() == before and ws.store.events() == events
    assert draft["fact_ids"] == ["report-fact"]  # No denormalized upstream facts.


def test_replacements_do_not_silently_remap_or_inherit_fact_adoption(ws):
    root = produce(ws, "Root", ["fact-version-1"])
    draft = produce(ws, "Consumer", ["direct-fact"], [root["id"]])
    replacement = commit(ws, ws.request_revision(root["id"], "Replace root"), fact_ids=["fact-version-2"])
    assert ws.collect_fact_ids([draft["id"]]) == ["direct-fact", "fact-version-1"]
    assert ws.collect_fact_ids([replacement["id"]]) == ["fact-version-2"]
    ws.assess_result_impact(draft["id"], "writer", "The adopted facts still support this text")
    assert ws.collect_fact_ids([draft["id"]]) == ["direct-fact", "fact-version-1"]
    assert ws.result(draft["id"]) == draft
    independent = commit(ws, ws.request_revision(replacement["id"], "No longer adopt graph facts"))
    assert independent["fact_ids"] == []
    assert ws.collect_fact_ids([independent["id"]]) == []


@pytest.mark.parametrize("facts", [None, "fact", {"fact": "body"}, [None], [1], [""], [" "], [" padded"],
                                    [{"id": "fact", "body": "Must remain in graph"}]])
def test_invalid_references_and_fact_bodies_are_rejected_atomically(ws, facts):
    task = ws.request_task("draft", "Compile", [])
    before, events = ws.status(), ws.store.events()
    with pytest.raises(ValueError, match="FACT_IDS"):
        commit(ws, task, fact_ids=facts)
    assert ws.status() == before and ws.store.events() == events


def test_fact_references_do_not_grant_producer_or_review_permissions(ws):
    task = ws.request_task("materials", "Upstream", [])
    with pytest.raises(PermissionError, match="OWNER"):
        ws.commit(task["id"], actor="writer", title="Attempt", body="Body", source_ids=[], input_ids=[],
                  fact_ids=["fact-version"])
    draft = produce(ws, "Compile", ["fact-version"])
    check = ws.request_task("review", "Exact review", [draft["id"]])
    with pytest.raises(ValueError, match="TARGET_NOT_OBSERVED"):
        commit(ws, check, fact_ids=["fact-version"], target_id=draft["id"], outcome="accepted")
    ws.record_read(check["id"], result_ids=[draft["id"]])
    review = commit(ws, check, target_id=draft["id"], outcome="accepted")
    another = produce(ws, "Another draft", ["fact-version"])
    with pytest.raises(ValueError, match="VERSION_MISMATCH"):
        ws.delivery(another["id"], review["id"])


@pytest.mark.parametrize("failure", ["receipt", "audit", "replacement"])
def test_fact_refs_result_and_receipt_roll_back_together(ws, failure):
    old = produce(ws, "Old", ["fact-old"])
    task = ws.request_revision(old["id"], "Replace") if failure == "replacement" else ws.request_task("draft", "New", [])
    trigger = {"receipt": "BEFORE UPDATE ON work_items",
               "audit": "BEFORE INSERT ON events WHEN NEW.kind='result_committed'",
               "replacement": "BEFORE INSERT ON result_replacements"}[failure]
    before, events = ws.status(), ws.store.events()
    with ws.store.connect() as db:
        db.execute(f"CREATE TRIGGER fail_commit {trigger} BEGIN SELECT RAISE(ABORT, 'injected'); END")
    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        commit(ws, task, fact_ids=["fact-new"], submission_id="atomic-submission")
    assert ws.status() == before and ws.store.events() == events
    assert ws.submission_receipt("atomic-submission") is None
    assert ws.collect_fact_ids([old["id"]]) == ["fact-old"]
    with ws.store.connect() as db:
        db.execute("DROP TRIGGER fail_commit")
    result = commit(ws, task, fact_ids=["fact-new"], submission_id="atomic-submission")
    assert ws.task(task["id"])["result_id"] == result["id"]
    assert ws.submission_receipt("atomic-submission") == result
    assert ws.collect_fact_ids([result["id"]]) == ["fact-new"]


def test_concurrent_identical_fact_submissions_recover_one_receipt(ws):
    task = ws.request_task("draft", "Compile", [])
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: commit(ws, task, fact_ids=["fact-a", "fact-b"]), range(2)))
    assert results[0] == results[1]
    assert len(ws.results()) == 1
    assert len([e for e in ws.store.events() if e["kind"] == "result_committed"]) == 1


def test_collection_rejects_foreign_roots_and_handles_no_graph_dependencies(ws, tmp_path):
    other_store = Store(tmp_path / "other")
    other_store.initialize(ws.store.manifest)
    other = Workspace(other_store)
    foreign = produce(other, "Foreign report", ["foreign-fact"])
    local = produce(ws, "Local report")
    assert ws.collect_fact_ids([]) == []
    assert ws.collect_fact_ids([local["id"]]) == []
    with pytest.raises(ValueError, match="RESULT_NOT_IN_PROJECT"):
        ws.collect_fact_ids([local["id"], foreign["id"]])
    with pytest.raises(ValueError, match="RESULT_IDS"):
        ws.collect_fact_ids(local["id"])


def test_submission_receipt_recovers_exact_result_without_graph_sources_or_new_task(ws, monkeypatch):
    task = ws.request_task("draft", "Compile", [])
    result = ws.submit(task["id"], actor="writer", title="Compile", body="Report content",
                       source_ids=["source"], input_ids=[], fact_ids=["fact-v1"], submission_id="raw-request-hash")
    ws.store.set("context_revision", 7)
    reopened = Workspace(Store(ws.store.root))
    tasks, events = reopened.tasks(), reopened.store.events()

    def unavailable(*args, **kwargs):
        raise AssertionError("Receipt recovery must not need graph/source/impact/task validation")

    monkeypatch.setattr(reopened.store, "sources", unavailable)
    monkeypatch.setattr(reopened, "impact", unavailable)
    monkeypatch.setattr(reopened, "request_task", unavailable)
    assert reopened.submission_receipt("raw-request-hash") == result
    assert reopened.submission_receipt("unknown") is None
    assert reopened.submission_receipt("") is None
    assert reopened.tasks() == tasks and reopened.store.events() == events
    # Normal task replay remains available even when the new key is omitted.
    assert reopened.commit(task["id"], actor="writer", title="Compile", body="Report content",
                           source_ids=["source"], input_ids=[], fact_ids=["fact-v1"]) == result


@pytest.mark.parametrize("change", [
    {"title": "Changed"}, {"body": "Changed"}, {"source_ids": ["source"]},
    {"input_ids": ["different-result"]}, {"fact_ids": ["different-fact"]},
    {"outcome": "accepted"}, {"target_id": "different-draft"},
])
def test_submission_id_collision_cannot_return_a_result_for_different_payload(ws, change):
    task = ws.request_task("draft", "Compile", [])
    args = dict(actor="writer", title="Compile", body="Report content", source_ids=[], input_ids=[],
                fact_ids=["fact-v1"], submission_id="same-key")
    result = ws.submit(task["id"], **args)
    before, events = ws.results(), ws.store.events()
    with pytest.raises(ValueError, match="SUBMISSION_ID_CONFLICT"):
        ws.submit(task["id"], **{**args, **change})
    assert ws.results() == before and ws.store.events() == events
    assert ws.submission_receipt("same-key") == result


def test_submission_id_is_bound_to_task_and_cannot_rebind_existing_commits(ws):
    task = ws.request_task("draft", "Compile", [])
    result = commit(ws, task, submission_id="first-key")
    with pytest.raises(ValueError, match="SUBMISSION_ID_MISMATCH"):
        commit(ws, task, submission_id="second-key")
    other = ws.request_task("draft", "Different task", [])
    with pytest.raises(ValueError, match="SUBMISSION_ID_CONFLICT"):
        ws.commit(other["id"], actor="writer", title="Compile", body="Report content",
                  source_ids=[], input_ids=[], submission_id="first-key")
    with pytest.raises(PermissionError, match="OWNER"):
        ws.commit(task["id"], actor="reviewer", title="Compile", body="Report content",
                  source_ids=[], input_ids=[], submission_id="first-key")
    legacy_task = ws.request_task("draft", "Legacy", [])
    legacy = commit(ws, legacy_task)
    assert "submission_id" not in legacy
    with pytest.raises(ValueError, match="SUBMISSION_ID_MISMATCH"):
        commit(ws, legacy_task, submission_id="late-key")
    assert commit(ws, legacy_task, submission_id="") == legacy
    assert ws.submission_receipt("second-key") is None and ws.submission_receipt("late-key") is None
    assert ws.submission_receipt("first-key") == result


def test_submission_receipt_retains_original_version_and_is_project_local(ws, tmp_path):
    task = ws.request_task("draft", "Original", [])
    original = commit(ws, task, submission_id="original-key")
    revision = ws.request_revision(original["id"], "Replace")
    replacement = commit(ws, revision, submission_id="replacement-key")
    assert ws.submission_receipt("original-key") == original
    assert ws.submission_receipt("replacement-key") == replacement
    assert commit(ws, revision, submission_id="replacement-key") == replacement
    other_store = Store(tmp_path / "other")
    other_store.initialize(ws.store.manifest)
    other = Workspace(other_store)
    assert other.submission_receipt("original-key") is None
    other_result = commit(other, other.request_task("draft", "Other project", []), submission_id="original-key")
    assert other.submission_receipt("original-key") == other_result
    assert ws.submission_receipt("original-key") == original


def test_submission_id_is_unique_in_sql_and_concurrent_replay_is_atomic(ws):
    task = ws.request_task("draft", "Compile", [])
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: commit(ws, task, fact_ids=["fact-v1"], submission_id="once"), range(2)))
    assert results[0] == results[1] == ws.submission_receipt("once")
    assert len(ws.results()) == 1
    assert len([e for e in ws.store.events() if e["kind"] == "result_committed"]) == 1
    duplicate = {**results[0], "id": "different-id", "operation": "different-operation"}
    with pytest.raises(sqlite3.IntegrityError):
        with ws.store.connect() as db:
            db.execute("INSERT INTO results VALUES (?, ?, ?)",
                       (duplicate["id"], duplicate["operation"], encode(duplicate)))
    assert ws.submission_receipt("once") == results[0]


@pytest.mark.parametrize("submission_id", [None, 123, [], " ", " padded", "trailing "])
def test_invalid_submission_ids_are_rejected_without_writes(ws, submission_id):
    task = ws.request_task("draft", "Compile", [])
    before, events = ws.results(), ws.store.events()
    with pytest.raises(ValueError, match="INVALID_SUBMISSION_ID"):
        commit(ws, task, submission_id=submission_id)
    with pytest.raises(ValueError, match="INVALID_SUBMISSION_ID"):
        ws.submission_receipt(submission_id)
    assert ws.results() == before and ws.store.events() == events
