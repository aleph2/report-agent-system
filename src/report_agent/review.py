"""Thin evidence and persistence adapter for DeepAgents' native rubric loop."""
from . import issue_state
from . import legacy_state as legacy
from pathlib import Path
from inspect import iscoroutinefunction
from typing import Literal, NotRequired

from deepagents import RubricMiddleware
from deepagents.middleware.rubric import GRADER_SYSTEM_PROMPT, RubricState
from langchain.agents import AgentState
from langchain_core.messages import HumanMessage
from langchain_core.tools import StructuredTool

from .store import digest, encode


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
    return digest({"changes": changes, "human_inputs": issue_state.get_report_issues(workspace.store, [])})


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
