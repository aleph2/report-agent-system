from io import BytesIO
import re
from unicodedata import east_asian_width
from urllib.parse import quote, unquote

from docx import Document
from docx.enum.section import WD_SECTION_START
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.image.image import Image
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Mm, Pt, RGBColor, Twips
from markdown_it import MarkdownIt
from markdown_it.rules_block.table import escapedSplit

from .workspace import Workspace
from .knowledge_state import delivery_state


def _cell_runs(paragraph, tokens, header=False, image_renderer=None, image_width=None):
    bold = italic = 0
    links = []
    for token in tokens:
        if token.type in ("strong_open", "strong_close"):
            bold += token.nesting
        elif token.type in ("em_open", "em_close"):
            italic += token.nesting
        elif token.type == "link_open":
            links.append((token.attrGet("href") or "", token.attrGet("title")))
        elif token.type == "link_close":
            href, title = links.pop()
            paragraph.add_run(" (" + href + ("; " + title if title else "") + ")")
        elif token.type in ("softbreak", "hardbreak") or (
            token.type == "html_inline" and token.content.lower() in ("<br>", "<br/>", "<br />")
        ):
            paragraph.add_run().add_break()
        elif token.type == "image" and image_renderer is not None:
            image_renderer(paragraph, token, image_width)
        else:
            text = token.content
            if token.type == "image":
                title = token.attrGet("title")
                text += " (" + (token.attrGet("src") or "") + ("; " + title if title else "") + ")"
            run = paragraph.add_run(text)
            run.bold = True if header or bold else None
            run.italic = True if italic else None
            if token.type == "code_inline":
                run.font.name = "Consolas"


def _table_widths(doc, rows):
    section = doc.sections[-1]
    available = (section.page_width - section.left_margin - section.right_margin) / Pt(1)
    minimum, desired = [], []
    for column in zip(*rows):
        texts = [re.sub(r"<br\s*/?>", "\n", "".join(t.content for t in cell.children or []),
                        flags=re.IGNORECASE) for cell in column]
        # Reserve space for intact Latin/numeric identifiers, without business column rules.
        words = [word for text in texts for word in re.findall(r"[A-Za-z0-9]+(?:[+_.:/-][A-Za-z0-9]+)*", text)]
        floor = max(21, max((len(word) * 6.3 for word in words), default=0)) + 14.4
        extent = max((sum(10.5 if east_asian_width(c) in "WF" else 6.3 for c in line)
                      for text in texts for line in text.splitlines()), default=0)
        minimum.append(floor)
        desired.append(max(floor, min(extent, 210) + 14.4))
    if sum(minimum) >= available:
        widths = [available * value / sum(minimum) for value in minimum]
    else:
        weights = [want - floor for want, floor in zip(desired, minimum)]
        if not sum(weights):
            weights = [1] * len(minimum)
        widths = [floor + (available - sum(minimum)) * weight / sum(weights)
                  for floor, weight in zip(minimum, weights)]
    twips = [int(value * 20) for value in widths]
    twips[-1] += round(available * 20) - sum(twips)
    return [Twips(value) for value in twips]


