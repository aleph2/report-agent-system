"""G5 J3 first slice: explicit source applicability decisions and anchored artifacts."""
from copy import deepcopy
from importlib import import_module

import pytest

from report_agent import plan_authority
from report_agent.errors import ActionRejected
from test_m1_commission_plan import api, save, writer
from test_m1_g3_integration import method_commission, persist
from test_m1_g5_j2 import composition_data


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    import httpx
    def denied(*args, **kwargs):
        raise AssertionError("G5_J3_NETWORK_FORBIDDEN")
    monkeypatch.setattr(httpx.Client, "send", denied)
    monkeypatch.setattr(httpx.AsyncClient, "send", denied)


def choices():
    return [{"section_id": sid, "choice": "keep_verbatim", "replacements": []} for sid in ("5.1", "5.5")]


@pytest.fixture
def source_decision_case(method_commission):
    f = method_commission
    f.plan = deepcopy(f.plan)
    section = next(s for s in f.plan["sections"] if s["section_id"] == "5")
    section.update(sources=[f.cite("template")], result_bindings=[], result_composition=[
        {"section_id": "5.1", "kind": "source", "text": "Exact method sentence.",
         "applicability_question": "Designer must confirm whether the template method statement applies."},
        {"section_id": "5.2", "kind": "assessment_summary", "text": ""},
        {"section_id": "5.3", "kind": "indicator_list", "text": ""},
        {"section_id": "5.4", "kind": "special_assessments", "text": ""},
        {"section_id": "5.5", "kind": "source", "text": "Project OLD.",
         "applicability_question": "Designer must confirm project applicability of this retained template sentence."}])
    f.composed_section = section
    f.saved = save(f)
    f.checkpoint = api().request_checkpoint(f.ws)
    f.decision = {"plan_ref": f.saved["plan_ref"], "approved": True, "corrections": "", "reductions": [],
                  "template_decisions": choices()}
    return f


def decide(f, decision=None):
    return api().reply(f.ws, f.checkpoint["issue_id"], deepcopy(f.decision if decision is None else decision))


def test_pending_source_applicability_is_not_implicitly_approved(source_decision_case):
    f = source_decision_case
    decision = deepcopy(f.decision)
    decision.pop("template_decisions")
    with pytest.raises(ActionRejected):
        decide(f, decision)
    assert not plan_authority.decision_ref(f.cs.store)
    assert not next(i for i in f.cs.store.get("report_issues") if i["id"] == f.checkpoint["issue_id"]).get("resolved")


@pytest.mark.parametrize("fault", ["missing-choice", "unknown-part", "duplicate-part", "wrong-choice", "keep-with-replacement",
    "replace-without-spans", "absent-old", "ambiguous-old", "overlapping-old"])
def test_owner_source_decision_rejects_incomplete_or_invalid_choices(source_decision_case, fault):
    f = source_decision_case
    decision = deepcopy(f.decision)
    first = decision["template_decisions"][0]
    if fault == "missing-choice":
        decision["template_decisions"].pop()
    elif fault == "unknown-part":
        first["section_id"] = "5.99"
    elif fault == "duplicate-part":
        decision["template_decisions"].append(deepcopy(first))
    elif fault == "wrong-choice":
        first["choice"] = "approve_automatically"
    elif fault == "keep-with-replacement":
        first["replacements"] = [{"old": "Exact", "new": "Changed"}]
    else:
        first["choice"] = "replace"
        first["replacements"] = [] if fault == "replace-without-spans" else [
            {"old": "ABSENT" if fault == "absent-old" else "e" if fault == "ambiguous-old" else "Exact method", "new": "Changed"}]
        if fault == "overlapping-old":
            first["replacements"].append({"old": "method sentence", "new": "Updated"})
    with pytest.raises((ActionRejected, ValueError)):
        decide(f, decision)
    assert not plan_authority.decision_ref(f.cs.store)


def test_source_choices_are_still_bound_to_current_plan_and_issue(source_decision_case):
    f = source_decision_case
    decision = deepcopy(f.decision)
    decision["plan_ref"]["version"] += 1
    with pytest.raises(ActionRejected, match="STALE"):
        decide(f, decision)
    assert not plan_authority.decision_ref(f.cs.store)


