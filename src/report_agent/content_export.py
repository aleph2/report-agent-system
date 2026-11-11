"""Snapshot-only export and rendering. Neither operation confers acceptance."""
from __future__ import annotations

import hashlib
from copy import deepcopy
import shutil
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path

from docx import Document

from .content_models import Ref
from .errors import ActionForbidden, ActionRejected
from .store import digest
from .material_issues import (validate_node, rendered_issues, comment_passage,
    table_header, validate_required_issues)


def _asset(store, name, data):
    root = store.root / "content-assets"
    root.mkdir(exist_ok=True)
    path = root / name
    if path.exists():
        if path.read_bytes() != data:
            raise ActionRejected("ASSET_IDENTITY_CONFLICT")
        return path.relative_to(store.root).as_posix()
    path.write_bytes(data)
    return path.relative_to(store.root).as_posix()


def _bytes(store, asset, expected):
    path = (store.root / asset).resolve()
    if not path.is_relative_to((store.root / "content-assets").resolve()):
        raise ActionForbidden("ASSET_OUTSIDE_PROJECT")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ActionRejected("ASSET_DIGEST_MISMATCH")
    return data


def _emit_source_views(doc, text, views, emit_text, render_image, width_mm):
    """Display approved source crops in place of unique, unchanged source passages."""
    from PIL import Image
    from docx.shared import Mm, Pt
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    spans = []
    for view in views:
        passage = view.get('text')
        if not isinstance(passage, str) or not passage or text.count(passage) != 1:
            raise ActionRejected('SOURCE_VIEW_PASSAGE_MUST_BE_UNIQUE')
        start = text.index(passage)
        spans.append((start, start + len(passage), view))
    spans.sort(key=lambda item: item[0])
    if any(left[1] > right[0] for left, right in zip(spans, spans[1:])):
        raise ActionRejected('SOURCE_VIEW_PASSAGES_OVERLAP')
    cursor = 0
    for start, stop, view in spans:
        if text[cursor:start].strip():
            emit_text(text[cursor:start])
        png = render_image(view)
        section = doc.sections[-1]
        height_mm = (section.page_height - section.top_margin - section.bottom_margin) / 36000 - 12
        with Image.open(BytesIO(png)) as image:
            width = min(width_mm, height_mm * image.width / image.height)
        doc.add_picture(BytesIO(png), width=Mm(width))
        paragraph = doc.paragraphs[-1]
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        paragraph.paragraph_format.first_line_indent = Mm(0)
        paragraph.paragraph_format.space_before = paragraph.paragraph_format.space_after = Pt(0)
        paragraph.paragraph_format.line_spacing = 1
        cursor = stop
    if text[cursor:].strip():
        emit_text(text[cursor:])


