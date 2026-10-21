"""Host synthetic export fixtures; actual DOCX/XLSX bytes, not agent semantics."""
from copy import deepcopy
from io import BytesIO
import json
import hashlib
import os
from pathlib import Path

from docx import Document
from openpyxl import load_workbook
import pytest

from report_agent.content_export import export_snapshot
from report_agent.content_workbook import export_workbook
from report_agent.errors import ActionRejected
from test_hierarchical_content import seed
from test_task_supervision import ws, offline


FOOTNOTE = "  Footnote: retain the complete qualification.\nSecond complete line.  "


@pytest.mark.parametrize("variant", ["present", "absent", "blank", "null", "false", "mapping"])
def test_table_footnote_visible_without_changing_data_or_saved_nodes(ws, tmp_path, variant):
    cs, actor, refs, _, members = seed(ws)
    body = {"columns": ["A", "B"], "rows": [["1", "2"]], "_debug": "PRIVATE_SYNTHETIC_AUX"}
    if variant != "absent":
        body["footnote"] = {"present": FOOTNOTE, "blank": " \n\t ", "null": None,
                            "false": False, "mapping": {"text": "Unsupported note"}}[variant]
    added = cs.commit(actor, "synthetic-export-fixture", [
        {"client_key": "table", "type": "ContentNode", "payload": {"kind": "table", "body": body,
            "qualifiers": {"scope": "QUALIFIER_VALUE"}, "claim_kind": "structure"}},
        {"client_key": "note", "type": "ContentNode", "payload": {"kind": "block",
            "body": {"text": "EXPLICIT_NOTE_VALUE"}, "qualifiers": {}, "claim_kind": "structure"}},
        *[{"client_key": "edge-" + key, "type": "Relation", "payload": {
            "subject_ref": refs["root"], "object_ref": {"client_key": key}, "predicate": "contains",
            "position": position, "provenance_kind": "adopted_during_generation"}}
          for position, key in enumerate(["table", "note"], 1)]])['result']['refs']
    snapshot = cs.freeze(actor, "fixture-snapshot", refs["root"], members + list(added.values()))['result']['snapshot_ref']
    protected = deepcopy(cs.list_objects())
    capture = {"variant": variant, "body": body, "protected": protected, "outputs": {}, "errors": {}}
    for kind, execute in {
        "word": lambda: export_snapshot(cs, actor, "word", snapshot, {"toc": False}),
        "excel": lambda: export_workbook(cs, actor, "excel", snapshot,
            [{"name": "Synthetic", "table_ref": added["table"], "note_refs": [added["note"]]}]),
    }.items():
        try:
            result = execute()["result"]
            capture["outputs"][kind] = {"result": result, "artifact": cs.read(result["export_ref"]),
                "mapping": cs.read(result["mapping_ref"])}
        except ActionRejected as exc:
            capture["errors"][kind] = str(exc)
    capture.update(events=ws.store.events(), objects=cs.list_objects())
    root = Path(os.environ.get("FOOTNOTE_EXPORT_EVIDENCE", str(tmp_path / "evidence")))
    root.mkdir(parents=True, exist_ok=True)
    evidence_path = root / (variant + ".json")
    evidence_path.write_text(json.dumps(capture, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        for kind, output in capture["outputs"].items():
            data = (ws.store.root / output["result"]["file_ref"]).read_bytes()
            output["actual_file_sha256"] = hashlib.sha256(data).hexdigest()
            if kind == "word":
                doc = Document(BytesIO(data))
                output["paragraphs"] = [p.text for p in doc.paragraphs]
                output["tables"] = [[[cell.text for cell in row.cells] for row in table.rows] for table in doc.tables]
            else:
                workbook = load_workbook(BytesIO(data))
                sheet = workbook.active
                output.update(rows=[list(r) for r in sheet.iter_rows(values_only=True)], auto_filter=sheet.auto_filter.ref)
                workbook.close()
    except Exception as exc:
        capture["observer_error"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        evidence_path.write_text(json.dumps(capture, ensure_ascii=False, indent=2), encoding="utf-8")
    assert all(cs.read(record["ref"]) == record for record in protected)
    if variant in {"false", "mapping"}:
        assert set(capture["errors"]) == {"word", "excel"}
        assert all("TABLE_FOOTNOTE_REQUIRES_TEXT" in error for error in capture["errors"].values())
        assert capture["outputs"] == {}
        assert not cs.list_objects("ExportArtifact")
        return
    assert capture["errors"] == {}
    for output in capture["outputs"].values():
        assert output["artifact"]["owner_id"] == output["mapping"]["owner_id"] == actor.id
        assert output["artifact"]["ref"] == output["result"]["export_ref"]
        assert output["mapping"]["ref"] == output["result"]["mapping_ref"]
        assert output["artifact"]["payload"]["snapshot_ref"] == output["mapping"]["payload"]["snapshot_ref"] == snapshot
        assert output["mapping"]["payload"]["export_ref"] == output["result"]["export_ref"]
        assert output["actual_file_sha256"] == output["result"]["file_digest"] == output["artifact"]["payload"]["file_digest"]
    word, excel = capture["outputs"]["word"], capture["outputs"]["excel"]
    assert word["tables"] == [[["A", "B"], ["1", "2"]]]
    assert excel["auto_filter"] == "A2:B3"
    values = [cell for row in excel["rows"] for cell in row]
    assert values.count("QUALIFIER_VALUE") == values.count("EXPLICIT_NOTE_VALUE") == 1
    assert "PRIVATE_SYNTHETIC_AUX" not in values and "PRIVATE_SYNTHETIC_AUX" not in str(word["paragraphs"])
    anchors = [a for a in excel["mapping"]["payload"]["anchor_records"] if a.get("kind") == "table-footnote"]
    if variant == "present":
        assert word["paragraphs"].count(FOOTNOTE) == values.count(FOOTNOTE) == 1
        assert anchors == [{"node_ref": added["table"], "sheet": "Synthetic", "kind": "table-footnote", "row_start": 4, "row_stop": 5}]
    else:
        assert anchors == [] and FOOTNOTE not in values
    assert excel["artifact"]["payload"]["export_config"]["layout_engine_digest"] == word["artifact"]["payload"]["export_config"]["layout_engine_digest"]
