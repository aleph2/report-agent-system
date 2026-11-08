"""Offline, unwired S2 examples. Host projections are supplied explicitly."""
import hashlib
import json
import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from report_agent.assertions.schema.kinds import Assertion, is_canonical_id

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src/report_agent"
SCHEMA = SRC / "assertions/schema"
CATALOG = json.loads((SCHEMA / "actions.json").read_text())
SQL = (SCHEMA / "checks.sql").read_text()


def envelope(claim, grounds=()):
    return dict(id="r1", subject="A", claim=claim, grounds=list(grounds),
                was_attributed_to="agent-1", was_generated_by="task-1", operation_id="op-1",
                observed_at="2026-11-07T12:00:00Z", recorded_at="2026-11-07T12:00:01Z",
                schema_version="s2-proposal-1", check_version="s2-proposal-2")


def check(row, ctx):
    valid = Assertion.model_validate(row)
    with sqlite3.connect(":memory:") as conn:
        conn.create_function("is_canonical_id", 1, is_canonical_id, deterministic=True)
        conn.create_function("decimal_between", 3, lambda x, lo, hi: lo is not None and
                             hi is not None and Decimal(str(lo)) <= Decimal(str(x)) <= Decimal(str(hi)))
        return {code for code, _ in conn.execute(SQL, dict(row=valid.model_dump_json(),
                ctx=json.dumps(ctx), catalog=json.dumps(CATALOG)))}


def supported():
    row = envelope(dict(kind="judgment", basis="evidence", classification="m", value="37",
                   warrant=dict(criterion="rule", criterion_version="v1", rationale="Applicable range")),
                   [dict(assertion_id="f1", proposition="count", purpose="classification")])
    ctx = dict(action="save_judgment", role="writer", packet=["f1", "rule"], records={
        "f1": dict(subject="A", state="value", status="confirmed", stale=False, supports=["count"]),
        "rule": dict(kind="convention", status="confirmed", version="v1", stale=False,
                     value_policy="confirmed_midpoint", bands={"m": {"min":"25","max":"49","midpoint":"37"},
                     "l":{"min":"0","max":"24","midpoint":"12"}})},
        applicable_readings=["m","m"], readings_exhaustive=True,
        satisfied_authority_conditions=["calculator_determined","producer_binding"])
    return row, ctx


def test_evidence_and_open_world():
    row, ctx = supported()
    assert check(row, ctx) == set()
    ctx["records"]["f1"]["state"] = "unknown"
    assert check(row, ctx) == {"C3"}
    with pytest.raises(ValidationError, match="C2"):
        Assertion.model_validate(envelope(dict(kind="source", predicate="count", state="no_value", coverage="A")))
    Assertion.model_validate(envelope(dict(kind="source", predicate="count", state="unknown", coverage="A")))
    Assertion.model_validate(envelope(dict(kind="source", predicate="count", state="no_value", coverage="A",
        citation=dict(source_version="src@v1", page=1, quote="No records in unit A."))))


def test_packet_context_warrant_and_conflict():
    row, ctx = supported()
    ctx["packet"].remove("f1")
    assert check(row, ctx) == {"C4"}
    ctx["packet"].append("f1")
    ctx["records"]["f1"]["subject"] = "B"
    assert check(row, ctx) == {"C5"}
    row["grounds"][0]["transfer_convention"] = "lift"
    ctx["records"]["lift"] = {"kind":"convention","status":"confirmed","stale":False,
                               "from":"B","to":"A","proposition":"count"}
    ctx["packet"].append("lift")
    assert check(row, ctx) == set()
    row["claim"]["value"] = "49.0000000000000001"
    assert check(row, ctx) == {"C6"}
    row["claim"]["value"] = "37"
    ctx["records"]["f1"]["conflicts"] = [{"id":"c", "precedence":"p"}]
    assert check(row, ctx) == {"C9"}
    ctx["records"]["p"] = dict(kind="convention", status="confirmed", stale=False, resolves="c", preferred="f1")
    assert check(row, ctx) == set()


