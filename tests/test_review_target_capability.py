"""Offline admission/execution regressions; scripted judgments are not report acceptance."""
import json
from copy import deepcopy
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from report_agent import deep_runtime
from report_agent.bounded_review import perform_review
from report_agent.content_tasks import delegated_task, normalize_review_requirements
from report_agent.errors import ActionRejected
from report_agent.hierarchical_tools import actor_for
from report_agent.store import encode
from report_agent.task_supervision import review_readiness, readiness_metadata, reconcile, validate_requirements
from report_agent.task_supervision import content_review_capability_issue
from test_bounded_review import Model, review_call
from test_deep_runtime import Driver, invoke, observation
from test_hierarchical_content import seed
from test_task_supervision import ws, offline


def bounded(ws):
    ws.store.set('manifest', {**ws.store.manifest, 'review_execution_mode': 'bounded-tool-v1'})


def retain_native_evidence(ws, driver, name, **extra):
    """Saved actual scripted native I/O, not a claim about a live model or report quality."""
    path = ws.store.root / (name + '-native-evidence.json')
    path.write_text(json.dumps({'calls': [{'role': role, 'step': step,
        'messages': [m.model_dump() for m in messages]} for role, step, messages in driver.calls],
        'bound_tools': driver.bindings, 'factory_constructed': driver.created, **extra},
        ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    return path


@pytest.mark.parametrize('context_policy', ['plain', 'managed', 'reference'])
async def test_native_snapshot_target_rejected_before_creating_reviewer(ws, context_policy, record_property):
    cs, _, refs, snapshot, _ = seed(ws)
    bounded(ws)
    if context_policy != 'plain':
        ws.store.set('context_policy', 'stateful-tools-v1')
    if context_policy == 'reference':
        ws.store.set('manifest', {**ws.store.manifest, 'decision_data_policy': 'reference-data-v1'})
    call = review_call(snapshot, refs)
    call['args']['review_requirements'][0]['target_ref'] = snapshot
    original = deepcopy(call)
    requirements = normalize_review_requirements(call['args']['review_requirements'])
    readiness = validate_requirements(cs, snapshot, requirements)
    assert not readiness['execution_ready']
    problem = next(i for i in readiness['issues'] if i['kind'] == 'capability')
    assert problem['ref'] == snapshot and problem['path'] == '/review_requirements/0/target_ref'
    assert problem['scope_id'] == 'rule-comparison' and problem['supported_target_types'] == ['ContentNode']
    assert readiness_metadata(readiness)['issues']['entries'][0]['supported_target_types'] == ['ContentNode']

    def see_error(messages):
        packet = json.loads(messages[-1].content)
        error = packet.get('metadata', packet)
        assert error['code'] == 'BOUNDED_TOOL_SUPPORTS_NODE_CONTENT_ONLY'
        assert snapshot['id'] in messages[-1].content and 'ContentNode' in messages[-1].content
        return AIMessage(content='Correct the task binding; no review was executed.')

    driver = Driver(coordinator=[AIMessage(content='', tool_calls=[call]), see_error])
    result = await deep_runtime.run_report(ws, driver)
    assert result['last_error'] is None, result
    assert not cs.list_objects('DelegatedTask') and not cs.list_objects('ReviewRecord')
    assert {role for role, _, _ in driver.calls} == {'coordinator'}
    assert call == original
    path = retain_native_evidence(ws, driver, 'admission-'+context_policy,
        actual_readiness=readiness, original_call=original,
        saved_delegated_tasks=cs.list_objects('DelegatedTask'), saved_reviews=cs.list_objects('ReviewRecord'))
    record_property('native_evidence_path', str(path))
    record_property('actual_context_policy', context_policy)


@pytest.mark.parametrize('kind', ['export', 'render'])
def test_node_target_wrong_assessment_kind_diagnostic_identifies_route(kind):
    problem = content_review_capability_issue({'assessment_kind':kind,'scope_id':'route',
        'target_ref':{'type':'ContentNode','id':'existing-node','version':1}})
    assert problem['code']=='BOUNDED_TOOL_SUPPORTS_NODE_CONTENT_ONLY'
    assert ('assessment_kind='+kind) in problem['reason']
    assert 'requires assessment_kind=content' in problem['reason']
    assert 'type ContentNode is unsupported' not in problem['reason']


async def test_saved_mixed_task_replay_and_resume_allow_only_selected_supported_scope(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    source = next(r for r in cs.read(snapshot)['payload']['refs'] if r['type'] == 'SourceArtifact')
    call = review_call(snapshot, refs, reads=[source])
    unsupported = deepcopy(call['args']['review_requirements'][0])
    unsupported.update(scope_id='whole-snapshot', target_ref=snapshot)
    call['args']['review_requirements'].append(unsupported)
    # Preserve a historically admitted task before enabling the bounded route.
    with delegated_task(ws, 'coordinator', call) as (_, actor):
        task_id = actor.task_id
    original_task = deepcopy(cs.list_objects('DelegatedTask'))
    original_receipt = deepcopy(cs.receipt(actor_for('coordinator'), 'delegate:' + call['id']))
    bounded(ws)
    with delegated_task(ws, 'coordinator', call) as (_, actor):
        assert actor.task_id == task_id
    resumed = deepcopy(call)
    resumed['id'] = 'resume-mixed'
    resumed['args']['resume_content_task_id'] = task_id
    with delegated_task(ws, 'coordinator', resumed) as (_, actor):
        task = cs.read(original_task[0]['ref'])['payload']
        readiness = validate_requirements(cs, snapshot, task['review_requirements'])
        assert not readiness['execution_ready']
        assert all(i['scope_id'] == 'whole-snapshot' for i in readiness['issues'])
        model = Model()
        await perform_review(ws, actor, model, 'legal-selected', ['rule-comparison'])
        assert len(model.calls) == 1
        state = reconcile(cs, task_id)
        assert not state['execution_complete']
        assert [r['requirement']['scope_id'] for r in state['remaining']] == ['whole-snapshot']
        refused = Model()
        before = len(cs.list_objects('ReviewRecord'))
        with pytest.raises(ActionRejected, match='BOUNDED_TOOL_SUPPORTS_NODE_CONTENT_ONLY:') as caught:
            await perform_review(ws, actor, refused, 'unsupported-selected', ['whole-snapshot'])
        details = json.loads(str(caught.value).split(': ', 1)[1])
        assert details['target_ref'] == snapshot and details['model_called'] is False
        assert 'Coordinator' in details['correction'] and 'operation_id' in details['correction']
        assert not refused.calls and len(cs.list_objects('ReviewRecord')) == before
    assert cs.list_objects('DelegatedTask') == original_task
    assert cs.receipt(actor_for('coordinator'), 'delegate:' + call['id']) == original_receipt


@pytest.mark.parametrize('missing,customer_instruction', [(None,None), ('body',None), ('pool',None),
    (None,'当设计与地勘有出入的时候，以设计为主，当设计资料缺失时，用地勘数据补充。同时需要能核对出地勘和设计不一致的地方。')])
async def test_root_target_retains_seven_original_checks_sources_and_explicit_subtree(ws, missing, customer_instruction, record_property):
    cs, _, refs, snapshot, _ = seed(ws)
    if missing != 'pool':
        bounded(ws)
    instruction = None
    if customer_instruction:
        from report_agent.prompt_instructions import configure_report, save_instruction, release_instruction
        ws.store.set('context_policy', 'stateful-tools-v1')
        configure_report(ws.store, 'fixture-report')
        instruction = save_instruction(ws.store, {'id':'customer-scope', 'topic':'customer-source-precedence',
            'scope':'report', 'report_id':'fixture-report', 'roles':['coordinator','writer','reviewer','layout'],
            'text':customer_instruction, 'source_decision':'Direct user text, protocol fixture only'})
        release_instruction(ws.store, 'customer-scope', 1, expected_active=None, reason='Fixture operator release')
    source = next(r for r in cs.read(snapshot)['payload']['refs'] if r['type'] == 'SourceArtifact')
    checks = json.loads(Path(__file__).with_name('fixtures').joinpath('original_review_seven_checks.json').read_text(encoding='utf-8'))
    call = review_call(snapshot, refs)
    requirements = []
    for scope, questions in checks.items():
        requirements.append({'scope_id': scope, 'target_ref': refs['root'], 'criterion_ref': refs['k'],
            'assessment_kind': 'content', 'required_checks': questions, 'required_read_refs': [],
            'material_refs': [] if missing == 'pool' else [refs['claim']],
            'required_materials': [{'requirement_index': i, 'purpose': question,
                'refs': [refs['root'], source]} for i, question in enumerate(questions)],
            'content_check_scopes': [{'requirement_index': i, 'node_ref': refs['root'],
                'kind': 'subtree_bodies'} for i in range(len(questions))]})
    call['args']['review_requirements'] = requirements
    call['args']['supervision_plugin'] = None
    original = deepcopy(requirements)
    if missing == 'pool':
        # Historical saved tasks still expose their execution gap; fresh tasks
        # with this impossible extent are covered by the admission regression.
        with delegated_task(ws, 'coordinator', call):
            pass
        bounded(ws)

    class SevenChecks(Model):
        async def ainvoke(self, messages):
            return self.answer(json.loads(messages[1][1]))

        def answer(self, packet):
            self.calls.append(packet)
            if instruction:
                supplied = packet['commission']['scoped_instructions']
                assert supplied['effective'] == [instruction] and not supplied['conflicts']
                assert supplied['effective'][0]['payload']['text'] == customer_instruction
            else:
                assert 'scoped_instructions' not in packet['commission']
            assert {r['scope_id']: r['required_checks'] for r in packet['assignment']['review_requirements']} == checks
            evidence = packet['evidence']
            assert any(e.get('object', {}).get('ref') == source and
                       e['object']['payload']['content'] == 'Class B permits 75 to 100.' for e in evidence)
            assert any(e.get('selection', {}).get('ref') == refs['claim'] and e['complete_body_selection'] for e in evidence)
            structure = next(e['structure'] for e in evidence if e['kind'] == 'snapshot_structure')
            assert structure['inventory_complete'] and not structure['missing_body_extents']
            observations = [{'evidence_index': i, 'locator': 'Exact supplied protocol fixture',
                'observation': encode(e)} for i, e in enumerate(evidence)]
            indexes = list(range(len(observations)))
            return AIMessage(content=json.dumps({'items': [{
                'scope_id': scope, 'checked_requirement_indexes': list(range(len(questions))),
                'execution_state': 'completed', 'verdict': 'undetermined', 'observations': observations,
                'check_results': [{'requirement_index': i, 'execution_state': 'completed',
                    'result': 'Protocol input verified; synthetic evidence cannot establish this real engineering requirement.',
                    'observation_indexes': indexes, 'remaining': ''} for i in range(len(questions))],
                'coverage': {'checked': questions, 'unchecked': [], 'blocked': [],
                    'basis': 'Exact seven check texts with explicit fixture subtree and independent source.'},
                'reason': 'Offline interface regression, not engineering acceptance.', 'findings': []
            } for scope, questions in checks.items()]}))

    model, seen = SevenChecks(), {}
    def finish(messages):
        seen['result'] = observation(messages, 'perform_assigned_review')
        return AIMessage(content='Exact scope result retained; no global acceptance.')
    driver = Driver(coordinator=[AIMessage(content='', tool_calls=[call]),
        AIMessage(content='Review task returned with actual evidence and gaps.')],
        reviewer=[invoke('perform_assigned_review', operation_id='seven-checks', scope_ids=list(checks),
            source_selections=[], content_selections=[] if missing else [{'ref': refs['claim']}]), finish],
        text_tool=[lambda messages: model.answer(json.loads(messages[-1].content))])
    status = await deep_runtime.run_report(ws, driver)
    assert status['last_error'] is None, status
    if missing:
        assert seen['result']['code'] == 'REVIEW_REQUIRED_BODIES_NOT_SUPPLIED'
        assert seen['result']['model_called'] is False and not model.calls
        assert 'text_tool' not in {role for role, _, _ in driver.calls}
        assert not cs.list_objects('ReviewRecord')
    else:
        assert len(model.calls) == 1
        review = cs.list_objects('ReviewRecord')[0]
        assert [len(i['check_results']) for i in review['payload']['items']] == [4, 3]
        assert all(i['verdict'] == 'undetermined' for i in review['payload']['items'])
        assert reconcile(cs, review['task_id'])['execution_complete']
    assert cs.list_objects('DelegatedTask')[0]['payload']['review_requirements'] == normalize_review_requirements(original)
    assert requirements == original
    path = retain_native_evidence(ws, driver, 'seven-checks-'+str(missing),
        original_seven_checks=checks, actual_checker_packets=model.calls,
        public_tool_result=seen['result'], saved_tasks=cs.list_objects('DelegatedTask'),
        saved_reviews=cs.list_objects('ReviewRecord'))
    record_property('native_evidence_path', str(path))
    record_property('checker_call_count', len(model.calls))
