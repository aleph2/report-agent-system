"""Presentation-only controls for an immutable report. No text replacement capability."""
from typing import Literal

from pydantic import Field, model_validator
from docx.enum.section import WD_SECTION_START
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor

from .content_models import Contract, Ref
from .errors import ActionRejected


def table_footnote(body):
    """Read the explicitly supported visible note without rewriting its text."""
    value = body.get("footnote")
    if value is None:
        return None
    if not isinstance(value, str):
        raise ActionRejected("TABLE_FOOTNOTE_REQUIRES_TEXT")
    return value if value.strip() else None


class Typography(Contract):
    line_spacing: float | None = Field(default=None, ge=0.5, le=3,
        description='Line-height multiplier; distinct from an exact point height.')
    space_before_pt: float | None = Field(default=None, ge=0, le=48)
    space_after_pt: float | None = Field(default=None, ge=0, le=48)
    space_before_lines: float | None = Field(default=None, ge=0, le=6)
    space_after_lines: float | None = Field(default=None, ge=0, le=6)
    left_indent_mm: float | None = Field(default=None, ge=0, le=50)
    hanging_indent_mm: float | None = Field(default=None, ge=0, le=30)
    first_line_indent_mm: float | None = Field(default=None, ge=0, le=30)
    first_line_indent_chars: float | None = Field(default=None, ge=0, le=10,
        description='First-line indentation in font ems, converted to points using the effective font size for consistent Word/LibreOffice rendering.')
    line_spacing_pt: float | None = Field(default=None, ge=1, le=144,
        description='Exact line height in points; can clip taller glyphs, so inspect the rendered output.')
    font_size: float | None = Field(default=None, ge=6, le=72)
    font_family: str | None = Field(default=None, min_length=1, max_length=100)
    east_asia_font: str | None = Field(default=None, min_length=1, max_length=100)
    alignment: Literal['left', 'center', 'right', 'justify'] | None = None
    bold: bool | None = None

    @model_validator(mode='after')
    def exclusive_indent(self):
        if self.line_spacing is not None and self.line_spacing_pt is not None:
            raise ValueError('Specify multiple or exact point line spacing, not both')
        for side in ('before', 'after'):
            if (getattr(self, 'space_'+side+'_lines') is not None
                    and 'space_'+side+'_pt' in self.model_fields_set
                    and getattr(self, 'space_'+side+'_pt') is not None):
                raise ValueError('Specify point or line paragraph spacing, not both')
            if (getattr(self, 'space_'+side+'_lines') is not None
                    and 'space_'+side+'_pt' not in self.model_fields_set):
                # Canonicalize an unused inherited/default point value. The
                # public tool serializes and revalidates layouts, so intent must
                # survive model_dump(), not depend on model_fields_set alone.
                setattr(self, 'space_'+side+'_pt', None)
        if self.first_line_indent_mm is not None and self.first_line_indent_chars is not None:
            raise ValueError('Specify millimetres or character ems, not both')
        if self.hanging_indent_mm is not None and (self.first_line_indent_mm is not None or self.first_line_indent_chars is not None):
            raise ValueError('Hanging and first-line indentation are mutually exclusive')
        return self


class StyleLayout(Typography):
    name: Literal['Normal', 'Title', 'Heading 1', 'Heading 2', 'Heading 3', 'Heading 4', 'Heading 5', 'Heading 6', 'Caption', 'Header', 'Footer', 'TOC Heading', 'TOC 1', 'TOC 2', 'TOC 3']


class HeaderSourceLine(Contract):
    node_ref: Ref
    text: str = Field(min_length=1, description='Exact complete unique line from a node actually rendered in the snapshot body; not new text.')


class HeaderLayout(Typography, HeaderSourceLine):
    additional_lines: list[HeaderSourceLine] = Field(default_factory=list, max_length=8,
        description='Additional exact adopted body lines, joined by spaces in this header position. Each retains its own versioned source binding.')


