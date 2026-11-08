"""S3 read projections over committed, immutable action envelopes."""
import json
import sqlite3
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from report_agent.assertions.ids import request_digest
from report_agent.assertions.queries import (
    assertion_states, followups, open_questions, packet, report_view, stale_derivations, status,
)


@pytest.fixture
def db():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE assertions(id TEXT PRIMARY KEY, body TEXT, action TEXT, role TEXT, snapshot TEXT)")
    yield con
    con.close()


def put(db, key, kind, *, role="writer", actor="worker", subject="section", grounds=(), **claim):
    body = {
        "id": key, "subject": subject, "claim": {"kind": kind, **claim},
        "was_attributed_to": actor, "was_generated_by": "task",
        "operation_id": "op-" + key, "grounds": [{"assertion_id": x} for x in grounds],
    }
    action = {"finding": "record_finding", "decision": "decide"}.get(kind, claim.get("effect", kind))
    db.execute("INSERT INTO assertions VALUES(?,?,?,?,?)", (key, json.dumps(body), action, role, claim.get("snapshot")))


def ctx(db, *visible, resources=None, snapshot=None):
    grant = SimpleNamespace(packet=frozenset(visible), subjects=frozenset({"section"}),
                            resources=resources or {}, snapshot=snapshot)
    @contextmanager
    def read():
        yield db, grant
    return SimpleNamespace(read=read)


def test_contested_confirmation_is_restored_only_after_all_challenges_close(db):
    put(db, "s", "source")
    put(db, "c", "act", effect="confirm", target="s", role="owner")
    for n in ["1", "2"]:
        put(db, n, "act", effect="challenge", target="s", role="reviewer", actor="person-" + n)
    put(db, "w", "act", effect="retract", target="1", role="reviewer", actor="person-1")
    assert assertion_states(db)["s"]["status"] == "contested"
    put(db, "d", "decision", effect="dismiss_challenge", target="2", role="owner")
    assert assertion_states(db)["s"]["status"] == "confirmed"
    put(db, "later", "act", effect="retract", target="d", role="owner")
    assert assertion_states(db)["s"]["status"] == "contested"


def test_acts_on_acts_stop_at_retraction(db):
    put(db, "s", "source")
    put(db, "e", "act", effect="endorse", target="s", role="reviewer")
    put(db, "w", "act", effect="retract", target="e")
    # A malformed historical attempt cannot resurrect an endorsement.
    put(db, "again", "act", effect="retract", target="w")
    states = assertion_states(db)
    assert (states["s"]["status"], states["e"]["status"], states["w"]["status"]) == (
        "proposed", "retracted", "proposed",
    )


def test_supersession_marks_typed_and_envelope_dependents_including_reviews(db):
    put(db, "s", "source")
    put(db, "replacement", "source")
    put(db, "j", "judgment", grounds=["s"])
    put(db, "r", "derived", inputs=["j"])
    put(db, "review", "finding", target="r", snapshot="version", role="reviewer")
    put(db, "change", "act", effect="supersede", target="s", successor="replacement")
    view = ctx(db, "s", "j", "review")
    assert status(view, "s") == {"status": "superseded", "stale": False}
    assert status(view, "review") == {"status": "proposed", "stale": True}
    assert set(stale_derivations(view, "s")) == {"j", "review"}
    assert not assertion_states(db)["replacement"]["stale"]


def test_open_questions_reopen_after_answer_retraction_and_packet_is_scoped(db):
    put(db, "q", "question", text="Please decide", affects="classification")
    put(db, "private", "question", subject="private-section")
    view = ctx(db, "q", "private")
    assert [r["id"] for r in open_questions(view)] == ["q"]
    assert [r["id"] for r in packet(view)] == ["q"]
    for key in ("private", "nonexistent"):
        with pytest.raises(PermissionError):
            status(view, key)
    put(db, "a", "decision", effect="answer", target="q", role="owner")
    assert open_questions(view) == ()
    put(db, "retract", "act", effect="retract", target="a", role="owner")
    assert [r["id"] for r in open_questions(view)] == ["q"]