def _add_table(doc, tokens, lines, image_renderer=None, *, technical=False):
    rows = []
    for token in tokens:
        if token.type == "tr_open":
            rows.append([])
        elif token.type == "inline":
            rows[-1].append(token)
    width = len(rows[0])
    # GFM silently discards surplus cells. Preserve the original instead of losing data.
    for line in lines:
        cells = escapedSplit(line.strip())
        if cells and cells[0] == "":
            cells.pop(0)
        if cells and cells[-1] == "":
            cells.pop()
        if len(cells) > width:
            return False
    if technical and doc.paragraphs:
        previous = doc.paragraphs[-1]
        if (previous._p.getnext() is doc.element.body.sectPr and previous.text.strip()
                and not previous._p.xpath('.//w:br[@w:type="page"] | ./w:pPr/w:sectPr')):
            previous.paragraph_format.keep_with_next = True
    table = doc.add_table(rows=0, cols=width)
    table.style = "Table Grid"
    widths = _table_widths(doc, rows) if technical else None
    if technical:
        table.autofit = False
        table_width = table._tbl.tblPr.find(qn("w:tblW"))
        table_width.set(qn("w:type"), "dxa")
        table_width.set(qn("w:w"), str(sum(value.twips for value in widths)))
        for column, value in zip(table.columns, widths):
            column.width = value
    for index, cells in enumerate(rows):
        row = table.add_row()
        properties = row._tr.get_or_add_trPr()
        properties.append(OxmlElement("w:cantSplit"))
        if index == 0:
            properties.append(OxmlElement("w:tblHeader"))
        for column, (cell, token) in enumerate(zip(row.cells, cells)):
            if technical:
                cell.width = widths[column]
            paragraph = cell.paragraphs[0]
            paragraph.paragraph_format.first_line_indent = Pt(0)
            paragraph._p.get_or_add_pPr().get_or_add_ind().set(qn("w:firstLineChars"), "0")
            paragraph.paragraph_format.keep_together = True
            paragraph.paragraph_format.keep_with_next = index == 0
            if technical:
                paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
            _cell_runs(paragraph, token.children or [], header=index == 0,
                       image_renderer=image_renderer, image_width=max(Pt(1), cell.width - Inches(0.2)))
            if technical:
                for run in paragraph.runs:
                    run.font.size = Pt(10.5)
                    run.font.name = "Times New Roman"
                    run._r.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), "\u5b8b\u4f53")
    return True


def _add_body(doc, body, image_renderer=None):
    lines = body.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    tokens = MarkdownIt("commonmark").enable("table").parse(body)
    tables = {}
    images = {}
    for index, token in enumerate(tokens):
        if token.type == "table_open" and token.level == 0:
            end = next(i for i in range(index + 1, len(tokens)) if tokens[i].type == "table_close")
            tables[token.map[0]] = (token.map[1], tokens[index:end + 1])
        elif token.type == "inline" and image_renderer is not None and any(
            child.type == "image" for child in token.children or []
        ) and token.level == 1:
            images[token.map[0]] = token
    line = 0
    while line < len(lines):
        if line in tables:
            end, table_tokens = tables[line]
            if _add_table(doc, table_tokens, lines[line:end], image_renderer):
                line = end
                continue
        if line in images:
            token = images[line]
            _cell_runs(doc.add_paragraph(), token.children, image_renderer=image_renderer)
            line = token.map[1]
            continue
        paragraph = lines[line]
        line += 1
        if not paragraph.strip():
            continue
        if paragraph.startswith("#") and " " in paragraph:
            prefix, content = paragraph.split(" ", 1)
            if set(prefix) == {"#"}:
                doc.add_heading(content, min(len(prefix), 9))
                continue
        doc.add_paragraph(paragraph)


def _source_images(workspace, doc, source_ids):
    cache = {}

    def render(paragraph, token, width=None):
        match = re.fullmatch(r"source-page://([^/?#]+)/([1-9][0-9]*)",
                             token.attrGet("src") or "")
        if not match:
            raise ValueError("EXPORT_IMAGE_REQUIRES_SOURCE_PAGE_REFERENCE")
        source_id, page = unquote(match[1], errors="strict"), int(match[2])
        if source_id in (".", "..") or quote(source_id, safe="") != match[1]:
            raise ValueError("EXPORT_IMAGE_REQUIRES_SOURCE_PAGE_REFERENCE")
        source = workspace.store.sources([source_id])[0]
        key = (source_id, page)
        if key not in cache:
            # Only the project-scoped tool may resolve files or render original pages.
            from .document_tools import source_page_png
            data = source_page_png(workspace, source_id, page)
            if not isinstance(data, bytes) or not data.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError("SOURCE_PAGE_PNG_REQUIRED")
            cache[key] = data
        data = cache[key]
        section = doc.sections[-1]
        paragraph.paragraph_format.first_line_indent = Pt(0)
        paragraph._p.get_or_add_pPr().get_or_add_ind().set(qn("w:firstLineChars"), "0")
        indent = paragraph.paragraph_format.left_indent or 0
        max_width = min(width or section.page_width, section.page_width - section.left_margin - section.right_margin) - indent
        max_height = section.page_height - section.top_margin - section.bottom_margin - Inches(1)
        image = Image.from_blob(data)
        scale = min(max_width / image.width, max_height / image.height)
        if paragraph.text:
            paragraph.add_run().add_break()
        paragraph.add_run().add_picture(BytesIO(data), width=int(image.width * scale), height=int(image.height * scale))
        paragraph.add_run().add_break()
        caption = token.content
        title = token.attrGet("title")
        if title:
            caption += " (" + title + ")"
        paragraph.add_run(f"{caption} [{source_id}] {source['title']}, PDF physical page {page}")
        paragraph.add_run().add_break()
        source_ids.add(source_id)

    return render


