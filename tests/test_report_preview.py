"""Real offline DOCX evidence checks; no model, rendering or engineering verdict."""

import hashlib
from io import BytesIO
import json
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches
import pytest

from report_agent.errors import ActionRejected
from report_agent import report_preview as preview
from report_agent.store import Store
from report_agent.workspace import Workspace


def saved_workspace(root, body="# Heading\nBefore\n\n| Item | Value |\n| --- | --- |\n| Last | 42 |\n\nAfter"):
    store = Store(root)
    store.initialize({"goal": "Preview testing only", "sources": [
        {"id": "source", "title": "Synthetic evidence", "content": "42", "coverage": "complete"},
    ]})
    ws = Workspace(store)
    ws.initialize()
    task = ws.request_task("draft", "Compile", [])
    draft = ws.submit(task["id"], actor=task["owner"], title="Preview title", body=body,
                      source_ids=["source"], input_ids=[])
    return ws, draft


def state(ws):
    return ws.tasks(), ws.results(), ws.status(), ws.store.events()


def test_real_export_hash_counts_read_order_and_no_approval(tmp_path):
    ws, draft = saved_workspace(tmp_path)
    before = state(ws)
    result = preview.preview_saved_report(ws, draft["id"])
    path = Path(result["docx"]["path"])
    assert path.is_relative_to(tmp_path / "previews" / result["preview_version"])
    data = path.read_bytes()
    assert hashlib.sha256(data).hexdigest() == result["docx"]["sha256"]
    assert result["draft_body_sha256"] == hashlib.sha256(draft["body"].encode()).hexdigest()
    doc = Document(BytesIO(data))
    assert result["counts"]["body_paragraphs"] == len(doc.paragraphs)
    assert result["counts"]["paragraphs"] == len(doc.element.body.xpath(".//w:p"))
    assert result["counts"]["tables"] == len(doc.tables) == 1
    assert result["counts"]["images"] == 0
    assert any(h["text"] == "Heading" for h in result["headings"])
    assert result["cover"]["title_count"] >= 1
    assert "text" not in result["text"]
    assert result["render"]["status"] == "render_unavailable"
    assert result["render"]["page_count"] is None
    assert result["render"]["visual_verification"] == "not_performed"
    text, offset = "", 0
    while True:
        chunk = preview.read_preview(ws, draft["id"], offset, 2)
        assert chunk["preview_version"] == result["preview_version"]
        assert chunk["physical_page_numbers"] is None
        text += chunk["text"]
        offset = chunk["next_offset"]
        if offset is None:
            break
    assert "Before\nItem\nValue\nLast\n42\nAfter" in text
    assert hashlib.sha256(text.encode()).hexdigest() == result["text"]["sha256"]
    assert before == state(ws)


def field(paragraph, instruction, simple=False):
    if simple:
        node = OxmlElement("w:fldSimple")
        node.set(qn("w:instr"), instruction)
        paragraph._p.append(node)
        return
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    paragraph.add_run()._r.append(begin)
    for part in (instruction[:2], instruction[2:]):
        node = OxmlElement("w:instrText")
        node.text = part
        paragraph.add_run()._r.append(node)
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    paragraph.add_run()._r.append(end)


def rich_docx():
    import base64

    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Inches(8.27), Inches(11.69)
    section.different_first_page_header_footer = True
    doc.add_heading("Cover title", 0)
    doc.add_page_break()
    field(doc.add_paragraph(), ' TOC \\o "1-3" \\h ')
    field(doc.add_paragraph(), 'TOC \\o "1-2"', simple=True)
    doc.add_heading("Evidence heading", 1)
    doc.add_paragraph("\u4e2d\u6587\u8bc1\u636e")
    section.header.paragraphs[0].text = "Header evidence"
    field(section.footer.paragraphs[0], "PAGE", simple=True)
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a19sAAAAASUVORK5CYII=")
    doc.add_picture(BytesIO(png), width=Inches(0.2))
    output = BytesIO()
    doc.save(output)
    return output.getvalue()


def test_actual_ooxml_cover_toc_fields_headers_footers_image_and_sections(tmp_path, monkeypatch):
    ws, draft = saved_workspace(tmp_path)
    monkeypatch.setattr(preview, "export_docx", lambda *args: rich_docx())
    result = preview.preview_saved_report(ws, draft["id"])
    assert result["counts"]["images"] == result["counts"]["media_files"] == 1
    assert result["counts"]["headings"] == 1
    assert result["toc"]["field_count"] == 2
    assert result["toc"]["updated_or_paginated"] == "unknown_without_rendering"
    assert result["sections"][0]["different_first_page"] is True
    assert result["sections"][0]["page_size_twips"]["w"] == "11909"
    assert result["pagination_markers"]["explicit_page_breaks"] == 1
    assert result["headers"][0]["text_excerpt"] == "Header evidence"
    assert result["footers"][0]["fields"] == ["PAGE"]
    assert "\u4e2d\u6587\u8bc1\u636e" in preview.read_preview(ws, draft["id"])["text"]


