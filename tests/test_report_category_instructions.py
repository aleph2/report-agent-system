"""Category delivery at real middleware boundaries; no semantic success claims."""
import pytest
from langchain_core.messages import HumanMessage
from pydantic import ValidationError

from report_agent.content_tasks import delegated_task
from report_agent.errors import ActionRejected
from report_agent.prompt_instructions import configure_report, instruction_context, save_instruction
from test_hierarchical_content import seed
from test_prompt_instructions import receive, release
from test_task_supervision import ws

CATEGORY = 'construction_safety_risk_assessment'
TEXT = '施工安全风险评估报告：保留对应工点完整相关段落/图表。表格可调整尺寸与分页，内容不变。'


def bind(ws, report_id='report-a', category=CATEGORY):
    seed(ws)
    ws.store.set('context_policy', 'stateful-tools-v1')
    configure_report(ws.store, report_id, report_category=category)
    record = save_instruction(ws.store, {'id': 'safety-report-rules',
        'topic': 'customer-report-requirements', 'scope': 'report_category',
        'report_category': CATEGORY, 'text': TEXT,
        'source_decision': 'Offline category delivery fixture',
        'allow_override_scopes': ['project', 'report', 'assignment']})
    release(ws, record)
    return record


@pytest.mark.parametrize('report_id', ['slope-report-a', 'bridge-report-b'])
async def test_same_category_different_reports_receive_exact_requirement(ws, report_id):
    record = bind(ws, report_id)
    context, _ = await receive(ws)
    assert context['scoped_instructions']['report_id'] == report_id
    assert context['scoped_instructions']['effective'] == [record]
    assert context['scoped_instructions']['report_category'] == CATEGORY


@pytest.mark.parametrize('category', ['design_quality_consultation', None])
async def test_other_or_unknown_category_does_not_receive_rule_from_history(ws, category):
    bind(ws, category=category)
    stale = [HumanMessage(content='Compacted history: this is a construction safety report. '+TEXT)]
    context, _ = await receive(ws, history=stale)
    assert context['scoped_instructions']['effective'] == []


@pytest.mark.parametrize('role', ['writer', 'reviewer', 'layout'])
async def test_category_survives_delegation_and_summary_recollection(ws, role):
    record = bind(ws)
    args = {'subagent_type': role, 'description': 'Assigned scoped work'}
    if role == 'layout':
        from report_agent.content_store import ContentStore
        args['layout_snapshot_ref'] = next(o['ref'] for o in ContentStore(ws.store).list_objects()
                                           if o['ref']['type'] == 'DocumentSnapshot')
    with delegated_task(ws, 'coordinator', {'id': role+'-task', 'args': args}):
        context, _ = await receive(ws, role, history=[HumanMessage(content='Summary omitted category guidance')])
        assert context['scoped_instructions']['effective'] == [record]
        assert context['scoped_instructions']['effective'][0]['payload']['text'] == TEXT


def test_host_category_cannot_drift_or_be_blank(ws):
    bind(ws)
    with pytest.raises(ActionRejected, match='REPORT_BINDING_IMMUTABLE'):
        configure_report(ws.store, 'report-a', report_category='design_quality_consultation')
    with pytest.raises(ActionRejected, match='REPORT_CATEGORY_REQUIRED'):
        configure_report(ws.store, 'report-a', report_category=' ')


def test_category_override_cannot_escape_parent_applicability(ws):
    parent = bind(ws)
    payload = {'id': 'local-safety', 'topic': 'customer-report-requirements',
        'scope': 'report', 'report_id': 'report-a', 'text': 'Explicit fixture exception',
        'source_decision': 'Offline only', 'overrides': [parent['ref']]}
    for category in [None, 'design_quality_consultation']:
        with pytest.raises(ActionRejected, match='OVERRIDE_TARGET_MISMATCH'):
            save_instruction(ws.store, {**payload, 'report_category': category})
    child = save_instruction(ws.store, {**payload, 'report_category': CATEGORY})
    release(ws, child)
    assert instruction_context(ws.store, 'coordinator')['effective'] == [child]


def test_category_scope_requires_declared_category_and_new_identity_for_change(ws):
    record = bind(ws)
    with pytest.raises(ValidationError, match='requires report_category'):
        save_instruction(ws.store, {**record['payload'], 'id': 'missing-category', 'report_category': None})
    with pytest.raises(ActionRejected, match='SCOPE_CHANGE_REQUIRES_NEW_ID'):
        save_instruction(ws.store, {**record['payload'], 'report_category': 'design_quality_consultation'}, expected_version=1)
