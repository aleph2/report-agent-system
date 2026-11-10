"""Task-side progress points to immutable Writer judgments and their completed business details."""
from typing import Any
from uuid import NAMESPACE_URL, uuid5
import json

from . import assertions, legacy_state as legacy
from .assertion_host import AssertionHost, Grant
from .errors import ActionForbidden, ActionRejected
from .store import digest, encode


def _has_table(db, name):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def submission_for(scope, indicator, operation, original, entry) -> dict[str, Any]:
    # Preserve the presentation and exact request needed for replay. The assertion owns the effective verdict.
    scored = entry.get("judgment", {})
    authority = dict(plan_ref=scope["plan"]["ref"], decision_ref=scope["decision"]["ref"],
                     method=scope["decision"]["payload"]["confirmed_rules"]["method"], rule_id=indicator)
    return dict(assignment=scope["assignment_digest"], indicator=indicator, operation=operation, criterion_authority=authority,
                original=original, input=entry["input"], rank=entry["rank"], read_locations=entry["read_locations"],
                citations=entry.get("sources", scored.get("sources", [])), evidence_receipts=entry.get("evidence_receipts", []),
                scoring={k:scored[k] for k in ("rank_reason","basis_kind","low","high") if k in scored},
                review={k:v for k,v in entry.items() if k in ("claim_checks","issue_id","binding","proposal_digest")})


def project(row, submission) -> dict[str, Any]:
    claim = row["claim"]
    kind = "gap" if claim["basis"] == "conditional" else claim["basis"]
    value = dict(submission["input"])
    if kind != value["kind"]:
        raise ActionRejected("WRITER_SUBMISSION_BASIS_MISMATCH")
    value["value"] = claim["value"]
    result = dict(kind=kind, rank=submission["rank"], input=value, read_locations=submission["read_locations"],
                  assertion_id=row["id"], claim=claim, grounds=row["grounds"], **submission["review"])
    if "criterion_authority" in submission:
        result["criterion_authority"] = submission["criterion_authority"]
    if submission.get("evidence_receipts"):
        result["evidence_receipts"] = submission["evidence_receipts"]
    if submission.get("ground_details"):
        result["ground_details"] = submission["ground_details"]
    if submission.get("disclosed_context"):
        result["disclosed_context"] = submission["disclosed_context"]
    if kind == "gap":
        result["sources"] = submission["citations"]
    else:
        result["judgment"] = dict(indicator_id=submission["indicator"], rank=submission["rank"],
                                  grade_id=claim["classification"], value=claim["value"],
                                  plausible_grades=claim["alternatives"], rationale=claim["warrant"]["rationale"],
                                  question=value["question"], sources=submission["citations"], **submission["scoring"])
    return result


def _saved(host, operation, expected_id, assignment):
    saved = host.recover_receipt(operation)
    if not saved or saved["result"]["id"] != expected_id or saved["result"]["claim"]["kind"] != "judgment":
        raise ActionRejected("WRITER_JUDGMENT_RECEIPT_MISMATCH")
    binding, row = saved["binding"], saved["result"]
    if row["was_attributed_to"] != binding["actor"] or row["was_generated_by"] != binding["task"]:
        raise ActionForbidden("WRITER_JUDGMENT_RECEIPT_SCOPE")
    item = host.commission.judgment_details(expected_id)
    if not item or item["assignment"] != assignment:
        raise ActionRejected("WRITER_SUBMISSION_RECEIPT_MISMATCH")
    return row, item


def read_progress(store, assignment, db=None) -> dict[str, Any]:
    """A trusted historical reader or already-bound Writer can project this allocation's rows."""
    if db is None:
        with store.connect() as conn:
            return read_progress(store, assignment, conn)
    historical = legacy.get_writer_indicator_steps(db, assignment)
    result: dict[str, Any] = historical or dict(rows={}, assessment_ref=None, interrupted_indicators={})
    result.setdefault("interrupted_indicators", {})
    if not _has_table(db, "writer_step_receipts"):
        return result
    host = None
    for indicator,operation,assertion_id,interruption,assessment in db.execute(
            "SELECT indicator,operation,assertion_id,interruption,assessment FROM writer_step_receipts "
            "WHERE assignment=? ORDER BY rowid", (assignment,)):
        if interruption is not None:
            result.setdefault("interrupted_indicators", {})[indicator] = json.loads(interruption)
        else:
            host = host or AssertionHost(store.root)
            row, item = _saved(host, operation, assertion_id, assignment)
            if item["indicator"] != indicator:
                raise ActionRejected("WRITER_JUDGMENT_INDICATOR_MISMATCH")
            result["rows"][indicator] = project(row, item)
        if assessment:
            result["assessment_ref"] = json.loads(assessment)
    return result


def _ensure(db):
    db.execute("""CREATE TABLE IF NOT EXISTS writer_step_receipts(
        assignment TEXT NOT NULL, indicator TEXT NOT NULL, operation TEXT UNIQUE NOT NULL,
        assertion_id TEXT UNIQUE, interruption TEXT, assessment TEXT, PRIMARY KEY(assignment,indicator),
        CHECK ((assertion_id IS NULL) != (interruption IS NULL)))""")


