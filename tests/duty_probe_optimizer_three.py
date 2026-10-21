"""UNEXECUTED DRAFT: three feedback items through the native learning worker.

Synthetic host preparation creates real feedback records and one exact inactive
F1 candidate. Optional scripted read choices use the actual ToolNode. Thereafter
the original handler and injected client handle decisions and independent
analysis. No second agent loop, publication, forced new proposal or fake fallback.
Target after Main's explicit release: tests/duty_probe_optimizer_three.py.
"""
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import deepagents
from langchain.agents.middleware.types import AgentMiddleware, ModelResponse
from langchain_core.messages import AIMessage, ToolMessage, messages_to_dict

from duty_probe_agent_decisions import dump, traced_model
from duty_probe_optimizer_outcome import (
    CONDITIONS, MISSING, PREFERENCE, STRATEGY, SUSPICION, classify_observed_call,
)
from report_agent.content_store import ContentStore
from report_agent.hierarchical_tools import actor_for
from report_agent.learning import binding
from report_agent.learning_worker import consume_pending


TECHNICAL_UNKNOWN = ('At synthetic Site T, the groundwater level has not been established '
                     'from the supplied materials; retain this uncertainty.')
PRESERVE_CORRECTION = ('For synthetic Site T, preserve the stated technical uncertainty about '
                       'groundwater. The existing paragraph already states that the level is '
                       'not established; do not replace that statement with a definite water level.')
FINAL = ('All three assigned feedback items are accounted for. The existing candidate remains '
         'inactive and unverified; the missing title evidence and Site T technical uncertainty remain unresolved.')


def prepare_three_feedback(ws):
    """Actual public storage APIs; no work is attributed to an Optimizer here."""
    ws.store.set('manifest', {**ws.store.manifest,
        'goal': 'Handle the assigned customer feedback and preserve unresolved evidence.',
        'sources': [
            {'id': 'customer-request', 'title': 'Synthetic customer request', 'content': PREFERENCE, 'coverage': 'complete'},
            {'id': 'site-t-observation', 'title': 'Synthetic Site T observation', 'content': TECHNICAL_UNKNOWN, 'coverage': 'complete'}]})
    cs = ContentStore(ws.store)
    inputs = cs.import_inputs(actor_for('coordinator'), 'synthetic-three-inputs',
                              ['customer-request', 'site-t-observation'])['result']
    refs = cs.commit(actor_for('writer'), 'synthetic-three-original-content', [
        {'client_key': 'f1-row', 'type': 'ContentNode', 'payload': {'kind': 'table',
            'body': {'columns': ['Entry', 'Value'], 'rows': [['Routine source-file inventory', '5 files']]},
            'qualifiers': {'status': 'Synthetic original; no review or engineering approval.'}, 'claim_kind': 'fact'}},
        {'client_key': 'f3-block', 'type': 'ContentNode', 'payload': {'kind': 'block',
            'body': {'text': TECHNICAL_UNKNOWN},
            'qualifiers': {'technical_uncertainty': TECHNICAL_UNKNOWN}, 'claim_kind': 'fact'}}
    ])['result']['refs']
    source_records = [cs.read(ref) for ref in inputs['source_refs']]
    by_text = {record['payload']['content']: record for record in source_records}
    assert set(by_text) == {PREFERENCE, TECHNICAL_UNKNOWN}
    f1_source, f3_source = by_text[PREFERENCE]['ref'], by_text[TECHNICAL_UNKNOWN]['ref']
    assert refs['f1-row']['id'] != refs['f3-block']['id']
    ws.store.set('learning_config', {'library_path': str(ws.store.root / 'isolated-learning-library'),
                                     'customer_id': 'synthetic-optimizer-customer'})
    library, scope = binding(ws)
    f1 = library.feedback(scope, {}, refs['f1-row'], PREFERENCE, cs.read(refs['f1-row'])['payload'],
                          [{'source_ref': f1_source, 'customer_request': PREFERENCE}])
    # Absence is explicit evidence metadata, not a fabricated report inspection.
    f2 = library.feedback(scope, {}, {}, SUSPICION, {'report_available': False}, [deepcopy(MISSING)])
    f3 = library.feedback(scope, {}, refs['f3-block'], PRESERVE_CORRECTION, cs.read(refs['f3-block'])['payload'],
                          [{'source_ref': f3_source, 'original_statement': TECHNICAL_UNKNOWN}])
    # Host-only synthetic starting state, created with the actual candidate API.
    # The ensuing worker is free to choose a different legal handling strategy.
    created = library.propose(scope, [f1['id']], 'customer_preference',
        'Issues-only workbook preference', STRATEGY, CONDITIONS,
        'Check a later scoped workbook for identified issues versus routine file-inventory rows.')
    existing = next(c for c in library.list_versions(scope)
                    if (c['id'], c['version']) == (created['id'], created['version']))
    assert existing['feedback_ids'] == [f1['id']] and not existing['active']
    return {'feedback': {'f1': f1, 'f2': f2, 'f3': f3},
        'feedback_originals': deepcopy(library.feedback_items(scope)),
        'business_originals': deepcopy(cs.list_objects()), 'targets': refs,
        'source_refs': {'f1': f1_source, 'f3': f3_source},
        'source_originals': {'f1': cs.read(f1_source), 'f3': cs.read(f3_source)},
        'existing_candidate': deepcopy(existing), 'candidate_creation_receipt': created,
        'candidate_originals': deepcopy(library.list_versions(scope)),
        'queue_before_claim': deepcopy(library.queue_status(scope)),
        'customer': scope.customer, 'project': scope.project,
        'setup_origin': 'Explicit synthetic host fixture through feedback/propose APIs; no model achievement.',
        'finite_material_states': {'f1': 'Evidence-backed preference and pre-existing inactive exact-F1 candidate.',
            'f2': 'No report version or locator; missing title is unverified.',
            'f3': 'Different exact target already preserves the source technical uncertainty.'}}


