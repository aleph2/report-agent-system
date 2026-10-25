"""Explicitly invoked background reflection; no provider calls at import or read."""
from pathlib import Path
from typing import Literal
import json

from .learning import binding
from .errors import ActionRejected
from .content_models import Ref
from .store import encode, digest


def _page(value, offset, limit):
    if offset < 0 or not 1 <= limit <= 8000:
        raise ActionRejected("INVALID_LEARNING_PAGE")
    text = value if isinstance(value, str) else encode(value)
    end = min(offset + limit, len(text))
    return {"text": text[offset:end], "offset": offset, "total_chars": len(text),
            "next_offset": end if end < len(text) else None, "digest": digest(value)}


def _assignment_page(assignment, offset=0):
    if not assignment:
        return None
    ids = assignment["feedback_ids"]
    return {"id": assignment["id"], "feedback_ids": ids[offset:offset + 6],
            "total": len(ids), "next_offset": offset + 6 if offset + 6 < len(ids) else None}


def optimizer_tools(workspace, experiment_runner=None, text_model=None):
    from .content_store import ContentStore
    library, scope = binding(workspace)

    def read_learning_feedback(feedback_id: str = "", field: Literal["correction", "before", "evidence", "observation"] = "correction",
                               offset: int = 0, limit: int = 6000) -> dict:
        """Without id: bounded feedback index (offset in records, six per page), current assignment first.
        With exact id: read original field text (offset/limit in characters), with digest and
        next_offset. All evidence remains accessible; index previews are not the complete feedback.
        Runtime observations are typed execution facts, not report corrections or proven learning.
        For their facts use field=observation (the legacy default also selects it).
        """
        if offset < 0 or not 1 <= limit <= 8000:
            raise ActionRejected("INVALID_LEARNING_PAGE")
        items = library.feedback_items(scope)
        assignment = workspace.store.get("learning_active_feedback")
        if feedback_id:
            item = next((x for x in items if x["id"] == feedback_id), None)
            if item is None:
                raise ActionRejected("FEEDBACK_OUTSIDE_PROJECT")
            if item.get('kind')=='runtime_observation':
                actual='observation' if field=='correction' else field
                if actual not in {'observation','before','evidence'}:raise ActionRejected('INVALID_LEARNING_FIELD')
                return {'feedback_id':feedback_id,'kind':'runtime_observation','field':actual,
                    **_page(item[actual],offset,limit),'semantic_progress_verified':False}
            if field not in {"correction", "before", "evidence"}:
                raise ActionRejected("INVALID_LEARNING_FIELD")
            return {"feedback_id": feedback_id, "field": field, **_page(item[field], offset, limit)}
        assigned = set((assignment or {}).get("feedback_ids", []))
        items.sort(key=lambda x: x["id"] not in assigned)
        return {"pending_assignment": _assignment_page(assignment, offset), "feedback": [
            {'id':x['id'],'assigned':x['id'] in assigned,'kind':'runtime_observation',
             'observation_preview':encode(x['observation'])[:400],
             'fields':{k:{'total_chars':len(encode(x[k])),'digest':digest(x[k])} for k in ('observation','before','evidence')},
             'semantic_progress_verified':False} if x.get('kind')=='runtime_observation' else
            {"id": x["id"], "assigned": x["id"] in assigned,
             "correction_preview": x["correction"][:400],
             "fields": {k: {"total_chars": len(x[k] if isinstance(x[k], str) else encode(x[k])),
                             "digest": digest(x[k])} for k in ("correction", "before", "evidence")}}
            for x in items[offset:offset + 6]], "total": len(items),
            "next_offset": offset + 6 if offset + 6 < len(items) else None}

    def read_learning_evidence(ref: Ref, offset: int = 0, limit: int = 6000) -> dict:
        """Read immutable project object JSON in character pages; use exact full ref, not a prefix.
        next_offset means more original text is available. Never modify source or report.
        """
        obj = ContentStore(workspace.store).read(ref)
        return {"ref": obj["ref"], **_page(obj, offset, limit)}

    def read_experience_candidates(experience_id: str = "", version: int = 0,
                                   offset: int = 0, limit: int = 6000) -> dict:
        """Without id: six-item index (record offset). With id/version: original JSON pages
        (character offset/limit). Use exact versions. Active state/use counts are not quality.
        """
        if offset < 0 or not 1 <= limit <= 8000:
            raise ActionRejected("INVALID_LEARNING_PAGE")
        items = library.list_versions(scope)
        if experience_id:
            item = next((x for x in items if x["id"] == experience_id and x["version"] == version), None)
            if item is None:
                raise ActionRejected("EXPERIENCE_NOT_AVAILABLE")
            return {"id": experience_id, "version": version, **_page(item, offset, limit)}
        return {"items": [{k: (x[k][:256] if k == "title" else x[k])
                           for k in ("id", "version", "kind", "title", "active")}
                          for x in items[offset:offset + 6]], "total": len(items),
                "next_offset": offset + 6 if offset + 6 < len(items) else None}

    def record_feedback_disposition(feedback_id: str,
                                    outcome: Literal["candidate", "no_change", "insufficient_evidence"],
                                    rationale: str, experience_id: str = "", experience_version: int = 0) -> dict:
        """Record your handling of one currently assigned feedback item, with rationale.
        candidate requires an exact saved candidate version linked to this feedback.
        no_change/insufficient_evidence are valid outcomes without a new candidate. This is
        an agent declaration, not verification of understanding, strategy quality or release.
        """
        assignment = workspace.store.get("learning_active_feedback") or {}
        job = workspace.store.get("learning_job") or {}
        if feedback_id not in assignment.get("feedback_ids", []) or job.get("state") != "running":
            raise ActionRejected("FEEDBACK_NOT_ASSIGNED")
        if outcome not in {"candidate", "no_change", "insufficient_evidence"} or not rationale.strip():
            raise ActionRejected("FEEDBACK_DISPOSITION_REQUIRED")
        result = {"feedback_id": feedback_id, "outcome": outcome, "rationale": rationale,
                  "claim_id": assignment["id"], "quality_verified": False}
        if outcome == "candidate":
            candidate = next((x for x in library.list_versions(scope)
                              if x["id"] == experience_id and x["version"] == experience_version), None)
            if candidate is None or feedback_id not in candidate["feedback_ids"]:
                raise ActionRejected("CANDIDATE_FEEDBACK_MISMATCH")
            result["candidate"] = {"id": experience_id, "version": experience_version}
        elif experience_id or experience_version:
            raise ActionRejected("NON_CANDIDATE_DISPOSITION_HAS_CANDIDATE")
        # ToolNode can execute multiple synchronous calls concurrently. Merge under
        # one SQLite write transaction so successful receipts cannot erase one another.
        with workspace.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = json.loads(db.execute("SELECT value FROM state WHERE key=?", ("learning_job",)).fetchone()[0])
            if current.get("id") != job["id"] or current.get("state") != "running":
                raise ActionRejected("LEARNING_JOB_CHANGED")
            current.setdefault("feedback_dispositions", {})[feedback_id] = result
            db.execute("UPDATE state SET value=? WHERE key=?", (encode(current), "learning_job"))
        workspace.store.event("learning_feedback_disposition", result)
        return result

    def propose_experience(feedback_ids: list[str], kind: Literal["project_fact", "customer_preference", "general_skill"], title: str, strategy: str,
                           conditions: str, verification: str,
                           experience_id: str | None = None, expected_version: int = 0, analysis_id: str = "") -> dict:
        """Save a scoped candidate, with source feedback and verification plan. Does not publish."""
        if kind == "project_fact":
            from .learning_text_work import adopt_project_fact
            adopt_project_fact(workspace, analysis_id, feedback_ids, title, strategy, conditions)
        return library.propose(scope, feedback_ids, kind, title, strategy, conditions,
                               verification, experience_id, expected_version)

    tools = [read_learning_feedback, read_learning_evidence, read_experience_candidates,
             propose_experience, record_feedback_disposition]
    if text_model is not None:
        from .learning_text_work import learning_analysis_tool
        tools.append(learning_analysis_tool(workspace, text_model))
    if experiment_runner is not None:
        async def optimize_saved_guidance(experience_id: str, version: int) -> dict:
            """Use the host-authorized GEPA execution-trace/report evaluator on a saved
            candidate. Choose this when measured guidance improvement is useful.
            Dataset, metric, runtime, request limits and publication permissions are
            host-bound; this tool cannot replace them. No automatic job retry.
            """
            from .learning_worker import _optimize_saved_candidate_locked
            return await _optimize_saved_candidate_locked(workspace, experience_id, version, experiment_runner)
        tools.append(optimize_saved_guidance)
    return tools


