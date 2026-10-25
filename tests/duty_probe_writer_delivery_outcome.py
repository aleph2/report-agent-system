"""Observe one owned Writer delivery task through the unchanged native runtime.

Typed originals and initial read choices are explicit fixtures. After those
reads the injected Writer chooses every action; this helper has no tool loop,
completion action, model client, retry or semantic acceptance rule.
"""
from contextlib import ExitStack
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
from report_agent.content_tasks import delegated_task
from report_agent.hierarchical_tools import actor_for
from report_agent.task_context import exact_task_context
from test_decision_data import activate


UNREVIEWED = 'Working draft; independent review and engineering acceptance remain outstanding.'
UNKNOWN = 'Actual weathering class is not established; no site score is selected.'
BODY_A = 'Revision A. ' + UNKNOWN
BODY_B = 'Revision B. ' + UNKNOWN
FOOTNOTE = 'Original footnote: confirm actual classification against the governing guideline.'
BOOK_NOTE = 'Workbook note: the unresolved issue requires independent source verification.'
REPORT_TABLE = {'columns': ['Indicator', 'Class', 'Score', 'Basis'],
    'rows': [['Synthetic condition', 'Not established', 'Not selected', 'Original condition unverified']]}
GOAL = ('Produce the current revision B synthetic working report and its separate issues workbook '
    'as an exact pair, and inspect the actual outputs. Revision A is retained historical material. '
    'Keep original technical uncertainty and unreviewed status; do not edit prose or claim '
    'engineering acceptance.')


def prepare_writer_delivery_fixture(ws):
    ws.store.set('manifest', {**ws.store.manifest, 'goal': GOAL, 'sources': [
        {'id': 's', 'title': 'Synthetic original condition', 'content': UNKNOWN, 'coverage': 'complete'}]})
    activate(ws)
    cs = ContentStore(ws.store)
    inputs = cs.import_inputs(actor_for('coordinator'), 'writer-delivery-inputs', ['s'])['result']
    commission = {'id': 'writer-delivery-owner', 'args': {'subagent_type': 'writer', 'description': GOAL}}

    def text(kind, body, qualifiers=None):
        return {'kind': kind, 'body': {'text': body}, 'qualifiers': qualifiers or {}, 'claim_kind': 'structure'}

    def issues(revision):
        return {'kind': 'table', 'body': {'columns': ['Revision', 'Object', 'Issue', 'Evidence status'],
            'rows': [[revision, 'Site S', 'Issue: actual weathering class remains unresolved.',
                      'Original source requires verification']]}, 'qualifiers': {}, 'claim_kind': 'structure'}

    with delegated_task(ws, 'coordinator', commission) as (_, writer):
        objects = [
            {'client_key': 'root', 'type': 'ContentNode', 'payload': text('report', 'Synthetic working report')},
            {'client_key': 'body', 'type': 'ContentNode', 'payload': text('block', BODY_A, {'status': UNREVIEWED})},
            {'client_key': 'table', 'type': 'ContentNode', 'payload': {
                'kind': 'table', 'body': deepcopy(REPORT_TABLE), 'qualifiers': {}, 'claim_kind': 'structure'}},
            {'client_key': 'footnote', 'type': 'ContentNode', 'payload': text('block', FOOTNOTE)},
            {'client_key': 'issues', 'type': 'ContentNode', 'payload': issues('A')},
            {'client_key': 'note', 'type': 'ContentNode', 'payload': text('block', BOOK_NOTE, {'status': UNREVIEWED})},
        ]
        for index, name in enumerate(['body', 'table', 'footnote']):
            objects.append({'client_key': name + '_edge', 'type': 'Relation', 'payload': {
                'subject_ref': {'client_key': 'root'}, 'object_ref': {'client_key': name},
                'predicate': 'contains', 'position': index, 'provenance_kind': 'adopted_during_generation'}})
        old = cs.commit(writer, 'writer-delivery-original-a', objects)['result']['refs']
        changed = cs.commit(writer, 'writer-delivery-original-b', [
            {'client_key': 'body', 'type': 'ContentNode', 'previous_ref': old['body'],
             'payload': text('block', BODY_B, {'status': UNREVIEWED})},
            {'client_key': 'issues', 'type': 'ContentNode', 'previous_ref': old['issues'], 'payload': issues('B')},
        ])['result']['refs']
        changed['body_edge'] = cs.commit(writer, 'writer-delivery-original-b-edge', [
            {'client_key': 'edge', 'type': 'Relation', 'previous_ref': old['body_edge'],
             'payload': {**cs.read(old['body_edge'])['payload'], 'object_ref': changed['body']}}
        ])['result']['refs']['edge']
        current = {**old, **changed}
        actor = deepcopy(writer.__dict__)
    task = {'id': 'writer-delivery-native', 'name': 'task', 'type': 'tool_call', 'args': {
        'subagent_type': 'writer', 'description': GOAL, 'resume_content_task_id': writer.task_id}}
    return {'case': 'writer-current-paired-delivery', 'goal': GOAL, 'inputs': inputs,
        'writer_actor': actor, 'task_call': task, 'bundles': {'historical': old, 'current': current},
        'originals': cs.list_objects(), 'limits': [
            'All original content is typed synthetic setup, not a real text-producer achievement.',
            'Current revision is independent of export time; internally coherent historical pairs are legal.',
            'Ordinary footnote placement does not repair the separate auxiliary-footnote defect.',
            'No visual typography, independent review or engineering acceptance.']}


