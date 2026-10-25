"""Learning responsibility checks with one-shot fake services; no strategy acceptance."""
import json

import pytest
from langchain_core.messages import AIMessage

from report_agent.errors import ActionRejected
from report_agent.learning import binding
from report_agent.learning_runtime import optimizer_tools
from report_agent.learning_text_work import FeedbackSelection
from report_agent.store import Store
from report_agent.workspace import Workspace
from test_bounded_review import Model


@pytest.fixture
def case(tmp_path):
    ws = Workspace(Store(tmp_path/'project'))
    ws.store.set('learning_config', {'library_path': str(tmp_path/'library'), 'customer_id': 'a'})
    library, scope = binding(ws)
    feedback = library.feedback(scope, {}, {}, 'Compare recorded class and interval', 'B,70', ['B permits 75–100'])
    ws.store.set('learning_job', {'id': 'synthetic-job', 'state': 'running'})
    return ws, library, scope, feedback


async def test_fact_candidate_adopts_exact_tool_fields_while_strategy_is_learner_decision(case):
    ws, library, scope, feedback = case
    fact = {'title': 'Located rule', 'strategy': 'The supplied example states B permits 75–100.',
            'conditions': 'Only the supplied synthetic rule.'}
    model = Model(json.dumps({'findings': 'The recorded value is outside that interval.', 'project_fact': fact}))
    t = {f.__name__: f for f in optimizer_tools(ws, text_model=model)}
    with pytest.raises(ActionRejected, match='REQUIRES_CURRENT_SCOPED_ANALYSIS'):
        t['propose_experience']([feedback['id']], 'project_fact', **fact, verification='Read actual rule')
    result = await t['analyze_learning_material']('Compare the rule and recorded value', [
        FeedbackSelection(feedback_id=feedback['id'], field='evidence'),
        FeedbackSelection(feedback_id=feedback['id'], field='before')])
    t['propose_experience']([feedback['id']], 'project_fact', **fact, verification='Read actual rule', analysis_id=result['analysis_id'])
    with pytest.raises(ActionRejected, match='OUTPUT_CHANGED'):
        t['propose_experience']([feedback['id']], 'project_fact', **{**fact, 'strategy': 'Invented 70 is permitted'},
            verification='Read actual rule', analysis_id=result['analysis_id'])
    # Formulating useful future actions is agent decision; no tool rewrite required.
    t['propose_experience']([feedback['id']], 'general_skill', 'Interval decision',
        'Select supported class before score', 'Use when a rubric specifies classes', 'Compare chosen actions')
    assert len(model.calls) == 1 and len(library.list_versions(scope)) == 2
    assert not library.search(scope) and not result['fact_correctness_verified']
    assert not {'task', 'release', 'commit_objects'} & t.keys()


async def test_scoped_analysis_cannot_read_foreign_feedback_or_be_reused_by_other_job(case):
    ws, library, scope, feedback = case
    fact = {'title': 'Rule', 'strategy': 'B interval', 'conditions': 'Supplied evidence only'}
    model = Model(json.dumps({'findings': 'Synthetic finding', 'project_fact': fact}))
    t = {f.__name__: f for f in optimizer_tools(ws, text_model=model)}
    with pytest.raises(ActionRejected, match='OUTSIDE_PROJECT'):
        await t['analyze_learning_material']('Read', [FeedbackSelection(feedback_id='foreign', field='before')])
    assert not model.calls
    result = await t['analyze_learning_material']('Read selected original', [FeedbackSelection(feedback_id=feedback['id'], field='evidence')])
    ws.store.set('learning_job', {'id': 'another-job', 'state': 'running'})
    with pytest.raises(ActionRejected, match='REQUIRES_CURRENT_SCOPED_ANALYSIS'):
        t['propose_experience']([feedback['id']], 'project_fact', **fact, verification='Check', analysis_id=result['analysis_id'])


async def test_real_optimizer_has_independent_analysis_capability_without_mandatory_dispatch(case):
    from report_agent.learning_runtime import build_optimizer
    from test_deep_runtime import Driver, invoke
    ws, _, _, feedback = case
    driver = Driver(optimizer=[invoke('analyze_learning_material', question='Compare selected original evidence',
        feedback_selections=[{'feedback_id': feedback['id'], 'field': 'evidence'}]),
        AIMessage(content='Retain uncertainty; choose no candidate.')])
    model = Model(json.dumps({'findings': 'The supplied original states an interval.', 'project_fact': None}))
    result = await build_optimizer(ws, driver('optimizer'), text_model=model).ainvoke(
        {'messages': [('user', 'Investigate the assigned evidence')]}, config={'recursion_limit': 8})
    assert len(model.calls) == 1 and result['messages'][-1].content == 'Retain uncertainty; choose no candidate.'