class HeaderPart(HeaderLayout):
    position: Literal['left', 'center', 'right']


class ParagraphLayout(Typography):
    text: str = Field(min_length=1, description="Exact complete unique line from this node's stored text; selector only, never replacement text.")
    heading_level: int | None = Field(default=None, ge=1, le=6)
    space_before_pt: float | None = Field(default=0, ge=0, le=48)
    space_after_pt: float | None = Field(default=6, ge=0, le=48)
    keep_with_next: bool = False
    page_break_before: bool = False


class NodeLayout(Contract):
    """Table controls apply to typed tables and actual Markdown tables in text nodes.

    Local controls apply to every table in that node; column_weights must match
    every rendered table's column count. They never restyle body paragraphs.
    """
    node_ref: Ref
    heading_level: int | None = Field(default=None, ge=1, le=6)
    page_break_before: bool = False
    landscape: bool = False
    column_weights: list[float] = Field(default_factory=list)
    table_font_size: float = Field(default=10, ge=9, le=14)
    table_line_spacing: float | None = Field(default=None, ge=1, le=3)
    table_alignment: Literal['left', 'center', 'right'] | None = Field(default=None,
        description='Position the table between page margins; independent of text alignment inside its cells. None preserves inherited/default behavior.')
    table_cell_alignment: Literal['left', 'center', 'right', 'justify'] | None = Field(default=None,
        description='Horizontal paragraph alignment inside table cells; does not change body paragraphs.')
    table_cell_first_line_indent_mm: float | None = Field(default=None, ge=0, le=30,
        description='Explicit cell-paragraph first-line indent. Zero cancels inherited body indentation; None preserves inheritance.')
    outer_border_style: Literal['single', 'double'] | None = None
    outer_border_width_pt: float | None = Field(default=None, ge=0.125, le=6,
        description='Word border widths are rounded to the nearest eighth of a point.')
    keep_table_together: bool = False
    allow_row_split: bool = False
    figure_width_mm: float | None = Field(default=None, ge=30, le=250)
    paragraphs: list[ParagraphLayout] = Field(default_factory=list)
    qualifier_font_size: float = Field(default=10, ge=9, le=14)
    qualifier_placement: Literal['adjacent', 'end_notes'] = Field(default='adjacent',
        description='Keep all semantic qualifier text visible beside its node, or move it verbatim to numbered end notes with a visible node marker. Never suppress qualifiers.')


class LayoutOptions(Contract):
    paper: Literal["A4"] = "A4"
    margin_mm: float = Field(default=25, ge=15, le=35)
    top_margin_mm: float | None = Field(default=None, ge=10, le=50)
    bottom_margin_mm: float | None = Field(default=None, ge=10, le=50)
    left_margin_mm: float | None = Field(default=None, ge=10, le=50)
    right_margin_mm: float | None = Field(default=None, ge=10, le=50)
    styles: list[StyleLayout] = Field(default_factory=list)
    header: HeaderLayout | None = None
    header_parts: list[HeaderPart] = Field(default_factory=list, max_length=3)
    hide_first_page_header_footer: bool = False
    cover_vertical_alignment: Literal['top', 'center', 'bottom'] | None = Field(default=None,
        description='Isolate report root text in a borderless, expandable cover cell/section and vertically align it. Following TOC, children and end notes use top alignment. Oversized covers can span pages; inspect the render.')
    font_size: float = Field(default=12, ge=10, le=14)
    toc: bool = True
    page_numbers: bool = True
    toc_depth: int = Field(default=2, ge=1, le=3)
    refresh_toc: bool = False
    line_spacing: float = Field(default=1.3, ge=1, le=2)
    table_line_spacing: float = Field(default=1.15, ge=1, le=3)
    table_alignment: Literal['left', 'center', 'right'] | None = Field(default=None,
        description='Position the table between page margins; independent of text alignment inside its cells. None preserves inherited/default behavior.')
    table_cell_alignment: Literal['left', 'center', 'right', 'justify'] | None = Field(default=None,
        description='Horizontal paragraph alignment inside table cells; does not change body paragraphs.')
    table_cell_first_line_indent_mm: float | None = Field(default=None, ge=0, le=30,
        description='Explicit cell-paragraph first-line indent. Zero cancels inherited body indentation; None preserves inheritance.')
    outer_border_style: Literal['single', 'double'] | None = None
    outer_border_width_pt: float | None = Field(default=None, ge=0.125, le=6)
    paragraph_space_after_pt: float = Field(default=6, ge=0, le=24)
    nodes: list[NodeLayout] = Field(default_factory=list)