def test_same_bytes_reuse_version_new_bytes_preserve_previous(tmp_path, monkeypatch):
    ws, draft = saved_workspace(tmp_path)
    data = rich_docx()
    monkeypatch.setattr(preview, "export_docx", lambda *args: data)
    one = preview.preview_saved_report(ws, draft["id"])
    assert preview.preview_saved_report(ws, draft["id"])["preview_version"] == one["preview_version"]
    changed = Document(BytesIO(data))
    changed.add_paragraph("New export state")
    buffer = BytesIO()
    changed.save(buffer)
    data = buffer.getvalue()
    two = preview.preview_saved_report(ws, draft["id"])
    assert one["preview_version"] != two["preview_version"]
    assert Path(one["docx"]["path"]).exists()
    assert preview.read_preview(ws, draft["id"])["preview_version"] == two["preview_version"]


def test_pinned_old_preview_survives_new_export_without_latest_index(tmp_path, monkeypatch):
    ws, draft = saved_workspace(tmp_path)
    data = rich_docx()
    monkeypatch.setattr(preview, "export_docx", lambda *args: data)
    old = preview.preview_saved_report(ws, draft["id"])
    first = preview.read_preview(ws, draft["id"], 0, 2, preview_version=old["preview_version"])
    changed = Document(BytesIO(data))
    changed.add_paragraph("Only in the new export")
    buffer = BytesIO()
    changed.save(buffer)
    data = buffer.getvalue()
    new = preview.preview_saved_report(ws, draft["id"])
    assert new["preview_version"] != old["preview_version"]
    assert "Only in the new export" in preview.read_preview(ws, draft["id"])["text"]
    next((tmp_path / "previews").glob("*.json")).unlink()
    monkeypatch.setattr(preview, "export_docx", lambda *args: pytest.fail("reading must not export"))
    text, offset = first["text"], first["next_offset"]
    while offset is not None:
        part = preview.read_preview(ws, draft["id"], offset, 2, preview_version=old["preview_version"])
        assert part["preview_version"] == old["preview_version"]
        assert part["docx_sha256"] == old["docx"]["sha256"]
        assert part["text_sha256"] == old["text"]["sha256"]
        text += part["text"]
        offset = part["next_offset"]
    assert "Only in the new export" not in text
    assert hashlib.sha256(text.encode()).hexdigest() == old["text"]["sha256"]


@pytest.mark.parametrize("version", ["../../outside", "0" * 64 + "-" + "0" * 64, None, False, 7])
def test_pinned_version_rejects_invalid_or_other_draft_identity(tmp_path, version):
    ws, draft = saved_workspace(tmp_path)
    preview.preview_saved_report(ws, draft["id"])
    with pytest.raises(ActionRejected, match="PREVIEW_INVALID_VERSION"):
        preview.read_preview(ws, draft["id"], preview_version=version)


def test_missing_pinned_snapshot_does_not_fall_back_to_latest(tmp_path):
    ws, draft = saved_workspace(tmp_path)
    current = preview.preview_saved_report(ws, draft["id"])
    nonexistent = current["preview_version"][:65] + "0" * 64
    with pytest.raises(ActionRejected, match="PREVIEW_SNAPSHOT_NOT_FOUND"):
        preview.read_preview(ws, draft["id"], preview_version=nonexistent)


def test_unicode_long_blocks_are_bounded_and_lossless(tmp_path):
    ws, draft = saved_workspace(tmp_path, "\u4e2d" * 2500 + "\nTail")
    result = preview.preview_saved_report(ws, draft["id"])
    contents, offset = [], 0
    while offset is not None:
        part = preview.read_preview(ws, draft["id"], offset, 1)
        assert len(part["text"]) <= preview.BLOCK_CHARACTERS
        contents.append(part["text"])
        offset = part["next_offset"]
    assert hashlib.sha256("".join(contents).encode()).hexdigest() == result["text"]["sha256"]
    assert preview.read_preview(ws, draft["id"], result["text"]["blocks"])["text"] == ""


@pytest.mark.parametrize("offset,limit", [(-1, 1), (0, 0), (0, 101), (True, 3), (1.5, 2), (0, "3")])
def test_invalid_ranges(tmp_path, offset, limit):
    ws, draft = saved_workspace(tmp_path)
    with pytest.raises(ActionRejected, match="PREVIEW_INVALID_RANGE"):
        preview.read_preview(ws, draft["id"], offset, limit)


