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
    refs.update(claim.get("disclosed_gaps", ()))
    refs.update(claim.get(k) for k in ("target", "successor", "snapshot"))
    refs.add((claim.get("citation") or {}).get("source_version"))
    if pair := claim.get("pair"):
        refs.add(pair["snapshot"])
        refs.update(pair["records"])
    if refs - {None} - packet:
        raise ValueError("C4: a reference was outside the issued packet")


def _save(action, ctx, *, subject, claim, grounds=(), id=None):
    if action != ctx.action:
        raise PermissionError("Native call belongs to a different action")
    digest = request_digest(dict(action=action, subject=subject, claim=claim, grounds=grounds, id=id))
    with ctx.write() as (db, grant):
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
        return store.commit(db, row, action, grant.role, grant.snapshot, ctx.binding, digest)


assert_source = partial(_save, "assert_source")
record_conflict = partial(_save, "record_conflict")
record_convention = partial(_save, "record_convention")
save_judgment = partial(_save, "save_judgment")
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