def export_snapshot(contents, actor, operation_id, snapshot_ref, layout=None, layout_from_export_ref=None, *, deliverable=None):
    from .commission_requirements import export_preflight
    export_preflight(contents, actor, snapshot_ref, deliverable)
    def execute(db):
        nonlocal snapshot_ref
        from .prompt_sources import review_interface_profile
        v4 = review_interface_profile(contents.store) == 'review-interfaces-v4'
        if deliverable is not None:
            if not v4 or snapshot_ref is not None:
                raise ActionRejected('EXPORT_DELIVERABLE_SELECTION_CONFLICT')
            from .deliverables import resolve_snapshot
            snapshot_ref = resolve_snapshot(contents, db, actor, deliverable)
        if actor.role not in {"coordinator", "writer", "layout"}:
            raise ActionForbidden("FORBIDDEN: export producer")
        snapshot = contents._read(db, snapshot_ref)
        delegated = False
        if actor.role == "layout":
            task = contents._read(db, {"type": "DelegatedTask", "id": actor.task_id, "version": 1})
            delegated = (actor.id == "content:layout:" + actor.task_id and
                task["payload"].get("role") == "layout" and
                task["payload"].get("layout_snapshot_ref") == snapshot_ref)
        allowed = delegated or actor.role != 'layout' and snapshot['owner_id'] == actor.id
        if v4:
            from .deliverables import export_allowed
            allowed = export_allowed(contents, db, actor, snapshot)
        if snapshot_ref["type"] != "DocumentSnapshot" or not allowed:
            raise ActionForbidden("FORBIDDEN: snapshot owner")
        from .commission_requirements import require_snapshot
        require_snapshot(contents, db, snapshot)
        if layout is not None and layout_from_export_ref is not None:
            raise ActionRejected("LAYOUT_AND_SOURCE_MUTUALLY_EXCLUSIVE")
        selected_layout = layout
        if layout_from_export_ref is not None:
            source = contents._read(db, layout_from_export_ref)
            if (layout_from_export_ref['type'] != 'ExportArtifact' or
                    not source['payload'].get('file_ref', '').endswith('.docx')):
                raise ActionRejected('LAYOUT_SOURCE_REQUIRES_WORD_EXPORT')
            selected_layout = source['payload'].get('export_config', {}).get('layout')
            if not isinstance(selected_layout, dict):
                raise ActionRejected('LAYOUT_SOURCE_CONFIG_MISSING')
        records = {Ref.model_validate(r).key(): contents._read(db, r) for r in snapshot["payload"]["refs"]}
        plan_ref = snapshot['payload'].get('commission_plan_ref')
        plan = contents._read(db, plan_ref)['payload'] if plan_ref else None
        method_pack = plan.get('method_pack') if plan else None
        edges = {}
        for record in records.values():
            p = record["payload"]
            if record["ref"]["type"] == "Relation" and p["predicate"] == "contains":
                edges.setdefault(Ref.model_validate(p["subject_ref"]).key(), []).append((p["position"], p["object_ref"]))
        doc, mappings = Document(), []
        end_notes, qualifier_mappings = [], []
        from . import content_layout as presentation
        rendered_keys = set()
        def collect_body(ref):
            key = Ref.model_validate(ref).key()
            if key in rendered_keys:
                return
            rendered_keys.add(key)
            for _, child in edges.get(key, []):
                collect_body(child)
        collect_body(snapshot['payload']['root_ref'])
        from .material_issues import export_issue_records
        issue_records, owner_issues = export_issue_records(contents, db, snapshot, records)
        validate_required_issues(contents, db, snapshot, records, issue_records)
        from .material_issues import instruction_sources
        excluded_ids, excluded_titles = instruction_sources(db, records)
        from .g3_export import prepare_export, citation_text
        selected_layout = prepare_export(contents, snapshot, records, rendered_keys, selected_layout)
        options = presentation.LayoutOptions.model_validate(selected_layout or {})
        node_options = presentation.validate_layout(options, records, rendered_keys)
        root_key = Ref.model_validate(snapshot['payload']['root_ref']).key()
        title_pages = [ref for _, ref in sorted(edges.get(root_key, []), key=lambda pair: pair[0])
                       if method_pack and records[Ref.model_validate(ref).key()]['payload']['body'].get('page_role') == 'title_page']
        if options.cover_vertical_alignment and records[Ref.model_validate(snapshot['payload']['root_ref']).key()]['payload']['kind'] != 'report':
            raise ActionRejected('COVER_ALIGNMENT_REQUIRES_REPORT_ROOT')
        if options.refresh_toc and records[Ref.model_validate(snapshot['payload']['root_ref']).key()]['payload']['kind'] != 'report':
            raise ActionRejected('DIRECTORY_REFRESH_REQUIRES_REPORT_ROOT')
        from .layout_revision import check as check_layout_revision
        export_config = {"exporter_digest": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                         "layout_engine_digest": hashlib.sha256(Path(presentation.__file__).read_bytes()).hexdigest(),
                         "material_issue_ids": [issue.id for _, issue in issue_records],
                         "helper_digests": {name: hashlib.sha256(Path(__file__).with_name(name + '.py').read_bytes()).hexdigest()
                                            for name in ('g3_export', 'material_issues', 'commission_owner_records')},
                         "layout": options.model_dump()}
        if layout_from_export_ref is not None:
            export_config['layout_source'] = {'export_ref': layout_from_export_ref,
                                              'layout_digest': digest(options.model_dump())}
        layout_revision = check_layout_revision(db, export_config)
        presentation.setup(doc, options)
        toc_headings = []
        def headings(ref, depth):
            if ref in title_pages:
                return
            key = Ref.model_validate(ref).key()
            node = records[key]["payload"]
            style = node_options.get(key)
            level = (style.heading_level if style and style.heading_level else depth if node['kind'] == 'chapter' else None)
            heading_text = node['body'].get('text', '') if node['kind'] not in {'table', 'figure'} else ''
            first = heading_text.split('\n', 1)[0]
            first_control = next((p for p in style.paragraphs if p.text == first), None) if style else None
            if first_control and first_control.heading_level:
                level = first_control.heading_level
            if first and level and level <= options.toc_depth:
                toc_headings.append((first, level))
            if style:
                for line in heading_text.split('\n'):
                    for paragraph in style.paragraphs:
                        if paragraph.text == line and paragraph.heading_level and paragraph.heading_level <= options.toc_depth:
                            if not (level and line == node['body']['text'].split('\n', 1)[0]):
                                toc_headings.append((line, paragraph.heading_level))
            for _, child in sorted(edges.get(key, []), key=lambda p: p[0]):
                headings(child, depth+1)
        headings(snapshot['payload']['root_ref'], 0)
        from .exporting import _source_images
        from types import SimpleNamespace
        adopted_sources = {r["payload"]["source_id"] for r in records.values() if r["ref"]["type"] == "SourceArtifact"}
        source_versions = {r["payload"]["source_id"]: r["payload"] for r in records.values() if r["ref"]["type"] == "SourceArtifact"}
        # Both figure objects and Markdown images must use frozen, authorized bytes.
        from .document_tools import markdown_source_ids, _original
        image_sources = set()
        for record in records.values():
            if record["ref"]["type"] != "ContentNode":
                continue
            node = record["payload"]
            if node['body'].get('source_views'):
                if not plan or not plan.get('method_pack'):
                    raise ActionRejected('SOURCE_VIEWS_REQUIRE_G3_PLAN')
                image_sources.update(view['source_id'] for view in node['body']['source_views'])
            if node["kind"] == "figure":
                image_sources.add(node["body"]["source_id"])
            elif isinstance(node["body"].get("text"), str):
                image_sources.update(markdown_source_ids(node["body"]["text"]))
        if not image_sources <= adopted_sources:
            raise ActionRejected("IMAGE_SOURCE_OUTSIDE_SNAPSHOT")
        used_images = set()
        source_workspace = SimpleNamespace(store=contents.store)
        for source_id in image_sources:
            _, original = _original(source_workspace, source_id)
            if hashlib.sha256(original).hexdigest() != source_versions[source_id]["file_digest"]:
                raise ActionRejected("IMAGE_SOURCE_VERSION_MISMATCH")
        image_renderer = _source_images(source_workspace, doc, used_images)
        from docx.shared import RGBColor
        for name in ("Normal", "Title", "Heading 1", "Heading 2", "Heading 3"):
            doc.styles[name].font.color.rgb = RGBColor(0, 0, 0)
            from docx.oxml.ns import qn
            for border in doc.styles[name].element.iter(qn("w:pBdr")):
                border.getparent().remove(border)
        def emit(ref, depth):
            node = records[Ref.model_validate(ref).key()]["payload"]
            body, kind = node["body"], node["kind"]
            issues, merges = validate_node(node, ref)
            style = node_options.get(Ref.model_validate(ref).key())
            def format_embedded_table(table):
                presentation.format_table(table, options, style, embedded=True)
            controls = style.paragraphs if style else []
            if style and style.landscape:
                presentation.section(doc, options, True)
            elif style and style.page_break_before:
                doc.add_page_break()
            start = len(list(doc.element.body)) - 1
            paragraph_start = len(doc.paragraphs)
            if plan and plan.get('format_source') and (kind == 'report' or ref in title_pages):
                # Cover/title lines are literal fields with distinct typography, not Markdown prose.
                for line in body['text'].split('\n'):
                    paragraph = doc.add_paragraph(line)
                    control = next((item for item in controls if item.text == line), None)
                    if control:
                        presentation.apply_paragraph(paragraph, control)
            elif kind == "table":
                title = presentation.caption(node)
                if title:
                    p = doc.add_paragraph(title, "Caption")
                    p.paragraph_format.keep_with_next = True
                headers, header_merges = table_header(body)
                header_count = len(headers)
                table = doc.add_table(rows=0, cols=len(body["columns"]), style="Table Grid")
                for values in [*headers, *body["rows"]]:
                    for cell, value in zip(table.add_row().cells, values):
                        cell.text = str(value)
                for merge in merges:
                    first = table.cell(merge.start_row + header_count, merge.start_col)
                    value = first.text
                    first.merge(table.cell(merge.end_row + header_count, merge.end_col)).text = value
                presentation.format_table(table, options, style)
                # Row.cells aliases horizontal spans; format_table assigns each grid width in turn.
                for merge in merges:
                    if merge.start_col != merge.end_col:
                        table.cell(merge.start_row + header_count, merge.start_col).width = sum(
                            table.columns[index].width for index in range(merge.start_col, merge.end_col + 1))
                # Set individual widths before horizontal spans; preserve styled primary paragraph.
                for merge in header_merges:
                    first = table.cell(merge.start_row, merge.start_col)
                    paragraph = deepcopy(first.paragraphs[0]._p)
                    cell = first.merge(table.cell(merge.end_row, merge.end_col))
                    for other in list(cell.paragraphs):
                        other._p.getparent().remove(other._p)
                    cell._tc.append(paragraph)
                from docx.oxml import OxmlElement
                from docx.oxml.ns import qn
                for row in table.rows[:header_count]:
                    properties = row._tr.get_or_add_trPr()
                    if properties.find(qn('w:tblHeader')) is None:
                        properties.append(OxmlElement('w:tblHeader'))
                    for cell in row.cells:
                        for paragraph in cell.paragraphs:
                            for run in paragraph.runs:
                                run.bold = True
                for issue in issues:
                    cell = table.cell(issue.anchor.row + header_count, issue.anchor.column)
                    doc.add_comment(cell.paragraphs[0].runs, issue.comment(excluded_titles), author="待核", initials="核")
                footnote = presentation.table_footnote(body)
                if footnote is not None:
                    doc.add_paragraph(footnote)
            elif kind == "figure":
                from .document_tools import vision_source_image
                png, _ = vision_source_image(source_workspace, body["source_id"], body.get("page", 1), None)
                used_images.add(body["source_id"])
                from docx.shared import Mm
                available = presentation.available_width(options, bool(style and style.landscape))
                doc.add_picture(BytesIO(png), width=Mm(min(style.figure_width_mm if style and style.figure_width_mm else available, available)))
                doc.add_paragraph(body["caption"], "Caption")
            elif body.get('source_views'):
                from .document_tools import vision_source_image
                def render_source_view(view):
                    png, _ = vision_source_image(source_workspace, view['source_id'], view['page'], view['crop'])
                    used_images.add(view['source_id'])
                    return png
                _emit_source_views(doc, body['text'], body['source_views'],
                    lambda text: presentation.emit_text(doc, text, image_renderer, controls, table_formatter=format_embedded_table),
                    render_source_view, presentation.available_width(options, bool(style and style.landscape)))
            elif kind in {"report", "chapter"}:
                first, _, rest = body["text"].partition("\n")
                first_control = next((p for p in controls if p.text == first), None)
                if kind == "report" and not first_control and len(first) > 100 and "。" in first:
                    title, separator, continuation = first.partition("。")
                    first, rest = title + separator, continuation + ("\n" + rest if rest else "")
                level = 0 if kind == 'report' else style.heading_level if style and style.heading_level else min(depth, 9)
                p = doc.add_heading(first, first_control.heading_level if first_control and first_control.heading_level else level)
                if first_control:
                    presentation.apply_paragraph(p, first_control)
                if rest.strip():
                    from .exporting import _add_markdown
                    presentation.emit_text(doc, rest, image_renderer, controls, table_formatter=format_embedded_table)
            else:
                # Preserve full actual text and its explicit qualifiers; no model summarization.
                from .exporting import _add_markdown
                if style and style.heading_level and not any(p.text == body['text'].split('\n', 1)[0] for p in controls):
                    first, _, rest = body["text"].partition("\n")
                    doc.add_heading(first, style.heading_level)
                    if rest.strip():
                        presentation.emit_text(doc, rest, image_renderer, controls, table_formatter=format_embedded_table)
                else:
                    presentation.emit_text(doc, body["text"], image_renderer, controls, table_formatter=format_embedded_table)
            if body.get('section_heading') and body['text'].split(' ', 1)[-1] == '待核事项':
                doc.add_paragraph(f'本草稿共{len(issue_records)}项待核事项，详见随附 Excel 问题清单；本文件批注记录相同事项。')
            if kind == 'report' and depth == 0 and plan and plan.get('report_title') and not plan.get('format_source'):
                doc.add_paragraph('编制日期：' + snapshot['created_at'][:10])
            if kind != 'table':
                for issue in issues:
                    comment_passage(doc, doc.paragraphs[paragraph_start:], issue, ref, excluded_titles)
            citation = citation_text(node, records, plan=plan, excluded=excluded_ids)
            if citation:
                paragraphs = [p for p in doc.paragraphs[paragraph_start:] if not p.style.name.startswith('Heading')]
                if kind == 'table':
                    paragraphs = paragraphs[:1]
                runs = [run for p in paragraphs for run in p.runs]
                if runs:
                    doc.add_comment(runs, '来源：' + citation, author='来源', initials='源')
            visible = {k: v for k, v in node["qualifiers"].items() if k not in presentation.STRUCTURAL}
            # Suppress only a full literal qualifier line already emitted in this node.
            body_lines = body['text'].splitlines() if kind not in {'table', 'figure'} else []
            visible = {key: value for key, value in visible.items()
                if f"{'来源说明' if key == 'source_note' else key}：{value}" not in body_lines}
            if visible:
                parts = [f"{'来源说明' if key == 'source_note' else key}：{value}" for key, value in visible.items()]
                text = parts[0]
                for part in parts[1:]:
                    text += (" " if text.rstrip().endswith(('。', '！', '？', '.', '!', '?')) else "；") + part
                if style and style.qualifier_placement == 'end_notes':
                    number = len(end_notes) + 1
                    end_notes.append((number, ref, visible, text, style.qualifier_font_size))
                    text = f"〔说明 {number}〕"
                p = doc.add_paragraph(text)
                from docx.shared import Pt
                for run in p.runs:
                    run.font.size = Pt(style.qualifier_font_size if style else 10)
            if kind == 'report' and depth == 0 and options.cover_vertical_alignment:
                presentation.wrap_cover(doc, start, options)
            stop = len(list(doc.element.body)) - 1
            presentation.mark_blocks(doc, start, stop, len(mappings))
            mappings.append({"node_ref": ref, "block_start": start,
                "block_stop": stop, "layout_anchor": len(mappings), "content_digest": digest(body),
                "qualifiers": node["qualifiers"]})
            if style and style.landscape:
                presentation.section(doc, options, False)
            cover_section = kind == 'report' and depth == 0 and options.cover_vertical_alignment is not None
            cover_break = cover_section and (options.toc or edges.get(Ref.model_validate(ref).key()) or end_notes)
            if cover_break:
                presentation.section(doc, options, False)
                from docx.shared import Pt
                separator = doc.paragraphs[-1].paragraph_format
                separator.line_spacing = Pt(1)
                separator.space_before = separator.space_after = Pt(0)
                separator.keep_with_next = separator.page_break_before = False
            if kind == "report" and depth == 0:
                for title_page in title_pages:
                    emit(title_page, depth + 1)
                if options.toc:
                    presentation.add_toc(doc, toc_headings, options.toc_depth,
                        start_new_page=bool(title_pages) or not cover_break, options=options)
                elif title_pages and any(child not in title_pages for _, child in edges.get(root_key, [])):
                    presentation.section(doc, options, False)
            children = [child for _, child in sorted(edges.get(Ref.model_validate(ref).key(), []), key=lambda p: p[0])
                        if not (depth == 0 and child in title_pages)]
            for child in children:
                emit(child, depth + 1)
        emit(snapshot["payload"]["root_ref"], 0)
        if owner_issues:
            doc.add_paragraph("业主范围决定", "Heading 1")
            for issue in owner_issues:
                paragraph = doc.add_paragraph(issue.adopted_value)
                doc.add_comment(paragraph.runs, issue.comment(excluded_titles), author="待核", initials="核")
        if end_notes:
            notes_heading = doc.add_paragraph('说明', 'Title')
            notes_heading.paragraph_format.keep_with_next = True
            from docx.shared import Pt
            for number, ref, visible, text, size in end_notes:
                start = len(list(doc.element.body)) - 1
                p = doc.add_paragraph(f'〔说明 {number}〕{text}')
                for run in p.runs:
                    run.font.size = Pt(size)
                stop = len(list(doc.element.body)) - 1
                anchor = len(mappings) + len(qualifier_mappings)
                presentation.mark_blocks(doc, start, stop, anchor)
                qualifier_mappings.append({'node_ref': ref, 'block_start': start,
                    'block_stop': stop, 'layout_anchor': anchor,
                    'note_number': number, 'qualifiers': visible, 'qualifier_digest': digest(visible)})
        if not used_images <= adopted_sources:
            raise ActionRejected("IMAGE_SOURCE_OUTSIDE_SNAPSHOT")
        anchors = {Ref.model_validate(m["node_ref"]).key(): m for m in mappings}
        for record in records.values():
            p = record["payload"]
            if record["ref"]["type"] == "Relation" and p["predicate"] in {"expresses", "references"}:
                subject = Ref.model_validate(p["subject_ref"]).key()
                if subject in anchors and p["object_ref"]["type"] == "ContentNode":
                    mappings.append({**anchors[subject], "node_ref": p["object_ref"], "via_relation": record["ref"]})
        mapped = {Ref.model_validate(m["node_ref"]).key() for m in mappings}
        unrendered = [r["ref"] for key, r in records.items() if key[0] == "ContentNode" and key not in mapped]
        buffer = BytesIO()
        doc.save(buffer)
        data = buffer.getvalue()
        finalization = None
        if options.refresh_toc:
            if not options.toc:
                raise ActionRejected('TOC_REFRESH_REQUIRES_TOC')
            from .layout_capabilities import refresh_directory
            data, finalization = refresh_directory(contents.store, data)
            presentation.remap_blocks(Document(BytesIO(data)), mappings)
            presentation.remap_blocks(Document(BytesIO(data)), qualifier_mappings)
        checksum = hashlib.sha256(data).hexdigest()
        asset = _asset(contents.store, checksum + ".docx", data)
        export_ref = contents._insert(db, actor, "ExportArtifact", {"snapshot_ref": snapshot_ref,
            "file_ref": asset, "file_digest": checksum, "template_ref": "snapshot-layout-v7",
            "export_config": {**export_config, "layout_revision": layout_revision,
                              "finalization": finalization}})
        mapping_ref = contents._insert(db, actor, "MappingArtifact", {"snapshot_ref": snapshot_ref,
            "export_ref": export_ref, "anchor_records": mappings, "unrendered_dependency_nodes": unrendered,
            "qualifier_anchor_records": qualifier_mappings,
            "limitation": "OOXML block indices bind only this export; page coordinates require a render."})
        result = {"export_ref": export_ref, "mapping_ref": mapping_ref, "file_ref": asset, "file_digest": checksum}
        if layout_from_export_ref is not None:
            result['layout_source'] = export_config['layout_source']
        from .content_workbook import _export_workbook, companion_sheets
        result['workbook'] = _export_workbook(contents, actor, db, snapshot_ref,
            companion_sheets(snapshot, records, rendered_keys), export_ref, system_companion=True)
        return result
    request = {"export": snapshot_ref}
    if deliverable is not None:
        request['deliverable'] = deliverable
    if layout is not None:
        request["layout"] = layout
    if layout_from_export_ref is not None:
        request['layout_from_export_ref'] = layout_from_export_ref
    return contents.operation(actor, operation_id, request, execute)


