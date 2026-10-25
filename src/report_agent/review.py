"""Thin evidence and persistence adapter for DeepAgents' native rubric loop."""
from pathlib import Path
from inspect import iscoroutinefunction
from typing import Literal, NotRequired

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

    def __init__(self, *, target_observation=None, claim_evidence_contract=False, acceptance_workspace=None, **kwargs):
        super().__init__(**kwargs)
        self.target_observation = target_observation or (lambda: {})
        self.claim_evidence_contract = claim_evidence_contract
        self.acceptance_workspace = acceptance_workspace

    def _ensure_grader(self):
        if not self.claim_evidence_contract and self.acceptance_workspace is None:
            return super()._ensure_grader()
        if self._grader is None:
            # Thin construction hook for pinned DeepAgents0.7.19; keep its loop,
            # coverage validation and evaluation serialization unchanged.
            from deepagents._models import resolve_model
            from deepagents.middleware.rubric import RUBRIC_GRADER_MESSAGE_SOURCE
            from langchain.agents import create_agent
            if self.acceptance_workspace is not None:
                from .acceptance_review import GraderResponse
            else:
                from .review_contract import GraderResponse
            resolved_model = resolve_model(self._model)
            self._resolved_model = resolved_model
            self._grader = create_agent(
                model=resolved_model, system_prompt=self._system_prompt, tools=self._tools,
                middleware=self._grader_middleware, name=RUBRIC_GRADER_MESSAGE_SOURCE,
                response_format=GraderResponse, state_schema=self._grader_state_schema,
                context_schema=self._grader_context_schema)
        return self._grader

    def _extract_graded(self, result):
        if self.acceptance_workspace is not None and isinstance(result.get("structured_response"), dict):
            from .acceptance_review import GraderResponse
            return GraderResponse.model_validate(result["structured_response"])
        return super()._extract_graded(result)

    def _usability_correction(self, state, graded):
        if self.acceptance_workspace is not None and graded.result != "failed":
            expected = state.get("_rubric_criteria", [])
            actual = [c["name"] for c in graded.criteria]
            if actual != expected:
                return "Return exactly one outcome for each supplied criterion ID in order, without replacements, omissions or duplicates: " + encode(expected)
        return super()._usability_correction(state, graded)

    def _build_evaluation(self, graded, grading_run_id, iteration):
        result = super()._build_evaluation(graded, grading_run_id, iteration)
        if (self.acceptance_workspace is not None and graded.result != "failed"
                and [c["name"] for c in graded.criteria] != getattr(self, "_criterion_ids", [])):
            result["unverified"] = True
            result["result"] = "undetermined"
            result["explanation"] = ("The grader did not return the exact required criterion IDs after "
                                     "the native structural correction attempt. Acceptance remains "
                                     "undetermined; this is not evidence of a report defect. "
                                     "Original grader summary: " + graded.explanation)
        return result

    @staticmethod
    def _revision_prompt(evaluation):
        if any("status" in c for c in evaluation["criteria"]):
            known = [c for c in evaluation["criteria"] if c.get("status") != "undetermined"]
            base = RubricMiddleware._revision_prompt({**evaluation, "criteria": known})
            return base + "\n\nPublic acceptance observations (not authoritative facts). " \
                "Only not_satisfied denotes an established defect. Undetermined entries are unresolved verification, not instructions to invent changes. Preserve user authority and request standard corrections from its owner when necessary.\n" + encode(evaluation["criteria"])
        base = RubricMiddleware._revision_prompt(evaluation)
        grounds = [{"name": c["name"], "grounds": c["grounds"]}
                   for c in evaluation["criteria"] if "grounds" in c]
        if not grounds:
            return base
        from .review_contract import FEEDBACK_NOTE
        return base + "\n\n" + FEEDBACK_NOTE + "\n" + encode(grounds)

    async def abefore_agent(self, state, runtime):
        if state.get("rubric_terminal_handoff"):
            return None  # Resume the pending handoff without resetting its budget.
        if self.acceptance_workspace is not None and state.get("_rubric_status") == "undetermined":
            state = {**state, "_rubric_status": "failed"}  # Explicit new invocation resets the native run.
        return await super().abefore_agent(state, runtime)

    async def aafter_agent(self, state, runtime):
        if state.get("rubric_terminal_handoff"):
            return {"rubric_terminal_handoff": False}
        reset = {}
        if self.acceptance_workspace is not None:
            from .acceptance import draft_criteria, criteria_rules
            from .errors import ActionRejected
            workspace = self.acceptance_workspace
            draft_id = (workspace.store.get("delivery") or {}).get("draft_id")
            try:
                if not draft_id:
                    raise ActionRejected("SELECTED_DRAFT_REQUIRED_FOR_ACCEPTANCE")
                criteria = draft_criteria(workspace, workspace.result(draft_id))
            except ActionRejected as exc:
                workspace.store.event("acceptance_precondition_unmet", {"reason": str(exc)})
                workspace.store.set("acceptance_limitation", {"reason": str(exc), "draft_id": draft_id})
                workspace.store.set("report_status", "needs_attention")
                return None
            workspace.store.set("acceptance_limitation", None)
            rules = criteria_rules(criteria)
            state = {**state, "rubric": rules}
            reset = {"rubric": rules, **(self._reset_for_new_rubric(state) or {}),
                     "_rubric_criteria": [c["id"] for c in criteria["criteria"]]}
            state = {**state, **reset}
            self._criterion_ids = reset["_rubric_criteria"]
            workspace.store.set("active_rubric_hash", digest(rules))
        update = await super().aafter_agent(state, runtime)
        if update is not None:
            update = {**reset, **update}
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
        if any("grounds" in c for c in feedback["criteria"]):
            from .review_contract import FEEDBACK_NOTE
            feedback["grounds_status"] = FEEDBACK_NOTE
        return {**update, "rubric_terminal_handoff": True,
                "messages": [HumanMessage(content=encode(feedback), name="rubric_terminal_feedback")],
                "jump_to": "model"}


