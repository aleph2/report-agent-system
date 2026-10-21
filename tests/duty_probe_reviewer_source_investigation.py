"""Fresh source-version investigation through the unchanged Reviewer runtime.

Only the typed originals and parent delegation are fixtures. The Reviewer and
independent checker use injected services, without prepared investigation,
semantic repair, a replacement tool loop or a host-authored final.
"""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import messages_to_dict

from duty_probe_agent_decisions import dump, traced_model
from duty_probe_writer_delivery_outcome import DeliveryParent
from report_agent import deep_runtime
from report_agent.catalog import Catalog
from report_agent.content_store import ContentStore
from report_agent.evidence_analysis import model_identity
from report_agent.hierarchical_tools import actor_for
from report_agent.task_context import exact_task_context
from report_agent.task_supervision import reconcile
from report_agent.store import digest
from test_decision_data import activate


OLD_RULE = 'Historical synthetic rule v1: class B permits 70 to 100.'
CURRENT_RULE = 'Current synthetic rule v2: class B permits 75 to 100.'
CLAIM = 'For the synthetically adopted class B, use 70.'
LIMIT = 'Synthetic adopted class only; actual site classification and engineering acceptance are not established.'
GOAL = ('Investigate the existing synthetic claim against the current authorized rule. '
        'Retain exact original source versions and disclose selected-material limits. '
        'The author snapshot is historical and immutable. Do not revise report content '
        'or claim whole-report or engineering acceptance.')


def prepare_reviewer_source_fixture(ws):
    old = {'id': 's', 'title': 'Historical synthetic rule v1', 'content': OLD_RULE,
           'coverage': 'complete', 'current': True}
    ws.store.set('manifest', {**ws.store.manifest, 'goal': GOAL, 'sources': [old]})
    activate(ws)
    cs, owner = ContentStore(ws.store), actor_for('coordinator')
    inputs = cs.import_inputs(owner, 'source-investigation-originals', ['s'])['result']
    objects = [
        {'client_key': 'root', 'type': 'ContentNode', 'payload': {
            'kind': 'report', 'body': {'text': 'Synthetic historical report'},
            'qualifiers': {}, 'claim_kind': 'structure'}},
        {'client_key': 'claim', 'type': 'ContentNode', 'payload': {
            'kind': 'claim', 'body': {'text': CLAIM}, 'qualifiers': {'status': LIMIT},
            'claim_kind': 'inference'}},
        {'client_key': 'criterion', 'type': 'Criterion', 'payload': {
            'requirement_refs': [inputs['requirement_ref']], 'purpose': 'Faithful current-source comparison',
            'scope': 'One synthetic adopted-class claim',
            'expected_outcome': 'Compare the adopted value with the eligible current rule.',
            'evidence_expectation': 'Actual claim and exact selected original source version.',
            'allowed_limits': LIMIT}},
        {'client_key': 'edge', 'type': 'Relation', 'payload': {
            'subject_ref': {'client_key': 'root'}, 'object_ref': {'client_key': 'claim'},
            'predicate': 'contains', 'position': 0, 'provenance_kind': 'adopted_during_generation'}},
    ]
    refs = cs.commit(owner, 'source-investigation-author-content', objects)['result']['refs']
    members = [inputs['requirement_ref'], *inputs['source_refs'], *refs.values()]
    snapshot = cs.freeze(owner, 'source-investigation-author-snapshot', refs['root'], members)['result']['snapshot_ref']
    old_source_object, old_snapshot_object = cs.read(inputs['source_refs'][0]), cs.read(snapshot)
    with ws.store.connect() as db:
        old_block_rows = [list(r) for r in db.execute(
            "SELECT source_id,ordinal,locator,text FROM source_blocks WHERE source_id='s' ORDER BY ordinal")]
    current = {**old, 'title': 'Current synthetic rule v2', 'content': CURRENT_RULE}
    ws.store.set('manifest', {**ws.store.manifest, 'sources': [current]})
    # Explicit synthetic catalog transition, not a public same-ID version-import claim.
    current_block_rows = [['s', 0, 'current synthetic rule v2; block 0', CURRENT_RULE]]
    with ws.store.connect() as db:
        db.execute("DELETE FROM source_blocks WHERE source_id='s'")
        db.executemany('INSERT INTO source_blocks VALUES (?,?,?,?)', current_block_rows)
    catalog = Catalog(ws.store)
    current_page = catalog.read('s', 0, 1)
    assert current_page['source'] == {k: v for k, v in catalog.sources()[0].items() if k != 'content'}
    assert current_page['source']['title'] == current['title']
    assert current_page['blocks'] == [{'ordinal': 0, 'locator': current_block_rows[0][2], 'text': CURRENT_RULE}]
    assert cs.read(inputs['source_refs'][0]) == old_source_object and cs.read(snapshot) == old_snapshot_object
    eligible = cs.capture_sources(owner, 'source-investigation-eligible-current', ['s'])['result']['source_refs'][0]
    assert cs.read(eligible)['payload'] == ContentStore.source_payload(catalog.sources()[0])
    task_call = {'name': 'task', 'id': 'source-investigation-task', 'type': 'tool_call', 'args': {
        'subagent_type': 'reviewer', 'description': GOAL, 'review_snapshot_ref': snapshot,
        'review_requirements': [{
            'scope_id': 'current-rule-comparison', 'target_ref': refs['claim'],
            'criterion_ref': refs['criterion'],
            'required_checks': ['Compare the adopted value against the current authorized source rule.'],
            'required_read_refs': [], 'required_materials': [{
                'requirement_index': 0, 'purpose': 'Exact claim being compared', 'refs': [refs['claim']]}],
            'material_refs': [eligible],
            'source_ranges': [{'source_ref': eligible, 'offset': 0, 'limit': 1}],
        }]}}
    return {'case': 'reviewer-current-source-investigation', 'goal': GOAL,
            'inputs': inputs, 'refs': refs, 'snapshot_ref': snapshot,
            'eligible_current_source_ref': eligible, 'task_call': task_call,
            'old_source_payload': cs.read(inputs['source_refs'][0])['payload'],
            'current_source_payload': cs.read(eligible)['payload'],
            'catalog_transition': {'old_block_rows': old_block_rows, 'current_block_rows': current_block_rows,
                                   'current_source_page': current_page, 'current_page_digest': digest(current_page)},
            'originals': deepcopy(cs.list_objects()),
            'limits': ['Typed originals and Coordinator eligible-source binding are explicit fixtures.',
                       'Current source is eligible additional material, not automatically required whole-body input.',
                       'Capturing a source does not establish selection into the independent checker.',
                       'Same-ID catalog replacement is explicit host fixture setup, not an application import capability.',
                       'Fake checker calibration is not a real engineering verdict.']}