def _reviewer_export_scope(contents, actor):
    if actor.role != 'reviewer' or contents.store.get('manifest') is None:
        return None
    from .prompt_sources import review_interface_profile
    if review_interface_profile(contents.store) != 'review-interfaces-v4':
        return None
    from types import SimpleNamespace
    from .content_tasks import bound_actor
    from .task_context import complete_review_materials
    workspace = SimpleNamespace(store=contents.store)
    if bound_actor(workspace, 'reviewer', None) != actor or actor.id != 'content:reviewer:' + actor.task_id:
        raise ActionForbidden('FORBIDDEN: reviewer task binding')
    task = contents.read({'type': 'DelegatedTask', 'id': actor.task_id, 'version': 1})['payload']
    if task.get('role') != 'reviewer' or not task.get('review_snapshot_ref'):
        raise ActionForbidden('FORBIDDEN: reviewer task binding')
    allowed = {Ref.model_validate(record['ref']).key()
               for record in complete_review_materials(workspace, task)['objects']}
    return workspace, task, allowed


def _require_review_export(scope, export_ref):
    if scope is not None and Ref.model_validate(export_ref).key() not in scope[2]:
        raise ActionForbidden('FORBIDDEN: export outside reviewer assignment')


def read_export(contents, actor, export_ref):
    _require_review_export(_reviewer_export_scope(contents, actor), export_ref)
    record = contents.read(export_ref)
    if export_ref["type"] != "ExportArtifact":
        raise ActionRejected("EXPORT_REQUIRED")
    data = _bytes(contents.store, record["payload"]["file_ref"], record["payload"]["file_digest"])
    if record['payload']['file_ref'].endswith('.xlsx'):
        from .content_workbook import read_workbook
        result = read_workbook(data)
        structure, text = result['structure'], result['text']
    else:
        from .report_preview import _structure
        structure, text = _structure(data)
        from .prompt_sources import review_interface_profile
        if contents.store.get('manifest') is not None and review_interface_profile(contents.store) == 'review-interfaces-v4':
            from .content_models import RenderState
            state = RenderState(execution_state='not_attempted', capability_state='not_probed')
            # The legacy preview label describes no attempt, not a capability test.
            structure['render'].update(state.model_dump(), status=state.execution_state)
    return contents.observe(actor, {"export_ref": export_ref, "file_digest": record["payload"]["file_digest"],
        "structure": structure, "text": text, "limitation": "Actual OOXML content; not visual observation."})


