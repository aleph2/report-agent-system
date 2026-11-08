"""Exercise the approved SQL with authority projected from persisted records and host grants."""
import hashlib
from types import SimpleNamespace

import pytest

from report_agent.assertions.authority import authority_projection
from report_agent.assertions.ids import request_digest
from report_agent.assertions.queries import assertion_states
from report_agent.assertions.schema.kinds import Assertion
from report_agent.assertions.refusals import enforce
from .test_status import db, put


def issued(role, actor, *, packet=(), resources=None, snapshot=None):
    return SimpleNamespace(role=role, principal=actor, task="task", attempt="attempt", plan="plan",
                           subjects=frozenset({"section"}), packet=frozenset(packet), snapshot=snapshot,
                           resources=resources or {}, actor_class="person" if role in ("owner", "engineer") else "agent")


def grant_for(action, target, actor="coord", **extras):
    return {"action": action, "target": target, "actor": actor, "subject": "section",
            "task": "task", "attempt": "attempt", "plan": "plan", "active": True,
            **({"snapshot": "snap"} if action == "release" else {}), **extras}


def check_claim(db, grant, action, claim):
    row = Assertion(
        id="out", subject="section", claim=claim, grounds=(), was_attributed_to=grant.principal,
        was_generated_by=grant.task, operation_id="new", observed_at="2026-11-08T12:00:00Z",
        recorded_at="2026-11-08T12:00:01Z", schema_version="s2-proposal-1", check_version="s2-proposal-2",
    )
    projection = authority_projection(db, grant, action, row, assertion_states(db))
    try:
        enforce(db, row, projection)
    except ValueError as error:
        return {refusal.split(":", 1)[0] for refusal in str(error).split("; ")}
    return set()


def delivery(db):
    put(db, "scope", "convention", rule=request_digest(["required"]))
    put(db, "owner-confirm", "act", actor="owner", role="owner", effect="confirm", target="scope")
    put(db, "j", "judgment", role="writer", actor="producer", basis="evidence")
    put(db, "confirmed", "act", actor="owner", role="owner", effect="confirm", target="j")
    snapshot = {"members": {"required": "j"}, "scope": "scope", "word": b"word", "excel": b"excel"}
    resources = {"scopes": {"scope": {"confirmation": "owner-confirm", "slots": ["required"]}},
                 "snapshots": {"snap": snapshot}, "authorities": [grant_for("release", "scope")]}
    grant = issued("coordinator", "coord", packet=["snap","scope","j","open"], resources=resources, snapshot="snap")
    pair = dict(snapshot="snap", records=["j"], word_sha256=hashlib.sha256(b"word").hexdigest(),
                excel_sha256=hashlib.sha256(b"excel").hexdigest())
    return grant, dict(kind="decision", effect="release", target="scope", reason="deliver", pair=pair)


def test_release_needs_same_snapshot_independent_reviewer_and_absence_of_open_questions(db):
    grant, claim = delivery(db)
    for key, role, actor, snap in [("self","reviewer","producer","snap"),("rel","reviewer","coord","snap"),
                                  ("old","reviewer","reviewer","old"),("coord","coordinator","other","snap")]:
        put(db, key, "finding", role=role, actor=actor, snapshot=snap, target="j", conclusion="passed")
    assert "C12" in check_claim(db, grant, "release", claim)
    put(db, "review", "finding", role="reviewer", actor="reviewer", snapshot="snap", target="j", conclusion="passed")
    assert check_claim(db, grant, "release", claim) == set()
    put(db, "open", "question", affects="classification", text="undecided")
    assert "C12" in check_claim(db, grant, "release", claim)
    put(db, "answered", "decision", role="owner", effect="answer", target="open")
    assert check_claim(db, grant, "release", claim) == set()
    put(db, "withdraw", "act", role="reviewer", effect="retract", target="review")
    assert "C12" in check_claim(db, grant, "release", claim)


@pytest.mark.parametrize("field", ["actor", "subject", "action", "task", "attempt", "plan", "target", "snapshot", "active"])
def test_release_delegation_requires_exact_issued_binding(db, field):
    grant, claim = delivery(db)
    grant.resources["authorities"][0][field] = False if field == "active" else "other"
    assert "C11" in check_claim(db, grant, "release", claim)


