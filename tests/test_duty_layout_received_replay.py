"""Execute recorded R3 Layout actions through native tools, without new models.

Synthetic fixture identities are rebound; all received layout numbers/text and
operation IDs remain unchanged. Rendering is a scripted test observation, not a
claim that the historical live model chose another action. No application repair.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from docx.text.run import Run
from jsonschema import Draft202012Validator
from langchain_core.messages import AIMessage, messages_to_dict
import pytest

from duty_probe_visual_packets import LAYOUT_STANDARD, capture_layout
from report_agent.content_store import ContentStore
from report_agent.deep_runtime import run_report
from test_agent_duty_repro_artifacts import effective_properties, save_evidence, toc_fields
from test_agent_duty_trace_cases import action, result_value, tool_reply
from test_deep_runtime import Driver, call
from test_task_supervision import ws, offline


ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT / '.analysis/agent-duty-validation-20261018/completion-execution-20261019/real/live-r3'
PINNED = {
    'layout-standard': {
        'model-output.json': 'ab9c1ea70f59a8a996bf9c7a7d09e3c7db88fa87dce13fa9cc034fd4c25ecfdc',
        'native-capture.json': '8e9138b945a3c2aeea19d97605f34dc972aabcb67f9d16409d6886af691cb240',
        'wire-requests.json': '1be4d5721ab400d4ce2628d07a2df7048ed5f1ee873713a3025c14fa0b2307cb',
        'wire-responses.json': '4b6873e203b6462d648101c3f9fa009c312f084726c0066cab4840fa06493dd3',
        'result.json': 'd2efbdd6e37530fdc005c401567443389e160e6df1d56938ee1d07329e026f5a'},
    'layout-old-reference': {
        'model-output.json': '6faefd9d8b67be59c58b79918e147b7b18e00ea430eedd91944643fc6bf66fd8',
        'native-capture.json': '11ec4cd41a0ed137e74e16dccd6eb1ebb4a994cd8ca63454559842e3d7e1eb1b',
        'wire-requests.json': '8ad3063a24000d2166b7ccb17fb440ba3cf237747cdde8bf934effe3674c67da',
        'wire-responses.json': 'c243c29c5d3a3cf6fc5a8ec72533024596c1cbae1c83916dc5e9b91de680a3c1',
        'result.json': 'cc1c257040c66a0609f377d736ea8cca46e45fcfad9bf99744b03d0e1314e3fc'},
}


def read_objects(capture):
    objects = {}
    for message in capture['messages']:
        if message['type'] == 'tool' and message['data'].get('name') == 'read_context':
            value = json.loads(message['data']['content'])
            value = value.get('metadata', value)
            for obj in value.get('result', {}).get('objects', []):
                if obj['ref']['type'] == 'ContentNode':
                    objects[obj['ref']['id']] = obj
    return objects


def rebind_refs(value, identities, changes, path='$'):
    if isinstance(value, dict):
        if set(value) == {'type', 'id', 'version'} and value['id'] in identities:
            replacement = identities[value['id']]
            assert value['type'] == replacement['type'] and value['version'] == replacement['version']
            changes.append({'path': path, 'before': value, 'after': replacement})
            return deepcopy(replacement)
        return {k: rebind_refs(v, identities, changes, path + '.' + k) for k, v in value.items()}
    if isinstance(value, list):
        return [rebind_refs(v, identities, changes, f'{path}[{i}]') for i, v in enumerate(value)]
    return value


def inspect_word(doc, nodes, layout):
    """Independent numeric rules come from LAYOUT_STANDARD, not export config."""
    expected_headings, body_lines = {}, []
    controls = {n['node_ref']['id']: n for n in layout['nodes']}
    for ident, obj in nodes.items():
        payload = obj['payload']
        if 'text' not in payload['body']:
            continue
        lines = payload['body']['text'].splitlines()
        control = controls.get(ident, {})
        first = lines[0]
        selected = next((p for p in control.get('paragraphs', []) if p['text'] == first), {})
        level = selected.get('heading_level') or control.get('heading_level')
        if level:
            expected_headings[first] = {'level': level, 'size_pt': {1: 18, 2: 15, 3: 14}[level]}
            body_lines.extend(lines[1:])
        elif payload['kind'] == 'block':
            body_lines.extend(lines)
    observations, violations, found = [], [], set()
    for element in doc.element.body.iter(qn('w:p')):
        paragraph = Paragraph(element, doc._body)
        text = ''.join(t.text or '' for t in element.iter(qn('w:t')))
        if not text:
            continue
        style = paragraph.style.name
        is_toc = bool(re.match(r'^(TOC|Contents)( |[0-9])', style)) or text == '目录'
        is_table = any(a.tag == qn('w:tc') for a in element.iterancestors())
        if is_table:
            kind, expected_size = 'table', None
        elif is_toc:
            kind, expected_size = 'toc', None
        elif text in expected_headings:
            kind, expected_size = 'heading', expected_headings[text]['size_pt']
        elif text in body_lines:
            kind, expected_size = 'body', 12
        else:
            kind, expected_size = 'other', None
        if kind != 'other':
            found.add((kind, text))
            for run_element in element.iter(qn('w:r')):
                if not any(t.text for t in run_element.iter(qn('w:t'))):
                    continue
                props = effective_properties(doc, paragraph, Run(run_element, paragraph))
                observations.append({'text': text, 'kind': kind, 'style': style, 'effective': props,
                                     'selected_heading': expected_headings.get(text) if kind == 'heading' else None})
                if props['line_multiple'] != 1.5:
                    violations.append({'text': text, 'kind': kind, 'property': 'line_multiple', 'expected': 1.5, 'actual': props['line_multiple']})
                if expected_size is not None and props['size_pt'] != expected_size:
                    violations.append({'text': text, 'kind': kind, 'property': 'size_pt', 'expected': expected_size, 'actual': props['size_pt']})
    for text in expected_headings:
        if ('heading', text) not in found:
            violations.append({'kind': 'heading', 'text': text, 'property': 'actual_content', 'actual': 'missing'})
    for text in body_lines:
        if ('body', text) not in found:
            violations.append({'kind': 'body', 'text': text, 'property': 'actual_content', 'actual': 'missing'})
    for index, section in enumerate(doc.sections):
        for side, expected in {'top': 25, 'bottom': 25, 'left': 25, 'right': 15}.items():
            actual = getattr(section, side + '_margin').mm
            if abs(actual - expected) >= .05:
                violations.append({'kind': 'page', 'section': index, 'property': side + '_mm', 'expected': expected, 'actual': actual})
    return observations, violations, expected_headings, body_lines


@pytest.mark.parametrize('case', ['layout-standard', 'layout-old-reference'])
async def test_received_layout_action_reaches_actual_word_without_parameter_repair(ws, request, case):
    folder = Path(os.environ.get('REPORT_ARTIFACT_REPRO_OUT', str(ws.store.root / 'repro'))) / request.node.name
    folder.mkdir(parents=True, exist_ok=True)
    originals = {}
    for name, checksum in PINNED[case].items():
        raw = (ORIGINAL / case / name).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == checksum, (case, name, 'Pinned evidence changed')
        (folder / ('original-' + name)).write_bytes(raw)
        originals[name] = json.loads(raw)
    old_capture, raw_message = originals['native-capture.json'], originals['model-output.json']
    assert originals['result.json']['generated_actions_executed'] is False
    assert len(raw_message['tool_calls']) == 1 and not raw_message['invalid_tool_calls']
    original_call, = raw_message['tool_calls']
    assert original_call['name'] == 'export_content_snapshot'
    old_schema = next(t['function']['parameters'] for t in old_capture['tools'] if t['function']['name'] == original_call['name'])
    Draft202012Validator(old_schema).validate(original_call['args'])
    await capture_layout(ws, case, folder / 'fresh-input')
    current = json.loads((folder / 'fresh-input/native-capture.json').read_text())
    assert current['observations']['standard_original']['payload'] == old_capture['observations']['standard_original']['payload']
    assert current['observations']['standard_original']['payload']['body']['text'] == LAYOUT_STANDARD
    old_nodes, fresh_nodes = read_objects(old_capture), read_objects(current)
    identities = {old_capture['observations']['snapshot_ref']['id']: current['observations']['snapshot_ref']}
    for ident, old in old_nodes.items():
        match = [new for new in fresh_nodes.values() if new['payload'] == old['payload']]
        assert len(match) == 1, ('Fixture payload match is not unique', old, match)
        identities[ident] = match[0]['ref']
    changes = []
    replay = rebind_refs(original_call, identities, changes)
    reverse = {r['id']: old_nodes[old]['ref'] if old in old_nodes else old_capture['observations']['snapshot_ref']
               for old, r in identities.items()}
    assert rebind_refs(replay, reverse, []) == original_call
    cs = ContentStore(ws.store)
    snapshot = current['observations']['snapshot_ref']
    members = cs.read(snapshot)['payload']['refs']
    before = [cs.read(ref) for ref in [snapshot, *members]]
    rendered_nodes = {r['id']: cs.read(r) for r in members if r['type'] == 'ContentNode'}
    observed = {'case': case, 'original_source_hashes': PINNED[case], 'original_received_message': raw_message,
        'recorded_action_executed_now_not_original_run': replay, 'identity_map': identities, 'identity_rebindings': changes,
        'standard': LAYOUT_STANDARD, 'assets': [], 'render_decision': 'Scripted observer after the recorded export; not a live-model action.',
        'cover_exception': 'Synthetic cover project is absent; no single-spacing exception claimed.', 'paid_calls': 0}

    def render(messages):
        public = result_value(tool_reply(messages, replay['id']))
        observed['export_return'] = public
        if not public.get('ok'):
            return AIMessage(content=json.dumps(public))
        observed['export'] = public['result']
        observed['export_record'] = cs.read(public['result']['export_ref'])
        observed['assets'].append({'file_ref': public['result']['file_ref'], 'kind': 'docx'})
        return action('render_content_export', 'received-render', operation_id='received-render', export_ref=public['result']['export_ref'])

    def finish(messages):
        public = result_value(tool_reply(messages, 'received-render'))
        observed['render_return'] = public
        if public.get('ok') and public['result']['execution_state'] == 'completed':
            payload = cs.read(public['result']['render_ref'])['payload']
            observed['render'] = payload
            observed['assets'].append({'file_ref': payload['pdf_ref'], 'kind': 'pdf'})
            observed['assets'].extend({'file_ref': p['asset_ref'], 'kind': 'png', 'page': p['page']} for p in payload['page_assets'])
        return AIMessage(content='Recorded export and test render observed; no visual or engineering acceptance.')

    def parent(messages):
        observed['parent_tool_message'] = tool_reply(messages, 'received-layout-task').model_dump()
        return AIMessage(content='Recorded Layout result received. Independent artifact assertions remain.')

    def prior_capture_step(messages):
        raise AssertionError('Historical capture steps must not execute again')

    # Driver indexes actual AI messages, including the two retained Co capture
    # responses. Continue that native history without clearing its checkpoint.
    def resumed_start(messages):
        observed['pre_replay_coordinator_messages'] = messages_to_dict(messages)
        observed['pre_replay_coordinator_ai_count'] = sum(isinstance(m, AIMessage) for m in messages)
        assert observed['pre_replay_coordinator_ai_count'] == 2, 'Native capture history must remain intact'
        return AIMessage(content='', tool_calls=[call('task', {
            'subagent_type': 'layout', 'layout_snapshot_ref': snapshot,
            'description': 'Execute the recorded export for the current governing synthetic format standard.'}, 'received-layout-task')])

    driver = Driver(coordinator=[prior_capture_step, prior_capture_step, resumed_start, parent],
        layout=[AIMessage(content=raw_message['content'], tool_calls=[replay]), render, finish])
    try:
        observed['runtime_result'] = await run_report(ws, driver)
        assert observed['runtime_result']['last_error'] is None, observed
        observed['final_schema'] = next(s['parameters'] for s in driver.bindings['layout'][0] if s['name'] == replay['name'])
        Draft202012Validator(observed['final_schema']).validate(replay['args'])
        if case == 'layout-old-reference':
            # Approved R8 oracle correction; the recorded illegal root heading
            # remains unchanged and must not yield a pretend successful export.
            assert observed['export_return']['ok'] is False and observed['export_return']['accepted'] is False
            assert observed['export_return']['code'] == 'LAYOUT_HEADING_REQUIRES_TEXT_BLOCK'
            assert 'LAYOUT_HEADING_REQUIRES_TEXT_BLOCK' in str(observed['export_return'])
            assert 'LAYOUT_HEADING_REQUIRES_TEXT_BLOCK' in str(observed['parent_tool_message']['content'])
            assert not cs.list_objects('ExportArtifact') and not cs.list_objects('RenderArtifact')
            assert not observed['assets'] and 'render_return' not in observed
            assert before == [cs.read(ref) for ref in [snapshot, *members]]
            assert not cs.list_objects('ReviewRecord')
            observed['test_disposition'] = 'Exact rejection of historical illegal action; no Word/PDF or model repair claimed.'
            return
        assert observed['export_return'].get('ok'), observed['export_return']
        assert observed.get('render', {}).get('page_assets'), observed.get('render_return')
        assert before == [cs.read(ref) for ref in [snapshot, *members]]
        assert not cs.list_objects('ReviewRecord'), 'First artifact must be measured before any review.'
        doc = Document(ws.store.root / observed['export']['file_ref'])
        props, violations, headings, body_lines = inspect_word(doc, rendered_nodes, replay['args']['layout'])
        observed.update(effective_properties=props, violations=violations, expected_headings=headings,
            body_lines=body_lines, toc_count=len(toc_fields(doc)),
            actual_matrices=[[[cell.text for cell in row.cells] for row in table.rows] for table in doc.tables])
        expected_matrix = [['Indicator', 'Class', 'Score', 'Note'], ['Synthetic item', 'B', '75', 'Conditional']]
        assert observed['actual_matrices'] == [expected_matrix]
        assert observed['toc_count'] == 1
        text = '\n'.join(''.join(t.text or '' for t in p.iter(qn('w:t'))) for p in doc.element.body.iter(qn('w:p')))
        for obj in rendered_nodes.values():
            for line in obj['payload']['body'].get('text', '').splitlines():
                assert line in text, ('Original body missing from DOCX', line)
        import pypdfium2 as pdfium
        with pdfium.PdfDocument(ws.store.root / observed['render']['pdf_ref']) as pdf:
            pages = []
            for page in pdf:
                reader = page.get_textpage()
                pages.append(reader.get_text_range())
                reader.close()
                page.close()
        observed['pdf_page_text'] = pages
        normalized = ' '.join('\n'.join(pages).split())
        for obj in rendered_nodes.values():
            for line in obj['payload']['body'].get('text', '').splitlines():
                assert ' '.join(line.split()) in normalized, ('Original ASCII body missing from PDF', line)
        for asset in observed['assets']:
            raw = (ws.store.root / asset['file_ref']).read_bytes()
            asset['sha256'] = hashlib.sha256(raw).hexdigest()
        font = subprocess.run(['fc-match', '宋体'], capture_output=True, text=True, check=False)
        observed['font_environment'] = {'query': '宋体', 'returncode': font.returncode, 'actual_match': font.stdout.strip(),
            'limitation': 'Font-family was not specified by the synthetic standard; missing Song font does not prove Chinese visual compliance.'}
        observed['unobserved_heading_levels'] = sorted({1, 2, 3} - {h['level'] for h in headings.values()})
        assert not violations, ('P11_ACTUAL_WORD_STANDARD_MISMATCH', violations)
    finally:
        save_evidence(request, ws, observed, driver)


async def test_independent_legal_text_heading_reaches_actual_word(ws, request):
    """Independent valid Layout action; not a retargeted historical response."""
    from test_decision_data import activate
    from test_hierarchical_content import seed

    activate(ws)
    cs, owner, refs, _, members = seed(ws)
    additions = cs.commit(owner, 'legal-heading-fixture', [
        {'client_key': 'heading', 'type': 'ContentNode', 'payload': {'kind': 'block',
            'body': {'text': 'Independent synthetic heading'}, 'qualifiers': {}, 'claim_kind': 'structure'}},
        {'client_key': 'heading_edge', 'type': 'Relation', 'payload': {'subject_ref': refs['root'],
            'object_ref': {'client_key': 'heading'}, 'predicate': 'contains', 'position': 1,
            'provenance_kind': 'adopted_during_generation'}}])['result']['refs']
    snapshot = cs.freeze(owner, 'legal-heading-snapshot', refs['root'],
        [*members, *additions.values()])['result']['snapshot_ref']
    before = [cs.read(ref) for ref in [snapshot, *members, *additions.values()]]
    layout = {'toc': True, 'nodes': [{'node_ref': additions['heading'], 'heading_level': 1}]}
    observed = {'control_kind': 'Independent legal text-block heading, no original-response rewriting', 'assets': []}

    def finish(messages):
        public = result_value(tool_reply(messages, 'legal-heading-export'))
        observed['export_return'] = public
        assert public.get('ok'), public
        observed['export'] = public['result']
        observed['assets'].append({'file_ref': public['result']['file_ref'], 'kind': 'docx'})
        return AIMessage(content=json.dumps(public))

    def parent(messages):
        public = result_value(tool_reply(messages, 'legal-heading-task'))
        assert public['result']['export_ref'] == observed['export']['export_ref']
        observed['parent_received'] = True
        return AIMessage(content='Actual export received; no visual or engineering approval.')

    driver = Driver(coordinator=[AIMessage(content='', tool_calls=[call('task', {
        'subagent_type': 'layout', 'description': 'Export this synthetic snapshot with its explicit text-block heading.',
        'layout_snapshot_ref': snapshot}, 'legal-heading-task')]), parent],
        layout=[action('export_content_snapshot', 'legal-heading-export', operation_id='legal-heading-export',
            snapshot_ref=snapshot, layout=layout), finish])
    try:
        result = await run_report(ws, driver)
        observed['runtime_result'] = result
        assert result['last_error'] is None, result
        assert observed['parent_received'] and len(cs.list_objects('ExportArtifact')) == 1
        schema = next(t['parameters'] for t in driver.bindings['layout'][0] if t['name'] == 'export_content_snapshot')
        Draft202012Validator(schema).validate({'operation_id': 'legal-heading-export', 'snapshot_ref': snapshot, 'layout': layout})
        saved = cs.read(observed['export']['export_ref'])
        data = (ws.store.root / saved['payload']['file_ref']).read_bytes()
        assert hashlib.sha256(data).hexdigest() == saved['payload']['file_digest']
        doc = Document(ws.store.root / saved['payload']['file_ref'])
        matching = [p for p in doc.paragraphs if p.text == 'Independent synthetic heading']
        observed['heading_paragraph_styles'] = [p.style.name for p in matching]
        assert len([p for p in matching if p.style.name == 'Heading 1']) == 1
        assert len(toc_fields(doc)) == 1
        text = '\n'.join(p.text for p in doc.paragraphs)
        for original in before:
            if original['ref']['type'] == 'ContentNode':
                assert original['payload']['body']['text'] in text
        assert before == [cs.read(ref) for ref in [snapshot, *members, *additions.values()]]
        assert not cs.list_objects('ReviewRecord') and not cs.list_objects('RenderArtifact')
    finally:
        save_evidence(request, ws, observed, driver)