def test_explicit_source_choices_persist_and_replay_idempotently(source_decision_case):
    f = source_decision_case
    decide(f)
    original = plan_authority.decision_ref(f.cs.store)
    record = f.cs.read(original)["payload"]
    assert record["template_decisions"] == choices()
    decide(f)
    assert plan_authority.decision_ref(f.cs.store) == original
    assert len(f.cs.list_objects("CommissionDecision")) == 1


def test_plan_rejection_does_not_require_source_adoption_choices(source_decision_case):
    f = source_decision_case
    decision = deepcopy(f.decision)
    decision.update(approved=False, corrections="Review source applicability before approval.")
    decision.pop("template_decisions")
    decide(f, decision)
    assert f.cs.read(plan_authority.decision_ref(f.cs.store))["payload"]["approved"] is False


def test_template_choice_cannot_attach_to_legacy_plan_without_question_parts(method_commission):
    f = method_commission
    saved = save(f)
    checkpoint = api().request_checkpoint(f.ws)
    with pytest.raises(ActionRejected):
        api().reply(f.ws, checkpoint["issue_id"], {"plan_ref": saved["plan_ref"], "approved": True,
            "corrections": "", "reductions": [], "template_decisions": choices()})
    assert not plan_authority.decision_ref(f.cs.store)


@pytest.fixture
def applicable_composition(composition_data):
    f = composition_data
    for part in f.section["result_composition"]:
        if part["kind"] == "source":
            part["applicability_question"] = "Confirm applicability of source part " + part["section_id"] + "."
    f.applicability_issues = [{"id": "template-applicability:" + p["section_id"], "kind": "unclear",
        "object_label": "Template " + p["section_id"], "basis": "Template applicability needs designer confirmation.",
        "sources": [{"document": "Synthetic template", "page": 1}], "question": p["applicability_question"]}
        for p in f.section["result_composition"] if p["kind"] == "source"]
    return f


def composed(f, decisions=()):
    return import_module("report_agent.commission_results").composed_nodes(f.plan, f.section,
        {"S_NORMAL": f.result("S_NORMAL")}, template_decisions=decisions,
        applicability_issues=f.applicability_issues)


def source_nodes(nodes):
    return {n["body"]["composition_section_id"]: n for n in nodes if n["body"].get("composition_section_id") in ("5.1", "5.5")}


def test_composition_has_no_fallback_for_unanswered_applicability(applicable_composition):
    with pytest.raises(ActionRejected):
        composed(applicable_composition)


def test_keep_verbatim_preserves_exact_body_and_anchors_concern_outside_body(applicable_composition):
    from report_agent.material_issues import MaterialIssue
    f = applicable_composition
    nodes = source_nodes(composed(f, choices()))
    for part in f.section["result_composition"]:
        if part["kind"] != "source":
            continue
        body = nodes[part["section_id"]]["body"]
        assert body["text"] == part["text"]
        issues = [MaterialIssue.model_validate(i) for i in body["material_issues"]]
        assert len(issues) == 1
        issue = issues[0]
        assert issue.kind == "unclear"
        assert issue.anchor.text in body["text"]
        assert issue.adopted_value == issue.anchor.text
        assert part["applicability_question"] in issue.question
        assert issue.sources
        assert part["applicability_question"] not in body["text"]
        assert "不表示本次已完成现场调查" not in body["text"]


def test_owner_replacements_apply_once_to_original_disjoint_spans(applicable_composition):
    f = applicable_composition
    f.section["result_composition"][0]["text"] = "Alpha Beta guidance."
    decisions = choices()
    decisions[0].update(choice="replace", replacements=[{"old": "Alpha", "new": "Beta"}, {"old": "Beta", "new": "Gamma"}])
    nodes = source_nodes(composed(f, decisions))
    assert nodes["5.1"]["body"]["text"] == "Beta Gamma guidance."
    assert f.section["result_composition"][0]["text"] == "Alpha Beta guidance."


def test_generated_result_region_cannot_receive_source_applicability_question(composition_data):
    from report_agent.commission_plan import ResultComposition
    with pytest.raises(ValueError):
        ResultComposition.model_validate({"section_id": "5.2", "kind": "assessment_summary", "text": "",
            "applicability_question": "Agent tries to use an unrelated source choice."})


def test_checkpoint_exposes_each_template_applicability_choice(source_decision_case):
    f = source_decision_case
    text = (f.cs.store.root / f.checkpoint["brief_path"]).read_text(encoding="utf-8")
    for part in f.composed_section["result_composition"]:
        if part["kind"] == "source":
            assert part["section_id"] in text
            assert part["applicability_question"] in text
    assert "keep_verbatim" in text and "replace" in text


