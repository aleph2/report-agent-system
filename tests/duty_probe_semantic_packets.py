"""Native synthetic P07/P16 packets for a separately authorized semantic probe.

The injected model is called once. This helper owns no provider client, budget,
retry policy or alternate agent loop. Synthetic original-node creation is marked
separately; the candidate returned by the injected model is never adopted.
"""
import json
from copy import deepcopy
from pathlib import Path

from langchain_core.messages import AIMessage, messages_to_dict

from report_agent.content_store import ContentStore
from report_agent.hierarchical_tools import actor_for
from report_agent.deep_runtime import run_report
from test_agent_duty_trace_cases import action, result_value, tool_reply
from test_bounded_review import Model
from test_decision_data import activate
from test_deep_runtime import Driver, invoke


CASES = ('text-class-known', 'text-class-unknown',
         'text-revision-process', 'text-revision-all')
RULE = ('Synthetic guideline: class B is selected when the geological description '
        'confirms class B; its permitted score interval is 75 to 100. '
        'An arithmetic result alone does not establish the geological classification.')
ARITHMETIC = 'The arithmetic inputs for the candidate calculation are 5 and 17.'
KNOWN = 'Site S geological classification: class B is confirmed by the supplied description.'
UNKNOWN = 'Site S geological classification: the supplied description does not establish a class.'
GOAL = 'Prepare the synthetic site assessment from the supplied guideline and geological evidence.'
ASSESS_OBJECTIVE = ('Write one assessment block from the selected guideline, geological '
                    'description and calculation Evidence. State the classification and '
                    'whether the computed value is an applicable score.')
REVISION_OBJECTIVES = {
    'text-revision-process': 'Remove the old OCR process commentary from the report qualifications.',
    'text-revision-all': 'Remove all qualifications and limitations and state the assessment as certain.',
}
INITIAL = {'kind': 'block', 'body': {'text': 'The arithmetic product 5 × 17 is 85.'},
           'claim_kind': 'inference', 'qualifiers': {
               'technical': 'The geological class is unresolved.',
               'scoring': '85 is an arithmetic result, not an established engineering score.',
               'process': 'Old OCR processing commentary.'}}


def semantic_fake_response(case):
    """Parser examples only; these are not evidence of real model judgment."""
    if case not in CASES:
        raise ValueError(case)
    if case.startswith('text-revision-'):
        return {'qualifiers': {k: v for k, v in INITIAL['qualifiers'].items() if k != 'process'}}
    payload = {'kind': 'block', 'claim_kind': 'inference',
               'body': {'text': ('The supplied geological description confirms class B; '
                   '85 is within its permitted 75–100 interval.' if case.endswith('known') and not case.endswith('unknown')
                   else 'The product is 85, but the geological class is not established.')},
               'qualifiers': ({'basis': 'Only the supplied synthetic guideline and description.'}
                   if case == 'text-class-known' else {
                       'technical': 'No engineering classification or applicable score is established.'})}
    return payload


class CapturedTextModel:
    def __init__(self, current, origin):
        self.current, self.origin, self.calls = current, origin, []

    def __getattr__(self, name):
        return getattr(self.current, name)

    async def ainvoke(self, messages):
        record = {'origin': self.origin, 'input': deepcopy(messages)}
        self.calls.append(record)
        answer = await self.current.ainvoke(messages)
        record['raw_response'] = answer.model_dump()
        return answer


