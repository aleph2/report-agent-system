"""Native Learner null/default parsing and exact project-fact adoption.

An analysis is not verified project truth. All candidates stay scoped/inactive;
this probe neither runs a learning job to completion nor publishes guidance.
"""
from copy import deepcopy
import json

from langchain_core.messages import AIMessage, messages_to_dict
import pytest

from duty_probe_agent_decisions import dump
from report_agent.learning_runtime import build_optimizer
from report_agent.learning_text_work import LearningAnalysis
from report_agent.store import digest, encode
from test_agent_duty_trace_cases import action
from test_bounded_review import Model
from test_deep_runtime import Driver
from test_duty_contract_default_siblings import evidence_folder, retain, schema_errors
from test_learning_text_work import case
from test_task_supervision import offline


@pytest.mark.parametrize('variant', ['explicit-null', 'omit-default-null', 'exact-fact', 'changed-conditions'])
async def test_native_learner_default_and_fact_integrity(case, tmp_path, request, variant):
    ws, library, scope, feedback = case
    original_feedback = deepcopy(library.feedback_items(scope))
    original_job = deepcopy(ws.store.get('learning_job'))
    fact = {'title': 'Located synthetic rule', 'strategy': 'B permits 75–100.',
            'conditions': 'Only the supplied synthetic rule; actual field class is unresolved.'}
    findings = 'The selected rule gives the class B interval; it does not establish the actual field class.'
    payload = {'findings': findings}
    if variant != 'omit-default-null':
        payload['project_fact'] = fact if variant in {'exact-fact', 'changed-conditions'} else None
    raw_response = json.dumps(payload)
    model, folder = Model(raw_response), evidence_folder(tmp_path, request)
    first_args = {'question': 'Compare the selected original rule and retain factual limits.',
                  'feedback_selections': [{'feedback_id': feedback['id'], 'field': 'evidence'}]}
    capture = {'variant': variant, 'raw_fake_response': raw_response, 'analysis_arguments': first_args,
               'feedback_before': original_feedback, 'job_before': original_job,
               'scope': {'customer': scope.customer, 'project': scope.project}}

    def propose(messages):
        value = retain(folder, capture, messages, 'learner-analysis')
        capture['public_analysis'] = deepcopy(value)
        capture['typed_analysis_before'] = deepcopy(ws.store.get('learning_analysis:' + value['analysis_id']))
        # These are explicit fake agent choices, not values recovered from the private receipt.
        proposed = deepcopy(value['payload']['project_fact'] or fact)
        if variant == 'changed-conditions':
            proposed['conditions'] = 'Applies to every project without the supplied-evidence limitation.'
        args = {'feedback_ids': [feedback['id']], 'kind': 'project_fact', **proposed,
                'verification': 'Compare with the selected synthetic original; not accepted or released.',
                'analysis_id': value['analysis_id']}
        capture['proposal_arguments'] = deepcopy(args)
        dump(folder / 'proposal-arguments.json', args)
        return action('propose_experience', 'learner-propose', **args)

    final_text = 'Synthetic contract test ended; no verified fact, completed learning job or published guidance claimed.'

    def finish(messages):
        retain(folder, capture, messages, 'learner-propose')
        return AIMessage(content=final_text)

    driver = Driver(optimizer=[action('analyze_learning_material', 'learner-analysis', **first_args), propose, finish])
    try:
        result = await build_optimizer(ws, driver('optimizer'), text_model=model).ainvoke(
            {'messages': [('user', 'Investigate only this isolated synthetic feedback; do not publish.')]},
            config={'recursion_limit': 12})
        capture['final_messages'] = messages_to_dict(result['messages'])
        capture['final_text'] = result['messages'][-1].content
        packet = json.loads(model.calls[0][1][1])
        tools = {t['name']: t['parameters'] for t in driver.bindings['optimizer'][-1]}
        capture.update(independent_packet=packet, actual_schemas=tools,
            analysis_schema_errors=schema_errors(tools['analyze_learning_material'], first_args),
            proposal_schema_errors=schema_errors(tools['propose_experience'], capture['proposal_arguments']),
            output_schema_errors=schema_errors(packet['output_schema'], payload),
            normalized_output=LearningAnalysis.model_validate(payload).model_dump())
    except Exception as exc:
        capture['execution_error'] = {'type': type(exc).__name__, 'message': str(exc)}
        raise
    finally:
        capture.update(fake_models_only=True, application_repair_applied=False,
            independent_calls=model.calls,
            role_calls=[{'role': r, 'step': s, 'messages': messages_to_dict(m)} for r, s, m in driver.calls],
            registered_bindings=driver.bindings)
        dump(folder / 'raw-capture.json', capture)
        try:
            analysis_id = capture.get('public_analysis', {}).get('analysis_id')
            capture.update(candidates=library.list_versions(scope), active=library.search(scope),
                feedback_after=library.feedback_items(scope), job_after=ws.store.get('learning_job'),
                typed_analysis_after=ws.store.get('learning_analysis:' + analysis_id) if analysis_id else None)
        except Exception as exc:
            capture['observer_error'] = {'type': type(exc).__name__, 'message': str(exc)}
            raise
        finally:
            dump(folder / 'capture.json', capture)

    assert len(model.calls) == 1 and len(driver.calls) == 3
    assert capture['analysis_schema_errors'] == capture['proposal_schema_errors'] == capture['output_schema_errors'] == []
    assert capture['final_text'] == final_text
    assert capture['feedback_after'] == original_feedback and capture['job_after'] == original_job
    assert capture['public_analysis']['payload'] == capture['normalized_output']
    assert capture['public_analysis']['fact_correctness_verified'] is False
    saved = capture['typed_analysis_after']
    assert saved == capture['typed_analysis_before']
    assert saved['scope'] == capture['scope'] and saved['job_id'] == original_job['id']
    assert saved['feedback_ids'] == [feedback['id']]
    assert saved['payload'] == capture['normalized_output']
    assert capture['independent_packet']['scope'] == capture['scope']
    assert capture['independent_packet']['job_id'] == original_job['id']
    assert capture['independent_packet']['question'] == first_args['question']
    selected, = capture['independent_packet']['evidence']
    assert selected['selection'] == {'feedback_id': feedback['id'], 'field': 'evidence', 'offset': 0, 'characters': 6000}
    assert selected['total_characters'] == len(encode(feedback['evidence']))
    assert selected['original_digest'] == digest(feedback['evidence'])
    assert capture['independent_packet']['evidence'][0]['text'] == json.dumps(feedback['evidence'], ensure_ascii=False, sort_keys=True)
    assert capture['active'] == []
    if variant == 'exact-fact':
        candidate, = capture['candidates']
        assert candidate['kind'] == 'project_fact' and candidate['active'] is False
        assert {k: candidate[k] for k in fact} == fact
        assert candidate['customer'] == scope.customer and candidate['project'] == scope.project
        assert candidate['feedback_ids'] == [feedback['id']]
    else:
        assert capture['candidates'] == []
        message = capture['observed']['learner-propose']['message']
        assert message['status'] == 'error' and 'PROJECT_FACT_ANALYSIS_OUTPUT_CHANGED' in message['content']
    if variant in {'explicit-null', 'omit-default-null'}:
        assert saved['payload']['project_fact'] is None
