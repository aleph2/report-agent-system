"""Build authority and release checks inside the action transaction."""
import hashlib
import json
from decimal import Decimal, InvalidOperation

from .queries import _confirmed_scope, _dependencies, _frozen
from .schema.kinds import Assertion


def _issued_authority(grant, action, subject, target):
    binding = {
        "actor": grant.principal, "action": action, "subject": subject, "target": target,
        "task": grant.task, "attempt": grant.attempt, "plan": grant.plan,
    }
    if action == "release":
        binding["snapshot"] = grant.snapshot
    for issued in grant.resources.get("authorities", ()):
        if issued.get("active") is True and all(issued.get(k) == v for k, v in binding.items()):
            return issued
    return {}


def _calculator_matches(grant, row):
    calculation = grant.resources.get("calculations", {}).get(row.subject, {})
    claim = row.claim
    if not calculation or claim.basis != "evidence" or claim.value is None:
        return False
    try:
        value = Decimal(str(calculation["value"]))
    except (KeyError, InvalidOperation):
        return False
    return (
        calculation.get("plan") == grant.plan
        and calculation.get("criterion") == claim.warrant.criterion
        and calculation.get("version") == claim.warrant.criterion_version
        and calculation.get("classification") == claim.classification and value == claim.value
        and set(calculation.get("inputs", ())) == {g.assertion_id for g in row.grounds}
    )


def _question_ids(root, bodies, states):
    """Include explicit linked questions and open subject questions at every input depth."""
    seen = set()
    pending = [root]
    subjects = set()
    found = set()
    while pending:
        key = pending.pop()
        if key in seen or key not in bodies:
            continue
        seen.add(key)
        body = bodies[key]
        subjects.add(body["subject"])
        if states[key]["open"]:
            found.add(key)
        pending.extend(_dependencies(body))
    for key, state in states.items():
        if state["open"] and state["subject"] in subjects:
            found.add(key)
    return found


def _deliver(grant, row, states, bodies):
    claim = row.claim
    pair = claim.pair
    result = {"required_list_owner_confirmed": False, "required_slots": [], "reviews": [], "snapshot": {}}
    if pair is None or grant.snapshot != pair.snapshot:
        return result, False
    visible = {key for key in grant.packet if key in states and states[key]["subject"] in grant.subjects}
    try:
        frozen = _frozen(grant, pair.snapshot, visible)
    except (PermissionError, ValueError):
        return result, False
    members = frozen["members"]
    scope_id = frozen.get("scope")
    if not scope_id or scope_id != claim.target or scope_id not in grant.packet:
        return result, False
    if not isinstance(frozen.get("word"), bytes) or not isinstance(frozen.get("excel"), bytes):
        return result, False
    word = hashlib.sha256(frozen["word"]).hexdigest()
    excel = hashlib.sha256(frozen["excel"]).hexdigest()
    exact_pair = (
        pair.word_sha256 == word and pair.excel_sha256 == excel and
        len(members) == len(set(members.values())) and set(pair.records) == set(members.values())
    )
    gaps = set()
    projected = []
    for slot, key in members.items():
        state = states[key]
        member_claim = bodies[key]["claim"]
        questions = _question_ids(key, bodies, states)
        gaps.update(questions)
        incomplete = member_claim.get("basis") in ("conditional", "gap")
        if incomplete:
            gaps.add(member_claim.get("question") or key)
        open_classifications = {q for q in questions if bodies[q]["claim"]["affects"] in ("classification", "value")}
        projected.append({
            "slot": slot, "id": key, "kind": state["kind"], "producer": state["author"],
            "status": state["status"], "stale": state["stale"],
            "open_grade_questions": len(open_classifications),
        })
    result["snapshot"] = {"id": pair.snapshot, "members": projected, "gaps": sorted(gaps),
                          "word_sha256": word, "excel_sha256": excel}
    result["scope_id"] = scope_id
    scope = grant.resources.get("scopes", {}).get(scope_id, {})
    result["required_slots"] = list(scope.get("slots", ()))
    result["required_list_owner_confirmed"] = _confirmed_scope(states, bodies, scope_id, scope)
    for key, state in states.items():
        if state["role"] != "reviewer" or state["action"] not in ("record_finding", "endorse"):
            continue
        review_claim = bodies[key]["claim"]
        bound = state["snapshot"]
        if not bound or review_claim.get("snapshot", bound) != bound:
            continue
        result["reviews"].append({
            "snapshot": bound, "record": review_claim["target"], "actor": state["author"],
            "role": state["role"], "action": state["action"], "stale": state["stale"],
            "passed": state["active"] and not state["challenged"] and
                      (state["action"] == "endorse" or review_claim.get("conclusion") == "passed"),
        })
    return result, exact_pair