class DeliveryParent(AgentMiddleware):
    def __init__(self, fixture, events):
        self.fixture, self.events, self.started = fixture, events, False

    async def awrap_model_call(self, request, handler):
        event = {'phase': 'explicit_fake_coordinator', 'messages': messages_to_dict(request.messages)}
        self.events.append(event)
        if not self.started:
            self.started = True
            response = AIMessage(content='', tool_calls=[deepcopy(self.fixture['task_call'])])
        else:
            returned = next(m for m in reversed(request.messages) if isinstance(m, ToolMessage)
                            and m.tool_call_id == self.fixture['task_call']['id'])
            event['actual_child_return'] = returned.model_dump()
            response = AIMessage(content='Synthetic Coordinator receipt control: actual child return retained; '
                                 'no independent review or engineering acceptance is inferred.')
        event['response'] = response.model_dump()
        return ModelResponse(result=[response])


class DeliveryOriginalReads(AgentMiddleware):
    def __init__(self, ws, fixture, events):
        self.ws, self.fixture, self.events, self.started = ws, fixture, events, False

    async def awrap_model_call(self, request, handler):
        event = {'phase': 'unchanged_writer_handler' if self.started else 'explicit_fake_original_reads',
            'server_context': deepcopy(exact_task_context(self.ws, 'writer')),
            'messages': messages_to_dict(request.messages)}
        self.events.append(event)
        if not self.started:
            self.started = True
            refs = [o['ref'] for o in self.fixture['originals'] if o['ref']['type'] != 'DelegatedTask']
            response = AIMessage(content='', tool_calls=[{'name': 'read_context', 'type': 'tool_call',
                'id': 'delivery-original-' + str(i), 'args': {'target_ref': ref}} for i, ref in enumerate(refs)])
            event['response'] = response.model_dump()
            return ModelResponse(result=[response])
        response = await handler(request)
        event['response'] = messages_to_dict(response.result)
        return response


