"""Template and restricted page-image integration, using temporary synthetic reports."""

import base64
import hashlib
from io import BytesIO
from urllib.parse import quote
from zipfile import ZipFile

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Mm
import pytest

from report_agent import document_tools
from report_agent.exporting import export_docx
from report_agent.store import Store
from report_agent.workspace import Workspace


PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX1kAAAAASUVORK5CYII=")


@pytest.fixture
def ws(tmp_path):
    store = Store(tmp_path)
    store.initialize({"goal": "Compile supplied material only", "sources": [
        {"id": "source", "title": "Project original", "coverage": "partial", "content": "Original evidence",
         "limitations": ["Unverified appendix"]},
        {"id": "source_Upper-2", "title": "Original page sheet", "coverage": "complete", "content": "Evidence"},
        {"id": "\u539f\u4ef6 A", "title": "Encoded source ID", "coverage": "complete", "content": "Evidence"},
    ]})
    workspace = Workspace(store)
    workspace.initialize()
    return workspace


def save(ws, body="# Heading\n\nSaved **content**."):
    task = ws.request_task("draft", f"Compile {len(ws.tasks())}", [])
    return ws.submit(task["id"], actor=task["owner"], title="Technical report", body=body,
                     source_ids=["source"], input_ids=[])


def export(ws, draft, **options):
    return Document(BytesIO(export_docx(ws, draft["id"], **options)))


def text(doc):
    return "\n".join(p.text for p in doc.paragraphs)


def test_default_legacy_and_explicit_override_remain_compatible(ws):
    draft = save(ws)
    legacy = export(ws, draft)
    assert "Saved **content**." in text(legacy)
    assert "Unreviewed draft; not approved." in text(legacy)
    assert len(legacy.sections) == 1
    manifest = ws.store.manifest
    manifest["export"] = {"template": "technical_zh", "metadata": {"organization": "Supplied unit"}}
    ws.store.set("manifest", manifest)
    assert "Supplied unit" in text(export(ws, draft))
    assert "Saved **content**." in text(export(ws, draft, template="legacy"))


def test_technical_geometry_fonts_cover_toc_header_footer_and_no_fake_approval(ws):
    draft = save(ws)
    doc = export(ws, draft, template="technical_zh", metadata={"organization": "Known unit", "date": "2026-09-28", "project_name": "Known project"})
    for section in doc.sections:
        for actual, expected in ((section.page_width, Mm(210)), (section.page_height, Mm(297)),
                                 (section.top_margin, Mm(25)), (section.bottom_margin, Mm(25)),
                                 (section.left_margin, Mm(25)), (section.right_margin, Mm(15)),
                                 (section.gutter, 0)):
            assert abs(actual - expected) < 1000
    for name in ("Normal", "Title", "Heading 1", "Heading 3", "Header", "Footer"):
        style = doc.styles[name]
        assert style.font.name == ("\u5b8b\u4f53" if name == "Header" else "Times New Roman")
        assert style.element.rPr.rFonts.get(qn("w:eastAsia")) == "\u5b8b\u4f53"
    content = text(doc)
    assert content.count("Known unit") == 2
    assert sum(p.text == "\u7f16\u5236\u65e5\u671f\uff1a2026-09-28" for p in doc.paragraphs) == 2
    assert "\u6249\u9875" in content and "\u76ee\u5f55" in content
    assert "\u672a\u7ecf\u5de5\u7a0b\u6279\u51c6" in content
    assert "\u5f85\u586b\u5199" in content
    assert ' TOC \\o "1-3" \\h \\z \\u ' in doc.element.xpath(".//w:instrText/text()")
    assert doc.settings.element.find(qn("w:updateFields")).get(qn("w:val")) == "true"
    assert doc.sections[0].header.paragraphs[0].text == ""
    header = doc.sections[-1].header.paragraphs[0]
    assert header.text == "Known project\t" + draft["title"]
    assert header._p.xpath('./w:pPr/w:tabs/w:tab[@w:val="right"]')
    assert " PAGE " in doc.sections[-1].footer._element.xpath(".//w:instrText/text()")
    assert doc.sections[-1].footer.paragraphs[0].text == ""
    assert doc.sections[-1].footer.paragraphs[0].alignment == WD_ALIGN_PARAGRAPH.CENTER
    assert doc.styles["Header"].font.size.pt == doc.styles["Footer"].font.size.pt == 9
    normal = doc.styles["Normal"]
    assert normal.font.size.pt == 12
    assert normal.paragraph_format.line_spacing == 1.5
    assert normal.paragraph_format.alignment == WD_ALIGN_PARAGRAPH.JUSTIFY
    assert normal.element.pPr.ind.get(qn("w:firstLineChars")) == "200"


