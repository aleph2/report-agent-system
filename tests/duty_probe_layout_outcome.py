"""Fresh native Layout task; only parent and original-read choices are fake.

Provider construction, budgets and responses belong to the caller. This helper
does not finish the document, select Layout actions, retry, or synthesize pages.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from langchain.agents.middleware.types import AgentMiddleware, ModelResponse
from langchain_core.messages import AIMessage, ToolMessage, messages_to_dict

from duty_probe_agent_decisions import dump, traced_model
from report_agent import deep_models, deep_runtime, vision
from report_agent.content_store import ContentStore
from report_agent.hierarchical_tools import actor_for
from report_agent.task_context import exact_task_context
from test_agent_duty_trace_cases import action
from test_decision_data import activate


FORMAT_STANDARD = (
    'Current synthetic format standard: top, bottom and left margins 25 mm; right margin 15 mm. '
    'Normal body font size 12 pt. Body, headings, TOC and table paragraphs use 1.5 line spacing. '
    'Chapter heading sizes at levels 1, 2 and 3 are 18, 15 and 14 pt. '
    'Preserve all four table columns, the complete ordinary footnote and every technical qualifier. '
    'Include one logical TOC covering the three chapter levels. '
    'No font family or table font size is prescribed. Formatting is not independent content review.'
)
GOAL = (
    'Present this immutable short synthetic report according to its saved current format standard. '
    'Inspect actual generated files and pages using authorized capabilities and return exact artifact '
    'references, the observed extent and unresolved limitations to the Coordinator. '
    'Do not change report content. Formatting is not content review or engineering acceptance.'
)
FOOTNOTE = 'Original footnote: applicability remains conditional on actual classification.'
BODY = 'The original field description and its uncertainty remain unchanged.'


def prepare_layout_outcome_fixture(ws):
    """One current snapshot, with seed's unchanged B=70 inference and support.

    Reuse seed's typed setup pattern without calling seed(), which would freeze
    an unnecessary earlier snapshot. These saved fixtures are not model output.
    """
    sources = [
        {'id': 's', 'title': 'Rule', 'content': 'Class B permits 75 to 100.', 'coverage': 'complete'},
        {'id': 'format-layout', 'title': 'Current synthetic format',
         'content': FORMAT_STANDARD, 'coverage': 'complete'},
    ]
    ws.store.set('manifest', {**ws.store.manifest, 'goal': GOAL, 'sources': sources})
    activate(ws)
    cs, owner = ContentStore(ws.store), actor_for('coordinator')
    inputs = cs.import_inputs(owner, 'layout-outcome-inputs', ['s', 'format-layout'])['result']
    objects = [
        {'client_key': 'k', 'type': 'Criterion', 'payload': {
            'requirement_refs': [inputs['requirement_ref']], 'purpose': 'Faithful compilation',
            'scope': 'whole report', 'expected_outcome': 'Adopted class and value agree.',
            'evidence_expectation': 'Compare adopted conditions to original rule.',
            'allowed_limits': 'Unresolved actual class may be conditional.'}},
        {'client_key': 'root', 'type': 'ContentNode', 'payload': {
            'kind': 'report', 'body': {'text': 'Report'}, 'qualifiers': {}, 'claim_kind': 'structure'}},
        {'client_key': 'claim', 'type': 'ContentNode', 'payload': {
            'kind': 'claim', 'body': {'text': 'For adopted class B use 70.'},
            'qualifiers': {'condition': 'class B'}, 'claim_kind': 'inference'}},
        {'client_key': 'edge', 'type': 'Relation', 'payload': {
            'subject_ref': {'client_key': 'root'}, 'object_ref': {'client_key': 'claim'},
            'predicate': 'contains', 'position': 0, 'provenance_kind': 'adopted_during_generation'}},
        {'client_key': 'evidence', 'type': 'Evidence', 'payload': {
            'source_refs': inputs['source_refs'][:1], 'locator': 's', 'excerpt': 'Class B permits 75 to 100.'}},
        {'client_key': 'support', 'type': 'Relation', 'payload': {
            'subject_ref': {'client_key': 'claim'}, 'object_ref': {'client_key': 'evidence'},
            'predicate': 'supported_by', 'provenance_kind': 'adopted_during_generation'}},
    ]
    headings = {'1 Field description': 1, '1.1 Recorded conditions': 2, '1.1.1 Original details': 3}

    def add(key, kind, body, parent, position):
        objects.extend([
            {'client_key': key, 'type': 'ContentNode', 'payload': {
                'kind': kind, 'body': body, 'qualifiers': {}, 'claim_kind': 'structure'}},
            {'client_key': key + '_edge', 'type': 'Relation', 'payload': {
                'subject_ref': {'client_key': parent}, 'object_ref': {'client_key': key},
                'predicate': 'contains', 'position': position,
                'provenance_kind': 'adopted_during_generation'}},
        ])

    for key, text, parent, position in [
            ('h1', '1 Field description', 'root', 1),
            ('h2', '1.1 Recorded conditions', 'h1', 0),
            ('h3', '1.1.1 Original details', 'h2', 0)]:
        add(key, 'chapter', {'text': text}, parent, position)
    add('body', 'block', {'text': BODY}, 'h3', 0)
    table = {'columns': ['Indicator', 'Class', 'Score', 'Note'],
             'rows': [['Synthetic item', 'B', '70', 'Requires independent rule comparison']]}
    add('table', 'table', table, 'h3', 1)
    add('footnote', 'block', {'text': FOOTNOTE}, 'h3', 2)
    refs = cs.commit(owner, 'layout-outcome-content', objects)['result']['refs']
    snapshot = cs.freeze(owner, 'layout-outcome-snapshot', refs['root'],
        [inputs['requirement_ref'], *inputs['source_refs'], *refs.values()])['result']['snapshot_ref']
    task = {'id': 'layout-outcome-task', 'name': 'task', 'type': 'tool_call', 'args': {
        'subagent_type': 'layout', 'description': GOAL + '\nCurrent format reference: ' +
            json.dumps(inputs['source_refs'][1]), 'layout_snapshot_ref': snapshot}}
    return {'case': 'fresh-layout-current-document-outcome', 'goal': GOAL,
        'snapshot_ref': snapshot, 'format_ref': inputs['source_refs'][1], 'inputs': inputs,
        'refs': refs, 'task_call': task, 'expected_headings': headings,
        'expected_body_lines': ['For adopted class B use 70.', BODY, FOOTNOTE],
        'expected_table': table, 'originals': cs.list_objects(),
        'limits': ['Synthetic typed originals, not a real producer achievement.',
            'The retained B=70 versus75-100 conflict is not repaired by formatting.',
            'An ordinary visible footnote does not fix the separate body.footnote omission.',
            'No prescribed font family, whole-document visual or engineering acceptance.']}


class FakeLayoutParent(AgentMiddleware):
    def __init__(self, fixture, events):
        self.fixture, self.events, self.started = fixture, events, False

    async def awrap_model_call(self, request, handler):
        event = {'phase': 'explicit_fake_coordinator', 'messages': messages_to_dict(request.messages)}
        self.events.append(event)
        if not self.started:
            self.started = True
            answer = AIMessage(content='', tool_calls=[deepcopy(self.fixture['task_call'])])
        else:
            message = next(m for m in reversed(request.messages) if isinstance(m, ToolMessage)
                           and m.tool_call_id == self.fixture['task_call']['id'])
            event['actual_child_return'] = message.model_dump()
            answer = AIMessage(content='Synthetic Coordinator receipt control: child return recorded; '
                               'no independent content review or engineering acceptance is inferred.')
        event['response'] = answer.model_dump()
        return ModelResponse(result=[answer])


class PreparedLayoutReads(AgentMiddleware):
    def __init__(self, ws, fixture, events):
        self.ws, self.fixture, self.events, self.started = ws, fixture, events, False

    async def awrap_model_call(self, request, handler):
        event = {'phase': 'unchanged_layout_handler' if self.started else 'explicit_fake_original_reads',
                 'server_context': deepcopy(exact_task_context(self.ws, 'layout')),
                 'messages': messages_to_dict(request.messages)}
        self.events.append(event)
        if not self.started:
            self.started = True
            answer = AIMessage(content='', tool_calls=[
                {'name': 'read_context', 'id': 'layout-prepare-' + str(i), 'type': 'tool_call',
                 'args': {'target_ref': ref}} for i, ref in enumerate([
                     self.fixture['format_ref'], self.fixture['snapshot_ref']])])
            event['response'] = answer.model_dump()
            return ModelResponse(result=[answer])
        response = await handler(request)
        event['response'] = messages_to_dict(response.result)
        return response


async def capture_layout_outcome(ws, folder, model_factory, *, vision_client_factory):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    fixture = prepare_layout_outcome_fixture(ws)
    dump(folder / 'fixture.json', fixture)
    cs, calls, phases, parent_events, models, vision_clients = ContentStore(ws.store), [], [], [], {}, []
    parent, prepared = FakeLayoutParent(fixture, parent_events), PreparedLayoutReads(ws, fixture, phases)

    def factory(role):
        if role not in models:
            models[role] = traced_model(model_factory(role), role, calls)
        return models[role]

    def selected_vision_client():
        client = vision_client_factory()
        vision_clients.append(client)
        return client

    original_builder = deep_runtime.create_deep_agent

    def build(*args, **kwargs):
        if kwargs.get('name') == 'report_coordinator':
            kwargs['middleware'] = [*kwargs.get('middleware', []), parent]
            kwargs['subagents'] = [{**a, 'middleware': [*a.get('middleware', []), prepared]}
                                  if a['name'] == 'layout' else a for a in kwargs['subagents']]
        return original_builder(*args, **kwargs)

    runtime, error = None, None
    try:
        with patch.object(deep_runtime, 'create_deep_agent', build), \
                patch.object(deep_models, 'configured_vision_client', selected_vision_client), \
                patch.object(vision, 'configured_vision_client', selected_vision_client):
            runtime = await deep_runtime.run_report(ws, factory)
    except Exception as exc:
        error = {'type': type(exc).__name__, 'message': str(exc)}
    finally:
        raw = {'fixture': fixture, 'runtime': runtime, 'raised_error': error,
               'phase_events': phases, 'fake_parent_events': parent_events, 'native_model_calls': calls}
        dump(folder / 'raw-capture.json', raw)
        finals, observer_errors, assets = [], [], []
        for index, event in enumerate(phases):
            if event['phase'] != 'unchanged_layout_handler' or 'response' not in event:
                continue
            response = event['response']
            if not isinstance(response, list) or any(not isinstance(m, dict) or
                    not isinstance(m.get('data'), dict) for m in response):
                observer_errors.append({'code': 'LAYOUT_OBSERVER_RESPONSE_SHAPE', 'event': index})
                continue
            finals.extend(m['data']['content'] for m in response
                          if m.get('type') == 'ai' and not m['data'].get('tool_calls'))
        exports, renders = cs.list_objects('ExportArtifact'), cs.list_objects('RenderArtifact')
        wanted = [(r['payload']['file_ref'], r['payload']['file_digest']) for r in exports]
        for r in renders:
            wanted.append((r['payload']['pdf_ref'], r['payload']['pdf_digest']))
            wanted.extend((a['asset_ref'], a['sha256']) for a in r['payload']['page_assets'])
        (folder / 'assets').mkdir(exist_ok=True)
        for source, expected in dict(wanted).items():
            try:
                data = (ws.store.root / source).read_bytes()
                actual = hashlib.sha256(data).hexdigest()
                if actual != expected:
                    raise ValueError('LAYOUT_CAPTURE_ASSET_DIGEST_MISMATCH')
                saved = folder / 'assets' / Path(source).name
                saved.write_bytes(data)
                assets.append({'file_ref': source, 'retained_path': str(saved.relative_to(folder)), 'sha256': actual})
            except Exception as exc:
                observer_errors.append({'code': 'LAYOUT_CAPTURE_ASSET_ERROR', 'file_ref': source,
                                        'type': type(exc).__name__, 'message': str(exc)})
        capture = {**raw, 'finals': finals, 'saved_tasks': cs.list_objects('DelegatedTask'),
            'saved_exports': exports, 'saved_renders': renders, 'saved_reviews': cs.list_objects('ReviewRecord'),
            'originals_unchanged': all(cs.read(o['ref']) == o for o in fixture['originals']),
            'observer_errors': observer_errors, 'assets': assets,
            'vision_clients': [{'type': type(c).__name__, 'closed': getattr(c, 'closed', None)}
                               for c in vision_clients],
            'host_completion_actions': False, 'semantic_status': 'not_semantically_assessed'}
        dump(folder / 'capture.json', capture)
        dump(folder / 'saved-state.json', {'objects': cs.list_objects(), 'events': ws.store.events()})
        if observer_errors:
            raise RuntimeError('LAYOUT_CAPTURE_OBSERVER_ERROR: see raw-capture.json')
    return capture