class CaptureChecker:
    def __init__(self, service, calls):
        self.service, self.calls = service, calls

    def __getattr__(self, name):
        return getattr(self.service, name)

    async def ainvoke(self, messages):
        record = {'input': deepcopy(messages), 'model_identity': model_identity(self.service)}
        self.calls.append(record)
        try:
            result = await self.service.ainvoke(messages)
        except Exception as exc:
            record['error'] = {'type': type(exc).__name__, 'message': str(exc)}
            raise
        record['raw_response'] = result.model_dump()
        return result


class InvestigationObserver(AgentMiddleware):
    def __init__(self, ws, phases):
        self.ws, self.phases = ws, phases

    async def awrap_model_call(self, request, handler):
        event = {'phase': 'unchanged_reviewer_handler',
                 'server_context': deepcopy(exact_task_context(self.ws, 'reviewer')),
                 'messages': messages_to_dict(request.messages)}
        self.phases.append(event)
        result = await handler(request)
        event['response'] = messages_to_dict(result.result)
        return result


async def capture_reviewer_source_investigation(ws, folder, model_factory):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    fixture = prepare_reviewer_source_fixture(ws)
    dump(folder / 'fixture.json', fixture)
    cs, calls, checker_calls, phases, parents, models = ContentStore(ws.store), [], [], [], [], {}
    parent = DeliveryParent(fixture, parents)
    observer = InvestigationObserver(ws, phases)

    def factory(role):
        if role not in models:
            service = model_factory(role)
            models[role] = (CaptureChecker(service, checker_calls) if role == 'text_tool'
                            else traced_model(service, role, calls))
        return models[role]

    original_builder = deep_runtime.create_deep_agent

    def build(*args, **kwargs):
        if kwargs.get('name') == 'report_coordinator':
            kwargs['middleware'] = [*kwargs.get('middleware', []), parent]
            kwargs['subagents'] = [{**a, 'middleware': [*a.get('middleware', []), observer]}
                                  if a['name'] == 'reviewer' else a for a in kwargs['subagents']]
        return original_builder(*args, **kwargs)

    runtime, error = None, None
    try:
        with patch.object(deep_runtime, 'create_deep_agent', build):
            runtime = await deep_runtime.run_report(ws, factory)
    except Exception as exc:
        error = {'type': type(exc).__name__, 'message': str(exc)}
    finally:
        objects = cs.list_objects()
        raw = {'fixture': fixture, 'runtime': runtime, 'raised_error': error,
               'phase_events': phases, 'native_model_calls': calls, 'checker_calls': checker_calls,
               'fake_parent_events': parents, 'objects': objects, 'events': ws.store.events()}
        dump(folder / 'raw-capture.json', raw)
        with ws.store.connect() as db:
            receipts = [{'id': r[0], 'actor_id': r[1], 'data': json.loads(r[2])}
                        for r in db.execute('SELECT id,actor_id,data FROM content_observations')]
        raw['receipts'] = receipts
        dump(folder / 'raw-capture.json', raw)
        dump(folder / 'saved-state.json', {'objects': objects, 'events': raw['events'], 'receipts': receipts})
        captured = [r for r in objects if r['ref']['type'] == 'SourceArtifact'
                    and r['owner_id'].startswith('content:reviewer:')]
        capture = {'fixture': fixture, 'runtime': runtime, 'raised_error': error,
                   'phase_events': phases, 'native_model_calls': calls, 'checker_calls': checker_calls,
                   'fake_parent_events': parents, 'reviewer_captured_sources': captured,
                   'saved_reviews': [r for r in objects if r['ref']['type'] == 'ReviewRecord'],
                   'host_completion_actions': False}
        try:
            capture['task_status'] = [reconcile(cs, t['ref']['id']) for t in objects if t['ref']['type'] == 'DelegatedTask']
            capture['originals_unchanged'] = all(cs.read(r['ref']) == r for r in fixture['originals'])
        except Exception as exc:
            capture['observer_errors'] = [{'type': type(exc).__name__, 'message': str(exc)}]
            dump(folder / 'observer-errors.json', capture['observer_errors'])
            dump(folder / 'capture.json', capture)
            raise
        dump(folder / 'capture.json', capture)
    return capture