def test_unknown_metadata_stays_unfilled_and_manifest_defaults_are_not_mutated(ws):
    draft = save(ws)
    manifest = ws.store.manifest
    manifest["export"] = {"template": "technical_zh", "metadata": {"organization": "Default unit", "date": ""}}
    ws.store.set("manifest", manifest)
    doc = export(ws, draft, metadata={"organization": "Supplied unit"})
    assert "Default unit" not in text(doc)
    assert "\u7f16\u5236\u65e5\u671f\uff1a\u5f85\u586b\u5199" in text(doc)
    assert ws.store.manifest == manifest


@pytest.mark.parametrize("explicit_scope", ["Original business scope only", ""])
@pytest.mark.parametrize("scope_instruction", ["Fallback business scope", {"text": "Fallback business scope", "filename": "PRIVATE-scope.md"}])
def test_reader_explicit_scope_never_exposes_revision_goal(ws, explicit_scope, scope_instruction):
    draft = save(ws)
    manifest = ws.store.manifest
    manifest["goal"] = "PRIVATE defect feedback and tool testing instructions"
    manifest["scope_instruction"] = scope_instruction
    manifest["export"] = {"template": "technical_zh", "metadata": {"scope": explicit_scope}}
    ws.store.set("manifest", manifest)
    content = text(export(ws, draft))
    assert "PRIVATE" not in content and "Fallback business scope" not in content
    assert "\u7f16\u5236\u8303\u56f4\uff1a" in content
    assert not explicit_scope or "\u7f16\u5236\u8303\u56f4\uff1a\n" + explicit_scope in content
    assert ws.store.manifest == manifest
    assert "PRIVATE" in text(export(ws, draft, template="legacy"))


@pytest.mark.parametrize("scope_instruction", [
    "Business scope instruction",
    {"text": "Business scope instruction", "filename": "PRIVATE-scope.md", "copied_path": "sources/PRIVATE-scope.md"},
])
def test_reader_scope_instruction_fallback_and_api_override(ws, scope_instruction):
    draft = save(ws)
    manifest = ws.store.manifest
    manifest["goal"] = "PRIVATE revision instructions"
    manifest["scope_instruction"] = scope_instruction
    ws.store.set("manifest", manifest)
    content = text(export(ws, draft, template="technical_zh"))
    assert "Business scope instruction" in content and "PRIVATE" not in content
    content = text(export(ws, draft, template="technical_zh", metadata={"scope": "Explicit API scope"}))
    assert "Explicit API scope" in content and "Business scope instruction" not in content and "PRIVATE" not in content
    assert ws.store.manifest == manifest


@pytest.mark.parametrize("scope_instruction", [{"filename": "PRIVATE-scope.md"}, {"text": ""}])
def test_reader_empty_scope_record_falls_back_to_goal(ws, scope_instruction):
    draft = save(ws)
    manifest = ws.store.manifest
    manifest["scope_instruction"] = scope_instruction
    ws.store.set("manifest", manifest)
    content = text(export(ws, draft, template="technical_zh"))
    assert "\u7f16\u5236\u8303\u56f4\uff1a\n" + manifest["goal"] in content
    assert "PRIVATE" not in content


