"""Offline business-boundary checks; no runtime scheduling or model calls."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from report_agent.catalog import Catalog
from report_agent.store import Store
from report_agent.workspace import OWNERS, Workspace


@pytest.fixture
def ws(tmp_path):
    store = Store(tmp_path)
    store.initialize({"goal": "Compile supplied access facts", "sources": [
        {"id": "facts", "title": "Facts", "content": "East entrance", "coverage": "complete"},
        {"id": "other", "title": "Other", "content": "Unrelated facts", "coverage": "complete"},
    ]})
    workspace = Workspace(store)
    workspace.initialize()
    return workspace


def submit(ws, task, *, sources=(), inputs=(), **kwargs):
    return ws.submit(task["id"], actor=task["owner"], title=task["goal"], body="Supplied facts",
                     source_ids=list(sources), input_ids=list(inputs), **kwargs)


def produce(ws, kind, goal, *, inputs=(), sources=(), observed=(), observed_sources=(), **kwargs):
    task = ws.request_task(kind, goal, list(inputs))
    ws.record_read(task["id"], result_ids=observed, source_ids=observed_sources)
    return submit(ws, task, sources=sources, **kwargs)


def replace_source(ws, previous="facts", text=b"East entrance; spelling clarified"):
    return Catalog(ws.store).import_file("facts.txt", text, replaces_id=previous)["source"]["id"]


def assess(ws, result, description="Changes do not affect the adopted facts"):
    return ws.assess_result_impact(result["id"], result["owner"], description)


def test_raw_source_to_exact_review_and_recovered_delivery_without_intermediates(ws):
    draft = produce(ws, "draft", "Compile directly", sources=["facts"])
    review = produce(ws, "review", "Check exact draft", inputs=[draft["id"]],
                     observed=[draft["id"]], target_id=draft["id"], outcome="accepted")
    assert [r["kind"] for r in ws.results()] == ["draft", "review"]
    assert ws.select_delivery(draft["id"], review["id"])["status"] == "reviewed_draft"
    recovered = Workspace(Store(ws.store.root))
    before = recovered.store.events()
    assert submit(recovered, recovered.task(draft["task_id"]), sources=["facts"]) == draft
    assert recovered.store.events() == before
    assert recovered.status()["delivery"]["review_id"] == review["id"]


@pytest.mark.parametrize("kind", ["purpose", "plan", "materials", "draft"])
def test_outcome_tags_accept_raw_sources_or_existing_outcomes_with_static_owners(ws, kind):
    basis = produce(ws, "draft", "Existing useful outcome", sources=["facts"])
    raw = produce(ws, kind, "Use original evidence", sources=["facts"])
    reused = produce(ws, kind, "Reuse useful outcome", inputs=[basis["id"]])
    assert raw["owner"] == reused["owner"] == OWNERS[kind]
    assert reused["source_ids"] == [] and reused["input_ids"] == [basis["id"]]


def test_undeclared_reads_never_become_revision_inputs_or_source_feedback(ws):
    adopted = produce(ws, "materials", "Adopted facts", sources=["facts"])
    observed = produce(ws, "plan", "Observed plan", sources=["other"])
    draft = produce(ws, "draft", "Compile", inputs=[adopted["id"]],
                    observed=[observed["id"]], observed_sources=["other"])
    replace_source(ws, "other")
    replacement = submit(ws, ws.request_revision(observed["id"], "Plan revision"), sources=["facts"])
    assert draft["id"] not in ws.impact()["affected_result_ids"]
    revision = ws.request_revision(draft["id"], "Improve wording")
    assert revision["input_ids"] == [adopted["id"]]
    assert replacement["id"] not in revision["input_ids"]
    assert revision["feedback"] == ["Improve wording"]


def test_review_observations_do_not_invalidate_exact_review(ws):
    draft = produce(ws, "draft", "Compile", sources=["facts"])
    review = produce(ws, "review", "Review", inputs=[draft["id"]], observed=[draft["id"]],
                     observed_sources=["other"], target_id=draft["id"], outcome="accepted")
    replace_source(ws, "other")
    change = ws.store.get("source_changes")[-1]
    ws.assess_source_change(change["id"], "The consulted source was not adopted")
    assert ws.delivery(draft["id"], review["id"])["status"] == "reviewed_draft"


def test_impact_assessment_is_owned_durable_idempotent_and_does_not_schedule(ws):
    material = produce(ws, "materials", "Facts", sources=["facts"])
    draft = produce(ws, "draft", "Compile", inputs=[material["id"]])
    source_id = replace_source(ws)
    before, tasks = ws.results(), ws.tasks()
    assert set(ws.impact()["needs_assessment_result_ids"]) == {material["id"], draft["id"]}
    with pytest.raises(PermissionError, match="OWNER"):
        ws.assess_result_impact(material["id"], "writer", "Bypass upstream ownership")
    saved = assess(ws, material)
    assert saved["snapshot"]["source_versions"] == {"facts": source_id}
    assert ws.impact()["needs_assessment_result_ids"] == [draft["id"]]
    assert ws.impact()["affected_task_ids"] == [draft["task_id"]]
    assert ws.results() == before and ws.tasks() == tasks
    reopened = Workspace(Store(ws.store.root))
    events = reopened.store.events()
    assert assess(reopened, material) == saved
    assert reopened.store.events() == events
    assert material["id"] in {r["id"] for r in reopened.current_results()}
    assert reopened.status()["result_impact_assessments"][material["id"]] == saved


def test_each_affected_producer_can_assess_without_rewriting_or_inheriting_a_review(ws):
    draft = produce(ws, "draft", "Compile", sources=["facts"])
    review = produce(ws, "review", "Review", inputs=[draft["id"]], observed=[draft["id"]],
                     target_id=draft["id"], outcome="accepted")
    replace_source(ws)
    ws.assess_source_change(ws.store.get("source_changes")[-1]["id"], "Check producer impact")
    before, tasks = ws.results(), ws.tasks()
    assess(ws, draft)
    delivery = ws.delivery(draft["id"], review["id"])
    assert delivery["status"] == "reviewed_draft"
    assert delivery["changes"]  # Change evidence, not automatic content rejection.
    assess(ws, review)
    assert ws.delivery(draft["id"], review["id"])["status"] == "reviewed_draft"
    assert ws.results() == before and ws.tasks() == tasks
    revised = submit(ws, ws.request_revision(draft["id"], "New wording"), sources=[ws.store.source_catalog()[-1]["id"]])
    with pytest.raises(ValueError, match="VERSION_MISMATCH"):
        ws.delivery(revised["id"], review["id"])
    with pytest.raises(ValueError, match="CURRENT_RESULT"):
        assess(ws, draft)
    assert draft["id"] not in {r["id"] for r in ws.current_results()}
    assert ws.delivery(revised["id"])["status"] == "unreviewed_draft"


def test_new_source_versions_invalidate_assessment_but_unadopted_changes_do_not(ws):
    draft = produce(ws, "draft", "Compile", sources=["facts"], observed_sources=["other"])
    second = replace_source(ws)
    assess(ws, draft)
    replace_source(ws, "other")
    assert draft["id"] not in ws.impact()["affected_result_ids"]
    third = replace_source(ws, second, b"Entrance remains east; timing changed")
    assert ws.impact()["needs_assessment_result_ids"] == [draft["id"]]
    assert assess(ws, draft)["snapshot"]["source_versions"] == {"facts": third}
    assert ws.impact()["needs_assessment_result_ids"] == []


def test_current_dependency_replacement_and_its_sources_invalidate_assessment(ws):
    material = produce(ws, "materials", "Facts", sources=["facts"])
    draft = produce(ws, "draft", "Compile", inputs=[material["id"]])
    replacement = submit(ws, ws.request_revision(material["id"], "Different evidence"), sources=["other"])
    assessment = assess(ws, draft)
    assert assessment["snapshot"]["result_versions"][material["id"]] == replacement["id"]
    assert draft["id"] not in ws.impact()["affected_result_ids"]
    newer_source = replace_source(ws, "other")
    assert draft["id"] in ws.impact()["needs_assessment_result_ids"]
    assess(ws, draft)
    newest = submit(ws, ws.request_revision(replacement["id"], "Another revision"), sources=[newer_source])
    assert draft["id"] in ws.impact()["needs_assessment_result_ids"]
    assert assess(ws, draft)["snapshot"]["result_versions"][material["id"]] == newest["id"]


def test_new_results_can_adopt_assessed_outcomes_until_an_actual_dependency_changes(ws):
    material = produce(ws, "materials", "Facts", sources=["facts"])
    second = replace_source(ws)
    assess(ws, material)
    draft = produce(ws, "draft", "Compile unchanged useful facts", inputs=[material["id"]])
    review = produce(ws, "review", "Review", inputs=[draft["id"]], observed=[draft["id"]],
                     target_id=draft["id"], outcome="accepted")
    assert not ws.impact()["needs_assessment_result_ids"]
    assert ws.impact()["affected_task_ids"] == []
    replace_source(ws, second, b"West entrance")
    assert set(ws.impact()["needs_assessment_result_ids"]) == {material["id"], draft["id"], review["id"]}


def test_relevant_additions_invalidate_previous_assessment_including_downstream(ws):
    material = produce(ws, "materials", "Facts", sources=["facts"])
    draft = produce(ws, "draft", "Compile", inputs=[material["id"]])
    assess(ws, material)
    assess(ws, draft)
    Catalog(ws.store).import_file("additional.txt", b"New potentially relevant facts")
    change = ws.store.get("source_changes")[-1]
    ws.assess_source_change(change["id"], "Relevant to adopted facts", [material["id"]])
    assert set(ws.impact()["needs_assessment_result_ids"]) == {material["id"], draft["id"]}
    assess(ws, material)
    assess(ws, draft)
    assert not ws.impact()["needs_assessment_result_ids"]
    replace_source(ws, change["source_id"], b"Additional facts revised")
    assert set(ws.impact()["needs_assessment_result_ids"]) == {material["id"], draft["id"]}


def test_assessment_cannot_resolve_corrections_or_accept_a_rejected_review(ws):
    draft = produce(ws, "draft", "Compile", sources=["facts"])
    review = produce(ws, "review", "Review", inputs=[draft["id"]], observed=[draft["id"]],
                     target_id=draft["id"], outcome="changes_required")
    ws.request_correction(draft["id"], "Correct wording")
    assess(ws, draft)
    assess(ws, review)
    assert ws.store.get("corrections")[0]["status"] == "pending"
    assert ws.delivery(draft["id"], review["id"])["status"] == "changes_required"


def test_human_context_is_exposed_without_automatic_content_rejection(ws):
    draft = produce(ws, "draft", "Compile", sources=["facts"])
    review = produce(ws, "review", "Review", inputs=[draft["id"]], observed=[draft["id"]],
                     target_id=draft["id"], outcome="accepted")
    issue = ws.issue("source_conflict", "Confirm scope", ["facts"])
    ws.decide_issue(issue["id"], "Use narrower scope", resolved=True)
    assess(ws, review)
    delivery = ws.delivery(draft["id"], review["id"])
    assert delivery["status"] == "reviewed_draft"
    assert delivery["changes"]["context_revision"] != delivery["changes"]["review_context_revision"]


@pytest.mark.parametrize("correction_target", ["original", "replacement"])
def test_assessed_history_cannot_bypass_corrections_on_current_dependency(ws, correction_target):
    material = produce(ws, "materials", "Facts", sources=["facts"])
    draft = produce(ws, "draft", "Compile", inputs=[material["id"]])
    review = produce(ws, "review", "Review", inputs=[draft["id"]], observed=[draft["id"]],
                     target_id=draft["id"], outcome="accepted")
    replacement = submit(ws, ws.request_revision(material["id"], "Improve facts"), sources=["facts"])
    assess(ws, draft)
    assess(ws, review)
    assert ws.delivery(draft["id"], review["id"])["status"] == "reviewed_draft"
    target = material if correction_target == "original" else replacement
    ws.request_correction(target["id"], "Late finding on current dependency")
    assert ws.delivery(draft["id"], review["id"])["status"] == "changes_required"
    assert ws.store.get("corrections")[0]["status"] == "pending"


@pytest.mark.parametrize("operation,event", [("assessment", "result_impact_assessed"), ("task", "task_created")])
def test_assessment_and_assignment_roll_back_with_audit(ws, operation, event):
    draft = produce(ws, "draft", "Compile", sources=["facts"])
    before, events = ws.status(), ws.store.events()
    with ws.store.connect() as db:
        db.execute(f"CREATE TRIGGER fail_audit BEFORE INSERT ON events WHEN NEW.kind='{event}' "
                   "BEGIN SELECT RAISE(ABORT, 'injected'); END")
    with pytest.raises(sqlite3.IntegrityError, match="injected"):
        if operation == "assessment":
            assess(ws, draft)
        else:
            ws.request_task("draft", "Another receipt", [])
    assert ws.status() == before and ws.store.events() == events


def test_concurrent_assignment_and_submission_share_one_business_receipt(ws):
    with ThreadPoolExecutor(max_workers=2) as pool:
        tasks = list(pool.map(lambda _: ws.request_task("draft", "Compile", []), range(2)))
        assert tasks[0] == tasks[1]
        results = list(pool.map(lambda _: submit(ws, tasks[0], sources=["facts"]), range(2)))
    assert results[0] == results[1]
    assert len(ws.tasks()) == len(ws.results()) == 1
    assert len([e for e in ws.store.events() if e["kind"] == "task_created"]) == 1
    assert len([e for e in ws.store.events() if e["kind"] == "result_committed"]) == 1


def test_invalid_assessments_and_forged_adopted_references_preserve_state(ws):
    draft = produce(ws, "draft", "Compile", sources=["facts"])
    task = ws.request_task("draft", "Another outcome", [])
    before, events = ws.status(), ws.store.events()
    for action in (lambda: ws.assess_result_impact("foreign", "writer", "Still usable"),
                   lambda: ws.assess_result_impact(draft["id"], "writer", " "),
                   lambda: submit(ws, task, inputs=["foreign"]),
                   lambda: submit(ws, task, sources=["foreign"])):
        with pytest.raises(ValueError):
            action()
    assert ws.status() == before and ws.store.events() == events
