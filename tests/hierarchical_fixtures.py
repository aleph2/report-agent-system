"""Synthetic delivery evidence for protocol tests, never model quality evidence."""
from report_agent.content_export import read_export
from report_agent.hierarchical_tools import actor_for


def unchecked_delivery():
    return [{"kind": k, "artifact_refs": [], "execution_state": "not_started", "verdict": None,
        "observations": [], "coverage": {"checked": [], "unchecked": [k], "blocked": [], "basis": "not performed"},
        "reason": "Required delivery check has not run."} for k in ("export", "render")]


def delivery_evidence(cs, snapshot, export, actor=None):
    """Actual DOCX read + explicitly synthetic visual observation and render identity."""
    actor = actor or actor_for("rubric_grader")
    export_receipt = read_export(cs, actor, export)["receipt_id"]
    with cs.store.connect() as db:
        render = cs._insert(db, actor, "RenderArtifact", {"snapshot_ref": snapshot, "export_ref": export,
            "page_assets": [{"page": 1}], "test_fixture": "synthetic render; not quality evidence"})
    page_receipt = cs.observe(actor, {"status": "observed", "observation": "Synthetic visible page fixture.",
        "source": {"render_ref": render, "export_ref": export, "page": 1}})["receipt_id"]
    return [{"kind": k, "artifact_refs": [ref], "execution_state": "completed", "verdict": "satisfied",
        "observations": [{"locator": k, "observation": "Protocol fixture.", "receipt_id": receipt}],
        "coverage": {"checked": [k], "unchecked": [], "blocked": [], "basis": "protocol fixture"},
        "reason": "Synthetic protocol result; not a quality conclusion."}
        for k, ref, receipt in (("export", export, export_receipt), ("render", render, page_receipt))]
