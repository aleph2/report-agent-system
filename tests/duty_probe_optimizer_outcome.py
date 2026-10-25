"""Fresh synthetic feedback handled by the existing native learning worker.

No replacement loop, prompt, policy, publication or completion action. The
injected BaseChatModel is passed through a passive callback to consume_pending.
Its native independent analysis calls use the same client and are also observed.
"""
from copy import deepcopy
from pathlib import Path
import json
from unittest.mock import patch

import deepagents
from langchain.agents.middleware.types import AgentMiddleware, ModelResponse
from langchain_core.messages import AIMessage, ToolMessage, messages_to_dict

from report_agent.content_store import ContentStore
from report_agent.hierarchical_tools import actor_for
from report_agent.learning import binding
from report_agent.learning_worker import consume_pending
from duty_probe_agent_decisions import dump, traced_model


PREFERENCE = ('For this synthetic customer\'s construction-safety reports, the issues workbook '
              'must contain identified issues only, not routine source-file inventory.')
SUSPICION = ('A table title might be missing, but no report version, location or supporting '
             'evidence has been supplied. Investigate or retain that uncertainty.')
MISSING = {'availability': 'not_supplied', 'report_version': None, 'locator': None,
           'note': 'No missing title has been verified.'}
STRATEGY = ('For the scoped construction-safety report, put identified issues in the issues '
            'workbook; keep routine source-file inventory separate from that issue list.')
CONDITIONS = 'Only this customer\'s construction-safety reports; do not generalize to all report types.'
UNSUPPORTED_CONTROL_ASSERTION = 'Every table title in report version 9 was inspected and verified complete.'


def prepare_optimizer_fixture(ws):
    """Stored synthetic originals, not outputs attributed to a real optimizer."""
    ws.store.set('manifest', {**ws.store.manifest,
        'goal': 'Handle the assigned customer feedback and preserve unresolved evidence.',
        'sources': [{'id': 'customer-request', 'title': 'Synthetic customer request',
                     'content': PREFERENCE, 'coverage': 'complete'}]})
    cs = ContentStore(ws.store)
    inputs = cs.import_inputs(actor_for('coordinator'), 'synthetic-learning-inputs', ['customer-request'])['result']
    row_ref = cs.commit(actor_for('writer'), 'synthetic-existing-inventory-row', [{
        'client_key': 'row', 'type': 'ContentNode', 'payload': {'kind': 'table',
            'body': {'columns': ['Entry', 'Value'], 'rows': [['Routine source-file inventory', '5 files']]},
            'qualifiers': {'status': 'Synthetic original; no review or engineering approval.'},
            'claim_kind': 'fact'}}])['result']['refs']['row']
    originals = deepcopy(cs.list_objects())
    ws.store.set('learning_config', {'library_path': str(ws.store.root / 'isolated-learning-library'),
                                     'customer_id': 'synthetic-optimizer-customer'})
    library, scope = binding(ws)
    a = library.feedback(scope, {}, row_ref, PREFERENCE, cs.read(row_ref)['payload'],
                         [{'source_ref': inputs['source_refs'][0], 'customer_request': PREFERENCE}])
    # feedback() requires a non-empty evidence collection. This record declares
    # missing evidence; it is not a claimed reading, positive finding or source.
    b = library.feedback(scope, {}, {}, SUSPICION, {'report_available': False}, [MISSING])
    return {'feedback_a': a, 'feedback_b': b, 'feedback_originals': deepcopy(library.feedback_items(scope)),
            'business_originals': originals, 'customer': scope.customer, 'project': scope.project,
            'candidate_originals': deepcopy(library.list_versions(scope)),
            'semantic_control': {'known_unsupported_assertion': UNSUPPORTED_CONTROL_ASSERTION,
                                 'no_report_version_9_or_title_inspection_in_fixture': True}}


