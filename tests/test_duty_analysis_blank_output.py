"""Native output-boundary probes; retain failures before any application repair.

A blank independent response must not become a successful cached analysis. The
same exact question and selections are called twice to observe reuse, not to
retry a provider or repair the returned content. Fake outputs are not evidence
that a real model commonly emits whitespace or that engineering was accepted.
"""
from copy import deepcopy
import json
import os
from pathlib import Path

from langchain_core.messages import AIMessage, messages_to_dict
import pytest

from duty_probe_agent_decisions import dump
from report_agent.content_store import ContentStore
from test_agent_duty_trace_cases import action, result_value, tool_reply
from test_agent_result_delivery import run_role
from test_bounded_review import Model
from test_decision_data import activate
from test_hierarchical_content import seed
from test_task_supervision import ws, offline


QUESTION = 'Describe what the selected source establishes and what remains unresolved.'
FINDING = 'The selected rule establishes the class B interval. Actual site class remains unresolved.'
BLANK = ' \n\t '


def retained_analysis_state(ws):
    with ws.store.connect() as db:
        cached = [{'operation': r[0], 'data': json.loads(r[1])}
                  for r in db.execute('SELECT operation,data FROM analyses ORDER BY operation')]
        attempts = [{'key': r[0], 'data': json.loads(r[1])}
                    for r in db.execute("SELECT key,value FROM state WHERE key GLOB 'bounded_review_attempt:*' ORDER BY key")]
    return {'cached_analyses': cached, 'attempts': attempts, 'events': ws.store.events()}


@pytest.mark.parametrize('tool', ['analyze_text', 'analyze_evidence'])
@pytest.mark.parametrize('output', ['normal', 'blank'])
async def test_analysis_rejects_blank_before_completed_cache(ws, tmp_path, request, tool, output):
    cs, _, refs, snapshot, _ = seed(ws)
    activate(ws)
    originals = deepcopy(cs.list_objects())
    response = FINDING if output == 'normal' else BLANK
    model = Model(response)
    args = ({'source_id': 's', 'purpose': QUESTION, 'offset': 0, 'limit': 1}
            if tool == 'analyze_text' else
            {'question': QUESTION, 'source_selections': [{'source_id': 's', 'offset': 0, 'limit': 1}],
             'result_selections': []})
    root = Path(os.environ.get('DUTY_ANALYSIS_BLANK_EVIDENCE', str(tmp_path / 'evidence')))
    folder = root / request.node.name
    folder.mkdir(parents=True, exist_ok=True)
    observations, driver, execution_error = [], None, None

    def retain(messages, call_id):
        message = tool_reply(messages, call_id)
        observations.append({'call_id': call_id, 'actual_tool_message': message.model_dump(),
                             'consumer_messages': messages_to_dict(messages)})
        # Preserve the first response before querying derived cache/state views.
        dump(folder / (call_id + '-raw.json'), observations[-1])
        dump(folder / 'raw-observations.json', {'observations': observations,
             'independent_calls': model.calls, 'supplied_fake_content': response})
        try:
            observations[-1]['actual_value'] = result_value(message)
        except json.JSONDecodeError:
            if message.status != 'error':
                raise
            observations[-1]['actual_value'] = {'unparsed_native_error': message.content}
        observations[-1]['state_after_response'] = retained_analysis_state(ws)
        dump(folder / 'observations-with-state.json', observations)

    def first(messages):
        retain(messages, 'blank-first')
        return action(tool, 'blank-repeat-same-request', **args)

    def second(messages):
        retain(messages, 'blank-repeat-same-request')
        return AIMessage(content='Raw tool observations retained; no substantive or engineering acceptance.')

    try:
        driver = await run_role(ws, 'writer', [action(tool, 'blank-first', **args), first, second],
                                refs, snapshot, model)
    except Exception as exc:
        execution_error = {'type': type(exc).__name__, 'message': str(exc)}
        raise
    finally:
        raw = {'tool': tool, 'output': output, 'args': args, 'supplied_fake_content': response,
               'execution_error': execution_error, 'observations': observations,
               'independent_calls': model.calls, 'originals_before': originals,
               'native_role_calls': [{'role': role, 'step': step, 'messages': messages_to_dict(messages)}
                                     for role, step, messages in driver.calls] if driver else [],
               'fake_model_only': True, 'application_repair_applied': False}
        dump(folder / 'raw-capture.json', raw)
        try:
            raw['final_state'] = retained_analysis_state(ws)
            raw['originals_unchanged'] = all(cs.read(o['ref']) == o for o in originals)
        except Exception as exc:
            raw['observer_error'] = {'type': type(exc).__name__, 'message': str(exc)}
            raise
        finally:
            dump(folder / 'capture.json', raw)
    assert len(observations) == 2 and len(model.calls) == 1
    assert raw['originals_unchanged']
    completed = [e for e in raw['final_state']['events'] if e['kind'] == 'evidence_analysis_completed']
    reused = [e for e in raw['final_state']['events'] if e['kind'] == 'evidence_analysis_reused']
    if output == 'blank':
        assert 'EVIDENCE_ANALYSIS_EMPTY_RESPONSE' in observations[0]['actual_tool_message']['content'], \
            'BLANK_ANALYSIS_MUST_BE_REJECTED_BEFORE_SUCCESS'
        assert raw['final_state']['cached_analyses'] == [], 'BLANK_ANALYSIS_MUST_NOT_BE_CACHED'
        assert completed == [] and reused == [], 'BLANK_ANALYSIS_MUST_NOT_BE_COMPLETED_OR_REUSED'
        rejected = [e for e in raw['final_state']['events'] if e['kind'] == 'evidence_analysis_rejected_response']
        assert len(rejected) == 1 and rejected[0]['data']['content'] == BLANK
    else:
        first_value, second_value = [o['actual_value'] for o in observations]
        assert first_value['analysis'] == second_value['analysis'] == FINDING
        assert first_value['reused'] is False and second_value['reused'] is True
        assert first_value['operation'] == second_value['operation']
        assert len(completed) == len(reused) == len(raw['final_state']['cached_analyses']) == 1
        assert raw['final_state']['cached_analyses'][0]['data']['analysis'] == FINDING
