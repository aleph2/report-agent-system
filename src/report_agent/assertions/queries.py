"""Read-only projections of committed assertions for a host-issued packet."""
import hashlib
import json
from collections import defaultdict, deque
from sqlite3 import Connection

from .ids import request_digest


_ENDED = {"retracted", "superseded"}
_STATUS = (
    ("retract", "retracted"), ("supersede", "superseded"),
    ("challenge", "contested"), ("confirm", "confirmed"), ("endorse", "endorsed"),
)


def _dependencies(body):
    """Provenance edges, excluding decisions and acts referencing their targets."""
    for ground in body["grounds"]:
        yield ground["assertion_id"]
        if ground.get("transfer_convention"):
            yield ground["transfer_convention"]
    claim = body["claim"]
    kind = claim["kind"]
    if kind == "judgment":
        warrant = claim.get("warrant", {})
        if warrant.get("criterion"):
            yield warrant["criterion"]
        yield from (claim.get("adjustment") or {}).get("ground_ids", ())
        if claim.get("question"):
            yield claim["question"]
    elif kind == "finding":
        yield claim["target"]
    elif kind == "conflict":
        yield from claim["observations"]
        if claim.get("precedence_convention"):
            yield claim["precedence_convention"]
    elif kind == "derived":
        yield from claim["inputs"]
        if claim.get("rule_version"):
            yield claim["rule_version"]
    elif kind == "recommendation":
        yield from claim["basis"]


def _descendants(children, origins):
    visited = set()
    pending = deque(origins)
    while pending:
        for child in children.get(pending.popleft(), ()):
            if child not in visited:
                visited.add(child)
                pending.append(child)
    return visited


class _Projection:
    def __init__(self, db: Connection):
        self.bodies = {}
        self.states = {}
        self.children = defaultdict(set)
        for key, encoded, action, role, snapshot in db.execute(
            "SELECT id,body,action,role,snapshot FROM assertions ORDER BY id"
        ):
            body = json.loads(encoded)
            claim = body["claim"]
            self.bodies[key] = body
            self.states[key] = {
                "status": "proposed", "stale": False, "author": body["was_attributed_to"],
                "kind": claim["kind"], "subject": body["subject"], "effect": claim.get("effect"),
                "action": action, "role": role, "snapshot": snapshot,
            }
            for source in _dependencies(body):
                self.children[source].add(key)
        self._resolve()

    def _resolve(self):
        # A retraction of another act is terminal. Only the original action layer
        # decides who may write; projection does not reinterpret historical grants.
        withdrawn = set()
        for body in self.bodies.values():
            claim = body["claim"]
            if claim["kind"] == "act" and claim["effect"] == "retract":
                target = self.states.get(claim["target"])
                if target and target["effect"] != "retract":
                    withdrawn.add(claim["target"])

        effects = defaultdict(set)
        challenges = defaultdict(set)
        dismissed = set()
        decisions = []
        for key, body in self.bodies.items():
            if key in withdrawn:
                continue
            claim = body["claim"]
            if claim["kind"] == "decision":
                decisions.append((key, claim))
            if claim["kind"] != "act":
                continue
            target = claim["target"]
            effect = claim["effect"]
            if self.states.get(target, {}).get("kind") == "act":
                continue
            if effect == "challenge":
                challenges[target].add(key)
            else:
                effects[target].add(effect)
        ended = withdrawn | {key for key, acts in effects.items() if "supersede" in acts}
        for key in _descendants(self.children, ended):
            self.states[key]["stale"] = True
        answered = set()
        for key, decision in decisions:
            if key in ended or self.states[key]["stale"]:
                continue
            if decision["effect"] == "dismiss_challenge":
                dismissed.add(decision["target"])
            elif decision["effect"] == "answer":
                answered.add(decision["target"])
        for key, state in self.states.items():
            current = effects[key]
            if key in withdrawn:
                current.add("retract")
            if challenges[key] - dismissed:
                current.add("challenge")
            state["status"] = next((name for act, name in _STATUS if act in current), "proposed")
            state["active"] = state["status"] not in _ENDED and key not in dismissed
            state["challenged"] = state["status"] == "contested"
            state["open"] = state["kind"] == "question" and state["active"] and key not in answered


