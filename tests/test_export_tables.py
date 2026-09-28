"""Offline DOCX formatting checks using synthetic, temporary saved reports only."""

from io import BytesIO

import pytest
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Mm, Pt

from report_agent.exporting import _add_body, _add_markdown, _technical_template, export_docx
from report_agent.store import Store
from report_agent.workspace import Workspace


def render(body):
    doc = Document()
    _add_body(doc, body)
    output = BytesIO()
    doc.save(output)
    return Document(BytesIO(output.getvalue()))


def table_text(table):
    return [[cell.text for cell in row.cells] for row in table.rows]


def render_technical(body):
    doc = Document()
    _technical_template(doc, {"title": "Synthetic report"}, {}, "Synthetic project")
    _add_markdown(doc, body, None)
    output = BytesIO()
    doc.save(output)
    return Document(BytesIO(output.getvalue()))


def test_technical_table_font_widths_and_identifiers_not_equal_columns():
    body = "| \u5e8f\u53f7 | \u6869\u53f7 | \u4fa7\u522b | \u5761\u9ad8 | \u7c7b\u578b | \u5206\u503c | \u7b49\u7ea7 | \u5907\u6ce8 |\n| --- | --- | --- | --- | --- | --- | --- | --- |\n| 1 | K1319+910\uff5eK1320+160 | \u5de6 | 26.0 | A | 73.25 | III | \u5f85\u6838\u5bf9 |"
    table = render_technical(body).tables[0]
    assert table.autofit is False
    widths = [column.width for column in table.columns]
    assert abs(sum(widths) - Mm(170)) < Mm(0.1)
    assert widths[1] > widths[0]
    assert widths[1] - Pt(14.4) >= Pt(len("K1319+910") * 6.3)
    assert table.cell(1, 1).text == "K1319+910\uff5eK1320+160"
    assert not table.cell(1, 1)._tc.xpath(".//w:br")
    for row in table.rows:
        for index, cell in enumerate(row.cells):
            assert cell.width == widths[index]
            assert cell.paragraphs[0].alignment == WD_ALIGN_PARAGRAPH.LEFT
            for run in cell.paragraphs[0].runs:
                assert run.font.size.pt == 10.5
                assert run.font.name == "Times New Roman"
                assert run._r.rPr.rFonts.get(qn("w:eastAsia")) == "\u5b8b\u4f53"
    assert table.rows[0]._tr.xpath("./w:trPr/w:tblHeader")
    assert all(row._tr.xpath("./w:trPr/w:cantSplit") for row in table.rows)
    assert render(body).tables[0].autofit is True
    assert render(body).tables[0].cell(1, 1).paragraphs[0].runs[0].font.size is None


def test_technical_caption_follows_table_without_business_title_rewriting():
    body = "# Report title\n\n# Report title\n\nTable A: unchanged caption\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n\nIntervening paragraph\n\nSecond caption\n\n| C |\n| --- |\n| 3 |\n\nAfter"
    doc = render_technical(body)
    assert sum(p.text == "Report title" for p in doc.paragraphs) == 2
    for caption in ("Table A: unchanged caption", "Second caption"):
        p = next(p for p in doc.paragraphs if p.text == caption)
        assert p.paragraph_format.keep_with_next is True
        assert p._p.getnext().tag == qn("w:tbl")
    for content in ("Intervening paragraph", "After"):
        assert next(p for p in doc.paragraphs if p.text == content).paragraph_format.keep_with_next is None


def test_technical_table_format_preserves_inline_breaks_and_surplus_fallback():
    body = "| Value | Note |\n| --- | --- |\n| **Total** | *first*<br>second\\|part |\n\n| A | B |\n| --- | --- |\n| one | two | KEEP SURPLUS |"
    doc = render_technical(body)
    assert len(doc.tables) == 1
    assert table_text(doc.tables[0]) == [["Value", "Note"], ["Total", "first\nsecond|part"]]
    assert next(r for r in doc.tables[0].cell(1, 0).paragraphs[0].runs if r.text == "Total").bold
    assert next(r for r in doc.tables[0].cell(1, 1).paragraphs[0].runs if r.text == "first").italic
    assert "| one | two | KEEP SURPLUS |" in [p.text for p in doc.paragraphs]


def test_oversized_identifiers_keep_text_and_font_without_exceeding_page_width():
    long_id = "A" * 160
    table = render_technical(f"| A | B |\n| --- | --- |\n| {long_id} | {long_id} |").tables[0]
    assert abs(sum(column.width for column in table.columns) - Mm(170)) < Mm(0.1)
    assert table_text(table)[1] == [long_id, long_id]
    assert all(run.font.size.pt == 10.5 for cell in table.rows[1].cells for run in cell.paragraphs[0].runs)


def test_native_table_and_body_order():
    doc = render("# Heading\nBefore\n\n| Item | Value |\n| --- | ---: |\n| A | 12 |\n| Total | 12 |\n\nAfter\n## Next")
    assert table_text(doc.tables[0]) == [["Item", "Value"], ["A", "12"], ["Total", "12"]]
    assert [p.text for p in doc.paragraphs] == ["Heading", "Before", "After", "Next"]
    assert [p.style.name for p in doc.paragraphs] == ["Heading 1", "Normal", "Normal", "Heading 2"]
    assert [e.tag.rsplit("}", 1)[-1] for e in doc.element.body] == ["p", "p", "tbl", "p", "p", "sectPr"]


