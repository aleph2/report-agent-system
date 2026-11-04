"""G5 J2: trusted skeleton, constrained choices, and explicit candidate dispositions."""
from copy import deepcopy
from importlib import import_module

import pytest

from report_agent.errors import ActionRejected, ActionForbidden
from test_m1_commission_plan import api
from test_m1_g3_integration import method_commission
from test_m1_g4_requirements import anchored, required_case, requirements, capture, saved_historical_bundle
from test_m1_g4_planning_steps import entries, draft_case, planning, source_pins, classifications, enable_h2
from test_hierarchical_content import ws


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    import httpx
    def denied(*args, **kwargs):
        raise AssertionError("G5_J2_NETWORK_FORBIDDEN")
    monkeypatch.setattr(httpx.Client, "send", denied)
    monkeypatch.setattr(httpx.AsyncClient, "send", denied)


def skeleton_api():
    return import_module("report_agent.commission_skeleton")


def test_skeleton_public_preparation_and_validation_interfaces_exist():
    module = skeleton_api()
    for name in ("prepare_skeleton", "apply_skeleton", "validate_skeleton", "resolve_skeleton_question"):
        assert callable(getattr(module, name))


def test_skeleton_is_not_silently_assumed_when_no_reviewed_spec_exists(draft_case):
    fixture = draft_case
    refs = [row["ref"] for row in source_pins(fixture, fixture.plan)]
    with pytest.raises(ActionRejected):
        skeleton_api().prepare_skeleton(fixture.cs, refs)
    assert not fixture.cs.store.get("commission_skeleton")


@pytest.fixture
def skeleton_case(entries):
    return setup_skeleton_case(entries)


def setup_skeleton_case(f, *, fixed=False):
    from report_agent.store import digest
    f.entries[2]["table_specs"] = deepcopy(f.plan["table_specs"])
    f.entries[2]["source_pins"] = source_pins(f, f.entries[2]["table_specs"])
    enable_h2(f)
    planning().install_reviewed_entries(f.cs, f.entries)
    rows = classifications(f)
    for row in rows:
        anchor = next(a for a in f.anchors if a["id"] == row["anchor_id"])
        if anchor["kind"] == "instruction" and anchor.get("section_id") == "5":
            row["capabilities"] = ["result_bindings"]
        if fixed and anchor["kind"] == "instruction" and anchor.get("section_id") == "4":
            row["capabilities"] = ["fixed_text"]
    planning().install_classifications(f.cs, rows, "Reviewed J2 synthetic section structure.")
    req = requirements().read_requirements(f.cs)
    f.skeleton_refs = []
    for ref in [*f.sources.values(), f.scope_ref, f.outline_ref]:
        if ref not in f.skeleton_refs:
            f.skeleton_refs.append(ref)
    f.skeleton_spec = {
        "requirements_digest": digest({"anchors": req["payload"]["anchors"],
                                       "classifications": req["payload"]["classifications"]}),
        "deliverables": ["Word", "Excel"],
        "inventory_attributes": deepcopy(f.plan["inventory_attributes"]),
        "derived": {"5": {"derived_from": ["4"],
                           "rule": "Summarize the section 4 assessment.",
                           "result_bindings": []}},
        "documents": [],
    }
    return f


def prepare(f):
    return skeleton_api().prepare_skeleton(f.cs, f.skeleton_refs, deepcopy(f.skeleton_spec))


def assembled(f):
    return planning().read_draft(f.cs, f.co)["plan"]


def test_real_outline_populates_ordered_structure_before_any_section_tool(skeleton_case):
    f = skeleton_case
    state = prepare(f)
    plan = assembled(f)
    anchors = [a for a in f.anchors if a["kind"] == "section"]
    assert [s["section_id"] for s in plan["sections"]] == [a["section_id"] for a in anchors]
    assert [s["outline"] for s in plan["sections"]] == [a["source"] for a in anchors]
    sections = {s["section_id"]: s for s in plan["sections"]}
    assert sections["4"]["kind"] == "extracted"
    assert sections["5"]["kind"] == "derived"
    assert sections["5"]["derived_from"] == ["4"]
    assert sections["5"]["rule"] == f.skeleton_spec["derived"]["5"]["rule"]
    assert plan["deliverables"] == ["Word", "Excel"]
    assert plan["skeleton_digest"] == state["digest"]
    assert not plan.get("objects")
    assert not f.cs.store.get("commission_confirmation")


def test_skeleton_preserves_reviewed_convention_bindings(skeleton_case):
    f = skeleton_case
    prepare(f)
    plan = assembled(f)
    assert plan["method_pack"]
    assert plan["table_specs"]
    assert plan["method_conventions"][0]["strategy_id"] == f.entries[1]["strategy_id"]
    expected = {a["id"] for a in f.anchors if a["kind"] == "convention"}
    assert {row["requirement_anchor_id"] for row in plan["conventions"]} == expected


def test_skeleton_install_is_idempotent_but_cannot_be_replaced(skeleton_case):
    f = skeleton_case
    first = prepare(f)
    assert prepare(f) == first
    f.skeleton_spec["deliverables"] = ["Word"]
    with pytest.raises(ActionRejected):
        prepare(f)
    assert f.cs.store.get("commission_skeleton")["digest"] == first["digest"]


def test_reviewed_spec_cannot_target_other_requirements(skeleton_case):
    f = skeleton_case
    f.skeleton_spec["requirements_digest"] = "0" * 64
    with pytest.raises(ActionRejected):
        prepare(f)
    assert not f.cs.store.get("commission_skeleton")


@pytest.mark.parametrize("fault", ["invented-section", "unknown-dependency", "self-dependency"])
def test_derived_bindings_must_target_real_distinct_outline_sections(skeleton_case, fault):
    f = skeleton_case
    if fault == "invented-section":
        f.skeleton_spec["derived"]["99"] = f.skeleton_spec["derived"].pop("5")
    else:
        f.skeleton_spec["derived"]["5"]["derived_from"] = ["99" if fault == "unknown-dependency" else "5"]
    with pytest.raises(ActionRejected):
        prepare(f)


@pytest.mark.parametrize("field,value", [("title", "Agent replacement title"), ("kind", "fixed"),
    ("outline", None), ("derived_from", []), ("rule", "Agent replacement rule")])
def test_raw_plan_cannot_replace_frozen_structure(skeleton_case, field, value):
    f = skeleton_case
    prepare(f)
    plan = assembled(f)
    section = next(s for s in plan["sections"] if s["section_id"] == "5")
    section[field] = value
    with f.cs.store.connect() as db:
        with pytest.raises(ActionRejected):
            skeleton_api().validate_skeleton(f.cs, db, plan)


