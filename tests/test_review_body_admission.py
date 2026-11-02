"""Exact topology/permission regression; no semantic report-quality claims."""
import json
from copy import deepcopy
import pytest

from langchain_core.messages import AIMessage

from report_agent import deep_runtime
from report_agent.content_tasks import delegated_task, normalize_review_requirements
from report_agent.review_input import review_material_context
from report_agent.task_supervision import review_readiness, readiness_metadata
from test_bounded_review import Model, review_call
from test_deep_runtime import Driver, invoke
from test_hierarchical_content import seed
from test_review_input_correctness import extent_call
from test_review_target_capability import bounded, retain_native_evidence
from test_task_supervision import ws, offline


def tree52(ws):
    cs, actor, refs, _, all_refs = seed(ws)
    objects = []
    for i in range(50):
        objects.extend([
            {'client_key':f'n{i}', 'type':'ContentNode', 'payload':{'kind':'block',
                'body':{'text':f'Fixture section {i}'}, 'qualifiers':{}, 'claim_kind':'structure'}},
            {'client_key':f'e{i}', 'type':'Relation', 'payload':{
                'subject_ref':refs['root'], 'object_ref':{'client_key':f'n{i}'},
                'predicate':'contains', 'position':i+1, 'provenance_kind':'adopted_during_generation'}}])
    objects.append({'client_key':'outside', 'type':'ContentNode', 'payload':{
        'kind':'block', 'body':{'text':'Separate workbook placeholder'},
        'qualifiers':{}, 'claim_kind':'structure'}})
    added = cs.commit(actor, 'tree52', objects)['result']['refs']
    snapshot = cs.freeze(actor, 'tree52-snapshot', refs['root'],
        [*all_refs, *added.values()], workbook_refs=[added['outside']])['result']['snapshot_ref']
    call = extent_call(snapshot, refs)
    req = call['args']['review_requirements'][0]
    # Root + claim +18 children in tree; one separate object is not a descendant.
    req['material_refs'] = [refs['claim'], *[added[f'n{i}'] for i in range(18)], added['outside']]
    return cs, refs, added, snapshot, call


@pytest.mark.parametrize('context_policy', ['plain', 'reference'])
async def test_native_52_nodes_reports_exact_32_unbound_before_reviewer(ws, record_property, context_policy):
    cs, refs, added, snapshot, call = tree52(ws)
    bounded(ws)
    if context_policy == 'reference':
        ws.store.set('context_policy', 'stateful-tools-v1')
        ws.store.set('manifest', {**ws.store.manifest, 'decision_data_policy':'reference-data-v1'})
    original = deepcopy(call)
    expected = [added[f'n{i}'] for i in range(18, 50)]
    readiness = review_readiness(cs, snapshot, normalize_review_requirements(call['args']['review_requirements']))
    gap, = readiness['issues']
    assert gap['kind'] == 'unbound_body'
    assert gap['missing_refs'] == expected and gap['missing_refs_complete']
    assert (gap['required_body_count'], gap['bound_body_count'], gap['unbound_body_count']) == (52,20,32)
    assert gap['scope_id'] == 'rule-comparison' and gap['requirement_index'] == 0
    assert gap['path'] == '/review_requirements/0/content_check_scopes/0' and gap['ref'] == refs['root']
    compact = readiness_metadata(readiness)
    assert compact['issues']['entries'][0]['unbound_body_count'] == 32
    assert 'original observation' in compact['issues']['entries'][0]['missing_refs_location']
    assert 'missing_refs' not in compact['issues']['entries'][0]

    recovered = []
    def see_error(messages):
        raw = next(m for m in reversed(messages) if m.type == 'tool' and m.tool_call_id == call['id'])
        public = json.loads(raw.content)
        metadata = public.get('metadata', public)
        assert metadata['code'] == 'REVIEW_BODY_EXTENT_OUTSIDE_MATERIAL_POOL'
        if context_policy == 'reference':
            return invoke('read_tool_observation', observation_ref=public['observation_ref'])
        assert all(r['id'] in raw.content for r in expected)
        return AIMessage(content='Correct the explicit task pool; no review completed.')

    def read_page(messages):
        decision = max(i for i, m in enumerate(messages) if m.type == 'ai'
                       and any(c['name'] == 'read_tool_observation' for c in m.tool_calls))
        call_id, = [c['id'] for c in messages[decision].tool_calls if c['name'] == 'read_tool_observation']
        raw, = [m for m in messages[decision + 1:] if m.type == 'tool'
                and m.name == 'read_tool_observation' and m.tool_call_id == call_id]
        public = json.loads(raw.content)
        page = public.get('metadata', public)
        recovered.append(page['text'])
        if page['next_offset'] is not None:
            return invoke('read_tool_observation', observation_ref=page['observation_ref'], offset=page['next_offset'])
        assert all(r['id'] in ''.join(recovered) for r in expected)
        return AIMessage(content='Recovered the exact missing refs; Coordinator must correct the task.')

    driver = Driver(coordinator=[AIMessage(content='', tool_calls=[call]), see_error, *[read_page]*20])
    result = await deep_runtime.run_report(ws, driver)
    assert result['last_error'] is None, result
    assert {r for r, _, _ in driver.calls} == {'coordinator'}
    assert not cs.list_objects('DelegatedTask') and not cs.list_objects('ReviewRecord')
    assert call == original
    assert bool(recovered) == (context_policy == 'reference')
    path = retain_native_evidence(ws, driver, 'tree52-admission', actual_readiness=readiness,
        expected_unbound_refs=expected, original_call=original)
    record_property('native_evidence_path', str(path))
    record_property('actual_context_policy', context_policy)


