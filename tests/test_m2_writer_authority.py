"""The archived owner decision pins the exact method independent of the proposed judgment."""

from copy import deepcopy
import sqlite3
import pytest

from test_fake03_qualitative_steps import mini
from report_agent.store import digest
from report_agent.writer_judgment_authority import _authorized_method


def test_criterion_checks_plan_owner_pin_and_exact_rule():
    rule = dict(id="R", grades=[dict(id="good", min_value="0", max_value="8")])
    pack = dict(method_id="mine", version="1", indicators=[rule])
    plan = dict(
        ref={"id": "plan"},
        owner_id="content:coordinator",
        created_by="content:coordinator",
        payload=dict(method_pack=pack),
    )
    approval = dict(
        owner_id="operator",
        created_by="operator",
        task_id="checkpoint",
        ref={"id": "confirmation"},
        payload=dict(
            approved=True,
            plan_ref=plan["ref"],
            confirmed_rules=dict(method=dict(id="mine", version="1", digest=digest(pack))),
        ),
    )
    scope = dict(plan=plan, decision=approval)
    assert _authorized_method(scope, rule) == digest(pack)
    with pytest.raises(ValueError, match="METHOD"):
        _authorized_method(scope, {**rule, "grades": []})
    forged = deepcopy(approval)
    forged["owner_id"] = "some-writer"
    with pytest.raises(ValueError, match="METHOD"):
        _authorized_method({**scope, "decision": forged}, rule)


def test_context_receipt_keeps_displaced_ratio_and_decisive_use_is_refused(mini):
    from report_agent.assertion_host import AssertionHost
    from report_agent.content_store import ContentStore
    from report_agent.errors import ActionRejected
    from report_agent.writer_assessment import read_indicator_step, save_indicator_outcome
    from report_agent.writer_judgments import read_progress, _saved
    from report_agent.writer_runtime import writer_session
    from support.fake03 import install

    ws, binding, _ = mini
    install(ws, binding.plan_ref)
    cs, host = ContentStore(ws.store), AssertionHost(ws.store.root)
    with writer_session(ws, "坡段 A", None, assessment_only=True, indicator_steps=True, section_id="3") as run:
        step = read_indicator_step(cs, run.actor)
        grade = next(g["choice"] for g in step["grades"] if g["min_value"] == "25")
        request = dict(
            kind="evidence",
            grade=grade,
            value="37",
            basis_kind="direct_evidence",
            rationale="The confirmed observation records strongly weathered rock.",
            grade_claim=dict(statement="Strong weathering", fact_ids=["F03-A-WEATHERING"]),
            context_fact_ids=["F03-A-MEASURED-RATIO"],
        )
        # The same displaced measurement cannot silently become support for the selected grade.
        decisive = {
            **request,
            "grade_claim": dict(
                statement="Weathering and measured ratio", fact_ids=["F03-A-WEATHERING", "F03-A-MEASURED-RATIO"]
            ),
        }
        with pytest.raises(ActionRejected):
            save_indicator_outcome(cs, run.actor, "invalid-decisive", "X21", decisive)
        save_indicator_outcome(cs, run.actor, "valid-context", "X21", request)
        projection = read_progress(ws.store, step["assignment_digest"])["rows"]["X21"]
        (disclosure,) = projection["disclosed_context"]
        assert disclosure["role"] == "context_fact_ids"
        assert disclosure["qualifiers"]["fact_id"] == "F03-A-MEASURED-RATIO"
        assert disclosure["claim"]["citation"]["source_version"] and disclosure["claim"]["coverage"]
        with ws.store.connect() as db:
            op, identifier = db.execute("SELECT operation,assertion_id FROM writer_step_receipts").fetchone()
        row, receipt = _saved(host, op, identifier, step["assignment_digest"])
        assert disclosure in receipt["disclosed_context"]
        assert {g["purpose"] for g in row["grounds"]} == {"classification"}
        assert disclosure["assertion_id"] not in {g["assertion_id"] for g in row["grounds"]}


