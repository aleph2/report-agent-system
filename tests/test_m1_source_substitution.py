"""Named-source substitutions retain provenance and need ordinary owner confirmation."""
from copy import deepcopy

import pytest

from report_agent import plan_authority
from report_agent.catalog import Catalog
from report_agent.errors import ActionForbidden, ActionRejected
from test_m1_commission_plan import api, approve, commission, save, writer


REQUESTED = 'Named design general statement'
CUSTOMER_RULE = ('If the named general statement is unavailable, use the supplied design or survey records '
                 'as replacement material and state the substitution for owner confirmation.')


@pytest.fixture
def substitution(commission):
    source = Catalog(commission.ws.store).import_file('customer-substitution-scope.md',
        CUSTOMER_RULE.encode('utf-8'))['source']
    source_ref = commission.cs.capture_sources(commission.co, 'capture-substitution-scope',
        [source['id']])['result']['source_refs'][0]
    with commission.ws.store.connect() as db:
        locator = db.execute('SELECT locator FROM source_blocks WHERE source_id=? ORDER BY rowid',
            (source['id'],)).fetchone()[0]
    commission.ws.store.set('commission_source_roles', {
        'scope': {'id': 'scope', 'purpose': 'commission'},
        'substitution-scope': {'id': source['id'], 'purpose': 'commission'},
        'design': {'id': 'design', 'purpose': 'source_or_applicable_standard'},
        'survey': {'id': 'survey', 'purpose': 'source_or_applicable_standard'}})
    plan = deepcopy(commission.plan)
    section = next(s for s in plan['sections'] if s['section_id'] == '2')
    section.update(pending_sources=[REQUESTED], sources=[commission.cite('design')],
        source_substitutions=[{'requested_source': REQUESTED,
            'replacement_sources': [commission.cite('design')],
            'customer_basis': {'source_ref': source_ref, 'locator': locator, 'quote': CUSTOMER_RULE},
            'reason': 'Agent interpretation: the supplied design volume supports the required project overview.'}])
    commission.plan = plan
    return commission


def section(plan):
    return next(s for s in plan['sections'] if s['section_id'] == '2')


def test_substitution_keeps_named_gap_and_source_basis_then_uses_existing_checkpoint(substitution):
    saved = save(substitution)
    proposed = api().read_plan(substitution.ws.store)['payload']
    assert section(proposed)['pending_sources'] == [REQUESTED]
    assert section(proposed)['source_substitutions'] == section(substitution.plan)['source_substitutions']
    actor = writer(substitution, saved, section_ids=['2'])
    with substitution.ws.store.connect() as db, pytest.raises((ActionRejected, ActionForbidden)):
        api().assert_writing_allowed(substitution.cs, db, actor)
    checkpoint, _ = approve(substitution, saved)
    brief = (substitution.ws.store.root / checkpoint['brief_path']).read_text(encoding='utf-8')
    assert REQUESTED in brief and CUSTOMER_RULE in brief
    assert 'design' in brief
    assert section(proposed)['source_substitutions'][0]['reason'] in brief
    with substitution.ws.store.connect() as db:
        assert api().assert_writing_allowed(substitution.cs, db, actor)['ref'] == saved['plan_ref']
    assert api().read_plan(substitution.ws.store)['ref'] == saved['plan_ref']


@pytest.mark.parametrize('fault', ['no-quote', 'wrong-source', 'invented-quote',
    'missing-replacement', 'reference-mismatch', 'wrong-requested-name'])
def test_substitution_rejects_invalid_customer_or_replacement_basis(substitution, fault):
    # First prove the new valid contract is supported; unrelated extra-field errors must not count as negatives.
    save(substitution, operation='valid-substitution-control')
    plan = deepcopy(substitution.plan)
    item = section(plan)['source_substitutions'][0]
    if fault == 'no-quote':
        item['customer_basis']['quote'] = ''
    elif fault == 'wrong-source':
        item['customer_basis'] = substitution.cite('design')
    elif fault == 'invented-quote':
        item['customer_basis']['quote'] = 'Invented permission to replace any document.'
    elif fault == 'missing-replacement':
        item['replacement_sources'] = []
    elif fault == 'reference-mismatch':
        section(plan)['sources'] = [substitution.cite('survey')]
    else:
        item['requested_source'] = 'A different unrequested source'
    with pytest.raises((ActionRejected, ActionForbidden, ValueError)):
        save(substitution, plan, operation='invalid-substitution')
    assert plan_authority.decision_ref(substitution.ws.store) is None


def test_one_substitution_does_not_cover_another_pending_source(substitution):
    plan = deepcopy(substitution.plan)
    section(plan)['pending_sources'].append('Named overall layout drawing')
    saved = save(substitution, plan)
    with pytest.raises(ActionRejected, match='COMMISSION_PENDING_SOURCES'):
        approve(substitution, saved)
    assert plan_authority.decision_ref(substitution.ws.store) is None


def test_changed_substitution_requires_new_plan_confirmation(substitution):
    saved = save(substitution)
    approve(substitution, saved)
    actor = writer(substitution, saved, section_ids=['2'])
    revised = deepcopy(substitution.plan)
    section(revised)['sources'] = [substitution.cite('survey')]
    section(revised)['source_substitutions'][0]['replacement_sources'] = [substitution.cite('survey')]
    current = save(substitution, revised, operation='changed-substitution')
    with substitution.ws.store.connect() as db, pytest.raises((ActionRejected, ActionForbidden)):
        api().assert_writing_allowed(substitution.cs, db, actor)
    approve(substitution, current)
    with substitution.ws.store.connect() as db, pytest.raises((ActionRejected, ActionForbidden)):
        api().assert_writing_allowed(substitution.cs, db, actor)
    fresh = writer(substitution, current, section_ids=['2'], operation='new-substitution-writer')
    with substitution.ws.store.connect() as db:
        assert api().assert_writing_allowed(substitution.cs, db, fresh)['ref'] == current['plan_ref']