def render_export(contents, actor, operation_id, export_ref):
    _require_review_export(_reviewer_export_scope(contents, actor), export_ref)
    def prepare(db):
        export = contents._read(db, export_ref)
        if export_ref["type"] != "ExportArtifact":
            raise ActionRejected("EXPORT_REQUIRED")
        suffix = Path(export['payload']['file_ref']).suffix
        if suffix not in {'.docx', '.xlsx'}:
            raise ActionRejected('RENDER_FORMAT_UNSUPPORTED')
        from .operation_identity import NATIVE, profile
        if contents.store.get('manifest') is not None and profile(contents.store) == NATIVE:
            request_digest = digest({'actor': actor.__dict__, 'request': {'render': export_ref}})
            rows = db.execute('SELECT operation_id,response FROM content_operations '
                              'WHERE actor_id=? AND request_digest=? AND operation_id!=?',
                              (actor.id, request_digest, operation_id)).fetchall()
            for original_id, encoded in rows:
                import json
                if json.loads(encoded).get('code') == 'OPERATION_OUTCOME_UNRESOLVED':
                    raise ActionRejected('RENDER_EXPORT_OUTCOME_UNRESOLVED: related original reservation '
                        'unresolved; this new attempt did not execute; original_operation_id=' + original_id)
        return export

    def execute(export):
        data = _bytes(contents.store, export["payload"]["file_ref"], export["payload"]["file_digest"])
        suffix = Path(export['payload']['file_ref']).suffix
        from .office_render import convert_pdf
        pdf, version = convert_pdf(contents.store, data, suffix)
        if pdf is None:
            result = {"execution_state": "blocked", "verdict": None, "code": "RENDER_UNAVAILABLE",
                      "export_ref": export_ref, "diagnostic": version}
            from .prompt_sources import review_interface_profile
            if contents.store.get('manifest') is not None and review_interface_profile(contents.store) == 'review-interfaces-v4':
                from .content_models import RenderState
                attempts = version.get('attempts') if isinstance(version, dict) and version.get('code') == 'RENDER_UNAVAILABLE' else None
                known = isinstance(attempts, list)
                result['render_state'] = RenderState(
                    execution_state='failed' if known and attempts else 'blocked',
                    capability_state='unavailable' if known and not attempts else 'unknown').model_dump()
            return result
        import pypdfium2 as pdfium
        pages = []
        with pdfium.PdfDocument(pdf) as document:
            for index in range(len(document)):
                page = document[index]
                bitmap = page.render(scale=1.5)
                output = BytesIO()
                bitmap.to_pil().save(output, format="PNG")
                png = output.getvalue()
                sha = hashlib.sha256(png).hexdigest()
                pages.append({"page": index + 1, "asset_ref": _asset(contents.store, sha + ".png", png), "sha256": sha})
                bitmap.close()
                page.close()
        pdf_sha = hashlib.sha256(pdf).hexdigest()
        payload = {"snapshot_ref": export["payload"]["snapshot_ref"], "export_ref": export_ref,
            "export_digest": export["payload"]["file_digest"], "renderer_identity": version,
            "config": {"scale": 1.5}, "pdf_ref": _asset(contents.store, pdf_sha + ".pdf", pdf),
            "pdf_digest": pdf_sha, "page_assets": pages}
        return payload

    def finalize(db, export, computed):
        if contents._read(db, export_ref) != export:
            raise ActionRejected('RENDER_EXPORT_CHANGED')
        _bytes(contents.store, export['payload']['file_ref'], export['payload']['file_digest'])
        if computed.get('execution_state') == 'blocked':
            return computed
        ref = contents._insert(db, actor, "RenderArtifact", computed)
        result = {"render_ref": ref, "pages": computed['page_assets'], "execution_state": "completed", "verdict": None}
        from .prompt_sources import review_interface_profile
        if contents.store.get('manifest') is not None and review_interface_profile(contents.store) == 'review-interfaces-v4':
            from .content_models import RenderState
            result['render_state'] = RenderState(execution_state='completed', capability_state='available').model_dump()
        return result

    return contents.detached_operation(actor, operation_id, {"render": export_ref}, prepare, execute, finalize)


