"""Equivalent frozen guideline captures keep evidence and permission checks intact."""
from copy import deepcopy

import pytest

from report_agent.errors import ActionForbidden, ActionRejected
from test_m1_commission_plan import approve, save, writer
from test_m1_g3_integration import method_commission, persist, persistence_input


@pytest.fixture
def alias_commission(method_commission):
    f = method_commission
    f.alias = f.cs.capture_sources(f.co, 'capture-guideline-again', ['guideline'])['result']['source_refs'][0]
    assert f.alias != f.sources['guideline']
    assert f.cs.read(f.alias)['payload'] == f.cs.read(f.sources['guideline'])['payload']
    plan = deepcopy(f.plan)
    # A guide in the section list must never become project-fact evidence.
    plan['sections'][0]['sources'].append({**f.cite('guideline'), 'source_ref': f.alias})
    f.saved = save(f, plan)
    approve(f, f.saved)
    f.actor = writer(f, f.saved)
    f.assessment = persistence_input(f)
    f.applied = next(row for row in f.assessment['indicators'] if row['basis_kind'] == 'applied_guideline')
    f.applied['sources'][1]['source_ref'] = f.alias
    return f


def variant(f, field, value):
    payload = deepcopy(f.cs.read(f.alias)['payload'])
    payload[field] = value
    return f.cs.operation(f.co, 'capture-variant-' + field, {'variant': field},
        lambda db: f.cs._insert(db, f.co, 'SourceArtifact', payload))['result']


def test_same_frozen_guideline_capture_saves_without_rewriting_inputs(alias_commission):
    f = alias_commission
    sources_before = deepcopy(f.cs.list_objects('SourceArtifact'))
    input_before = deepcopy(f.assessment)
    original = persist(f, f.actor, persistence_input(f), operation='save-original-guideline')
    saved = persist(f, f.actor, f.assessment, operation='save-guideline-alias')
    actual = f.cs.read(saved['assessment_ref'])['payload']
    baseline = f.cs.read(original['assessment_ref'])['payload']
    assert f.cs.list_objects('SourceArtifact') == sources_before
    assert f.assessment == input_before
    for row, expected in zip(actual['indicators'], baseline['indicators']):
        assert {key: row[key] for key in ('indicator_id', 'rank', 'grade_id', 'value', 'rank_reason', 'rationale')} == {
            key: expected[key] for key in ('indicator_id', 'rank', 'grade_id', 'value', 'rank_reason', 'rationale')}
    assert actual['result']['adopted'] == baseline['result']['adopted']
    assert actual['result']['low'] == baseline['result']['low']
    assert actual['result']['high'] == baseline['result']['high']
    applied = next(row for row in actual['indicators'] if row['basis_kind'] == 'applied_guideline')
    assert applied['sources'][1]['source_ref'] == f.alias


@pytest.mark.parametrize('field,value', [
    ('source_id', 'design'), ('source_id', ''),
    ('file_digest', 'f' * 64), ('file_digest', ''),
    ('content', 'Changed frozen text despite a claimed identical file digest.'), ('content', ''),
])
def test_matching_title_or_claimed_hash_cannot_replace_frozen_identity(alias_commission, field, value):
    f = alias_commission
    changed = variant(f, field, value)
    f.applied['sources'][1].update(source_ref=changed, quote='')
    before = f.cs.list_objects('Assessment')
    with pytest.raises((ActionRejected, ActionForbidden)):
        persist(f, f.actor, f.assessment)
    assert f.cs.list_objects('Assessment') == before


def test_irrelevant_capture_metadata_does_not_change_guideline_identity(alias_commission):
    f = alias_commission
    metadata = deepcopy(f.cs.read(f.alias)['payload']['source_metadata'])
    metadata.update(current=False)
    alias = variant(f, 'source_metadata', metadata)
    f.applied['sources'][1]['source_ref'] = alias
    assert persist(f, f.actor, f.assessment)['assessment_ref']['type'] == 'Assessment'


def test_changed_title_is_a_new_frozen_version_without_file_reapproval(alias_commission):
    f = alias_commission
    from report_agent.source_use import immutable_version_digest
    original = deepcopy(f.cs.read(f.alias))
    metadata = {**original['payload']['source_metadata'], 'title': 'A new display title'}
    changed = variant(f, 'source_metadata', metadata)
    assert immutable_version_digest(original['payload']) != immutable_version_digest(f.cs.read(changed)['payload'])
    f.applied['sources'][1]['source_ref'] = changed
    saved = persist(f, f.actor, f.assessment)
    actual = f.cs.read(saved['assessment_ref'])['payload']
    assert any(c['source_ref'] == changed for r in actual['indicators'] for c in r['sources'])
    assert f.cs.read(f.alias) == original


def test_guideline_alias_in_section_sources_cannot_satisfy_project_facts(alias_commission):
    f = alias_commission
    f.applied['sources'] = [f.applied['sources'][1]]
    with pytest.raises(ActionRejected, match='ASSESSMENT_FACTUAL_SOURCE_REQUIRED'):
        persist(f, f.actor, f.assessment)
    assert not f.cs.list_objects('Assessment')


def test_guideline_alias_still_requires_the_quote_at_its_location(alias_commission):
    f = alias_commission
    f.applied['sources'][1]['quote'] = 'Invented sentence absent from the supplied synthetic guideline.'
    with pytest.raises(ActionRejected, match='COMMISSION_QUOTE_NOT_AT_SOURCE_LOCATION'):
        persist(f, f.actor, f.assessment)
    assert not f.cs.list_objects('Assessment')


@pytest.mark.parametrize('name,code', [
    ('template', 'ASSESSMENT_TEMPLATE_IS_NOT_FACTUAL_BASIS'),
    ('scope', 'ASSESSMENT_COMMISSION_IS_NOT_FACTUAL_BASIS'),
])
def test_guideline_alias_does_not_admit_template_or_commission_as_facts(alias_commission, name, code):
    f = alias_commission
    f.applied['sources'].append(f.cite(name))
    with pytest.raises(ActionRejected, match=code):
        persist(f, f.actor, f.assessment)
    assert not f.cs.list_objects('Assessment')


def test_guideline_alias_does_not_expand_host_source_authorization(alias_commission):
    from report_agent.catalog import Catalog
    f = alias_commission
    # A newly catalogued copy can have identical guideline text but was not enrolled
    # in the supplied-file boundary of this case.
    text = f.cs.read(f.alias)['payload']['content']
    other_id = Catalog(f.ws.store).import_file('extra-guideline.txt', text.encode())['source']['id']
    other = f.cs.capture_sources(f.co, 'new-guideline-copy', [other_id])['result']['source_refs'][0]
    source = f.applied['sources'][1]
    source['source_ref'] = other
    source['locator'] = Catalog(f.ws.store).read(other_id, 0, 1)['blocks'][0]['locator']
    with pytest.raises((ActionRejected, ActionForbidden), match='CASE_SOURCE_NOT_SUPPLIED'):
        persist(f, f.actor, f.assessment)
    assert not f.cs.list_objects('Assessment')


def test_guideline_alias_does_not_expand_the_writer_section_assignment(alias_commission):
    f = alias_commission
    other = writer(f, f.saved, section_ids=['5'], operation='derived-only-writer')
    with pytest.raises(ActionRejected, match='ASSESSMENT_REQUIRES_EXTRACTED_SECTION_ASSIGNMENT'):
        persist(f, other, f.assessment)
    assert not f.cs.list_objects('Assessment')