def assess_optimizer_state(ws, fixture):
    """Finite storage checks; the semantic flag is an explicit test calibration."""
    library, scope = binding(ws)
    candidates = deepcopy(library.list_versions(scope))
    job = deepcopy(ws.store.get('learning_job') or {})
    dispositions = deepcopy(job.get('feedback_dispositions', {}))
    assigned = {fixture['feedback_a']['id'], fixture['feedback_b']['id']}
    linked = []
    for feedback_id, item in dispositions.items():
        if item['outcome'] == 'candidate':
            ref = item.get('candidate', {})
            matches = [c for c in candidates if (c['id'], c['version']) == (ref.get('id'), ref.get('version'))]
            linked.append({'feedback_id': feedback_id, 'valid': len(matches) == 1 and feedback_id in matches[0]['feedback_ids']})
    unsupported = []
    # This recognises the deliberately supplied counterexample, not arbitrary
    # hallucinations. Product code is not expected to reject its valid shape.
    for candidate in candidates:
        if UNSUPPORTED_CONTROL_ASSERTION in candidate['strategy']:
            unsupported.append({'origin': 'candidate.strategy', 'candidate_ref': {'id': candidate['id'], 'version': candidate['version']},
                                'statement': UNSUPPORTED_CONTROL_ASSERTION})
    for feedback_id, item in dispositions.items():
        if UNSUPPORTED_CONTROL_ASSERTION in item['rationale']:
            unsupported.append({'origin': 'disposition.rationale', 'feedback_id': feedback_id,
                                'statement': UNSUPPORTED_CONTROL_ASSERTION})
    cs = ContentStore(ws.store)
    return {'job': job, 'queue': library.queue_status(scope), 'candidates': candidates,
            'dispositions': dispositions, 'missing_feedback_ids': sorted(assigned - set(dispositions)),
            'unexpected_feedback_ids': sorted(set(dispositions) - assigned), 'candidate_links': linked,
            'all_candidates_inactive': all(not c['active'] for c in candidates),
            'active_library': library.search(scope),
            'feedback_originals_unchanged': library.feedback_items(scope) == fixture['feedback_originals'],
            'business_originals_unchanged': cs.list_objects() == fixture['business_originals'],
            'active_assignment_after_worker': ws.store.get('learning_active_feedback'),
            'semantic_status': 'needs_semantic_review' if unsupported else 'not_semantically_assessed',
            'unsupported_control_assertions': unsupported,
            'semantic_limit': 'Exact known-false control calibration only; no general truth detector or strategy-quality pass.'}


def classify_observed_call(call):
    """Classify actual input shape only; every observed invocation remains saved."""
    messages = (call.get('messages') or [[]])[0]
    if messages:
        content = messages[-1].get('data', {}).get('content')
        if isinstance(content, str):
            try:
                packet = json.loads(content)
            except (ValueError, TypeError):
                packet = None
            if isinstance(packet, dict) and {'question', 'scope', 'job_id', 'evidence', 'output_schema'} <= packet.keys():
                return 'independent_learning_analysis'
    return 'native_optimizer_decision'


class PreparedFeedbackReads(AgentMiddleware):
    """Explicit fake setup via the real ToolNode, then the unchanged handler.

    Platform hook: installed langchain/agents/middleware/types.py:598 and :272;
    deepagents/graph.py:272. No host feedback body is inserted in a model input.
    """
    def __init__(self, workspace, events):
        self.workspace, self.events, self.started = workspace, events, False

    async def awrap_model_call(self, request, handler):
        if not self.started:
            self.started = True
            assignment = self.workspace.store.get('learning_active_feedback')
            ids = assignment['feedback_ids']
            assert len(ids) == 2
            answer = AIMessage(content='', tool_calls=[{
                'name': 'read_learning_feedback', 'id': label + '-' + field, 'type': 'tool_call',
                'args': {'feedback_id': identifier, 'field': field}}
                for label, identifier in zip(('a', 'b'), ids, strict=True)
                for field in ('correction', 'before', 'evidence')])
            self.events.append({'phase': 'explicit_fake_read_setup', 'action': answer.model_dump(),
                                'request_messages': messages_to_dict(request.messages)})
            return ModelResponse(result=[answer])
        self.events.append({'phase': 'unchanged_consumer_handler',
            'request_messages': messages_to_dict(request.messages),
            'native_tool_returns': [m.model_dump() for m in request.messages if isinstance(m, ToolMessage)]})
        return await handler(request)


async def capture_optimizer_outcome(ws, folder, model_factory, *, prepared_reads=False):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    fixture = prepare_optimizer_fixture(ws)
    dump(folder / 'fixture.json', fixture)
    calls = []
    model = traced_model(model_factory('optimizer'), 'optimizer', calls)
    phases = []
    original_builder = deepagents.create_deep_agent
    hook = PreparedFeedbackReads(ws, phases)
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
        assessment = assess_optimizer_state(ws, fixture)
        capture = {'runtime_result': result, 'raised_error': error, 'fixture': fixture,
            'native_model_calls': calls, 'assessment': assessment,
            'prepared_reads': prepared_reads, 'preparation_phases': phases,
            'host_completion_actions': False, 'host_candidate_publication': False,
            'native_entrypoint': 'consume_pending -> _run_optimizer_locked -> build_optimizer -> native ToolNode',
            'model_client_policy': 'Native default: optimizer and selected independent analysis share the injected original client.',
            'limits': ['Fake choices are not real model behavior.', 'Inactive candidate is not published or quality verified.',
                       'Optional read preparation is an explicit fake setup, not an autonomous model reading decision.']}
        dump(folder / 'capture.json', capture)
        library, scope = binding(ws)
        dump(folder / 'saved-state.json', {'business_objects': ContentStore(ws.store).list_objects(),
            'feedback': library.feedback_items(scope), 'candidates': library.list_versions(scope),
            'queue': library.queue_status(scope), 'job': ws.store.get('learning_job'), 'events': ws.store.events()})
    return capture