def export_applicable_source(f):
    from report_agent.risk_scoring import create_planned_section
    from report_agent.content_export import export_snapshot
    from report_agent.content_workbook import export_workbook
    f.actor = writer(f, f.saved, section_ids=["4", "5"])
    assessment = persist(f, f.actor)
    result = create_planned_section(f.cs, f.actor, "j3-materialize", "5", [assessment["assessment_ref"]])["result"]
    f.materialized_result = result
    objects = [
        {"client_key": "report", "type": "ContentNode", "payload": {"kind": "report",
            "body": {"text": "Current source applicability report"}, "qualifiers": {}, "claim_kind": "structure"}},
        {"client_key": "assessment", "type": "ContentNode", "payload": {"kind": "chapter",
            "body": {"text": "4 Assessment", "section_id": "4", "section_heading": True}, "qualifiers": {}, "claim_kind": "structure"}},
    ]
    def edge(name, parent, child, position):
        objects.append({"client_key": name, "type": "Relation", "payload": {"subject_ref": parent,
            "object_ref": child, "predicate": "contains", "position": position,
            "provenance_kind": "adopted_during_generation"}})
    edge("assessment-edge", {"client_key": "report"}, {"client_key": "assessment"}, 0)
    edge("composition-edge", {"client_key": "report"}, result["node_ref"], 1)
    for index, field in enumerate(("ranking_ref", "evaluation_ref", "level_ref")):
        edge("assessment-" + field, {"client_key": "assessment"}, assessment[field], index)
    refs = f.cs.commit(f.actor, "j3-report-tree", objects)["result"]["refs"]
    api().record_outcome(f.cs, f.actor, "j3-outcome", "S1", refs["assessment"],
        assessment["evaluation_ref"], assessment["level_ref"], [assessment["evidence_ref"]], [])
    frozen = f.cs.freeze(f.co, "j3-freeze", refs["report"], [],
        saved_receipt_ids=["save-assessment", "j3-materialize", "j3-report-tree"])["result"]["snapshot_ref"]
    f.frozen_snapshot_ref = frozen
    word = export_snapshot(f.cs, f.co, "j3-word", frozen)["result"]
    tables = [ref for ref in result["refs"].values() if ref["type"] == "ContentNode" and f.cs.read(ref)["payload"]["kind"] == "table"]
    excel = export_workbook(f.cs, f.co, "j3-excel", frozen,
        [{"name": "Results_" + str(i), "table_ref": ref} for i, ref in enumerate(tables, 1)],
        report_export_ref=word["export_ref"])["result"]
    return ((f.cs.store.root / word["file_ref"]).read_bytes(), (f.cs.store.root / excel["file_ref"]).read_bytes())


@pytest.mark.parametrize("choice", ["keep_verbatim", "replace"])
def test_source_applicability_reaches_anchored_word_comment_and_excel_not_body(source_decision_case, choice):
    from io import BytesIO
    from zipfile import ZipFile
    from xml.etree import ElementTree as ET
    from docx import Document
    from openpyxl import load_workbook
    f = source_decision_case
    decision = deepcopy(f.decision)
    expected = {"5.1": "Exact method sentence.", "5.5": "Project OLD."}
    if choice == "replace":
        decision["template_decisions"][0].update(choice="replace", replacements=[{"old": "Exact", "new": "Approved"}])
        decision["template_decisions"][1].update(choice="replace", replacements=[{"old": "OLD", "new": "CURRENT"}])
        expected = {"5.1": "Approved method sentence.", "5.5": "Project CURRENT."}
    decide(f, decision)
    word_bytes, excel_bytes = export_applicable_source(f)
    doc = Document(BytesIO(word_bytes))
    body = "\n".join(p.text for p in doc.paragraphs)
    book = load_workbook(BytesIO(excel_bytes))
    rows = list(book["资料澄清清单"].values)
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    with ZipFile(BytesIO(word_bytes)) as archive:
        comments = ET.fromstring(archive.read("word/comments.xml"))
        document = ET.fromstring(archive.read("word/document.xml"))
    for part in (p for p in f.composed_section["result_composition"] if p["kind"] == "source"):
        assert expected[part["section_id"]] in [p.text for p in doc.paragraphs]
        question = part["applicability_question"]
        assert question not in body
        matching = [c for c in comments if question in "".join(c.itertext())]
        assert len(matching) == 1
        comment_text = "".join(matching[0].itertext())
        assert "template" in comment_text and "全文" in comment_text
        assert ("替换" if choice == "replace" else "原文") in comment_text
        comment_id = matching[0].attrib["{" + ns["w"] + "}id"]
        start = next(e for e in document.findall(".//w:commentRangeStart", ns) if e.attrib["{" + ns["w"] + "}id"] == comment_id)
        paragraph = next(p for p in document.findall(".//w:p", ns) if start in list(p))
        children = list(paragraph)
        end = next(e for e in children if e.tag.endswith("commentRangeEnd") and e.attrib == start.attrib)
        anchor = "".join(t.text or "" for e in children[children.index(start)+1:children.index(end)] for t in e.findall(".//w:t", ns))
        assert anchor == expected[part["section_id"]]
        matched_rows = [row for row in rows[1:] if question in str(row)]
        assert len(matched_rows) == 1
        assert expected[part["section_id"]] in str(matched_rows[0])
        assert matched_rows[0][7] is None, "Owner text adoption does not invent a designer response."
    assert "不表示本次已完成现场调查" not in body