def test_draft_checks_pair_and_known_gaps_before_delivery(db):
    grant, claim = delivery(db)
    put(db, "open", "question", affects="value")
    claim["effect"] = "deliver_draft"
    assert "C11" in check_claim(db, grant, "deliver_draft", claim)
    claim["disclosed_gaps"] = ["open"]
    assert check_claim(db, grant, "deliver_draft", claim) == set()
    claim["pair"]["word_sha256"] = "0" * 64
    assert "C11" in check_claim(db, grant, "deliver_draft", claim)


def test_retraction_is_terminal_and_challenge_withdrawal_is_personal(db):
    put(db, "s", "source")
    put(db, "challenge", "act", effect="challenge", target="s", role="reviewer", actor="reviewer")
    put(db, "withdraw", "act", effect="retract", target="challenge", role="reviewer", actor="reviewer")
    grant = issued("owner", "owner", packet=["s","challenge","withdraw"])
    claim = dict(kind="act", effect="retract", target="withdraw", reason="try to resurrect")
    assert "C11" in check_claim(db, grant, "retract", claim)


def test_owner_confirmation_and_challenge_act_lifecycle(db):
    put(db, "s", "source", actor="coordinator")
    put(db, "c", "convention", actor="coordinator")
    grant = issued("owner", "owner", packet=["s", "c", "ch"])
    confirm = dict(kind="act", effect="confirm", target="c", reason="reviewed")
    assert check_claim(db, grant, "confirm", confirm) == set()
    engineer = issued("engineer", "eng", packet=grant.packet,
                      resources={"authorities": [grant_for("confirm", "s", actor="eng")]})
    assert "C11" in check_claim(db, engineer, "confirm", confirm)
    assert check_claim(db, engineer, "confirm", dict(confirm, target="s")) == set()
    put(db, "ch", "act", effect="challenge", target="s", role="reviewer", actor="reviewer")
    withdrawal = dict(kind="act", effect="retract", target="ch", reason="withdrawn")
    assert "C11" in check_claim(db, grant, "retract", withdrawal)
    reviewer = issued("reviewer", "reviewer", packet=grant.packet)
    assert check_claim(db, reviewer, "retract", withdrawal) == set()
    dismissal = dict(kind="decision", effect="dismiss_challenge", target="ch", reason="resolved")
    assert check_claim(db, grant, "decide", dismissal) == set()
    assert "C11" in check_claim(db, reviewer, "decide", dismissal)


def test_coordinator_decision_and_named_personal_signoff(db):
    put(db, "q", "question", affects="presentation")
    put(db, "release", "decision", role="coordinator", actor="coord", effect="release", target="scope")
    answer = dict(kind="decision", effect="answer", target="q", reason="answer")
    coordinator = issued("coordinator", "coord", packet=["q", "release"])
    assert "C11" in check_claim(db, coordinator, "decide", answer)
    coordinator.resources["authorities"] = [grant_for("decide", "q")]
    assert check_claim(db, coordinator, "decide", answer) == set()
    sign = dict(kind="act", effect="sign_off", target="release", reason="reviewed")
    engineer = issued("engineer", "eng", packet=["release"],
                      resources={"authorities": [grant_for("sign_off", "release", actor="eng")]})
    assert "C11" in check_claim(db, engineer, "sign_off", sign)
    engineer.resources["authorities"][0]["engineer_name"] = "Named reviewer"
    assert check_claim(db, engineer, "sign_off", sign) == set()
    withdrawal = dict(kind="act", effect="retract", target="release", reason="new information")
    assert "C11" in check_claim(db, coordinator, "retract", withdrawal)
    assert check_claim(db, issued("owner", "owner", packet=["release"]), "retract", withdrawal) == set()
    put(db, "withdraw", "act", role="owner", effect="retract", target="release")
    assert "C11" in check_claim(db, engineer, "sign_off", sign)


def test_supersede_requires_matching_active_successor_and_owner_can_resolve_contested(db):
    for key, subject in [("s","section"), ("other","other"), ("replacement","section")]:
        put(db, key, "source", subject=subject, actor="producer")
    put(db, "challenge", "act", role="reviewer", effect="challenge", target="s")
    owner = issued("owner", "owner", packet=["s","replacement","other"])
    supersede = dict(kind="act", effect="supersede", target="s", successor="replacement", reason="updated")
    assert check_claim(db, owner, "supersede", supersede) == set()
    assert "C11" in check_claim(db, owner, "supersede", dict(supersede, successor="other"))
    assert "C11" in check_claim(db, owner, "supersede", dict(supersede, successor="s"))
    assert "C11" in check_claim(db, issued("writer", "producer", packet=owner.packet), "supersede", supersede)


