"""W03 native Writer comparison seam; no replacement agent loop or repair.

The parent and two initial source reads are explicit fake preparation. All
subsequent Writer and independent text calls use the supplied original factory.
Only observations are captured: neither a particular tool nor a final answer is
injected after preparation, and no report/review/snapshot is manufactured.
"""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch

from langchain.agents.middleware.types import AgentMiddleware, ModelResponse
from langchain_core.messages import AIMessage, messages_to_dict

from duty_probe_agent_decisions import dump, traced_model
from duty_probe_source_continuation import source_rows
from duty_probe_writer_delivery_outcome import DeliveryParent
from report_agent import deep_runtime
from report_agent.catalog import Catalog
from report_agent.content_store import ContentStore
from report_agent.hierarchical_tools import actor_for
from report_agent.task_context import exact_task_context
from test_decision_data import activate


RULE = 'Synthetic rule: class B permits a selected value from 75 to 100.'
FIELD = ('Synthetic field record: Site A is recorded as class B and its proposed value is 70. '
         'For Site B, neither a class nor a selected value is established in this record.')
GOAL = ('Provide the parent with an independent, traceable comparison of the proposed field '
        'assessment and source rule for Site A and Site B. Distinguish supported, conflicting '
        'and unresolved relationships and state the examined-material limits. Do not change '
        'originals, write a report or claim engineering acceptance.')
QUESTION = ('Compare the Site A proposal and Site B evidence against the supplied rule. '
            'Identify supported, conflicting and unresolved relationships using the supplied locators.')


def prepare_writer_analysis_fixture(ws):
    sources = [{'id': 'analysis-rule', 'title': 'Synthetic comparison rule',
                'content': RULE, 'coverage': 'complete'},
               {'id': 'analysis-field', 'title': 'Synthetic field comparison record',
                'content': FIELD, 'coverage': 'complete'}]
    ws.store.set('manifest', {**ws.store.manifest, 'goal': GOAL, 'sources': sources})
    catalog = Catalog(ws.store)
    cs = ContentStore(ws.store)
    inputs = cs.import_inputs(actor_for('coordinator'), 'writer-analysis-originals',
                              [s['id'] for s in sources])['result']
    activate(ws)
    task_description = GOAL + '\nProject source catalog:\n' + json.dumps(catalog.metadata(), ensure_ascii=False)
    return {'case': 'writer-independent-analysis', 'goal': GOAL,
            'task_call': {'name': 'task', 'id': 'writer-analysis-task', 'type': 'tool_call',
                          'args': {'subagent_type': 'writer', 'description': task_description}},
            'inputs': inputs, 'originals': deepcopy(cs.list_objects()),
            'catalog_sources': deepcopy(catalog.sources()), 'source_rows': source_rows(ws),
            'source_pages': {s['id']: deepcopy(catalog.read(s['id'], 0, 1)) for s in sources},
            'limits': ['SourceArtifact Ref/version is retained independently, not added to analysis inputs.',
                       'Source blocks and digests establish correspondence in this frozen fixture; '
                       'this does not prove the analysis interface forces a unique typed source version.']}


class AnalysisOriginalReads(AgentMiddleware):
    def __init__(self, ws, phases):
        self.ws, self.phases, self.started = ws, phases, False

    async def awrap_model_call(self, request, handler):
        event = {'phase': 'unchanged_writer_handler' if self.started else 'explicit_fake_original_reads',
                 'server_context': deepcopy(exact_task_context(self.ws, 'writer')),
                 'messages': messages_to_dict(request.messages)}
        self.phases.append(event)
        if not self.started:
            self.started = True
            response = AIMessage(content='', tool_calls=[
                {'name': 'read_source_page', 'type': 'tool_call', 'id': 'analysis-read-' + source_id,
                 'args': {'source_id': source_id, 'offset': 0, 'limit': 1}}
                for source_id in ['analysis-rule', 'analysis-field']])
            event['response'] = response.model_dump()
            return ModelResponse(result=[response])
        result = await handler(request)
        event['response'] = messages_to_dict(result.result)
        return result


async def capture_writer_analysis(ws, folder, model_factory):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    fixture = prepare_writer_analysis_fixture(ws)
    dump(folder / 'fixture.json', fixture)
    cs, calls, phases, parents, models = ContentStore(ws.store), [], [], [], {}
    parent, reads = DeliveryParent(fixture, parents), AnalysisOriginalReads(ws, phases)

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
        with patch.object(deep_runtime, 'create_deep_agent', build):
            runtime = await deep_runtime.run_report(ws, factory)
    except Exception as exc:
        error = {'type': type(exc).__name__, 'message': str(exc)}
    finally:
        capture = {'fixture': fixture, 'runtime': runtime, 'raised_error': error,
                   'phase_events': phases, 'native_model_calls': calls, 'fake_parent_events': parents,
                   'host_completed_consumer_actions': False,
                   'semantic_status': 'not_assessed_by_harness'}
        dump(folder / 'raw-capture.json', capture)
        try:
            with ws.store.connect() as db:
                receipts = [{'id': r[0], 'actor_id': r[1], 'data': json.loads(r[2])}
                            for r in db.execute('SELECT id,actor_id,data FROM content_observations')]
            capture.update(events=ws.store.events(), content_observations=receipts,
                content_objects=cs.list_objects(),
                originals_unchanged=all(cs.read(o['ref']) == o for o in fixture['originals']),
                source_rows_unchanged=source_rows(ws) == fixture['source_rows'],
                catalog_sources_unchanged=Catalog(ws.store).sources() == fixture['catalog_sources'])
        except Exception as exc:
            capture['observer_error'] = {'type': type(exc).__name__, 'message': str(exc)}
            raise
        finally:
            dump(folder / 'capture.json', capture)
    return capture
