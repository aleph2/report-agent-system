"""Reviewed role contracts; real autonomy remains a separate fresh-run check."""
import re
import pytest
from report_agent.hierarchical_tools import role_prompt
from report_agent.prompt_sources import load_prompt


def text(name):
    return re.sub(r"\s+", " ", load_prompt(name))


def test_reviewer_plan_precedes_verification_without_extra_planner():
    value = text("content-reviewer-v4")
    assert "before substantive verification" in value
    assert "calculation, evidence comparison or page/image inspection" in value
    assert "no separate planner" in value
    assert "before substantive judgments" in value
    assert "public working response or native todos" in value


@pytest.mark.parametrize("name", ["content-coordinator-v4", "content-coordinator-v4-concise"])
def test_co_presentation_authority_and_query_warning_are_explicit(name):
    value = text(name)
    assert "previously saved presentation settings" in value
    assert "New style/layout design belongs to Layout when needed" in value
    assert "warning alone does not establish a version change" in value
    assert "Do not personally inspect rendered report or export pages" in value


def test_writer_briefs_producer_and_preserves_legitimate_literal_material():
    value = text("content-writer-v4")
    assert "Brief the tool on content, structure and constraints" in value
    assert "Literal quotations and supplied wording remain legitimate" in value
    assert "unnecessary body or qualifier restatement" in value
    assert "Do not write or override substantive bodies" in value
    assert "candidate_selections" in value
    assert "business observation receipt UUIDs" not in value


@pytest.mark.parametrize("name", ["native-submit-review-v4", "native-submit-review-v4-concise"])
def test_artifact_declaration_distinct_from_check_extent(name):
    value = text(name)
    assert "complete artifact_refs set" in value
    assert "artifact_check_scopes" in value
    assert "outside_assignment_notes belongs to review.items[]" in value


@pytest.mark.parametrize("role", ["coordinator", "writer", "reviewer"])
def test_old_role_interfaces_remain_exact(role):
    legacy = role_prompt(role, expression_profile="report-expression-v1", interface_profile="review-interfaces-v1")
    assert legacy == '\n\n'.join(t for t in [load_prompt('agent-common'), load_prompt('agent-' + role)] if t.strip())
