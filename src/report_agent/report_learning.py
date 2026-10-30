"""Normal-runtime rollouts and artifact observations for host-owned learning.

This evaluator never writes report content, chooses agent tools, or publishes a
policy. All rollouts are fresh isolated workspaces. Models choose their own work
from the ordinary goal, through the existing DeepAgents/tools/ownership path.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import sqlite3
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from .store import Store, digest, encode

EVALUATOR_VERSION = "report-word-issues-v1"
COMPONENT = "customer_strategy"
CHECKS = ("source_fidelity", "source_attribution", "report_voice", "issues_only",
          "issue_coverage_and_pointers", "coverage_note_provenance")


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporary, path)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def validate_candidate(candidate):
    if (not isinstance(candidate, dict) or set(candidate) != {COMPONENT}
            or not isinstance(candidate[COMPONENT], str)
            or not 1 <= len(candidate[COMPONENT].strip()) <= 30000):
        raise ValueError("INVALID_REPORT_GUIDANCE_COMPONENT")
    return candidate


def validate_splits(splits):
    ids, inputs = set(), set()
    if set(splits) != {"train", "validation", "holdout"}:
        raise ValueError("THREE_DATA_SPLITS_REQUIRED")
    for rows in splits.values():
        if not rows:
            raise ValueError("NONEMPTY_DATA_SPLITS_REQUIRED")
        for row in rows:
            key = digest({"goal": row["goal"], "sources": row["sources"]})
            if row["case_id"] in ids or key in inputs:
                raise ValueError("EVALUATION_SPLIT_LEAKAGE")
            ids.add(row["case_id"])
            inputs.add(key)
    # Identity checks cannot establish semantic independence; record that limit.


def prepare_rollout(root, case, candidate, seed, library_root):
    """Copy verified bytes and use the ordinary scoped library release API.

    The candidate edits strategy only. Customer, kind, applicability/requirements,
    title, feedback lineage and permissions cannot be optimized.
    """
    from .workspace import Workspace
    from .learning import LearningLibrary, LearningScope, guidance_context
    validate_candidate(candidate)
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    ws = Workspace(Store(root / "case"))
    sources = []
    for source in case["sources"]:
        selected = dict(source)
        original = Path(selected.pop("byte_path"))
        data = original.read_bytes()
        if hashlib.sha256(data).hexdigest() != source["sha256"]:
            raise ValueError("SOURCE_BYTES_CHANGED")
        destination = ws.store.root / source["copied_path"]
        if not destination.resolve().is_relative_to((ws.store.root / "sources").resolve()):
            raise ValueError("SOURCE_COPY_OUTSIDE_WORKSPACE")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        sources.append(selected)
    manifest = {"goal": case["goal"], "sources": sources,
                "content_contract": "hierarchical-review-v1", "context_policy": "stateful-tools-v1",
                "review_entrypoint": "delegated-reviewer-v1", "review_execution_mode": "native-reviewer-v2",
                "presentation_references": [], "scope_instruction": case.get("scope_instruction")}
    ws.store.initialize(manifest)
    ws.store.set("context_policy", "stateful-tools-v1")
    ws.store.set("knowledge_enabled", False)
    ws.store.set("content_revision_limit", 1)
    trial = root / "library"
    trial.mkdir()
    with sqlite3.connect(Path(library_root) / "state.db") as src, sqlite3.connect(trial / "state.db") as dst:
        src.backup(dst)
    lib = LearningLibrary(trial)
    scope = LearningScope(seed["customer"], str(ws.store.root))
    if seed["kind"] != "customer_preference" or seed["project"]:
        raise ValueError("SCOPED_CUSTOMER_PREFERENCE_REQUIRED")
    entry = seed
    if candidate[COMPONENT] != seed["strategy"]:
        with lib.store.connect() as db:
            feedback = [json.loads(r[0]) for r in db.execute(
                "SELECT data FROM learning_feedback WHERE id IN (" +
                ",".join("?" for _ in seed["feedback_ids"]) + ")", seed["feedback_ids"])]
        projects = {f["project"] for f in feedback}
        if len(projects) != 1:
            raise ValueError("AMBIGUOUS_CANDIDATE_FEEDBACK_SCOPE")
        origin_scope = LearningScope(seed["customer"], projects.pop())
        head = max(r["version"] for r in lib.list_versions(scope) if r["id"] == seed["id"])
        entry = lib.propose(origin_scope, seed["feedback_ids"], seed["kind"], seed["title"],
            candidate[COMPONENT], seed["conditions"], "GEPA trial; evaluation pending; no publication.",
            experience_id=seed["id"], expected_version=head)
    lib.release(scope, entry["id"], entry["version"], "Isolated GEPA evaluation only.")
    ws.store.set("learning_config", {"library_path": str(trial.resolve()), "customer_id": seed["customer"]})
    delivered = next(r for r in guidance_context(ws)["customer_preferences"] if r["id"] == seed["id"])
    if delivered["strategy"] != candidate[COMPONENT] or delivered["conditions"] != seed["conditions"]:
        raise ValueError("GUIDANCE_DELIVERY_MISMATCH")
    ws.store.set("learning_evaluation", {"case_id": case["case_id"], "candidate_digest": digest(candidate),
        "entry_ref": {"id": entry["id"], "version": entry["version"]}, "evaluator": EVALUATOR_VERSION})
    save_json(root / "input.json", {"case": case, "candidate": candidate, "seed_ref":
        {"id": seed["id"], "version": seed["version"]}, "fixed_conditions_digest": digest(seed["conditions"])})
    return ws


def artifact_observation(ws):
    """Read exact export bytes, match Word/XLSX snapshot and capture producer nodes."""
    from .content_store import ContentStore
    from .content_export import read_export
    from .hierarchical_tools import actor_for
    cs = ContentStore(ws.store)
    objects = cs.list_objects()
    words = [o for o in objects if o["ref"]["type"] == "ExportArtifact"
             and o["payload"]["file_ref"].endswith(".docx")]
    excels = [o for o in objects if o["ref"]["type"] == "ExportArtifact"
              and o["payload"]["file_ref"].endswith(".xlsx")]
    pairs = [(w, x) for w in words for x in excels
             if w["payload"]["snapshot_ref"] == x["payload"]["snapshot_ref"]]
    result = {"complete": bool(pairs), "objects": objects, "exports": []}
    if not pairs:
        return result
    word, excel = pairs[-1]
    snapshot = cs.read(word["payload"]["snapshot_ref"])
    for obj in (word, excel):
        result["exports"].append({"ref": obj["ref"], "payload": obj["payload"],
            "actual_read": read_export(cs, actor_for("coordinator"), obj["ref"])})
    result["snapshot"] = snapshot
    result["word_workbook_linked"] = excel["payload"].get("export_config", {}).get("report_export_ref") == word["ref"]
    return result


def call_ledger(events, purpose, candidate=None):
    """No invented usage for missing responses; keep action-based classifications."""
    responses = {e["data"]["run_id"]: e for e in events if e["kind"] == "deep_model_response"}
    observed = {}
    for e in events:
        if e['kind'] == 'deep_model_request':
            for batch in e['data']['messages']:
                for message in batch:
                    if message.get('type') == 'tool':
                        observed[message.get('tool_call_id')] = message
    rows = []
    for e in events:
        if e["kind"] != "deep_model_request":
            continue
        req = e["data"]
        response = responses.get(req["run_id"])
        calls = response["data"]["generations"][0][0].get("tool_calls", []) if response else []
        classification, reason = "unassessed", "Inspect action results and changed artifacts; receiving a response is insufficient."
        if purpose != "report_rollout":
            classification, reason = "necessary_evaluation", purpose
        elif not response:
            classification, reason = "unknown_outcome", "No recorded model response; never retry automatically."
        elif calls and all(c['name'] in {'ls', 'glob', 'grep', 'read_file'} for c in calls):
            returns = [observed.get(c['id']) for c in calls]
            if all(r and r.get('content') in ('[]', 'No files found', 'No matches found') for r in returns):
                classification, reason = 'unproductive_avoidable', 'Virtual filesystem probes returned no files/matches; no project evidence or artifact gained.'
        rows.append({"run_id": req["run_id"], "sequence": e["sequence"], "role": req["role"],
            "purpose": purpose, "chosen_tools": calls, "received_response": bool(response),
            "usage": response["data"].get("usage") if response else None,
            "candidate_visible": candidate_visible(req["messages"], candidate) if candidate else None,
            "classification": classification, "rationale": reason})
    return rows


def candidate_visible(value, candidate):
    if isinstance(value, str):
        text = candidate[COMPONENT]
        return text in value or encode(text)[1:-1] in value
    if isinstance(value, dict):
        return any(candidate_visible(v, candidate) for v in value.values())
    if isinstance(value, list):
        return any(candidate_visible(v, candidate) for v in value)
    return False


def execution_trace(events, candidate):
    """Deduplicate real observed tool returns; retain calls and effective-input hashes.

    Full inputs remain in events.json. Reflection receives this trace, actual
    artifacts and selected sources, rather than treating a final summary as proof.
    """
    observations, seen = [], set()
    for e in events:
        if e["kind"] == "deep_model_request":
            for batch in e["data"]["messages"]:
                for message in batch:
                    if message.get("type") == "tool":
                        key = digest(message)
                        if key not in seen:
                            seen.add(key)
                            observations.append(message)
    return {"calls": [{**r, "effective_input_digest": digest(next(e["data"]["messages"]
                    for e in events if e["kind"] == "deep_model_request" and e["data"]["run_id"] == r["run_id"]))}
                for r in call_ledger(events, "report_rollout", candidate)],
            "observed_tool_returns": observations,
            "full_effective_inputs": "events.json", "tool_returns_may_be_missing_after_final_call": True}


async def native_rollout(ws, root, *, maximum_requests, seconds):
    from .model_invocation import MODEL_REQUEST_DEADLINE_SECONDS
    from .deep_runtime import project_agent, project_view
    from .request_budget import RequestBudget, request_budget
    from .model_config import bind_role_services
    from .deep_models import configured_model, LocalAudit, strict_wire_audit, error_data
    from .learning import binding
    from .acceptance import bind_mode
    from .source_search import bind_source_search
    from .review_context import bind_context_experiment
    models = []
    bind_role_services(ws.store)
    def factory(role):
        model = configured_model(ws.store, role)
        model.callbacks = [*(model.callbacks or []), LocalAudit(ws.store, role)]
        model.http_async_client.event_hooks["request"].append(strict_wire_audit(ws.store, role))
        models.append(model)
        return model
    budget = RequestBudget(maximum_requests)
    root = Path(root)
    start = time.monotonic()
    deadline = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    record = {"state": "running", "started_at": datetime.now(timezone.utc).isoformat(),
        "pid": os.getpid(), "max_http_attempts": maximum_requests, "whole_case_seconds": seconds,
        "deadline_utc": deadline.isoformat(), "logical_deadline_seconds": MODEL_REQUEST_DEADLINE_SECONDS,
        "automatic_retry": False, "original_revisions": False, "canonical_release": False}
    save_json(root / "started.json", record)
    whole_window = asyncio.timeout(seconds)
    with ws.store.run_lock():
        try:
            bind_source_search(ws)
            bind_context_experiment(ws.store)
            ws.initialize()
            bind_mode(ws)
            ws.store.set("report_status", "running")
            with request_budget(budget):
                async with whole_window:
                    async with project_agent(ws, model_factory=factory) as agent:
                        config = {"configurable": {"thread_id": "report"}, "recursion_limit": 10000}
                        payload = {"messages": [("user", encode({**project_view(ws), "host_execution_limits": {
                            "deadline_utc": deadline.isoformat(), "max_http_attempts": maximum_requests}}))]}
                        while True:
                            await agent.ainvoke(payload, config, interrupt_after=["tools"], durability="sync")
                            state = await agent.aget_state(config)
                            observation = artifact_observation(ws)
                            save_json(root / "progress.json", {"at": datetime.now(timezone.utc).isoformat(),
                                "http_attempts": budget.count, "elapsed_seconds": time.monotonic() - start,
                                "artifacts_complete": observation["complete"], "native_next": list(state.next)})
                            if observation["complete"] and observation["word_workbook_linked"]:
                                record.update(state="artifact_boundary_reached", native_continuation_pending=bool(state.next))
                                break
                            if state.interrupts:
                                record.update(state="human_decision_pending", interrupts=[i.value for i in state.interrupts])
                                break
                            if not state.next:
                                record["state"] = "native_terminal_without_required_artifacts"
                                break
                            payload = None
        except BaseException as exc:
            record.update(state="terminal_incomplete", error=error_data(exc))
            record['termination_boundary'] = ('whole_case_window' if whole_window.expired()
                else 'runtime_or_logical_request_failure')
        finally:
            try:
                observation = artifact_observation(ws)
            except Exception as exc:
                observation = {"complete": False, "error": error_data(exc), "objects": []}
            events = ws.store.events()
            save_json(root / "events.json", events)
            save_json(root / "artifacts.json", observation)
            candidate = read_json(root / "input.json")["candidate"]
            ledger = call_ledger(events, "report_rollout", candidate)
            save_json(root / "call-ledger.json", ledger)
            save_json(root / "execution-trace.json", execution_trace(events, candidate))
            recorded = [r["usage"] for r in ledger if r["usage"]]
            record.update(elapsed_seconds=time.monotonic() - start, http_attempts=budget.count,
                recorded_tokens=sum(u.get("total_tokens", 0) for u in recorded),
                cached_input_already_included=sum((u.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0 for u in recorded),
                received_responses=sum(r["received_response"] for r in ledger), logical_requests=len(ledger),
                artifacts_complete=observation["complete"], semantic_validation=False)
            lib, scope = binding(ws)
            entry = ws.store.get("learning_evaluation")["entry_ref"]
            lib.release(scope, entry["id"], None, "Terminal isolated evaluation; no publication.")
            record["trial_activation_withdrawn"] = True
            ws.store.set("report_status", "learning_evaluation_terminal")
            save_json(root / "result.json", record)
            for model in models:
                await model.root_async_client.close()
                model.root_client.close()
    return record


def score_judgment(judgment):
    if set(judgment.get("checks", {})) != set(CHECKS):
        raise ValueError("INCOMPLETE_SEMANTIC_JUDGMENT")
    passed = 0
    for item in judgment["checks"].values():
        if (set(item) != {"status", "evidence", "reason"} or item["status"] not in {"pass", "fail", "unknown"}
                or not isinstance(item["evidence"], str) or not item["evidence"].strip()
                or not isinstance(item["reason"], str) or not item["reason"].strip()):
            raise ValueError("UNGROUNDED_SEMANTIC_JUDGMENT")
        passed += item["status"] == "pass"
    return passed / len(CHECKS)
