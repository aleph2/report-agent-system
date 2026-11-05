"""Nested layout defaults through the native Layout tool and actual DOCX.

The revision limit belongs only to each temporary fixture. No renderer, vision,
independent model, application repair or original report is involved.
"""
from copy import deepcopy
import hashlib
import json
from zipfile import ZipFile

from docx import Document
from docx.oxml.ns import qn
from langchain_core.messages import AIMessage
import pytest

from duty_probe_agent_decisions import dump
from report_agent.content_layout import LayoutOptions
from report_agent.layout_revision import status
from report_agent.task_context import exact_task_context
from test_agent_duty_trace_cases import action
from test_agent_result_delivery import run_role
from test_bounded_review import Model
from test_decision_data import activate
from test_duty_contract_default_siblings import evidence_folder, finish_capture, retain, schema_errors
from test_hierarchical_content import seed
from test_task_supervision import ws, offline


@pytest.mark.parametrize('variant', ['explicit-null', 'omit-default-null', 'changed-lines'])
async def test_native_layout_nested_default_equivalence_and_change_guard(ws, tmp_path, request, variant):
    cs, _, refs, snapshot, _ = seed(ws)
    activate(ws)
    ws.store.set('layout_revision_limit', 0)
    originals = deepcopy(cs.list_objects())
    claim = cs.read(refs['claim'])['payload']['body']['text']
    baseline = {'toc': False, 'nodes': [{'node_ref': refs['claim'], 'paragraphs': [
        {'text': claim, 'space_after_lines': 0.5, 'space_after_pt': None}]}]}
    selected = deepcopy(baseline)
    paragraph = selected['nodes'][0]['paragraphs'][0]
    if variant == 'omit-default-null':
        del paragraph['space_after_pt']
    elif variant == 'changed-lines':
        paragraph['space_after_lines'] = 0.75
    first_args = {'operation_id': 'layout-baseline', 'snapshot_ref': snapshot, 'layout': baseline}
    second_args = {'operation_id': 'layout-second', 'snapshot_ref': snapshot, 'layout': selected}
    folder = evidence_folder(tmp_path, request)
    capture = {'variant': variant, 'baseline_arguments': first_args, 'second_arguments': second_args}
    unused = Model(AssertionError('Layout default probe must not call independent text work.'))
    driver = None

    def after_baseline(messages):
        value = retain(folder, capture, messages, 'layout-baseline')
        capture.setdefault('server_contexts', []).append(exact_task_context(ws, 'layout'))
        capture['baseline_result'] = deepcopy(value)
        capture['baseline_records'] = deepcopy(cs.list_objects())
        capture['baseline_assets'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                      for p in (ws.store.root / 'content-assets').iterdir() if p.is_file()}
        dump(folder / 'baseline-state.json', capture)
        return action('export_content_snapshot', 'layout-second', **second_args)

    def finish(messages):
        retain(folder, capture, messages, 'layout-second')
        capture.setdefault('server_contexts', []).append(exact_task_context(ws, 'layout'))
        return AIMessage(content='Synthetic layout contract observation only; no visual or engineering acceptance.')

    try:
        driver = await run_role(ws, 'layout', [
            action('export_content_snapshot', 'layout-baseline', **first_args), after_baseline, finish],
            refs, snapshot, unused)
        tool_schema = next(t['parameters'] for t in driver.bindings['layout'][-1]
                           if t['name'] == 'export_content_snapshot')
        capture.update(actual_export_schema=tool_schema,
            first_schema_errors=schema_errors(tool_schema, first_args),
            second_schema_errors=schema_errors(tool_schema, second_args),
            normalized_first=LayoutOptions.model_validate(baseline).model_dump(),
            normalized_second=LayoutOptions.model_validate(selected).model_dump())
        with ws.store.connect() as db:
            capture['revision_status'] = status(db)
        capture['assets_after'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                   for p in (ws.store.root / 'content-assets').iterdir() if p.is_file()}
        capture['word_observations'] = []
        for record in cs.list_objects('ExportArtifact'):
            if not record['payload']['file_ref'].endswith('.docx'):
                continue
            path = ws.store.root / record['payload']['file_ref']
            data = path.read_bytes()
            with ZipFile(path) as archive:
                xml = archive.read('word/document.xml').decode('utf-8')
            dump(folder / ('word-' + record['ref']['id'] + '.json'),
                 {'file_ref': record['payload']['file_ref'], 'sha256': hashlib.sha256(data).hexdigest(), 'document_xml': xml})
            doc = Document(path)
            selected_paragraphs = [p for p in doc.paragraphs if p.text == claim]
            spacing = [p._p.pPr.find(qn('w:spacing')) if p._p.pPr is not None else None
                       for p in selected_paragraphs]
            capture['word_observations'].append({'ref': record['ref'],
                'sha256': hashlib.sha256(data).hexdigest(), 'paragraph_texts': [p.text for p in doc.paragraphs],
                'exact_claim_count': len(selected_paragraphs),
                'spacing': [dict(s.attrib) if s is not None else None for s in spacing]})
    except Exception as exc:
        capture['execution_error'] = {'type': type(exc).__name__, 'message': str(exc)}
        raise
    finally:
        capture['independent_calls'] = unused.calls
        finish_capture(folder, capture, driver, cs, originals, ws)

    assert capture['originals_unchanged'] and not unused.calls
    assert capture['first_schema_errors'] == capture['second_schema_errors'] == []
    assert capture['baseline_result']['ok'] is True
    assert all(cs.read(o['ref']) == o for o in capture['baseline_records'])
    task, = cs.list_objects('DelegatedTask')
    assert task['payload']['role'] == 'layout' and task['payload']['layout_snapshot_ref'] == snapshot
    assert task['owner_id'] == task['payload']['delegated_by'] == 'content:coordinator'
    assert task['payload']['write_scope'] == 'Only artifacts produced by this task; read other project artifacts.'
    assert len(capture['server_contexts']) == 2
    for context in capture['server_contexts']:
        assert context['role'] == 'layout' and context['actor_id'] == 'content:layout:' + task['ref']['id']
        assert context['assignment'] == task['payload']
    exports, mappings = cs.list_objects('ExportArtifact'), cs.list_objects('MappingArtifact')
    expected_count = 2 if variant == 'changed-lines' else 4
    assert len(exports) == len(mappings) == expected_count
    for call_id in ['layout-baseline', *(['layout-second'] if variant != 'changed-lines' else [])]:
        observed = capture['observed'][call_id]
        assert observed['message']['status'] == 'success' and observed['value']['ok'] is True
        public = observed['value']['result']
        exported = cs.read(public['export_ref'])
        companion=cs.read(public['workbook']['export_ref'])
        assert companion['payload']['snapshot_ref']==exported['payload']['snapshot_ref']
        assert companion['payload']['export_config']['report_export_ref']==exported['ref']
        mapping = cs.read(public['mapping_ref'])
        assert exported['ref'] in [o['ref'] for o in exports] and mapping['ref'] in [o['ref'] for o in mappings]
        assert mapping['payload']['export_ref'] == exported['ref']
        assert public['file_digest'] == exported['payload']['file_digest']
    for exported in exports:
        assert exported['owner_id'] == exported['created_by'] == 'content:layout:' + task['ref']['id']
        assert exported['task_id'] == task['ref']['id'] and exported['payload']['snapshot_ref'] == snapshot
        if exported['payload']['file_ref'].endswith('.docx'):
            assert exported['payload']['export_config']['layout'] == capture['normalized_first']
        else:
            parent=cs.read(exported['payload']['export_config']['report_export_ref'])
            assert parent['payload']['snapshot_ref']==snapshot
            assert parent['payload']['export_config']['layout']==capture['normalized_first']
        mapping, = [m for m in mappings if m['payload']['export_ref'] == exported['ref']]
        assert mapping['owner_id'] == exported['owner_id'] and mapping['task_id'] == task['ref']['id']
        assert mapping['payload']['snapshot_ref'] == snapshot
    for observed in capture['word_observations']:
        assert observed['sha256'] == cs.read(observed['ref'])['payload']['file_digest']
        assert observed['exact_claim_count'] == 1
        spacing, = observed['spacing']
        assert spacing[qn('w:afterLines')] == '50'
        assert spacing.get(qn('w:after')) in (None, '0')
        assert any(p != claim and 'condition' in p and 'class B' in p for p in observed['paragraph_texts'])
    assert capture['revision_status']['revisions_used'] == 0
    if variant == 'changed-lines':
        assert capture['normalized_first'] != capture['normalized_second']
        message = capture['observed']['layout-second']['message']
        assert message['status'] == 'error'
        assert 'LAYOUT_REVISION_LIMIT_REACHED' in json.dumps(message, ensure_ascii=False)
        assert capture['assets_after'] == capture['baseline_assets']
    else:
        assert capture['normalized_first'] == capture['normalized_second']
        assert capture['observed']['layout-second']['value']['ok'] is True