def test_raw_plan_cannot_drop_section_or_change_deliverables(skeleton_case):
    f = skeleton_case
    prepare(f)
    for mutate in (lambda p: p["sections"].pop(), lambda p: p.update(deliverables=["Word"])):
        plan = assembled(f)
        mutate(plan)
        with f.cs.store.connect() as db:
            with pytest.raises(ActionRejected):
                skeleton_api().validate_skeleton(f.cs, db, plan)


def test_agent_judgment_can_add_citations_without_recreating_structure(skeleton_case):
    f = skeleton_case
    prepare(f)
    sources = deepcopy(next(s for s in f.plan["sections"] if s["section_id"] == "4")["sources"])
    planning().save_item(f.cs, f.co, "j2-judgment", "section_judgment",
                         {"section_id": "4", "sources": sources, "notes": ["Retain designer review note."]})
    section = next(s for s in assembled(f)["sections"] if s["section_id"] == "4")
    assert section["sources"] == sources
    assert "Retain designer review note." in section["notes"]
    assert section["outline"] == next(a["source"] for a in f.anchors if a.get("section_id") == "4" and a["kind"] == "section")


def test_section_judgment_cannot_smuggle_a_new_kind(skeleton_case):
    f = skeleton_case
    prepare(f)
    with pytest.raises((ActionRejected, ValueError)):
        planning().save_item(f.cs, f.co, "j2-smuggle-kind", "section_judgment",
                             {"section_id": "4", "kind": "derived", "sources": []})


def add_candidate(f, *, included=True):
    obj = deepcopy(f.plan["objects"][0])
    obj["included"] = included
    obj["reason"] = "Included for assessment." if included else "Proposed exclusion pending owner decision."
    planning().save_item(f.cs, f.co, "j2-object-" + str(included), "object", obj)
    return obj


def test_boolean_inclusion_alone_does_not_classify_candidate(skeleton_case):
    f = skeleton_case
    prepare(f)
    obj = add_candidate(f)
    with pytest.raises(ActionRejected) as exc:
        planning().submit_plan(f.cs, f.co, "j2-unclassified-submit")
    gaps = exc.value.diagnostic.get("gaps", [])
    assert any("disposition" in str(gap).lower() and obj["object_id"] in str(gap) for gap in gaps), gaps
    assert not f.cs.store.get("commission_plan")


def test_included_disposition_is_explicit_and_has_no_exclusion_question(skeleton_case):
    f = skeleton_case
    prepare(f)
    obj = add_candidate(f)
    disposition = {"object_id": obj["object_id"], "status": "included", "reason": "Assessed within commissioned scope."}
    planning().save_item(f.cs, f.co, "j2-included-disposition", "disposition", disposition)
    plan = assembled(f)
    assert any(row["object_id"] == obj["object_id"] and row["status"] == "included"
               for row in plan["candidate_dispositions"])
    assert not any(obj["object_id"] in str(q) for q in plan.get("open_questions", []))


def test_proposed_exclusion_generates_nonerasable_owner_question(skeleton_case):
    f = skeleton_case
    prepare(f)
    obj = add_candidate(f, included=False)
    disposition = {"object_id": obj["object_id"], "status": "proposed_exclusion", "reason": obj["reason"]}
    planning().save_item(f.cs, f.co, "j2-proposed-exclusion", "disposition", disposition)
    initial = assembled(f)["open_questions"]
    assert any(obj["object_id"] in str(q) for q in initial)
    planning().save_item(f.cs, f.co, "j2-fake-resolved-question", "question", {
        "question_id": "candidate-exclusion:" + obj["object_id"],
        "text": "Agent claims owner already agreed.", "resolved": True})
    assert assembled(f)["open_questions"] == initial
    assert not f.cs.store.get("commission_confirmation")


def test_claimed_owner_exclusion_without_owner_record_is_rejected(skeleton_case):
    f = skeleton_case
    prepare(f)
    obj = add_candidate(f, included=False)
    with pytest.raises(ActionRejected):
        planning().save_item(f.cs, f.co, "j2-forged-owner-exclusion", "disposition", {
            "object_id": obj["object_id"], "status": "owner_excluded",
            "owner_record_id": "forged-owner-record", "reason": obj["reason"]})


def test_disposition_cannot_contradict_object_inclusion(skeleton_case):
    f = skeleton_case
    prepare(f)
    obj = add_candidate(f, included=True)
    planning().save_item(f.cs, f.co, "j2-contradict-inclusion", "disposition", {
        "object_id": obj["object_id"], "status": "proposed_exclusion", "reason": "Contradicts included object."})
    assert_disposition_gap(f, obj["object_id"])


def test_disposition_cannot_reference_an_invented_candidate(skeleton_case):
    f = skeleton_case
    prepare(f)
    planning().save_item(f.cs, f.co, "j2-invented-candidate", "disposition", {
        "object_id": "NEVER-INVENTORIED", "status": "included", "reason": "No object exists."})
    assert_disposition_gap(f, "NEVER-INVENTORIED")


@pytest.fixture
def fixed_case(entries, request):
    from test_ingestion import pdf_bytes
    f = setup_skeleton_case(entries, fixed=True)
    mode = getattr(request, "param", "unique")
    pages = ["SYNTHETIC HEADER\n4 Assessment\nFixed first paragraph.\nFixed last paragraph.\n5 Conclusion\nFollowing section must not leak."]
    if mode == "duplicate":
        pages.append("SYNTHETIC HEADER\n4 Assessment\nSecond occurrence body.\n5 Conclusion\nSecond following section.")
    elif mode == "missing":
        pages = ["SYNTHETIC HEADER\n8 Other section\nNot the required title."]
    f.template_ref = capture(f, "j2-actual-template.pdf", pdf_bytes(pages), "j2-template")
    payload = f.cs.read(f.template_ref)["payload"]
    roles = deepcopy(f.cs.store.get("commission_source_roles"))
    roles["j2-template"] = {"id": payload["source_id"], "purpose": "template"}
    f.cs.store.set("commission_source_roles", roles)
    planning().install_text_profile(f.cs, {"id": "j2-template-profile", "source_ref": f.template_ref,
        "file_digest": payload["file_digest"], "header_lines": ["SYNTHETIC HEADER"],
        "footer_lines": [], "page_number_offset": 0, "join_lines": "paragraph"})
    f.skeleton_refs.append(f.template_ref)
    return f