def _list_numbering(doc, ordered, start=1):
    numbering = doc.part.numbering_part.element
    abstract_id = max((int(e.get(qn("w:abstractNumId"))) for e in numbering.findall(qn("w:abstractNum"))), default=-1) + 1
    abstract = OxmlElement("w:abstractNum")
    abstract.set(qn("w:abstractNumId"), str(abstract_id))
    level = OxmlElement("w:lvl")
    level.set(qn("w:ilvl"), "0")
    for tag, value in (("start", str(start)), ("numFmt", "decimal" if ordered else "bullet"),
                       ("lvlText", "%1." if ordered else "\u2022"), ("suff", "tab")):
        child = OxmlElement("w:" + tag)
        child.set(qn("w:val"), value)
        level.append(child)
    abstract.append(level)
    numbering.insert_element_before(abstract, "w:num")
    return numbering.add_num(abstract_id).numId


def _add_markdown(doc, body, image_renderer, *, headings_in_toc=True):
    lines = body.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    tokens = MarkdownIt("commonmark").enable("table").parse(body)
    lists = []
    paragraph = None
    scope_heading = False
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.type == "table_open":
            end = next(i for i in range(index + 1, len(tokens)) if tokens[i].type == "table_close")
            original = lines[token.map[0]:token.map[1]]
            if not _add_table(doc, tokens[index:end + 1], original, image_renderer, technical=True):
                for line in original:
                    doc.add_paragraph(line)
            index = end
        elif token.type in ("bullet_list_open", "ordered_list_open"):
            ordered = token.type == "ordered_list_open"
            lists.append({"id": _list_numbering(doc, ordered, int(token.attrGet("start") or 1)), "first": False})
        elif token.type in ("bullet_list_close", "ordered_list_close"):
            lists.pop()
        elif token.type == "list_item_open":
            lists[-1]["first"] = True
        elif token.type in ("heading_open", "paragraph_open"):
            heading = token.type == "heading_open"
            scope_heading = heading and not headings_in_toc
            paragraph = doc.add_heading("", int(token.tag[1:])) if heading and headings_in_toc else doc.add_paragraph()
            if scope_heading:
                paragraph.paragraph_format.keep_with_next = True
                paragraph.paragraph_format.first_line_indent = Pt(0)
                paragraph._p.get_or_add_pPr().get_or_add_ind().set(qn("w:firstLineChars"), "0")
            if lists:
                paragraph.style = doc.styles["List Paragraph"]
                paragraph.paragraph_format.left_indent = Inches(0.25 * len(lists))
                if lists[-1]["first"]:
                    paragraph.paragraph_format.first_line_indent = Inches(-0.2)
                    numbering = paragraph._p.get_or_add_pPr().get_or_add_numPr()
                    numbering.get_or_add_ilvl().val = 0
                    numbering.get_or_add_numId().val = lists[-1]["id"]
                    lists[-1]["first"] = False
        elif token.type == "inline":
            _cell_runs(paragraph, token.children or [], header=scope_heading, image_renderer=image_renderer)
        elif token.type in ("fence", "code_block", "html_block"):
            doc.add_paragraph(token.content.rstrip("\n"))
        elif token.type == "hr":
            doc.add_paragraph("---")
        index += 1


def _field(paragraph, instruction, placeholder=""):
    for kind in ("begin", "separate", "end"):
        element = OxmlElement("w:fldChar")
        element.set(qn("w:fldCharType"), kind)
        if kind == "begin":
            element.set(qn("w:dirty"), "true")
        paragraph.add_run()._r.append(element)
        if kind == "begin":
            code = OxmlElement("w:instrText")
            code.set(qn("xml:space"), "preserve")
            code.text = " " + instruction + " "
            paragraph.add_run()._r.append(code)
        elif kind == "separate" and placeholder:
            paragraph.add_run(placeholder)


