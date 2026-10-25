"""One synthetic customer preference through the existing native learning loop.

The optional setup is explicitly fake action selection using actual read tools.
Subsequent model calls, independent analysis and tool execution use the injected
client and unmodified platform handler. No publication or host completion.
"""
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import deepagents
from langchain.agents.middleware.types import AgentMiddleware, ModelResponse
from langchain_core.messages import AIMessage, ToolMessage, messages_to_dict

from duty_probe_agent_decisions import dump, traced_model
from duty_probe_optimizer_outcome import (
    PREFERENCE, UNSUPPORTED_CONTROL_ASSERTION, classify_observed_call,
)
from report_agent.content_store import ContentStore
from report_agent.hierarchical_tools import actor_for
from report_agent.learning import binding
from report_agent.learning_worker import consume_pending


def prepare_single_feedback(ws):
    """Create A directly; never create/delete a second feedback record."""
    ws.store.set('manifest', {**ws.store.manifest,
        'goal': 'Handle the assigned customer feedback and preserve unresolved evidence.',
        'sources': [{'id': 'customer-request', 'title': 'Synthetic customer request',
                     'content': PREFERENCE, 'coverage': 'complete'}]})
    cs = ContentStore(ws.store)
    inputs = cs.import_inputs(actor_for('coordinator'), 'synthetic-single-inputs', ['customer-request'])['result']
    row_ref = cs.commit(actor_for('writer'), 'synthetic-existing-inventory-row', [{
        'client_key': 'row', 'type': 'ContentNode', 'payload': {'kind': 'table',
            'body': {'columns': ['Entry', 'Value'], 'rows': [['Routine source-file inventory', '5 files']]},
            'qualifiers': {'status': 'Synthetic original; no review or engineering approval.'},
            'claim_kind': 'fact'}}])['result']['refs']['row']
    originals = deepcopy(cs.list_objects())
    ws.store.set('learning_config', {'library_path': str(ws.store.root / 'isolated-learning-library'),
                                     'customer_id': 'synthetic-optimizer-customer'})
    library, scope = binding(ws)
    feedback = library.feedback(scope, {}, row_ref, PREFERENCE, cs.read(row_ref)['payload'],
        [{'source_ref': inputs['source_refs'][0], 'customer_request': PREFERENCE}])
    source_ref = feedback['evidence'][0]['source_ref']
    return {'feedback': feedback, 'feedback_originals': deepcopy(library.feedback_items(scope)),
        'business_originals': originals, 'source_ref': source_ref, 'source_original': cs.read(source_ref),
        'customer': scope.customer, 'project': scope.project,
        'candidate_originals': deepcopy(library.list_versions(scope)),
        'semantic_control': {'known_unsupported_assertion': UNSUPPORTED_CONTROL_ASSERTION,
                             'no_report_version_9_or_title_inspection_in_fixture': True}}


class PreparedSingleReads(AgentMiddleware):
    """Five explicit fake read choices, actual ToolNode; then unchanged handler.

    Same installed platform hook as the existing double-feedback helper:
    langchain/agents/middleware/types.py awrap_model_call + ModelResponse.
    """
    def __init__(self, ws, fixture, events):
        self.ws, self.fixture, self.events, self.started = ws, fixture, events, False

    async def awrap_model_call(self, request, handler):
        if not self.started:
            self.started = True
            assigned = self.ws.store.get('learning_active_feedback')['feedback_ids']
            assert assigned == [self.fixture['feedback']['id']]
            source_ref = self.fixture['feedback']['evidence'][0]['source_ref']
            assert source_ref == self.fixture['source_ref']
            calls = [{'name': 'read_learning_feedback', 'id': 'a-' + field, 'type': 'tool_call',
                      'args': {'feedback_id': assigned[0], 'field': field}}
                     for field in ('correction', 'before', 'evidence')]
            calls += [
                {'name': 'read_learning_evidence', 'id': 'a-source', 'type': 'tool_call',
                 'args': {'ref': source_ref, 'offset': 0, 'limit': 8000}},
                {'name': 'read_experience_candidates', 'id': 'candidate-index', 'type': 'tool_call', 'args': {}}]
            answer = AIMessage(content='', tool_calls=calls)
            self.events.append({'phase': 'explicit_fake_read_setup', 'action': answer.model_dump(),
                                'request_messages': messages_to_dict(request.messages)})
            return ModelResponse(result=[answer])
        self.events.append({'phase': 'unchanged_consumer_handler',
            'request_messages': messages_to_dict(request.messages),
            'native_tool_returns': [m.model_dump() for m in request.messages if isinstance(m, ToolMessage)]})
        return await handler(request)


