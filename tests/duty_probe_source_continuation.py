"""P03 controlled first search, then native model decisions over actual tools.

Only the parent and initial query are scripted. Subsequent Writer decisions use
the injected factory and unchanged handler. No provider, second loop, repair,
search replacement, or semantic acceptance is implemented here.
"""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch

from langchain.agents.middleware.types import AgentMiddleware, ModelResponse
from langchain_core.messages import AIMessage, ToolMessage, messages_to_dict

from duty_probe_agent_decisions import dump, traced_model
from report_agent import deep_runtime
from report_agent.catalog import Catalog
from report_agent.content_store import ContentStore
from test_agent_duty_trace_cases import action, result_value, tool_reply
from test_decision_data import activate
from test_deep_runtime import Driver


CASES = {'literal-hit': 'strong weathering', 'synonym-no-hit': 'decomposed rock'}
GOAL = ('Locate the original geology description and its complete applicability condition for Site S, '
        'using the project source material. Return source identity and location with any limits in '
        'what has been examined. Do not assess engineering acceptance or write a report.')
GEOLOGY = [
    {'ordinal': 0, 'locator': 'G-17 frozen block 0',
     'text': 'G-17 / Site S: the material is described as strong weathering. Applicability continues in the next frozen block.'},
    {'ordinal': 1, 'locator': 'G-17 frozen block 1',
     'text': 'APPLICABILITY: this description applies only to the upper 2 m at Site S; it does not establish the condition of the whole slope.'},
]
MAINTENANCE = [
    {'ordinal': 0, 'locator': 'M-02 frozen block 0',
     'text': 'Weathered fragments were noted at Site T. This maintenance observation is not the G-17 geology record.'},
]


def source_rows(ws):
    with ws.store.connect() as db:
        return [list(r) for r in db.execute(
            'SELECT source_id,ordinal,locator,text FROM source_blocks ORDER BY source_id,ordinal')]


def prepare_source_fixture(ws, case):
    query = CASES[case]
    sources = [
        {'id': 'geo-g17', 'title': 'Synthetic G-17 geology record for Site S',
         'content': '\n'.join(b['text'] for b in GEOLOGY), 'coverage': 'complete'},
        {'id': 'maintenance-m02', 'title': 'Synthetic M-02 maintenance note for Site T',
         'content': '\n'.join(b['text'] for b in MAINTENANCE), 'coverage': 'complete'},
    ]
    ws.store.set('manifest', {**ws.store.manifest, 'goal': GOAL, 'sources': sources})
    catalog = Catalog(ws.store)
    # Independent frozen-block fixture, as in existing P03 tests; no PDF page
    # or semantic-index claim. This workspace is a fresh synthetic test project.
    with ws.store.connect() as db:
        db.execute('DELETE FROM source_blocks')
        for source_id, blocks in [('geo-g17', GEOLOGY), ('maintenance-m02', MAINTENANCE)]:
            db.executemany('INSERT INTO source_blocks VALUES (?,?,?,?)',
                [(source_id, b['ordinal'], b['locator'], b['text']) for b in blocks])
    cs = ContentStore(ws.store)
    activate(ws)
    return {'case': case, 'query': query, 'goal': GOAL,
        'catalog_metadata': deepcopy(catalog.metadata()), 'original_sources': deepcopy(catalog.sources()),
        'original_source_rows': source_rows(ws), 'expected_geology_blocks': deepcopy(GEOLOGY),
        'initial_content_objects': deepcopy(cs.list_objects()),
        'task_description': GOAL + '\nCurrent project source catalog:\n' + json.dumps(catalog.metadata(), ensure_ascii=False)}


class InitialLiteralSearch(AgentMiddleware):
    """One explicit fake action through native ToolNode; then the real handler."""
    def __init__(self, query, events):
        self.query, self.events, self.started = query, events, False

    async def awrap_model_call(self, request, handler):
        if not self.started:
            self.started = True
            response = action('search_sources', 'initial-literal-search', query=self.query, offset=0, limit=1)
            self.events.append({'phase': 'explicit_fake_initial_search',
                'request_messages': messages_to_dict(request.messages), 'response': response.model_dump()})
            return ModelResponse(result=[response])
        event = {'phase': 'native_writer_handler', 'request_messages': messages_to_dict(request.messages),
            'actual_tool_returns': [m.model_dump() for m in request.messages if isinstance(m, ToolMessage)]}
        self.events.append(event)
        result = await handler(request)
        event['response'] = messages_to_dict(result.result)
        return result


