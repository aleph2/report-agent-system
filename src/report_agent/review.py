"""Thin evidence and persistence adapter for DeepAgents' native rubric loop."""
from pathlib import Path
from inspect import iscoroutinefunction
from typing import NotRequired

from deepagents import RubricMiddleware
from deepagents.middleware.rubric import GRADER_SYSTEM_PROMPT, RubricState
from langchain.agents import AgentState
from langchain_core.messages import HumanMessage
from langchain_core.tools import StructuredTool

from .store import digest, encode


class ReviewState(RubricState):
    rubric_terminal_handoff: NotRequired[bool]


class FeedbackRubric(RubricMiddleware):
    """Native grading, with one observable handoff on non-passing termination."""

    state_schema = ReviewState

    def __init__(self, *, target_observation=None, **kwargs):
        super().__init__(**kwargs)
        self.target_observation = target_observation or (lambda: {})

    async def abefore_agent(self, state, runtime):
        if state.get("rubric_terminal_handoff"):
            return None  # Resume the pending handoff without resetting its budget.
        return await super().abefore_agent(state, runtime)

    async def aafter_agent(self, state, runtime):
        if state.get("rubric_terminal_handoff"):
            return {"rubric_terminal_handoff": False}
        update = await super().aafter_agent(state, runtime)
        if not update or update.get("_rubric_status") not in {
                "grader_error", "failed", "max_iterations_reached"}:
            return update
        evaluation = update["_rubric_evaluations"][-1]
        status = evaluation["result"]
        explanation = "The grader could not execute; report correctness is unknown." if status == "grader_error" else evaluation["explanation"]
        feedback = {"source": "native_rubric_terminal_feedback", "status": status,
                    "target": self.target_observation(),
                    "explanation": explanation,
                    "criteria": [] if status == "grader_error" else evaluation["criteria"],
                    "handling": "This grading attempt has ended without approval. "
                    "Explain the actual limitation and preserve or improve the usable draft. "
                    "Your response does not change the verdict; grading will not automatically "
                    "restart in this invocation. Do not claim a technical grader error proves "
                    "a report defect or that a revision is already approved."}
        return {**update, "rubric_terminal_handoff": True,
                "messages": [HumanMessage(content=encode(feedback), name="rubric_terminal_feedback")],
                "jump_to": "model"}


def load_rules():
    return (Path(__file__).parent / "rules" / "report-review.md").read_text(encoding="utf-8")


def reviewer_prompt():
    """Specialist purpose plus the installed framework's full grading contract."""
    role = (Path(__file__).parent / "rules" / "report-reviewer.md").read_text(encoding="utf-8")
    return role + "\n\n# Native grading contract\n\n" + GRADER_SYSTEM_PROMPT


def export_configuration(workspace):
    return digest({"options": workspace.store.manifest.get("export", {}),
                   "exporter": (Path(__file__).parent / "exporting.py").read_text(encoding="utf-8")})


def observation_version(workspace, draft_id):
    changes = dict(workspace.delivery(draft_id).get("changes", {}))
    changes.pop("context_revision", None)
    changes.pop("review_context_revision", None)
    return digest({"changes": changes, "human_inputs": workspace.store.get("report_issues", [])})