def test_scope_markdown_preserves_content_without_adding_toc_headings(ws):
    scope = "# Scope heading\n\nFirst **important** line\nsecond *emphasized* line.\n\n- Required item\n\n> Quoted requirement\n\n| Scope item | Value |\n| --- | --- |\n| A | 12 |"
    draft = save(ws, "# Report heading\n\nSaved report **content**.")
    manifest = ws.store.manifest
    manifest["goal"] = "PRIVATE internal revision instructions"
    manifest["scope_instruction"] = {"text": scope, "filename": "PRIVATE-scope.md"}
    ws.store.set("manifest", manifest)
    before = (ws.results(), ws.tasks(), ws.store.events(), ws.store.manifest)
    doc = export(ws, draft, template="technical_zh")
    content = text(doc)
    assert "PRIVATE" not in content and "# Scope heading" not in content and "**" not in content
    heading = next(p for p in doc.paragraphs if p.text == "Scope heading")
    assert heading.style.name == "Normal"
    assert heading.runs[0].bold and heading.paragraph_format.keep_with_next
    assert not heading._p.xpath("./w:pPr/w:outlineLvl")
    assert next(p for p in doc.paragraphs if p.text == "Report heading").style.name == "Heading 1"
    p = next(p for p in doc.paragraphs if p.text.startswith("First important"))
    assert p.text == "First important line\nsecond emphasized line."
    assert next(r for r in p.runs if r.text == "important").bold
    assert next(r for r in p.runs if r.text == "emphasized").italic
    item = next(p for p in doc.paragraphs if p.text == "Required item")
    assert item._p.xpath("./w:pPr/w:numPr")
    assert "Quoted requirement" in content
    assert doc.tables[0].cell(1, 1).text == "12"
    assert before == (ws.results(), ws.tasks(), ws.store.events(), ws.store.manifest)


def test_technical_soft_break_compatibility_keeps_breaks_and_legacy_unchanged(ws):
    body = "First line\nSecond line  \nThird line"
    draft = save(ws, body)
    doc = export(ws, draft, template="technical_zh")
    flags = doc.settings.element.xpath("./w:compat/w:doNotExpandShiftReturn")
    assert len(flags) == 1 and flags[0].get(qn("w:val")) == "true"
    p = next(p for p in doc.paragraphs if p.text.startswith("First line"))
    assert p.text == "First line\nSecond line\nThird line"
    assert len(p._p.xpath(".//w:br")) == 2
    assert doc.styles["Normal"].paragraph_format.alignment == WD_ALIGN_PARAGRAPH.JUSTIFY
    legacy = export(ws, draft, template="legacy")
    assert not legacy.settings.element.xpath("./w:compat/w:doNotExpandShiftReturn")
    assert ws.result(draft["id"])["body"] == body


@pytest.mark.parametrize("options", [
    {"template": "unrecognized"}, {"metadata": {"approved_by": "Fake reviewer"}},
    {"metadata": {"date": 2026}},
])
def test_invalid_template_or_approval_metadata_rejected(ws, options):
    with pytest.raises(ValueError):
        export(ws, save(ws), **options)


def test_markdown_strong_emphasis_lists_order_start_restart_and_table(ws):
    body = """# **Heading**

Normal **strong** and *emphasis*.

3. First
4. Second
   - Nested **bullet**

Separated paragraph.

1. Restarted

| Header | Value |
| --- | --- |
| **Total** | 12 |
"""
    doc = export(ws, save(ws, body), template="technical_zh")
    p = next(p for p in doc.paragraphs if p.text == "Normal strong and emphasis.")
    assert next(r for r in p.runs if r.text == "strong").bold
    assert next(r for r in p.runs if r.text == "emphasis").italic
    assert "**" not in text(doc)
    numbered = {p.text: p for p in doc.paragraphs if p._p.xpath("./w:pPr/w:numPr")}
    assert set(numbered) == {"First", "Second", "Nested bullet", "Restarted"}
    ids = {k: p._p.pPr.numPr.numId.val for k, p in numbered.items()}
    assert ids["First"] == ids["Second"] != ids["Restarted"]
    assert numbered["Nested bullet"].paragraph_format.left_indent > numbered["First"].paragraph_format.left_indent
    numbering = doc.part.numbering_part.element
    num = numbering.xpath(f'./w:num[@w:numId="{ids["First"]}"]')[0]
    abstract = numbering.xpath(f'./w:abstractNum[@w:abstractNumId="{num.abstractNumId.val}"]')[0]
    assert abstract.find(qn("w:lvl")).find(qn("w:start")).get(qn("w:val")) == "3"
    assert doc.tables[0].cell(1, 0).text == "Total"
    assert doc.tables[0].rows[0]._tr.xpath("./w:trPr/w:tblHeader")
    assert all(row._tr.xpath("./w:trPr/w:cantSplit") for row in doc.tables[0].rows)


