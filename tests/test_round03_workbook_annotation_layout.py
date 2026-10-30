"""Reader-v2 known note rows use available width, not content rewriting."""
from io import BytesIO
from copy import deepcopy
import pytest
from openpyxl import load_workbook
from report_agent.content_workbook import export_workbook
from test_hierarchical_content import ws, seed


def fixture(ws, note, expression="reader-expression-v2", label="范围"):
    ws.store.set("manifest",{**ws.store.manifest,"report_expression_profile":expression})
    cs,actor,refs,_,members=seed(ws)
    items=[{"client_key":"table","type":"ContentNode","payload":{"kind":"table",
        "body":{"columns":["项目","数量","单价","金额","来源","说明"],
                "rows":[["甲",9,120,1080,"清单","=1+1"],["乙",6,180,1080,"清单","保留"],["合计",15,"",2160,"","不加费用"]]},
        "qualifiers":{label:"仅模拟数量核算"},"claim_kind":"structure"}},
        {"client_key":"note","type":"ContentNode","payload":{"kind":"block","body":{"text":note},
            "qualifiers":{"限制":"缺少实测厚度，不作工程验收。"},"claim_kind":"structure"}}]
    items += [{"client_key":"edge"+str(i),"type":"Relation","payload":{"subject_ref":refs["root"],
        "object_ref":{"client_key":name},"predicate":"contains","position":i+1,
        "provenance_kind":"adopted_during_generation"}} for i,name in enumerate(["table","note"])]
    added=cs.commit(actor,"annotations",items)["result"]["refs"]
    snap=cs.freeze(actor,"closure-snapshot",refs["root"],[*members,*added.values()])["result"]["snapshot_ref"]
    before=deepcopy(cs.read(snap))
    result=export_workbook(cs,actor,"xlsx",snap,[{"name":"数量费用","table_ref":added["table"],"note_refs":[added["note"]]}])["result"]
    wb=load_workbook(BytesIO((ws.store.root/result["file_ref"]).read_bytes()))
    assert cs.read(snap)==before
    return cs,result,wb.active


def test_short_annotations_span_available_columns_with_explicit_height(ws):
    note="资料仅支持数量与费用核对。"*12
    cs,result,sheet=fixture(ws,note)
    assert sheet["B6"].value==note and sheet["B6"].data_type=="s"
    assert {"B1:F1","B6:F6","B7:F7"} <= {str(r) for r in sheet.merged_cells.ranges}
    assert sheet.row_dimensions[6].height>=40
    assert sheet["F3"].value=="=1+1" and sheet["F3"].data_type=="s"
    assert sheet["D5"].value=="2160" and sheet.freeze_panes=="A3"
    assert sheet.print_title_rows=="$2:$2"
    mapping=cs.read(result["mapping_ref"])["payload"]["anchor_records"]
    assert next(m for m in mapping if m.get("kind")=="note")["row_start"]==6
    assert next(m for m in mapping if m.get("kind")=="note")["row_stop"]==8
    assert not cs.read(result["export_ref"])["payload"]["export_config"].get("annotation_layout_unverified_rows")


def test_oversized_annotation_preserves_full_text_without_clipping_height(ws):
    note="完整限制不得截掉。"*1200
    cs,result,sheet=fixture(ws,note)
    assert sheet["B6"].value==note
    assert "B6:F6" not in {str(r) for r in sheet.merged_cells.ranges}
    assert sheet.row_dimensions[6].height is None
    config=cs.read(result["export_ref"])["payload"]["export_config"]
    assert config["annotation_layout_unverified_rows"]==[{"sheet":"数量费用","row":6}]
    assert "single-row print fit is unverified" in config["limitation"]


def test_legacy_profile_keeps_existing_annotation_cells_and_layout(ws):
    _,_,sheet=fixture(ws,"Literal existing note",expression="report-expression-v1")
    assert sheet["A6"].value=="Note" and sheet["B6"].value=="Literal existing note"
    assert not sheet.merged_cells.ranges and sheet.row_dimensions[6].height is None


def test_two_column_data_is_not_mistaken_for_annotation_and_newlines_get_height(ws):
    from test_content_workbook import prepared
    ws.store.set("manifest", {**ws.store.manifest, "report_expression_profile":"reader-expression-v2"})
    cs,actor,_,snapshot,sheets=prepared(ws,"=1+1")
    table=cs.read(sheets[0]["table_ref"])
    # The seeded table has an actual two-column row; it is never an annotation.
    result=export_workbook(cs,actor,"two-column-proof",snapshot,sheets)["result"]
    book=load_workbook(BytesIO((ws.store.root/result["file_ref"]).read_bytes()))
    assert not book.active.merged_cells.ranges
    assert book.active["A3"].value=="=1+1"
    assert book.active["A3"].data_type=="s" and book.active.row_dimensions[3].height is None
    assert cs.read(sheets[0]["table_ref"])==table


def test_explicit_multiline_qualifier_uses_all_lines(ws):
    cs,actor,refs,_,members=seed(ws)
    ws.store.set("manifest", {**ws.store.manifest,"report_expression_profile":"reader-expression-v2"})
    qualifier="第一项限定\n第二项限定\n第三项限定"
    added=cs.commit(actor,"multiline",[{"client_key":"table","type":"ContentNode","payload":{
        "kind":"table","body":{"columns":["甲","乙","丙"],"rows":[[1,2,3]]},
        "qualifiers":{"范围":qualifier},"claim_kind":"structure"}},
        {"client_key":"edge","type":"Relation","payload":{"subject_ref":refs["root"],
         "object_ref":{"client_key":"table"},"predicate":"contains","position":1,
         "provenance_kind":"adopted_during_generation"}}])["result"]["refs"]
    snapshot=cs.freeze(actor,"multiline-snapshot",refs["root"],[*members,*added.values()])["result"]["snapshot_ref"]
    result=export_workbook(cs,actor,"multiline-xlsx",snapshot,[{"name":"说明","table_ref":added["table"]}])["result"]
    book=load_workbook(BytesIO((ws.store.root/result["file_ref"]).read_bytes()))
    assert book.active["B1"].value==qualifier
    assert book.active.row_dimensions[1].height>=56
    assert "B1:C1" in {str(r) for r in book.active.merged_cells.ranges}


def test_native_calibrated_wide_latin_label_and_note_have_room_for_tail(ws):
    # Actual Excel PDF before repair clipped these tails at heights 104/24.
    _,_,sheet=fixture(ws,"W"*100+"尾标",label="W"*110+"标签尾标")
    assert sheet["A1"].value.endswith("标签尾标") and sheet["B6"].value.endswith("尾标")
    assert sheet.row_dimensions[1].height>=136
    assert sheet.row_dimensions[6].height>=40