def load_rules():
    return (Path(__file__).parent / "rules" / "report-review.md").read_text(encoding="utf-8")


def reviewer_prompt(experiment=None, *, requirement_acceptance=False):
    """Specialist purpose plus the installed framework's full grading contract."""
    if requirement_acceptance:
        return (Path(__file__).parent / "rules" / "acceptance-reviewer.md").read_text(encoding="utf-8")
    role = (Path(__file__).parent / "rules" / "report-reviewer.md").read_text(encoding="utf-8")
    prompt = role + "\n\n# Native grading contract\n\n" + GRADER_SYSTEM_PROMPT
    if experiment and experiment["grounded_verdict"]:
        from .review_context import GROUNDING_INSTRUCTION
        prompt += "\n\n# Public verdict grounds\n\n" + GROUNDING_INSTRUCTION
    if experiment and experiment.get("calibrated_acceptance"):
        from .review_context import ACCEPTANCE_INSTRUCTION
        prompt += "\n\n# Acceptance boundaries\n\n" + ACCEPTANCE_INSTRUCTION
    return prompt


def export_configuration(workspace):
    return digest({"options": workspace.store.manifest.get("export", {}),
                   "exporter": (Path(__file__).parent / "exporting.py").read_text(encoding="utf-8")})


def observation_version(workspace, draft_id):
    changes = dict(workspace.delivery(draft_id).get("changes", {}))
    changes.pop("context_revision", None)
    changes.pop("review_context_revision", None)
    return digest({"changes": changes, "human_inputs": workspace.store.get("report_issues", [])})