@pytest.mark.parametrize("fault", ["wrong-confirmation", "wrong-decision-digest"])
def test_export_requires_composition_receipt_bound_to_frozen_owner_choices(source_decision_case, fault):
    from report_agent.content_models import Ref
    from report_agent.g3_export import validate_export
    from report_agent.store import digest
    f = source_decision_case
    decide(f)
    export_applicable_source(f)
    snapshot = f.cs.read(f.frozen_snapshot_ref)
    records = {Ref.model_validate(ref).key(): f.cs.read(ref) for ref in snapshot["payload"]["refs"]}
    confirmation_ref = snapshot["payload"]["commission_confirmation_ref"]
    root = f.materialized_result["node_ref"]
    key = "planned_section_receipt:" + digest(root)
    receipt = deepcopy(f.cs.store.get(key))
    assert receipt["commission_confirmation_ref"] == confirmation_ref
    assert receipt["decision_digest"] == digest(f.cs.read(confirmation_ref)["payload"])
    if fault == "wrong-confirmation":
        receipt["commission_confirmation_ref"] = {**confirmation_ref, "version": confirmation_ref["version"] + 1}
    else:
        receipt["decision_digest"] = "0" * 64
    f.cs.store.set(key, receipt)
    with pytest.raises(ActionRejected, match="template decision receipt"):
        validate_export(f.cs, snapshot, records)


@pytest.mark.parametrize("locator,readable", [
    ("body/paragraph 1", "正文第1段"),
    ("body/paragraph 11; chars 1-5", "正文第11段"),
    ("body/paragraph 2; chars 7-7", "正文第2段"),
    ("line 22", "第22行"),
    ("line 22; chars 1-23", "第22行"),
])
def test_validated_document_locations_render_readably(method_commission, locator, readable):
    from report_agent.content_models import Ref
    from report_agent.g3_export import citation_text
    f = method_commission
    citation = {**f.cite("outline"), "locator": locator}
    records = {Ref.model_validate(citation["source_ref"]).key(): f.cs.read(citation["source_ref"])}
    node = {"kind": "block", "body": {"text": "Offline citation fixture."}, "citations": [citation]}
    rendered = citation_text(node, records)
    assert "outline" in rendered and readable in rendered
    assert "body/paragraph" not in rendered and "; chars" not in rendered


@pytest.mark.parametrize("locator", [
    "body/paragraph 0", "body/paragraph -1", "body/paragraph 1x",
    "body/paragraph 1; chars 0-5", "body/paragraph 1; chars 8-2",
    "body/paragraph 1; chars 1-5; ignored", "body/paragraph 1; arbitrary",
    "line 22; chars 0-5", "line 22; chars 8-2", "line 22; arbitrary",
])
def test_malformed_document_locations_are_still_refused(method_commission, locator):
    from report_agent.content_models import Ref
    from report_agent.g3_export import citation_text
    f = method_commission
    citation = {**f.cite("outline"), "locator": locator}
    records = {Ref.model_validate(citation["source_ref"]).key(): f.cs.read(citation["source_ref"])}
    node = {"kind": "block", "body": {"text": "Offline citation fixture."}, "citations": [citation]}
    with pytest.raises(ActionRejected, match="G3_CITATION_LOCATION_NOT_READABLE"):
        citation_text(node, records)