def validate_layout(options, records, rendered_keys=None):
    if len({s.name for s in options.styles}) != len(options.styles):
        raise ActionRejected('LAYOUT_DUPLICATE_STYLE')
    if options.header and options.header_parts:
        raise ActionRejected('HEADER_CONTROLS_CONFLICT')
    if len({p.position for p in options.header_parts}) != len(options.header_parts):
        raise ActionRejected('HEADER_DUPLICATE_POSITION')
    headers = ([options.header] if options.header else options.header_parts)
    for header in [line for part in headers for line in [part, *part.additional_lines]]:
        key = header.node_ref.key()
        if not rendered_keys or key not in rendered_keys or key not in records or key[0] != 'ContentNode':
            raise ActionRejected('HEADER_REQUIRES_RENDERED_BODY_NODE')
        if records[key]['payload']['kind'] in {'table', 'figure'}:
            raise ActionRejected('HEADER_REQUIRES_RENDERED_TEXT_NODE')
        lines = records[key]['payload']['body'].get('text', '').split('\n')
        if lines.count(header.text) != 1:
            raise ActionRejected('HEADER_REQUIRES_UNIQUE_EXACT_LINE')
    seen = set()
    for item in options.nodes:
        key = item.node_ref.key()
        if key in seen or key not in records or key[0] != "ContentNode":
            raise ActionRejected("LAYOUT_REQUIRES_UNIQUE_SNAPSHOT_NODE")
        seen.add(key)
        body = records[key]["payload"]
        lines = body['body'].get('text', '').split('\n')
        from .exporting import markdown_table_spans
        table_spans = markdown_table_spans(body['body'].get('text', ''))
        if item.heading_level and any(start == 0 for _, start, _ in table_spans):
            raise ActionRejected('HEADING_CONTROL_INTERSECTS_MARKDOWN_TABLE')
        if item.paragraphs and body['kind'] in {'table','figure'}:
            raise ActionRejected('PARAGRAPH_CONTROLS_REQUIRE_TEXT_BLOCK_OR_CLAIM')
        selected = set()
        for paragraph in item.paragraphs:
            if paragraph.text in selected or lines.count(paragraph.text) != 1:
                raise ActionRejected('LAYOUT_PARAGRAPH_REQUIRES_UNIQUE_EXACT_LINE')
            if any(start <= lines.index(paragraph.text) < end for _, start, end in table_spans):
                raise ActionRejected('PARAGRAPH_CONTROL_INTERSECTS_MARKDOWN_TABLE')
            selected.add(paragraph.text)
            if item.heading_level and paragraph.text == lines[0] and paragraph.heading_level != item.heading_level:
                raise ActionRejected('LAYOUT_CONFLICTING_HEADING_LEVELS')
        if item.heading_level and (body["kind"] not in {"block", "chapter"} or not body["body"].get("text")):
            raise ActionRejected("LAYOUT_HEADING_REQUIRES_TEXT_BLOCK")
        table_columns = ([len(body['body']['columns'])] if body['kind'] == 'table' else
                         [width for width, _, _ in table_spans])
        if item.column_weights and (not table_columns or
                any(len(item.column_weights) != n for n in table_columns) or
                any(not 0 < n < 1000 for n in item.column_weights)):
            raise ActionRejected("LAYOUT_COLUMN_WEIGHTS_INVALID")
        if item.landscape and not table_columns and body["kind"] != "figure":
            raise ActionRejected("LANDSCAPE_REQUIRES_TABLE_OR_FIGURE")
        if item.figure_width_mm and body["kind"] != "figure":
            raise ActionRejected("FIGURE_WIDTH_REQUIRES_FIGURE")
        if any(getattr(item, field) is not None for field in
               ('table_line_spacing','table_alignment','table_cell_alignment','table_cell_first_line_indent_mm','outer_border_style','outer_border_width_pt')) and not table_columns:
            raise ActionRejected('TABLE_CONTROLS_REQUIRE_TABLE')
    return {item.node_ref.key(): item for item in options.nodes}