class PreparedThreeReads(AgentMiddleware):
    """One explicit fake selection, twelve real reads, then unchanged handler."""
    def __init__(self, ws, fixture, phases):
        self.ws, self.fixture, self.phases, self.started = ws, fixture, phases, False

    async def awrap_model_call(self, request, handler):
        if not self.started:
            self.started = True
            assignment = deepcopy(self.ws.store.get('learning_active_feedback'))
            ids = [self.fixture['feedback'][label]['id'] for label in ('f1', 'f2', 'f3')]
            assert assignment['feedback_ids'] == ids
            calls = [{'name': 'read_learning_feedback', 'id': label + '-' + field, 'type': 'tool_call',
                'args': {'feedback_id': identifier, 'field': field}}
                for label, identifier in zip(('f1', 'f2', 'f3'), ids, strict=True)
                for field in ('correction', 'before', 'evidence')]
            calls += [{'name': 'read_learning_evidence', 'id': label + '-source', 'type': 'tool_call',
                'args': {'ref': self.fixture['source_refs'][label], 'offset': 0, 'limit': 8000}}
                for label in ('f1', 'f3')]
            candidate = self.fixture['existing_candidate']
            calls.append({'name': 'read_experience_candidates', 'id': 'f1-existing-candidate', 'type': 'tool_call',
                'args': {'experience_id': candidate['id'], 'version': candidate['version'], 'offset': 0, 'limit': 8000}})
            answer = AIMessage(content='', tool_calls=calls)
            self.phases.append({'phase': 'explicit_fake_read_setup', 'assignment': assignment,
                'action': answer.model_dump(), 'request_messages': messages_to_dict(request.messages)})
            return ModelResponse(result=[answer])
        event = {'phase': 'unchanged_consumer_handler', 'request_messages': messages_to_dict(request.messages),
                 'native_tool_returns': [m.model_dump() for m in request.messages if isinstance(m, ToolMessage)]}
        self.phases.append(event)
        result = await handler(request)
        event['response'] = messages_to_dict(result.result)
        return result


