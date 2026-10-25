"""Synthetic Office boundary checks only, not a report-generation run."""
from io import BytesIO

import pytest
from docx import Document
from openpyxl import load_workbook

from report_agent.content_export import export_snapshot
from report_agent.content_workbook import export_workbook
from report_agent.content_store import Actor
from report_agent.errors import ActionForbidden
from report_agent.workspace import Workspace
from test_deliverable_declaration_v4 import case, work
from test_deliverable_recovery_v4 import declaration, resolve


def test_explicit_word_and_excel_exports_resolve_the_same_declared_snapshot(case):
    cs, co, writer, _, source = case
    objects = work(source)
    sheet = next(o for o in objects if o['client_key'] == 'sheet')
    sheet['payload'].update(kind='table', body={'columns': ['Item', 'Value'], 'rows': [['A', 1]]})
    refs = cs.commit(writer, 'output', objects, deliverable_selection={'kind': 'saved_work',
        'root_ref': {'client_key': 'a'}, 'include_current_save': True, 'members_from': [],
        'workbook_refs': [{'client_key': 'sheet'}]})['result']['refs']
    selected = {'kind': 'deliverable', 'operation_id': 'output'}
    word = export_snapshot(cs, writer, 'word', None, deliverable=selected)['result']
    excel = export_workbook(cs, writer, 'excel', None,
        [{'name': 'Data', 'table_ref': refs['sheet'], 'note_refs': []}],
        report_export_ref=word['export_ref'], deliverable=selected)['result']
    assert cs.read(word['export_ref'])['payload']['snapshot_ref'] == cs.read(excel['export_ref'])['payload']['snapshot_ref']
    assert len(cs.list_objects('DocumentSnapshot')) == 1
    text = '\n'.join(p.text for p in Document(cs.store.root/word['file_ref']).paragraphs)
    assert 'a-body' in text and 'b-body' not in text
    workbook = load_workbook(BytesIO((cs.store.root/excel['file_ref']).read_bytes()), read_only=True)
    assert ('A', '1') in list(workbook['Data'].values)
    workbook.close()


def test_coordinator_uses_writer_owned_selected_snapshot_without_cloning(case):
    cs, co, writer, _, _ = case
    declaration(case)
    saved = resolve(cs, writer, 'writer-binds', {'kind': 'deliverable', 'operation_id': 'published'})
    assert cs.read(saved)['owner_id'] == writer.id
    export = export_snapshot(cs, co, 'co-export', saved)['result']
    assert cs.read(export['export_ref'])['payload']['snapshot_ref'] == saved
    assert cs.read(saved)['owner_id'] == writer.id and len(cs.list_objects('DocumentSnapshot')) == 1


def test_writer_foreign_root_selection_does_not_grant_export_rights(case):
    cs, co, writer, _, _ = case
    result = declaration(case)
    task = cs.operation(co, 'other-writer', {}, lambda db: {'ref': cs._insert(db, co, 'DelegatedTask',
        {'role': 'writer', 'goal': 'Select readable existing work.', 'delegated_by': co.id})})['result']['ref']
    other = Actor('content:writer:'+task['id'], 'writer', task['id'])
    cs.commit(other, 'foreign-output', [], deliverable_selection={'kind': 'saved_work',
        'root_ref': result['refs']['a'], 'members_from': [{'kind': 'deliverable', 'operation_id': 'published'}]})
    with pytest.raises(ActionForbidden):
        export_snapshot(cs, other, 'denied-export', None,
                        deliverable={'kind': 'deliverable', 'operation_id': 'foreign-output'})
    assert cs.list_objects('DocumentSnapshot') == []


def test_guarded_adoption_exposes_optional_selection_only_in_v4(case):
    from langchain_core.tools import StructuredTool
    from report_agent.hierarchical_tools import content_tools
    from report_agent.text_work import guarded_tools
    from test_bounded_review import Model
    cs = case[0]
    workspace = Workspace(cs.store)
    functions = guarded_tools(workspace, 'writer', Model('unused'), content_tools(workspace, 'writer'))
    for name in ['commit_objects', 'save_text_node']:
        function = next(t for t in functions if getattr(t, 'name', getattr(t, '__name__', None)) == name)
        tool = function if isinstance(function, StructuredTool) else StructuredTool.from_function(function)
        assert 'deliverable_selection' in tool.tool_call_schema.model_json_schema()['properties']


async def test_native_guarded_writer_really_forwards_selection_to_saved_receipt(case):
    from report_agent.content_tasks import delegated_task
    from test_native_write_identity import native_tools, dispatch, heading
    cs = case[0]
    workspace = Workspace(cs.store)
    call = {'name':'task', 'id':'writer-native', 'args':{'subagent_type':'writer','description':'Save selected fixture heading.'}}
    with delegated_task(workspace, 'coordinator', call) as (_, actor):
        function = native_tools(workspace, 'writer')['commit_objects']
        result = await dispatch(function, 'declared-heading', {**heading(), 'deliverable_selection': {
            'kind':'saved_work', 'root_ref':{'client_key':'heading'}, 'include_current_save':True, 'members_from':[]}})
        assert result['ok'] and result['receipt_id'].startswith('native:')
        saved = cs.receipt(actor, result['receipt_id'])['response']['result']
        assert saved['deliverable']['root_ref'] == saved['refs']['heading']
        assert saved['deliverable']['producer_actor_id'] == actor.id
        assert cs.list_objects('DocumentSnapshot') == []


@pytest.mark.parametrize('role,name', [('coordinator','commit_objects'),('writer','commit_objects'),('writer','save_text_node')])
def test_final_native_save_description_keeps_v4_declaration_contract(case, role, name):
    from report_agent.prompt_sources import load_prompt
    from test_native_write_identity import native_tools
    tool = native_tools(Workspace(case[0].store), role)[name]
    description = getattr(tool,'description',None) or tool.__doc__
    assert load_prompt('deliverable-save-tool-v4').strip() in description