def margin(options, side):
    value = getattr(options, side + '_margin_mm')
    return options.margin_mm if value is None else value


def available_width(options, landscape=False):
    return (297 if landscape else 210) - margin(options, 'left') - margin(options, 'right')


def page_setup(section, options, landscape=False):
    section.page_width, section.page_height = (Mm(297), Mm(210)) if landscape else (Mm(210), Mm(297))
    for side in ('top', 'bottom', 'left', 'right'):
        setattr(section, side + '_margin', Mm(margin(options, side)))
    section.header_distance = section.footer_distance = Mm(12)


def field(paragraph, instruction):
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar"); begin.set(qn("w:fldCharType"), "begin")
    code = OxmlElement("w:instrText"); code.set(qn("xml:space"), "preserve"); code.text = instruction
    end = OxmlElement("w:fldChar"); end.set(qn("w:fldCharType"), "end")
    for e in (begin, code, end):
        run._r.append(e)


def setup(doc, options):
    page_setup(doc.sections[0], options)
    doc.sections[0].different_first_page_header_footer = options.hide_first_page_header_footer
    if options.hide_first_page_header_footer:
        # Explicit empty parts survive the LibreOffice DOCX round trip. A titlePg
        # flag without a first-footer relationship may inherit the default footer.
        for part in (doc.sections[0].first_page_header, doc.sections[0].first_page_footer):
            part.is_linked_to_previous = False
            part.paragraphs[0].clear()
    for name in ("Normal", "Title", "Heading 1", "Heading 2", "Heading 3", "Heading 4", "Heading 5", "Heading 6", "Caption"):
        style = doc.styles[name]
        apply_run_typography(style, Typography(font_family='Times New Roman',
            east_asia_font='宋体' if name in {'Normal', 'Caption'} else '黑体'))
        style.font.color.rgb = RGBColor(0, 0, 0)
        style.font.size = Pt(options.font_size if name == "Normal" else 10 if name == "Caption" else 16 if name == "Title" else 14)
        style.paragraph_format.space_after = Pt(options.paragraph_space_after_pt)
        style.paragraph_format.line_spacing = options.line_spacing
        style.paragraph_format.widow_control = True
    from docx.enum.style import WD_STYLE_TYPE
    for name in ('TOC Heading', 'TOC 1', 'TOC 2', 'TOC 3'):
        style = doc.styles[name] if name in doc.styles else doc.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        style.base_style = doc.styles['Title' if name == 'TOC Heading' else 'Normal']
        if name != 'TOC Heading':
            style.paragraph_format.left_indent = Mm((int(name[-1])-1)*5)
            style.paragraph_format.space_after = Pt(2)
    doc.styles["Normal"].paragraph_format.keep_with_next = False
    if options.page_numbers:
        p = doc.sections[0].footer.paragraphs[0]; p.alignment = 1
        field(p, " PAGE ")
    # Finalize inherited font sizes before resolving character-em indentation.
    # A Header/Footer may inherit Normal even when its control appears first.
    for control in options.styles:
        apply_run_typography(doc.styles[control.name], control)
    for control in options.styles:
        apply_typography(doc.styles[control.name], control, is_style=True)
    footer_control = next((s for s in options.styles if s.name == 'Footer'), None)
    if options.page_numbers and footer_control:
        apply_typography(doc.sections[0].footer.paragraphs[0], footer_control)
    if options.header:
        p = doc.sections[0].header.paragraphs[0]
        p.text = header_text(options.header)
        apply_typography(p, options.header)
    if options.header_parts:
        doc.styles['Header'].paragraph_format.tab_stops.clear_all()
        multipart_header(doc.sections[0], options)
    setting = OxmlElement("w:updateFields"); setting.set(qn("w:val"), "true")
    doc.settings.element.append(setting)