def native_review(workspace, model, tools, rules, middleware=()):
    from .review_context import ReviewContext, experiment_config
    from .source_search import bind_source_search
    from .acceptance import enabled, draft_criteria, criteria_identity, criteria_rules
    context = {}
    search_view = bind_source_search(workspace)
    experiment = experiment_config(workspace.store)
    acceptance = enabled(workspace)
    system_prompt = reviewer_prompt(experiment, requirement_acceptance=acceptance)
    review_context = ReviewContext(workspace) if experiment or acceptance else None

    def read_review_context(section: Literal["assignment", "state", "history"], offset: int = 0, limit: int = 12000) -> dict:
        """Read this attempt's assignment, state or public history. Offset/limit are
        characters; limit is 1..16000. Follow next_offset for the complete section.
        Assignment includes the current goal, real feedback and human decisions.
        State includes source catalog and saved-result metadata. History contains
        public messages and tool calls; author assertions are not verified facts.
        """
        return review_context.read(section, offset, limit)

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
        if bind_source_search(workspace) != search_view:
            raise RuntimeError("SOURCE_SEARCH_VIEW_BINDING_CHANGED")
        selected = workspace.store.get("delivery") or {}
        draft_id = selected.get("draft_id")
        context.clear()
        effective_rules = rules
        criteria = None
        if acceptance:
            criteria = draft_criteria(workspace, workspace.result(draft_id))
            effective_rules = criteria_rules(criteria)
        context.update(draft_id=draft_id, rubric_hash=digest(effective_rules),
                       reviewer_prompt_hash=digest(system_prompt),
                       grader_model=getattr(model, "model_name", None),
                       export_configuration_hash=export_configuration(workspace))
        if experiment:
            context["review_context_experiment"] = experiment
        if search_view is not None:
            context["source_search_view"] = search_view
        from .review_contract import contract_identity
        contract = contract_identity(experiment)
        if acceptance:
            from .acceptance_review import contract_identity as acceptance_contract
            contract = acceptance_contract()
            context["acceptance_criteria"] = criteria_identity(criteria)
        if contract:
            context["review_response_contract"] = contract
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
        if review_context:
            packet = review_context.capture(messages, context)
            if acceptance or experiment["input_mode"] == "artifact":
                return [HumanMessage(content=encode(packet))]
        return [*messages, HumanMessage(content=encode({"application_review_target": context,
                "observation": "This is the selected saved report and pinned export for assessment. "
                "No selected draft means no report is available for acceptance. "
                "Project scope, changes, issues and corrections are available in the current project state."
                + (" Full assignment, state and public history are also available through read_review_context." if experiment else "")}))]

    def bind_target(state, iteration):
        key = state["_current_grading_run_id"] + ":" + str(iteration)
        targets = workspace.store.get("rubric_targets", {})
        if key in targets and targets[key] != context:
            raise RuntimeError("RUBRIC_TARGET_IDENTITY_CHANGED")
        if review_context:
            snapshots = workspace.store.get("review_context_snapshots", {})
            snapshot = {"context_sha256": review_context.snapshot_sha256,
                        "sections": dict(review_context.sections)}
            if key in snapshots and snapshots[key] != snapshot:
                raise RuntimeError("REVIEW_CONTEXT_SNAPSHOT_CHANGED")
            snapshots.setdefault(key, snapshot)
            workspace.store.set("review_context_snapshots", snapshots)
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
                    else StructuredTool.from_function(t) for t in
                    [*tools, read_review_export, *([read_review_context] if review_context else [])]]
    return FeedbackRubric(model=model, tools=grader_tools, system_prompt=system_prompt,
                            acceptance_workspace=workspace if acceptance else None,
                            claim_evidence_contract=bool(experiment and experiment.get("claim_evidence_contract")),
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
    from .review_context import experiment_config
    experiment = experiment_config(workspace.store)
    from .source_search import bind_source_search
    search_view = bind_source_search(workspace)
    from .review_contract import contract_identity
    contract = contract_identity(experiment)
    from .acceptance import enabled, draft_criteria, criteria_identity, criteria_rules
    acceptance = enabled(workspace)
    criteria_version = None
    if acceptance:
        from .errors import ActionRejected
        from .acceptance_review import contract_identity as acceptance_contract
        contract = acceptance_contract()
        try:
            criteria = draft_criteria(workspace, draft)
        except ActionRejected as exc:
            return {"draft_id": draft_id, "review_id": "", "status": "needs_attention",
                    "rubric_review": None, "acceptance_status": "undetermined",
                    "acceptance_limitation": str(exc)}
        criteria_version = criteria_identity(criteria)
        rule_hash = digest(criteria_rules(criteria))
    candidates = [r for r in workspace.store.get("rubric_reviews", [])
                  if r["target"].get("draft_id") == draft_id
                  and r["target"].get("draft_body_sha256") == body_hash
                  and r["target"].get("rubric_hash") == rule_hash
                  and (not prompt_hash or r["target"].get("reviewer_prompt_hash") == prompt_hash)
                  and r["target"].get("review_context_experiment") == experiment
                  and r["target"].get("source_search_view") == search_view
                  and r["target"].get("review_response_contract") == contract
                  and (not acceptance or r["target"].get("acceptance_criteria") == criteria_version)
                  and r["target"].get("export_configuration_hash") == export_configuration(workspace)]
    review = candidates[-1] if candidates else None
    status = "unreviewed_draft"
    if review:
        verdict = review["result"]
        status = "reviewed_draft" if verdict == "satisfied" and not review.get("unverified") else (
            "system_error" if verdict == "grader_error" else
            "needs_attention" if verdict == "undetermined" else "changes_required")
        if status == "reviewed_draft" and review["target"].get("observation_version") != observation_version(workspace, draft_id):
            status = "needs_attention"  # New feedback to consider, not a verdict that content is wrong.
    return {"draft_id": draft_id, "review_id": "", "status": status, "rubric_review": review,
            **({"acceptance_criteria": criteria_version,
                "acceptance_status": (review["result"] if review and not review.get("unverified")
                                      and status != "needs_attention" else "undetermined")} if acceptance else {}),
            "review_scope": "Exact saved text and recorded preview snapshot; a fresh export is a new file."}
