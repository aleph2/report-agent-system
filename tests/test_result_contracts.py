from types import SimpleNamespace

import pytest

from report_agent.deep_runtime import business_tools
from report_agent.errors import ActionRejected
from report_agent.store import Store
from report_agent.workspace import Workspace


@pytest.fixture
def context(tmp_path):
    store = Store(tmp_path)
    store.initialize({"goal": "Compile the source.", "sources": [
        {"id": "s", "title": "Source", "coverage": "complete", "content": "Open in daytime."}]})
    ws = Workspace(store)
    ws.initialize()
    def tools(role):
        return {t.__name__: t for t in business_tools(ws, role, None, SimpleNamespace(model_name="offline"))}
    author, reviewer = tools("writer"), tools("reviewer")
    draft = author["submit_result"](title="Draft", body="Open in daytime.", source_ids=["s"], input_ids=[])
    return ws, draft, reviewer, tools


def test_review_target_is_linked_without_duplicate_input(context):
    ws, draft, reviewer, _ = context
    reviewer["read_result"](draft["id"])
    args = dict(title="Review", body="Checked exact draft.", source_ids=["s"],
                target_id=draft["id"], outcome="accepted")
    result = reviewer["submit_result"](**args)
    assert result["input_ids"] == [draft["id"]]
    assert result["target_id"] == draft["id"]
    assert reviewer["submit_result"](**args) == result
    assert len(ws.results()) == 2


def test_automatic_target_link_does_not_invent_observation(context):
    _, draft, reviewer, _ = context
    with pytest.raises(ActionRejected, match="REVIEW_TARGET_NOT_OBSERVED"):
        reviewer["submit_result"](title="Review", body="Not read.", source_ids=["s"],
                                  target_id=draft["id"], outcome="accepted")


def test_review_target_must_exist_and_be_draft(context):
    _, _, reviewer, tools = context
    with pytest.raises(ActionRejected, match="RESULT_NOT_IN_PROJECT"):
        reviewer["submit_result"](title="Review", body="Unknown.", source_ids=["s"],
                                  target_id="unknown", outcome="accepted")
    plan = tools("knowledge")["submit_result"](kind="plan", title="Plan", body="Compile.",
                                              source_ids=["s"], input_ids=[])
    reviewer["read_result"](plan["id"])
    with pytest.raises(ActionRejected, match="REVIEW_REQUIRES_EXACT_DRAFT"):
        reviewer["submit_result"](title="Review", body="Wrong kind.", source_ids=["s"],
                                  target_id=plan["id"], outcome="accepted")


def test_figure_source_is_adopted_without_duplicate_ids(context):
    ws, _, _, tools = context
    author = tools("writer")
    args = dict(title="Illustrated draft", body="![Source page](source-page://s/1)",
                source_ids=[], input_ids=[])
    result = author["submit_result"](**args)
    assert result["source_ids"] == ["s"]
    assert author["submit_result"](**args) == result
    from report_agent.catalog import Catalog
    new = Catalog(ws.store).import_file("updated.txt", b"Updated source", replaces_id="s")
    assert new["source"]["replaces_id"] == "s"
    assert result["id"] in ws.impact()["stale_result_ids"]


def test_figure_reference_cannot_adopt_foreign_source(context):
    _, _, _, tools = context
    with pytest.raises(ActionRejected, match="SOURCE_NOT_IN_PROJECT"):
        tools("writer")["submit_result"](title="Invalid image", body="![Foreign](source-page://outside/1)",
                                            source_ids=[], input_ids=[])


def test_preview_text_counts_as_exact_draft_observation(context):
    _, draft, reviewer, _ = context
    preview = reviewer["preview_report"](draft["id"])
    assert preview["content"]["text"]
    result = reviewer["submit_result"](title="Review", body="Read actual exported text.", source_ids=["s"],
                                        target_id=draft["id"], outcome="accepted")
    assert result["target_id"] == draft["id"]


@pytest.mark.parametrize("mode", ["empty", "invalid", "other_draft"])
def test_preview_does_not_invent_target_observation(context, mode):
    from report_agent.report_preview import preview_saved_report
    ws, draft, reviewer, tools = context
    saved = preview_saved_report(ws, draft["id"])
    if mode == "empty":
        read = reviewer["preview_report"](draft["id"], offset=saved["text"]["blocks"],
                                            preview_version=saved["preview_version"])
        assert read["content"]["text"] == ""
    elif mode == "invalid":
        with pytest.raises(ActionRejected):
            reviewer["preview_report"](draft["id"], preview_version="invalid")
    else:
        other = tools("writer")["submit_result"](title="Other draft", body="Other text", source_ids=["s"], input_ids=[])
        reviewer["preview_report"](other["id"])
    with pytest.raises(ActionRejected, match="REVIEW_TARGET_NOT_OBSERVED"):
        reviewer["submit_result"](title="Not observed", body="Must reject", source_ids=["s"],
                                   target_id=draft["id"], outcome="accepted")


def test_draft_review_revision_adopting_old_review_can_be_reviewed(context):
    ws, draft, reviewer, tools = context
    reviewer["read_result"](draft["id"])
    old_review = reviewer["submit_result"](title="Initial review", body="Clarify scope.",
        source_ids=["s"], target_id=draft["id"], outcome="changes_required")
    correction = ws.request_correction(draft["id"], "Clarify scope")
    args = dict(title="Revised draft", body="Scope clarified, pending exact review.",
                source_ids=["s"], input_ids=[draft["id"], old_review["id"]], replaces_id=draft["id"])
    revised = tools("writer")["submit_result"](**args)
    assert revised["input_ids"] == [old_review["id"]]
    assert revised["replaces_id"] == draft["id"]
    assert old_review["id"] in ws.impact()["stale_result_ids"]
    addressed = next(c for c in ws.store.get("corrections") if c["id"] == correction["id"])
    assert addressed["status"] == "addressed" and addressed["resolved"] is False
    assert ws.delivery(revised["id"])["status"] == "unreviewed_draft"
    with pytest.raises(ActionRejected, match="REVIEW_VERSION_MISMATCH"):
        ws.select_delivery(revised["id"], old_review["id"])
    review_args = dict(title="Exact revised review", body="Checked revised scope.", source_ids=["s"],
                       input_ids=[old_review["id"]], target_id=revised["id"], outcome="accepted")
    with pytest.raises(ActionRejected, match="REVIEW_TARGET_NOT_OBSERVED"):
        reviewer["submit_result"](**review_args)
    reviewer["read_result"](revised["id"])
    new_review = reviewer["submit_result"](**review_args)
    assert new_review["target_id"] == revised["id"]
    assert old_review["id"] in new_review["input_changes"]["changed_result_ids"]
    assert ws.select_delivery(revised["id"], new_review["id"])["status"] == "reviewed_draft"
    assert tools("writer")["submit_result"](**args)["id"] == revised["id"]
    assert reviewer["submit_result"](**review_args)["id"] == new_review["id"]
    assert len(ws.results()) == 4
    assert ws.store.get("corrections")[0]["resolved"] is False
    assert ws.result(draft["id"])["body"] == draft["body"]
    assert ws.result(old_review["id"])["body"] == old_review["body"]