def build_optimizer(workspace, model, experiment_runner=None, *, text_model=None):
    from deepagents import create_deep_agent
    from deepagents.backends import StateBackend
    from deepagents import register_harness_profile, HarnessProfile, GeneralPurposeSubagentProfile
    from langchain.agents.middleware import AgentMiddleware
    from langchain_core.messages import ToolMessage

    if not binding(workspace):
        raise ActionRejected("LEARNING_NOT_CONFIGURED")

    registered_tools = optimizer_tools(workspace, experiment_runner, text_model if text_model is not None else model)
    class CandidateBoundary(AgentMiddleware):
        async def awrap_model_call(self, request, handler):
            # This worker's evidence lives in immutable project objects, not the
            # harness's empty virtual filesystem. Expose only its actual capabilities.
            names = {tool.__name__ for tool in registered_tools}
            return await handler(request.override(tools=[tool for tool in request.tools
                if getattr(tool, "name", None) in names]))

        async def awrap_tool_call(self, request, handler):
            try:
                return await handler(request)
            except (ValueError, PermissionError) as exc:
                return ToolMessage(content=str(exc), tool_call_id=request.tool_call["id"], status="error")

    register_harness_profile("openai", HarnessProfile(
        general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False)))
    from .prompt_sources import load_prompt, record_runtime_version
    runtime_version_ref = record_runtime_version(workspace.store)
    from .prompt_provenance import AgentPromptBoundary
    prompt = load_prompt('experience-optimizer')
    return create_deep_agent(model=model, tools=registered_tools, system_prompt=prompt,
                             subagents=[], backend=StateBackend(), middleware=[CandidateBoundary(),
                                AgentPromptBoundary(workspace,'experience_optimizer',source='experience-optimizer')],
                             name="experience_optimizer").with_config(
                                metadata={'report_runtime_version_ref':runtime_version_ref})