def test_fixed_section_uses_real_pdf_heading_to_next_heading_span(fixed_case):
    f = fixed_case
    state = prepare(f)
    section = next(s for s in state["sections"] if s["section_id"] == "4")
    assert section["kind"] == "fixed"
    assert "Fixed first paragraph." in section["text"]
    assert "Fixed last paragraph." in section["text"]
    assert "SYNTHETIC HEADER" not in section["text"]
    assert "5 Conclusion" not in section["text"]
    assert "Following section" not in section["text"]
    assert section["sources"] and all(c["source_ref"] == f.template_ref for c in section["sources"])
    assert not state["questions"]


@pytest.mark.parametrize("fixed_case", ["duplicate"], indirect=True)
def test_duplicate_template_heading_requires_only_offered_span_choice(fixed_case):
    f = fixed_case
    state = prepare(f)
    question = next(q for q in state["questions"] if q["section_id"] == "4")
    assert len(question["choices"]) == 2
    assert not next(s for s in state["sections"] if s["section_id"] == "4").get("text")
    with pytest.raises(ActionRejected):
        skeleton_api().resolve_skeleton_question(f.cs, f.co, "j2-invented-choice", question["question_id"], state["digest"], "invented-span")
    selected = question["choices"][1]
    skeleton_api().resolve_skeleton_question(f.cs, f.co, "j2-real-choice", question["question_id"], state["digest"], selected["id"])
    current = f.cs.store.get("commission_skeleton")
    section = next(s for s in current["sections"] if s["section_id"] == "4")
    assert section["text"] == selected["fields"]["text"]
    assert not any(q["question_id"] == question["question_id"] for q in current["questions"])
    with pytest.raises(ActionRejected):
        skeleton_api().resolve_skeleton_question(f.cs, f.co, "j2-stale-choice", question["question_id"], state["digest"], question["choices"][0]["id"])


@pytest.mark.parametrize("fixed_case", ["missing"], indirect=True)
def test_missing_template_heading_is_unresolved_not_whole_document_fallback(fixed_case):
    f = fixed_case
    state = prepare(f)
    question = next(q for q in state["questions"] if q["section_id"] == "4")
    assert question["choices"] == []
    section = next(s for s in state["sections"] if s["section_id"] == "4")
    assert not section.get("text")
    with pytest.raises(ActionRejected):
        skeleton_api().resolve_skeleton_question(f.cs, f.co, "j2-missing-free-text", question["question_id"], state["digest"], "Use all pages instead")


def test_frozen_template_text_cannot_be_changed_in_raw_plan(fixed_case):
    f = fixed_case
    prepare(f)
    plan = assembled(f)
    next(s for s in plan["sections"] if s["section_id"] == "4")["text"] += " Unreviewed replacement."
    with f.cs.store.connect() as db:
        with pytest.raises(ActionRejected):
            skeleton_api().validate_skeleton(f.cs, db, plan)


def assert_disposition_gap(f, object_id):
    with pytest.raises(ActionRejected) as exc:
        planning().submit_plan(f.cs, f.co, "j2-invalid-disposition-submit")
    gaps = exc.value.diagnostic.get("gaps", [])
    assert any("disposition" in str(gap).lower() and object_id in str(gap) for gap in gaps), gaps
    assert not f.cs.store.get("commission_confirmation")


def test_template_source_must_be_explicitly_in_preparation_source_refs(fixed_case):
    f = fixed_case
    f.skeleton_refs.remove(f.template_ref)
    with pytest.raises(ActionRejected):
        prepare(f)
    assert not f.cs.store.get("commission_skeleton")


def test_template_profile_cannot_change_after_preparation(fixed_case):
    f = fixed_case
    prepare(f)
    profiles = deepcopy(f.cs.store.get("commission_text_profiles"))
    profiles["j2-template-profile"]["header_lines"] = []
    f.cs.store.set("commission_text_profiles", profiles)
    with pytest.raises(ActionRejected):
        assembled(f)


def test_raw_plan_cannot_silence_generated_candidate_question(skeleton_case):
    f = skeleton_case
    prepare(f)
    obj = add_candidate(f, included=False)
    planning().save_item(f.cs, f.co, "j2-proposal-raw-question", "disposition", {
        "object_id": obj["object_id"], "status": "proposed_exclusion", "reason": obj["reason"]})
    plan = assembled(f)
    plan["open_questions"] = []
    with f.cs.store.connect() as db:
        gaps = skeleton_api().disposition_gaps(f.cs, db, plan)
    assert any(obj["object_id"] in str(g) and "open_questions" in str(g) for g in gaps)


def test_owner_registry_does_not_erase_additional_outline_document_obligation(skeleton_case):
    from report_agent.commission_owner_records import install_owner_records
    f = skeleton_case
    f.skeleton_spec["documents"] = [
        {"id": "doc-design", "name": "Design source obligation", "mentions": ["Use the design"]},
        {"id": "doc-results", "name": "Results source obligation", "mentions": ["Summarize the saved"]},
    ]
    install_owner_records(f.cs, {"contract": "owner-records-v1", "records": [],
        "documents": [{"id": "doc-design", "name": "Design source obligation", "section_ids": ["4"]}],
        "substitutions": [], "objects": []}, f.skeleton_refs)
    prepare(f)
    sections = {s["section_id"]: s for s in assembled(f)["sections"]}
    assert {d["id"] for d in sections["4"]["missing_documents"]} == {"doc-design"}
    assert {d["id"] for d in sections["5"]["missing_documents"]} == {"doc-results"}
    assert any("doc-results" in value for value in api().unresolved_sources(sections["5"]))


def test_host_owner_exclusion_automatically_classifies_only_its_object(skeleton_case):
    from report_agent.commission_owner_records import install_owner_records
    from test_m1_g5_j1 import owner
    f = skeleton_case
    obj = deepcopy(f.plan["objects"][0])
    reason = "Owner excludes this object by scope decision."
    obj.update(included=False, reason=reason)
    record = owner("scope_exclusion", obj["object_id"], {"included": False, "reason": reason}, reason=reason)
    install_owner_records(f.cs, {"contract": "owner-records-v1", "records": [record],
        "documents": [], "substitutions": [], "objects": [obj]}, f.skeleton_refs)
    prepare(f)
    plan = assembled(f)
    disposition = next(d for d in plan["candidate_dispositions"] if d["object_id"] == obj["object_id"])
    assert disposition["status"] == "owner_excluded"
    assert disposition["owner_record_id"] == record["id"]
    assert not any("candidate-exclusion:" + obj["object_id"] in q for q in plan["open_questions"])
    assert not f.cs.store.get("commission_confirmation")


