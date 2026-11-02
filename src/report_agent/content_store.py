"""Project-local immutable objects and append-only review/handling records."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from pydantic import ValidationError

from .content_models import PAYLOADS, SCHEMA_VERSION, Ref, ReviewSubmission, aggregate, refs_in
from .errors import ActionForbidden, ActionRejected, LocalStorageBusy, external_outcome_pending
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

    def operation(self, actor, operation_id, request, execute, *, binding_identity=None):
        if not isinstance(operation_id, str) or not operation_id.strip():
            raise ActionRejected("OPERATION_ID_REQUIRED")
        request_digest = digest({"actor": actor.__dict__, "request": request})
        failure = None
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT actor_id,request_digest,response FROM content_operations WHERE operation_id=?", (operation_id,)).fetchone()
            if previous:
                if previous[0] != actor.id:
                    raise ActionRejected("OPERATION_CONFLICT")
                cached = json.loads(previous[2])
                if cached['ok'] and binding_identity is not None:
                    request_digest = digest({'actor': actor.__dict__, 'request': request,
                                             'binding': binding_identity(db, cached['result'])})
                if previous[1] != request_digest:
                    raise ActionRejected("OPERATION_CONFLICT")
                if not cached["ok"]:
                    error = ActionForbidden if cached["code"] == "FORBIDDEN" else ActionRejected
                    if error is ActionRejected and cached.get("diagnostic") is not None:
                        raise error(cached["message"], diagnostic=cached["diagnostic"])
                    raise error(cached["message"])
                return cached
            db.execute("SAVEPOINT content_effect")
            try:
                result = execute(db)
                if binding_identity is not None:
                    request_digest = digest({'actor': actor.__dict__, 'request': request,
                                             'binding': binding_identity(db, result)})
            except LocalStorageBusy:
                raise
            except (ValidationError, ActionRejected, ActionForbidden) as exc:
                db.execute("ROLLBACK TO content_effect")
                failure = ActionRejected("INVALID_CONTRACT: " + str(exc)) if isinstance(exc, ValidationError) else exc
                response = {"ok": False, "code": "FORBIDDEN" if isinstance(exc, ActionForbidden) else str(failure).split(":")[0],
                            "message": str(failure), "retryable": False, "receipt_id": operation_id}
                if isinstance(failure, ActionRejected) and failure.diagnostic is not None:
                    response["diagnostic"] = failure.diagnostic
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
        state = ('outcome_unresolved' if response.get('code')=='OPERATION_OUTCOME_UNRESOLVED'
                 else 'known_success' if response['ok'] else 'known_failure')
        return {"state": state, "request_digest": row[1], "response": response}

    def detached_operation(self, actor, operation_id, request, prepare, execute, finalize):
        """Reserve an external operation, release SQLite during work, then commit.

        The original operation ID owns its reservation. Cancellation/crash leaves
        an explicit unresolved receipt; neither this nor ordinary operation() can
        silently run it again. No worker loop or external retry is introduced.
        """
        if not isinstance(operation_id,str) or not operation_id.strip():
            raise ActionRejected('OPERATION_ID_REQUIRED')
        request_digest = digest({'actor':actor.__dict__,'request':request})
        pending = {'ok':False,'code':'OPERATION_OUTCOME_UNRESOLVED',
            'message':'OPERATION_OUTCOME_UNRESOLVED: external work reserved; inspect its original outcome before another action',
            'retryable':False,'receipt_id':operation_id}
        def failure_response(exc):
            error = ActionRejected('INVALID_CONTRACT: '+str(exc)) if isinstance(exc,ValidationError) else exc
            return error, {'ok':False,'code':'FORBIDDEN' if isinstance(exc,ActionForbidden) else str(error).split(':')[0],
                'message':str(error),'retryable':False,'receipt_id':operation_id}
        failure = None
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT actor_id,request_digest,response FROM content_operations WHERE operation_id=?',
                             (operation_id,)).fetchone()
            if row:
                if row[:2] != (actor.id,request_digest):
                    raise ActionRejected('OPERATION_CONFLICT')
                saved = json.loads(row[2])
                if saved['ok']:
                    return saved
                error = ActionForbidden if saved['code']=='FORBIDDEN' else ActionRejected
                raise error(saved['message'])
            try:
                prepared = prepare(db)
            except LocalStorageBusy:
                raise
            except (ValidationError,ActionRejected,ActionForbidden) as exc:
                failure,pending = failure_response(exc)
            db.execute('INSERT INTO content_operations VALUES (?,?,?,?)',
                       (operation_id,actor.id,request_digest,encode(pending)))
        if failure:
            raise failure
        try:
            with external_outcome_pending(operation_id):
                computed = execute(prepared)  # No SQLite transaction is held here.
        except LocalStorageBusy:
            raise
        except (ValidationError,ActionRejected,ActionForbidden) as exc:
            failure,response = failure_response(exc)
        with external_outcome_pending(operation_id), self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT actor_id,request_digest,response FROM content_operations WHERE operation_id=?',
                             (operation_id,)).fetchone()
            if row != (actor.id,request_digest,encode(pending)):
                raise ActionRejected('OPERATION_RESERVATION_CHANGED')
            db.execute('SAVEPOINT external_effect')
            if failure is None:
                try:
                    result = finalize(db,prepared,computed)
                except LocalStorageBusy:
                    raise
                except (ValidationError,ActionRejected,ActionForbidden) as exc:
                    db.execute('ROLLBACK TO external_effect')
                    failure,response = failure_response(exc)
                else:
                    response = {'ok':True,'result':result,'receipt_id':operation_id}
            db.execute('RELEASE external_effect')
            db.execute('UPDATE content_operations SET response=? WHERE operation_id=?',
                       (encode(response),operation_id))
        if failure:
            raise failure
        return response

    def observe(self, actor, result):
        receipt = str(uuid4())
        with self.store.connect() as db:
            db.execute("INSERT INTO content_observations VALUES (?,?,?)", (receipt, actor.id, encode(result)))
            if actor.role == 'reviewer':
                from .review_handles import assign_evidence_handle
                assign_evidence_handle(db, actor.id, receipt)
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

    def commit(self, actor, operation_id, objects, *, deliverable_selection=None):
        """Atomic batch; {'client_key': key} references are resolved only inside this batch."""
        if hasattr(deliverable_selection, 'model_dump'):
            deliverable_selection = deliverable_selection.model_dump()
        def save(db):
            if not objects and deliverable_selection is None:
                raise ActionRejected("EMPTY_COMMIT")
            if any(obj.get('type') == 'ContentNode' for obj in objects):
                from .commission_plan import assert_writing_allowed
                assert_writing_allowed(self, db, actor)
            assigned, plans, exception_uses = {}, [], []
            configured = db.execute("SELECT value FROM state WHERE key='content_revision_limit'").fetchone()
            revision_limit = json.loads(configured[0]) if configured else None
            if revision_limit is not None and (revision_limit.__class__ is not int or revision_limit < 0):
                raise ActionRejected("INVALID_CONTENT_REVISION_LIMIT")
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
                    if type == "ContentNode" and revision_limit is not None and head - 1 >= revision_limit:
                        from .revision_authorization import exact_exception
                        grant = exact_exception(db, actor, prior, obj['payload'])
                        if grant is None:
                            raise ActionRejected("CONTENT_REVISION_LIMIT_REACHED")
                        exception_uses.append((grant, {**previous, "version": head + 1}))
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
                if ref["type"] == "Evidence" and any(r["type"] != "SourceArtifact" for r in payload["source_refs"]):
                    raise ActionRejected("EVIDENCE_REQUIRES_SOURCE_VERSIONS")
                self._insert(db, actor, ref["type"], payload, id=ref["id"], version=ref["version"], previous_ref=obj.get("previous_ref"))
            from .revision_authorization import record_use
            for grant, resulting_ref in exception_uses:
                record_use(db, grant, resulting_ref, operation_id)
            result = {"refs": assigned}
            if deliverable_selection is not None:
                from .deliverables import declare
                result['deliverable'] = declare(self, db, actor, operation_id, deliverable_selection, assigned)
                if not objects:
                    result['selection_only'] = True
            return result
        request = {"commit": objects}
        if deliverable_selection is not None:
            request['deliverable_selection'] = deliverable_selection
        return self.operation(actor, operation_id, request, save)

    def _freeze_in_transaction(self, db, actor, root_ref, refs, workbook_refs):
        if actor.role not in {"coordinator", "writer"}:
            raise ActionForbidden("FORBIDDEN: snapshot")
        root = self._read(db, root_ref)
        # Coordinator can assemble a delivery snapshot of saved producer work;
        # this grants no content-write or producer ownership transfer.
        if root_ref["type"] != "ContentNode" or (root["owner_id"] != actor.id and actor.role != "coordinator"):
            raise ActionForbidden("FORBIDDEN: root owner")
        payload = self._snapshot_payload(db, root_ref, refs, workbook_refs)
        return {"snapshot_ref": self._insert(db, actor, "DocumentSnapshot", payload), "manifest_digest": payload["manifest_digest"]}

    def _snapshot_payload(self, db, root_ref, refs, workbook_refs):
        """Shared structural checks only; callers retain their separate authority checks."""
        from .commission_plan import snapshot_inventory
        refs, commission_plan_ref = snapshot_inventory(self, db, refs)
        by_key = {Ref.model_validate(r).key(): self._read(db, r) for r in refs}
        if len(by_key) != len(refs) or Ref.model_validate(root_ref).key() not in by_key:
            raise ActionRejected("INVALID_MANIFEST")
        logical = [(r[0], r[1]) for r in by_key]
        if len(logical) != len(set(logical)):
            raise ActionRejected("MIXED_LOGICAL_VERSIONS")
        allowed = {"Requirement", "Criterion", "SourceArtifact", "Evidence", "ContentNode", "Relation"}
        if any(r[0] not in allowed for r in by_key):
            raise ActionRejected("INVALID_SNAPSHOT_TYPE")
        missing_refs, referrers = {}, []
        for record in by_key.values():
            missing = {ref.key(): ref.model_dump() for ref in refs_in(record["payload"]) if ref.key() not in by_key}
            if missing:
                missing_refs.update(missing)
                referrers.append({'ref': record['ref'], 'missing_refs': list(missing.values())})
        if missing_refs:
            raise ActionRejected("INCOMPLETE_REFERENCE_CLOSURE", diagnostic={
                'reason': 'referenced_objects_missing_from_manifest', 'parameter_path': ['refs'],
                'missing_refs': list(missing_refs.values()), 'referrers': referrers})
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
        workbook_keys = [Ref.model_validate(r).key() for r in workbook_refs]
        if len(workbook_keys) != len(set(workbook_keys)):
            raise ActionRejected("DUPLICATE_WORKBOOK_CHANNEL_REF")
        for key in workbook_keys:
            if key not in by_key or key[0] != "ContentNode":
                raise ActionRejected("WORKBOOK_CHANNEL_OUTSIDE_MANIFEST")
            if by_key[key]['payload']['kind'] not in {'table','block'}:
                raise ActionRejected("WORKBOOK_CHANNEL_REQUIRES_TABLE_OR_TEXT_BLOCK")
            if key in rendered:
                raise ActionRejected("WORKBOOK_ONLY_NODE_IN_REPORT")
            if key in parents or key in edges:
                raise ActionRejected("WORKBOOK_CHANNEL_NODE_HAS_CONTAINMENT")
        for key, record in by_key.items():
            if key[0] == "ContentNode" and record["payload"]["kind"] != "claim" and key not in rendered and key not in workbook_keys:
                raise ActionRejected("DETACHED_PRESENTATION_NODE")
        criteria = [r for r in refs if r["type"] == "Criterion"]
        ordered = sorted(refs, key=lambda r: Ref.model_validate(r).key())
        payload = {"root_ref": root_ref, "refs": ordered, "criteria_refs": criteria, "manifest_digest": digest(ordered)}
        if workbook_refs:
            payload['workbook_refs'] = sorted(workbook_refs,key=lambda r:Ref.model_validate(r).key())
            payload['manifest_digest'] = digest({'refs':ordered,'workbook_refs':payload['workbook_refs']})
        if self.store.manifest.get("coverage_contract"):
            from .review_coverage import CONTRACT
            if self.store.manifest["coverage_contract"] != CONTRACT:
                raise ActionRejected("UNKNOWN_COVERAGE_CONTRACT")
            payload["coverage_contract"] = CONTRACT
        if commission_plan_ref:
            from .commission_plan import snapshot_outcomes
            payload['commission_plan_ref'] = commission_plan_ref
            payload['commission_outcome_refs'] = snapshot_outcomes(self, db, commission_plan_ref, ordered)
            payload['manifest_digest'] = digest({'content_digest': payload['manifest_digest'],
                'commission_plan_ref': commission_plan_ref, 'commission_outcome_refs': payload['commission_outcome_refs']})
        return payload

    def _saved_reference_set(self, db, actor, receipt_id):
        """Project saved object identities, never another actor's private receipt."""
        row = db.execute('SELECT actor_id,response FROM content_operations WHERE operation_id=?',
                         (receipt_id,)).fetchone()
        if row is None:
            raise ActionRejected('SAVED_REFERENCE_RECEIPT_NOT_FOUND')
        owner, raw = row
        task_id = None
        if owner != actor.id:
            prefix = 'content:writer:'
            if actor.role != 'coordinator' or not owner.startswith(prefix):
                raise ActionForbidden('FORBIDDEN: saved reference scope')
            task_id = owner[len(prefix):]
            task = self._read(db, {'type':'DelegatedTask', 'id':task_id, 'version':1})
            if (task['owner_id'] != actor.id or task['payload'].get('delegated_by') != actor.id
                    or task['payload'].get('role') != 'writer'):
                raise ActionForbidden('FORBIDDEN: saved reference scope')
        response = json.loads(raw)
        saved = response.get('result')
        assigned = saved.get('refs') if isinstance(saved, dict) else None
        if response.get('ok') is not True or not isinstance(assigned, dict) or not assigned:
            raise ActionRejected('SAVED_REFERENCE_RECEIPT_UNSUPPORTED')
        result = {}
        for name, value in assigned.items():
            ref = Ref.model_validate(value).model_dump()
            record = self._read(db, ref)
            if (ref['type'] not in {'Criterion','ContentNode','Evidence','Relation'}
                    or record['owner_id'] != owner or record['created_by'] != owner
                    or (task_id is not None and record['task_id'] != task_id)):
                raise ActionForbidden('FORBIDDEN: saved reference origin')
            result[name] = ref
        return result

    def saved_reference_summary(self, actor, producer_task_ref):
        """Parent-scoped navigation facts; saved versions are not task acceptance."""
        from collections import Counter
        task_ref = Ref.model_validate(producer_task_ref).model_dump()
        with self.store.connect() as db:
            task = self._read(db, task_ref)
            if (task_ref['type'] != 'DelegatedTask' or actor.role != 'coordinator'
                    or task['owner_id'] != actor.id or task['payload'].get('delegated_by') != actor.id
                    or task['payload'].get('role') != 'writer'):
                raise ActionForbidden('FORBIDDEN: saved reference scope')
            owner = 'content:writer:' + task_ref['id']
            rows = db.execute('SELECT operation_id,response FROM content_operations WHERE actor_id=? ORDER BY rowid',
                              (owner,)).fetchall()
            receipts = []
            for receipt_id, raw in rows:
                response = json.loads(raw)
                saved = response.get('result')
                refs = saved.get('refs') if isinstance(saved, dict) else None
                if response.get('ok') is not True or not isinstance(refs, dict) or not refs:
                    continue
                refs = self._saved_reference_set(db, actor, receipt_id)
                receipts.append({'receipt_id':receipt_id, 'refs_digest':digest(refs),
                    'counts':dict(Counter(r['type'] for r in refs.values())),
                    'content_nodes':[{'ref':r, 'kind':self._read(db,r)['payload']['kind']}
                                     for r in refs.values() if r['type']=='ContentNode']})
            from .deliverables import V4, directory
            from .prompt_sources import review_interface_profile
            declared = (directory(self, db, actor, task_ref)
                        if review_interface_profile(self.store) == V4 else None)
        return {'origin':'program_saved_reference_metadata', 'producer_task_ref':task_ref,
                'receipts':receipts, 'semantic_acceptance':False,
                **({'declared_deliverables': declared} if declared is not None else {})}

    def declared_deliverables(self, actor):
        from .deliverables import directory
        with self.store.connect() as db:
            return directory(self, db, actor, full=True)

    def freeze(self, actor, operation_id, root_ref, refs, workbook_refs=None, saved_receipt_ids=None):
        workbook_refs = workbook_refs or []
        if saved_receipt_ids is not None and (not isinstance(saved_receipt_ids, list)
                or any(not isinstance(v,str) or not v.strip() for v in saved_receipt_ids)):
            raise ActionRejected('INVALID_SAVED_REFERENCE_RECEIPTS')
        def save(db):
            selected = refs
            if saved_receipt_ids:
                selected = {Ref.model_validate(r).key():r for r in refs}
                for receipt_id in saved_receipt_ids:
                    for ref in self._saved_reference_set(db, actor, receipt_id).values():
                        selected[Ref.model_validate(ref).key()] = ref
                pending = list(selected)
                while pending:
                    record = self._read(db, selected[pending.pop()])
                    for ref in refs_in(record['payload']):
                        if ref.key() not in selected:
                            selected[ref.key()] = ref.model_dump()
                            pending.append(ref.key())
                selected = list(selected.values())
            return self._freeze_in_transaction(db, actor, root_ref, selected, workbook_refs)
        request = {"freeze": {"root_ref": root_ref, "refs": refs}}
        if workbook_refs:
            request['freeze']['workbook_refs'] = workbook_refs
        if saved_receipt_ids:
            request['freeze']['saved_receipt_ids'] = saved_receipt_ids
        return self.operation(actor, operation_id, request, save)

    def derive_snapshot(self, actor, operation_id, base_snapshot_ref, additional_refs,
                        replacements=None, workbook_refs=None):
        """Assemble explicit version deltas; use the original freeze invariants."""
        from .content_models import SnapshotReplacement
        base_ref = Ref.model_validate(base_snapshot_ref).model_dump()
        if base_ref['type'] != 'DocumentSnapshot':
            raise ActionRejected('BASE_REQUIRES_DOCUMENT_SNAPSHOT')
        base = self.read(base_ref)
        base_digest = base['payload']['manifest_digest']
        additions = [Ref.model_validate(r).model_dump() for r in additional_refs]
        changes = [SnapshotReplacement.model_validate(r).model_dump() for r in (replacements or [])]
        channel = (None if workbook_refs is None else
                   [Ref.model_validate(r).model_dump() for r in workbook_refs])
        request = {'derive_snapshot': {'base_snapshot_ref': base_ref,
            'base_manifest_digest': base_digest, 'additional_refs': additions,
            'replacements': changes, 'workbook_refs': channel}}

        def save(db):
            # Re-read the exact immutable base inside the operation transaction.
            original = self._read(db, base_ref)['payload']
            if original['manifest_digest'] != base_digest:
                raise ActionRejected('BASE_SNAPSHOT_CHANGED')
            members = {Ref.model_validate(r).key(): r for r in original['refs']}
            mapped = {}
            for change in changes:
                previous = Ref.model_validate(change['previous_ref']).key()
                if previous not in members:
                    raise ActionRejected('SNAPSHOT_REPLACEMENT_OUTSIDE_BASE')
                if previous in mapped:
                    raise ActionRejected('DUPLICATE_SNAPSHOT_REPLACEMENT')
                mapped[previous] = change['new_ref']
            refs = [mapped.get(key, value) for key, value in members.items()]
            keys = {Ref.model_validate(r).key() for r in refs}
            for ref in additions:
                key = Ref.model_validate(ref).key()
                if key in keys:
                    raise ActionRejected('DUPLICATE_SNAPSHOT_ADDITION')
                keys.add(key)
                refs.append(ref)
            root = mapped.get(Ref.model_validate(original['root_ref']).key(), original['root_ref'])
            selected_channel = channel
            if selected_channel is None:
                selected_channel = [mapped.get(Ref.model_validate(r).key(), r)
                                    for r in original.get('workbook_refs', [])]
            result = self._freeze_in_transaction(db, actor, root, refs, selected_channel)
            lineage = {**request['derive_snapshot'], 'snapshot_ref': result['snapshot_ref'],
                       'manifest_digest': result['manifest_digest']}
            # Same transaction as snapshot and operation receipt, not a second operation.
            db.execute('INSERT INTO events(kind,data) VALUES (?,?)',
                       ('snapshot_derived', encode({'actor_id': actor.id, 'task_id': actor.task_id,
                           'operation_id': operation_id, **lineage})))
            return {**result, 'derivation': lineage}
        return self.operation(actor, operation_id, request, save)

    def read_context(self, actor, target_ref, offset=0, limit=20):
        if offset < 0 or limit < 1 or limit > 100:
            raise ActionRejected("INVALID_PAGE")
        record = self.read(target_ref)
        refs = record["payload"]["refs"] if target_ref["type"] == "DocumentSnapshot" else [target_ref]
        items = [self.read(r) for r in refs[offset:offset + limit]]
        return self.observe(actor, {"target_ref": target_ref, "objects": items, "loaded_refs": refs[offset:offset + limit],
            "total": len(refs), "next_offset": offset + limit if offset + limit < len(refs) else None,
            "unreturned_refs": refs[:offset] + refs[offset + limit:]})

    def submit_review(self, actor, operation_id, submission, runtime_identity, delivery_export_ref=None,
                      *, review_message_binding=None, review_step=None):
        from .prompt_sources import native_reviewer, review_profile
        from .handoff_release import manifest
        native = native_reviewer(self.store)
        mode = manifest(self.store).get('review_execution_mode')
        entrypoint = manifest(self.store).get('review_entrypoint')
        if native:
            runtime_identity = {**runtime_identity, 'review_profile':'native-reviewer-v2'}
        if native:
            # Public submitted arguments remain evidence even when validation
            # rejects them. This is an existing event, not a formal review/pass.
            self.store.event('review_submission_candidate', {'actor':actor.__dict__,
                'operation_id':operation_id, 'submission':submission})
        def save(db):
            if actor.role not in {"reviewer", "rubric_grader"}:
                raise ActionForbidden("FORBIDDEN: review writer")
            if review_message_binding is not None:
                from .review_message import validate_message_binding
                validate_message_binding(self, db, actor, review_message_binding)
            data = ReviewSubmission.model_validate(submission).model_dump()
            if mode == "bounded-tool-v1":
                if any(i["assessment_kind"] == "content" for i in data["items"]):
                    if runtime_identity.get("mode") != "bounded-review-v1":
                        raise ActionRejected("CONTENT_JUDGMENT_REQUIRES_BOUNDED_CHECKER")
                    if data["delivery_checks"] or any(i["assessment_kind"] != "content" for i in data["items"]):
                        raise ActionRejected("BOUNDED_CONTENT_CHECK_CANNOT_PUBLISH_ARTIFACT_JUDGMENTS")
            task_row = db.execute("SELECT data FROM content_versions WHERE type='DelegatedTask' AND id=? AND version=1",
                                  (actor.task_id,)).fetchone()
            task_payload = json.loads(task_row[0])["payload"] if task_row else {}
            requirements = task_payload.get("review_requirements", [])
            basis = task_payload.get('review_commission_basis')
            standard_keys = {Ref.model_validate(r).key() for r in basis['criterion_refs']} if basis else set()
            if native:
                from .review_input import validate_native_submission
                validate_native_submission(self, db, actor,
                    json.loads(task_row[0])['payload'] if task_row else None, requirements, data)
            if native or mode == "bounded-tool-v1":
                from .artifact_review import matching_requirement
                for item in data["items"]:
                    requirement = matching_requirement(requirements, item)
                    reference = requirement.get("presentation_reference_ref") if requirement else None
                    if reference and reference not in data["dependency_refs"]:
                        data["dependency_refs"].append(reference)
                    if reference and item.get("dependency_refs") is not None and reference not in item["dependency_refs"]:
                        item["dependency_refs"].append(reference)
            if delivery_export_ref is not None:
                if actor.role != "reviewer":
                    raise ActionForbidden("FORBIDDEN: final submission belongs to delegated reviewer")
                export = self._read(db, delivery_export_ref)
                if (export["ref"]["type"] != "ExportArtifact" or
                        export["payload"]["snapshot_ref"] != data["snapshot_ref"]):
                    raise ActionRejected("REVIEW_EXPORT_VERSION_MISMATCH")
                data["bound_export_ref"] = delivery_export_ref
                if entrypoint == "native-rubric-v1" and delivery_export_ref not in data["dependency_refs"]:
                    data["dependency_refs"].append(delivery_export_ref)
            snap = self._read(db, data["snapshot_ref"])
            if snap["ref"]["type"] != "DocumentSnapshot":
                raise ActionRejected("SNAPSHOT_REQUIRED")
            members = {Ref.model_validate(r).key() for r in [snap["ref"], *snap["payload"]["refs"]]}
            # Reviewed targets/criteria stay in the author's manifest. Independent
            # source dependencies belong to the project, not necessarily that manifest.
            external_sources = {Ref.model_validate(r).key() for r in [*data["dependency_refs"],
                *[r for i in data["items"] for r in (i.get("dependency_refs") or [])]] if r["type"] == "SourceArtifact"}
            from .task_supervision import historical_read_refs, material_refs_in_observation, review_identity
            whole_reads = set()
            for row in db.execute('SELECT data FROM content_observations WHERE actor_id=?', (actor.id,)):
                whole_reads.update(material_refs_in_observation(json.loads(row[0])))
            encoded_members = {encode(r) for r in [snap['ref'], *snap['payload']['refs']]}
            comparisons = set()
            for item in data['items']:
                requirement = next((r for r in requirements if review_identity(r) == review_identity(item)), None)
                if requirement:
                    comparisons.update(historical_read_refs(requirement, encoded_members, whole_reads))
            declared_dependencies = {encode(r) for r in [*data['dependency_refs'],
                *[r for i in data['items'] for r in (i.get('dependency_refs') or [])]]}
            comparisons &= declared_dependencies
            targets = [("target_ref", data["target_ref"])] + [
                (f"criteria_refs[{i}]", r) for i, r in enumerate(data["criteria_refs"])] + [
                (f"items[{i}].{field}", item[field]) for i, item in enumerate(data["items"])
                for field in ("target_ref", "criterion_ref")]
            for path, ref in targets:
                allowed = standard_keys if basis and ('criterion_ref' in path or path.startswith('criteria_refs')) else members
                if Ref.model_validate(ref).key() not in allowed:
                    raise ActionRejected("REVIEW_TARGET_OUTSIDE_SNAPSHOT: " + encode({
                        "field": path, "received": ref, "snapshot_ref": snap["ref"],
                        "hint": "Use a snapshot member as target; ExportArtifact/RenderArtifact belong in artifact_refs."}))
            for ref in refs_in(data):
                record = self._read(db, ref.model_dump())
                if ref.key() not in members:
                    if basis and ref.key() in standard_keys:
                        continue
                    if ref.key() in external_sources:
                        # SourceArtifact records can only be captured by server code
                        # from this project's authorized catalog, never model payloads.
                        continue
                    if encode(ref.model_dump()) in comparisons:
                        continue
                    if ref.type not in {"ExportArtifact", "RenderArtifact"} or record["payload"].get("snapshot_ref") != snap["ref"]:
                        raise ActionRejected("REVIEW_VERSION_OUTSIDE_SNAPSHOT: " + encode({
                            "received": ref.model_dump(), "snapshot_ref": snap["ref"],
                            "hint": "All review references must belong to this snapshot, except declared "
                                    "SourceArtifact dependencies, exact task-declared and actually read historical "
                                    "ContentNode comparison dependencies, and ExportArtifact/RenderArtifact bound to it. "
                                    "ReviewRecord references are not snapshot members; prior review reuse "
                                    "has a separate confirm_review_reuse operation."}))
            if any(r not in (basis['criterion_refs'] if basis else snap["payload"]["criteria_refs"]) for r in data["criteria_refs"]):
                raise ActionRejected("CRITERION_OUTSIDE_SNAPSHOT")
            # Excel is a content companion. Layout judgments apply to Word only;
            # an export-fidelity check can still bind the exact workbook version.
            render_refs = [ref for item in data["items"]
                           if item["assessment_kind"] == "render"
                           for ref in item["artifact_refs"]]
            render_refs += [ref for check in data["delivery_checks"]
                            if check["kind"] == "render" for ref in check["artifact_refs"]]
            for ref in render_refs:
                record = self._read(db, ref)
                export = (self._read(db, record["payload"]["export_ref"])
                          if ref["type"] == "RenderArtifact" else record)
                if export["payload"].get("file_ref", "").lower().endswith(".xlsx"):
                    raise ActionRejected("EXCEL_LAYOUT_REVIEW_OUTSIDE_SCOPE")
            if mode == "bounded-tool-v1" and not any(
                    i["assessment_kind"] == "content" for i in data["items"]):
                from .artifact_review import validate_artifact_items
                validate_artifact_items(self, db, requirements, data)
            elif native and (any(i['assessment_kind'] != 'content' for i in data['items']) or data['delivery_checks']):
                from .artifact_review import validate_artifact_items
                validate_artifact_items(self, db, requirements, data, skip_content=True)
            for item_index, item in enumerate(data["items"]):
                if item["criterion_ref"] not in data["criteria_refs"]:
                    raise ActionRejected("UNDECLARED_CRITERION")
                usable_observations = 0
                for observation_index, observation in enumerate(item["observations"]):
                    # Receipt existence is deterministic; support remains the reviewer's judgment.
                    row = db.execute("SELECT actor_id,data FROM content_observations WHERE id=?", (observation["receipt_id"],)).fetchone()
                    if not row or row[0] != actor.id:
                        raise ActionRejected("OBSERVATION_RECEIPT_NOT_FROM_THIS_REVIEWER", diagnostic={
                            "reason": "observation_receipt_unavailable_to_current_reviewer",
                            "parameter_path": ["review", "items", item_index, "observations", observation_index, "receipt_id"]})
                    observed = json.loads(row[1])
                    if (observed.get("status") != "failed" and observed.get("execution_state") != "blocked"
                            and observed.get("ok") is not False and observed.get("accepted") is not False):
                        usable_observations += 1
                if item["verdict"] is not None and not usable_observations:
                    raise ActionRejected("FAILED_READS_DO_NOT_ESTABLISH_OBSERVATIONS")
                for check in item.get("check_results") or []:
                    for index in check["observation_indexes"]:
                        observation = item["observations"][index]
                        row = db.execute("SELECT data FROM content_observations WHERE id=?", (observation["receipt_id"],)).fetchone()
                        observed = json.loads(row[0])
                        if check["execution_state"] == "completed" and (observed.get("status") == "failed" or observed.get("execution_state") == "blocked" or observed.get("ok") is False or observed.get("accepted") is False):
                            raise ActionRejected("COMPLETED_CHECK_REQUIRES_SUCCESSFUL_OBSERVATION")
                requirement = next((r for r in requirements if r["target_ref"] == item["target_ref"] and
                    r["criterion_ref"] == item["criterion_ref"] and r["scope_id"] == (item.get("scope_id") or item["scope"]) and
                    r["assessment_kind"] == item["assessment_kind"]), None)
                if requirement and requirement.get("required_materials"):
                    from .task_supervision import (missing_required_materials, material_refs_in_observation,
                                                   source_extents_in_observation)
                    if not item.get("check_results") and (item["execution_state"] == "completed" or item.get("checked_requirement_indexes")):
                        raise ActionRejected("DECLARED_MATERIALS_REQUIRE_PER_CHECK_ACCOUNT")
                    for check in item.get("check_results") or []:
                        if check["execution_state"] != "completed":
                            continue
                        cited, source_extents = set(), []
                        for index in check["observation_indexes"]:
                            row = db.execute("SELECT data FROM content_observations WHERE id=?",
                                (item["observations"][index]["receipt_id"],)).fetchone()
                            actual = json.loads(row[0])
                            cited.update(material_refs_in_observation(actual))
                            source_extents.extend(source_extents_in_observation(self, actor.id, actual))
                        if missing_required_materials(requirement, cited, {check["requirement_index"]}, source_extents):
                            raise ActionRejected("COMPLETED_CHECK_MISSING_REQUIRED_MATERIAL")
            item_keys = [self.review_item_key(i) for i in data["items"]]
            if len(item_keys) != len(set(item_keys)):
                raise ActionRejected("DUPLICATE_REVIEW_OBLIGATION")
            kinds = [c["kind"] for c in data["delivery_checks"]]
            if len(kinds) != len(set(kinds)):
                raise ActionRejected("DUPLICATE_DELIVERY_CHECK")
            for check_index, check in enumerate(data["delivery_checks"]):
                matched = False
                for observation_index, observation in enumerate(check["observations"]):
                    row = db.execute("SELECT actor_id,data FROM content_observations WHERE id=?", (observation["receipt_id"],)).fetchone()
                    if not row or row[0] != actor.id:
                        raise ActionRejected("OBSERVATION_RECEIPT_NOT_FROM_THIS_REVIEWER", diagnostic={
                            "reason": "observation_receipt_unavailable_to_current_reviewer",
                            "parameter_path": ["review", "delivery_checks", check_index, "observations", observation_index, "receipt_id"]})
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
            if basis:
                data.update(review_interface_profile='review-interfaces-v4', review_basis_digest=basis['digest'])
            # Capture access evidence available when this judgment was saved.
            # Later reads cannot retroactively establish an earlier assessment.
            data["observation_rowid"] = db.execute(
                "SELECT COALESCE(MAX(rowid), 0) FROM content_observations WHERE actor_id=?",
                (actor.id,)).fetchone()[0]
            from .review_coverage import validate_accounting
            validate_accounting(snap, data)
            review_ref = self._insert(db, actor, "ReviewRecord", data)
            step_result = {}
            if review_step is not None:
                from .review_steps import finalize_mark
                step_result = finalize_mark(self, db, actor, operation_id, review_ref, review_step)
            if delivery_export_ref is not None and entrypoint == "native-rubric-v1":
                final = {"target": {"snapshot_ref": data["snapshot_ref"], "export_ref": delivery_export_ref},
                         "review_ref": review_ref, "runtime_identity": runtime_identity,
                         "entrypoint": "delegated-reviewer-v1"}
                db.execute("INSERT OR REPLACE INTO state VALUES ('content_final_review', ?)", (encode(final),))
            return {"review_ref": review_ref, **step_result}
        request = {"submit_review": submission, "runtime_identity": runtime_identity}
        if review_message_binding is not None:
            request['review_message_binding'] = digest(review_message_binding)
        if review_step is not None:
            request = review_step['request']
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

    @staticmethod
    def review_item_key(item):
        return (encode(item["target_ref"]), encode(item["criterion_ref"]),
                item.get("scope_id") or item["scope"], item.get("assessment_kind", "content"))

    @staticmethod
    def item_dependencies(payload, item):
        return payload["dependency_refs"] if item.get("dependency_refs") is None else item["dependency_refs"]

    def review_item_state(self, review, snapshot_ref, index=None, history=None):
        """Explicit correction/reuse only; None addresses legacy delivery checks."""
        corrections, reuses = history if history is not None else (
            self.list_objects("ReviewSupersession"), self.list_objects("ReviewReuse"))
        withdrawn = any(r["payload"]["review_ref"] == review["ref"] and
            (r["payload"].get("item_indexes") is None or index in r["payload"]["item_indexes"])
            for r in corrections)
        reuse = [r["ref"] for r in reuses
            if r["payload"]["review_ref"] == review["ref"] and r["payload"]["snapshot_ref"] == snapshot_ref
            and (r["payload"].get("item_indexes") is None or index in r["payload"]["item_indexes"])]
        return withdrawn, review["payload"]["snapshot_ref"] == snapshot_ref or bool(reuse), reuse

    def item_applies(self, item, snapshot_ref, export_ref=None, workbook_export_ref=None):
        """Match every assessed artifact against the exact selected delivery.

        A Word-only finding remains Word-only evidence when a companion is selected;
        membership never expands its coverage to that companion. Callers supply the
        saved, validated selection, not all exports sharing a snapshot.
        """
        if item.get("assessment_kind", "content") == "content":
            return True
        # Older mixed findings cannot safely lose their content concern when only
        # the exported file changes. Keep negative evidence, never transfer a pass.
        if item.get("assessment_kind") == "combined" and item.get("verdict") == "not_satisfied":
            return True
        exports = []
        for ref in item["artifact_refs"]:
            record = self.read(ref)
            if record["payload"].get("snapshot_ref") != snapshot_ref:
                return False
            exports.append(record["payload"]["export_ref"] if ref["type"] == "RenderArtifact" else ref)
        selected = [r for r in (export_ref, workbook_export_ref) if r is not None]
        return bool(exports) and all(r in selected for r in exports)

    def review_summary(self, snapshot_ref, required, export_ref=None, workbook_export_ref=None):
        self.read(snapshot_ref)
        items, delivery_violations, needs_recheck = [], [], []
        history = (self.list_objects("ReviewSupersession"), self.list_objects("ReviewReuse"))
        for review in self.list_objects("ReviewRecord"):
            for index, item in enumerate(review["payload"]["items"]):
                withdrawn, relevant, _ = self.review_item_state(review, snapshot_ref, index, history)
                if withdrawn or not relevant:
                    continue
                changed = self.changed_review_sources(review["payload"], item)
                if changed:
                    needs_recheck.append({"review_ref": review["ref"], "item_index": index, "changed_source_refs": changed})
                if (not changed or item["verdict"] == "not_satisfied") and self.item_applies(item, snapshot_ref, export_ref, workbook_export_ref):
                    items.append(item)
            withdrawn, relevant, _ = self.review_item_state(review, snapshot_ref, history=history)
            if relevant and not withdrawn:
                delivery_violations.extend(c for c in review["payload"].get("delivery_checks", [])
                    if c["verdict"] == "not_satisfied" and self.item_applies(
                        {**c, "assessment_kind": c["kind"]}, snapshot_ref, export_ref, workbook_export_ref))
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

    def _supersede_review(self, db, actor, review_ref, replacement_ref, reason, item_indexes=None):
        old, new = self._read(db, review_ref), self._read(db, replacement_ref)
        if actor.role not in {"reviewer", "rubric_grader"} or old["owner_id"] != actor.id or new["owner_id"] != actor.id:
            raise ActionForbidden("FORBIDDEN: review owner")
        if (review_ref["type"] != "ReviewRecord" or replacement_ref["type"] != "ReviewRecord"
                or old["payload"]["snapshot_ref"] != new["payload"]["snapshot_ref"]
                or review_ref == replacement_ref or not reason.strip()):
            raise ActionRejected("INVALID_REVIEW_SUPERSESSION")
        selected = self.selected_review_items(old["payload"], item_indexes)
        if not {self.review_item_key(i) for i in selected} <= {self.review_item_key(i) for i in new["payload"]["items"]} or not all(i["observations"] for i in new["payload"]["items"]):
            raise ActionRejected("CORRECTED_REVIEW_REQUIRES_COVERAGE_AND_OBSERVATIONS")
        def checks_by_key(record):
            return {(c["kind"], tuple(sorted(encode(r) for r in c["artifact_refs"]))): c
                    for c in record["payload"].get("delivery_checks", [])}
        old_checks, new_checks = checks_by_key(old) if item_indexes is None else {}, checks_by_key(new)
        if not old_checks.keys() <= new_checks.keys() or any(
                (c["verdict"] is not None or c["observations"]) and not new_checks[key]["observations"]
                for key, c in old_checks.items()):
            raise ActionRejected("CORRECTED_REVIEW_REQUIRES_DELIVERY_COVERAGE")
        return {"supersession_ref": self._insert(db, actor, "ReviewSupersession", {
            "review_ref": review_ref, "replacement_ref": replacement_ref, "reason": reason, "item_indexes": item_indexes})}

    def supersede_review(self, actor, operation_id, review_ref, replacement_ref, reason, item_indexes=None):
        """A reviewer can correct their own finding, keeping the original evidence."""
        def save(db):
            return self._supersede_review(db, actor, review_ref, replacement_ref, reason, item_indexes)
        request = [review_ref, replacement_ref, reason] + ([] if item_indexes is None else [item_indexes])
        return self.operation(actor, operation_id, {"supersede_review": request}, save)

    @staticmethod
    def selected_review_items(payload, indexes):
        if indexes is None:
            return payload["items"]
        if not indexes or len(set(indexes)) != len(indexes) or any(
                type(i) is not int or i < 0 or i >= len(payload["items"]) for i in indexes):
            raise ActionRejected("REVIEW_ITEM_INDEX_INVALID")
        return [payload["items"][i] for i in indexes]

    def confirm_reuse(self, actor, operation_id, review_ref, new_snapshot, reason, item_indexes=None, *, item_mappings=None):
        """Explicit reviewer confirmation, never a latest-version automatic pass."""
        if item_mappings is not None:
            from .review_binding import confirm_reuse
            if item_indexes is not None:
                raise ActionRejected('REVIEW_REUSE_MAPPING_CONFLICT')
            return self.operation(actor, operation_id, {'reuse_mapping': [review_ref, new_snapshot, reason, item_mappings]},
                lambda db: confirm_reuse(self, db, actor, review_ref, new_snapshot, reason, item_mappings))
        task = self.read({'type':'DelegatedTask','id':actor.task_id,'version':1}) if actor.id.startswith('content:reviewer:') else None
        if task and task['payload'].get('review_interface_profile') == 'review-interfaces-v4':
            raise ActionRejected('REVIEW_REUSE_MAPPING_REQUIRED')
        current_sources = {s["id"]: s for s in self.store.sources([s["id"] for s in self.store.source_catalog()])}
        def save(db):
            if actor.role not in {"reviewer", "rubric_grader"}:
                raise ActionForbidden("FORBIDDEN: review applicability")
            old = self._read(db, review_ref)
            new = self._read(db, new_snapshot)
            if review_ref["type"] != "ReviewRecord" or new_snapshot["type"] != "DocumentSnapshot" or not reason.strip():
                raise ActionRejected("REVIEW_REUSE_REQUIRES_REASON_AND_SNAPSHOT")
            payload = old["payload"]
            selected = self.selected_review_items(payload, item_indexes)
            keys = {Ref.model_validate(r).key() for r in new["payload"]["refs"]}
            keys.add(Ref.model_validate(new_snapshot).key())
            required = [r for i in selected for r in [i["target_ref"], i["criterion_ref"], *self.item_dependencies(payload, i)]]
            if item_indexes is None:
                required += [payload["target_ref"], *payload["criteria_refs"], *payload["dependency_refs"]]
            independent = [r for r in required if r["type"] == "SourceArtifact" and Ref.model_validate(r).key() not in keys]
            for ref in independent:
                source = self._read(db, ref)["payload"]
                current = current_sources.get(source["source_id"])
                if not current or not current.get("current", True) or source != self.source_payload(current):
                    raise ActionRejected("CHANGED_REVIEW_SOURCE_REQUIRES_RECHECK")
            if any(Ref.model_validate(r).key() not in keys and r not in independent for r in required):
                raise ActionRejected("CHANGED_REVIEW_INPUT_REQUIRES_RECHECK")
            for item in [*selected, *(payload.get("delivery_checks", []) if item_indexes is None else [])]:
                for ref in item.get("artifact_refs", []):
                    if self._read(db, ref)["payload"].get("snapshot_ref") != new_snapshot:
                        raise ActionRejected("CHANGED_ARTIFACT_REQUIRES_RECHECK")
            # A whole-snapshot judgment cannot be reused as another whole-snapshot judgment.
            # Unchanged local targets still require semantic confirmation of relevance.
            return {"reuse_ref": self._insert(db, actor, "ReviewReuse", {"review_ref": review_ref,
                "snapshot_ref": new_snapshot, "reason": reason, "item_indexes": item_indexes, "applicability_to_snapshot": "current"})}
        request = [review_ref, new_snapshot, reason] + ([] if item_indexes is None else [item_indexes])
        return self.operation(actor, operation_id, {"reuse": request}, save)

    def changed_review_sources(self, payload, item=None):
        members = self.read(payload["snapshot_ref"])["payload"]["refs"]
        changed = []
        for ref in self.item_dependencies(payload, item) if item is not None else payload["dependency_refs"]:
            if ref["type"] != "SourceArtifact" or ref in members:
                continue
            source = self.read(ref)["payload"]
            current = self.store.sources([source["source_id"]])[0]
            if not current.get("current", True) or source != self.source_payload(current):
                changed.append(ref)
        return changed