async def run_optimizer(workspace, model, *, max_steps=40):
    """Explicit manual reflection; host must supply an authorized model."""
    if not 1 <= max_steps <= 100:
        raise ValueError("INVALID_LEARNING_STEP_LIMIT")
    with workspace.store.run_lock():
        return await _run_optimizer_locked(workspace, model, max_steps=max_steps)


async def _run_optimizer_locked(workspace, model, *, max_steps=40, experiment_runner=None):
    from uuid import uuid4
    job_id = str(uuid4())
    library, scope = binding(workspace) or (None, None)
    if library is None:
        raise ActionRejected("LEARNING_NOT_CONFIGURED")
    before = {(x["id"], x["version"]) for x in library.list_versions(scope)}
    job = {"id": job_id, "state": "running", "quality_verified": False,
           "gepa_capability_available": experiment_runner is not None}
    workspace.store.set("learning_job", job)
    workspace.store.event("learning_started", {"max_steps": max_steps})
    assignment = workspace.store.get("learning_active_feedback")
    task = ("Reduce repeated report errors and user revision effort using the saved feedback and evidence. "
            "Choose useful investigations and candidate improvements, or explain why evidence is insufficient. "
            "Return saved candidate identities and remaining uncertainties.")
    if experiment_runner is not None:
        task += (" The host-bound optimize_saved_guidance capability uses GEPA with actual execution traces, "
                 "report artifacts and fixed evaluation cases. Choose it when measured improvement is useful. "
                 "If you don't use it, explain the reason in your final response; ordinary reflection is not GEPA optimization.")
    host_limits = workspace.store.get("learning_execution_limits")
    if host_limits:
        limits = {key: host_limits[key] for key in (
            "max_http_attempts", "whole_job_seconds", "deadline_utc",
            "logical_request_deadline_seconds", "graph_step_limit") if key in host_limits}
        task += (" Host resource limits for this job: " + encode(limits) + ". "
                 "HTTP attempts include SDK retries; graph steps are not model-call counts. "
                 "Use sufficient evidence for the assigned outcome and leave room to save its "
                 "disposition and return the result. These resource limits do not prescribe "
                 "your investigation route or expand permissions.")
    if assignment:
        task += (" Your current assignment (first page; total and continuation are explicit) is: "
                 + encode(_assignment_page(assignment)) + ". The feedback index exposes remaining assignment pages. "
                 "Historical feedback is context, not a replacement "
                 "for this assignment. Record your disposition for each assigned item using "
                 "record_feedback_disposition. A justified no-change or insufficient-evidence outcome is valid. "
                 "The read tools expose original text in pages with next_offset; previews are incomplete.")
    try:
        result = await build_optimizer(workspace, model, experiment_runner).ainvoke(
            {"messages": [{"role": "user", "content": task}]},
            config={"recursion_limit": max_steps})
        if any(getattr(message, "invalid_tool_calls", None) for message in result.get("messages", [])):
            raise ActionRejected("LEARNING_INVALID_TOOL_CALLS")
        last = result.get("messages", [])[-1] if result.get("messages") else None
        if last is None or getattr(last, 'response_metadata', {}).get('finish_reason') == 'length':
            raise ActionRejected("LEARNING_INCOMPLETE_RESPONSE")
        if not getattr(last, 'content', None):
            raise ActionRejected("LEARNING_EMPTY_RESPONSE")
        job = workspace.store.get("learning_job")
        if assignment and not set(assignment["feedback_ids"]) <= set(job.get("feedback_dispositions", {})):
            raise ActionRejected("LEARNING_FEEDBACK_UNACCOUNTED")
    except BaseException as exc:
        failed = {**workspace.store.get("learning_job"), "state": "failed", "error_type": type(exc).__name__}
        workspace.store.set("learning_job", failed)
        workspace.store.set("learning_job:" + job_id, failed)
        workspace.store.event("learning_failed", {"error_type": type(exc).__name__})
        raise
    candidates = [{"id": x["id"], "version": x["version"]} for x in library.list_versions(scope)
                  if (x["id"], x["version"]) not in before]
    summary = result["messages"][-1].content if result.get("messages") else ""
    completed = {**job, "state": "completed", "candidates": candidates, "summary": summary,
        "gepa_disposition": (workspace.store.get('guidance_experiment') or
            {"state": "not_used", "reason_source": "learner_final_response", "rationale": summary}) if experiment_runner is not None else
            {"state": "not_used", "reason": "No host-authorized GEPA evaluator/runtime/dataset was bound to this job; this was ordinary native reflection."}}
    workspace.store.set("learning_job", completed)
    workspace.store.set("learning_job:" + job_id, completed)
    workspace.store.event("learning_finished", {"quality_verified": False})
    return result