def assertion_states(db: Connection) -> dict:
    """Internal, transaction-local facts. Callers must already own the connection."""
    return _Projection(db).states


def _visible(projection, grant):
    return {
        key for key, state in projection.states.items()
        if key in grant.packet and state["subject"] in grant.subjects
    }


def _require(key, permitted):
    if key not in permitted:
        raise PermissionError("The issued packet does not permit this read")


def _readable_body(body, permitted):
    """Show authorized content and provenance without expanding its reference IDs."""
    result = dict(body)
    result["grounds"] = [
        {k: v for k, v in ground.items() if k != "transfer_convention" or v in permitted}
        for ground in body["grounds"] if ground["assertion_id"] in permitted
    ]
    claim = dict(body["claim"])
    for field in ("target", "successor", "precedence_convention", "question", "rule_version", "snapshot"):
        if claim.get(field) and claim[field] not in permitted:
            claim.pop(field)
    for field in ("observations", "inputs", "disclosed_gaps", "evidence_receipts"):
        if field in claim:
            claim[field] = [key for key in claim[field] if key in permitted]
    if claim["kind"] == "recommendation":
        claim["basis"] = [key for key in claim["basis"] if key in permitted]
    if claim.get("citation") and claim["citation"]["source_version"] not in permitted:
        claim.pop("citation")
    if claim.get("warrant") and claim["warrant"]["criterion"] not in permitted:
        claim.pop("warrant")
    if claim.get("adjustment"):
        adjustment = dict(claim["adjustment"])
        adjustment["ground_ids"] = [key for key in adjustment.get("ground_ids", ()) if key in permitted]
        claim["adjustment"] = adjustment
    if claim.get("pair"):
        pair = claim["pair"]
        if pair["snapshot"] not in permitted or not set(pair["records"]) <= permitted:
            claim.pop("pair")
    result["claim"] = claim
    return result


def _read_set(projection, grant):
    # A grant can name external resources as well as assertion IDs. An assertion
    # from another subject stays hidden even if its ID appears in the packet.
    return grant.packet.difference(projection.states) | _visible(projection, grant)


def status(ctx, assertion_id):
    with ctx.read() as (db, grant):
        projection = _Projection(db)
        _require(assertion_id, _visible(projection, grant))
        state = projection.states[assertion_id]
        return {"status": state["status"], "stale": state["stale"]}


def packet(ctx, *, confirmed_only=False):
    with ctx.read() as (db, grant):
        projection = _Projection(db)
        visible = _visible(projection, grant)
        permitted = _read_set(projection, grant)
        if confirmed_only:
            visible = {key for key in visible if projection.states[key]["status"] == "confirmed"
                       and not projection.states[key]["stale"]}
        return tuple(_readable_body(projection.bodies[key], permitted) for key in sorted(visible))


def stale_derivations(ctx, assertion_id):
    with ctx.read() as (db, grant):
        projection = _Projection(db)
        visible = _visible(projection, grant)
        _require(assertion_id, visible)
        state = projection.states[assertion_id]
        if state["status"] not in _ENDED and not state["stale"]:
            return ()
        return tuple(sorted(visible & _descendants(projection.children, (assertion_id,))))


def open_questions(ctx):
    with ctx.read() as (db, grant):
        projection = _Projection(db)
        permitted = _read_set(projection, grant)
        return tuple(
            _readable_body(projection.bodies[key], permitted)
            for key in sorted(_visible(projection, grant)) if projection.states[key]["open"]
        )