def test_ambiguous_evidence_assumptions_and_weak_inputs():
    row, ctx = supported()
    ctx["applicable_readings"] = ["m","l"]
    assert check(row, ctx) == {"C7"}
    row["claim"].update(basis="gap", alternatives=["l","m"], classification=None, value=None, question="q")
    ctx["packet"].append("q")
    assert check(row, ctx) == set()
    row["claim"].update(basis="assumption", classification="m")
    with pytest.raises(ValidationError, match="C8"):
        check(row, ctx)
    row["claim"]["defeaters"] = ["An explicit count in the second inventory"]
    assert check(row, ctx) == {"C7"}
    ctx["applicable_readings"] = ["m"]
    assert check(row, ctx) == set()
    row = envelope(dict(kind="derived", rule_version="v1", inputs=["f1"], strength="determined", value="20"))
    ctx.update(action="derive_result",role="calculator")
    ctx["packet"].append("v1")
    ctx["records"]["f1"]["strength_rank"] = 1
    assert check(row, ctx) == {"C10"}
    row["claim"]["strength"] = "provisional"
    assert check(row, ctx) == set()


def release():
    slots = [f"slot-{n}" for n in range(22)]
    members = [dict(slot=s, id=f"r-{s}", stale=False, status="endorsed", kind="judgment",
                    producer="writer-1", open_grade_questions=0) for s in slots]
    ids = [m["id"] for m in members]
    pair = dict(snapshot="s1", records=ids, word_sha256="a"*64, excel_sha256="b"*64)
    row = envelope(dict(kind="decision",effect="release",reason="Reviewed pair",target="outputs",pair=pair))
    return row, dict(action="release",role="coordinator",packet=["outputs","s1",*ids],
        required_list_owner_confirmed=True,scope_id="outputs",required_slots=slots,snapshot=dict(id="s1",members=members,
        word_sha256="a"*64,excel_sha256="b"*64),reviews=[dict(snapshot="s1",record=i,stale=False,
        passed=True, action="endorse", role="reviewer", actor="reviewer-1") for i in ids],satisfied_authority_conditions=["frozen_pair","release_delegation"],
        delegation=dict(active=True,actor="agent-1",subject="A",action="release"))


@pytest.mark.parametrize(("status", "action"), [
    ("confirmed", "record_finding"), ("confirmed", "endorse"), ("endorsed", "endorse"),
])
def test_release_accepts_an_independent_reviewer(status, action):
    row, ctx = release()
    ctx["snapshot"]["members"][0]["status"] = status
    ctx["reviews"][0]["action"] = action
    assert check(row, ctx) == set()


@pytest.mark.parametrize(("action", "role", "actor", "producer"), [
    ("endorse", "coordinator", "agent-1", "writer-1"),
    ("endorse", "coordinator", "other-coordinator", "writer-1"),
    ("record_finding", "reviewer", "writer-1", "writer-1"),
    ("endorse", "reviewer", "agent-1", "writer-1"),
    ("record_finding", "reviewer", "", "writer-1"),
    ("record_finding", "reviewer", "reviewer-1", None),
    ("sign_off", "reviewer", "reviewer-1", "writer-1"),
    ("endorse", "reviewer", " agent-1 ", "writer-1"),
    ("record_finding", "reviewer", "writer-1", "\u3000writer-1\u3000"),
    ("record_finding", "reviewer", "\t", "writer-1"),
])
def test_release_requires_independent_review_on_every_record(action, role, actor, producer):
    row, ctx = release()
    member = ctx["snapshot"]["members"][0]
    member["producer"] = producer
    if action != "endorse":
        member["status"] = "confirmed"
    ctx["reviews"][0].update(action=action, role=role, actor=actor)
    assert check(row, ctx) == {"C12"}


def test_coordinator_endorsement_does_not_establish_endorsed_status_for_release():
    row, ctx = release()
    endorsement = ctx["reviews"][0]
    ctx["reviews"].append(dict(endorsement, action="record_finding"))
    endorsement.update(actor="agent-1", role="coordinator")
    assert check(row, ctx) == {"C12"}
    ctx["snapshot"]["members"][0]["status"] = "confirmed"
    assert check(row, ctx) == set()