def test_no_preview_and_out_of_range(tmp_path):
    ws, draft = saved_workspace(tmp_path)
    with pytest.raises(ActionRejected, match="PREVIEW_NOT_FOUND"):
        preview.read_preview(ws, draft["id"])
    result = preview.preview_saved_report(ws, draft["id"])
    with pytest.raises(ActionRejected, match="PREVIEW_OFFSET_OUT_OF_RANGE"):
        preview.read_preview(ws, draft["id"], result["text"]["blocks"] + 1)


def test_reject_other_projects_non_drafts_and_paths_before_export(tmp_path, monkeypatch):
    ws, draft = saved_workspace(tmp_path / "one")
    other, _ = saved_workspace(tmp_path / "two")
    task = ws.request_task("materials", "Evidence", [])
    result = ws.submit(task["id"], actor=task["owner"], title="Evidence", body="42", source_ids=["source"], input_ids=[])
    monkeypatch.setattr(preview, "export_docx", lambda *args: pytest.fail("must reject before export"))
    for workspace, identifier, error in [(other, draft["id"], "RESULT_NOT_IN_PROJECT"),
                                         (ws, "../../outside", "RESULT_NOT_IN_PROJECT"),
                                         (ws, result["id"], "PREVIEW_REQUIRES_SAVED_DRAFT")]:
        with pytest.raises(ActionRejected, match=error):
            preview.preview_saved_report(workspace, identifier)
        with pytest.raises(ActionRejected, match=error):
            preview.read_preview(workspace, identifier)


@pytest.mark.parametrize("name", ["text.txt", "report.docx"])
def test_detect_corrupted_preview(tmp_path, name):
    ws, draft = saved_workspace(tmp_path)
    result = preview.preview_saved_report(ws, draft["id"])
    (Path(result["docx"]["path"]).parent / name).write_bytes(b"tampered")
    with pytest.raises(ActionRejected, match="PREVIEW_INTEGRITY_MISMATCH"):
        preview.read_preview(ws, draft["id"])


def test_reject_symlink_outside_workspace(tmp_path):
    ws, draft = saved_workspace(tmp_path / "project")
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (ws.store.root / "previews").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(ActionRejected, match="PREVIEW_PATH_OUTSIDE_PROJECT"):
        preview.preview_saved_report(ws, draft["id"])
    assert not list(outside.iterdir())


def test_reject_tampered_version_path(tmp_path):
    ws, draft = saved_workspace(tmp_path)
    preview.preview_saved_report(ws, draft["id"])
    index = next((tmp_path / "previews").glob("*.json"))
    index.write_text(json.dumps({"version": "../../outside"}))
    with pytest.raises(ActionRejected, match="PREVIEW_INVALID_VERSION"):
        preview.read_preview(ws, draft["id"])


def test_export_failure_keeps_previous_snapshot(tmp_path, monkeypatch):
    ws, draft = saved_workspace(tmp_path)
    old = preview.preview_saved_report(ws, draft["id"])

    def fail(*args):
        raise RuntimeError("export failed")

    monkeypatch.setattr(preview, "export_docx", fail)
    with pytest.raises(RuntimeError, match="export failed"):
        preview.preview_saved_report(ws, draft["id"])
    assert preview.read_preview(ws, draft["id"])["preview_version"] == old["preview_version"]


def test_concurrent_same_snapshot_is_complete(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    ws, draft = saved_workspace(tmp_path)
    data = rich_docx()
    monkeypatch.setattr(preview, "export_docx", lambda *args: data)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: preview.preview_saved_report(ws, draft["id"]), range(6)))
    assert len({r["preview_version"] for r in results}) == 1
    assert Path(results[0]["docx"]["path"]).read_bytes() == data
    assert preview.read_preview(ws, draft["id"])["preview_version"] == results[0]["preview_version"]
    assert not list((tmp_path / "previews").rglob(".preview-*"))


@pytest.mark.parametrize("role", ["coordinator", "writer", "reviewer"])
def test_runtime_wrapper_default_pagination_is_compatible(tmp_path, role):
    from report_agent.deep_runtime import business_tools

    ws, draft = saved_workspace(tmp_path)
    tools = business_tools(ws, role, knowledge=None, text_model=None)
    tool = next(t for t in tools if t.__name__ == "preview_report")
    before = state(ws)
    result = tool(draft["id"])
    assert result["content"]["limit"] == 30
    assert result["content"]["unit"] == "text_blocks"
    assert result["content"]["preview_version"] == result["preview"]["preview_version"]
    assert before == state(ws)
