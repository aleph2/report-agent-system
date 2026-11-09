from copy import deepcopy

import pytest

from report_agent.commission_imports import install_source_roles
from report_agent import plan_authority
from report_agent.errors import ActionRejected
from test_m1_commission_plan import api, approve, commission, save


def test_missing_named_source_is_recorded_but_cannot_be_approved_as_available(commission):
    plan = deepcopy(commission.plan)
    chapter = next(s for s in plan['sections'] if s['section_id'] == '2')
    chapter.update(sources=[], pending_sources=['Named design general statement'])
    saved = save(commission, plan)
    checkpoint = api().request_checkpoint(commission.ws)
    brief = (commission.ws.store.root / checkpoint['brief_path']).read_text(encoding='utf-8')
    assert 'Named design general statement' in brief
    with pytest.raises(ActionRejected, match='COMMISSION_PENDING_SOURCES'):
        approve(commission, saved)
    assert plan_authority.decision_ref(commission.ws.store) is None


@pytest.mark.parametrize('v4', [False, True])
@pytest.mark.parametrize('args', [
    {'subagent_type': 'reviewer', 'section_ids': ['4']},
    {'subagent_type': 'writer', 'section_ids': ['4'], 'resume_content_task_id': 'old-task'}])
def test_direct_delegation_rejects_misplaced_section_assignment(commission, v4, args):
    from report_agent.content_tasks import delegated_task, _v4_task
    call = {'id': 'misplaced', 'args': {'description': 'fixture', **args}}
    context = _v4_task(commission.ws, call) if v4 else delegated_task(commission.ws, 'coordinator', call)
    with pytest.raises(ActionRejected, match='COMMISSION_SECTION_ASSIGNMENT_REQUIRES_NEW_WRITER'):
        with context:
            pytest.fail('Invalid section assignment was forwarded')


def test_derived_sections_cannot_form_a_cycle(commission):
    plan = deepcopy(commission.plan)
    plan['sections'][-2].update(kind='derived', derived_from=['5'], rule='Use chapter 5')
    with pytest.raises(ActionRejected, match='DERIVED_SECTION'):
        save(commission, plan)


def test_source_quote_cannot_impersonate_customer_convention(commission):
    install_source_roles(commission.ws.store, {
        'scope': {'id': 'scope', 'purpose': 'commission'},
        'design': {'id': 'design', 'purpose': 'source_or_applicable_standard'}})
    plan = deepcopy(commission.plan)
    plan['conventions'][0]['source'] = commission.cite('design')
    with pytest.raises(ActionRejected, match='CUSTOMER_SOURCE'):
        save(commission, plan)