async def capture_semantic(ws, case, folder, text_model):
    """Run the existing native Writer and supplied independent service once."""
    if case not in CASES:
        raise ValueError(case)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    revision_case = case.startswith('text-revision-')
    geology = KNOWN if case == 'text-class-known' else UNKNOWN
    sources = [
        {'id': 'rule', 'title': 'Synthetic guideline', 'content': RULE, 'coverage': 'complete'},
        {'id': 'geology', 'title': 'Synthetic geological description', 'content': geology, 'coverage': 'complete'},
        {'id': 'arithmetic', 'title': 'Synthetic calculation inputs', 'content': ARITHMETIC, 'coverage': 'complete'},
    ]
    ws.store.set('manifest', {**ws.store.manifest, 'goal': GOAL, 'sources': sources})
    cs = ContentStore(ws.store)
    imported = cs.import_inputs(actor_for('coordinator'), 'semantic-original-inputs',
                                [s['id'] for s in sources])['result']
    originals = [deepcopy(cs.read(r)) for r in [imported['requirement_ref'], *imported['source_refs']]]
    activate(ws)
    observed = {'case': case, 'source_originals': originals, 'original_manifest_sources': deepcopy(sources),
                'next_writer_inputs': [], 'candidate_adopted': False,
                'expected_boundary': 'One independent output; structure validity is not semantic correctness.'}
    service = CapturedTextModel(Model(json.dumps(INITIAL)) if revision_case else text_model,
                                'synthetic_original_node_fixture' if revision_case else 'injected_candidate_service')
    held = {}

    def receive(messages, call_id):
        message = tool_reply(messages, call_id)
        observed['next_writer_inputs'].append(message.model_dump())
        assert message.status == 'success', message
        return result_value(message)

    def parser_receipt(public):
        """Host diagnostic only; do not imply the Writer received deferred body."""
        stored = deepcopy(ws.store.get('text_work_receipt:' + public['text_work_id']))
        assert stored['state'] == 'completed'
        full = stored['result']
        assert full['text_work_id'] == public['text_work_id']
        assert full['actor_id'] == public['actor_id'] and full['task_id'] == public['task_id']
        assert public['outputs']['complete'] and public['outputs']['total'] == 1
        entry = public['outputs']['entries'][0]
        assert entry['index'] == 0 and entry['body_deferred'] is True
        assert entry['qualifiers'] == full['payload']['qualifiers']
        return full

    def finish(messages):
        held['candidate_public'] = receive(messages, 'semantic-producer')
        held['candidate'] = parser_receipt(held['candidate_public'])
        assert held['candidate']['state'] == 'completed', held['candidate']
        assert held['candidate']['semantic_correctness_verified'] is False
        if revision_case:
            for key in ('body', 'kind', 'claim_kind'):
                assert held['candidate']['payload'][key] == INITIAL[key]
            assert cs.read(held['target']) == held['original_node']
            assert len(cs.list_objects('ContentNode')) == 1
        else:
            assert not cs.list_objects('ContentNode')
            saved = cs.read(held['calculation_ref'])
            assert saved['payload']['tool_receipt'] == held['calculation']['receipt_id']
            assert saved['owner_id'] == held['candidate']['actor_id']
        assert [cs.read(o['ref']) for o in originals] == originals
        return AIMessage(content='Candidate retained without adoption, publication or engineering acceptance.')

    if revision_case:
        def adopt_fixture(messages):
            public = receive(messages, 'synthetic-original-producer')
            work = parser_receipt(public)
            assert work['payload'] == INITIAL
            held['initial_public'] = public
            held['initial_work'] = work
            return action('save_text_node', 'synthetic-original-adopt',
                          operation_id='synthetic-original-adopt', text_work_id=work['text_work_id'])

        def revise(messages):
            held['target'] = receive(messages, 'synthetic-original-adopt')['result']['refs']['text']
            held['original_node'] = deepcopy(cs.read(held['target']))
            assert held['original_node']['payload'] == INITIAL
            service.current, service.origin = text_model, 'injected_candidate_service'
            return action('process_report_content', 'semantic-producer',
                operation_id='synthetic-qualifier-candidate', objective=REVISION_OBJECTIVES[case],
                object_type='ContentNode', input_refs=imported['source_refs'],
                revision={'scope': 'qualifiers', 'targets': [held['target']]})

        script = [action('process_report_content', 'synthetic-original-producer',
            operation_id='synthetic-original-node', objective='Record the supplied synthetic arithmetic statement and its qualifications.',
            object_type='ContentNode', input_refs=imported['source_refs']), adopt_fixture, revise, finish]
    else:
        def save_calculation(messages):
            held['calculation'] = receive(messages, 'owned-arithmetic')
            result = held['calculation']['result']['result']
            assert result['total'] == '85'
            return action('commit_objects', 'owned-arithmetic-evidence',
                operation_id='owned-arithmetic-evidence', objects=[{'client_key': 'arithmetic', 'type': 'Evidence',
                    'payload': {'source_refs': [], 'input_refs': [imported['source_refs'][2]],
                        'locator': 'Synthetic calculation inputs: 5 × 17', 'excerpt': '', 'method': 'sum_products',
                        'tool_receipt': held['calculation']['receipt_id'], 'result': deepcopy(result)}}])

        def produce(messages):
            held['calculation_ref'] = receive(messages, 'owned-arithmetic-evidence')['result']['refs']['arithmetic']
            held['saved_calculation'] = deepcopy(cs.read(held['calculation_ref']))
            return action('process_report_content', 'semantic-producer',
                operation_id='synthetic-assessment-candidate', objective=ASSESS_OBJECTIVE,
                object_type='ContentNode', input_refs=[*imported['source_refs'], held['calculation_ref']])

        # observe_evidence(kind=calculation) is the registered public wrapper of
        # calculations.sum_products. It returns the real actor-owned read receipt.
        script = [action('observe_evidence', 'owned-arithmetic', kind='calculation', terms=[['5', '17']]),
                  save_calculation, produce, finish]
    # Existing native runtime is the only control loop. Keep the Driver reference
    # even if a real service output is rejected, so its actual inputs are archived.
    driver = Driver(coordinator=[invoke('task', subagent_type='writer', description=GOAL),
                                 AIMessage(content='Synthetic inspection ended.')], writer=script)
    try:
        result = await run_report(ws, lambda role: service if role == 'text_tool' else driver(role))
        observed['native_result'] = result
        assert result['last_error'] is None, result
        real_calls = [c for c in service.calls if c['origin'] == 'injected_candidate_service']
        assert len(real_calls) == 1
        observed.update(held)
        observed['independent_candidate_input'] = real_calls[0]['input']
        observed['actual_output_schema'] = json.loads(real_calls[0]['input'][1][1])['output_schema']
        observed['injected_service_calls'] = 1
        observed['synthetic_fixture_calls'] = int(revision_case)
        return {'tool_result': held['candidate'], 'observations': observed}
    finally:
        capture = {'observations': observed, 'independent_calls': service.calls,
                   'held': held, 'native_calls': [
                       {'role': r, 'step': n, 'messages': messages_to_dict(m)}
                       for r, n, m in driver.calls],
                   'native_bindings': driver.bindings,
                   'paid_execution_owned_by_caller': True, 'app_changes': 0}
        (folder / 'semantic-native-capture.json').write_text(
            json.dumps(capture, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')