async def capture_writer_delivery_outcome(ws, folder, model_factory, *, vision_client_factory=None):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    fixture = prepare_writer_delivery_fixture(ws)
    dump(folder / 'fixture.json', fixture)
    cs, calls, phases, parents, models = ContentStore(ws.store), [], [], [], {}
    parent, reads = DeliveryParent(fixture, parents), DeliveryOriginalReads(ws, fixture, phases)

    def factory(role):
        if role not in models:
            models[role] = traced_model(model_factory(role), role, calls)
        return models[role]

    original_builder = deep_runtime.create_deep_agent

    def build(*args, **kwargs):
        if kwargs.get('name') == 'report_coordinator':
            kwargs['middleware'] = [*kwargs.get('middleware', []), parent]
            kwargs['subagents'] = [{**a, 'middleware': [*a.get('middleware', []), reads]}
                                  if a['name'] == 'writer' else a for a in kwargs['subagents']]
        return original_builder(*args, **kwargs)

    runtime, error = None, None
    try:
        with ExitStack() as stack:
            stack.enter_context(patch.object(deep_runtime, 'create_deep_agent', build))
            if vision_client_factory is not None:
                stack.enter_context(patch.object(deep_models, 'configured_vision_client', vision_client_factory))
                stack.enter_context(patch.object(vision, 'configured_vision_client', vision_client_factory))
            runtime = await deep_runtime.run_report(ws, factory)
    except Exception as exc:
        error = {'type': type(exc).__name__, 'message': str(exc)}
    finally:
        raw = {'fixture': fixture, 'runtime': runtime, 'raised_error': error,
               'phase_events': phases, 'fake_parent_events': parents, 'native_model_calls': calls}
        dump(folder / 'raw-capture.json', raw)
        finals, errors, assets = [], [], []
        for index, event in enumerate(phases):
            if event['phase'] != 'unchanged_writer_handler' or 'response' not in event:
                continue
            response = event['response']
            if not isinstance(response, list) or any(not isinstance(m, dict) or
                    not isinstance(m.get('data'), dict) for m in response):
                errors.append({'code': 'WRITER_DELIVERY_RESPONSE_SHAPE', 'event': index})
                continue
            finals.extend(m['data']['content'] for m in response
                          if m.get('type') == 'ai' and not m['data'].get('tool_calls'))
        exports, renders = cs.list_objects('ExportArtifact'), cs.list_objects('RenderArtifact')
        wanted = [(o['payload']['file_ref'], o['payload']['file_digest']) for o in exports]
        for render in renders:
            wanted.append((render['payload']['pdf_ref'], render['payload']['pdf_digest']))
            wanted.extend((a['asset_ref'], a['sha256']) for a in render['payload']['page_assets'])
        (folder / 'assets').mkdir(exist_ok=True)
        for file_ref, expected in dict(wanted).items():
            try:
                data = (ws.store.root / file_ref).read_bytes()
                actual = hashlib.sha256(data).hexdigest()
                if actual != expected:
                    raise ValueError('WRITER_DELIVERY_ASSET_DIGEST_MISMATCH')
                retained = folder / 'assets' / Path(file_ref).name
                retained.write_bytes(data)
                assets.append({'file_ref': file_ref, 'retained_path': str(retained.relative_to(folder)), 'sha256': actual})
            except Exception as exc:
                errors.append({'code': 'WRITER_DELIVERY_ASSET_ERROR', 'file_ref': file_ref,
                               'type': type(exc).__name__, 'message': str(exc)})
        capture = {**raw, 'finals': finals, 'assets': assets, 'observer_errors': errors,
            'saved_snapshots': cs.list_objects('DocumentSnapshot'), 'saved_exports': exports,
            'saved_mappings': cs.list_objects('MappingArtifact'), 'saved_renders': renders,
            'saved_reviews': cs.list_objects('ReviewRecord'),
            'originals_unchanged': all(cs.read(o['ref']) == o for o in fixture['originals']),
            'host_completion_actions': False, 'semantic_status': 'not_semantically_assessed'}
        dump(folder / 'capture.json', capture)
        dump(folder / 'saved-state.json', {'objects': cs.list_objects(), 'events': ws.store.events()})
        if errors:
            raise RuntimeError('WRITER_DELIVERY_CAPTURE_ERROR: see raw-capture.json')
    return capture