@pytest.mark.parametrize("change", ["omit","review","digest","stale","question","contested","source_endorsement","duplicate"])
def test_release_exact_pair_and_complete_confirmed_output_list(change):
    row, ctx = release()
    assert check(row, ctx) == set()
    first = ctx["snapshot"]["members"][0]
    if change == "omit":
        ctx["snapshot"]["members"].pop()
        row["claim"]["pair"]["records"].pop()
    elif change == "duplicate":
        ctx["snapshot"]["members"][-1]["id"] = first["id"]
        row["claim"]["pair"]["records"].pop()
        ctx["reviews"].pop()
    elif change == "review":
        ctx["reviews"][0]["snapshot"] = "old"
    elif change == "digest":
        ctx["snapshot"]["word_sha256"] = "c"*64
    elif change == "source_endorsement":
        first["kind"] = "source"
    else:
        first.update({"stale": {"stale": True}, "question": {"open_grade_questions": 1},
                      "contested":{"status":"contested"}}[change])
    assert check(row, ctx) == {"C12"}


def test_draft_signoff_and_owner_authority():
    row, ctx = release()
    ctx["delegation"]["active"] = False
    assert check(row, ctx) == {"C11"}
    ctx.update(action="deliver_draft", satisfied_authority_conditions=["frozen_pair","draft_disclosures"])
    row["claim"]["effect"] = "deliver_draft"
    ctx["snapshot"]["gaps"] = ["q"]
    assert check(row, ctx) == {"C11"}
    row["claim"]["disclosed_gaps"] = ["q"]
    ctx["packet"].append("q")
    assert check(row, ctx) == set()
    row = envelope(dict(kind="act", effect="sign_off",target="release-1",reason="Engineering review"))
    ctx.update(action="sign_off",role="engineer",actor_class="person",engineer_name="Engineer A",
               packet=["release-1"],target={"effect":"release","status":"confirmed"},
               satisfied_authority_conditions=["named_engineer","live_release"])
    assert check(row,ctx) == set()
    ctx["engineer_name"] = ""
    assert check(row,ctx) == {"C11"}


def test_method_provenance_and_all_eleven_criteria():
    raw = (SRC / "methods/high_slope_guideline.json").read_bytes()
    pack = json.loads(raw)
    proposal = json.loads((SRC / "methods/high_slope_guideline.assertions.proposal.json").read_text())
    assert hashlib.sha256(raw).hexdigest() == proposal["transcription_sha256"]
    assert [x["id"] for x in proposal["criteria"]] == [x["id"] for x in pack["indicators"]]
    for section, criterion in zip(proposal["criteria"], pack["indicators"], strict=True):
        for assertion, band in zip(section["source_assertions"], criterion["grades"], strict=True):
            i, j = (int(assertion["description_at"]["pointer"].split("/")[k]) for k in (2,4))
            assert pack["indicators"][i]["grades"][j]["description"] == band["description"]
            assert (assertion["grade"],assertion["min"],assertion["max"]) == (
                band["id"], band["min_value"], band["max_value"])
            assert assertion["physical_pages"] == criterion["source_pages"]
    fixture = SRC.parents[1] / "tests/fake_data/mini_commission/writer-conventions.json"
    deferred = json.loads(fixture.read_bytes())["method_conventions"]["A/X51"]
    assert deferred["basis"] == "gap" and deferred["value"] is None
    assert deferred["possibilities"] == ["low","moderate"]