def add_toc(doc, headings, depth=2, start_new_page=True, options=None):
    if start_new_page:
        doc.add_page_break()
    doc.add_paragraph("目录", "TOC Heading")
    # Seed a readable field cache; Word can update page numbers on opening. A bare
    # uncalculated TOC field otherwise renders as an empty page in headless export.
    p = doc.add_paragraph()
    start = OxmlElement('w:fldChar'); start.set(qn('w:fldCharType'), 'begin')
    code = OxmlElement('w:instrText'); code.set(qn('xml:space'), 'preserve'); code.text = f' TOC \\o "1-{depth}" \\h \\z \\u '
    sep = OxmlElement('w:fldChar'); sep.set(qn('w:fldCharType'), 'separate')
    for e in (start, code, sep): p.add_run()._r.append(e)
    for text, level in headings:
        p = doc.add_paragraph(text, 'TOC '+str(level))
        if options is None or not any(c.name == 'TOC '+str(level) for c in options.styles):
            # Preserve the previous seed cache unless the caller selects TOC
            # typography. Explicit styles must remain effective after refresh.
            p.paragraph_format.line_spacing = 1.1
            p.paragraph_format.left_indent = Mm((level-1)*5)
            p.paragraph_format.space_after = Pt(2)
            for run in p.runs:
                run.font.size = Pt(11)
    end = OxmlElement('w:fldChar'); end.set(qn('w:fldCharType'), 'end')
    p.add_run()._r.append(end)
    doc.add_page_break()


# Only explicit structural metadata is projected into styles or retained solely in
# the export mapping. Unknown/semantic qualifiers remain visible, never discarded.
STRUCTURAL = {"commission", "document_type", "edition", "part", "revision", "number",
              "title", "标题", "表号", "图号", "章节号", "模板章节"}


def caption(node):
    qualifiers = node["qualifiers"]
    title = node["body"].get("caption") or qualifiers.get("标题") or qualifiers.get("title", "")
    number = qualifiers.get("表号") or qualifiers.get("number", "")
    return (str(number) + " " + str(title)).strip() if number and not str(title).startswith(str(number)) else str(title)


