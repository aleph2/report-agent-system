"""Named S3 actions. Only the host can supply an authenticated launch context."""
from datetime import date, datetime, timezone
import re
from functools import partial

from pydantic import TypeAdapter

from .authority import authority_projection
from .evidence import evidence_projection, normalize_judgment
from .ids import assertion_id, request_digest
from .queries import _dependencies, assertion_states
from .refusals import CATALOG, enforce
from .schema.kinds import Assertion, Claims, Ground, is_canonical_id

_CLAIM = TypeAdapter(Claims)
_GROUNDS = TypeAdapter(tuple[Ground, ...])


def _check_packet(row, packet):
    body = row.model_dump(mode="json")
    claim = body["claim"]
    refs = set(_dependencies(body))
    refs.update(claim.get("evidence_receipts", ()))
    refs.add(claim.get("submission_receipt"))
    refs.update(claim.get("disclosed_gaps", ()))
    refs.update(claim.get(k) for k in ("target", "successor", "snapshot"))
    refs.add((claim.get("citation") or {}).get("source_version"))
    if pair := claim.get("pair"):
        refs.add(pair["snapshot"])
        refs.update(pair["records"])
    if refs - {None} - packet:
        raise ValueError("C4: a reference was outside the issued packet")


def _observation_time(source, resources, proposed):
    citation = source.citation
    material = resources.get("sources", {}).get(citation.source_version, {}) if citation else {}
    pinned = (material.get("observation_times", {}).get(str(citation.page), {}).get(citation.quote)
              if citation else None)
    if proposed is not None:
        if not isinstance(proposed, str) or not citation:
            raise ValueError("C2: material observation time needs an exact source citation")
        matches = proposed == pinned if pinned is not None else proposed in citation.quote
        if not matches:
            raise ValueError("C2: observation time must match the quoted observation or its bound metadata")
    value = pinned if pinned is not None else proposed
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("C2: invalid material observation time")
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        return date.fromisoformat(value)
    moment = datetime.fromisoformat(value)
    if "T" not in value or moment.tzinfo is None:
        raise ValueError("C2: supply a calendar date or an observation timestamp with a time zone")
    return moment


def _save(action, ctx, **request):
    with ctx.write() as (db, grant):
        return _save_locked(action, ctx, db, grant, **request)


def _save_locked(action, ctx, db, grant, *, subject, claim, grounds=(), id=None, observed_at=None):
    if action != ctx.action:
        raise PermissionError("Native call belongs to a different action")
    request = dict(action=action, subject=subject, claim=claim, grounds=grounds, id=id)
    if observed_at is not None:
        if action != "assert_source":
            raise ValueError("Only a source assertion accepts a material observation time")
        request["observed_at"] = observed_at
    digest = request_digest(request)
    store = ctx._store
    previous = store.lookup(db, ctx.operation_id, ctx.binding, digest, can_read=True)
    if previous is not None:
        return previous
    if action not in grant.actions or subject not in grant.subjects or not is_canonical_id(subject):
        raise PermissionError("C11: action or subject outside assignment")
    spec = CATALOG["actions"][action]
    if grant.role not in spec["roles"] and not ("@agent" in spec["roles"] and grant.actor_class == "agent"):
        raise ValueError("C11: role cannot perform this action")
    claim = _CLAIM.validate_python(claim)
    grounds = _GROUNDS.validate_python(grounds)
    if claim.kind != spec["kind"]:
        raise ValueError("C1: action does not produce this kind")
    stamp = datetime.now(timezone.utc)
    row = Assertion(id="pending", subject=subject, claim=claim, grounds=grounds,
                    was_attributed_to=grant.principal, was_generated_by=grant.task,
                    operation_id=ctx.operation_id, observed_at=stamp, recorded_at=stamp,
                    schema_version="s2-proposal-1", check_version=CATALOG["version"])
    _check_packet(row, grant.packet)
    if receipt_id := getattr(claim, "submission_receipt", None):
        receipt = grant.resources.get("receipts", {}).get(receipt_id)
        if receipt is None or request_digest(receipt) != receipt_id:
            raise ValueError("C4: use the exact submission receipt bound to this assignment")
    if claim.kind == "source":
        row = row.model_copy(update={"observed_at": _observation_time(claim, grant.resources, observed_at),
                                     "schema_version": "m1-source-time-1"})
    states = assertion_states(db)
    authority = authority_projection(db, grant, action, row, states)
    evidence = evidence_projection(db, row, grant.resources, states)
    effective = normalize_judgment(row, evidence)
    identifier = assertion_id(subject, effective, grounds, grant.principal, grant.task, ctx.operation_id)
    if id is not None and id != identifier:
        raise ValueError("ASSERTION_ID_MISMATCH")
    row = row.model_copy(update={"id": identifier, "claim": effective})
    enforce(db, row, {**evidence, **authority})
    if action == "save_judgment":
        db.execute("INSERT INTO producers(plan,subject,actor) VALUES(?,?,?) ON CONFLICT DO NOTHING",
                   (grant.plan, subject, grant.principal))
        producer = db.execute("SELECT actor FROM producers WHERE plan=? AND subject=?",
                              (grant.plan, subject)).fetchone()[0]
        if producer != grant.principal:
            raise ValueError("C11: assessment already has a producer")
    saved = store.commit(db, row, action, grant.role, grant.snapshot, ctx.binding, digest)
    if receipt_id:
        store.store_submission(db, receipt_id, grant.resources["receipts"][receipt_id])
    return saved



def save_judgment(ctx, *, subject, claim, grounds=(), id=None, accompanying_question=None):
    request = dict(subject=subject, claim=claim, grounds=grounds, id=id)
    if accompanying_question is None:
        return _save("save_judgment", ctx, **request)

    ask_ctx, question = accompanying_question
    same_binding = ("actor", "role", "task", "plan", "snapshot")
    if (ask_ctx._store is not ctx._store or ask_ctx.binding["role"] != "writer"
            or any(ask_ctx.binding[k] != ctx.binding[k] for k in same_binding)):
        raise PermissionError("C11: accompanying question must belong to the same Writer assignment")
    with ask_ctx._authorized() as asker, ctx.write() as (db, writer):
        saved_question = _save_locked("ask", ask_ctx, db, asker, subject=subject, claim=question)
        if claim.get("question") != saved_question["id"]:
            raise ValueError("C4: judgment must reference the accompanying question")
        return _save_locked("save_judgment", ctx, db, writer, **request)


assert_source = partial(_save, "assert_source")
record_conflict = partial(_save, "record_conflict")
record_convention = partial(_save, "record_convention")
derive_result = partial(_save, "derive_result")
save_recommendation = partial(_save, "save_recommendation")
record_finding = partial(_save, "record_finding")
record_presentation_check = partial(_save, "record_presentation_check")
ask = partial(_save, "ask")
decide = partial(_save, "decide")
endorse = partial(_save, "endorse")
challenge = partial(_save, "challenge")
confirm = partial(_save, "confirm")
supersede = partial(_save, "supersede")
retract = partial(_save, "retract")
deliver_draft = partial(_save, "deliver_draft")
release = partial(_save, "release")
sign_off = partial(_save, "sign_off")
