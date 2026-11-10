"""Named S3 actions. Only the host can supply an authenticated launch context."""
from datetime import datetime, timezone
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
    refs.update(p["source_version"] for p in (claim.get("page_binding") or {}).get("pages", ()))
    if pair := claim.get("pair"):
        refs.add(pair["snapshot"])
        refs.update(pair["records"])
    if refs - {None} - packet:
        raise ValueError("C4: a reference was outside the issued packet")


def _save(action, ctx, **request):
    with ctx.write() as (db, grant):
        return _save_locked(action, ctx, db, grant, **request)


def _save_locked(action, ctx, db, grant, *, subject, claim, grounds=(), id=None, judgment_details=None):
    if action != ctx.action:
        raise PermissionError("Native call belongs to a different action")
    request = dict(action=action, subject=subject, claim=claim, grounds=grounds, id=id)
    if judgment_details is not None:
        request["judgment_details"] = judgment_details
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
    if grant.role == "writer" and claim.kind == "source" and claim.state != "unknown" and not grounds:
        raise ValueError("C3: Writer extraction requires an applicable confirmed page binding")
    if claim.kind != spec["kind"]:
        raise ValueError("C1: action does not produce this kind")
    stamp = datetime.now(timezone.utc)
    schema_version = "s2-proposal-1"
    if claim.kind == "source":
        schema_version = "m1-source-time-1"
    elif claim.kind == "derived" and claim.assessment:
        schema_version = "m3-assessment-1"
    row = Assertion(id="pending", subject=subject, claim=claim, grounds=grounds,
                    was_attributed_to=grant.principal, was_generated_by=grant.task,
                    operation_id=ctx.operation_id, observed_at=None if claim.kind == "source" else stamp, recorded_at=stamp,
                    schema_version=schema_version,
                    check_version=CATALOG["version"])
    _check_packet(row, grant.packet)
    if receipt_id := getattr(claim, "submission_receipt", None):
        receipt = grant.resources.get("receipts", {}).get(receipt_id)
        if receipt is None or request_digest(receipt) != receipt_id:
            raise ValueError("C4: use the exact submission receipt bound to this assignment")
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
    if judgment_details is not None:
        store.store_judgment_details(db, saved["id"], judgment_details)
    return saved



def save_judgment(ctx, *, subject, claim, grounds=(), id=None, accompanying_question=None, judgment_details=None):
    request = dict(subject=subject, claim=claim, grounds=grounds, id=id)
    if judgment_details is not None:
        request["judgment_details"] = judgment_details
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
