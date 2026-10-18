"""Versioned feedback and scoped experience. Publication is an operator action.

The library may be shared by explicitly configured projects. Tenant and project
identity come from the host binding, never from model tool arguments.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

from .errors import ActionRejected
from .content_models import Ref
from .store import Store, encode, digest


@dataclass(frozen=True)
class LearningScope:
    customer: str
    project: str

    def __post_init__(self):
        if not self.customer.strip() or not self.project.strip():
            raise ValueError("LEARNING_SCOPE_REQUIRED")


class LearningLibrary:
    def __init__(self, root):
        self.store = Store(root)
        with self.store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS learning_feedback (
                    id TEXT PRIMARY KEY, customer TEXT, project TEXT, data TEXT);
                CREATE TABLE IF NOT EXISTS learning_versions (
                    id TEXT, version INTEGER, customer TEXT, project TEXT,
                    data TEXT, PRIMARY KEY(id, version));
                CREATE TABLE IF NOT EXISTS learning_release (
                    id TEXT PRIMARY KEY, version INTEGER);
                CREATE TABLE IF NOT EXISTS learning_audit (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    at TEXT DEFAULT CURRENT_TIMESTAMP, kind TEXT, data TEXT);
                CREATE TABLE IF NOT EXISTS learning_queue (
                    feedback_id TEXT PRIMARY KEY, customer TEXT, project TEXT,
                    status TEXT NOT NULL, claim_id TEXT, error_type TEXT);
            """)

    @staticmethod
    def _audit(db, kind, data):
        db.execute("INSERT INTO learning_audit(kind,data) VALUES (?,?)", (kind, encode(data)))

    def feedback(self, scope, snapshot, target, correction, before, evidence):
        if not correction.strip() or not evidence:
            raise ActionRejected("CORRECTION_AND_EVIDENCE_REQUIRED")
        payload = dict(customer=scope.customer, project=scope.project,
                    snapshot=snapshot, target=target, correction=correction,
                    before=before, evidence=evidence)
        data = dict(id=digest(payload), **payload)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT data FROM learning_feedback WHERE id=?", (data["id"],)).fetchone()
            if old:
                return json.loads(old[0])
            db.execute("INSERT INTO learning_feedback VALUES (?,?,?,?)",
                       (data["id"], scope.customer, scope.project, encode(data)))
            db.execute("INSERT INTO learning_queue VALUES (?,?,?,'queued',NULL,NULL)",
                       (data["id"], scope.customer, scope.project))
            self._audit(db, "feedback_received", {"id": data["id"]})
        return data

    def queue_status(self, scope):
        with self.store.connect() as db:
            rows = db.execute("SELECT feedback_id,status,claim_id,error_type FROM learning_queue WHERE customer=? AND project=? ORDER BY rowid",
                              (scope.customer, scope.project)).fetchall()
        return [dict(zip(("feedback_id", "status", "claim_id", "error_type"), row)) for row in rows]

    def claim_feedback(self, scope):
        """Host worker only, while holding the report project lock. No automatic retry."""
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            pending = db.execute("SELECT feedback_id FROM learning_queue WHERE customer=? AND project=? AND status='queued' ORDER BY rowid",
                                 (scope.customer, scope.project)).fetchall()
            if not pending:
                return None
            claim = {"id": str(uuid4()), "feedback_ids": [r[0] for r in pending]}
            db.execute("UPDATE learning_queue SET status='running',claim_id=? WHERE customer=? AND project=? AND status='queued'",
                       (claim["id"], scope.customer, scope.project))
            self._audit(db, "feedback_claimed", claim)
        return claim

    def finish_claim(self, scope, claim_id, error_type=None):
        with self.store.connect() as db:
            cursor = db.execute("UPDATE learning_queue SET status=?,error_type=? WHERE customer=? AND project=? AND claim_id=? AND status='running'",
                                ("failed" if error_type else "completed", error_type, scope.customer, scope.project, claim_id))
            if not cursor.rowcount:
                raise ActionRejected("LEARNING_CLAIM_NOT_RUNNING")
            self._audit(db, "feedback_claim_finished", {"claim_id": claim_id, "error_type": error_type})

    def retry_feedback(self, scope, feedback_id, reason):
        """Operator recovery; caller must hold the project lock to exclude live work."""
        if not reason.strip():
            raise ActionRejected("RETRY_REASON_REQUIRED")
        with self.store.connect() as db:
            cursor = db.execute("UPDATE learning_queue SET status='queued',claim_id=NULL,error_type=NULL WHERE feedback_id=? AND customer=? AND project=? AND status IN ('failed','running')",
                                (feedback_id, scope.customer, scope.project))
            if not cursor.rowcount:
                raise ActionRejected("FEEDBACK_NOT_RETRYABLE")
            self._audit(db, "operator_feedback_retry", {"feedback_id": feedback_id, "reason": reason})
        return {"feedback_id": feedback_id, "status": "queued"}

    def feedback_items(self, scope):
        with self.store.connect() as db:
            rows = db.execute("SELECT data FROM learning_feedback WHERE customer=? AND project=?",
                              (scope.customer, scope.project)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def propose(self, scope, feedback_ids, kind, title, strategy, conditions,
                verification, experience_id=None, expected_version=0):
        if kind not in {"project_fact", "customer_preference", "general_skill"}:
            raise ActionRejected("INVALID_EXPERIENCE_KIND")
        if not all(isinstance(x, str) and x.strip() for x in (title, strategy, conditions, verification)):
            raise ActionRejected("EXPERIENCE_DESCRIPTION_REQUIRED")
        available = {f["id"] for f in self.feedback_items(scope)}
        if not feedback_ids or not set(feedback_ids) <= available:
            raise ActionRejected("FEEDBACK_OUTSIDE_PROJECT")
        identifier = experience_id or str(uuid4())
        # General strategies stay within the originating customer in this release.
        # Cross-customer promotion requires a separate redaction/review capability.
        project = scope.project if kind == "project_fact" else ""
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            head = db.execute("SELECT version,customer,project,data FROM learning_versions WHERE id=? ORDER BY version DESC LIMIT 1",
                              (identifier,)).fetchone()
            if (head[0] if head else 0) != expected_version:
                raise ActionRejected("EXPERIENCE_VERSION_CONFLICT")
            if head and (head[1] != scope.customer or head[2] != project or json.loads(head[3])["kind"] != kind):
                raise ActionRejected("EXPERIENCE_SCOPE_IMMUTABLE")
            data = dict(id=identifier, version=expected_version + 1, customer=scope.customer,
                        project=project, kind=kind, title=title, strategy=strategy,
                        conditions=conditions, verification=verification, feedback_ids=feedback_ids)
            db.execute("INSERT INTO learning_versions VALUES (?,?,?,?,?)",
                       (identifier, data["version"], scope.customer, project, encode(data)))
            self._audit(db, "candidate_created", data)
        return data

    @staticmethod
    def _read(db, scope, identifier, version):
        row = db.execute("SELECT customer,project,data FROM learning_versions WHERE id=? AND version=?",
                         (identifier, version)).fetchone()
        if not row or row[0] != scope.customer or row[1] not in {"", scope.project}:
            raise ActionRejected("EXPERIENCE_NOT_AVAILABLE")
        return json.loads(row[2])

    def release(self, scope, identifier, version, reason):
        """Host/operator API, deliberately absent from agent tools. None disables."""
        if not reason.strip():
            raise ActionRejected("RELEASE_REASON_REQUIRED")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            head = db.execute("SELECT MAX(version) FROM learning_versions WHERE id=?", (identifier,)).fetchone()[0]
            self._read(db, scope, identifier, version if version is not None else head)
            previous = db.execute("SELECT version FROM learning_release WHERE id=?", (identifier,)).fetchone()
            db.execute("INSERT OR REPLACE INTO learning_release VALUES (?,?)", (identifier, version))
            result = dict(id=identifier, version=version, previous=previous[0] if previous else None, reason=reason)
            self._audit(db, "operator_release", result)
        return result

    def list_versions(self, scope):
        with self.store.connect() as db:
            rows = db.execute("""SELECT v.data,r.version FROM learning_versions v
                LEFT JOIN learning_release r ON r.id=v.id
                WHERE v.customer=? AND (v.project='' OR v.project=?) ORDER BY v.rowid""",
                              (scope.customer, scope.project)).fetchall()
        return [{**json.loads(data), "active": json.loads(data)["version"] == released} for data, released in rows]

    def search(self, scope, query="", *, match_mode="text"):
        active = [r for r in self.list_versions(scope) if r["active"]]
        if match_mode == "identifier":
            identifier = query.strip().casefold()
            if not identifier:
                raise ActionRejected("EXPERIENCE_IDENTIFIER_REQUIRED")
            return [r for r in active if r['id'].casefold() == identifier or
                    len(identifier) >= 8 and r['id'].casefold().startswith(identifier)][:20]
        if match_mode != "text":
            raise ActionRejected("INVALID_EXPERIENCE_MATCH_MODE")
        return [r for r in active if not query or query.casefold() in
                (r["title"] + r["strategy"] + r["conditions"]).casefold()][:20]

    def use(self, scope, identifier, version, target, reason, actor):
        if not reason.strip():
            raise ActionRejected("APPLICATION_REASON_REQUIRED")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            experience = self._read(db, scope, identifier, version)
            released = db.execute("SELECT version FROM learning_release WHERE id=?", (identifier,)).fetchone()
            if not released or released[0] != version:
                raise ActionRejected("EXPERIENCE_NOT_ACTIVE")
            self._audit(db, "application_declared", dict(customer=scope.customer, project=scope.project,
                        id=identifier, version=version, target=target, reason=reason, actor=actor))
        return {"experience": experience, "limitation": "Declared use is not evidence of correct application or quality improvement."}


def binding(workspace):
    """Configured by host code/operator only; disabled by default."""
    config = workspace.store.get("learning_config")
    if not config:
        return None
    from pathlib import Path
    root = Path(config["library_path"])
    if not root.is_absolute():
        raise ValueError("LEARNING_LIBRARY_ABSOLUTE_PATH_REQUIRED")
    return LearningLibrary(root), LearningScope(config["customer_id"], str(workspace.store.root))


def submit_feedback(workspace, snapshot_ref, target_ref, correction, evidence_refs):
    from .content_store import ContentStore
    from .content_models import refs_in
    bound = binding(workspace)
    if not bound:
        raise ActionRejected("LEARNING_NOT_CONFIGURED")
    contents = ContentStore(workspace.store)
    snapshot, target = contents.read(snapshot_ref), contents.read(target_ref)
    if snapshot_ref["type"] != "DocumentSnapshot":
        raise ActionRejected("FEEDBACK_SNAPSHOT_REQUIRED")
    if target_ref != snapshot_ref and target_ref not in [r.model_dump() for r in refs_in(snapshot["payload"])]:
        raise ActionRejected("FEEDBACK_TARGET_OUTSIDE_SNAPSHOT")
    evidence = [contents.read(ref)["ref"] for ref in evidence_refs]
    library, scope = bound
    return library.feedback(scope, snapshot_ref, target_ref, correction, target["payload"], evidence)


def guidance_context(workspace):
    """Expose released scoped preferences through application context, without
    choosing actions or treating learned project facts as source evidence.

    Candidate kind is chosen by the learner; release remains a host decision.
    Detailed optional methods remain available through the existing search tool.
    """
    bound = binding(workspace)
    if not bound:
        return None
    library, scope = bound
    active = [r for r in library.list_versions(scope) if r['active']]
    def fields(r):
        return {k:r[k] for k in ('id','version','kind','title','conditions','customer','project')}
    return {
        'customer_preferences': [{**fields(r), 'strategy':r['strategy']}
                                 for r in active if r['kind']=='customer_preference'],
        'available_experience': [fields(r) for r in active if r['kind']!='customer_preference'],
        'note': 'Exact released guidance for the bound customer/project. Determine applicability from its conditions and the current assignment. Newer direct user decisions prevail. Guidance does not grant permissions, change ownership, prove source facts or establish acceptance. Optional methods and learned project facts can be examined through search_experience; no fixed retrieval or execution sequence is required.'}


def report_tools(workspace, actor):
    if not workspace.store.get("learning_config"):
        return []

    def search_experience(query: str = "", match_mode: Literal["text", "identifier"] = "text") -> dict:
        """Find active scoped experience. Text mode is literal substring search; empty query
        browses up to 20. A textual mention of another ID is not that experience entry.
        Identifier mode matches the actual ID exactly, or its prefix of at least 8 characters.
        Inactive or out-of-scope candidates are not exposed. Check applicability against sources.
        """
        actor()
        library, scope = binding(workspace)
        items = library.search(scope, query, match_mode=match_mode)
        if match_mode == "identifier":
            hint = ("No active scoped identity matches. This does not establish that a historical "
                    "or inaccessible candidate does not exist." if not items else
                    "Only actual active scoped identities matched; decide applicability from the current task.")
        else:
            hint = ("No match for this wording; try a shorter term or an empty query to browse accessible active experience."
                    if query and not items else "Experience is not source truth; decide applicability from the current task.")
            hint += " Text matches can mention other IDs; identifier mode looks up the actual entry."
        return {"items": items, "match_mode": "identifier" if match_mode == "identifier" else "exact_substring",
                "match_details": [{"id": r['id'], "version": r['version'],
                    "matched_fields": ['id'] if match_mode == 'identifier' else
                        [k for k in ('title','strategy','conditions') if query and query.casefold() in r[k].casefold()]}
                    for r in items], "hint": hint}

    def record_experience_use(experience_id: str, version: int, target_ref: Ref, reason: str) -> dict:
        """Record which exact strategy version you applied to saved work; not a quality verdict."""
        from .content_store import ContentStore
        responsible = actor()
        target = ContentStore(workspace.store).read(target_ref)
        library, scope = binding(workspace)
        return library.use(scope, experience_id, version, target["ref"], reason, responsible.id)

    return [search_experience, record_experience_use]
