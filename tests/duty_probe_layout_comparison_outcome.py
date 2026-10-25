"""Fresh one-page comparison; four explicit fixture actions, then native Layout.

Preparation uses the original task grant, ToolNode, exporter and renderer. It
does not choose later Layout/vision actions or finish the comparison for it.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from langchain.agents.middleware.types import AgentMiddleware, ModelResponse
from langchain_core.messages import AIMessage, messages_to_dict
from docx import Document
import pypdfium2 as pdfium

from duty_probe_agent_decisions import dump, traced_model
from duty_probe_layout_outcome import FakeLayoutParent
from report_agent import deep_models, deep_runtime, vision
from report_agent.content_store import ContentStore
from report_agent.hierarchical_tools import actor_for
from report_agent.task_context import exact_task_context
from test_agent_duty_repro_artifacts import effective_properties
from test_agent_duty_trace_cases import action, result_value, tool_reply
from test_decision_data import activate


BODY = 'Comparison target: original conditions remain uncertain.'
FOOTNOTE = 'Original footnote: applicability remains conditional on actual classification.'
STANDARD = ('This synthetic local format requires the comparison target body paragraph to be 12 pt. '
            'Keep all original text, four table columns, footnote and technical conditions unchanged. '
            'Only that paragraph on the supplied physical page is in this comparison; other layout '
            'properties, TOC, content review and engineering acceptance are not established.')
LIMIT = 'One target paragraph on the paired physical pages only; no whole-report or engineering acceptance.'
GOAL = ('Compare the saved before and after presentation of the target paragraph against the saved '
        'local format. Inspect the actual files/pages using authorized capabilities and report the '
        'exact artifact and observation identities, extent and limitations to the Coordinator. '
        'The prepared files are test fixtures, not your export achievement. Do not revise them or '
        'the report content. ' + LIMIT)
QUESTION = 'Describe the comparison target paragraph on this supplied physical page only; retain unreadable and unseen-material limits.'


def prepare_layout_comparison_fixture(ws):
    sources = [{'id': 'rule', 'title': 'Original synthetic rule', 'content': 'Class B permits 75 to 100.', 'coverage': 'complete'},
               {'id': 'local-format', 'title': 'Local synthetic comparison format', 'content': STANDARD, 'coverage': 'complete'}]
    ws.store.set('manifest', {**ws.store.manifest, 'goal': GOAL, 'sources': sources})
    activate(ws)
    cs, owner = ContentStore(ws.store), actor_for('coordinator')
    inputs = cs.import_inputs(owner, 'comparison-inputs', ['rule', 'local-format'])['result']
    table = {'columns': ['Indicator', 'Class', 'Score', 'Note'],
             'rows': [['Synthetic item', 'B', '70', 'Independent review remains required']]}
    payloads = {'root': {'kind': 'report', 'body': {'text': 'Synthetic local comparison'}, 'qualifiers': {}, 'claim_kind': 'structure'},
                'claim': {'kind': 'claim', 'body': {'text': 'For adopted class B use 70.'}, 'qualifiers': {'condition': 'class B'}, 'claim_kind': 'inference'},
                'body': {'kind': 'block', 'body': {'text': BODY}, 'qualifiers': {}, 'claim_kind': 'structure'},
                'table': {'kind': 'table', 'body': table, 'qualifiers': {}, 'claim_kind': 'structure'},
                'footnote': {'kind': 'block', 'body': {'text': FOOTNOTE}, 'qualifiers': {}, 'claim_kind': 'structure'}}
    objects = [{'client_key': k, 'type': 'ContentNode', 'payload': p} for k, p in payloads.items()]
    for pos, key in enumerate(['claim', 'body', 'table', 'footnote']):
        objects.append({'client_key': key + '_edge', 'type': 'Relation', 'payload': {
            'subject_ref': {'client_key': 'root'}, 'object_ref': {'client_key': key},
            'predicate': 'contains', 'position': pos, 'provenance_kind': 'adopted_during_generation'}})
    objects.extend([
        {'client_key': 'evidence', 'type': 'Evidence', 'payload': {'source_refs': inputs['source_refs'][:1],
            'locator': 'original rule', 'excerpt': sources[0]['content']}},
        {'client_key': 'support', 'type': 'Relation', 'payload': {'subject_ref': {'client_key': 'claim'},
            'object_ref': {'client_key': 'evidence'}, 'predicate': 'supported_by', 'provenance_kind': 'adopted_during_generation'}}])
    refs = cs.commit(owner, 'comparison-content', objects)['result']['refs']
    snapshot = cs.freeze(owner, 'comparison-snapshot', refs['root'],
                         [inputs['requirement_ref'], *inputs['source_refs'], *refs.values()])['result']['snapshot_ref']
    task = {'name': 'task', 'id': 'comparison-fresh-task', 'type': 'tool_call', 'args': {
        'subagent_type': 'layout', 'description': GOAL + '\nLocal format reference: ' + json.dumps(inputs['source_refs'][1]),
        'layout_snapshot_ref': snapshot}}
    return {'case': 'layout-local-paired-page-comparison', 'goal': GOAL, 'task_call': task,
            'inputs': inputs, 'refs': refs, 'snapshot_ref': snapshot, 'expected_table': table,
            'originals': deepcopy(cs.list_objects()), 'limits': [LIMIT,
                'Fresh synthetic originals and four preparation actions are fixtures, not model achievements.',
                'This local font comparison does not replace the earlier full-format standard or its tests.',
                'The retained class B70 versus75-100 conflict is not corrected or accepted.']}


def measure_prepared_page(ws, export_ref, render_ref, expected_size):
    cs = ContentStore(ws.store)
    exported, rendered = cs.read(export_ref), cs.read(render_ref)
    word = ws.store.root / exported['payload']['file_ref']
    assert hashlib.sha256(word.read_bytes()).hexdigest() == exported['payload']['file_digest']
    doc = Document(word)
    paragraph, = [p for p in doc.paragraphs if p.text == BODY]
    sizes = [effective_properties(doc, paragraph, run)['size_pt'] for run in paragraph.runs if run.text]
    assert sizes and all(size == expected_size for size in sizes), 'PREPARED_BODY_SIZE_MISMATCH'
    pdf_path = ws.store.root / rendered['payload']['pdf_ref']
    assert hashlib.sha256(pdf_path.read_bytes()).hexdigest() == rendered['payload']['pdf_digest']
    with pdfium.PdfDocument(pdf_path) as pdf:
        assert len(pdf) == 1, 'PREPARED_COMPARISON_REQUIRES_EXACTLY_ONE_PAGE'
        page = pdf[0]
        text_page = page.get_textpage()
        text = text_page.get_text_range()
        text_page.close(); page.close()
    assert BODY in ' '.join(text.split()), 'PREPARED_TARGET_NOT_ON_FIXED_PAGE1'
    image, = rendered['payload']['page_assets']
    assert image['page'] == 1
    assert hashlib.sha256((ws.store.root / image['asset_ref']).read_bytes()).hexdigest() == image['sha256']
    return {'export_ref': export_ref, 'render_ref': render_ref, 'page': 1, 'image': image,
            'effective_body_sizes': sizes, 'pdf_text': text}


class PreparedComparison(AgentMiddleware):
    def __init__(self, ws, fixture, folder, phases):
        self.ws, self.fixture, self.folder, self.phases = ws, fixture, folder, phases
        self.step, self.receipts = 0, {}

    async def awrap_model_call(self, request, handler):
        event = {'phase': 'explicit_fake_pair_preparation' if self.step < 4 else 'unchanged_layout_handler',
                 'server_context': deepcopy(exact_task_context(self.ws, 'layout')),
                 'messages': messages_to_dict(request.messages)}
        self.phases.append(event)
        if self.step and self.step - 1 not in self.receipts:
            reply = tool_reply(request.messages, 'comparison-prepare-' + str(self.step - 1))
            self.receipts[self.step - 1] = result_value(reply)
            assert self.receipts[self.step - 1]['ok'] is True, 'PREPARATION_TOOL_REJECTED'
        if self.step < 4:
            if self.step in {0, 2}:
                answer = action('export_content_snapshot', 'comparison-prepare-' + str(self.step),
                    operation_id='comparison-' + ('old' if self.step == 0 else 'current') + '-export',
                    snapshot_ref=self.fixture['snapshot_ref'],
                    layout={'toc': False, 'page_numbers': False, 'font_size': 11 if self.step == 0 else 12})
            else:
                answer = action('render_content_export', 'comparison-prepare-' + str(self.step),
                    operation_id='comparison-' + ('old' if self.step == 1 else 'current') + '-render',
                    export_ref=self.receipts[self.step - 1]['result']['export_ref'])
            self.step += 1
            event['response'] = answer.model_dump()
            return ModelResponse(result=[answer])
        if 'prepared_pair' not in self.fixture:
            before = measure_prepared_page(self.ws, self.receipts[0]['result']['export_ref'],
                                          self.receipts[1]['result']['render_ref'], 11)
            after = measure_prepared_page(self.ws, self.receipts[2]['result']['export_ref'],
                                         self.receipts[3]['result']['render_ref'], 12)
            assert before['image']['sha256'] != after['image']['sha256'], 'PREPARED_PNGS_MUST_DIFFER'
            self.fixture['prepared_pair'] = {'before': before, 'after': after}
            dump(self.folder / 'fixture.json', self.fixture)
        response = await handler(request)
        event['response'] = messages_to_dict(response.result)
        return response


async def capture_layout_comparison(ws, folder, model_factory, *, vision_client_factory):
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    fixture = prepare_layout_comparison_fixture(ws); dump(folder / 'fixture.json', fixture)
    cs, calls, phases, parents, models, clients = ContentStore(ws.store), [], [], [], {}, []
    parent, prepare = FakeLayoutParent(fixture, parents), PreparedComparison(ws, fixture, folder, phases)
    def factory(role):
        if role not in models:
            models[role] = traced_model(model_factory(role), role, calls)
        return models[role]
    def visual_factory():
        client = vision_client_factory(); clients.append(client); return client
    original_builder = deep_runtime.create_deep_agent
    def build(*args, **kwargs):
        if kwargs.get('name') == 'report_coordinator':
            kwargs['middleware'] = [*kwargs.get('middleware', []), parent]
            kwargs['subagents'] = [{**a, 'middleware': [*a.get('middleware', []), prepare]}
                                  if a['name'] == 'layout' else a for a in kwargs['subagents']]
        return original_builder(*args, **kwargs)
    runtime, error = None, None
    try:
        with patch.object(deep_runtime, 'create_deep_agent', build), \
                patch.object(deep_models, 'configured_vision_client', visual_factory), \
                patch.object(vision, 'configured_vision_client', visual_factory):
            runtime = await deep_runtime.run_report(ws, factory)
    except Exception as exc:
        error = {'type': type(exc).__name__, 'message': str(exc)}
    finally:
        with ws.store.connect() as db:
            observations = [{'id': row[0], 'actor_id': row[1], 'data': row[2]} for row in db.execute(
                'SELECT id,actor_id,data FROM content_observations ORDER BY rowid')]
        raw = {'fixture': fixture, 'runtime': runtime, 'raised_error': error, 'phase_events': phases,
               'native_model_calls': calls, 'fake_parent_events': parents, 'objects': cs.list_objects(),
               'events': ws.store.events(), 'preparation_receipts': prepare.receipts,
               'native_observation_rows': observations}
        dump(folder / 'raw-capture.json', raw)
        capture = {**raw, 'host_completion_actions': False, 'assets': [], 'observer_errors': []}
        try:
            capture['originals_unchanged'] = all(cs.read(o['ref']) == o for o in fixture['originals'])
            exports, renders = cs.list_objects('ExportArtifact'), cs.list_objects('RenderArtifact')
            wanted = [(e['payload']['file_ref'], e['payload']['file_digest']) for e in exports]
            for r in renders:
                wanted.append((r['payload']['pdf_ref'], r['payload']['pdf_digest']))
                wanted.extend((p['asset_ref'], p['sha256']) for p in r['payload']['page_assets'])
            for filename, expected in dict(wanted).items():
                data = (ws.store.root / filename).read_bytes(); assert hashlib.sha256(data).hexdigest() == expected
                saved = folder / 'assets' / Path(filename).name; saved.parent.mkdir(exist_ok=True); saved.write_bytes(data)
                capture['assets'].append({'file_ref': filename, 'retained_path': str(saved.relative_to(folder)), 'sha256': expected})
            capture['vision_clients'] = [{'closed': getattr(c, 'closed', None)} for c in clients]
        except Exception as exc:
            capture['observer_errors'].append({'type': type(exc).__name__, 'message': str(exc)})
            dump(folder / 'capture.json', capture)
            raise
        dump(folder / 'capture.json', capture)
    return capture
