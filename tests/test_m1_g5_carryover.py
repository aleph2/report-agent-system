"""G5 J3 carryover is a source-bound proposal requiring fresh explicit review."""
from copy import deepcopy
from importlib import import_module

import pytest

from report_agent import commission_imports, plan_authority, plan_inputs
from report_agent.errors import ActionRejected, ActionForbidden
from report_agent.content_models import Ref
from test_m1_g5_j2 import skeleton_case, entries, required_case, anchored, method_commission, ws
from test_m1_g4_planning_steps import planning, source_pins


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    import httpx
    def denied(*args, **kwargs):
        raise AssertionError("G5_CARRYOVER_NETWORK_FORBIDDEN")
    monkeypatch.setattr(httpx.Client, "send", denied)
    monkeypatch.setattr(httpx.AsyncClient, "send", denied)


def carry():
    return import_module("report_agent.commission_carryover")


@pytest.fixture
def carry_case(skeleton_case):
    f = skeleton_case
    import_module("report_agent.commission_skeleton").prepare_skeleton(f.cs, f.skeleton_refs, f.skeleton_spec)
    return package_case(f)


def package_case(f):
    section = next(s for s in f.plan["sections"] if s["section_id"] == "4")
    judgments = {"objects": [deepcopy(f.plan["objects"][0])],
        "reconciliations": [deepcopy(f.plan["reconciliations"][0])], "questions": [],
        "section_source_choices": [{"section_id": "4", "sources": deepcopy(section["sources"]),
            "examples": [], "rule": section.get("rule", "")}]}
    pins = source_pins(f, judgments)
    mapping = {Ref.model_validate(pin["ref"]).key(): {"type": "SourceArtifact", "id": "prior-source-" + str(i), "version": 7}
               for i, pin in enumerate(pins)}
    def historical(value):
        if isinstance(value, dict):
            return {key: deepcopy(mapping[Ref.model_validate(child).key()]) if key == "source_ref" else historical(child)
                    for key, child in value.items()}
        return [historical(child) for child in value] if isinstance(value, list) else value
    f.package = {"contract": "judgment-carryover-v1", "origin": {"run": "synthetic-prior-run"},
        "source_pins": [{"ref": mapping[Ref.model_validate(pin["ref"]).key()], "file_digest": pin["file_digest"]} for pin in pins],
        "judgments": historical(judgments)}
    f.current_judgments = judgments
    return f


def install(f, package=None):
    return carry().install_carryover(f.cs, deepcopy(f.package if package is None else package), f.skeleton_refs)


def view(f):
    return planning().read_draft(f.cs, f.co)


def review_all(f, status="confirmed", note="", operation="review-carried"):
    return carry().review_carried_items(f.cs, f.co, operation, [
        {"item_id": row["item_id"], "expected_digest": row["current_digest"], "status": status, "note": note}
        for row in view(f)["plan"]["carried_items"]])


def test_import_remaps_sources_by_unique_hash_and_preserves_unapproved_proposals(carry_case):
    f = carry_case
    fingerprint = install(f)
    plan = view(f)["plan"]
    assert plan["carryover_digest"] == fingerprint
    assert len(plan["carried_items"]) == 3
    assert all(row["status"] == "proposed" for row in plan["carried_items"])
    assert plan["objects"][0]["sources"] == f.current_judgments["objects"][0]["sources"]
    assert "prior-source-" not in str(plan)
    assert not plan_authority.plan_ref(f.cs.store)
    assert not plan_authority.decision_ref(f.cs.store)
    assert install(f) == fingerprint


def test_unreviewed_carried_items_block_submission_with_named_gaps(carry_case):
    f = carry_case
    install(f)
    with pytest.raises(ActionRejected) as exc:
        planning().submit_plan(f.cs, f.co, "unreviewed-carry-submit")
    gaps = exc.value.diagnostic["gaps"]
    assert sum(gap["code"] == "CARRYOVER_REVIEW_REQUIRED" for gap in gaps) == 3


