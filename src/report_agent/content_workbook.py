"""Serialize agent-owned frozen tables with provenance; never author their contents."""
import hashlib
import json
import math
import re
from io import BytesIO
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from pydantic import BaseModel, ConfigDict, Field

from .content_models import Ref
from .content_export import _asset, _bytes
from .errors import ActionForbidden, ActionRejected
from . import content_layout as presentation
from .material_issues import LABELS, validate_node, rendered_issues, table_header, validate_required_issues


class WorkbookSheet(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=31)
    table_ref: Ref
    note_refs: list[Ref] = Field(default_factory=list,
        description='Optional frozen text ContentNodes to copy verbatim after this table, including correction notices and their qualifiers. Choose applicable notes; this tool never authors them.')


def export_workbook(contents, actor, operation_id, snapshot_ref, sheets, report_export_ref=None, *, deliverable=None):
    from .commission_requirements import export_preflight
    export_preflight(contents, actor, snapshot_ref, deliverable)
    def execute(db):
        nonlocal snapshot_ref
        from .prompt_sources import review_interface_profile, report_expression_profile, READER_EXPRESSION_V2
        v4 = review_interface_profile(contents.store) == 'review-interfaces-v4'
        expression = report_expression_profile(contents.store)
        note_label = '备注' if expression == READER_EXPRESSION_V2 else 'Note'
        if deliverable is not None:
            if not v4 or snapshot_ref is not None:
                raise ActionRejected('EXPORT_DELIVERABLE_SELECTION_CONFLICT')
            from .deliverables import resolve_snapshot
            snapshot_ref = resolve_snapshot(contents, db, actor, deliverable)
        snapshot = contents._read(db, snapshot_ref)
        allowed = snapshot['owner_id'] == actor.id
        if v4:
            from .deliverables import export_allowed
            allowed = export_allowed(contents, db, actor, snapshot)
        if actor.role not in {'coordinator', 'writer'} or snapshot_ref['type'] != 'DocumentSnapshot' or not allowed:
            raise ActionForbidden('FORBIDDEN: workbook snapshot owner')
        from .commission_requirements import require_snapshot
        require_snapshot(contents, db, snapshot)
        members = {Ref.model_validate(r).key() for r in snapshot['payload']['refs']}
        records = {Ref.model_validate(r).key(): contents._read(db, r) for r in snapshot['payload']['refs']}
        issue_records = rendered_issues(records, snapshot['payload']['root_ref'])
        from .commission_owner_records import frozen_material_issues
        owner_issues = frozen_material_issues(contents, snapshot, records)
        if {i.id for _, i in issue_records} & {i.id for i in owner_issues}:
            raise ActionRejected('OWNER_OPEN_FACT_IS_SYSTEM_OWNED')
        issue_records += [(snapshot['payload']['root_ref'], issue) for issue in owner_issues]
        validate_required_issues(contents, db, snapshot, records, issue_records)
        from .g3_export import validate_export, citation_text
        validate_export(contents, snapshot, records)
        plan_ref = snapshot['payload'].get('commission_plan_ref')
        plan = contents._read(db, plan_ref)['payload'] if plan_ref else None
        method_pack = plan.get('method_pack') if plan else None
        if method_pack:
            from .g3_export import _order
            rendered = set(_order(snapshot, records)[0])
            selected = {Ref.model_validate(ref).key() for sheet in sheets
                        for ref in [sheet['table_ref'], *sheet.get('note_refs', [])]}
            if not selected <= rendered:
                raise ActionRejected('G3_WORKBOOK_NODE_NOT_RENDERED')
        clarification = bool(issue_records or method_pack)
        if not sheets and not clarification:
            raise ActionRejected('WORKBOOK_SHEETS_REQUIRED')
        channel = snapshot['payload'].get('workbook_refs')
        if channel:
            declared = {Ref.model_validate(r).key() for r in channel}
            selected = {Ref.model_validate(r).key() for sheet in sheets
                        for r in [sheet['table_ref'],*sheet.get('note_refs',[])]}
            if selected != declared:
                raise ActionRejected('WORKBOOK_CHANNEL_SELECTION_MISMATCH')
        if issue_records and not report_export_ref:
            raise ActionRejected('WORD_EXPORT_REQUIRED_FOR_MATERIAL_ISSUES')
        if report_export_ref:
            linked = contents._read(db, report_export_ref)
            if report_export_ref['type'] != 'ExportArtifact' or not linked['payload']['file_ref'].endswith('.docx'):
                raise ActionRejected('WORD_EXPORT_REQUIRED')
            if linked['payload']['snapshot_ref'] != snapshot_ref:
                raise ActionRejected('WORD_WORKBOOK_SNAPSHOT_MISMATCH')
            _bytes(contents.store, linked['payload']['file_ref'], linked['payload']['file_digest'])
            if linked['payload'].get('export_config', {}).get('material_issue_ids', []) != [issue.id for _, issue in issue_records]:
                raise ActionRejected('WORD_WORKBOOK_MATERIAL_ISSUE_MISMATCH')
        names = set()
        workbook, mappings = Workbook(), []
        unverified_annotation_rows = []
        workbook.remove(workbook.active)
        def text(value):
            value = str(value) if value is not None else ''
            if len(value) > 32767 or re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', value):
                raise ActionRejected('WORKBOOK_CELL_TEXT_UNSUPPORTED')
            return value
        def qualifier_rows(node):
            lines = node['body'].get('text', '').splitlines()
            result = []
            for key, value in node.get('qualifiers', {}).items():
                label = '来源说明' if key == 'source_note' else str(key)
                if key in presentation.STRUCTURAL or f'{label}：{value}' in lines:
                    continue
                result.append([label, text(value) if not isinstance(value, (dict, list)) else json.dumps(value, ensure_ascii=False)])
            return result
        for sheet in sheets:
            name, ref = sheet['name'], sheet['table_ref']
            if not name.strip() or re.search(r'[\\/*?:\[\]]', name) or name.startswith("'") or name.endswith("'") or name.casefold() in names:
                raise ActionRejected('INVALID_OR_DUPLICATE_SHEET_NAME')
            names.add(name.casefold())
            if Ref.model_validate(ref).key() not in members or ref['type'] != 'ContentNode':
                raise ActionRejected('TABLE_OUTSIDE_SNAPSHOT')
            node = contents._read(db, ref)['payload']
            if node['kind'] != 'table':
                raise ActionRejected('TABLE_NODE_REQUIRED')
            body = node['body']
            _, merges = validate_node(node)
            rows = qualifier_rows(node)
            annotation_rows = [(i, 2) for i in range(1, len(rows) + 1)]
            header_row = len(rows) + 1
            headers, header_merges = table_header(body)
            header_count = len(headers)
            rows += [*headers, *body['rows']]
            table_stop = len(rows)
            footnote = presentation.table_footnote(body)
            if footnote is not None:
                start = len(rows) + 1
                rows.append([footnote])
                annotation_rows.append((start, 1))
                mappings.append({'node_ref': ref, 'sheet': name, 'kind': 'table-footnote',
                                 'row_start': start, 'row_stop': len(rows) + 1})
            citation = citation_text(node, records, plan=plan)
            if citation:
                rows.append([citation])
                annotation_rows.append((len(rows), 1))
            seen_notes = set()
            for note_ref in sheet.get('note_refs', []):
                key = Ref.model_validate(note_ref).key()
                if key in seen_notes:
                    raise ActionRejected('DUPLICATE_WORKBOOK_NOTE')
                seen_notes.add(key)
                if key not in members or note_ref['type'] != 'ContentNode':
                    raise ActionRejected('NOTE_OUTSIDE_SNAPSHOT')
                note = contents._read(db, note_ref)['payload']
                if note['kind'] not in {'report', 'chapter', 'block', 'claim'} or type(note['body'].get('text')) is not str:
                    raise ActionRejected('WORKBOOK_TEXT_NOTE_REQUIRED')
                start = len(rows) + 1
                rows += [[note_label, line] for line in note['body']['text'].split('\n')]
                citation = citation_text(note, records, plan=plan)
                if citation:
                    rows.append([note_label, citation])
                rows += qualifier_rows(note)
                annotation_rows.extend((i, 2) for i in range(start, len(rows) + 1))
                mappings.append({'node_ref': note_ref, 'sheet': name, 'kind': 'note',
                                 'row_start': start, 'row_stop': len(rows) + 1})
            if len(rows) > 1048576 or max(map(len, rows)) > 16384:
                raise ActionRejected('WORKBOOK_DIMENSIONS_UNSUPPORTED')
            ws = workbook.create_sheet(name)
            for row_index, row in enumerate(rows, 1):
                for col_index, value in enumerate(row, 1):
                    cell = ws.cell(row_index, col_index, text(value))
                    cell.data_type = 's'  # User/source text is never an executable formula.
                    cell.alignment = Alignment(vertical='top', wrap_text=True)
                    if header_row <= row_index < header_row + header_count:
                        cell.font = Font(bold=True, color='FFFFFF')
                        cell.fill = PatternFill('solid', fgColor='244A63')
            for index in range(1, max(map(len, rows)) + 1):
                ws.column_dimensions[get_column_letter(index)].width = 28
            for merge in header_merges:
                ws.merge_cells(start_row=header_row + merge.start_row,
                    end_row=header_row + merge.end_row, start_column=merge.start_col + 1,
                    end_column=merge.end_col + 1)
            for merge in merges:
                ws.merge_cells(start_row=header_row + header_count + merge.start_row,
                    end_row=header_row + header_count + merge.end_row, start_column=merge.start_col + 1,
                    end_column=merge.end_col + 1)
            if expression == READER_EXPRESSION_V2:
                last_column = max(map(len, rows))
                for row_index, text_column in annotation_rows:
                    value = ws.cell(row_index, text_column).value or ''
                    width = 28 * (last_column - text_column + 1) * 0.8
                    def lines(value, width):
                        # Conservative glyph estimate calibrated with native print, not font metrics.
                        return sum(max(1, math.ceil(2 * len(line) / width))
                                   for line in str(value).split('\n'))
                    count = lines(value, width)
                    if text_column > 1:
                        count = max(count, lines(ws.cell(row_index, 1).value or '', 28 * 0.8))
                    height = 16 * count + 8
                    if height > 409:
                        # Excel's row-height limit: retain auto-wrap and disclose unverified print fit.
                        unverified_annotation_rows.append({'sheet': name, 'row': row_index})
                        continue
                    if text_column < last_column:
                        ws.merge_cells(start_row=row_index, start_column=text_column,
                                       end_row=row_index, end_column=last_column)
                    ws.row_dimensions[row_index].height = height
            ws.freeze_panes = f'A{header_row + header_count}'
            ws.auto_filter.ref = f'A{header_row + header_count - 1}:{get_column_letter(len(body["columns"]))}{table_stop}'
            ws.print_title_rows = f'{header_row}:{header_row + header_count - 1}'
            ws.sheet_properties.pageSetUpPr.fitToPage = True
            ws.page_setup.orientation = 'landscape'
            ws.page_setup.paperSize = ws.PAPERSIZE_A4
            ws.page_setup.fitToWidth = 1
            ws.page_setup.fitToHeight = 0
            mappings.append({'node_ref': ref, 'sheet': name, 'header_row': header_row,
                             'header_rows': header_count, 'data_rows': len(body['rows']), 'columns': len(body['columns'])})
        if clarification:
            name = '资料澄清清单'
            if name.casefold() in names:
                raise ActionRejected('INVALID_OR_DUPLICATE_SHEET_NAME: ' + name)
            ws = workbook.create_sheet(name)
            rows = [['编号', '类型', '边坡或章节', '文件与页码', '问题与依据', '采用值', '待确认问题', '答复', '影响等级']]
            ordered = sorted(issue_records, key=lambda pair: 0 if pair[1].kind == 'no_evidence_assumption' else 1)
            for number, (ref, issue) in enumerate(ordered, 1):
                rows.append([number, LABELS[issue.kind], issue.object_label, issue.source_text(), issue.basis,
                             issue.adopted_value, issue.question, '', '是' if issue.affects_level else '否'])
                mappings.append({'node_ref': ref, 'sheet': name, 'kind': 'material-issue',
                                 'issue_id': issue.id, 'row_start': number + 1, 'row_stop': number + 2})
            if len(rows) > 1048576:
                raise ActionRejected('WORKBOOK_DIMENSIONS_UNSUPPORTED')
            for row_index, row in enumerate(rows, 1):
                for col_index, value in enumerate(row, 1):
                    cell = ws.cell(row_index, col_index, text(value))
                    cell.data_type = 's'
                    cell.alignment = Alignment(vertical='top', wrap_text=True)
                    if row_index == 1:
                        cell.font = Font(bold=True, color='FFFFFF')
                        cell.fill = PatternFill('solid', fgColor='244A63')
            for index in range(1, 10):
                ws.column_dimensions[get_column_letter(index)].width = 28
            ws.freeze_panes = 'A2'
            ws.auto_filter.ref = f'A1:I{len(rows)}'
            ws.print_title_rows = '1:1'
        buffer = BytesIO()
        workbook.save(buffer)
        data = buffer.getvalue()
        checksum = hashlib.sha256(data).hexdigest()
        asset = _asset(contents.store, checksum + '.xlsx', data)
        export_ref = contents._insert(db, actor, 'ExportArtifact', {
            'snapshot_ref': snapshot_ref, 'file_ref': asset, 'file_digest': checksum,
            'template_ref': 'frozen-tables-notes-xlsx-v2',
            'export_config': {'format': 'xlsx', 'sheets': sheets, 'report_expression_profile': expression, 'report_export_ref': report_export_ref,
                'material_issue_ids': [issue.id for _, issue in issue_records],
                'helper_digests': {name: hashlib.sha256(Path(__file__).with_name(name + '.py').read_bytes()).hexdigest()
                                   for name in ('g3_export', 'material_issues', 'commission_owner_records')},
                'exporter_digest': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'layout_engine_digest': hashlib.sha256(Path(presentation.__file__).read_bytes()).hexdigest(),
                **({'annotation_layout_unverified_rows': unverified_annotation_rows} if unverified_annotation_rows else {}),
                'limitation': 'Version link is provenance, not a claim of Word/Excel consistency or review.'
                    + (' Oversized annotations retain original wrapping; single-row print fit is unverified.' if unverified_annotation_rows else '')}})
        mapping_ref = contents._insert(db, actor, 'MappingArtifact', {'snapshot_ref': snapshot_ref,
            'export_ref': export_ref, 'anchor_records': mappings,
            'unrendered_dependency_nodes': [r for r in snapshot['payload']['refs'] if r['type'] == 'ContentNode' and r not in [m['node_ref'] for m in mappings]],
            'limitation': 'Only selected frozen tables and notes are exported; no report completeness or acceptance claim.'})
        return {'export_ref': export_ref, 'mapping_ref': mapping_ref, 'file_ref': asset, 'file_digest': checksum}
    request = {'workbook': snapshot_ref, 'sheets': sheets, 'report_export_ref': report_export_ref}
    if deliverable is not None:
        request['deliverable'] = deliverable
    return contents.operation(actor, operation_id, request, execute)


def read_workbook(data):
    workbook = load_workbook(BytesIO(data), read_only=True, data_only=False)
    try:
        sheets = [{'name': ws.title, 'rows': [list(row) for row in ws.iter_rows(values_only=True)]} for ws in workbook]
        return {'structure': {'format': 'xlsx', 'sheets': sheets},
                'text': '\n'.join(str(v) for s in sheets for row in s['rows'] for v in row if v is not None)}
    finally:
        workbook.close()