def format_table(table, options, node_options=None, *, embedded=False):
    available = available_width(options, bool(node_options and node_options.landscape))
    columns = len(table.columns)
    weights = node_options.column_weights if node_options and node_options.column_weights else [1] * columns
    widths = ([col.width for col in table.columns] if embedded and not (node_options and node_options.column_weights)
              else [Mm(available * w / sum(weights)) for w in weights])
    table.autofit = False
    def selected(field):
        local = getattr(node_options, field) if node_options else None
        return local if local is not None else getattr(options, field)
    position = selected('table_alignment')
    cell_alignment = selected('table_cell_alignment')
    cell_indent = selected('table_cell_first_line_indent_mm')
    if position is not None:
        from docx.enum.table import WD_TABLE_ALIGNMENT
        table.alignment = {'left': WD_TABLE_ALIGNMENT.LEFT, 'center': WD_TABLE_ALIGNMENT.CENTER,
                           'right': WD_TABLE_ALIGNMENT.RIGHT}[position]
    for col, width in zip(table.columns, widths): col.width = width
    header_properties = table.rows[0]._tr.get_or_add_trPr()
    if header_properties.find(qn('w:tblHeader')) is None:
        header_properties.append(OxmlElement('w:tblHeader'))
    spacing = node_options.table_line_spacing if node_options and node_options.table_line_spacing is not None else options.table_line_spacing
    border_style = node_options.outer_border_style if node_options and node_options.outer_border_style is not None else options.outer_border_style
    border_width = node_options.outer_border_width_pt if node_options and node_options.outer_border_width_pt is not None else options.outer_border_width_pt
    if border_style is not None or border_width is not None:
        borders = table._tbl.tblPr.find(qn('w:tblBorders'))
        if borders is None:
            borders = OxmlElement('w:tblBorders'); table._tbl.tblPr.append(borders)
        for side in ('top', 'left', 'bottom', 'right'):
            border = borders.find(qn('w:'+side))
            if border is None:
                border = OxmlElement('w:'+side); borders.append(border)
            border.set(qn('w:val'), border_style or 'single')
            border.set(qn('w:sz'), str(round((border_width if border_width is not None else 0.5)*8)))
            border.set(qn('w:color'), 'auto')
    for index, row in enumerate(table.rows):
        row_properties = row._tr.get_or_add_trPr()
        if node_options and node_options.allow_row_split:
            for old in list(row_properties.findall(qn('w:cantSplit'))):
                row_properties.remove(old)
        if not (node_options and node_options.allow_row_split) and max(len(c.text) for c in row.cells) < 800:
            if row_properties.find(qn('w:cantSplit')) is None:
                row_properties.append(OxmlElement('w:cantSplit'))
        for cell, width in zip(row.cells, widths):
            cell.width = width
            for paragraph in cell.paragraphs:
                if cell_alignment is not None:
                    from docx.enum.text import WD_ALIGN_PARAGRAPH
                    paragraph.alignment = {'left': WD_ALIGN_PARAGRAPH.LEFT, 'center': WD_ALIGN_PARAGRAPH.CENTER,
                        'right': WD_ALIGN_PARAGRAPH.RIGHT, 'justify': WD_ALIGN_PARAGRAPH.JUSTIFY}[cell_alignment]
                if cell_indent is not None:
                    paragraph.paragraph_format.first_line_indent = Mm(cell_indent)
                    paragraph._p.get_or_add_pPr().get_or_add_ind().attrib.pop(qn('w:firstLineChars'), None)
                paragraph.paragraph_format.space_after = Pt(3)
                paragraph.paragraph_format.line_spacing = spacing
                if node_options and node_options.keep_table_together:
                    paragraph.paragraph_format.keep_with_next = index < len(table.rows)-1
                for run in paragraph.runs:
                    if not embedded or node_options:
                        run.font.size = Pt(node_options.table_font_size if node_options else 10)
                    if not embedded:
                        run.bold = index == 0


def multipart_header(section, options):
    from docx.enum.text import WD_TAB_ALIGNMENT
    section.header.is_linked_to_previous = False
    p = section.header.paragraphs[0]
    p.clear()
    p.alignment = 0
    p.paragraph_format.first_line_indent = Mm(0)
    tabs = p.paragraph_format.tab_stops
    tabs.clear_all()
    width = section.page_width - section.left_margin - section.right_margin
    parts = {part.position: part for part in options.header_parts}
    if 'center' in parts:
        tabs.add_tab_stop(int(width / 2), WD_TAB_ALIGNMENT.CENTER)
    if 'right' in parts:
        tabs.add_tab_stop(width, WD_TAB_ALIGNMENT.RIGHT)
    for position in ('left', 'center', 'right'):
        if position not in parts:
            continue
        if position != 'left':
            p.add_run('\t')
        part = parts[position]
        run = p.add_run(header_text(part))
        apply_run_typography(run, part)


def section(doc, options, landscape):
    current = doc.add_section(WD_SECTION_START.NEW_PAGE)
    page_setup(current, options, landscape)
    vertical_alignment(current, 'top')
    current.different_first_page_header_footer = False
    if options.header_parts:
        multipart_header(current, options)