def test_review_view_exposes_original_and_current_proposals(carry_case):
    f = carry_case
    install(f)
    page = planning().read_draft_page(f.cs, f.co, "carried_items", page_size=5)
    assert "original" in str(page) and "current" in str(page)
    assert "initial_digest" in str(page)


def test_confirming_every_current_projection_is_not_plan_approval(carry_case):
    f = carry_case
    install(f)
    reviews = [{"item_id": row["item_id"], "expected_digest": row["current_digest"], "status": "confirmed", "note": ""}
        for row in view(f)["plan"]["carried_items"]]
    tool = next(fx for fx in planning().planning_tools(f.cs, lambda: f.co) if fx.__name__ == 'review_carried_items')
    result = tool(operation_id='review-carried', reviews=reviews)
    assert result['result']['reviewed'] == len(reviews)
    assert result == f.cs.receipt(f.co, 'review-carried')['response']
    assert all(row["status"] == "confirmed" for row in view(f)["plan"]["carried_items"])
    assert not plan_authority.decision_ref(f.cs.store)


def test_edit_after_review_invalidates_only_the_affected_object_review(carry_case):
    f = carry_case
    install(f)
    review_all(f)
    obj = deepcopy(view(f)["plan"]["objects"][0])
    obj["label"] += " revised"
    planning().save_item(f.cs, f.co, "edit-carried-object", "object", obj)
    rows = view(f)["plan"]["carried_items"]
    assert next(row for row in rows if row["kind"] == "object")["status"] == "proposed"
    assert all(row["status"] == "confirmed" for row in rows if row["kind"] != "object")


@pytest.mark.parametrize("status,note", [("confirmed", ""), ("revised", " ")])
def test_changed_proposal_needs_revised_status_and_reason(carry_case, status, note):
    f = carry_case
    install(f)
    obj = deepcopy(view(f)["plan"]["objects"][0]);obj["label"] += " revised"
    planning().save_item(f.cs, f.co, "edit-before-review", "object", obj)
    row = next(row for row in view(f)["plan"]["carried_items"] if row["kind"] == "object")
    with pytest.raises(ActionRejected):
        carry().review_carried_items(f.cs, f.co, "invalid-revision-review", [{"item_id": row["item_id"],
            "expected_digest": row["current_digest"], "status": status, "note": note}])


def test_revised_current_judgment_with_reason_can_be_reviewed(carry_case):
    f = carry_case
    install(f)
    obj = deepcopy(view(f)["plan"]["objects"][0]);obj["label"] += " revised"
    planning().save_item(f.cs, f.co, "edit-reasoned", "object", obj)
    review_all(f, "revised", "Verified against current citations and owner scope.")
    assert all(row["status"] == "revised" for row in view(f)["plan"]["carried_items"])


@pytest.mark.parametrize("fault", ["stale", "unknown", "duplicate", "empty"])
def test_review_batch_is_atomic_and_digest_bound(carry_case, fault):
    f = carry_case
    install(f)
    rows = view(f)["plan"]["carried_items"]
    reviews = [{"item_id": row["item_id"], "expected_digest": row["current_digest"], "status": "confirmed", "note": ""} for row in rows]
    if fault == "empty": reviews = []
    elif fault == "duplicate": reviews.append(deepcopy(reviews[0]))
    elif fault == "unknown": reviews[-1]["item_id"] = "unknown-item"
    else: reviews[-1]["expected_digest"] = "0" * 64
    with pytest.raises(ActionRejected):
        carry().review_carried_items(f.cs, f.co, "bad-review-batch", reviews)
    assert all(row["status"] == "proposed" for row in view(f)["plan"]["carried_items"])


def test_writer_cannot_confirm_carried_judgments(carry_case):
    from report_agent.content_store import Actor
    f = carry_case
    install(f)
    row = view(f)["plan"]["carried_items"][0]
    with pytest.raises(ActionForbidden):
        carry().review_carried_items(f.cs, Actor("writer", "writer", "task"), "writer-review", [{
            "item_id": row["item_id"], "expected_digest": row["current_digest"], "status": "confirmed", "note": ""}])