def _technical_template(doc, draft, metadata, project_name):
    compat = doc.settings.element.find(qn("w:compat"))
    if compat is None:
        compat = OxmlElement("w:compat")
        doc.settings.element.append(compat)
    soft_break = compat.find(qn("w:doNotExpandShiftReturn"))
    if soft_break is None:
        soft_break = OxmlElement("w:doNotExpandShiftReturn")
        compat.insert(0, soft_break)
    soft_break.set(qn("w:val"), "true")
    section = doc.sections[0]
    section.page_width, section.page_height = Mm(210), Mm(297)
    section.top_margin = section.bottom_margin = section.left_margin = Mm(25)
    section.right_margin = Mm(15)
    section.gutter = Mm(0)
    section.header_distance = section.footer_distance = Mm(12.7)
    for name in ("Normal", "Title", "Subtitle", "Caption", "Header", "Footer", "List Paragraph", *[f"Heading {n}" for n in range(1, 10)]):
        style = doc.styles[name]
        style.font.name = "Times New Roman"
        fonts = style.element.get_or_add_rPr().get_or_add_rFonts()
        fonts.set(qn("w:eastAsia"), "\u5b8b\u4f53")
        for attr in ("asciiTheme", "hAnsiTheme", "eastAsiaTheme"):
            fonts.attrib.pop(qn("w:" + attr), None)
        style.font.color.rgb = RGBColor(0, 0, 0)
        if name != "Normal":
            style.paragraph_format.first_line_indent = Pt(0)
            style.element.get_or_add_pPr().get_or_add_ind().set(qn("w:firstLineChars"), "0")
    doc.styles["Normal"].font.size = Pt(12)
    doc.styles["Normal"].paragraph_format.line_spacing = 1.5
    doc.styles["Normal"].paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    doc.styles["Normal"].paragraph_format.first_line_indent = Pt(24)
    doc.styles["Normal"].element.get_or_add_pPr().get_or_add_ind().set(qn("w:firstLineChars"), "200")
    doc.styles["Header"].font.name = "\u5b8b\u4f53"
    doc.styles["Header"].font.size = Pt(9)
    doc.styles["Footer"].font.size = Pt(9)
    doc.styles["Title"].font.size = Pt(22)
    for name, size in (("Heading 1", 16), ("Heading 2", 14), ("Heading 3", 12)):
        doc.styles[name].font.size = Pt(size)
    title = doc.add_heading(draft["title"], 0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.paragraph_format.space_before = Pt(100)
    for text in ("\u8d44\u6599\u6c47\u7f16\u6280\u672f\u62a5\u544a", "\u672a\u7ecf\u5de5\u7a0b\u6279\u51c6", "\u7f16\u5236\u5355\u4f4d\uff1a" + metadata.get("organization", "\u5f85\u586b\u5199"),
                 "\u7f16\u5236\u65e5\u671f\uff1a" + metadata.get("date", "\u5f85\u586b\u5199")):
        doc.add_paragraph(text).alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_page_break()
    doc.add_heading("\u6249\u9875", 0)
    doc.add_paragraph(draft["title"])
    doc.add_paragraph("\u7f16\u5236\u5355\u4f4d\uff1a" + metadata.get("organization", "\u5f85\u586b\u5199"))
    doc.add_paragraph("\u7f16\u5236\u65e5\u671f\uff1a" + metadata.get("date", "\u5f85\u586b\u5199"))
    doc.add_paragraph("\u5de5\u7a0b\u5ba1\u6838\u3001\u6279\u51c6\u4fe1\u606f\uff1a\u5f85\u586b\u5199\uff08\u672a\u7ecf\u5de5\u7a0b\u6279\u51c6\uff09")
    section = doc.add_section(WD_SECTION_START.NEW_PAGE)
    section.header.is_linked_to_previous = False
    section.footer.is_linked_to_previous = False
    header = section.header.paragraphs[0]
    header.alignment = WD_ALIGN_PARAGRAPH.LEFT
    header.paragraph_format.tab_stops.clear_all()
    header.paragraph_format.tab_stops.add_tab_stop(
        section.page_width - section.left_margin - section.right_margin, WD_TAB_ALIGNMENT.RIGHT)
    header.text = project_name + "\t" + draft["title"]
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _field(footer, "PAGE")
    doc.add_heading("\u76ee\u5f55", 0)
    _field(doc.add_paragraph(), 'TOC \\o "1-3" \\h \\z \\u', "\u76ee\u5f55\u5f85\u66f4\u65b0")
    update = OxmlElement("w:updateFields")
    update.set(qn("w:val"), "true")
    doc.settings.element.append(update)
    doc.add_page_break()


def export_docx(workspace: Workspace, draft_id: str, *, template=None, metadata=None) -> bytes:
    """Export a saved version, without model calls, tasks, or approval.

    template: legacy (default) or technical_zh (reader copy). If omitted, use
    manifest["export"]["template"]. Optional metadata (organization/date/scope/project_name)
    overrides manifest["export"]["metadata"], without changing saved data.
    Technical audit is omitted from reader appendices, never deleted from storage.
    """
    options = workspace.store.manifest.get("export", {})
    template = template if template is not None else options.get("template", "legacy")
    if template not in ("legacy", "technical_zh"):
        raise ValueError("UNKNOWN_EXPORT_TEMPLATE")
    metadata = {**options.get("metadata", {}), **(metadata or {})}
    if set(metadata) - {"organization", "date", "scope", "project_name"} or any(not isinstance(v, str) for v in metadata.values()):
        raise ValueError("EXPORT_METADATA_ONLY_ORGANIZATION_DATE_SCOPE_PROJECT_NAME")
    metadata = {k: v for k, v in metadata.items() if v.strip() or k == "scope"}
    technical = template == "technical_zh"
    draft = workspace.result(draft_id)
    state, evidence = delivery_state(workspace, draft_id)
    review_id = state["review_id"]
    doc = Document()
    section = doc.sections[0]
    section.top_margin = section.bottom_margin = Inches(0.8)
    section.left_margin = section.right_margin = Inches(0.9)
    for name in ("Normal", "Title", "Heading 1", "Heading 2", "Heading 3"):
        style = doc.styles[name]
        style.font.name = "Calibri"
        style.font.color.rgb = RGBColor(0, 0, 0)
    doc.styles["Normal"].font.size = Pt(11)
    if technical:
        project_name = metadata.get("project_name") or workspace.store.manifest.get("project_name") or "\u9879\u76ee\u540d\u79f0\u5f85\u586b\u5199"
        _technical_template(doc, draft, metadata, project_name)
    else:
        doc.add_heading(draft["title"], 0)
    labels = {"reviewed_draft": "Model-reviewed draft; not engineering-approved.",
              "changes_required": "Draft requiring corrections; not approved.",
              "needs_human": "Draft with unresolved issues requiring human handling.",
              "system_error": "Draft affected by an unresolved system failure; not a missing-source judgment.",
              "needs_attention": "Draft pending assessment of changed source material; not approved.",
              "unreviewed_draft": "Unreviewed draft; not approved."}
    if technical:
        labels = {
            "reviewed_draft": "\u6a21\u578b\u5ba1\u6838\u901a\u8fc7\u7684\u8349\u7a3f\uff1b\u672a\u7ecf\u5de5\u7a0b\u6279\u51c6\u3002",
            "changes_required": "\u5f85\u4fee\u6539\u8349\u7a3f\uff1b\u672a\u7ecf\u5de5\u7a0b\u6279\u51c6\u3002",
            "needs_human": "\u5b58\u5728\u5f85\u4eba\u5de5\u5904\u7406\u4e8b\u9879\uff1b\u672a\u7ecf\u5de5\u7a0b\u6279\u51c6\u3002",
            "system_error": "\u5f53\u524d\u6709\u6548\u6027\u672a\u80fd\u786e\u8ba4\uff1b\u672a\u7ecf\u5de5\u7a0b\u6279\u51c6\u3002",
            "needs_attention": "\u8d44\u6599\u53d8\u66f4\u5f85\u8bc4\u4f30\uff1b\u672a\u7ecf\u5de5\u7a0b\u6279\u51c6\u3002",
            "unreviewed_draft": "\u672a\u5ba1\u6838\u8349\u7a3f\uff1b\u672a\u7ecf\u5de5\u7a0b\u6279\u51c6\u3002",
        }
    doc.add_paragraph(labels[state["status"]])
    if evidence["status"] == "unknown":
        doc.add_paragraph("Shared knowledge validity could not be checked. Historical text and review are retained; current validity is unknown.")
    elif evidence["status"] == "needs_assessment":
        doc.add_paragraph("Adopted knowledge has changed. Producer assessment is pending; this does not automatically require rewriting.")
    if workspace.store.get("model_mode") == "scripted_fixture":
        doc.add_paragraph("SYNTHETIC PROTOCOL FIXTURE. Not a real-model or engineering report.")
    manifest = workspace.store.manifest
    scope_instruction = manifest.get("scope_instruction")
    if isinstance(scope_instruction, dict):
        scope_instruction = scope_instruction.get("text")
    scope = metadata.get("scope", scope_instruction or manifest["goal"]) if technical else manifest["goal"]
    source_ids = set(draft["source_ids"])
    images = _source_images(workspace, doc, source_ids)
    if technical:
        doc.add_paragraph("\u7f16\u5236\u8303\u56f4\uff1a")
        _add_markdown(doc, scope, images, headings_in_toc=False)
        _add_markdown(doc, draft["body"], images)
    else:
        doc.add_paragraph("Scope: " + scope)
        _add_body(doc, draft["body"], images)
    issues = workspace.status()["issues"]
    if technical:
        issues = [i for i in issues if not i["resolved"] and i["category"] in {"source_missing", "source_conflict"}]
    if issues:
        doc.add_heading("\u5f85\u786e\u8ba4\u4e8b\u9879" if technical else "Issues and decisions", 1)
        for issue in issues:
            if technical:
                doc.add_paragraph(issue["description"])
                source_ids.update(issue["source_ids"])
                if issue["source_ids"]:
                    doc.add_paragraph("\u76f8\u5173\u6765\u6e90\uff1a" + ", ".join(issue["source_ids"]))
            else:
                doc.add_paragraph(issue["category"] + ": " + issue["description"])
                if issue.get("decision"):
                    doc.add_paragraph("Operator input: " + issue["decision"])
                doc.add_paragraph("Resolved: " + str(issue["resolved"]))
    # Include transitive evidence so the report does not lose source references merely
    # because the writer consumed shared materials instead of rereading originals.
    visited = set()
    for fact in evidence["facts"]:
        source_ids.update(p["source_id"] for p in fact["provenance"])
    pending = list(draft["input_ids"])
    while pending:
        ref = pending.pop()
        if ref in visited:
            continue
        visited.add(ref)
        result = workspace.result(ref)
        source_ids.update(result["source_ids"])
        pending.extend(result["input_ids"])
    doc.add_heading("\u8d44\u6599\u6765\u6e90\u7d22\u5f15" if technical else "Source index", 1)
    for source in workspace.store.sources(sorted(source_ids)):
        doc.add_paragraph(f'[{source["id"]}] {source["title"]}; coverage: {source["coverage"]}')
        if not source.get("current", True):
            doc.add_paragraph("Historical source version; this draft may require revision.")
        for limitation in source.get("limitations", []):
            doc.add_paragraph("Extraction limitation: " + limitation)
    doc.add_heading("\u7248\u672c\u8bb0\u5f55" if technical else "Version record", 1)
    doc.add_paragraph("Knowledge versions: " + ", ".join(evidence["fact_ids"]))
    doc.add_paragraph("Knowledge validity at export: " + evidence["status"] + " (" + evidence["checked_at"] + ")")
    doc.add_paragraph("Draft: " + draft_id)
    doc.add_paragraph("Review: " + (review_id or "none"))
    doc.add_paragraph("Input results: " + ", ".join(draft["input_ids"]))
    output = BytesIO()
    doc.save(output)
    return output.getvalue()