def test_brief_keeps_full_questions_and_binds_original_appendix_and_audit(skeleton_case, tmp_path):
    import json
    from pathlib import Path
    from report_agent.store import digest
    f = skeleton_case
    prepare(f)
    plan = {**deepcopy(f.plan), **assembled(f)}
    plan["objects"] = deepcopy(f.plan["objects"])
    obj = plan["objects"][0]
    obj["included"] = False
    reason = "Scope decision pending: " + "preserve every material qualification; " * 20
    obj["reason"] = reason
    plan["candidate_dispositions"] = [{"object_id": obj["object_id"],
        "status": "proposed_exclusion", "reason": reason, "question_id": "candidate-exclusion:" + obj["object_id"]}]
    question = "candidate-exclusion:" + obj["object_id"] + "：是否同意排除？" + reason
    plan["open_questions"] = [question]
    plan["scope_boundary"] = deepcopy(f.plan["scope_boundary"])
    req = requirements().read_requirements(f.cs)
    ref = {"id": "synthetic-bound-plan", "version": 1}
    path = tmp_path / "brief.md"
    original = ["# System original full appendix", "Exact full detail retained."]
    metadata = import_module("report_agent.commission_brief").write_brief(f.cs, plan, req, {}, ref, path, original)
    brief = path.read_text(encoding="utf-8")
    assert question in brief
    assert reason in brief
    assert obj["label"] in brief
    assert "拟排除" in brief or "建议排除" in brief or "待批准排除" in brief
    appendix = Path(metadata["appendix_path"])
    audit_path = Path(metadata["audit_path"])
    assert appendix.name in brief and audit_path.name in brief
    assert appendix.read_text(encoding="utf-8").splitlines()[-len(original):] == original
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit["plan_ref"] == ref
    assert audit["requirements_ref"] == req["ref"]
    assert audit["plan_sha256"] == digest(plan)
    assert audit["requirements_sha256"] == digest(req["payload"])
    assert audit["plan"] == plan
    assert audit["requirements"] == req
    assert audit["source_access"] == {}
    assert Path(metadata["html_path"]).exists()


@pytest.mark.parametrize("field", ["outline", "kind", "derived_from", "rule"])
def test_omitting_protected_field_is_not_treated_as_permission_to_rebuild_it(skeleton_case, field):
    f = skeleton_case
    prepare(f)
    plan = assembled(f)
    next(s for s in plan["sections"] if s["section_id"] == "5").pop(field)
    with f.cs.store.connect() as db:
        with pytest.raises(ActionRejected):
            skeleton_api().validate_skeleton(f.cs, db, plan)


def test_raw_plan_cannot_invent_skeleton_question_state(fixed_case):
    f = fixed_case
    state = prepare(f)
    plan = assembled(f)
    plan["skeleton_questions"] = [{"question_id": "unrecorded-question"}]
    with f.cs.store.connect() as db:
        with pytest.raises(ActionRejected):
            skeleton_api().validate_skeleton(f.cs, db, plan)


def test_owner_fact_for_not_yet_entered_object_is_a_visible_draft_gap(skeleton_case):
    from report_agent.commission_owner_records import install_owner_records
    from test_m1_g5_j1 import owner
    f = skeleton_case
    record = owner("object_fact", "HP06", {"included": True, "height": "14 m"})
    install_owner_records(f.cs, {"contract": "owner-records-v1", "records": [record],
        "documents": [], "substitutions": [], "objects": []}, f.skeleton_refs)
    prepare(f)
    view = planning().read_draft(f.cs, f.co)
    assert view["plan"]["sections"]
    assert any("HP06" in str(gap) for gap in view["gaps"]), view["gaps"]
    with pytest.raises(ActionRejected):
        planning().submit_plan(f.cs, f.co, "j2-owner-fact-missing-object")
    assert not f.cs.store.get("commission_confirmation")


@pytest.mark.parametrize("gate", ["save", "approval", "writer"])
def test_raw_structural_forgery_is_rejected_at_persisted_authority_gates(skeleton_case, gate):
    from test_m1_commission_plan import save
    f = skeleton_case
    prepare(f)
    f.requirements_ref = requirements().read_requirements(f.cs)["ref"]
    plan = {**deepcopy(f.plan), **assembled(f)}
    plan["objects"] = deepcopy(f.plan["objects"])
    plan["scope_boundary"] = deepcopy(f.plan["scope_boundary"])
    plan["candidate_dispositions"] = [{"object_id": plan["objects"][0]["object_id"],
        "status": "included", "reason": "Commissioned object."}]
    plan["sections"][0]["title"] = "Injected structure after host preparation"
    if gate != "save":
        bundle = saved_historical_bundle(f, plan, answered=gate == "writer")
    with pytest.raises(ActionRejected, match="SKELETON_"):
        if gate == "save":
            save(f, plan, operation="j2-raw-structure-save")
        elif gate == "approval":
            api().reply(f.ws, bundle.issue_id, bundle.decision)
        else:
            with f.cs.store.connect() as db:
                api().assert_writing_allowed(f.cs, db, bundle.actor)


@pytest.mark.parametrize("fixed_case", ["duplicate"], indirect=True)
def test_template_choice_does_not_expand_writer_permissions(fixed_case):
    from report_agent.content_store import Actor
    f = fixed_case
    state = prepare(f)
    question = state["questions"][0]
    with pytest.raises(ActionForbidden):
        skeleton_api().resolve_skeleton_question(f.cs, Actor("writer", "writer", "undelegated"),
            "j2-writer-template-choice", question["question_id"], state["digest"], question["choices"][0]["id"])
    assert f.cs.store.get("commission_skeleton")["digest"] == state["digest"]


def test_changed_pinned_source_identity_is_rejected_on_read(skeleton_case, monkeypatch):
    f = skeleton_case
    state = prepare(f)
    target = state["source_pins"][0]["ref"]
    original = f.cs._read
    def changed(db, ref, *args, **kwargs):
        record = original(db, ref, *args, **kwargs)
        if ref == target:
            record = deepcopy(record)
            record["payload"]["file_digest"] = "f" * 64
        return record
    monkeypatch.setattr(f.cs, "_read", changed)
    with pytest.raises(ActionRejected, match="SKELETON_SOURCE_CHANGED"):
        assembled(f)