@pytest.mark.parametrize("fault", ["missing-pin", "wrong-hash", "wrong-quote", "wrong-locator",
    "extra-authority", "judgment-authority", "section-structure", "unknown-section", "duplicate-object"])
def test_untrusted_carryover_content_is_rejected_before_draft_mutation(carry_case, fault):
    f = carry_case
    package = deepcopy(f.package)
    if fault == "missing-pin": package["source_pins"].pop(0)
    elif fault == "wrong-hash": package["source_pins"][0]["file_digest"] = "0" * 64
    elif fault == "wrong-quote": package["judgments"]["objects"][0]["sources"][0]["quote"] = "THIS_QUOTATION_DOES_NOT_EXIST"
    elif fault == "wrong-locator": package["judgments"]["objects"][0]["sources"][0]["locator"] = "page 999999"
    elif fault == "extra-authority": package["commission_confirmation"] = {"approved": True}
    elif fault == "judgment-authority": package["judgments"]["approved"] = True
    elif fault == "section-structure": package["judgments"]["section_source_choices"][0]["kind"] = "fixed"
    elif fault == "unknown-section": package["judgments"]["section_source_choices"][0]["section_id"] = "99"
    else: package["judgments"]["objects"].append(deepcopy(package["judgments"]["objects"][0]))
    with pytest.raises((ActionRejected, ValueError)):
        install(f, package)
    assert not f.cs.store.get("commission_carryover")
    assert not plan_inputs.get_draft(f.cs.store, {}).get("revision")


def test_two_current_source_refs_with_same_hash_are_ambiguous(carry_case):
    f = carry_case
    sha = f.package["source_pins"][0]["file_digest"]
    original = next(ref for ref in f.skeleton_refs if f.cs.read(ref)["payload"]["file_digest"] == sha)
    with f.cs.store.connect() as db:
        duplicate = f.cs._insert(db, f.co, "SourceArtifact", deepcopy(f.cs.read(original)["payload"]))
    f.skeleton_refs.append(duplicate)
    with pytest.raises(ActionRejected, match="AMBIGUOUS"):
        install(f)
    assert not f.cs.store.get("commission_carryover")


def test_import_does_not_overwrite_existing_draft(carry_case):
    f = carry_case
    planning().save_item(f.cs, f.co, "existing-object", "object", f.plan["objects"][0])
    before = deepcopy(plan_inputs.get_draft(f.cs.store))
    with pytest.raises(ActionRejected, match="FRESH_SKELETON"):
        install(f)
    assert plan_inputs.get_draft(f.cs.store) == before


def test_installed_package_is_immutable_even_after_review(carry_case):
    f = carry_case
    install(f)
    review_all(f)
    changed = deepcopy(f.package)
    changed["origin"] = {"run": "different-prior-run"}
    with pytest.raises(ActionRejected, match="IMMUTABLE"):
        install(f, changed)
    assert all(row["status"] == "confirmed" for row in view(f)["plan"]["carried_items"])


def test_carryover_requires_prepared_reviewed_skeleton(method_commission):
    f = method_commission
    package = {"contract": "judgment-carryover-v1", "origin": {"run": "synthetic"}, "source_pins": [],
        "judgments": {"objects": [], "reconciliations": [], "questions": [], "section_source_choices": []}}
    with pytest.raises(ActionRejected, match="FRESH_SKELETON"):
        carry().install_carryover(f.cs, package, list(f.sources.values()))


def test_raw_plan_cannot_forge_confirmed_carryover_status(carry_case):
    f = carry_case
    install(f)
    plan = deepcopy(view(f)["plan"])
    plan["carried_items"][0]["status"] = "confirmed"
    with f.cs.store.connect() as db:
        with pytest.raises(ActionRejected, match="BINDING_CHANGED"):
            carry().gaps(f.cs, db, plan)


def test_carryover_cannot_read_outside_supplied_case_files(carry_case):
    from support.source_policy import restrict_supplied_case_files
    f = carry_case
    excluded = f.current_judgments["objects"][0]["sources"][0]["source_ref"]
    allowed = [ref for ref in f.skeleton_refs if ref != excluded]
    restrict_supplied_case_files(f.cs.store, [f.cs.read(ref)["payload"]["source_id"] for ref in allowed])
    with pytest.raises((ActionForbidden, ActionRejected)):
        install(f)
    assert not f.cs.store.get("commission_carryover")