def test_reader_business_issues_without_technical_audit_and_no_mutations(ws):
    draft = save(ws)
    ws.issue("source_conflict", "Height remains unconfirmed", ["source"])
    technical = ws.issue("system_failure", "PRIVATE technical recovery traceback", [])
    ws.decide_issue(technical["id"], "PRIVATE Main recovery instructions", resolved=True)
    resolved = ws.issue("source_missing", "Previously missing file", ["source"])
    ws.decide_issue(resolved["id"], "Supplied", resolved=True)
    before = (ws.results(), ws.tasks(), ws.store.events(), ws.store.get("report_issues"))
    doc = export(ws, draft, template="technical_zh")
    content = text(doc)
    assert "Height remains unconfirmed" in content
    assert "PRIVATE" not in content and "system_failure" not in content and "Resolved:" not in content
    assert "Previously missing file" not in content
    assert "[source] Project original" in content
    assert "Unverified appendix" in content
    assert "Draft: " + draft["id"] in content
    assert before == (ws.results(), ws.tasks(), ws.store.events(), ws.store.get("report_issues"))
    legacy = text(export(ws, draft))
    assert "PRIVATE Main recovery instructions" in legacy


@pytest.mark.parametrize("template", ["legacy", "technical_zh"])
def test_selected_page_embeds_exact_bytes_caption_source_and_version(ws, monkeypatch, template):
    calls = []

    def page(workspace, source_id, number):
        calls.append((workspace, source_id, number))
        return PNG

    monkeypatch.setattr(document_tools, "source_page_png", page)
    body = "Before\n\n![Selected detail](source-page://source_Upper-2/3)\n\nAfter"
    draft = save(ws, body)
    before = (ws.results(), ws.tasks(), ws.store.events())
    blob = export_docx(ws, draft["id"], template=template)
    doc = Document(BytesIO(blob))
    assert calls == [(ws, "source_Upper-2", 3)]
    assert len(doc.inline_shapes) == 1
    with ZipFile(BytesIO(blob)) as package:
        images = [name for name in package.namelist() if name.startswith("word/media/")]
        assert len(images) == 1 and package.read(images[0]) == PNG
    assert "Selected detail [source_Upper-2] Original page sheet, PDF physical page 3" in text(doc)
    assert "[source_Upper-2] Original page sheet; coverage: complete" in text(doc)
    assert before == (ws.results(), ws.tasks(), ws.store.events())
    assert ws.result(draft["id"])["body"] == body
    section = doc.sections[-1]
    assert doc.inline_shapes[0].width <= section.page_width - section.left_margin - section.right_margin
    assert doc.inline_shapes[0].height < section.page_height - section.top_margin - section.bottom_margin


def test_encoded_source_id_matches_main_tool_reference_contract(ws, monkeypatch):
    calls = []
    monkeypatch.setattr(document_tools, "source_page_png", lambda workspace, source, page: calls.append((source, page)) or PNG)
    draft = save(ws, f"![Original](source-page://{quote(chr(0x539f) + chr(0x4ef6) + ' A', safe='')}/1)")
    assert len(export(ws, draft, template="technical_zh").inline_shapes) == 1
    assert calls == [("\u539f\u4ef6 A", 1)]


def test_repeated_table_image_uses_scoped_tool_once_and_fits_cell(ws, monkeypatch):
    calls = []
    monkeypatch.setattr(document_tools, "source_page_png", lambda *args: calls.append(args) or PNG)
    image = "![Caption](source-page://source/1)"
    doc = export(ws, save(ws, f"| Figure | Note |\n| --- | --- |\n| {image} | {image} |"), template="technical_zh")
    assert len(doc.inline_shapes) == 2 and len(calls) == 1
    assert all(shape.width < doc.tables[0].cell(1, 0).width for shape in doc.inline_shapes)


@pytest.mark.parametrize("reference", [
    "https://example.test/image.png", "http://127.0.0.1/private", "/etc/passwd",
    "../../private.png", "source-page://source/0", "source-page://source/-1", "source-page://source/1.5",
    "source-page://source/1?file=x", "source-page://source/1#fragment", "source-page://../1",
    "source-page://%2e%2e/1", "source-page://source@foreign/1", "source-page://source/1/other",
])
def test_arbitrary_locations_and_invalid_refs_never_reach_renderer(ws, monkeypatch, reference):
    monkeypatch.setattr(document_tools, "source_page_png", lambda *a: pytest.fail("Unsafe reference reached renderer"))
    with pytest.raises(ValueError, match="EXPORT_IMAGE_REQUIRES_SOURCE_PAGE_REFERENCE"):
        export(ws, save(ws, f"![Do not fetch]({reference})"), template="technical_zh")