@pytest.fixture
def derived_template_case(entries, request):
    from test_ingestion import pdf_bytes
    f = setup_skeleton_case(entries)
    f.skeleton_spec["derived"]["5"].update(template=True,
        result_bindings=[{"old": "{COUNT}", "field": "object_count"}])
    mode = getattr(request, "param", "unique")
    body = "Objects {COUNT}."
    if mode == "repeated-placeholder":
        body = "Objects {COUNT}; duplicated {COUNT}."
    pages = ["SYNTHETIC HEADER\n5 Conclusion\n" + body + "\n6 Next chapter\nDo not include next chapter."]
    if mode == "duplicate":
        pages.append("SYNTHETIC HEADER\n5 Conclusion\nSecond objects {COUNT}.\n6 Next chapter\nOther chapter.")
    elif mode == "missing":
        pages = ["SYNTHETIC HEADER\n5 Changed title\nObjects {COUNT}.\n6 Next chapter\nDo not include next chapter."]
    ref = capture(f, "j2-derived-template.pdf", pdf_bytes(pages), "j2-derived-template")
    f.template_ref = ref
    payload = f.cs.read(ref)["payload"]
    roles = deepcopy(f.cs.store.get("commission_source_roles"))
    roles["j2-derived-template"] = {"id": payload["source_id"], "purpose": "template"}
    f.cs.store.set("commission_source_roles", roles)
    planning().install_text_profile(f.cs, {"id": "j2-derived-profile", "source_ref": ref,
        "file_digest": payload["file_digest"], "header_lines": ["SYNTHETIC HEADER"],
        "footer_lines": [], "page_number_offset": 0, "join_lines": "paragraph"})
    f.skeleton_refs.append(ref)
    return f


def test_fresh_skeleton_provides_inventory_attributes_without_details_tool(skeleton_case):
    f = skeleton_case
    prepare(f)
    plan = assembled(f)
    assert plan["inventory_attributes"] == f.plan["inventory_attributes"]
    assert not f.cs.store.get("commission_planning_draft", {}).get("items", {}).get("details")
    with f.cs.store.connect() as db:
        changed = deepcopy(plan)
        changed["inventory_attributes"] = ["Agent invented field"]
        with pytest.raises(ActionRejected):
            skeleton_api().validate_skeleton(f.cs, db, changed)


def test_inventory_attributes_are_required_reviewed_spec_data(skeleton_case):
    f = skeleton_case
    f.skeleton_spec.pop("inventory_attributes")
    with pytest.raises(ActionRejected):
        prepare(f)


def test_derived_template_body_excludes_outline_instructions(derived_template_case):
    f = derived_template_case
    state = prepare(f)
    section = next(s for s in state["sections"] if s["section_id"] == "5")
    text = api().fixed_section_text(section)
    assert "Objects {COUNT}." in text
    assert "Summarize the saved section 4 results." not in text
    assert "Do not include next chapter." not in text
    assert all(c["source_ref"] == f.template_ref for c in section["sources"])
    assert section["extraction"]["text"] == section["text"]
    assert "template" not in section


@pytest.mark.parametrize("field", ["sources", "text", "extraction"])
def test_derived_template_source_and_text_are_frozen(derived_template_case, field):
    f = derived_template_case
    prepare(f)
    plan = assembled(f)
    section = next(s for s in plan["sections"] if s["section_id"] == "5")
    section[field] = [] if field == "sources" else "Unreviewed text" if field == "text" else None
    with f.cs.store.connect() as db:
        with pytest.raises(ActionRejected):
            skeleton_api().validate_skeleton(f.cs, db, plan)


@pytest.mark.parametrize("derived_template_case", ["duplicate", "missing"], indirect=True)
def test_derived_template_ambiguity_is_a_narrow_unresolved_question(derived_template_case):
    f = derived_template_case
    state = prepare(f)
    question = next(q for q in state["questions"] if q["section_id"] == "5")
    assert len(question["choices"]) in (0, 2)
    section = next(s for s in state["sections"] if s["section_id"] == "5")
    assert not section.get("text")
    assert not section["sources"]


@pytest.mark.parametrize("derived_template_case", ["repeated-placeholder"], indirect=True)
def test_derived_result_binding_requires_one_exact_template_occurrence(derived_template_case):
    with pytest.raises(ActionRejected):
        prepare(derived_template_case)


def test_fresh_plan_can_submit_through_judgment_tools_without_hidden_details(derived_template_case):
    f = derived_template_case
    prepare(f)
    planning().save_item(f.cs, f.co, "j2-complete-boundary", "boundary", f.plan["scope_boundary"])
    for obj in f.plan["objects"]:
        planning().save_item(f.cs, f.co, "j2-complete-object-" + obj["object_id"], "object", obj)
        planning().save_item(f.cs, f.co, "j2-complete-status-" + obj["object_id"], "disposition", {
            "object_id": obj["object_id"], "status": "included", "reason": obj["reason"]})
    for index, row in enumerate(f.plan["reconciliations"]):
        planning().save_item(f.cs, f.co, "j2-complete-reconciliation-" + str(index), "reconciliation", {
            "reconciliation_id": "pair-" + str(index), **deepcopy(row)})
    assessment = next(s for s in f.plan["sections"] if s["section_id"] == "4")
    planning().save_item(f.cs, f.co, "j2-complete-section-judgment", "section_judgment", {
        "section_id": "4", "sources": assessment["sources"]})
    view = planning().read_draft(f.cs, f.co)
    assert not view["gaps"], view["gaps"]
    assert not f.cs.store.get("commission_planning_draft")["items"].get("details")
    receipt = planning().submit_plan(f.cs, f.co, "j2-complete-submit")
    saved = f.cs.read(receipt["result"]["plan_ref"])["payload"]
    assert saved["inventory_attributes"] == f.plan["inventory_attributes"]
    assert not f.cs.store.get("commission_confirmation")


@pytest.mark.parametrize("derived_template_case", ["missing"], indirect=True)
def test_missing_title_can_select_only_actual_canonical_same_number_span(derived_template_case):
    f = derived_template_case
    state = prepare(f)
    question = next(q for q in state["questions"] if q["section_id"] == "5")
    selection = {"source_ref": f.template_ref, "profile_id": "j2-derived-profile",
        "start_page": 1, "end_page": 1, "start_sentence": "5 Changed title", "end_sentence": "Objects {COUNT}."}
    skeleton_api().resolve_skeleton_question(f.cs, f.co, "j2-canonical-missing-title", question["question_id"],
        state["digest"], "canonical-source-selection", selection=selection)
    current = f.cs.store.get("commission_skeleton")
    section = next(s for s in current["sections"] if s["section_id"] == "5")
    assert section["extraction"]["selection"] == selection
    assert api().fixed_section_text(section) == "5 Changed title\nObjects {COUNT}."
    assert not current["questions"]