def native_saved_count(db, assignment):
    if not _has_table(db, "writer_step_receipts"):
        return 0
    return db.execute("SELECT count(assertion_id) FROM writer_step_receipts WHERE assignment=?",
                      (assignment,)).fetchone()[0]


def record_save(db, scope, indicator, row, assessment):
    _ensure(db)
    db.execute("INSERT INTO writer_step_receipts VALUES(?,?,?,?,NULL,?)",
               (scope["assignment_digest"], indicator, row["operation_id"], row["id"],
                encode(assessment) if assessment else None))


def record_interruption(db, scope, indicator, operation, refusals):
    _ensure(db)
    db.execute("INSERT INTO writer_step_receipts VALUES(?,?,?,NULL,?,NULL)",
               (scope["assignment_digest"], indicator, operation,
                encode(dict(status="interrupted: save rejected", refusals=refusals))))


def unfinished_interruptions(db, assignment):
    if not _has_table(db, "writer_step_receipts"):
        return []
    rows = db.execute("""SELECT s.operation, s.indicator, s.interruption, stage.response
        FROM writer_step_receipts s JOIN content_operations stage ON stage.operation_id=s.operation || ':record'
        LEFT JOIN content_operations done ON done.operation_id=s.operation
        WHERE s.assignment=? AND s.interruption IS NOT NULL AND done.operation_id IS NULL ORDER BY s.rowid""",
        (assignment,))
    return [(op, indicator, json.loads(stop)['refusals'], json.loads(stage)['result'])
            for op, indicator, stop, stage in rows]


def link_interrupted_assessment(db, assignment, operation, ref):
    db.execute("UPDATE writer_step_receipts SET assessment=? WHERE assignment=? AND operation=?",
               (encode(ref), assignment, operation))


def pending(cs, db, actor, scope):
    """Find an assertion committed just before the task-side receipt transaction was lost."""
    if not (cs.store.root / "assertions.sqlite3").is_file():
        return []
    host = AssertionHost(cs.store.root)
    principal = str(uuid5(NAMESPACE_URL, actor.id))
    subject = scope["object"]["object_id"]
    ids = host.commission.produced_ids(actor=principal, task=actor.task_id, subject=subject, kind="judgment")
    if _has_table(db, "writer_step_receipts"):
        ids = ids.difference(r[0] for r in db.execute(
            "SELECT assertion_id FROM writer_step_receipts WHERE assignment=?", (scope["assignment_digest"],)))
    if not ids:
        return []
    grant = Grant(principal, actor.role, actor.task_id, "recover/"+digest(sorted(ids)), digest(scope["plan"]["ref"]),
                  frozenset({subject}), ids, frozenset())
    ctx = host.issue_once(grant, "save_judgment", "inspect-committed")
    missing = []
    for item in assertions.packet(ctx):
        missing.append(_saved(host, item["operation_id"], item["id"], scope["assignment_digest"]))
    return missing


def commit(cs, db, actor, scope, rule, operation, original, entry):
    from .writer_judgment_authority import disclosed_context, ground_details, prepare_judgment
    submission = submission_for(scope, rule["id"], operation, original, entry)
    try:
        details = ground_details(cs, db, actor, scope, rule, original, entry)
        for detail in details:
            citation = detail["claim"].get("citation") or {}
            detail["delivery_receipts"] = [
                r["id"] for r in submission["evidence_receipts"]
                if r["source_version"] == citation.get("source_version") and r["page"] == citation.get("page")]
        if details:
            submission["ground_details"] = details
        disclosures = disclosed_context(cs, db, actor, scope, rule["id"], original)
        if disclosures:
            submission["disclosed_context"] = disclosures
        ctx, claim, grounds, accompanying_question = prepare_judgment(
            cs, db, actor, scope, rule, operation, entry, submission=submission)
        row = assertions.save_judgment(ctx, subject=scope["object"]["object_id"], claim=claim,
                                       grounds=grounds, accompanying_question=accompanying_question,
                                       judgment_details=submission)
    except (ValueError, PermissionError) as exc:
        raise ActionRejected("WRITER_JUDGMENT_REFUSED: " + str(exc)) from exc
    return row, project(row, submission)


def remember_page(db, handle, receipt):
    db.execute("CREATE TABLE IF NOT EXISTS writer_page_deliveries(handle TEXT PRIMARY KEY, receipt TEXT NOT NULL)")
    db.execute("INSERT INTO writer_page_deliveries VALUES(?,?) ON CONFLICT(handle) DO UPDATE SET receipt=excluded.receipt",
               (handle, encode(receipt)))


def page_receipt(db, handle):
    if _has_table(db, "writer_page_deliveries"):
        row = db.execute("SELECT receipt FROM writer_page_deliveries WHERE handle=?", (handle,)).fetchone()
        if row:
            return json.loads(row[0])
    return legacy.get_writer_page_read(db, handle)


def delivered_pages(db, assignment=None):
    if not _has_table(db, "writer_page_deliveries"):
        return []
    sql = "SELECT handle,receipt FROM writer_page_deliveries"
    if assignment is None:
        rows = db.execute(sql)
    else:
        rows = db.execute(sql + " WHERE receipt ->> '$.assignment_digest'=?", (assignment,))
    return [(handle,json.loads(raw)) for handle,raw in rows]