def test_scope_authority_is_not_selection_or_cross_scope_and_local_is_local(ws):
    cs, refs, added, snapshot, call = tree52(ws)
    bounded(ws)
    req = call['args']['review_requirements'][0]
    other = deepcopy(req)
    other.update(scope_id='other', material_refs=[refs['claim'], *[added[f'n{i}'] for i in range(50)]])
    readiness = review_readiness(cs, snapshot, normalize_review_requirements([req, other]))
    assert [i['scope_id'] for i in readiness['issues']] == ['rule-comparison']
    with delegated_task(ws, 'coordinator', {**call, 'args':{**call['args'], 'review_requirements':[other]}}):
        pass  # All bodies eligible, none selected: admission must still succeed.
    context = review_material_context(cs, snapshot, [other], [], set())
    assert not context['body_extents'][0]['unbound_body_refs']
    assert len(context['body_extents'][0]['missing_full_body_refs']) == 52
    local = deepcopy(req)
    local['content_check_scopes'][0]['kind'] = 'local_body'
    assert review_readiness(cs, snapshot, normalize_review_requirements([local]))['execution_ready']


async def test_saved_unbound_scope_does_not_block_legal_selected_scope_or_replay(ws):
    from report_agent.bounded_review import perform_review
    from report_agent.hierarchical_tools import actor_for
    cs, _, refs, snapshot, _ = seed(ws)
    call = extent_call(snapshot, refs, bind_child=False)
    legal = review_call(snapshot, refs)['args']['review_requirements'][0]
    legal['scope_id'] = 'legal'
    source = next(r for r in cs.read(snapshot)['payload']['refs'] if r['type']=='SourceArtifact')
    legal['required_read_refs'] = [source]
    call['args']['review_requirements'].append(legal)
    with delegated_task(ws, 'coordinator', call) as (_, actor):
        task_id = actor.task_id
    before = deepcopy(cs.list_objects('DelegatedTask'))
    receipt = deepcopy(cs.receipt(actor_for('coordinator'), 'delegate:'+call['id']))
    bounded(ws)
    with delegated_task(ws, 'coordinator', call) as (_, actor):
        assert actor.task_id == task_id
    resumed = deepcopy(call)
    resumed['id'] = 'resume-unbound'
    resumed['args']['resume_content_task_id'] = task_id
    model = Model()
    # Preserve the native checker fixture, changing only its explicit scope id.
    original_invoke = model.ainvoke
    async def reply(messages):
        value = await original_invoke(messages)
        value.content = value.content.replace('rule-comparison', 'legal')
        return value
    model.ainvoke = reply
    with delegated_task(ws, 'coordinator', resumed) as (_, actor):
        result = await perform_review(ws, actor, model, 'legal', ['legal'])
        assert result['review_ref'] and len(model.calls) == 1
        blocked = Model()
        gap = await perform_review(ws, actor, blocked, 'unbound', ['rule-comparison'])
        assert gap['code'] == 'REVIEW_REQUIRED_BODIES_NOT_SUPPLIED' and not blocked.calls
    assert cs.list_objects('DelegatedTask') == before
    assert cs.receipt(actor_for('coordinator'), 'delegate:'+call['id']) == receipt


def test_extent_calculation_has_no_200_node_display_cutoff():
    from report_agent.review_input import body_extent_refs
    from report_agent.store import encode
    nodes = [{'type':'ContentNode','id':str(i),'version':1} for i in range(251)]
    children = {encode(r): [] for r in nodes}
    children[encode(nodes[0])] = nodes[1:]
    assert body_extent_refs(children, {'kind':'subtree_bodies','node_ref':nodes[0]}) == nodes
    assert body_extent_refs(children, {'kind':'local_body','node_ref':nodes[0]}) == nodes[:1]