@pytest.mark.parametrize("derived_template_case", ["missing"], indirect=True)
@pytest.mark.parametrize("fault", ["wrong-end", "foreign-profile", "wrong-section", "stale-digest"])
def test_missing_title_choice_cannot_override_canonical_source_constraints(derived_template_case, fault):
    f = derived_template_case
    state = prepare(f)
    question = next(q for q in state["questions"] if q["section_id"] == "5")
    selection = {"source_ref": f.template_ref, "profile_id": "j2-derived-profile",
        "start_page": 1, "end_page": 1, "start_sentence": "5 Changed title", "end_sentence": "Objects {COUNT}."}
    expected = state["digest"]
    if fault == "wrong-end":
        selection["end_sentence"] = "Do not include next chapter."
    elif fault == "foreign-profile":
        selection["profile_id"] = "unregistered-profile"
    elif fault == "wrong-section":
        selection.update(start_sentence="6 Next chapter", end_sentence="Do not include next chapter.")
    else:
        expected = "0" * 64
    with pytest.raises(ActionRejected):
        skeleton_api().resolve_skeleton_question(f.cs, f.co, "j2-canonical-bad-" + fault,
            question["question_id"], expected, "canonical-source-selection", selection=selection)
    assert f.cs.store.get("commission_skeleton")["digest"] == state["digest"]


@pytest.mark.parametrize("derived_template_case", ["duplicate"], indirect=True)
def test_nonempty_offered_choices_cannot_be_bypassed_with_selection_argument(derived_template_case):
    f = derived_template_case
    state = prepare(f)
    question = next(q for q in state["questions"] if q["section_id"] == "5")
    assert question["choices"]
    with pytest.raises(ActionRejected):
        skeleton_api().resolve_skeleton_question(f.cs, f.co, "j2-bypass-offered-choice", question["question_id"],
            state["digest"], "invalid-choice-id", selection=question["choices"][0]["selection"])


@pytest.fixture
def composition_data():
    from test_m1_g3_method_pack import pack_data, citation
    from report_agent.risk_scoring import calculate
    from types import SimpleNamespace
    pack = pack_data()
    original = deepcopy(pack["indicators"][0])
    pack["indicators"] = [{**deepcopy(original), "id": "I" + str(i).zfill(2),
        "label": "Indicator_" + str(i).zfill(2)} for i in range(1, 12)]
    pack["weight_tables"] = [{"id": "rank-lookup", "source": citation(),
        "rows": [{"indicator_count": 11, "weights": ["0.1"] * 10 + ["0"]}]}]
    def result(object_id, mode="ordinary"):
        rows = []
        for i, definition in enumerate(pack["indicators"]):
            value = "60" if mode == "level-III" else "40"
            if mode == "adopted-max" and i == 0:
                value = "100"
            assumed = mode == "high-only-max" and i == 0
            rows.append({"indicator_id": definition["id"], "rank": 11 - i,
                "grade_id": "g4" if value == "100" else "g3" if value == "60" else "g2",
                "value": value, "basis_kind": "indirect_assumption" if assumed else "direct_evidence",
                "sources": [citation("design")], "rationale": "Current verified evidence.",
                "question": "Designer must verify the adopted assumption." if assumed else "",
                "low": "25" if assumed else None, "high": "100" if assumed else None})
        return calculate(pack, {"object_id": object_id, "method_id": pack["method_id"],
            "method_version": pack["version"], "weight_strategy_id": "rank-lookup", "indicators": rows})
    section = {"section_id": "5", "kind": "derived", "sources": [citation("template")],
        "result_bindings": [], "result_composition": [
            {"section_id": "5.1", "kind": "source", "text": "Template guidance: field investigation informs the assessment."},
            {"section_id": "5.2", "kind": "assessment_summary", "text": ""},
            {"section_id": "5.3", "kind": "indicator_list", "text": ""},
            {"section_id": "5.4", "kind": "special_assessments", "text": ""},
            {"section_id": "5.5", "kind": "source", "text": "Retained management guidance."}]}
    objects = [{"object_id": name, "label": name + "_CURRENT", "included": True}
               for name in ("S_NORMAL", "S_LEVEL", "S_MAX", "S_HIGH")]
    plan = {"objects": objects, "method_pack": pack, "sections": [section]}
    return SimpleNamespace(plan=plan, section=section, result=result)


def composed(f, bound):
    return import_module("report_agent.commission_results").composed_nodes(f.plan, f.section, bound)


def visible_nodes(nodes):
    import json
    return json.dumps([{"body": n["body"], "qualifiers": n.get("qualifiers", {})} for n in nodes], ensure_ascii=False)


def test_composed_nodes_are_typed_and_contain_all_eleven_ranked_indicators(composition_data):
    from report_agent.content_models import ContentNode
    f = composition_data
    nodes = composed(f, {"S_NORMAL": f.result("S_NORMAL")})
    assert nodes
    for node in nodes:
        ContentNode.model_validate(node)
    tables = [n for n in nodes if n["kind"] == "table"]
    assert len(tables) >= 2
    assert all("columns" in n["body"] and "rows" in n["body"] for n in tables)
    text = visible_nodes(nodes)
    for i in range(1, 12):
        assert "Indicator_" + str(i).zfill(2) in text
    assert "S_NORMAL_CURRENT" in text
    assert "S_LEVEL_CURRENT" not in text
    assert not any("|---" in n["body"].get("text", "") for n in nodes)
    ranks = next(n for n in tables if "Indicator_11" in visible_nodes([n]))
    rendered = visible_nodes([ranks])
    assert rendered.index("Indicator_11") < rendered.index("Indicator_01")


def test_special_assessments_use_adopted_level_or_adopted_numeric_max(composition_data):
    f = composition_data
    bound = {"S_NORMAL": f.result("S_NORMAL"), "S_LEVEL": f.result("S_LEVEL", "level-III"),
        "S_MAX": f.result("S_MAX", "adopted-max"), "S_HIGH": f.result("S_HIGH", "high-only-max")}
    nodes = composed(f, bound)
    # The special-assessment result must itself identify the selected objects,
    # rather than relying on the earlier all-object summary table.
    special = [n for n in nodes if n["body"].get("composition_section_id") == "5.4"]
    assert special, nodes
    text = visible_nodes(special)
    assert "S_LEVEL_CURRENT" in text
    assert "S_MAX_CURRENT" in text
    assert "S_NORMAL_CURRENT" not in text
    assert "S_HIGH_CURRENT" not in text


def test_composed_assumed_values_have_visible_qualification(composition_data):
    f = composition_data
    text = visible_nodes(composed(f, {"S_HIGH": f.result("S_HIGH", "high-only-max")}))
    assert any(word in text for word in ("假设", "待确认", "待核实", "assumption"))
    assert "S_HIGH_CURRENT" in text