def test_foreign_source_and_render_failures_are_not_silently_dropped(ws, monkeypatch):
    monkeypatch.setattr(document_tools, "source_page_png", lambda *a: pytest.fail("Foreign source reached renderer"))
    with pytest.raises(ValueError, match="SOURCE_NOT_IN_PROJECT"):
        export(ws, save(ws, "![Foreign](source-page://foreign/1)"), template="technical_zh")

    def unavailable(*args):
        raise ValueError("SOURCE_PAGE_OUT_OF_RANGE")

    monkeypatch.setattr(document_tools, "source_page_png", unavailable)
    with pytest.raises(ValueError, match="SOURCE_PAGE_OUT_OF_RANGE"):
        export(ws, save(ws, "![Invalid page](source-page://source/99)"), template="technical_zh")
    monkeypatch.setattr(document_tools, "source_page_png", lambda *a: b"not a PNG")
    with pytest.raises(ValueError, match="SOURCE_PAGE_PNG_REQUIRED"):
        export(ws, save(ws, "![Invalid bytes](source-page://source/1)"), template="technical_zh")


def test_no_images_means_no_original_page_tool_calls(ws, monkeypatch):
    monkeypatch.setattr(document_tools, "source_page_png", lambda *a: pytest.fail("Unrequested image"))
    doc = export(ws, save(ws), template="technical_zh")
    assert not doc.inline_shapes


def test_parser_rejected_file_images_remain_inert_text(ws, monkeypatch):
    monkeypatch.setattr(document_tools, "source_page_png", lambda *a: pytest.fail("Local file access"))
    body = "![Not an allowed Markdown image](file:///etc/passwd)"
    doc = export(ws, save(ws, body), template="technical_zh")
    assert not doc.inline_shapes
    assert body in text(doc)


def test_actual_project_pdf_page_tool_embeds_without_changing_original(tmp_path):
    from test_ingestion import pdf_bytes

    data = pdf_bytes(("Synthetic first page", "Synthetic selected page"))
    sources = tmp_path / "sources"
    sources.mkdir()
    path = sources / "original.pdf"
    path.write_bytes(data)
    store = Store(tmp_path)
    store.initialize({"goal": "Synthetic export integration", "sources": [
        {"id": "source", "title": "Synthetic original", "filename": "original.pdf",
         "content": "Existing text stays unchanged", "coverage": "complete",
         "copied_path": "sources/original.pdf", "sha256": hashlib.sha256(data).hexdigest()},
    ]})
    ws = Workspace(store)
    ws.initialize()
    reference = document_tools.source_page_info(ws, "source", 2)["image_ref"]
    draft = save(ws, f"![Selected original page]({reference})")
    before = (ws.results(), ws.tasks(), ws.store.events(), ws.store.manifest)
    doc = export(ws, draft, template="technical_zh")
    assert len(doc.inline_shapes) == 1
    assert "Selected original page [source] Synthetic original, PDF physical page 2" in text(doc)
    assert path.read_bytes() == data
    assert before == (ws.results(), ws.tasks(), ws.store.events(), ws.store.manifest)


def test_model_accepted_remains_not_engineering_approved_and_version_exact(ws):
    draft = save(ws)
    task = ws.request_task("review", "Review exact draft", [draft["id"]])
    ws.record_read(task["id"], result_ids=[draft["id"]])
    review = ws.submit(task["id"], actor=task["owner"], title="Review", body="Synthetic review only",
                       source_ids=[], input_ids=[draft["id"]], target_id=draft["id"], outcome="accepted")
    doc = export(ws, draft, template="technical_zh")
    assert "\u6a21\u578b\u5ba1\u6838\u901a\u8fc7\u7684\u8349\u7a3f\uff1b\u672a\u7ecf\u5de5\u7a0b\u6279\u51c6" in text(doc)
    assert "Review: " + review["id"] in text(doc)
    newer = save(ws, "New saved version")
    assert "\u672a\u5ba1\u6838\u8349\u7a3f\uff1b\u672a\u7ecf\u5de5\u7a0b\u6279\u51c6" in text(export(ws, newer, template="technical_zh"))