def evaluate_strategy_pair(baseline, candidate, cases, evaluator):
    """Evaluator is host-owned, not editable by optimizer. No automatic release."""
    import math
    if not cases or len({c["id"] for c in cases}) != len(cases):
        raise ValueError("UNIQUE_EVALUATION_CASES_REQUIRED")
    results = []
    for case in cases:
        old, new = evaluator(baseline, case), evaluator(candidate, case)
        for result in (old, new):
            if not math.isfinite(result["score"]) or not 0 <= result["score"] <= 1:
                raise ValueError("INVALID_EVALUATION_SCORE")
        results.append({"case_id": case["id"], "baseline": old, "candidate": new})
    return {"results": results, "regressions": [r["case_id"] for r in results
            if r["candidate"]["score"] < r["baseline"]["score"]], "automatic_release": False}


def optimize_with_gepa(student, trainset, valset, metric, reflection_model, *, max_metric_calls):
    """Optional DSPy adapter. Explicit call budget, injected models and host metric.

    Holdout evaluation and publication remain separate. This function must only be
    called by the host after model-cost authorization, not by report agent tools.
    """
    if not 1 <= max_metric_calls <= 1000 or not trainset or not valset:
        raise ValueError("BOUNDED_OPTIMIZATION_DATA_REQUIRED")
    train_ids, val_ids = [x["case_id"] for x in trainset], [x["case_id"] for x in valset]
    if (len(set(train_ids)) != len(train_ids) or len(set(val_ids)) != len(val_ids)
            or set(train_ids) & set(val_ids)):
        raise ValueError("OPTIMIZATION_CASE_SPLIT_INVALID")
    import dspy
    optimizer = dspy.GEPA(metric=metric, reflection_lm=reflection_model,
                          max_metric_calls=max_metric_calls, track_stats=True)
    return optimizer.compile(student=student, trainset=trainset, valset=valset)