def header_text(control):
    return ' '.join(line.text for line in [control, *control.additional_lines])


def vertical_alignment(section, value):
    for existing in list(section._sectPr.findall(qn('w:vAlign'))):
        section._sectPr.remove(existing)
    align = OxmlElement('w:vAlign')
    align.set(qn('w:val'), value)
    section._sectPr.insert_element_before(align, 'w:noEndnote', 'w:titlePg', 'w:textDirection', 'w:bidi', 'w:rtlGutter', 'w:docGrid', 'w:printerSettings', 'w:sectPrChange')


def wrap_cover(doc, start, options):
    """Use a borderless cell: section vAlign survives LO save but is not rendered.

    Minimum height lets oversized covers expand without hiding text. Reserve room
    for the section-break paragraph; no business content or font size is chosen.
    """
    from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_ROW_HEIGHT_RULE
    blocks = list(doc.element.body)[start:-1]
    table = doc.add_table(rows=1, cols=1)
    table.autofit = False
    table.columns[0].width = Mm(available_width(options))
    row = table.rows[0]
    row.height = doc.sections[0].page_height - doc.sections[0].top_margin - doc.sections[0].bottom_margin - Pt(24)
    row.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
    cell = row.cells[0]
    cell.vertical_alignment = {'top':WD_CELL_VERTICAL_ALIGNMENT.TOP,
        'center':WD_CELL_VERTICAL_ALIGNMENT.CENTER, 'bottom':WD_CELL_VERTICAL_ALIGNMENT.BOTTOM}[options.cover_vertical_alignment]
    cell._tc.remove(cell.paragraphs[0]._p)
    for block in blocks:
        cell._tc.append(block)
    if cell._tc[-1].tag != qn('w:p'):
        cell.add_paragraph()
    borders = OxmlElement('w:tblBorders')
    for side in ('top','left','bottom','right','insideH','insideV'):
        border = OxmlElement('w:'+side); border.set(qn('w:val'),'nil'); borders.append(border)
    table._tbl.tblPr.append(borders)


def apply_typography(target, control, is_style=False):
    if control.line_spacing is not None:
        target.paragraph_format.line_spacing = control.line_spacing
    for side in ('before', 'after'):
        lines = getattr(control, 'space_'+side+'_lines')
        points = getattr(control, 'space_'+side+'_pt')
        if lines is not None or points is not None:
            spacing = target._element.get_or_add_pPr().get_or_add_spacing()
            spacing.attrib.pop(qn('w:'+side+'Autospacing'), None)
            spacing.attrib.pop(qn('w:'+side+'AutoSpacing'), None)
            if lines is not None:
                spacing.attrib.pop(qn('w:'+side), None)
                spacing.set(qn('w:'+side+'Lines'), str(round(lines*100)))
            else:
                spacing.attrib.pop(qn('w:'+side+'Lines'), None)
                setattr(target.paragraph_format, 'space_'+side, Pt(points))
    if control.left_indent_mm is not None:
        target.paragraph_format.left_indent = Mm(control.left_indent_mm)
    if control.hanging_indent_mm is not None:
        target.paragraph_format.first_line_indent = -Mm(control.hanging_indent_mm)
    if control.first_line_indent_mm is not None:
        target.paragraph_format.first_line_indent = Mm(control.first_line_indent_mm)
    if control.first_line_indent_chars is not None:
        current = target if is_style else target.style
        size = control.font_size
        while size is None and current is not None:
            size = current.font.size.pt if current.font.size is not None else None
            current = current.base_style
        target.paragraph_format.first_line_indent = Pt(control.first_line_indent_chars * (size or 12))
    if control.line_spacing_pt is not None:
        target.paragraph_format.line_spacing = Pt(control.line_spacing_pt)
    if control.alignment is not None:
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        alignment = {'left': WD_ALIGN_PARAGRAPH.LEFT, 'center': WD_ALIGN_PARAGRAPH.CENTER,
                     'right': WD_ALIGN_PARAGRAPH.RIGHT, 'justify': WD_ALIGN_PARAGRAPH.JUSTIFY}[control.alignment]
        if is_style:
            target.paragraph_format.alignment = alignment
        else:
            target.alignment = alignment
    for run in ([target] if is_style else target.runs):
        apply_run_typography(run, control)