def test_release_requires_owner_confirmation_for_this_scope_and_every_required_slot(db):
    grant, claim = delivery(db)
    put(db, "review", "finding", role="reviewer", actor="independent", target="j", snapshot="snap", conclusion="passed")
    assert check_claim(db, grant, "release", claim) == set()
    grant.resources["scopes"]["scope"]["slots"].append("absent")
    assert "C12" in check_claim(db, grant, "release", claim)
    grant.resources["scopes"]["scope"]["slots"].pop()
    put(db, "other", "convention")
    put(db, "wrong-proof", "act", role="owner", actor="owner", effect="confirm", target="other")
    grant.resources["scopes"]["scope"]["confirmation"] = "wrong-proof"
    assert "C12" in check_claim(db, grant, "release", claim)


@pytest.mark.parametrize("action", ["record_finding", "record_presentation_check"])
def test_review_writes_are_bound_to_original_snapshot_and_file(db, action):
    grant, release = delivery(db)
    grant.role = "reviewer" if action == "record_finding" else "layout"
    grant.principal = grant.role
    if action == "record_finding":
        claim = dict(kind="finding", target="j", snapshot="snap", conclusion="passed")
        wrong = dict(claim, target="scope")
    else:
        claim = dict(kind="presentation_check", snapshot="snap", check="rendered", outcome="passed",
                     artifact_digest=release["pair"]["word_sha256"])
        wrong = dict(claim, artifact_digest="1" * 64)
    assert check_claim(db, grant, action, claim) == set()
    with pytest.raises(ValueError, match="C11"):
        check_claim(db, grant, action, wrong)
    with pytest.raises(ValueError, match="C11"):
        check_claim(db, grant, action, dict(claim, snapshot="other"))


@pytest.mark.parametrize("change", ["word", "excel", "members", "scope"])
def test_same_snapshot_id_cannot_be_substituted_across_launch_grants(tmp_path, change):
    from uuid import uuid4

    from report_agent.assertion_host import AssertionHost, Grant

    host = AssertionHost(tmp_path)
    frozen = {"snapshots": {"frozen": {"members": {"required": "j"}, "scope": "scope",
                                       "word": b"reviewed word", "excel": b"reviewed excel"}}}
    def route(resources):
        return Grant(str(uuid4()), "reviewer", "task", "first", "plan", {"section"},
                     {"frozen", "j", "scope"}, {"record_finding"}, snapshot="frozen", resources=resources)

    host.authorize(route(frozen))
    host.authorize(route(frozen))
    fields = dict(frozen["snapshots"]["frozen"])
    fields[change] = {"word": b"other word", "excel": b"other excel",
                      "members": {"required": "other"}, "scope": "different"}[change]
    with pytest.raises(ValueError):
        AssertionHost(tmp_path).authorize(route({"snapshots": {"frozen": fields}}))


def test_same_scope_id_cannot_substitute_required_slots_under_old_confirmation(tmp_path):
    from uuid import uuid4

    from report_agent.assertion_host import AssertionHost, Grant

    host = AssertionHost(tmp_path)
    def with_slots(actor, slots):
        return Grant(actor, "coordinator", "task", "attempt", "plan", {"section"},
                     {"scope"}, {"release"}, resources={
                         "scopes": {"scope": {"slots": slots, "confirmation": "owner-confirmed"}},
                     })
    host.authorize(with_slots(str(uuid4()), ["first", "second"]))
    with pytest.raises(ValueError):
        host.authorize(with_slots(str(uuid4()), ["first"]))


def test_frozen_binding_first_registration_matches_what_owner_confirmed(db):
    grant, claim = delivery(db)
    put(db, "approved", "finding", role="reviewer", actor="independent", target="j", snapshot="snap", conclusion="passed")
    # Simulate first registration by an issuer who supplies a different one-slot
    # scope and a corresponding renamed slot in the frozen snapshot.
    grant.resources["scopes"]["scope"]["slots"] = ["different"]
    grant.resources["snapshots"]["snap"]["members"] = {"different": "j"}
    assert "C12" in check_claim(db, grant, "release", claim)


