from copy import deepcopy

import pytest

from report_agent import plan_authority
from report_agent.errors import ActionRejected
from test_m1_source_substitution import substitution, section, REQUESTED
from test_m1_commission_plan import commission, save, approve, api


@pytest.mark.parametrize('roles', [{}, None])
def test_customer_authority_missing_fails_closed(substitution, roles):
    substitution.ws.store.set('commission_source_roles', roles)
    with pytest.raises(ActionRejected, match='CUSTOMER_SOURCE'):
        save(substitution)


@pytest.mark.parametrize('change', ['delete-name', 'delete-section', 'rename-section'])
def test_revision_cannot_drop_known_source_obligation(substitution, change):
    original = deepcopy(substitution.plan)
    section(original)['source_substitutions'] = []
    save(substitution, original)
    revised = deepcopy(original)
    if change == 'delete-name':
        section(revised)['pending_sources'] = []
    elif change == 'rename-section':
        section(revised)['section_id'] = '2-renamed'
    else:
        revised['sections'].remove(section(revised))
    with pytest.raises(ActionRejected, match='SOURCE_OBLIGATION'):
        save(substitution, revised, operation='drop-pending-obligation')


def test_resolution_in_one_section_cannot_clear_another_section(substitution):
    plan = deepcopy(substitution.plan)
    other = next(s for s in plan['sections'] if s['section_id'] == '1.3')
    other['pending_sources'] = [REQUESTED]
    saved = save(substitution, plan)
    with pytest.raises(ActionRejected, match='COMMISSION_PENDING_SOURCES'):
        approve(substitution, saved)


def test_brief_is_chinese_and_distinguishes_proposal_from_approval(substitution):
    save(substitution)
    checkpoint = api().request_checkpoint(substitution.ws)
    brief = (substitution.ws.store.root / checkpoint['brief_path']).read_text(encoding='utf-8')
    for heading in ('编制计划确认', '评估对象', '章节计划', '交付物', '客户约定', '资料替代', '待确认问题'):
        assert heading in brief
    assert '客户原文依据' in brief and '代理解释' in brief
    assert plan_authority.decision_ref(substitution.ws.store) is None
