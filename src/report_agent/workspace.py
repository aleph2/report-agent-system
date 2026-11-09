from __future__ import annotations
from . import legacy_state as legacy

from .errors import ActionForbidden, ActionRejected

import json
from uuid import uuid4

from .store import Store, digest, encode


# Compatible outcome tags with stable producer permissions, not execution stages.
OWNERS = {"purpose": "purpose", "plan": "planner", "materials": "materials",
          "draft": "writer", "review": "reviewer", "acceptance": "coordinator"}


class Workspace:
    def __init__(self, store: Store):
        self.store = store
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS work_items (
                    id TEXT PRIMARY KEY, operation TEXT UNIQUE NOT NULL, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS results (
                    id TEXT PRIMARY KEY, operation TEXT UNIQUE NOT NULL, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS result_replacements (
                    replaces_id TEXT PRIMARY KEY, result_id TEXT UNIQUE NOT NULL,
                    task_id TEXT UNIQUE NOT NULL);
                CREATE UNIQUE INDEX IF NOT EXISTS result_submission_id
                    ON results(json_extract(data, '$.submission_id'))
                    WHERE json_extract(data, '$.submission_id') <> '';
            """)

    def initialize(self):
        """Trusted operator input may supply reusable purpose/materials, without a model call."""
        manifest = self.store.manifest
        if self.store.get("report_status") is None:
            self.store.set("report_status", "ready")
        uses = manifest.get("document_uses")
        if uses:
            source_ids = list(uses)
            self.store.sources(source_ids)
            self._seed("purpose", "Operator document-use statement", encode(uses), source_ids)
        for material in self.store.artifacts():
            self._seed("materials", material["title"], material["body"], material["source_ids"])

    def _seed(self, kind, title, body, source_ids):
        data = {"kind": kind, "owner": OWNERS[kind], "title": title, "body": body,
                "source_ids": source_ids, "input_ids": [], "task_id": None,
                "origin": "operator_input", "scope": digest(self.store.manifest)}
        with self.store.connect() as db:
            self._insert_result(db, data)

    def results(self):
        with self.store.connect() as db:
            return [json.loads(r[0]) for r in db.execute("SELECT data FROM results ORDER BY rowid")]

    def result(self, result_id):
        with self.store.connect() as db:
            row = db.execute("SELECT data FROM results WHERE id=?", (result_id,)).fetchone()
        if not row:
            raise ActionRejected("RESULT_NOT_IN_PROJECT")
        return json.loads(row[0])

    @staticmethod
    def _validate_submission_id(submission_id):
        if not isinstance(submission_id, str) or submission_id != submission_id.strip():
            raise ActionRejected("INVALID_SUBMISSION_ID")

    @staticmethod
    def _submission_receipt(db, submission_id):
        row = db.execute("SELECT data FROM results WHERE json_extract(data, '$.submission_id')=? "
                         "AND json_extract(data, '$.submission_id') <> ''", (submission_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def submission_receipt(self, submission_id):
        """Recover the immutable committed result without graph or freshness checks.

        The trusted caller derives the ID from the complete original request before
        graph lookup/provenance expansion or task creation. Empty/unknown IDs miss.
        """
        self._validate_submission_id(submission_id)
        if not submission_id:
            return None
        with self.store.connect() as db:
            return self._submission_receipt(db, submission_id)

    def collect_fact_ids(self, result_ids):
        """Collect exact adopted fact versions for status/export batch graph checks.

        Follows only adopted input_ids and review target_id, never observations or
        replacement pointers. No graph access or claim of current graph validity.
        """
        if (not isinstance(result_ids, (list, tuple))
                or any(not isinstance(i, str) or not i.strip() for i in result_ids)):
            raise ActionRejected("RESULT_IDS_MUST_BE_NONEMPTY_STRINGS")
        results = {r["id"]: r for r in self.results()}
        facts, visited, pending = set(), set(), set(result_ids)
        while pending:
            result_id = pending.pop()
            if result_id in visited:
                continue
            if result_id not in results:
                raise ActionRejected("RESULT_NOT_IN_PROJECT")
            visited.add(result_id)
            result = results[result_id]
            facts.update(result.get("fact_ids", []))
            pending.update(self._result_refs(result) - visited)
        return sorted(facts)

    def tasks(self):
        with self.store.connect() as db:
            return [json.loads(r[0]) for r in db.execute("SELECT data FROM work_items ORDER BY rowid")]

    def task(self, task_id):
        with self.store.connect() as db:
            row = db.execute("SELECT data FROM work_items WHERE id=?", (task_id,)).fetchone()
        if not row:
            raise ActionRejected("TASK_NOT_IN_PROJECT")
        return json.loads(row[0])

    @staticmethod
    def _result_refs(item):
        refs = set(item.get("input_ids", []))
        if item.get("target_id"):
            refs.add(item["target_id"])
        # A predecessor is historical editing context, never a dependency of its replacement.
        refs.discard(item.get("replaces_id"))
        return refs

    @staticmethod
    def _source_refs(item):
        return set(item.get("source_ids", []))

    def _dependency_snapshot(self, result_id, results, replacements, source_replacements, changes):
        """Version evidence for a producer judgment, including transitive current inputs."""
        by_id = {r["id"]: r for r in results}
        versions, source_ids, pending = {}, set(), {result_id}
        while pending:
            current = pending.pop()
            if current in versions:
                continue
            latest = self._current_id(current, replacements)
            versions[current] = latest
            result = by_id[current]
            source_ids.update(self._source_refs(result))
            pending.update(self._result_refs(result) - versions.keys())
            if latest not in versions:
                pending.add(latest)
        relevant_changes = {}
        for change in changes:
            affected = sorted(set(change.get("affected_result_ids", [])) & versions.keys())
            if affected:
                relevant_changes[change["id"]] = {"source_id": change["source_id"],
                                                  "affected_result_ids": affected}
                source_ids.add(change["source_id"])
        versions.pop(result_id, None)
        return {"result_versions": versions,
                "source_versions": {s: self._current_id(s, source_replacements) for s in sorted(source_ids)},
                "source_changes": relevant_changes}

    def impact(self):
        """Compute dependency impact without changing results or scheduling work."""
        with self.store.connect() as db:
            replacements = dict(db.execute("SELECT replaces_id,result_id FROM result_replacements"))
        source_replacements = self.store.superseded_sources()
        superseded = set(replacements)
        sources = set(source_replacements)
        results, tasks = self.results(), self.tasks()
        stale = {r["id"] for r in results if sources & self._source_refs(r)}
        changes = legacy.get_source_changes(self.store, [])
        for change in changes:
            stale.update(change.get("affected_result_ids", []))
        while True:
            affected = superseded | stale
            added = {r["id"] for r in results if self._result_refs(r) & affected} - stale
            if not added:
                break
            stale.update(added)
        # Each producer assesses its own outcome. An upstream judgment does not
        # silently validate downstream work, and superseded results stay historical.
        assessments = legacy.get_result_impact_assessments(self.store, {})
        assessed, unchanged = set(), set()
        for result in results:
            result_id = result["id"]
            if result_id not in stale - superseded:
                continue
            snapshot = self._dependency_snapshot(result_id, results, replacements, source_replacements, changes)
            if assessments.get(result_id, {}).get("snapshot") == snapshot:
                assessed.add(result_id)
            if result.get("dependency_snapshot") == snapshot:
                unchanged.add(result_id)
        stale.difference_update(assessed | unchanged)
        affected = superseded | stale
        affected_tasks = {t["id"] for t in tasks
                          if (t["result_id"] in affected if t.get("result_id") else
                              self._result_refs(t) & affected or sources & self._source_refs(t))}
        return {"replacements": replacements, "source_replacements": source_replacements,
                "superseded_result_ids": sorted(superseded), "stale_result_ids": sorted(stale),
                "needs_assessment_result_ids": sorted(stale - superseded),
                "assessed_result_ids": sorted(assessed),
                "affected_result_ids": sorted(affected), "superseded_source_ids": sorted(sources),
                "affected_task_ids": sorted(affected_tasks)}

    def current_results(self):
        affected = set(self.impact()["affected_result_ids"])
        return [r for r in self.results() if r["id"] not in affected]

    def _input_changes(self, result_ids, source_ids, impact):
        """Report version facts without deciding whether adopted evidence is usable."""
        return {
            "changed_result_ids": sorted(set(result_ids) & set(impact["affected_result_ids"])),
            "result_replacements": {i: self._current_id(i, impact["replacements"])
                                    for i in sorted(set(result_ids)) if i in impact["replacements"]},
            "source_replacements": {i: self._current_id(i, impact["source_replacements"])
                                    for i in sorted(set(source_ids)) if i in impact["source_replacements"]},
            "meaning": "change_evidence_only_not_validity",
        }

    @staticmethod
    def _current_id(result_id, replacements):
        while result_id in replacements:
            result_id = replacements[result_id]
        return result_id

    def request_revision(self, result_id, description):
        """Coordinator capability: bind a new task to the original producer and result."""
        previous = self.result(result_id)
        if not description.strip():
            raise ActionRejected("REVISION_REASON_REQUIRED")
        operation = digest({"replaces_id": result_id, "description": description})
        impact = self.impact()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT data FROM work_items WHERE operation=?", (operation,)).fetchone()
            if row:
                return json.loads(row[0])
            if db.execute("SELECT 1 FROM result_replacements WHERE replaces_id=?", (result_id,)).fetchone():
                raise ActionRejected("REVISION_REQUIRES_CURRENT_RESULT")
            inputs = sorted({self._current_id(i, impact["replacements"])
                             for i in self._result_refs(previous)})
            saved = legacy.get_corrections(db, [])
            corrections = [c for c in saved
                           if self._current_id(c["result_id"], impact["replacements"]) == result_id
                           and c.get("status", "pending") == "pending"]
            feedback = [description] + [c["description"] for c in corrections if c["description"] != description]
            old_sources = sorted(self._source_refs(previous) & set(impact["superseded_source_ids"]))
            if old_sources:
                feedback.append("Superseded source references: " + ", ".join(old_sources)
                                + ". Assess applicable source versions within the existing project goal; "
                                "source IDs are not automatically remapped.")
            task = {"id": str(uuid4()), "kind": previous["kind"], "owner": previous["owner"],
                    "goal": description, "replaces_id": result_id, "input_ids": inputs,
                    "status": "ready", "result_id": None, "error": None,
                    "used_result_ids": [], "used_source_ids": [], "feedback": feedback,
                    "correction_ids": [c.get("id", digest({"result_id": c["result_id"],
                                                          "description": c["description"]})) for c in corrections]}
            db.execute("INSERT INTO work_items VALUES (?, ?, ?)", (task["id"], operation, encode(task)))
            db.execute("INSERT INTO events(kind,data) VALUES ('revision_requested', ?)",
                       (encode({"task_id": task["id"], "replaces_id": result_id}),))
        return task

    def update_task(self, task_id, **values):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            task = self.task(task_id)
            bound = {"id", "kind", "owner", "goal", "input_ids", "replaces_id", "correction_ids", "result_id",
                     "used_history_source_ids", "used_history_result_ids"}
            if any(key in bound and value != task.get(key) for key, value in values.items()):
                raise ActionForbidden("TASK_BINDING_IMMUTABLE")
            task.update(values)
            db.execute("UPDATE work_items SET data=? WHERE id=?", (encode(task), task_id))
        return task

    def request_task(self, kind: str, goal: str, input_ids: list[str]):
        """Bind a producer and adopted inputs to a commit receipt; never schedule execution."""
        if kind not in OWNERS or not goal.strip():
            raise ActionRejected("INVALID_TASK_REQUEST")
        inputs = [self.result(i) for i in sorted(set(input_ids))]
        impact = self.impact()
        operation = digest({"kind": kind, "goal": goal, "input_ids": sorted(set(input_ids)),
                            "scope": digest(self.store.manifest),
                            "context_revision": self.store.get("context_revision", 0) if kind in {"draft", "review"} else None})
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT data FROM work_items WHERE operation=?", (operation,)).fetchone()
            if row:
                return json.loads(row[0])
            task = {"id": str(uuid4()), "kind": kind, "owner": OWNERS[kind], "goal": goal,
                    "input_ids": [r["id"] for r in inputs], "status": "ready", "result_id": None,
                    "error": None, "used_result_ids": [], "used_source_ids": [], "feedback": [],
                    "input_changes": self._input_changes(input_ids, (), impact)}
            db.execute("INSERT INTO work_items VALUES (?, ?, ?)", (task["id"], operation, encode(task)))
            db.execute("INSERT INTO events(kind,data) VALUES ('task_created', ?)",
                       (encode({"task_id": task["id"], "kind": kind}),))
        return task

    def record_read(self, task_id, *, result_ids=(), source_ids=()):
        """Audit observations only; submit input_ids/source_ids to adopt evidence."""
        task = self.task(task_id)
        self.update_task(task_id, used_result_ids=sorted(set(task["used_result_ids"]) | set(result_ids)),
                         used_source_ids=sorted(set(task["used_source_ids"]) | set(source_ids)))

    @staticmethod
    def _insert_result(db, data):
        operation = digest(data)
        existing = db.execute("SELECT data FROM results WHERE operation=?", (operation,)).fetchone()
        if existing:
            return json.loads(existing[0])
        result = {**data, "id": str(uuid4()), "operation": operation}
        db.execute("INSERT INTO results VALUES (?, ?, ?)", (result["id"], operation, encode(result)))
        return result

    def submit(self, task_id, *, actor, title, body, source_ids, input_ids, outcome="", target_id="", fact_ids=(),
               submission_id=""):
        """Commit explicit references with the result and receipt in one SQL transaction.

        The trusted tool boundary first checks submission_receipt, then validates
        new fact references and expands provenance. Only immutable version IDs
        are stored here; SQL does not assert current graph validity.
        """
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            return self._submit(db, self.task(task_id), actor=actor, title=title, body=body,
                                source_ids=source_ids, input_ids=input_ids, outcome=outcome,
                                target_id=target_id, fact_ids=fact_ids, submission_id=submission_id)

    commit = submit

    def _submit(self, db, task, *, actor, title, body, source_ids, input_ids, outcome, target_id, fact_ids,
                submission_id):
        task_id = task["id"]
        kind = task["kind"]
        if actor != task["owner"] or OWNERS[kind] != actor:
            raise ActionForbidden("RESULT_OWNER_MISMATCH")
        self._validate_submission_id(submission_id)
        if (not isinstance(fact_ids, (list, tuple))
                or any(not isinstance(i, str) or not i.strip() or i != i.strip() for i in fact_ids)):
            raise ActionRejected("FACT_IDS_MUST_BE_NONEMPTY_STRINGS")
        declared = sorted(set(task["input_ids"] + input_ids))
        receipt = {"kind": kind, "owner": actor, "task_id": task_id, "title": title, "body": body,
                   "source_ids": sorted(set(source_ids)), "input_ids": declared,
                   "fact_ids": sorted(set(fact_ids)),
                   "outcome": outcome, "target_id": target_id}
        if submission_id:
            old = self._submission_receipt(db, submission_id)
            if old:
                if (all((old.get(k, []) if k == "fact_ids" else old[k]) == v for k, v in receipt.items())
                        and old.get("replaces_id") == task.get("replaces_id")):
                    return old
                raise ActionRejected("SUBMISSION_ID_CONFLICT")
            if task["result_id"]:
                # Never attach or replace an ID on an already immutable result.
                raise ActionRejected("SUBMISSION_ID_MISMATCH")
        # Recover a committed write before applying today's observation checks.
        if task["result_id"]:
            old = self.result(task["result_id"])
            if all((old.get(k, []) if k == "fact_ids" else old[k]) == v for k, v in receipt.items()):
                return old
            raise ActionRejected("TASK_ALREADY_COMMITTED_REQUEST_REVISION")
        if not title.strip() or not body.strip():
            raise ActionRejected("RESULT_CONTENT_REQUIRED")
        if kind == "draft":
            from .acceptance import enabled, draft_criteria
            if enabled(self):
                draft_criteria(self, {"input_ids": declared})
        self.store.sources(source_ids)
        replaces_id = task.get("replaces_id")
        if replaces_id:
            previous = self.result(replaces_id)
            if previous["owner"] != actor or previous["kind"] != kind:
                raise ActionForbidden("REPLACEMENT_OWNER_MISMATCH")
            if replaces_id in declared:
                raise ActionRejected("PREDECESSOR_IS_NOT_AN_INPUT_DEPENDENCY")
            if db.execute("SELECT 1 FROM result_replacements WHERE replaces_id=?", (replaces_id,)).fetchone():
                raise ActionRejected("REVISION_REQUIRES_CURRENT_RESULT")
        impact = self.impact()
        for result_id in task["used_result_ids"]:
            self.result(result_id)
        self.store.sources(task["used_source_ids"])
        history_results = set(task["used_result_ids"]) & (set(impact["affected_result_ids"]) | {replaces_id})
        history_sources = set(task["used_source_ids"]) & set(impact["superseded_source_ids"])
        observed = sorted(set(task["used_result_ids"]) - history_results)
        observed_sources = sorted(set(task["used_source_ids"]) - history_sources)
        for result_id in declared:
            self.result(result_id)
        if kind == "review":
            if outcome not in {"accepted", "changes_required"}:
                raise ActionRejected("REVIEW_OUTCOME_REQUIRED")
            if target_id not in declared or self.result(target_id)["kind"] != "draft":
                raise ActionRejected("REVIEW_REQUIRES_EXACT_DRAFT")
            if target_id not in task["used_result_ids"]:
                raise ActionRejected("REVIEW_TARGET_NOT_OBSERVED")
        elif outcome or target_id:
            raise ActionForbidden("ONLY_REVIEWER_CAN_SUBMIT_REVIEW")
        data = {**receipt, "observed_result_ids": observed, "observed_source_ids": observed_sources,
                "observed_history_result_ids": sorted(history_results),
                "observed_history_source_ids": sorted(history_sources),
                "input_changes": self._input_changes(declared, source_ids, impact),
                "scope": digest(self.store.manifest),
                "context_revision": self.store.get("context_revision", 0), "origin": "agent"}
        if submission_id:
            data["submission_id"] = submission_id
        if replaces_id:
            data.update(replaces_id=replaces_id)
        pending_result = {**data, "id": ""}
        data["dependency_snapshot"] = self._dependency_snapshot(
            "", self.results() + [pending_result], impact["replacements"],
            impact["source_replacements"], legacy.get_source_changes(self.store, []))
        result = self._insert_result(db, data)
        if replaces_id:
            db.execute("INSERT INTO result_replacements VALUES (?, ?, ?)", (replaces_id, result["id"], task_id))
            corrections = legacy.get_corrections(db, [])
            for correction in corrections:
                correction_id = correction.get("id", digest({"result_id": correction["result_id"],
                                                              "description": correction["description"]}))
                if (correction_id in task.get("correction_ids", [])
                        and self._current_id(correction["result_id"], impact["replacements"]) == replaces_id
                        and correction.get("status", "pending") == "pending"):
                    correction.update(id=correction_id, status="addressed", resolved=False,
                                      replacement_id=result["id"], revision_task_id=task_id,
                                      resolution="replacement_committed_pending_review")
                    db.execute("INSERT INTO events(kind,data) VALUES ('correction_addressed', ?)",
                               (encode(correction),))
            legacy.set_corrections(db, corrections)
            db.execute("INSERT INTO events(kind,data) VALUES ('result_replaced', ?)",
                       (encode({"replaces_id": replaces_id, "result_id": result["id"], "task_id": task_id}),))
        task.update(status="completed", result_id=result["id"], error=None,
                    used_history_result_ids=sorted(history_results), used_history_source_ids=sorted(history_sources))
        db.execute("UPDATE work_items SET data=? WHERE id=?", (encode(task), task_id))
        db.execute("INSERT INTO events(kind,data) VALUES ('result_committed', ?)",
                   (encode({"task_id": task_id, "result_id": result["id"], "kind": kind}),))
        return result

    def request_correction(self, result_id, description):
        result = self.result(result_id)
        if not description.strip():
            raise ActionRejected("CORRECTION_REASON_REQUIRED")
        correction_id = digest({"result_id": result_id, "description": description})
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            corrections = legacy.get_corrections(db, [])
            for old in corrections:
                if old["result_id"] == result_id and old["description"] == description:
                    if "id" not in old:
                        old.update(id=correction_id, status="pending", resolved=False)
                        legacy.set_corrections(db, corrections)
                    return {"recorded": True, **old}
            item = {"id": correction_id, "result_id": result_id, "owner": result["owner"],
                    "description": description, "status": "pending", "resolved": False}
            legacy.set_corrections(db, corrections + [item])
            db.execute("INSERT INTO events(kind,data) VALUES ('correction_requested', ?)", (encode(item),))
        return {"recorded": True, **item}

    def assess_source_change(self, change_id, description, affected_result_ids=None):
        """Coordinator-only capability; consideration neither grants scope nor validates results."""
        if not description.strip():
            raise ActionRejected("SOURCE_CHANGE_ASSESSMENT_REQUIRED")
        affected = sorted(set(affected_result_ids or []))
        for result_id in affected:
            self.result(result_id)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            changes = legacy.get_source_changes(db, [])
            change = next((c for c in changes if c["id"] == change_id), None)
            if change is None:
                raise ActionRejected("SOURCE_CHANGE_NOT_IN_PROJECT")
            assessment = {"description": description, "origin": "coordinator",
                          "meaning": "relevance_considered_only", "affected_result_ids": affected}
            if change.get("assessment") == assessment:
                return change
            change["assessment"] = assessment
            # Acknowledging a change again cannot validate previously affected work.
            change["affected_result_ids"] = sorted(set(change.get("affected_result_ids", [])) | set(affected))
            legacy.set_source_changes(db, changes)
            db.execute("INSERT INTO events(kind,data) VALUES ('source_change_assessed', ?)", (encode(change),))
        return change

    def assess_result_impact(self, result_id, actor, description):
        """Producer-only judgment that unchanged content remains usable at this snapshot.

        The runtime must bind actor from the assigned producer, never model arguments.
        This does not resolve corrections, change review versions, or schedule work.
        """
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            result = self.result(result_id)
            if actor != result["owner"] or OWNERS[result["kind"]] != actor:
                raise ActionForbidden("RESULT_OWNER_MISMATCH")
            if not description.strip():
                raise ActionRejected("RESULT_IMPACT_ASSESSMENT_REQUIRED")
            impact = self.impact()
            if result_id in impact["superseded_result_ids"]:
                raise ActionRejected("ASSESSMENT_REQUIRES_CURRENT_RESULT")
            snapshot = self._dependency_snapshot(result_id, self.results(), impact["replacements"],
                                                 impact["source_replacements"],
                                                 legacy.get_source_changes(self.store, []))
            assessment = {"result_id": result_id, "actor": actor, "description": description,
                          "meaning": "still_usable", "snapshot": snapshot}
            assessments = legacy.get_result_impact_assessments(self.store, {})
            if assessments.get(result_id) == assessment:
                return assessment
            assessments[result_id] = assessment
            legacy.set_result_impact_assessments(db, assessments)
            db.execute("INSERT INTO events(kind,data) VALUES ('result_impact_assessed', ?)",
                       (encode(assessment),))
        return assessment

    def issue(self, category, description, source_ids):
        if category not in {"source_missing", "source_conflict", "system_failure", "requirement"} or not description.strip():
            raise ActionRejected("INVALID_ISSUE")
        self.store.sources(source_ids)
        issues = legacy.get_report_issues(self.store, [])
        for item in issues:
            if (item["category"], item["description"], item["source_ids"]) == (category, description, source_ids):
                return item
        item = {"id": str(uuid4()), "category": category, "description": description,
                "source_ids": source_ids, "resolved": False}
        self._issue_change(issues + [item], "issue_recorded",
                             {"issue_id": item["id"], "category": category})
        return item

    def _issue_change(self, issues, event_kind, event_data, *, report_status=None):
        with self.store.connect() as db:
            row = db.execute("SELECT value FROM state WHERE key='context_revision'").fetchone()
            revision = (json.loads(row[0]) if row else 0) + 1
            legacy.set_report_issues(db, issues)
            if report_status is not None:
                db.execute("INSERT OR REPLACE INTO state VALUES ('report_status', ?)", (encode(report_status),))
            db.execute("INSERT OR REPLACE INTO state VALUES ('context_revision', ?)", (encode(revision),))
            db.execute("INSERT INTO events(kind,data) VALUES (?, ?)", (event_kind, encode(event_data)))

    def decide_issue(self, issue_id, message, resolved=False):
        if not message.strip():
            raise ActionRejected("HUMAN_DECISION_REQUIRED")
        with self.store.run_lock():
            issues = legacy.get_report_issues(self.store, [])
            issue = next((i for i in issues if i["id"] == issue_id), None)
            if issue is None:
                raise ActionRejected("ISSUE_NOT_IN_PROJECT")
            from . import commission_assertions
            if issue["category"] == "requirement" and any(
                commission_assertions.checkpoint(self.store, kind, issue_id)
                for kind in ("plan", "requirements")
            ):
                raise ActionRejected("TYPED_CHECKPOINT_REQUIRES_COMMISSION_REPLY")
            if issue.get("decision") == message and issue["resolved"] == resolved:
                return issue
            issue.update(decision=message, resolved=resolved, decision_origin="operator")
            # A recorded decision is input for the producer, not automatic validation.
            self._issue_change(issues,
                                 "human_decision", {"issue_id": issue_id, "message": message, "resolved": resolved}, report_status="ready")
        return issue

    def delivery(self, draft_id, review_id=""):
        draft = self.result(draft_id)
        if draft["kind"] != "draft":
            raise ActionRejected("DRAFT_REQUIRED")
        status = "unreviewed_draft"
        impact = self.impact()
        if review_id:
            requested = self.result(review_id)
            if requested["kind"] != "review" or requested["target_id"] != draft_id:
                raise ActionRejected("REVIEW_VERSION_MISMATCH")
        results = self.results()
        reviews = [r for r in results if r["kind"] == "review" and r["target_id"] == draft_id
                   and r["id"] not in impact["superseded_result_ids"]]
        # One effective review rule for UI, delivery selection and export.
        review = None
        if reviews:
            review = reviews[-1]
            review_id = review["id"]
            status = "reviewed_draft" if review["outcome"] == "accepted" else "changes_required"
        dependencies = {draft_id, review_id} - {""}
        while True:
            current = {self._current_id(i, impact["replacements"]) for i in dependencies}
            added = (current | set().union(*(self._result_refs(r) for r in results
                                             if r["id"] in dependencies))) - dependencies
            if not added:
                break
            dependencies.update(added)
        corrections = [c for c in legacy.get_corrections(self.store, [])
                       if self._current_id(c["result_id"], impact["replacements"]) in dependencies
                       and not c.get("resolved", False)]
        if any(c.get("status", "pending") == "pending" for c in corrections):
            status = "changes_required"
        pending = [i for i in legacy.get_report_issues(self.store, []) if not i["resolved"]]
        if any(i["category"] in {"source_conflict", "source_missing"} for i in pending):
            status = "needs_human"
        elif any(i["category"] == "system_failure" for i in pending):
            status = "system_error"
        sources = {s for r in results if r["id"] in dependencies for s in self._source_refs(r)}
        changes = {**self._input_changes(dependencies, sources, impact),
                   "source_changes": legacy.get_source_changes(self.store, []),
                   "context_revision": self.store.get("context_revision", 0),
                   "review_context_revision": review.get("context_revision", 0) if review else None,
                   "pending_corrections": corrections, "pending_issues": pending}
        return {"draft_id": draft_id, "review_id": review_id, "status": status, "changes": changes}

    def select_delivery(self, draft_id, review_id):
        delivery = self.delivery(draft_id, review_id)
        with self.store.connect() as db:
            for key, value in (("delivery", delivery), ("report_status", delivery["status"])):
                db.execute("INSERT OR REPLACE INTO state VALUES (?, ?)", (key, encode(value)))
        return delivery

    def status(self):
        delivery = self.store.get("delivery")
        if delivery:
            delivery = self.delivery(delivery["draft_id"], delivery["review_id"])
        status = self.store.get("report_status", "ready")
        if status in {"reviewed_draft", "unreviewed_draft", "changes_required", "needs_human", "system_error", "needs_attention"} and delivery:
            from .execution_progress import protected
            if not (status=='needs_attention' and protected(self)):
                status = delivery["status"]
        tasks = self.tasks()
        impact = self.impact()
        stale = set(impact["stale_result_ids"])
        superseded = set(impact["superseded_result_ids"])
        affected_tasks = set(impact["affected_task_ids"])
        results = [{**r, "stale": r["id"] in stale, "superseded": r["id"] in superseded,
                    "needs_assessment": r["id"] in stale - superseded,
                    "current": r["id"] not in stale | superseded, "reusable": r["id"] not in stale | superseded,
                    "status": "superseded" if r["id"] in superseded else "needs_assessment" if r["id"] in stale else "current"}
                   for r in self.results()]
        tasks = [{**t, "affected": t["id"] in affected_tasks,
                  "stale": t["id"] in affected_tasks, "reusable": bool(t.get("result_id")) and t["id"] not in affected_tasks}
                 for t in tasks]
        task_error = next((t["error"] for t in reversed(tasks) if t.get("error")), None)
        return {"goal": self.store.manifest["goal"], "name": self.store.manifest.get("name") or self.store.root.name, "status": status,
                "activity": self.store.get("report_activity", ""), "last_error": self.store.get("report_error") or task_error,
                "tasks": tasks, "results": results, "corrections": legacy.get_corrections(self.store, []),
                "sources": self.store.source_catalog(), "impact": impact,
                "source_changes": legacy.get_source_changes(self.store, []),
                "result_impact_assessments": legacy.get_result_impact_assessments(self.store, {}),
                "issues": legacy.get_report_issues(self.store, []), "delivery": delivery,
                "feedback": self.store.get("feedback", [])}