def assess_three_feedback(ws, fixture):
    """Accounting and immutable identities; no automatic semantic classification."""
    library, scope = binding(ws)
    candidates = deepcopy(library.list_versions(scope))
    job = deepcopy(ws.store.get('learning_job') or {})
    dispositions = deepcopy(job.get('feedback_dispositions', {}))
    assigned = {f['id'] for f in fixture['feedback'].values()}
    originals = {(c['id'], c['version']): c for c in fixture['candidate_originals']}
    current = {(c['id'], c['version']): c for c in candidates}
    links = []
    for feedback_id, disposition in dispositions.items():
        if disposition['outcome'] == 'candidate':
            ref = disposition.get('candidate', {})
            candidate = current.get((ref.get('id'), ref.get('version')))
            links.append({'feedback_id': feedback_id, 'candidate': ref,
                'valid': candidate is not None and feedback_id in candidate['feedback_ids']})
    cs = ContentStore(ws.store)
    return {'job': job, 'queue': library.queue_status(scope), 'candidates': candidates,
        'new_candidates': [c for key, c in current.items() if key not in originals],
        'dispositions': dispositions, 'candidate_links': links,
        'missing_feedback_ids': sorted(assigned - set(dispositions)),
        'unexpected_feedback_ids': sorted(set(dispositions) - assigned),
        'candidate_originals_unchanged': all(current.get(key) == value for key, value in originals.items()),
        'feedback_originals_unchanged': library.feedback_items(scope) == fixture['feedback_originals'],
        'business_originals_unchanged': cs.list_objects() == fixture['business_originals'],
        'source_originals_unchanged': all(cs.read(record['ref']) == record for record in fixture['source_originals'].values()),
        'all_candidates_inactive': all(not c['active'] for c in candidates), 'active_library': library.search(scope),
        'active_assignment_after_worker': ws.store.get('learning_active_feedback'),
        'semantic_status': 'not_semantically_assessed',
        'limits': 'Completed accounting, no-change and candidate links do not establish quality, report correction or release.'}


async def capture_optimizer_three(ws, folder, model_factory, *, prepared_reads=True):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    fixture = prepare_three_feedback(ws)
    dump(folder / 'fixture.json', fixture)
    calls, phases = [], []
    model = traced_model(model_factory('optimizer'), 'optimizer', calls)
    hook = PreparedThreeReads(ws, fixture, phases)
    original_builder = deepagents.create_deep_agent
    def with_optional_reads(*args, **kwargs):
        if prepared_reads and kwargs.get('name') == 'experience_optimizer':
            kwargs['middleware'] = [*kwargs.get('middleware', []), hook]
        return original_builder(*args, **kwargs)
    result, error = None, None
    try:
        with patch.object(deepagents, 'create_deep_agent', with_optional_reads):
            result = await consume_pending(ws, lambda: model, max_steps=40)
    except Exception as exc:
        error = {'type': type(exc).__name__, 'message': str(exc)}
    finally:
        for call in calls:
            call['boundary'] = classify_observed_call(call)
        capture = {'runtime_result': result, 'raised_error': error, 'fixture': fixture,
            'native_model_calls': calls, 'preparation_phases': phases, 'prepared_reads': prepared_reads,
            'assessment': assess_three_feedback(ws, fixture),
            'host_completion_actions': False, 'host_candidate_publication': False,
            'host_existing_candidate_preparation': True,
            'native_entrypoint': 'consume_pending -> _run_optimizer_locked -> build_optimizer -> native ToolNode',
            'model_client_policy': 'Native optimizer decisions and any selected independent analysis share the same injected original client.',
            'limits': ['Three feedback records and the existing inactive candidate are explicit host synthetic preparation.',
                'Optional initial read choices are fake; actual ToolNode results enter the unchanged model handler.',
                'Different legal no-change, insufficient-evidence or candidate outcomes remain possible; no new proposal is required.',
                'No report changes, release, GEPA experiment, repair, second loop or fake service fallback.',
                'Any future six-all-HTTP budget is a separate proposed experiment, not authorization to execute this draft.']}
        dump(folder / 'capture.json', capture)
        library, scope = binding(ws)
        dump(folder / 'saved-state.json', {'business_objects': ContentStore(ws.store).list_objects(),
            'feedback': library.feedback_items(scope), 'candidates': library.list_versions(scope),
            'queue': library.queue_status(scope), 'job': ws.store.get('learning_job'), 'events': ws.store.events()})
    return capture
