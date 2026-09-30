"""Versioned review records on DeepAgents' native final-review entry point.

The pinned harness owns invocation, checkpoints and feedback routing. Its legacy
boolean contract cannot represent unexecuted work, so that projection is not used.
"""
from __future__ import annotations

from inspect import iscoroutinefunction

from deepagents.middleware.rubric import RubricMiddleware, RUBRIC_GRADER_MESSAGE_SOURCE
from langchain.agents import AgentState, create_agent
from langchain_core.messages import HumanMessage
from langchain_core.tools import StructuredTool
from pydantic import Field

from .content_models import Contract, ReviewSubmission, aggregate, delivery_aggregate, SCHEMA_VERSION
from .content_delivery import current_delivery, obligations
from .content_store import ContentStore
from .hierarchical_tools import actor_for, role_prompt
from .review import ReviewState
from .store import digest, encode


class HierarchicalResponse(Contract):
    explanation: str = Field(min_length=1)
    review: ReviewSubmission


class HierarchicalRubric(RubricMiddleware):
    state_schema = ReviewState

    def __init__(self, workspace, model, tools, middleware):
        self.workspace = workspace
        self.contents = ContentStore(workspace.store)
        self.actor = actor_for("rubric_grader")
        self.target = None
        self.required = []
        self.identity = {"contract": SCHEMA_VERSION, "model": getattr(model, "model_name", "unknown"),
            "runtime": "deepagents-0.7.19", "prompt_digest": digest(role_prompt("reviewer")),
            "schema_digest": digest(HierarchicalResponse.model_json_schema()),
            "settings": {key: getattr(model, key, None) for key in ("temperature", "reasoning_effort", "max_tokens", "max_retries")}}
        adapted = [StructuredTool.from_function(coroutine=t) if iscoroutinefunction(t)
                   else StructuredTool.from_function(t) for t in tools]
        super().__init__(model=model, system_prompt=role_prompt("reviewer"), tools=adapted,
            grader_middleware=middleware, grader_state_schema=AgentState,
            prepare_messages_for_grader=self.prepare)

    def prepare(self, messages):
        snapshot = self.contents.read(self.target["snapshot_ref"])
        criteria = [self.contents.read(r) for r in snapshot["payload"]["criteria_refs"]]
        packet = {"task": "Independently assess whole-document requirements, composition, omissions, export fidelity and actual page quality. Choose methods and depth; use original sources and bounded observations. Author text is unverified.",
            "target": self.target, "criteria": criteria, "required_obligations": self.required,
            "required_delivery_checks": ["export", "render"],
            "review_state_access": "read_review_status exposes paged per-object states and historical applicability for the selected snapshot/export. It is metadata, not fresh content evidence or a prescribed investigation route.",
            "review_contract": SCHEMA_VERSION, "note": "Return observations actually obtained, uncovered scope and honest states. Read actual objects and original sources through tools; metadata is not content."}
        from .review_coverage import CONTRACT, inventory
        if snapshot["payload"].get("coverage_contract") == CONTRACT:
            packet["object_coverage"] = {"contract": CONTRACT, "expected_refs": inventory(snapshot),
                "instruction": "Account for these exact objects in coverage_accounting. Each entry can group multiple objects and link to zero-based indexes of your review items. Record assessed, partial, not_assessed or justified not_applicable. This is coverage responsibility, not a prescribed method or one call per object. Whole-document requirements also include omissions and composition; listing objects or reading metadata is not assessment."}
        self.workspace.store.event("content_native_review_input", {"packet": packet, "runtime_identity": self.identity})
        return [HumanMessage(content=encode(packet))]

    def _ensure_grader(self):
        if self._grader is None:
            from deepagents._models import resolve_model
            self._resolved_model = resolve_model(self._model)
            self._grader = create_agent(model=self._resolved_model, system_prompt=self._system_prompt,
                tools=self._tools, middleware=self._grader_middleware, name=RUBRIC_GRADER_MESSAGE_SOURCE,
                response_format=HierarchicalResponse, state_schema=AgentState)
        return self._grader

    @staticmethod
    def _extract_graded(result):
        response = result.get("structured_response")
        return response if isinstance(response, HierarchicalResponse) else HierarchicalResponse.model_validate(response)

    def _usability_correction(self, state, graded):
        review = graded.review.model_dump()
        if review["snapshot_ref"] != self.target["snapshot_ref"] or review["target_ref"] != self.target["snapshot_ref"]:
            return "Use the exact selected snapshot as review target and snapshot_ref."
        if any(not self.contents.item_applies(item, self.target["snapshot_ref"], self.target["export_ref"]) for item in review["items"]):
            return "Artifact assessments must refer to the selected export, or a render of that export, in this exact snapshot. Do not judge another file as this delivery."
        if any(c["artifact_refs"] and not self.contents.item_applies({**c, "assessment_kind": c["kind"]},
                self.target["snapshot_ref"], self.target["export_ref"]) for c in review["delivery_checks"]):
            return "Delivery checks must bind the selected export and its rendered pages."
        summary = aggregate(review["items"], self.required)
        if summary["missing_obligations"]:
            return "Account for each required delivery obligation, with null and honest execution state if not checked: " + encode(summary["missing_obligations"])
        if {c["kind"] for c in review["delivery_checks"]} != {"export", "render"}:
            return "Account separately for export fidelity and rendered-page quality in delivery_checks. If not performed, use null and the actual execution/coverage state. Choose your methods; no fixed tool order is required."
        return None

    def _build_evaluation(self, graded, grading_run_id, iteration):
        review = graded.review.model_dump()
        if review["snapshot_ref"] != self.target["snapshot_ref"] or review["target_ref"] != self.target["snapshot_ref"]:
            raise ValueError("REVIEW_TARGET_MISMATCH")
        if any(not self.contents.item_applies(item, self.target["snapshot_ref"], self.target["export_ref"]) for item in review["items"]):
            raise ValueError("REVIEW_ARTIFACT_TARGET_MISMATCH")
        if any(c["artifact_refs"] and not self.contents.item_applies({**c, "assessment_kind": c["kind"]},
                self.target["snapshot_ref"], self.target["export_ref"]) for c in review["delivery_checks"]):
            raise ValueError("REVIEW_ARTIFACT_TARGET_MISMATCH")
        if self.target["export_ref"] not in review["dependency_refs"]:
            review["dependency_refs"].append(self.target["export_ref"])
        operation = "native-review:" + grading_run_id + ":" + str(iteration)
        saved = self.contents.submit_review(self.actor, operation, review, self.identity)
        summary = delivery_aggregate(aggregate(review["items"], self.required), review["delivery_checks"])
        from .review_coverage import apply_coverage
        summary = apply_coverage(summary, self.contents.read(self.target["snapshot_ref"]), review)
        summary["changed_review_sources"] = self.contents.changed_review_sources(review)
        if summary["changed_review_sources"] and summary["overall_verdict"] != "not_satisfied":
            summary.update(overall_verdict=None, coverage_complete=False)
        historical = self.contents.review_summary(self.target["snapshot_ref"], self.required, self.target["export_ref"])
        summary["confirmed_violations"] = historical["confirmed_violations"]
        summary["delivery_violations"] = historical["delivery_violations"]
        if historical["confirmed_violations"] or historical["delivery_violations"]:
            summary["overall_verdict"] = "not_satisfied"
        verdict = summary["overall_verdict"]
        result = {None: "execution_incomplete", "satisfied": "satisfied", "undetermined": "undetermined",
                  "not_satisfied": "needs_revision"}[verdict]
        if verdict == "not_satisfied" and self.target["ending_reason"] != "continue":
            result = "not_satisfied"  # Preserve defect while honoring an explicit stop.
        data = {"target": self.target, **summary, **saved["result"], "runtime_identity": self.identity,
                "explanation": graded.explanation, "execution_result": result, "native_run_id": grading_run_id}
        data["evidence_revision"] = self.evidence_revision()
        self.workspace.store.set("content_final_review", data)
        self.workspace.store.event("content_native_review_completed", data)
        return {"grading_run_id": grading_run_id, "iteration": iteration, "result": result,
            "explanation": graded.explanation, "criteria": [{"name": i["criterion_ref"]["id"], **i} for i in review["items"]],
            "unverified": verdict is None, "content_record": data}

    def _log_coverage_retry_failure(self, state, iteration, graded):
        # The native logger expects its boolean-era response.result attribute.
        # Retain the usable scoped record; missing responsibilities remain null.
        self.workspace.store.event("content_coverage_correction_failed", {
            "iteration": iteration, "snapshot_ref": graded.review.snapshot_ref.model_dump()})

    def evidence_revision(self):
        # Detect new observations, source versions or explicit review corrections,
        # not just text changes. This is an observation of progress, not a call quota.
        with self.workspace.store.connect() as db:
            observations = db.execute("SELECT coalesce(max(rowid),0) FROM content_observations").fetchone()[0]
            records = db.execute("SELECT coalesce(max(rowid),0) FROM content_versions").fetchone()[0]
        return {"observations": observations, "records": records}

    def _finalize_evaluation(self, graded, state, runtime, grading_run_id, iteration):
        # Keep native feedback routing. Do not turn its historical iteration count
        # into an acceptance criterion or a production call quota. The coordinator
        # can retain unresolved work; an unchanged review target is recognized below.
        evaluation = self._build_evaluation(graded, grading_run_id, iteration)
        self._emit(runtime, "rubric_evaluation_end", grading_run_id, iteration, evaluation)
        return self._compose_update(state, evaluation)

    @staticmethod
    def _revision_prompt(evaluation):
        return ("Review feedback for the exact selected version. Investigate the evidence and revise only your owned results; "
                "do not blindly accept feedback or invent missing values. Preserve correct content. "
                "Null is unexecuted, undetermined is unresolved investigation; neither is a confirmed defect. "
                "Read the persistent findings; choose correction, more evidence, delegation or a justified stop.\n"
                + encode(evaluation["content_record"]) + "\n" + encode(evaluation["criteria"]))

    async def abefore_agent(self, state, runtime):
        if state.get("rubric_terminal_handoff"):
            return None
        if state.get("_rubric_status") in {"undetermined", "execution_incomplete", "not_satisfied", "no_progress"}:
            state = {**state, "_rubric_status": "failed"}
        return await super().abefore_agent(state, runtime)

    async def aafter_agent(self, state, runtime):
        if state.get("rubric_terminal_handoff"):
            return {"rubric_terminal_handoff": False}
        self.target = self.workspace.store.get("content_delivery")
        if not self.target:
            self.workspace.store.set("report_status", "needs_attention")
            return None
        snapshot = self.contents.read(self.target["snapshot_ref"])
        self.required = obligations(self.contents, self.target["snapshot_ref"])
        previous = self.workspace.store.get("content_final_review")
        # No automatic repetition of the same evidence/target. Explicit new runs
        # can investigate again, with the retained findings available as feedback.
        if (previous and previous["target"]["snapshot_ref"] == self.target["snapshot_ref"]
                and previous["target"]["export_ref"] == self.target["export_ref"]
                and previous.get("native_run_id") == state.get("_current_grading_run_id")
                and previous.get("evidence_revision") == self.evidence_revision()):
            return {"_rubric_status": "no_progress"}
        rules = encode({"target": self.target, "required_obligations": self.required})
        state = {**state, "rubric": rules}
        update = await super().aafter_agent(state, runtime)
        if update and update.get("_rubric_status") not in {"satisfied", "needs_revision"}:
            return {**update, "rubric_terminal_handoff": True, "jump_to": "model",
                "messages": [HumanMessage(content="Final review ended without satisfaction. Preserve actual verdicts, coverage and unresolved work; explain the current delivery. "
                    + encode(self.workspace.store.get("content_final_review") or {"execution_state": "blocked", "verdict": None}), name="content_terminal_feedback")]}
        return update


def reconcile(workspace, native_state):
    status = current_delivery(workspace.store)["status"]
    if native_state.get("_rubric_status") == "grader_error":
        workspace.store.set("content_execution_limitation", {"execution_state": "blocked", "verdict": None, "reason": "grader_error"})
        status = "needs_attention"
    workspace.store.set("report_status", status)
