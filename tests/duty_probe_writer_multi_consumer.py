"""P06 tests: fresh two-output producer followed by native Writer.

Only the first Writer action and the parent decisions are scripted. The
independent producer uses the supplied model_factory('text_tool') from its
first call; subsequent Writer decisions use the original handler. No archived
response, provider, budget, retry, replacement final action, or agent loop.
"""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch

from langchain.agents.middleware.types import AgentMiddleware, ModelResponse
from langchain_core.messages import AIMessage, ToolMessage, messages_from_dict, messages_to_dict

from duty_probe_agent_decisions import dump, traced_model
from report_agent import deep_runtime
from report_agent.content_store import ContentStore
from report_agent.hierarchical_tools import actor_for
from test_agent_duty_repro_judgments import GUIDE
from test_agent_duty_trace_cases import action, result_value, tool_reply
from test_decision_data import activate
from test_deep_runtime import Driver


GOAL = ('Prepare the original reference table and a separate Site B assessment note from the supplied sources. '
        'Preserve the complete table, its original footnote and applicable source limitations. '
        'This synthetic work does not establish engineering acceptance.')
OBJECTIVE = ('Produce two content nodes in order: first the supplied reference table with all columns and '
             'its original footnote, then a separate Site B assessment note based on the Site B source. '
             'Retain source qualifications and distinguish a reference score interval from a selected score.')
SITE_B = ('Site B survey note: the available record does not establish a weathering category. '
          'It contains no classified geological description or matching design confirmation from which '
          'a category-specific risk score can be selected. This limitation concerns Site B only.')


class InitialBatchRequest(AgentMiddleware):
    def __init__(self, ws, fixture, events, held):
        self.ws, self.fixture, self.events, self.held, self.started = ws, fixture, events, held, False

    async def awrap_model_call(self, request, handler):
        if not self.started:
            self.started = True
            response = action('process_report_content', 'initial-batch', operation_id='fresh-two-candidate-work',
                objective=OBJECTIVE, object_type='ContentNode', output_count=2,
                input_refs=self.fixture['source_refs'])
            self.events.append({'phase': 'explicit_fake_initial_action',
                'request_messages': messages_to_dict(request.messages), 'response': response.model_dump()})
            return ModelResponse(result=[response])
        if 'first_public_message' not in self.held:
            actual = tool_reply(request.messages, 'initial-batch')
            self.held['first_public_message'] = actual.model_dump()
            self.held['first_public_value'] = result_value(actual)
            receipt = self.held['first_public_value'].get('text_work_id')
            self.held['initial_receipt_before'] = deepcopy(self.ws.store.get('text_work_receipt:' + receipt)) if receipt else None
        event = {'phase': 'native_writer_handler', 'request_messages': messages_to_dict(request.messages),
            'actual_tool_returns': [m.model_dump() for m in request.messages if isinstance(m, ToolMessage)]}
        self.events.append(event)
        result = await handler(request)
        event['response'] = messages_to_dict(result.result)
        return result


def observe_multi_adoption(ws, fixture, held, events):
    """Bind actual successful adoption actions to the initial receipt and index.

    Payload equality alone is insufficient: two equal objects or another
    operation must not silently count as adoption of both initial indexes.
    This observer makes no natural-language or engineering judgment.
    """
    cs = ContentStore(ws.store)
    public = held.get('first_public_value', {})
    receipt_id = public.get('text_work_id')
    stored = ws.store.get('text_work_receipt:' + receipt_id) if receipt_id else None
    result = (stored or {}).get('result', {})
    payloads = result.get('payloads', [])
    calls, returns = {}, {}
    for event in events:
        for message in messages_from_dict(event['request_messages']):
            if isinstance(message, AIMessage):
                calls.update({c['id']: c for c in message.tool_calls})
            elif isinstance(message, ToolMessage):
                returns[message.tool_call_id] = message
    adoptions, other_actions = [], []
    for call_id, call in calls.items():
        if call['name'] not in {'save_text_node', 'commit_objects'} or call_id not in returns:
            continue
        answer = returns[call_id]
        value = result_value(answer)
        if answer.status != 'success' or not value.get('ok'):
            continue
        args = call['args']
        items = ([{'client_key': 'text', **args}] if call['name'] == 'save_text_node'
                 else args.get('objects', []))
        for item in items:
            if item.get('text_work_id') != receipt_id:
                other_actions.append({'call_id': call_id, 'item': item})
                continue
            index = item.get('text_work_index', 0)
            ref = value['result']['refs'][item['client_key']]
            node = cs.read(ref)
            exact = (type(index) is int and 0 <= index < len(payloads)
                and node['payload'] == payloads[index] and node['owner_id'] == result.get('actor_id')
                and node['task_id'] == result.get('task_id'))
            adoptions.append({'call_id': call_id, 'tool': call['name'], 'args': args,
                'text_work_id': receipt_id, 'index': index, 'saved_node': node, 'exact': exact})
    indexes = sorted({a['index'] for a in adoptions if a['exact']})
    expected_indexes = list(range(len(payloads)))
    originals_ok = all(cs.read(o['ref']) == o for o in fixture['originals'])
    if not stored or stored.get('state') != 'completed' or len(payloads) != 2:
        status = 'initial_batch_not_completed'
    elif not originals_ok or any(not a['exact'] for a in adoptions):
        status = 'saved_state_requires_review'
    elif indexes == expected_indexes:
        status = 'exact_initial_batch_adopted'
    elif indexes:
        status = 'partial_initial_batch_adoption'
    else:
        status = 'initial_batch_not_adopted'
    return {'status': status, 'initial_receipt': stored, 'initial_receipt_id': receipt_id,
        'initial_receipt_unchanged': stored == held.get('initial_receipt_before'),
        'adoptions': adoptions, 'adopted_indexes': indexes,
        'unadopted_indexes': [i for i in expected_indexes if i not in indexes],
        'other_successful_content_actions': other_actions,
        'originals_unchanged': originals_ok, 'all_content_nodes': cs.list_objects('ContentNode'),
        'no_review_or_export': not cs.list_objects('ReviewRecord') and not cs.list_objects('ExportArtifact'),
        'semantic_status': 'needs_semantic_review',
        'limits': ['An exact stored candidate can retain unresolved technical conditions.',
            'Candidate count or one saved node does not establish that both indexes were adopted.',
            'This host diagnostic is never supplied to the Writer as source or tool evidence.',
            'No Word export: retaining body.footnote does not resolve the known visible-footnote defect.']}