def authority_projection(db, grant, action: str, row: Assertion, states: dict):
    """The trusted caller has already authenticated this grant and locked the store."""
    claim = row.claim
    target_id = getattr(claim, "target", None)
    target = states.get(target_id, {})
    same_subject = target.get("subject") == row.subject and row.subject in grant.subjects
    active = bool(same_subject and target_id in grant.packet and target.get("active"))
    actor_class = grant.actor_class
    person = actor_class == "person"
    owner = person and grant.role == "owner"
    issued = _issued_authority(grant, action, row.subject, target_id)
    conditions = set()
    result = {"role": grant.role, "actor_class": actor_class, "action": action,
              "packet": sorted(grant.packet), "target": target}

    bound_endorsement = action == "endorse" and grant.role == "reviewer" and grant.snapshot is not None
    if action in ("record_finding", "record_presentation_check") or bound_endorsement:
        frozen = grant.resources.get("snapshots", {}).get(grant.snapshot, {})
        if (not frozen or grant.snapshot not in grant.packet
                or getattr(claim, "snapshot", grant.snapshot) != grant.snapshot):
            raise ValueError("C11: use the snapshot bound to this review")
        if not all(isinstance(frozen.get(name), bytes) and frozen[name] for name in ("word", "excel")):
            raise ValueError("C11: freeze both files before recording review of this snapshot")
        if (action == "record_finding" or bound_endorsement) and (
            not active or target_id not in frozen.get("members", {}).values()
        ):
            raise ValueError("C11: review an eligible member of the bound snapshot")
        if claim.kind == "presentation_check":
            digests = {hashlib.sha256(frozen[k]).hexdigest() for k in ("word", "excel")
                       if isinstance(frozen.get(k), bytes)}
            if claim.artifact_digest not in digests:
                raise ValueError("C11: inspect a file from the bound snapshot")

    if action == "save_judgment" and claim.kind == "judgment":
        if grant.role == "writer":
            producer = db.execute("SELECT actor FROM producers WHERE plan=? AND subject=?",
                                  (grant.plan, row.subject)).fetchone()
            if producer is None or producer[0] == grant.principal:
                conditions.add("producer_binding")
            conditions.add("calculator_determined")
        elif grant.role == "calculator" and _calculator_matches(grant, row):
            conditions.update(("calculator_determined", "producer_binding"))

    if action in {"endorse", "challenge", "confirm", "supersede", "retract", "sign_off", "decide"}:
        if active and (action in ("retract", "supersede") or not target["stale"]):
            if target["kind"] != "act" or action == "retract" and target["effect"] != "retract":
                conditions.add("live_target")
        if action == "supersede":
            successor_id = getattr(claim, "successor", None)
            successor = states.get(successor_id, {})
            if (target_id == successor_id or successor_id not in grant.packet or not successor.get("active")
                    or successor.get("stale") or successor.get("subject") != row.subject
                    or successor.get("kind") != target.get("kind") or target.get("effect") == "release"):
                conditions.discard("live_target")
        if owner or target.get("author") == grant.principal:
            conditions.add("author_or_owner")
        if target.get("effect") == "challenge":
            if action == "retract" and target["author"] == grant.principal and grant.role == target["role"]:
                conditions.add("challenge_resolution")
        elif owner or not target.get("challenged"):
            conditions.add("challenge_resolution")
        if target.get("effect") != "release" or owner:
            conditions.add("release_owner")
        if person and (owner or issued):
            conditions.add("human_authority")
        if target.get("kind") != "convention" or owner:
            conditions.add("owner_for_conventions")
        if action == "decide" and active:
            effect = getattr(claim, "effect", "")
            if (effect == "answer" and target.get("open")) or (
                effect == "dismiss_challenge" and target.get("effect") == "challenge" and owner
            ):
                conditions.add("answer_or_dismiss")
            if owner or issued:
                conditions.add("decision_scope")
        if action == "sign_off" and active and not target["stale"] and not target["challenged"] and target.get("effect") == "release":
            conditions.add("live_release")
            name = issued.get("engineer_name")
            if person and grant.role == "engineer" and isinstance(name, str) and name.strip():
                result["engineer_name"] = name
                conditions.add("named_engineer")

    if action in ("deliver_draft", "release") and claim.kind == "decision":
        bodies = {key: json.loads(encoded) for key, encoded in db.execute("SELECT id,body FROM assertions")}
        delivery, pair_ok = _deliver(grant, row, states, bodies)
        result.update(delivery)
        if pair_ok:
            conditions.add("frozen_pair")
            if set(result["snapshot"]["gaps"]) <= set(claim.disclosed_gaps):
                conditions.add("draft_disclosures")
        if issued:
            result["delegation"] = {key: issued[key] for key in ("active", "action", "actor", "subject")}
            conditions.add("release_delegation")
    result["satisfied_authority_conditions"] = sorted(conditions)
    return result