def _confirmed_scope(states, bodies, scope_id, scope):
    slots = scope.get("slots")
    if not isinstance(slots, (tuple, list)) or not slots:
        return False
    if not all(isinstance(s, str) and s.strip() == s and s for s in slots) or len(set(slots)) != len(slots):
        return False
    state = states.get(scope_id, {})
    confirmation = scope.get("confirmation")
    proof = states.get(confirmation, {})
    if (state.get("status") != "confirmed" or state["stale"] or proof.get("role") != "owner"
            or proof.get("action") != "confirm" or not proof.get("active") or proof["stale"]):
        return False
    if bodies[confirmation]["claim"]["target"] != scope_id:
        return False
    claim = bodies[scope_id]["claim"]
    digest = request_digest(slots)
    if claim["kind"] == "convention":
        return claim.get("rule") == digest
    return claim["kind"] == "source" and claim.get("state") == "value" and claim.get("value") == digest


def _frozen(grant, snapshot_id, visible):
    _require(snapshot_id, grant.packet)
    if grant.snapshot is not None and snapshot_id != grant.snapshot:
        raise PermissionError("Snapshot is outside the issued binding")
    snapshot = grant.resources.get("snapshots", {}).get(snapshot_id)
    if not snapshot or not snapshot.get("members"):
        raise ValueError("Frozen snapshot is unavailable or has no members")
    if not set(snapshot["members"].values()) <= visible:
        raise PermissionError("The packet does not cover the complete frozen snapshot")
    return snapshot


def report_view(ctx, snapshot_id, *, subject=None):
    """Return exactly the frozen members and file digests, stable across later acts."""
    with ctx.read() as (db, grant):
        projection = _Projection(db)
        snapshot = _frozen(grant, snapshot_id, _visible(projection, grant))
        members = dict(snapshot["members"])
        if subject is not None:
            _require(subject, grant.subjects)
            members = {slot: key for slot, key in members.items() if projection.states[key]["subject"] == subject}
        permitted = _read_set(projection, grant)
        return {
            "snapshot": snapshot_id, "members": members,
            "records": tuple(_readable_body(projection.bodies[key], permitted) for key in members.values()),
            "word_sha256": hashlib.sha256(snapshot["word"]).hexdigest(),
            "excel_sha256": hashlib.sha256(snapshot["excel"]).hexdigest(),
        }


def followups(ctx):
    """Work visible to this packet. Reviews are scoped to its snapshot when bound."""
    with ctx.read() as (db, grant):
        projection = _Projection(db)
        visible = _visible(projection, grant)
        reviewed = set()
        for key, state in projection.states.items():
            if state["role"] != "reviewer" or not state["active"] or state["stale"] or state["challenged"]:
                continue
            if state["action"] not in {"record_finding", "endorse"}:
                continue
            claim = projection.bodies[key]["claim"]
            if grant.snapshot is not None and (claim.get("snapshot") or state["snapshot"]) != grant.snapshot:
                continue
            target = claim["target"]
            if target in visible and state["author"] != projection.states[target]["author"]:
                reviewed.add(target)
        groups = {"unreviewed": [], "stale": [], "open_questions": [], "flagged": []}
        for key in sorted(visible):
            state = projection.states[key]
            claim = projection.bodies[key]["claim"]
            if not state["active"]:
                continue
            if state["stale"]:
                groups["stale"].append(key)
            if state["open"]:
                groups["open_questions"].append(key)
            if state["kind"] == "judgment" and key not in reviewed:
                groups["unreviewed"].append(key)
            if state["challenged"] or claim.get("review_flags") or claim.get("basis") in ("assumption", "gap", "conditional"):
                groups["flagged"].append(key)
        groups["missing_slots"] = []
        if grant.snapshot is not None:
            snapshot = _frozen(grant, grant.snapshot, visible)
            scope_id = snapshot.get("scope")
            if scope_id in grant.packet:
                scope = grant.resources.get("scopes", {}).get(scope_id, {})
                if _confirmed_scope(projection.states, projection.bodies, scope_id, scope):
                    groups["missing_slots"] = sorted(set(scope["slots"]) - snapshot["members"].keys())
        return groups