def test_action_routes_actor_and_status():
    row = envelope(dict(kind="act", effect="retract", target="challenge", reason="Withdraw finding"))
    ctx = dict(action="retract", role="reviewer", packet=["challenge"], target={
        "kind": "act", "effect": "challenge", "status": "confirmed", "author": "agent-1"},
        satisfied_authority_conditions=["live_target","author_or_owner","challenge_resolution","release_owner"])
    assert check(row, ctx) == set()
    ctx["target"]["author"] = "someone-else"
    assert check(row, ctx) == {"C11"}
    ctx["role"] = "owner"
    assert check(row, ctx) == {"C11"}
    row["claim"] = dict(kind="decision", effect="dismiss_challenge", target="challenge", reason="Owner ruled")
    ctx.update(action="decide",satisfied_authority_conditions=["answer_or_dismiss","decision_scope"])
    assert check(row, ctx) == set()
    ctx["role"] = "coordinator"
    assert check(row, ctx) == {"C11"}
    row["claim"] = dict(kind="decision", effect="release", target="outputs", reason="Tried generic route",
                        pair=release()[0]["claim"]["pair"])
    assert "C11" in check(row,ctx)


def test_scope_target_and_action_output_are_bound():
    row, ctx = release()
    ctx["scope_id"] = "obsolete-scope"
    assert "C12" in check(row,ctx)
    row = envelope(dict(kind="question", text="Which source governs?", affects="classification"))
    ctx = dict(action="ask",role="writer",actor_class="agent")
    assert check(row,ctx) == set()
    ctx["actor_class"] = "service"
    assert "C11" in check(row,ctx)
    ctx.update(action="save_recommendation",role="writer")
    assert "C1" in check(row,ctx)


def test_in_band_move_needs_directional_entitlement_and_audit():
    row, ctx = supported()
    row["claim"]["value"] = "49"
    assert check(row,ctx) == {"C6"}
    row["grounds"].append(dict(assertion_id="quality", purpose="adjustment", proposition="higher"))
    ctx["packet"].append("quality")
    ctx["records"]["quality"] = dict(subject="A", state="value",status="confirmed",stale=False,supports=["higher"])
    row["claim"]["adjustment"] = dict(proposed="49",disposition="accepted_with_flag",
                                      rationale="Applicable survey quality",ground_ids=["quality"])
    row["claim"]["review_flags"] = ["ADJUSTMENT_REQUIRES_SEMANTIC_REVIEW"]
    assert check(row,ctx) == {"C6"}
    ctx["permitted_adjustments"] = [dict(subject="A",criterion="rule",effective_value="49",support_ids=["quality"])]
    assert check(row,ctx) == set()
    for name, invalid_value in (("stale",True),("status","proposed"),("state","unknown"),("supports",["count"])):
        old = ctx["records"]["quality"][name]
        ctx["records"]["quality"][name] = invalid_value
        assert check(row,ctx) == {"C6"}
        ctx["records"]["quality"][name] = old
    row["claim"].update(value="37", adjustment=dict(proposed="49",disposition="refused_midpoint_retained",
                       rationale="Directional support unavailable",ground_ids=["quality"]))
    ctx["permitted_adjustments"] = []
    assert check(row,ctx) == set()
    assert row["claim"]["adjustment"]["proposed"] == "49"


@pytest.mark.parametrize("support_kind", ["derived", "recommendation", "conflict"])
def test_typed_input_cannot_hide_subject_transfer(support_kind):
    row = envelope(dict(kind="derived", rule_version="v", inputs=["input"], strength="determined", value="12"))
    ctx = dict(action="derive_result", role="calculator", packet=["input","v"],
               records={"input":dict(subject="B",strength_rank=2)})
    purpose = "input"
    if support_kind == "recommendation":
        row = envelope(dict(kind="recommendation", statement="Use this result", basis=["input"]))
        ctx.update(action="save_recommendation", role="writer")
    elif support_kind == "conflict":
        row = envelope(dict(kind="conflict", observations=["input","other"]))
        ctx.update(action="record_conflict", role="coordinator")
        ctx["packet"].append("other")
        ctx["records"]["other"] = dict(subject="A")
        purpose = "context"
    assert check(row,ctx) == {"C5"}
    row["grounds"].append(dict(assertion_id="input",purpose=purpose,proposition="aggregate",
                              transfer_convention="lift"))
    ctx["packet"].append("lift")
    ctx["records"]["lift"] = {"kind":"convention","status":"confirmed","stale":False,
                               "from":"B","to":"A","proposition":"aggregate"}
    assert check(row,ctx) == set()
