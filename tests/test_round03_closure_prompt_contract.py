"""Concrete final-input boundaries; real prose/reuse assessed in fresh native Trace."""
import re
import pytest
from report_agent.prompt_sources import load_prompt

def text(name):
    return re.sub(r"\s+", " ", load_prompt(name))

@pytest.mark.parametrize("name", ["content-coordinator-v4", "content-coordinator-v4-concise"])
def test_co_prefers_compatible_saved_files_and_retains_legitimate_exports(name):
    value=text(name)
    assert "Prefer the already saved, authorized compatible artifacts and their mappings" in value
    assert "Export only missing files or an actual authorized change" in value
    assert "Distinguish inherent source limitations from fixable presentation findings" in value
    assert "Selection is not approval" in value
    assert "Do not personally inspect rendered report or export pages" in value

@pytest.mark.parametrize("name", ["content-writer-v4", "text-work-v2"])
def test_composition_places_each_fact_once_without_hiding_unique_conditions(name):
    value=text(name)
    assert "State each fact or limitation once within each artifact" in value
    assert "qualifiers add necessary conditions, not another complete narrative" in value
    assert "unique source attribution, uncertainty and adverse evidence" in value


def test_writer_uses_existing_contents_options_without_new_default_or_layout_stage():
    value=text("content-writer-v4")
    assert "toc=False" in value and "refresh_toc=True" in value
    assert "complete selected node layout" in value
    assert "unrefreshed field cache" in value
    from report_agent.content_layout import LayoutOptions
    assert LayoutOptions().toc is True and LayoutOptions().refresh_toc is False


def test_reviewer_work_units_are_executable_without_extra_planner():
    value=text("content-reviewer-v4")
    assert "evidence, method and decision conditions explicit enough" in value
    assert "before substantive verification" in value
    assert "no separate planner, approval or model call" in value