def test_template_source_guidance_is_visibly_attributed_not_claimed_as_run_work(composition_data):
    f = composition_data
    nodes = composed(f, {"S_NORMAL": f.result("S_NORMAL")})
    source = next(n for n in nodes if f.section["result_composition"][0]["text"] in n["body"].get("text", ""))
    assert any(word in source["body"]["text"] for word in ("模板", "来源指引", "source guidance"))
    assert "Retained management guidance." in visible_nodes(nodes)


@pytest.fixture
def composed_template_case(entries):
    from test_ingestion import pdf_bytes
    f = setup_skeleton_case(entries)
    body = """5 Conclusion
5.1 Basis
Template field-investigation guidance.
5.2 Results
OLD_PROJECT_SUMMARY_999
5.3 Indicators
OLD_PROJECT_RANKS_888
5.4 Special assessments
OLD_PROJECT_SPECIAL_777
5.5 Management
Retain management guidance.
6 Next chapter
Do not consume this chapter."""
    ref = capture(f, "j2-composed-template.pdf", pdf_bytes([body]), "j2-composed-template")
    f.template_ref = ref
    payload = f.cs.read(ref)["payload"]
    roles = deepcopy(f.cs.store.get("commission_source_roles"))
    roles["j2-composed-template"] = {"id": payload["source_id"], "purpose": "template"}
    f.cs.store.set("commission_source_roles", roles)
    planning().install_text_profile(f.cs, {"id": "j2-composed-profile", "source_ref": ref,
        "file_digest": payload["file_digest"], "header_lines": [], "footer_lines": [],
        "page_number_offset": 0, "join_lines": "paragraph"})
    f.skeleton_refs.append(ref)
    f.skeleton_spec["derived"]["5"].update(template=True, result_bindings=[], composition=[
        {"section_id": sid, "kind": kind} for sid, kind in [
            ("5.1", "source"), ("5.2", "assessment_summary"), ("5.3", "indicator_list"),
            ("5.4", "special_assessments"), ("5.5", "source")]])
    return f


def test_preparation_replaces_old_project_regions_with_typed_composition(composed_template_case):
    f = composed_template_case
    state = prepare(f)
    section = next(s for s in state["sections"] if s["section_id"] == "5")
    parts = section["result_composition"]
    assert [p["section_id"] for p in parts] == ["5.1", "5.2", "5.3", "5.4", "5.5"]
    assert [p["kind"] for p in parts] == ["source", "assessment_summary", "indicator_list", "special_assessments", "source"]
    assert all(p["text"] == "" for p in parts if p["kind"] != "source")
    assert "Template field-investigation guidance." in parts[0]["text"]
    assert "Retain management guidance." in parts[-1]["text"]
    assert not any("OLD_PROJECT_" in p["text"] for p in parts)
    assert not section.get("result_bindings")
    assert "OLD_PROJECT_SUMMARY_999" in section["extraction"]["text"], "Original source remains auditable."


def test_composition_regions_are_immutable_in_raw_plan(composed_template_case):
    f = composed_template_case
    prepare(f)
    plan = assembled(f)
    next(s for s in plan["sections"] if s["section_id"] == "5")["result_composition"][1]["kind"] = "source"
    with f.cs.store.connect() as db:
        with pytest.raises(ActionRejected):
            skeleton_api().validate_skeleton(f.cs, db, plan)


@pytest.fixture
def composed_runtime(method_commission):
    from test_m1_commission_plan import save, approve, writer
    from test_m1_g3_integration import persist
    f = method_commission
    plan = deepcopy(f.plan)
    section = next(s for s in plan["sections"] if s["section_id"] == "5")
    section.update(sources=[f.cite("template")], result_bindings=[], result_composition=[
        {"section_id": "5.1", "kind": "source", "text": "Exact method sentence."},
        {"section_id": "5.2", "kind": "assessment_summary", "text": ""},
        {"section_id": "5.3", "kind": "indicator_list", "text": ""},
        {"section_id": "5.4", "kind": "special_assessments", "text": ""}])
    f.saved = save(f, plan)
    approve(f, f.saved)
    f.actor = writer(f, f.saved, section_ids=["4", "5"])
    f.assessment_receipt = persist(f, f.actor)
    f.composed_section = section
    return f


def materialize_composition(f, refs=None, operation="j2-materialize-composition"):
    from report_agent.risk_scoring import create_planned_section
    return create_planned_section(f.cs, f.actor, operation, "5",
        [f.assessment_receipt["assessment_ref"]] if refs is None else refs)["result"]


def test_runtime_composition_requires_all_current_assessments(composed_runtime):
    f = composed_runtime
    with pytest.raises(ActionRejected, match="ALL_COMMISSIONED_ASSESSMENTS"):
        materialize_composition(f, [])


def test_runtime_composition_rejects_extra_receipted_assessment(composed_runtime):
    from report_agent.store import digest
    f = composed_runtime
    # Synthetic historical receipt tests the exact-set gate after receipt checks.
    original = f.cs.read(f.assessment_receipt["assessment_ref"])["payload"]
    with f.cs.store.connect() as db:
        extra = f.cs._insert(db, f.co, "Assessment", {**deepcopy(original), "object_id": "EXTRA"})
        api()._set(db, "assessment_receipt:" + digest(extra),
                   {**deepcopy(f.assessment_receipt), "assessment_ref": extra})
    with pytest.raises(ActionRejected, match="ALL_COMMISSIONED_ASSESSMENTS"):
        materialize_composition(f, [f.assessment_receipt["assessment_ref"], extra])


def test_composed_runtime_seals_every_child_body_and_region_contract(composed_runtime):
    from report_agent.store import digest
    f = composed_runtime
    result = materialize_composition(f)
    refs = [r for r in result["refs"].values() if r["type"] == "ContentNode"]
    assert len(refs) >= 7
    bodies = []
    for ref in refs:
        node = f.cs.read(ref)["payload"]
        receipt = f.cs.store.get("planned_section_receipt:" + digest(ref))
        assert node["body"]["planned_section"] is True
        assert node["body"]["commission_plan_ref"] == f.saved["plan_ref"]
        assert node["body"]["assessment_refs"] == [f.assessment_receipt["assessment_ref"]]
        assert receipt["body_digest"] == digest(node["body"])
        assert receipt["composition_digest"] == digest(f.composed_section["result_composition"])
        assert receipt["commission_plan_ref"] == f.saved["plan_ref"]
        assert receipt["assessment_refs"] == [f.assessment_receipt["assessment_ref"]]
        bodies.append(node)
    assert "Project OLD." not in visible_nodes(bodies)
    assert "43.5" in visible_nodes(bodies)
    root_receipt = f.cs.store.get("planned_section_receipt:" + digest(result["node_ref"]))
    assert root_receipt["node_refs"] == refs


