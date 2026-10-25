"""Serialize agent-owned frozen tables with provenance; never author their contents."""
import hashlib
import json
import re
from io import BytesIO
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from pydantic import BaseModel, ConfigDict, Field

from .content_models import Ref
from .content_export import _asset
from .errors import ActionForbidden, ActionRejected
from . import content_layout as presentation


class WorkbookSheet(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=31)
    table_ref: Ref
    note_refs: list[Ref] = Field(default_factory=list,
        description='Optional frozen text ContentNodes to copy verbatim after this table, including correction notices and their qualifiers. Choose applicable notes; this tool never authors them.')


def export_workbook(contents, actor, operation_id, snapshot_ref, sheets, report_export_ref=None, *, deliverable=None):
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
        members = {Ref.model_validate(r).key() for r in snapshot['payload']['refs']}
        if not sheets:
            raise ActionRejected('WORKBOOK_SHEETS_REQUIRED')
        channel = snapshot['payload'].get('workbook_refs')
        if channel:
            declared = {Ref.model_validate(r).key() for r in channel}
            selected = {Ref.model_validate(r).key() for sheet in sheets
                        for r in [sheet['table_ref'],*sheet.get('note_refs',[])]}
            if selected != declared:
                raise ActionRejected('WORKBOOK_CHANNEL_SELECTION_MISMATCH')
        if report_export_ref:
            linked = contents._read(db, report_export_ref)
            if report_export_ref['type'] != 'ExportArtifact' or not linked['payload']['file_ref'].endswith('.docx'):
                raise ActionRejected('WORD_EXPORT_REQUIRED')
            if linked['payload']['snapshot_ref'] != snapshot_ref:
                raise ActionRejected('WORD_WORKBOOK_SNAPSHOT_MISMATCH')
        names = set()
        workbook, mappings = Workbook(), []
        workbook.remove(workbook.active)
        def text(value):
            value = str(value) if value is not None else ''
            if len(value) > 32767 or re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', value):
                raise ActionRejected('WORKBOOK_CELL_TEXT_UNSUPPORTED')
            return value
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
            rows = [[str(k), text(v) if not isinstance(v, (dict, list)) else json.dumps(v, ensure_ascii=False)]
                    for k, v in node.get('qualifiers', {}).items()]
            header_row = len(rows) + 1
            rows += [body['columns'], *body['rows']]
            table_stop = len(rows)
            footnote = presentation.table_footnote(body)
            if footnote is not None:
                start = len(rows) + 1
                rows.append([footnote])
                mappings.append({'node_ref': ref, 'sheet': name, 'kind': 'table-footnote',
                                 'row_start': start, 'row_stop': len(rows) + 1})
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
                rows += [[str(k), text(v) if not isinstance(v, (dict, list)) else json.dumps(v, ensure_ascii=False)]
                         for k, v in note.get('qualifiers', {}).items()]
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
                    if row_index == header_row:
                        cell.font = Font(bold=True, color='FFFFFF')
                        cell.fill = PatternFill('solid', fgColor='244A63')
            for index in range(1, max(map(len, rows)) + 1):
                ws.column_dimensions[get_column_letter(index)].width = 28
            ws.freeze_panes = f'A{header_row + 1}'
            ws.auto_filter.ref = f'A{header_row}:{get_column_letter(len(body["columns"]))}{table_stop}'
            ws.print_title_rows = f'{header_row}:{header_row}'
            ws.sheet_properties.pageSetUpPr.fitToPage = True
            ws.page_setup.orientation = 'landscape'
            ws.page_setup.paperSize = ws.PAPERSIZE_A4
            ws.page_setup.fitToWidth = 1
            ws.page_setup.fitToHeight = 0
            mappings.append({'node_ref': ref, 'sheet': name, 'header_row': header_row,
                             'data_rows': len(body['rows']), 'columns': len(body['columns'])})
        buffer = BytesIO()
        workbook.save(buffer)
        data = buffer.getvalue()
        checksum = hashlib.sha256(data).hexdigest()
        asset = _asset(contents.store, checksum + '.xlsx', data)
        export_ref = contents._insert(db, actor, 'ExportArtifact', {
            'snapshot_ref': snapshot_ref, 'file_ref': asset, 'file_digest': checksum,
            'template_ref': 'frozen-tables-notes-xlsx-v2',
            'export_config': {'format': 'xlsx', 'sheets': sheets, 'report_expression_profile': expression, 'report_export_ref': report_export_ref,
                'exporter_digest': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'layout_engine_digest': hashlib.sha256(Path(presentation.__file__).read_bytes()).hexdigest(),
                'limitation': 'Version link is provenance, not a claim of Word/Excel consistency or review.'}})
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
