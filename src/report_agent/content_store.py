"""Project-local immutable objects and append-only review/handling records."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from pydantic import ValidationError

from .content_models import PAYLOADS, SCHEMA_VERSION, Ref, ReviewSubmission, aggregate, refs_in
from .errors import ActionForbidden, ActionRejected
from .store import digest, encode


@dataclass(frozen=True)
class Actor:
    id: str
    role: str
    task_id: str


class ContentStore:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS content_versions (
                    type TEXT NOT NULL, id TEXT NOT NULL, version INTEGER NOT NULL,
                    data TEXT NOT NULL, PRIMARY KEY(type,id,version));
                CREATE TABLE IF NOT EXISTS content_heads (
                    type TEXT NOT NULL, id TEXT NOT NULL, version INTEGER NOT NULL,
                    PRIMARY KEY(type,id));
                CREATE TABLE IF NOT EXISTS content_operations (
                    operation_id TEXT PRIMARY KEY, actor_id TEXT NOT NULL,
                    request_digest TEXT NOT NULL, response TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS content_observations (
                    id TEXT PRIMARY KEY, actor_id TEXT NOT NULL, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS content_edges (
                    relation_id TEXT NOT NULL, version INTEGER NOT NULL,
                    subject_key TEXT NOT NULL, object_key TEXT NOT NULL,
                    PRIMARY KEY(relation_id,version));
                CREATE INDEX IF NOT EXISTS content_edges_subject ON content_edges(subject_key);
                CREATE INDEX IF NOT EXISTS content_edges_object ON content_edges(object_key);
            """)

    @staticmethod
    def _read(db, ref):
        ref = Ref.model_validate(ref)
        row = db.execute("SELECT data FROM content_versions WHERE type=? AND id=? AND version=?", ref.key()).fetchone()
        if row is None:
            raise ActionRejected("NOT_FOUND: " + encode(ref.model_dump()))
        return json.loads(row[0])

    def read(self, ref):
        with self.store.connect() as db:
            return self._read(db, ref)

    def list_objects(self, type=None):
        with self.store.connect() as db:
            rows = db.execute("SELECT data FROM content_versions" + (" WHERE type=?" if type else "") + " ORDER BY rowid", (type,) if type else ()).fetchall()
        return [json.loads(r[0]) for r in rows]

    def operation(self, actor, operation_id, request, execute):
        if not isinstance(operation_id, str) or not operation_id.strip():
            raise ActionRejected("OPERATION_ID_REQUIRED")
        request_digest = digest({"actor": actor.__dict__, "request": request})
        failure = None
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT actor_id,request_digest,response FROM content_operations WHERE operation_id=?", (operation_id,)).fetchone()
            if previous:
                if previous[0] != actor.id or previous[1] != request_digest:
                    raise ActionRejected("OPERATION_CONFLICT")
                cached = json.loads(previous[2])
                if not cached["ok"]:
                    error = ActionForbidden if cached["code"] == "FORBIDDEN" else ActionRejected
                    raise error(cached["message"])
                return cached
            db.execute("SAVEPOINT content_effect")
            try:
                result = execute(db)
            except (ValidationError, ActionRejected, ActionForbidden) as exc:
                db.execute("ROLLBACK TO content_effect")
                failure = ActionRejected("INVALID_CONTRACT: " + str(exc)) if isinstance(exc, ValidationError) else exc
                response = {"ok": False, "code": "FORBIDDEN" if isinstance(exc, ActionForbidden) else str(failure).split(":")[0],
                            "message": str(failure), "retryable": False, "receipt_id": operation_id}
            else:
                response = {"ok": True, "result": result, "receipt_id": operation_id}
            db.execute("RELEASE content_effect")
            db.execute("INSERT INTO content_operations VALUES (?,?,?,?)", (operation_id, actor.id, request_digest, encode(response)))
        if failure:
            raise failure
        return response

    def receipt(self, actor, operation_id):
        with self.store.connect() as db:
            row = db.execute("SELECT actor_id,request_digest,response FROM content_operations WHERE operation_id=?", (operation_id,)).fetchone()
        if row is None:
            return {"state": "unknown", "operation_id": operation_id}
        if row[0] != actor.id:
            raise ActionForbidden("FORBIDDEN: operation owner")
        response = json.loads(row[2])
        return {"state": "known_success" if response["ok"] else "known_failure", "request_digest": row[1], "response": response}

    def observe(self, actor, result):
        receipt = str(uuid4())
        with self.store.connect() as db:
            db.execute("INSERT INTO content_observations VALUES (?,?,?)", (receipt, actor.id, encode(result)))
        return {"ok": True, "result": result, "receipt_id": receipt}

    @staticmethod
    def _insert(db, actor, type, payload, *, id=None, version=1, previous_ref=None):
        ref = {"type": type, "id": id or str(uuid4()), "version": version}
        record = {"ref": ref, "schema_version": SCHEMA_VERSION, "previous_ref": previous_ref,
                  "owner_id": actor.id, "created_by": actor.id, "task_id": actor.task_id,
                  "created_at": datetime.now(timezone.utc).isoformat(),
                  "payload_digest": digest(payload), "payload": payload}
        db.execute("INSERT INTO content_versions VALUES (?,?,?,?)", (*Ref.model_validate(ref).key(), encode(record)))
        db.execute("INSERT INTO content_heads VALUES (?,?,?) ON CONFLICT(type,id) DO UPDATE SET version=excluded.version", tuple(ref.values()))
        if type == "Relation":
            db.execute("INSERT INTO content_edges VALUES (?,?,?,?)", (ref["id"], version, encode(payload["subject_ref"]), encode(payload["object_ref"])))
        return ref

    def import_inputs(self, actor, operation_id, source_ids):
        """Capture authorized existing source versions and the unmodified commissioning text."""
        sources = self.store.sources(source_ids)
        manifest = self.store.manifest
        def save(db):
            requirement = self._insert(db, actor, "Requirement", {
                "text": manifest["goal"], "scope": "project commission", "origin": "project manifest goal"})
            requirements = [requirement]
            scope = manifest.get("scope_instruction")
            scope_text = scope.get("text") if isinstance(scope, dict) else scope
            if scope_text:
                requirements.append(self._insert(db, actor, "Requirement", {
                    "text": scope_text, "scope": "user scope instruction", "origin": "project manifest scope_instruction"}))
            refs = []
            for s in sources:
                refs.append(self._insert(db, actor, "SourceArtifact", {
                    "source_id": s["id"], "file_digest": s.get("sha256") or digest(s["content"]), "coverage": s["coverage"],
                    "source_metadata": {**{k: v for k, v in s.items() if k != "content"}, "text_digest": digest(s["content"])}, "content": s["content"]}))
            return {"requirement_ref": requirement, "requirement_refs": requirements, "source_refs": refs}
        return self.operation(actor, operation_id, {"import_inputs": source_ids}, save)

    @staticmethod
    def source_payload(source):
        return {"source_id": source["id"], "file_digest": source.get("sha256") or digest(source["content"]),
                "coverage": source["coverage"], "source_metadata": {
                    **{k: v for k, v in source.items() if k != "content"}, "text_digest": digest(source["content"])},
                "content": source["content"]}

    def capture_sources(self, actor, operation_id, source_ids):
        """Capture authorized source versions without changing requirements or author objects."""
        sources = self.store.sources(source_ids)
        def save(db):
            return {"source_refs": [self._insert(db, actor, "SourceArtifact", self.source_payload(s))
                                    for s in sources]}
        return self.operation(actor, operation_id, {"capture_sources": source_ids}, save)

    def commit(self, actor, operation_id, objects):
        """Atomic batch; {'client_key': key} references are resolved only inside this batch."""
        def save(db):
            if not objects:
                raise ActionRejected("EMPTY_COMMIT")
            assigned, plans = {}, []
            for obj in objects:
                if set(obj) - {"client_key", "type", "payload", "previous_ref"}:
                    raise ActionRejected("INVALID_COMMIT_FIELDS")
                key, type = obj["client_key"], obj["type"]
                if not key or key in assigned or type not in {"Criterion", "ContentNode", "Evidence", "Relation"}:
                    raise ActionRejected("INVALID_OR_DUPLICATE_OBJECT")
                allowed = ({"Criterion", "ContentNode", "Evidence", "Relation"} if actor.role == "coordinator"
                           else {"ContentNode", "Evidence", "Relation"} if actor.role == "writer" else set())
                if type not in allowed:
                    raise ActionForbidden("FORBIDDEN: object type")
                previous = obj.get("previous_ref")
                if previous:
                    prior = self._read(db, previous)
                    if prior["owner_id"] != actor.id or prior["ref"]["type"] != type:
                        raise ActionForbidden("FORBIDDEN: object owner")
                    head = db.execute("SELECT version FROM content_heads WHERE type=? AND id=?", (type, prior["ref"]["id"])).fetchone()[0]
                    if head != previous["version"]:
                        raise ActionRejected("VERSION_CONFLICT")
                    ref = {**previous, "version": head + 1}
                else:
                    ref = {"type": type, "id": str(uuid4()), "version": 1}
                assigned[key] = ref
                plans.append((obj, ref))
            def resolve(value):
                if isinstance(value, dict):
                    if set(value) == {"client_key"}:
                        if value["client_key"] not in assigned:
                            raise ActionRejected("UNKNOWN_CLIENT_KEY")
                        return assigned[value["client_key"]]
                    return {k: resolve(v) for k, v in value.items()}
                return [resolve(v) for v in value] if isinstance(value, list) else value
            new_keys = {Ref.model_validate(r).key() for r in assigned.values()}
            for obj, ref in plans:
                payload = PAYLOADS[ref["type"]].model_validate(resolve(obj["payload"])).model_dump()
                for dependency in refs_in(payload):
                    if dependency.key() not in new_keys:
                        self._read(db, dependency.model_dump())
                if ref["type"] == "Criterion" and any(r["type"] != "Requirement" for r in payload["requirement_refs"]):
                    raise ActionRejected("CRITERIA_REQUIRE_INDEPENDENT_REQUIREMENTS")
                if ref["type"] == "ContentNode" and not (any(r["type"] == "Criterion" for r in assigned.values()) or
                        db.execute("SELECT 1 FROM content_versions WHERE type='Criterion' LIMIT 1").fetchone()):
                    raise ActionRejected("CRITERIA_REQUIRED_BEFORE_CONTENT")
                if ref["type"] == "Evidence" and any(r["type"] != "SourceArtifact" for r in payload["source_refs"]):
                    raise ActionRejected("EVIDENCE_REQUIRES_SOURCE_VERSIONS")
                self._insert(db, actor, ref["type"], payload, id=ref["id"], version=ref["version"], previous_ref=obj.get("previous_ref"))
            return {"refs": assigned}
        return self.operation(actor, operation_id, {"commit": objects}, save)

    def freeze(self, actor, operation_id, root_ref, refs):
        def save(db):
            if actor.role not in {"coordinator", "writer"}:
                raise ActionForbidden("FORBIDDEN: snapshot")
            root = self._read(db, root_ref)
            if root_ref["type"] != "ContentNode" or root["owner_id"] != actor.id:
                raise ActionForbidden("FORBIDDEN: root owner")
            by_key = {Ref.model_validate(r).key(): self._read(db, r) for r in refs}
            if len(by_key) != len(refs) or Ref.model_validate(root_ref).key() not in by_key:
                raise ActionRejected("INVALID_MANIFEST")
            logical = [(r[0], r[1]) for r in by_key]
            if len(logical) != len(set(logical)):
                raise ActionRejected("MIXED_LOGICAL_VERSIONS")
            allowed = {"Requirement", "Criterion", "SourceArtifact", "Evidence", "ContentNode", "Relation"}
            if any(r[0] not in allowed for r in by_key):
                raise ActionRejected("INVALID_SNAPSHOT_TYPE")
            for record in by_key.values():
                if any(ref.key() not in by_key for ref in refs_in(record["payload"])):
                    raise ActionRejected("INCOMPLETE_REFERENCE_CLOSURE")
            parents, edges, positions = {}, {}, set()
            for record in by_key.values():
                p = record["payload"]
                if record["ref"]["type"] == "Relation" and p["predicate"] == "contains":
                    subject, obj = Ref.model_validate(p["subject_ref"]).key(), Ref.model_validate(p["object_ref"]).key()
                    if obj in parents or (subject, p["position"]) in positions:
                        raise ActionRejected("MULTIPLE_PARENTS_OR_POSITIONS")
                    parents[obj] = subject
                    positions.add((subject, p["position"]))
                    edges.setdefault(subject, []).append(obj)
            root_key = Ref.model_validate(root_ref).key()
            if root_key in parents:
                raise ActionRejected("ROOT_HAS_PARENT")
            visited, active = set(), set()
            def visit(key):
                if key in active:
                    raise ActionRejected("CONTAINS_CYCLE")
                if key in visited:
                    return
                active.add(key)
                for child in edges.get(key, []):
                    visit(child)
                active.remove(key)
                visited.add(key)
            for key in by_key:
                if key[0] == "ContentNode":
                    visit(key)
            rendered = set()
            pending = [root_key]
            while pending:
                key = pending.pop()
                if key not in rendered:
                    rendered.add(key)
                    pending.extend(edges.get(key, []))
            for key, record in by_key.items():
                if key[0] == "ContentNode" and record["payload"]["kind"] != "claim" and key not in rendered:
                    raise ActionRejected("DETACHED_PRESENTATION_NODE")
            criteria = [r for r in refs if r["type"] == "Criterion"]
            if not criteria:
                raise ActionRejected("SNAPSHOT_REQUIRES_CRITERIA")
            ordered = sorted(refs, key=lambda r: Ref.model_validate(r).key())
            payload = {"root_ref": root_ref, "refs": ordered, "criteria_refs": criteria, "manifest_digest": digest(ordered)}
            if self.store.manifest.get("coverage_contract"):
                from .review_coverage import CONTRACT
                if self.store.manifest["coverage_contract"] != CONTRACT:
                    raise ActionRejected("UNKNOWN_COVERAGE_CONTRACT")
                payload["coverage_contract"] = CONTRACT
            return {"snapshot_ref": self._insert(db, actor, "DocumentSnapshot", payload), "manifest_digest": payload["manifest_digest"]}
        return self.operation(actor, operation_id, {"freeze": {"root_ref": root_ref, "refs": refs}}, save)

    def read_context(self, actor, target_ref, offset=0, limit=20):
        if offset < 0 or limit < 1 or limit > 100:
            raise ActionRejected("INVALID_PAGE")
        record = self.read(target_ref)
        refs = record["payload"]["refs"] if target_ref["type"] == "DocumentSnapshot" else [target_ref]
        items = [self.read(r) for r in refs[offset:offset + limit]]
        return self.observe(actor, {"target_ref": target_ref, "objects": items, "loaded_refs": refs[offset:offset + limit],
            "total": len(refs), "next_offset": offset + limit if offset + limit < len(refs) else None,
            "unreturned_refs": refs[:offset] + refs[offset + limit:]})

    def submit_review(self, actor, operation_id, submission, runtime_identity, delivery_export_ref=None):
        def save(db):
            if actor.role not in {"reviewer", "rubric_grader"}:
                raise ActionForbidden("FORBIDDEN: review writer")
            data = ReviewSubmission.model_validate(submission).model_dump()
            if delivery_export_ref is not None:
                if actor.role != "reviewer":
                    raise ActionForbidden("FORBIDDEN: final submission belongs to delegated reviewer")
                export = self._read(db, delivery_export_ref)
                if (export["ref"]["type"] != "ExportArtifact" or
                        export["payload"]["snapshot_ref"] != data["snapshot_ref"] or
                        data["target_ref"] != data["snapshot_ref"] or data["scope"] != "delivery"):
                    raise ActionRejected("FINAL_REVIEW_TARGET_MISMATCH: use snapshot target, delivery scope and its exact export")
                if delivery_export_ref not in data["dependency_refs"]:
                    data["dependency_refs"].append(delivery_export_ref)
            snap = self._read(db, data["snapshot_ref"])
            if snap["ref"]["type"] != "DocumentSnapshot":
                raise ActionRejected("SNAPSHOT_REQUIRED")
            members = {Ref.model_validate(r).key() for r in [snap["ref"], *snap["payload"]["refs"]]}
            # Reviewed targets/criteria stay in the author's manifest. Independent
            # source dependencies belong to the project, not necessarily that manifest.
            external_sources = {Ref.model_validate(r).key() for r in data["dependency_refs"] if r["type"] == "SourceArtifact"}
            targets = [("target_ref", data["target_ref"])] + [
                (f"criteria_refs[{i}]", r) for i, r in enumerate(data["criteria_refs"])] + [
                (f"items[{i}].{field}", item[field]) for i, item in enumerate(data["items"])
                for field in ("target_ref", "criterion_ref")]
            for path, ref in targets:
                if Ref.model_validate(ref).key() not in members:
                    raise ActionRejected("REVIEW_TARGET_OUTSIDE_SNAPSHOT: " + encode({
                        "field": path, "received": ref, "snapshot_ref": snap["ref"],
                        "hint": "Use a snapshot member as target; ExportArtifact/RenderArtifact belong in artifact_refs."}))
            for ref in refs_in(data):
                record = self._read(db, ref.model_dump())
                if ref.key() not in members:
                    if ref.key() in external_sources:
                        # SourceArtifact records can only be captured by server code
                        # from this project's authorized catalog, never model payloads.
                        continue
                    if ref.type not in {"ExportArtifact", "RenderArtifact"} or record["payload"].get("snapshot_ref") != snap["ref"]:
                        raise ActionRejected("REVIEW_VERSION_OUTSIDE_SNAPSHOT")
            if any(r not in snap["payload"]["criteria_refs"] for r in data["criteria_refs"]):
                raise ActionRejected("CRITERION_OUTSIDE_SNAPSHOT")
            for item in data["items"]:
                if item["criterion_ref"] not in data["criteria_refs"]:
                    raise ActionRejected("UNDECLARED_CRITERION")
                usable_observations = 0
                for observation in item["observations"]:
                    # Receipt existence is deterministic; support remains the reviewer's judgment.
                    row = db.execute("SELECT actor_id,data FROM content_observations WHERE id=?", (observation["receipt_id"],)).fetchone()
                    if not row or row[0] != actor.id:
                        raise ActionRejected("OBSERVATION_RECEIPT_NOT_FROM_THIS_REVIEWER")
                    observed = json.loads(row[1])
                    if observed.get("status") != "failed" and observed.get("execution_state") != "blocked":
                        usable_observations += 1
                if item["verdict"] is not None and not usable_observations:
                    raise ActionRejected("FAILED_READS_DO_NOT_ESTABLISH_OBSERVATIONS")
            item_keys = [(encode(i["target_ref"]), encode(i["criterion_ref"]), i["scope"]) for i in data["items"]]
            if len(item_keys) != len(set(item_keys)):
                raise ActionRejected("DUPLICATE_REVIEW_OBLIGATION")
            kinds = [c["kind"] for c in data["delivery_checks"]]
            if len(kinds) != len(set(kinds)):
                raise ActionRejected("DUPLICATE_DELIVERY_CHECK")
            for check in data["delivery_checks"]:
                matched = False
                for observation in check["observations"]:
                    row = db.execute("SELECT actor_id,data FROM content_observations WHERE id=?", (observation["receipt_id"],)).fetchone()
                    if not row or row[0] != actor.id:
                        raise ActionRejected("OBSERVATION_RECEIPT_NOT_FROM_THIS_REVIEWER")
                    actual = json.loads(row[1])
                    if check["kind"] == "export":
                        matched |= actual.get("export_ref") in check["artifact_refs"] and "structure" in actual
                    else:
                        source = actual.get("source", {})
                        matched |= (actual.get("status") == "observed" and bool(actual.get("observation"))
                                    and source.get("render_ref") in check["artifact_refs"] and isinstance(source.get("page"), int))
                if check["verdict"] is not None and not matched:
                    raise ActionRejected("DELIVERY_CHECK_REQUIRES_MATCHING_ACTUAL_OBSERVATION")
            data.update(task_ref=actor.task_id, runtime_identity=runtime_identity)
            from .review_coverage import validate_accounting
            validate_accounting(snap, data)
            review_ref = self._insert(db, actor, "ReviewRecord", data)
            if delivery_export_ref is not None:
                final = {"target": {"snapshot_ref": data["snapshot_ref"], "export_ref": delivery_export_ref},
                         "review_ref": review_ref, "runtime_identity": runtime_identity,
                         "entrypoint": "delegated-reviewer-v1"}
                db.execute("INSERT OR REPLACE INTO state VALUES ('content_final_review', ?)", (encode(final),))
            return {"review_ref": review_ref}
        request = {"submit_review": submission, "runtime_identity": runtime_identity}
        if delivery_export_ref is not None:
            request["delivery_export_ref"] = delivery_export_ref
        return self.operation(actor, operation_id, request, save)

    def handoff(self, actor, operation_id, target_ref, problem, evidence, impact, *, handling_state="open", previous_ref=None, details=None):
        def save(db):
            self._read(db, target_ref)
            if not problem.strip() or not impact.strip() or handling_state not in {"open", "in_progress", "handled"}:
                raise ActionRejected("INVALID_HANDOFF")
            if previous_ref:
                previous = self._read(db, previous_ref)
                if previous_ref["type"] != "HandlingRecord" or previous["payload"]["target_ref"] != target_ref:
                    raise ActionRejected("INVALID_HANDLING_PREDECESSOR")
            return {"handling_ref": self._insert(db, actor, "HandlingRecord", {
                "target_ref": target_ref, "problem": problem, "evidence": evidence, "impact": impact,
                "handling_state": handling_state, "previous_handling_ref": previous_ref, **(details or {})})}
        return self.operation(actor, operation_id, {"handoff": {"target_ref": target_ref, "problem": problem,
            "evidence": evidence, "impact": impact, "handling_state": handling_state, "previous_ref": previous_ref, "details": details}}, save)

    def feedback(self, actor, offset=0, limit=20):
        if offset < 0 or not 1 <= limit <= 100:
            raise ActionRejected("INVALID_PAGE")
        records = [r for r in self.list_objects() if r["ref"]["type"] in {"ReviewRecord", "HandlingRecord", "ReviewReuse"}]
        return self.observe(actor, {"records": records[offset:offset + limit], "total": len(records),
            "next_offset": offset + limit if offset + limit < len(records) else None})

    def impact(self, old_snapshot, new_snapshot):
        old, new = self.read(old_snapshot)["payload"], self.read(new_snapshot)["payload"]
        old_keys = {Ref.model_validate(r).key() for r in old["refs"]}
        new_keys = {Ref.model_validate(r).key() for r in new["refs"]}
        changed = old_keys ^ new_keys
        affected = set(changed)
        edges = []
        for key in old_keys | new_keys:
            if key[0] == "Relation":
                p = self.read(dict(zip(("type", "id", "version"), key)))["payload"]
                if p["provenance_kind"] != "observed_only":
                    s, o = Ref.model_validate(p["subject_ref"]).key(), Ref.model_validate(p["object_ref"]).key()
                    edges.append((o, s))
                    if key in changed:
                        affected.add(s)
        while True:
            expanded = affected | {s for o, s in edges if o in affected}
            if expanded == affected:
                break
            affected = expanded
        return {"changed_refs": [dict(zip(("type", "id", "version"), k)) for k in sorted(changed)],
                "candidate_affected_refs": [dict(zip(("type", "id", "version"), k)) for k in sorted(affected)],
                "limitation": "Candidate dependency impact only. Agents decide semantic recheck scope and newly relevant evidence."}

    def item_applies(self, item, snapshot_ref, export_ref=None):
        if item.get("assessment_kind", "content") == "content":
            return True
        exports = []
        for ref in item["artifact_refs"]:
            record = self.read(ref)
            if record["payload"].get("snapshot_ref") != snapshot_ref:
                return False
            exports.append(record["payload"]["export_ref"] if ref["type"] == "RenderArtifact" else ref)
        return bool(exports) and all(r == export_ref for r in exports)

    def review_summary(self, snapshot_ref, required, export_ref=None):
        self.read(snapshot_ref)
        items, delivery_violations, needs_recheck = [], [], []
        superseded = {encode(r["payload"]["review_ref"]) for r in self.list_objects("ReviewSupersession")}
        def current_items(review):
            changed = self.changed_review_sources(review["payload"])
            if changed:
                needs_recheck.append({"review_ref": review["ref"], "changed_source_refs": changed})
            # Changes remove positive applicability, not historical findings.
            return [i for i in review["payload"]["items"]
                    if (not changed or i["verdict"] == "not_satisfied")
                    and self.item_applies(i, snapshot_ref, export_ref)]
        for review in self.list_objects("ReviewRecord"):
            if review["payload"]["snapshot_ref"] != snapshot_ref or encode(review["ref"]) in superseded:
                continue
            items.extend(current_items(review))
            delivery_violations.extend(c for c in review["payload"].get("delivery_checks", [])
                if c["verdict"] == "not_satisfied" and self.item_applies(
                    {**c, "assessment_kind": c["kind"]}, snapshot_ref, export_ref))
        for reuse in self.list_objects("ReviewReuse"):
            if reuse["payload"]["snapshot_ref"] == snapshot_ref and encode(reuse["payload"]["review_ref"]) not in superseded:
                items.extend(current_items(self.read(reuse["payload"]["review_ref"])))
        summary = aggregate(items, required)
        # Confirmed local violations of the same adopted criterion remain material
        # to delivery. Local passes never manufacture parent coverage.
        criteria = {encode(r["criterion_ref"]) for r in required}
        defects = [i for i in items if i["verdict"] == "not_satisfied" and encode(i["criterion_ref"]) in criteria]
        if defects:
            summary["overall_verdict"] = "not_satisfied"
        summary["confirmed_violations"] = defects
        summary["delivery_violations"] = delivery_violations
        summary["needs_recheck"] = needs_recheck
        return summary

    def supersede_review(self, actor, operation_id, review_ref, replacement_ref, reason):
        """A reviewer can correct their own finding, keeping the original evidence."""
        def save(db):
            old, new = self._read(db, review_ref), self._read(db, replacement_ref)
            if actor.role not in {"reviewer", "rubric_grader"} or old["owner_id"] != actor.id or new["owner_id"] != actor.id:
                raise ActionForbidden("FORBIDDEN: review owner")
            if (review_ref["type"] != "ReviewRecord" or replacement_ref["type"] != "ReviewRecord"
                    or old["payload"]["snapshot_ref"] != new["payload"]["snapshot_ref"]
                    or review_ref == replacement_ref or not reason.strip()):
                raise ActionRejected("INVALID_REVIEW_SUPERSESSION")
            def keys(record):
                return {(encode(i["target_ref"]), encode(i["criterion_ref"]), i["scope"]) for i in record["payload"]["items"]}
            if not keys(old) <= keys(new) or not all(i["observations"] for i in new["payload"]["items"]):
                raise ActionRejected("CORRECTED_REVIEW_REQUIRES_COVERAGE_AND_OBSERVATIONS")
            def checks_by_key(record):
                return {(c["kind"], tuple(sorted(encode(r) for r in c["artifact_refs"]))): c
                        for c in record["payload"].get("delivery_checks", [])}
            old_checks, new_checks = checks_by_key(old), checks_by_key(new)
            if not old_checks.keys() <= new_checks.keys() or any(
                    (c["verdict"] is not None or c["observations"]) and not new_checks[key]["observations"]
                    for key, c in old_checks.items()):
                raise ActionRejected("CORRECTED_REVIEW_REQUIRES_DELIVERY_COVERAGE")
            return {"supersession_ref": self._insert(db, actor, "ReviewSupersession", {
                "review_ref": review_ref, "replacement_ref": replacement_ref, "reason": reason})}
        return self.operation(actor, operation_id, {"supersede_review": [review_ref, replacement_ref, reason]}, save)

    def confirm_reuse(self, actor, operation_id, review_ref, new_snapshot, reason):
        """Explicit reviewer confirmation, never a latest-version automatic pass."""
        current_sources = {s["id"]: s for s in self.store.sources([s["id"] for s in self.store.source_catalog()])}
        def save(db):
            if actor.role not in {"reviewer", "rubric_grader"}:
                raise ActionForbidden("FORBIDDEN: review applicability")
            old = self._read(db, review_ref)
            new = self._read(db, new_snapshot)
            if review_ref["type"] != "ReviewRecord" or new_snapshot["type"] != "DocumentSnapshot" or not reason.strip():
                raise ActionRejected("REVIEW_REUSE_REQUIRES_REASON_AND_SNAPSHOT")
            payload = old["payload"]
            keys = {Ref.model_validate(r).key() for r in new["payload"]["refs"]}
            required = [payload["target_ref"], *payload["criteria_refs"], *payload["dependency_refs"],
                        *[i["target_ref"] for i in payload["items"]]]
            independent = [r for r in payload["dependency_refs"] if r["type"] == "SourceArtifact" and Ref.model_validate(r).key() not in keys]
            for ref in independent:
                source = self._read(db, ref)["payload"]
                current = current_sources.get(source["source_id"])
                if not current or not current.get("current", True) or source != self.source_payload(current):
                    raise ActionRejected("CHANGED_REVIEW_SOURCE_REQUIRES_RECHECK")
            if any(Ref.model_validate(r).key() not in keys and r not in independent for r in required):
                raise ActionRejected("CHANGED_REVIEW_INPUT_REQUIRES_RECHECK")
            for item in [*payload["items"], *payload.get("delivery_checks", [])]:
                for ref in item.get("artifact_refs", []):
                    if self._read(db, ref)["payload"].get("snapshot_ref") != new_snapshot:
                        raise ActionRejected("CHANGED_ARTIFACT_REQUIRES_RECHECK")
            # A whole-snapshot judgment cannot be reused as another whole-snapshot judgment.
            # Unchanged local targets still require semantic confirmation of relevance.
            return {"reuse_ref": self._insert(db, actor, "ReviewReuse", {"review_ref": review_ref,
                "snapshot_ref": new_snapshot, "reason": reason, "applicability_to_snapshot": "current"})}
        return self.operation(actor, operation_id, {"reuse": [review_ref, new_snapshot, reason]}, save)

    def changed_review_sources(self, payload):
        members = self.read(payload["snapshot_ref"])["payload"]["refs"]
        changed = []
        for ref in payload["dependency_refs"]:
            if ref["type"] != "SourceArtifact" or ref in members:
                continue
            source = self.read(ref)["payload"]
            current = self.store.sources([source["source_id"]])[0]
            if not current.get("current", True) or source != self.source_payload(current):
                changed.append(ref)
        return changed