async def capture_writer_multi_consumer(ws, folder, model_factory):
    """Caller owns all model clients, budgets and closing; native graph only."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    sources = [{'id': 'guide-a', 'title': 'Synthetic complete reference table', 'content': GUIDE, 'coverage': 'complete'},
               {'id': 'site-b', 'title': 'Synthetic Site B survey limitations', 'content': SITE_B, 'coverage': 'complete'}]
    ws.store.set('manifest', {**ws.store.manifest, 'goal': GOAL, 'sources': sources})
    cs = ContentStore(ws.store)
    imported = cs.import_inputs(actor_for('coordinator'), 'multi-consumer-inputs', [s['id'] for s in sources])['result']
    fixture = {'goal': GOAL, 'objective': OBJECTIVE, 'sources': sources, 'source_refs': imported['source_refs'],
        'originals': [deepcopy(cs.read(r)) for r in [imported['requirement_ref'], *imported['source_refs']]],
        'table_columns': ['Indicator', 'Category', 'Score', 'Explanation'],
        'table_rows': [['geology', 'B', '75-100', 'Apply only when weathering is strong.']],
        'original_footnote': GUIDE.split('\nFOOTNOTE:', 1)[1].strip(),
        'scope': 'Ordered reference-table and independent Site B note candidates. Full input/storage checks only.'}
    activate(ws)
    dump(folder / 'fixture.json', fixture)
    events, calls, models, held, parent = [], [], {}, {}, {}
    hook = InitialBatchRequest(ws, fixture, events, held)

    def parent_result(messages):
        parent['task_return'] = tool_reply(messages, 'multi-consumer-task').model_dump()
        return AIMessage(content='Writer outcome retained without host completion or engineering acceptance.')

    coordinator = Driver(coordinator=[action('task', 'multi-consumer-task', subagent_type='writer', description=GOAL),
                                     parent_result])

    def factory(role):
        if role == 'coordinator':
            return coordinator(role)
        if role not in models:
            # Includes text_tool from its first call. There is no recorded or
            # otherwise substituted producer response in this helper.
            models[role] = traced_model(model_factory(role), role, calls)
        return models[role]

    original_builder = deep_runtime.create_deep_agent
    def build(*args, **kwargs):
        kwargs['subagents'] = [{**a, 'middleware': [*a.get('middleware', []), hook]}
            if a['name'] == 'writer' else a for a in kwargs['subagents']]
        return original_builder(*args, **kwargs)

    runtime, error = None, None
    try:
        with patch.object(deep_runtime, 'create_deep_agent', build):
            runtime = await deep_runtime.run_report(ws, factory)
    except Exception as exc:
        error = {'type': type(exc).__name__, 'message': str(exc)}
    finally:
        capture = {'fixture': fixture, 'runtime_result': runtime, 'raised_error': error,
            'phase_events': events, 'native_model_calls': calls, 'host_diagnostic_held': held,
            'parent': parent, 'oracle': observe_multi_adoption(ws, fixture, held, events),
            'initial_producer_is_recorded_fixture': False, 'host_completion_actions': False,
            'limits': ['Initial process request and Coordinator are scripted; output/consumer models come from the factory.',
                'Fake factory responses demonstrate mechanics only; a live factory is a fresh producer call.',
                'No retry or completion is added when the outer call/token budget ends.',
                'Full four-column/footnote inputs are one P04 slice, not its missing-material or Criterion contrasts.']}
        dump(folder / 'capture.json', capture)
        dump(folder / 'saved-state.json', {'objects': cs.list_objects(), 'events': ws.store.events()})
    return capture