def assess_single_feedback(ws, fixture):
    library, scope = binding(ws)
    candidates = deepcopy(library.list_versions(scope))
    job = deepcopy(ws.store.get('learning_job') or {})
    dispositions = deepcopy(job.get('feedback_dispositions', {}))
    assigned = {fixture['feedback']['id']}
    links, unsupported = [], []
    for feedback_id, item in dispositions.items():
        if item['outcome'] == 'candidate':
            ref = item.get('candidate', {})
            matches = [c for c in candidates if (c['id'], c['version']) == (ref.get('id'), ref.get('version'))]
            links.append({'feedback_id': feedback_id,
                          'valid': len(matches) == 1 and feedback_id in matches[0]['feedback_ids']})
        if UNSUPPORTED_CONTROL_ASSERTION in item['rationale']:
            unsupported.append({'origin': 'disposition.rationale', 'feedback_id': feedback_id,
                                'statement': UNSUPPORTED_CONTROL_ASSERTION})
    for candidate in candidates:
        if UNSUPPORTED_CONTROL_ASSERTION in candidate['strategy']:
            unsupported.append({'origin': 'candidate.strategy',
                'candidate_ref': {'id': candidate['id'], 'version': candidate['version']},
                'statement': UNSUPPORTED_CONTROL_ASSERTION})
    return {'job': job, 'queue': library.queue_status(scope), 'candidates': candidates,
        'dispositions': dispositions, 'missing_feedback_ids': sorted(assigned - set(dispositions)),
        'unexpected_feedback_ids': sorted(set(dispositions) - assigned), 'candidate_links': links,
        'all_candidates_inactive': all(not c['active'] for c in candidates), 'active_library': library.search(scope),
        'feedback_originals_unchanged': library.feedback_items(scope) == fixture['feedback_originals'],
        'business_originals_unchanged': ContentStore(ws.store).list_objects() == fixture['business_originals'],
        'active_assignment_after_worker': ws.store.get('learning_active_feedback'),
        'semantic_status': 'needs_semantic_review' if unsupported else 'not_semantically_assessed',
        'unsupported_control_assertions': unsupported,
        'semantic_limit': 'Exact known-false test-control calibration only, not a general semantic validator.'}


async def capture_optimizer_single(ws, folder, model_factory, *, prepared_reads=True):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    fixture = prepare_single_feedback(ws)
    dump(folder / 'fixture.json', fixture)
    calls, phases = [], []
    model = traced_model(model_factory('optimizer'), 'optimizer', calls)
    original_builder = deepagents.create_deep_agent
    hook = PreparedSingleReads(ws, fixture, phases)
    def with_optional_preparation(*args, **kwargs):
        if prepared_reads and kwargs.get('name') == 'experience_optimizer':
            kwargs['middleware'] = [*kwargs.get('middleware', []), hook]
        return original_builder(*args, **kwargs)
    result, error = None, None
    try:
        with patch.object(deepagents, 'create_deep_agent', with_optional_preparation):
            result = await consume_pending(ws, lambda: model, max_steps=40)
    except Exception as exc:
        error = {'type': type(exc).__name__, 'message': str(exc)}
    finally:
        for call in calls:
            call['boundary'] = classify_observed_call(call)
        capture = {'runtime_result': result, 'raised_error': error, 'fixture': fixture,
            'native_model_calls': calls, 'preparation_phases': phases, 'prepared_reads': prepared_reads,
            'assessment': assess_single_feedback(ws, fixture),
            'host_completion_actions': False, 'host_candidate_publication': False,
            'native_entrypoint': 'consume_pending -> _run_optimizer_locked -> build_optimizer -> native ToolNode',
            'model_client_policy': 'Optimizer and selected independent analysis use the same original injected client.',
            'limits': ['Read preparation is explicit fake action selection, not autonomous material selection.',
                       'Candidate and completed accounting are not quality approval or publication.',
                       'No-change means no new reusable candidate; it does not waive the explicit customer requirement.',
                       'A future call cap includes independent analysis and cannot guarantee completion.']}
        dump(folder / 'capture.json', capture)
        library, scope = binding(ws)
        dump(folder / 'saved-state.json', {'business_objects': ContentStore(ws.store).list_objects(),
            'feedback': library.feedback_items(scope), 'candidates': library.list_versions(scope),
            'queue': library.queue_status(scope), 'job': ws.store.get('learning_job'), 'events': ws.store.events()})
    return capture
