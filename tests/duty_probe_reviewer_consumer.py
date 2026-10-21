"""Recorded R1 checker preparation, then the original native Reviewer handler.

Only fixture action selection/checker response and the parent are fake. The
actual ToolNode, bounded parser, receipts and saved task accounting are used.
Later Reviewer/text calls use the injected factory, without a second loop.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from unittest.mock import patch

from langchain.agents.middleware.types import AgentMiddleware, ModelResponse
from langchain_core.messages import AIMessage, ToolMessage, messages_to_dict

from duty_probe_agent_decisions import dump, traced_model
from report_agent import deep_runtime
from report_agent.content_store import ContentStore
from report_agent.evidence_analysis import model_identity
from report_agent.task_supervision import reconcile
from test_agent_duty_trace_cases import action, result_value, tool_reply
from test_bounded_review import Model, review_call
from test_decision_data import activate
from test_deep_runtime import Driver
from test_hierarchical_content import seed


ARCHIVE = Path(__file__).resolve().parents[1] / '.analysis/agent-duty-validation-20261018/completion-execution-20261019/real/live-r1'
FALSE_FINAL = 'Both assigned comparisons are satisfied and the whole report is accepted.'


def _replace_known_ids(value, mapping, changes, path=()):
    if isinstance(value, dict):
        return {k: _replace_known_ids(v, mapping, changes, (*path, k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_replace_known_ids(v, mapping, changes, (*path, i)) for i, v in enumerate(value)]
    if not isinstance(value, str):
        return value
    result = value
    for old, new in mapping.items():
        for before, after in ((old, new), (old[:8], new[:8])):
            pattern = r'(?<![0-9a-f-])' + re.escape(before) + r'(?![0-9a-f-])'
            changed, count = re.subn(pattern, lambda match: after, result)
            if count:
                changes.append({'path': list(path), 'old': before, 'new': after, 'occurrences': count})
                result = changed
    return result


def prepare_reviewer_fixture(ws, case):
    family = 'full' if case == 'full' else 'missing'
    folder = ARCHIVE / ('check-' + family)
    files = [folder / n for n in ('model-output.json', 'independent-input.json', 'result.json')]
    old_response, old_messages, old_result = [json.loads(p.read_text('utf-8')) for p in files]
    packet = json.loads(old_messages[-1][1])
    raw = json.loads(old_response['content'])
    sources = [entry['object']['payload'] for entry in packet['evidence'][:4]
               if entry['object']['ref']['type'] == 'SourceArtifact']
    manifest_sources = [{'id': p['source_id'], 'title': p['source_metadata']['title'],
                         'content': p['content'], 'coverage': p['coverage']} for p in sources]
    ws.store.set('manifest', {**ws.store.manifest, 'goal': packet['commission']['goal'], 'sources': manifest_sources})
    cs, owner, refs, _, members = seed(ws)
    second = cs.import_inputs(owner, 'recorded-c-input', ['c'])['result']
    extra = cs.commit(owner, 'recorded-second-scope', [
        {'client_key': 'claim2', 'type': 'ContentNode', 'payload': packet['evidence'][1]['object']['payload']},
        {'client_key': 'k2', 'type': 'Criterion', 'payload': {
            **packet['criteria'][1]['payload'], 'requirement_refs': cs.read(refs['k'])['payload']['requirement_refs']}},
        {'client_key': 'edge2', 'type': 'Relation', 'payload': {'subject_ref': refs['root'],
            'object_ref': {'client_key': 'claim2'}, 'predicate': 'contains', 'position': 1,
            'provenance_kind': 'adopted_during_generation'}}])['result']['refs']
    refs.update(extra)
    all_refs = {json.dumps(r, sort_keys=True): r for r in [*members, second['requirement_ref'], *second['source_refs'], *extra.values()]}
    snapshot = cs.freeze(owner, 'recorded-two-scope-snapshot', refs['root'], list(all_refs.values()))['result']['snapshot_ref']
    first_source = next(r for r in members if r['type'] == 'SourceArtifact')
    evidence_refs = [refs['claim'], refs['claim2'], first_source, second['source_refs'][0]]
    mapping = {packet['evidence'][i]['object']['ref']['id']: ref['id'] for i, ref in enumerate(evidence_refs)}
    mapping.update({packet['criteria'][i]['ref']['id']: refs[key]['id'] for i, key in enumerate(('k', 'k2'))})
    context = packet['evidence'][4]['structure']
    mapping.update({context['root_ref']['id']: refs['root']['id'], context['snapshot_ref']['id']: snapshot['id']})
    for old, new in zip(packet['criteria'][0]['payload']['requirement_refs'], cs.read(refs['k'])['payload']['requirement_refs'], strict=True):
        mapping[old['id']] = new['id']
    mapped_requirements = _replace_known_ids(packet['assignment']['review_requirements'], mapping, [])
    call = review_call(snapshot, refs, 'recorded-review-task')
    call['args'].pop('supervision_plugin', None)
    call['args']['review_requirements'] = mapped_requirements
    call['args']['description'] = packet['commission']['goal']
    changes = []
    rebound = _replace_known_ids(raw, mapping, changes)
    assert _replace_known_ids(rebound, {v: k for k, v in mapping.items()}, []) == raw
    for i, ref in enumerate(evidence_refs):
        assert cs.read(ref)['payload'] == packet['evidence'][i]['object']['payload']
    for i, key in enumerate(('k', 'k2')):
        assert cs.read(refs[key])['payload'] == _replace_known_ids(packet['criteria'][i]['payload'], mapping, [])
    return {'case': case, 'family': family, 'original_packet': packet, 'original_raw': raw,
        'recorded_raw_content': json.dumps(rebound, ensure_ascii=False), 'expected_assessments': rebound,
        'archive_files': [{'path': str(p), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in files],
        'archive_tool_result': old_result['tool_result'], 'id_mapping': mapping, 'raw_string_rebindings': changes,
        'evidence_refs': evidence_refs, 'criterion_refs': [refs['k'], refs['k2']], 'snapshot_ref': snapshot,
        'root_ref': refs['root'], 'task_call': call, 'originals': deepcopy(cs.list_objects()),
        'limits': ['Related recorded cases, not a single-variable semantic pair.',
                   'Recorded checker preparation is fake; historical usage is not new usage.']}


class RecordedChecker:
    """Only the first captured client invocation returns the recorded fixture."""
    def __init__(self, ws, fixture, factory):
        self.ws, self.fixture, self.factory = ws, fixture, factory
        self.recorded = Model(fixture['recorded_raw_content'])
        self.recorded.model_name = 'recorded-R1-checker-fixture-not-live'
        self.consumer_started, self.backend, self.calls = False, None, []

    def __getattr__(self, name):
        if self.consumer_started:
            if self.backend is None:
                self.backend = self.factory('text_tool')
            return getattr(self.backend, name)
        return getattr(self.recorded, name)

    async def ainvoke(self, messages):
        fixture_call = not self.calls
        if fixture_call:
            assert not self.consumer_started
            backend = self.recorded
            packet = json.loads(messages[-1][1] if isinstance(messages[-1], (tuple, list)) else messages[-1].content)
            cs = ContentStore(self.ws.store)
            assert packet['requested_scope_ids'] == ['rule-comparison', 'second-comparison']
            assert packet['assignment']['review_snapshot_ref'] == self.fixture['snapshot_ref']
            for i, ref in enumerate(self.fixture['evidence_refs']):
                assert packet['evidence'][i] == {'kind': 'saved_object', 'object': cs.read(ref)}
                assert packet['evidence'][i]['object']['payload'] == self.fixture['original_packet']['evidence'][i]['object']['payload']
            assert packet['criteria'] == [cs.read(ref) for ref in self.fixture['criterion_refs']]
            assert packet['evidence'][4]['kind'] == 'snapshot_structure'
            assert packet['evidence'][4]['structure']['root_ref'] == self.fixture['root_ref']
            for expected, actual in zip(self.fixture['task_call']['args']['review_requirements'], packet['assignment']['review_requirements'], strict=True):
                for key, value in expected.items():
                    assert actual[key] == value
        else:
            assert self.consumer_started
            if self.backend is None:
                self.backend = self.factory('text_tool')
            backend = self.backend
        record = {'origin': 'recorded_R1_fixture' if fixture_call else 'injected_text_service',
                  'model_identity': model_identity(backend), 'input': deepcopy(messages)}
        self.calls.append(record)
        response = await backend.ainvoke(messages)
        record['raw_response'] = response.model_dump()
        return response


class PrepareReview(AgentMiddleware):
    """Installed AgentMiddleware.awrap_model_call hook; no replacement loop."""
    def __init__(self, service, events):
        self.service, self.events, self.prepared = service, events, False

    async def awrap_model_call(self, request, handler):
        if not self.prepared:
            self.prepared = True
            answer = action('perform_assigned_review', 'recorded-checker', operation_id='recorded-R1-preparation',
                scope_ids=['rule-comparison', 'second-comparison'], source_selections=[], content_selections=[])
            self.events.append({'phase': 'explicit_fake_checker_setup', 'action': answer.model_dump(),
                                'request_messages': messages_to_dict(request.messages)})
            return ModelResponse(result=[answer])
        self.service.consumer_started = True
        event = {'phase': 'unchanged_reviewer_handler', 'request_messages': messages_to_dict(request.messages),
                 'native_tool_returns': [m.model_dump() for m in request.messages if isinstance(m, ToolMessage)]}
        self.events.append(event)
        result = await handler(request)
        event['response'] = messages_to_dict(result.result)
        return result


async def capture_reviewer_consumer(ws, case, folder, model_factory):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    fixture = prepare_reviewer_fixture(ws, case)
    activate(ws)
    dump(folder / 'fixture.json', fixture)
    cs, calls, phases, parent, models = ContentStore(ws.store), [], [], {}, {}
    service = RecordedChecker(ws, fixture, model_factory)
    hook = PrepareReview(service, phases)

    def parent_return(messages):
        parent['task_return'] = tool_reply(messages, 'recorded-review-task').model_dump()
        return action('read_task_supervision', 'parent-supervision')

    def parent_status(messages):
        message = next(m for m in reversed(messages) if isinstance(m, ToolMessage))
        value = result_value(message)
        parent.setdefault('status_tool_returns', []).append(message.model_dump())
        if message.name == 'read_task_supervision' and value.get('complete_tool_result') is False:
            assert value['exact_data_tool'] == 'read_tool_observation'
            parent['recovery'], parent['pages'] = value, []
            return action('read_tool_observation', 'parent-recovery', observation_ref=value['observation_ref'], offset=0, characters=6000)
        if message.name == 'read_tool_observation':
            assert value['observation_ref'] == parent['recovery']['observation_ref']
            assert value['offset'] == sum(len(p['text']) for p in parent['pages'])
            parent['pages'].append(deepcopy(value))
            if value['next_offset'] is not None:
                return action('read_tool_observation', 'parent-recovery', observation_ref=value['observation_ref'],
                              offset=value['next_offset'], characters=6000)
            value = json.loads(''.join(p['text'] for p in parent['pages']))
        parent['supervision'] = value
        return AIMessage(content='Recorded scoped findings received; no whole-report acceptance or host repair.')

    coordinator = Driver(coordinator=[AIMessage(content='', tool_calls=[fixture['task_call']]), parent_return, *([parent_status] * 15)])
    def factory(role):
        if role == 'coordinator':
            return coordinator(role)
        if role == 'text_tool':
            return service
        if role not in models:
            models[role] = traced_model(model_factory(role), role, calls)
        return models[role]
    original_builder = deep_runtime.create_deep_agent
    def build(*args, **kwargs):
        kwargs['subagents'] = [{**a, 'middleware': [*a.get('middleware', []), hook]}
            if a['name'] == 'reviewer' else a for a in kwargs['subagents']]
        return original_builder(*args, **kwargs)
    runtime, error = None, None
    try:
        with patch.object(deep_runtime, 'create_deep_agent', build):
            runtime = await deep_runtime.run_report(ws, factory)
    except Exception as exc:
        error = {'type': type(exc).__name__, 'message': str(exc)}
    finally:
        records, tasks = cs.list_objects('ReviewRecord'), cs.list_objects('DelegatedTask')
        finals = [m['data']['content'] for event in phases for m in event.get('response', [])
                  if m['type'] == 'ai' and not m['data'].get('tool_calls')]
        capture = {'case': case, 'runtime': runtime, 'raised_error': error, 'fixture': fixture,
            'phase_events': phases, 'native_model_calls': calls, 'checker_calls': service.calls,
            'parent': parent, 'parent_fake_calls': [{'role': r, 'step': n, 'messages': messages_to_dict(m)} for r, n, m in coordinator.calls],
            'saved_reviews': records, 'saved_task_status': [reconcile(cs, t['ref']['id']) for t in tasks],
            'consumer_finals': finals, 'semantic_status': 'needs_semantic_review' if FALSE_FINAL in finals else 'not_semantically_assessed',
            'originals_unchanged': all(cs.read(o['ref']) == o for o in fixture['originals']),
            'host_completion_actions': False, 'limits': [
                'Initial checker selection/response and parent are fake, not autonomous decisions.',
                'No cache/reuse shortcut: one fresh valid assignment is checked and saved through the real parser.',
                'False-final calibration is one known semantic counterexample, not a program acceptance guard.',
                'Future real Reviewer may investigate or hand off; every selected model call must count against its cap.']}
        dump(folder / 'capture.json', capture)
        with ws.store.connect() as db:
            receipts = [{'id': r[0], 'actor_id': r[1], 'data': json.loads(r[2])} for r in db.execute('SELECT id,actor_id,data FROM content_observations')]
        dump(folder / 'saved-state.json', {'objects': cs.list_objects(), 'receipts': receipts, 'events': ws.store.events()})
    return capture