def native_review(workspace, model, tools, rules, middleware=()):
    context = {}
    system_prompt = reviewer_prompt()

    def read_review_export(offset: int = 0, limit: int = 30) -> dict:
        """Read the exact DOCX text/structure snapshot bound to this grading attempt.

        This is not visual inspection. Follow next_offset to obtain remaining text.
        """
        from .report_preview import read_preview
        if not context.get("draft_id"):
            return {"available": False, "reason": "No report has been selected."}
        return read_preview(workspace, context["draft_id"], offset, limit,
                            preview_version=context["preview_version"])

    def prepare(messages):
        from .report_preview import preview_saved_report
        selected = workspace.store.get("delivery") or {}
        draft_id = selected.get("draft_id")
        context.clear()
        context.update(draft_id=draft_id, rubric_hash=digest(rules),
                       reviewer_prompt_hash=digest(system_prompt),
                       export_configuration_hash=export_configuration(workspace))
        if draft_id:
            draft = workspace.result(draft_id)
            context["observation_version"] = observation_version(workspace, draft_id)
            previous = [target for target in workspace.store.get("rubric_targets", {}).values()
                        if all(target.get(k) == v for k, v in context.items())]
            if previous:
                context.update(previous[-1])
            else:
                preview = preview_saved_report(workspace, draft_id)
                context.update(draft_body_sha256=preview["draft_body_sha256"],
                               preview_version=preview["preview_version"],
                               docx_sha256=preview["docx"]["sha256"], title=draft["title"])
        # The native grader truncates transcript excerpts; this small final observation
        # identifies the exact artifact being assessed.
        return [*messages, HumanMessage(content=encode({"application_review_target": context,
                "observation": "This is the selected saved report and pinned export for assessment. "
                "No selected draft means no report is available for acceptance. "
                "Project scope, changes, issues and corrections are available in the current project state."}))]

    def bind_target(state, iteration):
        key = state["_current_grading_run_id"] + ":" + str(iteration)
        targets = workspace.store.get("rubric_targets", {})
        if key in targets and targets[key] != context:
            raise RuntimeError("RUBRIC_TARGET_IDENTITY_CHANGED")
        targets.setdefault(key, dict(context))
        workspace.store.set("rubric_targets", targets)
        workspace.store.event("rubric_review_started", {"key": key, **context})
        return {}

    def observed(evaluation):
        # Observability only. Final projection is reconciled from native checkpoint
        # state, because DeepAgents intentionally suppresses callback failures.
        workspace.store.event("rubric_review_observed", {
            "grading_run_id": evaluation["grading_run_id"],
            "iteration": evaluation["iteration"], "result": evaluation["result"]})

    grader_tools = [StructuredTool.from_function(coroutine=t) if iscoroutinefunction(t)
                    else StructuredTool.from_function(t) for t in [*tools, read_review_export]]
    return FeedbackRubric(model=model, tools=grader_tools, system_prompt=system_prompt,
                            grader_middleware=list(middleware),
                            target_observation=lambda: dict(context),
                            prepare_messages_for_grader=prepare, build_grader_state=bind_target,
                            grader_state_schema=AgentState,
                            max_iterations=3, on_evaluation=observed)


def reconcile_review(workspace, native_state):
    targets = workspace.store.get("rubric_targets", {})
    records = workspace.store.get("rubric_reviews", [])
    known = {(r["grading_run_id"], r["iteration"]) for r in records}
    for evaluation in native_state.get("_rubric_evaluations", []):
        identity = evaluation["grading_run_id"], evaluation["iteration"]
        if identity in known:
            continue
        target = targets.get(identity[0] + ":" + str(identity[1]), {})
        record = {**evaluation, "target": target, "origin": "native_rubric_checkpoint"}
        # Never expose provider exception text carried by grader_error.
        if record["result"] == "grader_error":
            record["explanation"] = "RUBRIC_GRADER_ERROR"
            record["criteria"] = []
        records.append(record)
        known.add(identity)
    workspace.store.set("rubric_reviews", records)
    workspace.store.set("rubric_status", native_state.get("_rubric_status"))


def review_delivery(workspace, draft_id):
    """Project a verdict only onto its exact immutable draft and rule version."""
    from hashlib import sha256
    draft = workspace.result(draft_id)
    body_hash = sha256(draft["body"].encode("utf-8")).hexdigest()
    rule_hash = workspace.store.get("active_rubric_hash")
    prompt_hash = workspace.store.get("active_reviewer_prompt_hash")
    candidates = [r for r in workspace.store.get("rubric_reviews", [])
                  if r["target"].get("draft_id") == draft_id
                  and r["target"].get("draft_body_sha256") == body_hash
                  and r["target"].get("rubric_hash") == rule_hash
                  and (not prompt_hash or r["target"].get("reviewer_prompt_hash") == prompt_hash)
                  and r["target"].get("export_configuration_hash") == export_configuration(workspace)]
    review = candidates[-1] if candidates else None
    status = "unreviewed_draft"
    if review:
        verdict = review["result"]
        status = "reviewed_draft" if verdict == "satisfied" and not review.get("unverified") else (
            "system_error" if verdict == "grader_error" else "changes_required")
        if status == "reviewed_draft" and review["target"].get("observation_version") != observation_version(workspace, draft_id):
            status = "needs_attention"  # New feedback to consider, not a verdict that content is wrong.
    return {"draft_id": draft_id, "review_id": "", "status": status, "rubric_review": review,
            "review_scope": "Exact saved text and recorded preview snapshot; a fresh export is a new file."}