def test_imported_free_question_stays_open_after_review(carry_case):
    f = carry_case
    f.package["judgments"]["questions"] = ["Designer must confirm this retained question."]
    install(f)
    review_all(f)
    plan = view(f)["plan"]
    assert "Designer must confirm this retained question." in plan["open_questions"]
    assert not plan_authority.decision_ref(f.cs.store)


def test_carried_exclusion_without_current_page_read_or_owner_record_stays_blocked(carry_case):
    f = carry_case
    f.package["judgments"]["objects"][0].update(included=False, reason="Prior run proposed exclusion.")
    install(f)
    review_all(f)
    assert any(g["code"] == "CARRYOVER_EXCLUSION_PAGE_READ_REQUIRED" for g in view(f)["gaps"])
    assert not plan_authority.decision_ref(f.cs.store)


def test_recorded_owner_scope_exclusion_does_not_invent_page_read_requirement(skeleton_case):
    from report_agent.commission_owner_records import install_owner_records
    from test_m1_g5_j1 import owner
    f = package_case(skeleton_case)
    obj = f.package["judgments"]["objects"][0]
    reason = "Owner explicitly excludes by scope, preserving designer facts."
    obj.update(included=False, reason=reason)
    record = owner("scope_exclusion", obj["object_id"], {"included": False, "reason": reason}, reason=reason)
    install_owner_records(f.cs, {"contract": "owner-records-v1", "records": [record],
        "documents": [], "substitutions": [], "objects": []}, f.skeleton_refs)
    import_module("report_agent.commission_skeleton").prepare_skeleton(f.cs, f.skeleton_refs, f.skeleton_spec)
    install(f)
    review_all(f)
    assert not any(g["code"] == "CARRYOVER_EXCLUSION_PAGE_READ_REQUIRED" for g in view(f)["gaps"])
    assert not plan_authority.decision_ref(f.cs.store)


def test_only_current_direct_page_return_clears_carried_exclusion_read_gate(carry_case):
    import json
    from report_agent.catalog import Catalog
    from report_agent.source_materials import issue, block_material, analysis_materials
    from test_m1_g4_requirements import capture
    from test_ingestion import pdf_bytes
    f = carry_case
    sentence = "S1 proposed exclusion; height 30 m remains a designer fact."
    current = capture(f, "current-exclusion.pdf", pdf_bytes([sentence]), "carry-exclusion-source")
    source = f.cs.read(current)["payload"]
    roles = commission_imports.source_roles(f.ws.store)
    commission_imports.install_source_roles(f.ws.store,
        {**roles, "exclusion-evidence": {"id": source["source_id"], "purpose": "design"}})
    f.skeleton_refs.append(current)
    old = {"type": "SourceArtifact", "id": "prior-exclusion-page", "version": 8}
    f.package["source_pins"].append({"ref": old, "file_digest": source["file_digest"]})
    f.package["judgments"]["objects"][0].update(included=False, reason="Proposed exclusion requires a current source read.",
        sources=[{"source_ref": old, "locator": "page 1", "quote": sentence}])
    install(f)
    review_all(f)
    def requires_read():
        return any(g["code"] == "CARRYOVER_EXCLUSION_PAGE_READ_REQUIRED" for g in view(f)["gaps"])
    assert requires_read()
    data = Catalog(f.ws.store).read(source["source_id"], 0, 10)
    issue(f.ws, f.co, "analyze_text", json.dumps({"interpretation": "Prior proposal reviewed."}),
        analysis_materials({"operation": "analysis-only", "evidence": [{"kind": "source_blocks", "observation": data}]}))
    assert requires_read(), "Helper input alone is not a direct page return."
    issue(f.ws, f.co, "read_source_page", json.dumps(data, ensure_ascii=False), block_material(data))
    assert not requires_read()
    assert not plan_authority.decision_ref(f.cs.store)