@pytest.mark.parametrize("fault", ["alter-table", "drop-child", "reorder-children"])
def test_export_refuses_changed_incomplete_or_reordered_composition(composed_runtime, fault):
    from report_agent.content_models import Ref
    from report_agent.g3_export import validate_export
    f = composed_runtime
    result = materialize_composition(f)
    records = {Ref.model_validate(record["ref"]).key(): deepcopy(record) for record in f.cs.list_objects()}
    snapshot = {"payload": {"root_ref": result["node_ref"], "commission_plan_ref": f.saved["plan_ref"]}}
    validate_export(f.cs, snapshot, records)
    refs = [r for r in result["refs"].values() if r["type"] == "ContentNode"]
    if fault == "alter-table":
        table = next(records[Ref.model_validate(ref).key()]["payload"] for ref in refs
                     if records[Ref.model_validate(ref).key()]["payload"]["kind"] == "table")
        table["body"]["rows"][0][0] = "Forged result"
    else:
        edges = [records[Ref.model_validate(r).key()] for r in result["refs"].values() if r["type"] == "Relation"]
        if fault == "drop-child":
            records.pop(Ref.model_validate(edges[0]["ref"]).key())
        else:
            edges[0]["payload"]["position"], edges[1]["payload"]["position"] = edges[1]["payload"]["position"], edges[0]["payload"]["position"]
    with pytest.raises(ActionRejected, match="(?i)(receipt|composition)"):
        validate_export(f.cs, snapshot, records)


@pytest.mark.parametrize("fault", ["entire-composition-omitted", "heading-only", "two-complete-groups"])
def test_export_requires_exactly_one_complete_planned_composition(composed_runtime, fault):
    from report_agent.content_models import Ref
    from report_agent.g3_export import validate_export
    f = composed_runtime
    groups = []
    if fault == "two-complete-groups":
        groups = [materialize_composition(f, operation="j2-group-first")["node_ref"],
                  materialize_composition(f, operation="j2-group-second")["node_ref"]]
    with f.cs.store.connect() as db:
        root = f.cs._insert(db, f.co, "ContentNode", {"kind": "report", "body": {"text": "Report root"},
            "qualifiers": {}, "claim_kind": "structure"})
        if fault == "heading-only":
            title = f.composed_section["title"]
            groups = [f.cs._insert(db, f.co, "ContentNode", {"kind": "chapter",
                "body": {"text": "5 " + title, "section_id": "5", "section_heading": True},
                "qualifiers": {}, "claim_kind": "structure"})]
        for index, child in enumerate(groups):
            f.cs._insert(db, f.co, "Relation", {"subject_ref": root, "object_ref": child,
                "predicate": "contains", "position": index, "provenance_kind": "adopted_during_generation"})
    records = {Ref.model_validate(record["ref"]).key(): deepcopy(record) for record in f.cs.list_objects()}
    snapshot = {"payload": {"root_ref": root, "commission_plan_ref": f.saved["plan_ref"]}}
    with pytest.raises(ActionRejected, match="(?i)composition"):
        validate_export(f.cs, snapshot, records)


def test_composed_subsection_exports_real_docx_tables_and_xlsx_cells(composed_runtime):
    from io import BytesIO
    from docx import Document
    from openpyxl import load_workbook
    from report_agent.content_export import export_snapshot
    from report_agent.content_workbook import export_workbook
    f = composed_runtime
    result = materialize_composition(f)
    assessment = f.assessment_receipt
    objects = [
        {"client_key": "report", "type": "ContentNode", "payload": {
            "kind": "report", "body": {"text": "Current synthetic assessment report"},
            "qualifiers": {}, "claim_kind": "structure"}},
        {"client_key": "assessment-section", "type": "ContentNode", "payload": {
            "kind": "chapter", "body": {"text": "4 Assessment", "section_id": "4", "section_heading": True},
            "qualifiers": {}, "claim_kind": "structure"}},
    ]
    def edge(name, parent, child, position):
        objects.append({"client_key": name, "type": "Relation", "payload": {
            "subject_ref": parent, "object_ref": child, "predicate": "contains", "position": position,
            "provenance_kind": "adopted_during_generation"}})
    edge("assessment-section-edge", {"client_key": "report"}, {"client_key": "assessment-section"}, 0)
    edge("composed-section-edge", {"client_key": "report"}, result["node_ref"], 1)
    for index, field in enumerate(("ranking_ref", "evaluation_ref", "level_ref")):
        edge("assessment-" + field, {"client_key": "assessment-section"}, assessment[field], index)
    created = f.cs.commit(f.actor, "j2-rendered-report-tree", objects)["result"]["refs"]
    api().record_outcome(f.cs, f.actor, "j2-rendered-outcome", "S1", created["assessment-section"],
        assessment["evaluation_ref"], assessment["level_ref"], [assessment["evidence_ref"]], [])
    frozen = f.cs.freeze(f.co, "j2-rendered-freeze", created["report"], [],
        saved_receipt_ids=["save-assessment", "j2-materialize-composition", "j2-rendered-report-tree"])["result"]["snapshot_ref"]
    word = export_snapshot(f.cs, f.co, "j2-rendered-word", frozen)["result"]
    table_refs = [ref for ref in result["refs"].values() if ref["type"] == "ContentNode"
                  and f.cs.read(ref)["payload"]["kind"] == "table"]
    excel = export_workbook(f.cs, f.co, "j2-rendered-excel", frozen,
        [{"name": "Chapter5_" + str(i), "table_ref": ref} for i, ref in enumerate(table_refs, 1)],
        report_export_ref=word["export_ref"])["result"]
    doc = Document(BytesIO((f.cs.store.root / word["file_ref"]).read_bytes()))
    workbook = load_workbook(BytesIO((f.cs.store.root / excel["file_ref"]).read_bytes()), data_only=True)
    word_tables = "\n".join(cell.text for table in doc.tables for row in table.rows for cell in row.cells)
    excel_cells = "\n".join(str(cell) for sheet in workbook for row in sheet.values for cell in row if cell is not None)
    for text in (word_tables, excel_cells):
        assert "Slope 1" in text
        assert "43.5" in text
        for indicator in f.plan["method_pack"]["indicators"]:
            assert indicator["label"] in text
        assert "Project OLD." not in text
        assert "OLD_PROJECT" not in text
    assert len(doc.tables) >= len(table_refs)
    assert len(workbook.sheetnames) >= len(table_refs)
