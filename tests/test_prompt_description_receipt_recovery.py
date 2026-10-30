"""Description-only upgrades must reuse received output, never unknown provider work."""
from copy import deepcopy
import json

import pytest

from report_agent.content_tasks import delegated_task
from report_agent.errors import ActionRejected
from report_agent import prompt_sources
from test_bounded_review import Model
from test_hierarchical_content import seed
from test_native_operation_identity import activate, dispatch, graph_for, tools
from test_task_supervision import ws, offline
from test_text_work import content, writer_call


def current_interface(workspace):
    activate(workspace)
    workspace.store.set('manifest', {**workspace.store.manifest,
        'review_interface_profile':'review-interfaces-v4',
        'review_execution_mode':'native-reviewer-v2',
        'delegation_prompt_profile':'separate-description-v1',
        'report_expression_profile':'reader-expression-v2', 'report_prompt_profile':'concise-v1'})


def old_descriptions(monkeypatch):
    # Only schema prose changes; old typed models, materials and authorization are exact.
    monkeypatch.setattr(prompt_sources, 'describe_content_schema', lambda schema:(deepcopy(schema), []), raising=False)


async def test_completed_native_output_keeps_identity_after_current_field_description_upgrade(ws, monkeypatch):
    _, _, refs, _, _ = seed(ws)
    current_interface(ws)
    model = Model(json.dumps(content()))
    args = {'objective':'Describe the selected evidence', 'object_type':'ContentNode', 'input_refs':[refs['claim']]}
    with delegated_task(ws, 'coordinator', writer_call()) as (_, actor):
        function = tools(ws, 'writer', model)['process_report_content']
        with monkeypatch.context() as patch:
            old_descriptions(patch)
            first = await dispatch(graph_for(function), 'completed-before-description-upgrade', args)
        key = 'text_work:'+actor.id+':'+first['operation_id']
        original = ws.store.get(key)
        recovered = await dispatch(graph_for(function), 'completed-before-description-upgrade', args)
        for field in ('operation_id','text_work_id','operation','payload','actor_id','task_id'):
            assert recovered[field] == first[field]
        assert recovered['reused'] and len(model.calls) == 1
        assert ws.store.get(key) == original
        events = [e['data'] for e in ws.store.events() if e['kind']=='text_work_completed_schema_reused']
        assert len(events) == 1 and events[0]['paid_calls'] == 0


@pytest.mark.parametrize('call_id', ['original-unknown-call','new-id-cannot-authorize-replay'])
async def test_schema_description_upgrade_cannot_replay_synthetic_unknown(ws, monkeypatch, call_id):
    _, _, refs, _, _ = seed(ws)
    current_interface(ws)
    model = Model(RuntimeError('synthetic unknown provider result'))
    args = {'objective':'Describe the selected evidence', 'object_type':'ContentNode', 'input_refs':[refs['claim']]}
    with delegated_task(ws, 'coordinator', writer_call()) as (_, actor):
        graph = graph_for(tools(ws, 'writer', model)['process_report_content'])
        with monkeypatch.context() as patch:
            old_descriptions(patch)
            with pytest.raises(RuntimeError, match='synthetic unknown'):
                await dispatch(graph, 'original-unknown-call', args)
        key = 'text_work:'+actor.id+':native:process_report_content:original-unknown-call'
        original = ws.store.get(key)
        assert original['state'] == 'reserved'
        with pytest.raises(ActionRejected, match='OPERATION_CONFLICT|OUTCOME_UNRESOLVED'):
            await dispatch(graph, call_id, args)
        assert len(model.calls) == 1 and ws.store.get(key) == original
        assert not [e for e in ws.store.events() if e['kind']=='text_work_completed_schema_reused']


async def test_description_upgrade_never_reuses_completed_output_for_changed_objective(ws, monkeypatch):
    _, _, refs, _, _ = seed(ws)
    current_interface(ws)
    model = Model(json.dumps(content()))
    args = {'objective':'Describe the selected evidence', 'object_type':'ContentNode', 'input_refs':[refs['claim']]}
    with delegated_task(ws, 'coordinator', writer_call()) as (_, actor):
        graph = graph_for(tools(ws, 'writer', model)['process_report_content'])
        with monkeypatch.context() as patch:
            old_descriptions(patch)
            first = await dispatch(graph, 'completed-intent', args)
        key = 'text_work:'+actor.id+':'+first['operation_id']
        original = ws.store.get(key)
        with pytest.raises(ActionRejected, match='OPERATION_CONFLICT'):
            await dispatch(graph, 'completed-intent', {**args,'objective':'A different report objective'})
        assert len(model.calls) == 1 and ws.store.get(key) == original


async def test_independent_learning_analysis_has_no_report_profile_precondition(tmp_path):
    from report_agent.store import Store
    from report_agent.workspace import Workspace
    from report_agent.learning_text_work import LearningAnalysis
    from report_agent.evidence_analysis import analyze_evidence_packet
    workspace = Workspace(Store(tmp_path / 'independent-learning'))
    model = Model('Synthetic bounded learning observation.')
    result = await analyze_evidence_packet(workspace, model,
        {'evidence':[], 'output_schema':LearningAnalysis.model_json_schema()},
        prompt_sources.load_prompt('learning-analysis'), 'learning-evidence-text-work-v1')
    assert result['analysis'] == 'Synthetic bounded learning observation.'
    assert len(model.calls) == 1


async def test_content_schema_report_profile_error_still_fails_closed(ws):
    from report_agent.content_models import ContentNode
    from report_agent.evidence_analysis import analyze_evidence_packet
    ws.store.set('manifest', {**ws.store.manifest, 'review_interface_profile':'invalid-profile'})
    model = Model('Must not be invoked.')
    with pytest.raises(ActionRejected, match='UNKNOWN_REVIEW_INTERFACE_PROFILE'):
        await analyze_evidence_packet(ws, model,
            {'evidence':[], 'output_schema':ContentNode.model_json_schema()},
            prompt_sources.load_prompt('text-work'), 'independent-text-tools-v1')
    assert not model.calls