async def inspect_render(contents, actor, render_ref, page, question, client=None, *,
                         reference_source_id="", reference_page=1, crop=None):
    if actor.role == "coordinator":
        from .prompt_sources import review_interface_profile
        if review_interface_profile(contents.store) == 'review-interfaces-v4':
            raise ActionForbidden("FORBIDDEN: coordinator delegates page inspection")
    record = contents.read(render_ref)
    if render_ref["type"] != "RenderArtifact" or not question.strip():
        raise ActionRejected("RENDER_AND_QUESTION_REQUIRED")
    scope = _reviewer_export_scope(contents, actor)
    if scope is not None:
        from .review_work_units import material_allowed
        workspace, task, allowed = scope
        export_ref = record['payload']['export_ref']
        if Ref.model_validate(render_ref).key() not in allowed:
            _require_review_export(scope, export_ref)
        if not material_allowed(workspace, task, Ref.model_validate(render_ref), allowed):
            raise ActionForbidden('FORBIDDEN: render outside reviewer assignment')
        export_payload = contents.read(export_ref)['payload']
        if (export_ref.get('type') != 'ExportArtifact' or not export_payload.get('file_digest')
                or record['payload'].get('snapshot_ref') != task['review_snapshot_ref']
                or export_payload.get('snapshot_ref') != task['review_snapshot_ref']
                or record['payload'].get('export_digest') != export_payload.get('file_digest')):
            raise ActionForbidden('FORBIDDEN: render provenance mismatch')
    pages = record["payload"]["page_assets"]
    if not 1 <= page <= len(pages):
        raise ActionRejected("PAGE_OUT_OF_RANGE")
    export = contents.read(record["payload"]["export_ref"])["payload"]
    if not export["file_ref"].endswith('.docx'):
        raise ActionRejected("WORD_VISUAL_INSPECTION_REQUIRED_NO_EXCEL_LAYOUT")
    asset = pages[page - 1]
    png = _bytes(contents.store, asset["asset_ref"], asset["sha256"])
    provenance = {"source_id": render_ref["id"], "render_ref": render_ref,
        "export_ref": record["payload"]["export_ref"], "page": page,
        "coverage": "full_page_image" if crop is None else "region_only", "crop": crop}
    policy_ref = None
    if reference_source_id:
        from types import SimpleNamespace
        from .source_use import validate_source_versions
        policy_ref = validate_source_versions(SimpleNamespace(store=contents.store), actor, [reference_source_id])
    if crop is not None or reference_source_id:
        import math
        from PIL import Image, ImageDraw
        if crop is not None and (not isinstance(crop, list) or len(crop) != 4
                or any(isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) for n in crop)
                or not (0 <= crop[0] < crop[2] <= 1 and 0 <= crop[1] < crop[3] <= 1)):
            raise ActionRejected("RENDER_IMAGE_INVALID_CROP")
        with Image.open(BytesIO(png)) as original:
            image = original.convert('RGB')
        try:
            if crop is not None:
                bounds = (math.floor(crop[0]*image.width), math.floor(crop[1]*image.height),
                          math.ceil(crop[2]*image.width), math.ceil(crop[3]*image.height))
                region = image.crop(bounds);image.close();image=region
                provenance['crop_pixels'] = bounds
            if reference_source_id:
                from types import SimpleNamespace
                from .document_tools import vision_source_image
                reference_png, reference = vision_source_image(SimpleNamespace(store=contents.store),
                    reference_source_id, reference_page, crop)
                with Image.open(BytesIO(reference_png)) as raw:
                    left = raw.convert('RGB')
                try:
                    # Keep the existing page rendition resolutions; no synthesis,
                    # OCR or automatic semantic page selection is introduced.
                    canvas = Image.new('RGB', (left.width+image.width+24,max(left.height,image.height)+28),'white')
                    try:
                        canvas.paste(left,(0,28));canvas.paste(image,(left.width+24,28))
                        labels = ImageDraw.Draw(canvas)
                        labels.text((4,4),f'CUSTOMER reference physical page {reference_page}',fill='black')
                        labels.text((left.width+28,4),f'GENERATED Word physical page {page}',fill='black')
                        output=BytesIO();canvas.save(output,format='PNG');png=output.getvalue()
                    finally:canvas.close()
                finally:left.close()
                provenance['presentation_reference']=reference
                question='Compare the labeled CUSTOMER reference (left) and GENERATED Word (right) only within the supplied page/region. '+question
            else:
                output=BytesIO();image.save(output,format='PNG');png=output.getvalue()
            if crop is not None:
                question='This is a partial region, not a full-page inspection. '+question
        finally:image.close()
    from .deep_models import configured_vision_client
    from .vision import _observe
    owns = client is None
    client = client or configured_vision_client()
    try:
        result = await _observe(contents.store, png, provenance, question, client, actor,
                                **({'policy_ref': policy_ref} if policy_ref else {}))
        return contents.observe(actor, result)
    finally:
        if owns:
            await client.close()