def observe_source_result(ws, fixture, events):
    """Observe exact supplied blocks; never grade natural-language truth here."""
    consumer = [e for e in events if e['phase'] == 'native_writer_handler']
    tail = fixture['expected_geology_blocks'][1]['text']
    setup = next((e for e in events if e['phase'] == 'explicit_fake_initial_search'), {})
    setup_tail = tail in json.dumps(setup.get('request_messages', []), ensure_ascii=False)
    first_tail = tail in json.dumps(consumer[0]['request_messages'], ensure_ascii=False) if consumer else None
    reads, searches, complete_inputs = {}, {}, []
    for index, event in enumerate(consumer):
        blocks = {}
        for raw in event['actual_tool_returns']:
            message = ToolMessage.model_validate(raw)
            if message.name not in {'read_source_page', 'search_sources'}:
                continue
            value = result_value(message)
            entry = {'message': raw, 'actual_value': value}
            if message.name == 'search_sources':
                searches[message.tool_call_id] = entry
            else:
                reads[message.tool_call_id] = entry
                if value.get('source', {}).get('id') == 'geo-g17':
                    blocks.update({b['ordinal']: b for b in value.get('blocks', [])})
        if all(blocks.get(b['ordinal']) == b for b in fixture['expected_geology_blocks']):
            complete_inputs.append(index)
    sources_unchanged = (Catalog(ws.store).sources() == fixture['original_sources']
                         and source_rows(ws) == fixture['original_source_rows'])
    if setup_tail or first_tail:
        status = 'fixture_tail_already_visible'
    elif complete_inputs and sources_unchanged:
        status = 'selected_blocks_observed'
    else:
        status = 'not_observed'
    return {'status': status, 'semantic_status': 'needs_semantic_review',
        'source_originals_unchanged': sources_unchanged,
        'setup_tail_visible': setup_tail, 'first_consumer_tail_visible': first_tail,
        'actual_source_reads': list(reads.values()), 'actual_searches': list(searches.values()),
        'complete_block_input_indexes': complete_inputs,
        'limits': ['Only actual selected original blocks/locators supplied to a later Writer input are counted.',
            'Not observed is not a claim that the source is absent or that retaining uncertainty is a business failure.',
            'Final statements require Neo semantic review; no wording heuristic decides their truth.',
            'No PDF visual, engineering, whole-report or autonomous first-query acceptance.']}


async def capture_source_continuation(ws, case, folder, model_factory):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    fixture = prepare_source_fixture(ws, case)
    dump(folder / 'fixture.json', fixture)
    events, calls, models, parent = [], [], {}, {}
    hook = InitialLiteralSearch(fixture['query'], events)

    def receive_parent(messages):
        parent['task_return'] = tool_reply(messages, 'source-reading-task').model_dump()
        return AIMessage(content='Source retrieval outcome received; no semantic acceptance added by the parent fixture.')

    coordinator = Driver(coordinator=[action('task', 'source-reading-task', subagent_type='writer',
        description=fixture['task_description']), receive_parent])

    def factory(role):
        if role == 'coordinator':
            return coordinator(role)
        if role not in models:
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
        capture = {'case': case, 'fixture': fixture, 'runtime_result': runtime, 'raised_error': error,
            'phase_events': events, 'native_model_calls': calls, 'parent': parent,
            'parent_fake_calls': [{'role': r, 'step': n, 'messages': messages_to_dict(m)}
                                  for r, n, m in coordinator.calls],
            'oracle': observe_source_result(ws, fixture, events),
            'final_content_objects': ContentStore(ws.store).list_objects(),
            'limits': ['Initial query and Coordinator are scripted; subsequent models come from the supplied factory.',
                'Only a native execution harness. No provider, auto retry, corrected answer, or substitute final action.']}
        dump(folder / 'capture.json', capture)
    return capture