def test_header_repeats_and_every_row_including_total_stays_together():
    body = "| Item | Value |\n| --- | --- |\n" + "| Detail | 1 |\n" * 60 + "| Total | 60 |"
    table = render(body).tables[0]
    for index, row in enumerate(table.rows):
        assert len(row._tr.xpath("./w:trPr/w:cantSplit")) == 1
        assert len(row._tr.xpath("./w:trPr/w:tblHeader")) == (1 if index == 0 else 0)
        for cell in row.cells:
            paragraph = cell.paragraphs[0]
            assert paragraph.paragraph_format.keep_together is True
            assert paragraph.paragraph_format.keep_with_next is (index == 0)
    assert table_text(table)[-1] == ["Total", "60"]


def test_escaped_pipes_and_inline_formatting():
    doc = render(r"""| Name | Note |
| --- | --- |
| **Bold** and *italic* | left\|right and `x\|y` |
| [Evidence](https://example.test/source) | &lt;bound&gt; &amp; exact |""")
    assert table_text(doc.tables[0]) == [
        ["Name", "Note"],
        ["Bold and italic", "left|right and x|y"],
        ["Evidence (https://example.test/source)", "<bound> & exact"],
    ]
    runs = doc.tables[0].cell(1, 0).paragraphs[0].runs
    assert next(r for r in runs if r.text == "Bold").bold
    assert next(r for r in runs if r.text == "italic").italic
    code = doc.tables[0].cell(1, 1).paragraphs[0].runs
    assert next(r for r in code if r.text == "x|y").font.name == "Consolas"


@pytest.mark.parametrize("break_tag", ["<br>", "<br/>", "<br />", "<BR>"])
def test_multiline_cell_and_crlf(break_tag):
    doc = render(f"| Item | Notes |\r\n| --- | --- |\r\n| A | first{break_tag}**second** |\r\n\r\nUnchanged after.")
    cell = doc.tables[0].cell(1, 1)
    assert cell.text == "first\nsecond"
    assert len(cell._tc.xpath(".//w:br")) == 1
    assert doc.paragraphs[-1].text == "Unchanged after."


@pytest.mark.parametrize("body", [
    "a | b\nc | d", "| a | b |\n| not a delimiter | text |",
    "```markdown\n| a | b |\n| --- | --- |\n| c | d |\n```",
    "    | a | b |\n    | --- | --- |\n    | c | d |",
    "> | a | b |\n> | --- | --- |\n> | c | d |",
    "Plain **unchanged** [reference](url).\nA second paragraph.",
])
def test_nontables_and_nested_examples_keep_original_paragraphs(body):
    doc = render(body)
    assert not doc.tables
    assert [p.text for p in doc.paragraphs] == body.splitlines()


def test_surplus_cells_fall_back_without_silent_loss():
    body = "| A | B |\n| --- | --- |\n| one | two | MUST NOT DISAPPEAR |"
    doc = render(body)
    assert not doc.tables
    assert [p.text for p in doc.paragraphs] == body.splitlines()


def test_short_rows_empty_cells_and_multiple_tables():
    doc = render("A | B\n--- | ---\none\n| | two |\n\nMiddle\n\n| Only |\n| --- |\n| Last |")
    assert table_text(doc.tables[0]) == [["A", "B"], ["one", ""], ["", "two"]]
    assert table_text(doc.tables[1]) == [["Only"], ["Last"]]
    assert [p.text for p in doc.paragraphs] == ["Middle"]


def test_unknown_html_and_image_reference_text_are_not_lost():
    doc = render('| Content |\n| --- |\n| <sup>2</sup> ![Diagram](diagram.png) |')
    assert doc.tables[0].cell(1, 0).text == "<sup>2</sup> Diagram (diagram.png)"


def test_reference_links_and_titles_keep_source_information():
    doc = render('| Source |\n| --- |\n| [Evidence][ref] ![Plan](plan.png "Page 9") |\n\n[ref]: https://example.test/evidence "Page 4"')
    assert doc.tables[0].cell(1, 0).text == "Evidence (https://example.test/evidence; Page 4) Plan (plan.png; Page 9)"
    assert doc.paragraphs[-1].text == '[ref]: https://example.test/evidence "Page 4"'


def test_export_preserves_source_index_status_and_saved_content(tmp_path):
    store = Store(tmp_path)
    store.initialize({"goal": "Original scope\nFull second line", "sources": [
        {"id": "source", "title": "Original source", "content": "Evidence", "coverage": "partial",
         "limitations": ["Missing appendix"]},
    ]})
    ws = Workspace(store)
    ws.initialize()
    store.set("model_mode", "scripted_fixture")
    material_task = ws.request_task("materials", "Read evidence", [])
    material = ws.submit(material_task["id"], actor=material_task["owner"], title="Evidence",
                         body="Original evidence", source_ids=["source"], input_ids=[])
    body = "# Original heading\nUnchanged **paragraph**\n\n| Item | Evidence |\n| --- | --- |\n| Value | [source] |"
    task = ws.request_task("draft", "Compile", [material["id"]])
    draft = ws.submit(task["id"], actor=task["owner"], title="Original title", body=body,
                      source_ids=[], input_ids=[material["id"]])
    before = (ws.tasks(), ws.results(), store.events())
    doc = Document(BytesIO(export_docx(ws, draft["id"])))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "Unreviewed draft; not approved." in text
    assert "SYNTHETIC PROTOCOL FIXTURE" in text
    assert "Scope: Original scope\nFull second line" in text
    assert "Original heading\nUnchanged **paragraph**" in text
    assert "Source index\n[source] Original source; coverage: partial" in text
    assert "Extraction limitation: Missing appendix" in text
    assert "Draft: " + draft["id"] in text
    assert "Review: none" in text
    assert "Input results: " + material["id"] in text
    assert table_text(doc.tables[0])[-1] == ["Value", "[source]"]
    assert before == (ws.tasks(), ws.results(), store.events())
    assert ws.result(draft["id"])["body"] == body