@pytest.mark.parametrize("review_action", ["record_finding", "endorse"])
def test_public_release_lifecycle_binds_review_pair_scope_and_human_authority(tmp_path, review_action):
    from uuid import uuid4

    from report_agent import assertions
    from report_agent.assertion_host import AssertionHost, Grant

    host = AssertionHost(tmp_path)
    actors = {role: str(uuid4()) for role in ("coordinator", "reviewer", "engineer", "owner")}
    permitted = set()
    resources = {}

    def call(role, action, claim, *, snap=None, delegated=False):
        actor = actors[role]
        if delegated:
            authorities = [grant_for(action, claim["target"], actor=actor, engineer_name="Named Engineer")]
        else:
            authorities = []
        grant = Grant(actor, role, "task", "attempt", "plan", {"section"}, permitted, {action}, snapshot=snap,
                      resources={**resources, "authorities": authorities})
        ctx = host.issue(grant, action, str(uuid4()))
        saved = getattr(assertions, action)(ctx, subject="section", claim=claim)
        permitted.add(saved["id"])
        return saved["id"]

    scope = call("coordinator", "record_convention",
                 dict(kind="convention", scope="section", rule=request_digest(["required"])))
    member = call("coordinator", "record_convention", dict(kind="convention", scope="section", rule="content"))
    proof = call("owner", "confirm", dict(kind="act", effect="confirm", target=scope, reason="Checked slots"))
    call("owner", "confirm", dict(kind="act", effect="confirm", target=member, reason="Checked content"))
    permitted.add("snap")
    endorsement = dict(kind="act", effect="endorse", target=member, reason="Reviewed")
    if review_action == "endorse":
        # Ordinary advice is permitted and cannot later be promoted to pair-specific review.
        call("reviewer", "endorse", endorsement)
        with pytest.raises(ValueError, match="C11"):
            call("reviewer", "endorse", endorsement, snap="snap")
        for name, assets in (
            ("incomplete", {"members": {"required": member}, "word": b"w"}),
            ("wrong-target", {"members": {"required": scope}, "word": b"w", "excel": b"x"}),
        ):
            permitted.add(name)
            resources.setdefault("snapshots", {})[name] = assets
            with pytest.raises(ValueError, match="C11"):
                call("reviewer", "endorse", endorsement, snap=name)
    resources["scopes"] = {scope: {"confirmation": proof, "slots": ["required"]}}
    resources["snapshots"] = {"snap": {"scope": scope, "members": {"required": member},
                                      "word": b"frozen word", "excel": b"frozen excel"}}
    pair = dict(snapshot="snap", records=[member], word_sha256=hashlib.sha256(b"frozen word").hexdigest(),
                excel_sha256=hashlib.sha256(b"frozen excel").hexdigest())
    release = dict(kind="decision", effect="release", reason="Reviewed", target=scope, pair=pair)
    with pytest.raises(ValueError, match="C12"):
        call("coordinator", "release", release, snap="snap", delegated=True)
    if review_action == "endorse":
        call("reviewer", review_action, endorsement, snap="snap")
    else:
        call("reviewer", review_action, dict(kind="finding", target=member, snapshot="snap", conclusion="passed"),
             snap="snap")
    call("coordinator", "deliver_draft", dict(release, effect="deliver_draft"), snap="snap")
    released = call("coordinator", "release", release, snap="snap", delegated=True)
    call("engineer", "sign_off", dict(kind="act", effect="sign_off", target=released, reason="Signed"),
         delegated=True)
    revoke = dict(kind="act", effect="retract", target=released, reason="Owner recalls this release")
    with pytest.raises(ValueError, match="C11"):
        call("coordinator", "retract", revoke)
    call("owner", "retract", revoke)
    grant = Grant(actors["owner"], "owner", "reader", "attempt", "plan", {"section"}, permitted, set(),
                  snapshot="snap", resources=resources)
    ctx = host.issue(grant, "confirm", str(uuid4()))
    assert assertions.status(ctx, released)["status"] == "retracted"
    assert assertions.report_view(ctx, "snap")["word_sha256"] == pair["word_sha256"]