def apply_run_typography(run, control):
    if control.font_size is not None: run.font.size = Pt(control.font_size)
    if control.font_family is not None:
        run.font.name = control.font_family
        fonts = run.element.get_or_add_rPr().get_or_add_rFonts()
        for theme in ('asciiTheme', 'hAnsiTheme'):
            fonts.attrib.pop(qn('w:'+theme), None)
    if control.east_asia_font is not None:
        fonts = run.element.get_or_add_rPr().get_or_add_rFonts()
        fonts.attrib.pop(qn('w:eastAsiaTheme'), None)
        fonts.set(qn('w:eastAsia'), control.east_asia_font)
    if control.bold is not None: run.font.bold = control.bold


def apply_paragraph(p, item):
    p.paragraph_format.keep_with_next = bool(item.heading_level) or item.keep_with_next
    p.paragraph_format.page_break_before = item.page_break_before
    apply_typography(p, item)


def emit_text(doc, text, image_renderer, controls, *, table_formatter=None):
    """Style rendered paragraphs without splitting the author's Markdown."""
    from .exporting import _add_markdown
    selected = {item.text: item for item in controls}

    def format_paragraph(p, lines):
        matched = [selected[line] for line in lines if line in selected]
        styles = [item.model_dump(exclude={'text'}) for item in matched]
        if styles and any(style != styles[0] for style in styles[1:]):
            raise ActionRejected('CONFLICTING_LAYOUT_FOR_SAME_RENDERED_PARAGRAPH')
        if matched:
            item = matched[0]
            if item.heading_level:
                p.style = doc.styles[f'Heading {item.heading_level}']
            apply_paragraph(p, item)

    _add_markdown(doc, text, image_renderer, table_formatter=table_formatter,
                  paragraph_formatter=format_paragraph,
                  paragraph_boundary=lambda before, after: any(
                      selected[line].heading_level for line in (before, after) if line in selected))


def mark_blocks(doc, start, stop, index):
    blocks = list(doc.element.body)[start:stop]
    paragraphs = [p for block in blocks for p in ([block] if block.tag == qn('w:p') else list(block.iter(qn('w:p'))))]
    if not paragraphs:
        raise ActionRejected('LAYOUT_NODE_ANCHOR_MISSING')
    for offset, paragraph in enumerate((paragraphs[0], paragraphs[-1])):
        ident = str(index * 2 + offset)
        mark = OxmlElement('w:bookmarkStart'); mark.set(qn('w:id'), ident)
        mark.set(qn('w:name'), f'layout_{index}_{offset}')
        end = OxmlElement('w:bookmarkEnd'); end.set(qn('w:id'), ident)
        paragraph.append(mark); paragraph.append(end)


def remap_blocks(doc, mappings):
    anchors = {}
    for index, block in enumerate(doc.element.body):
        for mark in block.iter(qn('w:bookmarkStart')):
            name = mark.get(qn('w:name'))
            if name in anchors:
                raise ActionRejected('FINALIZED_ANCHOR_DUPLICATE')
            anchors[name] = index
    for item in mappings:
        n = item['layout_anchor']
        if f'layout_{n}_0' not in anchors or f'layout_{n}_1' not in anchors:
            raise ActionRejected('FINALIZED_ANCHOR_MISSING')
        item['block_start'] = anchors[f'layout_{n}_0']
        item['block_stop'] = anchors[f'layout_{n}_1'] + 1