def test_frozen_members_and_file_pair_do_not_change_after_retraction(db):
    import hashlib

    put(db, "member", "source", citation={"source_version": "pdf", "page": 1, "quote": "text"})
    snapshot = {"members": {"first": "member"}, "scope": "scope", "word": b"old-word", "excel": b"old-xlsx"}
    resources = {"snapshots": {"snap": snapshot}}
    view = ctx(db, "snap", "member", "pdf", resources=resources, snapshot="snap")
    saved = report_view(view, "snap")
    assert saved["members"] == {"first": "member"}
    assert saved["records"][0]["claim"]["citation"]["quote"] == "text"
    assert saved["records"][0]["operation_id"] == "op-member"
    assert saved["word_sha256"] == hashlib.sha256(b"old-word").hexdigest()
    assert saved["excel_sha256"] == hashlib.sha256(b"old-xlsx").hexdigest()
    put(db, "retract", "act", effect="retract", target="member", role="owner")
    assert report_view(view, "snap") == saved
    for partial in [ctx(db, "snap", resources=resources),
                    ctx(db, "member", resources=resources),
                    ctx(db, "member", "snap", resources=resources, snapshot="other")]:
        with pytest.raises(PermissionError):
            report_view(partial, "snap")


def test_partial_read_does_not_disclose_unauthorized_reference_ids(db):
    put(db, "private", "source", subject="other")
    put(db, "public", "derived", inputs=["private"], grounds=["private"])
    view = ctx(db, "public", "private")
    record, = packet(view)
    assert record["grounds"] == [] and record["claim"]["inputs"] == []
    assert "private" not in json.dumps(record)


def test_followups_require_live_independent_review_and_confirmed_scope(db):
    put(db, "j", "judgment", review_flags=["value suggested"], basis="evidence")
    put(db, "scope", "convention", role="coordinator", rule=request_digest(["first", "second"]))
    put(db, "wrong-scope", "convention", role="coordinator")
    put(db, "q", "question", affects="classification")
    put(db, "wrong-proof", "act", role="owner", effect="confirm", target="wrong-scope")
    snapshot = {"members": {"first": "j"}, "scope": "scope", "word": b"w", "excel": b"x"}
    scope = {"slots": ["first", "second"], "confirmation": "wrong-proof"}
    resources = {"snapshots": {"snap": snapshot}, "scopes": {"scope": scope}}
    view = ctx(db, "snap", "scope", "j", "q", resources=resources, snapshot="snap")
    assert followups(view) == {
        "unreviewed": ["j"], "stale": [], "open_questions": ["q"], "flagged": ["j"], "missing_slots": [],
    }
    scope["confirmation"] = "proof"
    put(db, "proof", "act", role="owner", effect="confirm", target="scope")
    put(db, "self", "finding", role="reviewer", target="j", snapshot="snap")
    put(db, "old", "finding", role="reviewer", actor="independent", target="j", snapshot="old-snap")
    assert followups(view)["unreviewed"] == ["j"]
    assert followups(view)["missing_slots"] == ["second"]
    put(db, "review", "finding", role="reviewer", actor="independent", target="j", snapshot="snap")
    assert followups(view)["unreviewed"] == []
    put(db, "retract", "act", role="owner", effect="retract", target="review")
    assert followups(view)["unreviewed"] == ["j"]


def test_rendering_one_subject_uses_that_section_of_the_bound_snapshot(db):
    put(db, "one", "judgment", subject="one")
    put(db, "two", "judgment", subject="two")
    snapshot = {"members": {"one.slot": "one", "two.slot": "two"}, "word": b"w", "excel": b"x"}
    resources = {"snapshots": {"snap": snapshot}}
    grant = SimpleNamespace(packet=frozenset(("snap", "one", "two")), subjects=frozenset(("one", "two")),
                            resources=resources, snapshot="snap")

    @contextmanager
    def read():
        yield db, grant

    view = SimpleNamespace(read=read)
    section = report_view(view, "snap", subject="two")
    assert section["members"] == {"two.slot": "two"}
    assert [r["id"] for r in section["records"]] == ["two"]
    with pytest.raises(PermissionError):
        report_view(view, "snap", subject="elsewhere")


def test_stale_answer_and_stale_dismissal_do_not_close_live_issues(db):
    put(db, "fact", "source")
    put(db, "q", "question", affects="classification")
    put(db, "a", "decision", effect="answer", target="q", grounds=["fact"], role="owner")
    put(db, "subject", "source")
    put(db, "ch", "act", effect="challenge", target="subject", role="reviewer")
    put(db, "dismiss", "decision", effect="dismiss_challenge", target="ch", grounds=["fact"], role="owner")
    assert not assertion_states(db)["q"]["open"]
    assert not assertion_states(db)["subject"]["challenged"]
    put(db, "withdraw", "act", effect="retract", target="fact", role="owner")
    states = assertion_states(db)
    assert states["a"]["stale"] and states["q"]["open"]
    assert states["dismiss"]["stale"] and states["subject"]["challenged"]