def test_reopened_criterion_uses_existing_confirmation_and_obeys_revocation(mini):
    from report_agent.assertion_host import AssertionHost
    from report_agent.content_store import ContentStore
    from report_agent.errors import ActionRejected
    from report_agent.writer_assessment import read_indicator_step, save_indicator_outcome
    from report_agent.writer_assignments import bound_assignment
    from report_agent.writer_judgment_authority import _criteria_key, provision_criteria
    from report_agent.writer_runtime import writer_session
    from support.fake03 import install

    ws, binding, _ = mini
    install(ws, binding.plan_ref)
    cs = ContentStore(ws.store)
    with writer_session(ws, "坡段 A", None, assessment_only=True, indicator_steps=True, section_id="3") as run:
        with ws.store.connect() as db:
            scope = bound_assignment(cs, db, run.actor)
        host = AssertionHost(ws.store.root)
        key = _criteria_key(scope)
        original = host.lookup(key)
        assert original and original.resources["criteria"]
        with sqlite3.connect(ws.store.root / "assertions.sqlite3") as db:
            count = db.execute("SELECT COUNT(*) FROM assertions").fetchone()[0]
        provision_criteria(ContentStore(ws.store), scope)
        reopened = AssertionHost(ws.store.root)
        assert reopened.lookup(key) == original
        with sqlite3.connect(ws.store.root / "assertions.sqlite3") as db:
            assert db.execute("SELECT COUNT(*) FROM assertions").fetchone()[0] == count
        reopened.revoke(original)
        indicator = read_indicator_step(cs, run.actor)["indicator_id"]
        with pytest.raises(ActionRejected, match="CRITERION_PACKET_REQUIRED"):
            save_indicator_outcome(
                cs,
                run.actor,
                "revoked-criterion",
                indicator,
                dict(kind="gap", missing="Rock subtype", question="Which subtype?"),
            )
        with sqlite3.connect(ws.store.root / "assertions.sqlite3") as db:
            assert db.execute("SELECT COUNT(*) FROM assertions").fetchone()[0] == count


def test_refused_second_producer_rolls_back_its_new_question(mini):
    from report_agent.content_store import ContentStore
    from report_agent.errors import ActionRejected
    from report_agent.writer_assessment import read_indicator_step, save_indicator_outcome
    from report_agent.writer_runtime import writer_session
    from support.fake03 import install

    ws, binding, _ = mini
    install(ws, binding.plan_ref)
    cs = ContentStore(ws.store)
    args = dict(assessment_only=True, indicator_steps=True, section_id="3")
    with writer_session(ws, "坡段 A", None, **args) as first:
        indicator = read_indicator_step(cs, first.actor)["indicator_id"]
        save_indicator_outcome(
            cs,
            first.actor,
            "producer-one",
            indicator,
            dict(kind="gap", missing="Rock subtype", question="First producer question?"),
        )
    with writer_session(ws, "坡段 A", None, **args) as second:
        with sqlite3.connect(ws.store.root / "assertions.sqlite3") as db:
            before = db.execute("SELECT id,body FROM assertions ORDER BY id").fetchall()
        with pytest.raises(ActionRejected, match="C11|producer"):
            save_indicator_outcome(
                cs,
                second.actor,
                "producer-two",
                indicator,
                dict(kind="gap", missing="Rock subtype", question="Orphan question?"),
            )
        with sqlite3.connect(ws.store.root / "assertions.sqlite3") as db:
            assert db.execute("SELECT id,body FROM assertions ORDER BY id").fetchall() == before


def test_native_b_height_alone_leaves_x11_interpretation_open(mini):
    from report_agent.content_store import ContentStore
    from report_agent.errors import ActionRejected
    from report_agent.writer_assessment import read_indicator_step, save_indicator_outcome
    from report_agent.writer_judgments import read_progress
    from report_agent.writer_runtime import writer_session

    ws, _, _ = mini
    cs = ContentStore(ws.store)
    with writer_session(ws, "坡段 B", None, assessment_only=True, indicator_steps=True, section_id="3") as writer:
        step = read_indicator_step(cs, writer.actor)
        assert step["indicator_id"] == "X11"
        grades = {g["min_value"]: g["choice"] for g in step["grades"]}
        assert "土质边坡20m≤H<30m" in grades["25"] and "岩质边坡H<30m" in grades["0"]
        quoted_height = dict(
            kind="evidence",
            grade=grades["25"],
            value="37",
            basis_kind="direct_evidence",
            rationale="The assignment records a 25 m slope.",
            quotes=["坡段 B：坡高 25 米"],
        )
        with pytest.raises(ActionRejected, match="C3:.*owner-confirmed interpretation.*save_gap"):
            save_indicator_outcome(cs, writer.actor, "no-interpreted-observation", "X11", quoted_height)
        question = "Is B soil or rock, and which confirmed observation establishes it?"
        save_indicator_outcome(
            cs,
            writer.actor,
            "preserve-x11-question",
            "X11",
            dict(kind="gap", missing="The assessed material and interpretation.", question=question),
        )
        row = read_progress(ws.store, step["assignment_digest"])["rows"]["X11"]
        assert row["claim"]["value"] is None and row["claim"]["classification"] is None
        assert row["input"]["question"] == question
