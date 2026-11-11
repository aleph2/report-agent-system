"""Method selection authority uses actual stored source versions and checkpoints."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from report_agent.commission_imports import install_source_roles
from report_agent import plan_authority
from report_agent.content_store import ContentStore
from report_agent.errors import ActionForbidden, ActionRejected
from report_agent.hierarchical_tools import actor_for
from report_agent.store import Store
from report_agent.workspace import Workspace
from test_m1_commission_plan import api, approve, save, unapproved_writer, writer
from test_m1_g3_method_pack import pack_data
from test_m1_g3_scoring import assessment_data


@pytest.fixture
def method_commission(tmp_path, request):
    texts = {
        'scope': 'Assess S1. Use rank-lookup weights from the supplied synthetic guideline. '
                 'Boundary K1+000 to K2+000; expected one in-range object. Select first contract.',
        'outline': 'Section 4 assesses S1; section 5 summarizes section 4.',
        'guideline': 'Synthetic four-indicator method with rank-lookup and alternative-lookup tables.',
        'design': 'S1 is a design object with a 30 metre height. S1 K1+200-K1+400. '
                  'S2 K3+000-K3+200. Conflicting S2 K1+500-K1+700. First contract K1+000-K2+000.',
        'template': 'Example report uses rank-lookup weights; this example is not customer authority.\n'
                    'Project OLD.\nExact method sentence.\nSummary: {SUMMARY}\n'
                    'Score {TOTAL}; level {LEVEL}.\nRepeated {REPEAT} and {REPEAT}.\n'
                    'Objects {COUNT}; level II {II_COUNT}; level III {III_COUNT}.'}
    if getattr(request, 'param', None) == 'with-owner-ranks':
        texts['scope'] += ' Owner rank order: B, A, D, C.'
    if getattr(request, 'param', None) == 'without-weight-convention':
        texts['scope'] = 'Assess S1.'
    store = Store(tmp_path)
    store.initialize({'goal': texts['scope'], 'content_contract': 'hierarchical-review-v1',
        'commission_checkpoint_required': True, 'coverage_contract': 'object-coverage-v1',
        'sources': [{'id': key, 'title': key, 'content': value, 'coverage': 'complete'}
                    for key, value in texts.items()]})
    ws, co = Workspace(store), actor_for('coordinator')
    cs = ContentStore(store)
    imported = cs.import_inputs(co, 'method-inputs', list(texts))['result']
    sources = {cs.read(ref)['payload']['source_id']: ref for ref in imported['source_refs']}
    install_source_roles(store, {
        name: {'id': name, 'purpose': 'commission' if name == 'scope' else
               'template' if name == 'template' else 'source_or_applicable_standard'}
        for name in texts})

    def cite(name, quote=None):
        return {'source_ref': sources[name], 'locator': 'manifest text', 'quote': quote or texts[name]}

    pack = pack_data()
    pack['sources'] = [cite('guideline')]
    for table in pack['weight_tables']:
        table['source'] = cite('guideline')
    convention = cite('scope', 'Use rank-lookup weights from the supplied synthetic guideline.'
                      if 'Use rank-lookup' in texts['scope'] else 'Assess S1.')
    plan = {
        'sections': [
            {'section_id': '4', 'title': 'Assessment', 'kind': 'extracted',
             'outline': cite('outline'), 'sources': [cite('design')]},
            {'section_id': '5', 'title': 'Conclusion', 'kind': 'derived',
             'outline': cite('outline'), 'sources': [cite('design')],
             'derived_from': ['4'], 'rule': 'Summarize the section 4 assessment.'}],
        'inventory_attributes': ['height'],
        'objects': [{'object_id': 'S1', 'label': 'Slope 1', 'included': True,
            'reason': 'Explicitly commissioned.', 'origin': 'customer',
            'attributes': [{'name': 'height', 'values': [
                {'value': '30 m', 'source': cite('design'), 'reason': 'Drawing fact.'}]}],
            'sources': [cite('design'), cite('scope')]}],
        'conventions': [{'source': convention, 'interpretation': 'Select supplied rank-lookup data.'}],
        'deliverables': ['Word', 'Excel'],
        'reconciliations': [{'sources': [cite('design'), cite('scope')],
            'result': 'The commissioned S1 occurs in the design.', 'differences': []}],
        'open_questions': [], 'method_pack': pack,
        'method_conventions': [{'key': 'weights', 'source': convention,
            'interpretation': 'Use the four-indicator row without recalculation.',
            'status': 'specified', 'method_id': pack['method_id'], 'strategy_id': 'rank-lookup'}]}
    fixture = SimpleNamespace(ws=ws, cs=cs, co=co, plan=plan, sources=sources, cite=cite)
    from support.plan_fixture import synthetic_pilot_plan
    if getattr(request, 'param', None) != 'historical-without-spec':
        fixture.plan = synthetic_pilot_plan(fixture, version=1)
    else:
        from report_agent.method_pack import register_reviewed_method_pack
        register_reviewed_method_pack(store, pack, 'Reviewed synthetic historical fixture.')
    return fixture


def brief_text(fixture, checkpoint):
    path = Path(checkpoint['brief_path'])
    return (path if path.is_absolute() else fixture.ws.store.root / path).read_text(encoding='utf-8')


def test_selected_method_preserves_exact_customer_basis_and_normal_checkpoint(method_commission):
    fixture = method_commission
    saved = save(fixture)
    payload = api().read_plan(fixture.ws.store)['payload']
    assert payload['method_conventions'] == fixture.plan['method_conventions']
    assert payload['method_pack']['sources'] == fixture.plan['method_pack']['sources']
    checkpoint, _ = approve(fixture, saved)
    brief = brief_text(fixture, checkpoint)
    assert fixture.plan['method_conventions'][0]['source']['quote'] in brief
    assert 'rank-lookup' in brief
    assert 'Use the four-indicator row without recalculation.' in brief
    actor = writer(fixture, saved)
    with fixture.cs.store.connect() as db:
        assert api().assert_writing_allowed(fixture.cs, db, actor)


@pytest.mark.parametrize('source', ['template', 'guideline'])
def test_method_selection_cannot_take_its_authority_from_reference_material(method_commission, source):
    fixture = method_commission
    plan = deepcopy(fixture.plan)
    plan['method_conventions'][0]['source'] = fixture.cite(source)
    with pytest.raises((ActionRejected, ValueError)):
        save(fixture, plan)


def test_method_selection_requires_the_same_exact_declared_customer_convention(method_commission):
    fixture = method_commission
    plan = deepcopy(fixture.plan)
    # This is an authentic scope quotation, but not the convention's declared quotation.
    plan['method_conventions'][0]['source'] = fixture.cite('scope', 'Assess S1.')
    with pytest.raises((ActionRejected, ValueError)):
        save(fixture, plan)


def test_invented_method_quote_is_refused_even_if_ordinary_convention_is_valid(method_commission):
    fixture = method_commission
    plan = deepcopy(fixture.plan)
    plan['method_conventions'][0]['source']['quote'] = 'Owner selected invented weights.'
    with pytest.raises((ActionRejected, ValueError)):
        save(fixture, plan)


@pytest.mark.parametrize('fault', ['missing', 'unavailable'])
def test_missing_method_capability_is_saved_as_question_but_cannot_be_approved(method_commission, fault):
    fixture = method_commission
    plan = deepcopy(fixture.plan)
    if fault == 'missing':
        plan['method_conventions'] = []
    else:
        plan['method_conventions'][0]['strategy_id'] = 'unimplemented-formula'
    saved = save(fixture, plan)
    record = api().read_plan(fixture.ws.store)['payload']
    assert record['method_questions']
    checkpoint = api().request_checkpoint(fixture.ws)
    brief = brief_text(fixture, checkpoint)
    assert all(question in brief for question in record['method_questions'])
    with pytest.raises(ActionRejected, match='(?i)(method|strategy|weight)'):
        approve(fixture, saved)
    assert plan_authority.decision_ref(fixture.ws.store) is None


@pytest.mark.parametrize('method_commission', ['without-weight-convention'], indirect=True)
def test_guideline_default_is_visible_as_unagreed_before_owner_approval(method_commission):
    fixture = method_commission
    plan = deepcopy(fixture.plan)
    plan['conventions'] = []
    plan['method_conventions'][0].update(source=None, status='default_unagreed',
        interpretation='Guideline default proposed for this missing convention.')
    saved = save(fixture, plan)
    checkpoint = api().request_checkpoint(fixture.ws)
    assert '默认，未约定' in brief_text(fixture, checkpoint)
    assert plan_authority.decision_ref(fixture.ws.store) is None
    approve(fixture, saved)


def test_method_version_revision_requires_new_operator_confirmation(method_commission):
    fixture = method_commission
    saved = save(fixture)
    approve(fixture, saved)
    actor = writer(fixture, saved)
    revised = deepcopy(fixture.plan)
    revised['method_pack']['version'] = 2
    current = save(fixture, revised, operation='revised-method-pack')
    assert current['plan_ref'] != saved['plan_ref']
    with fixture.cs.store.connect() as db, pytest.raises(ActionRejected, match='STALE'):
        api().assert_writing_allowed(fixture.cs, db, actor)


@pytest.mark.parametrize('fault', ['unregistered-version', 'changed-weight'])
def test_genuine_citations_do_not_authorize_unreviewed_numeric_method_data(method_commission, fault):
    fixture = method_commission
    plan = deepcopy(fixture.plan)
    if fault == 'unregistered-version':
        plan['method_pack']['version'] = 99
    else:
        plan['method_pack']['weight_tables'][0]['rows'][1]['weights'] = ['0.1', '0.2', '0.3', '0.4']
    saved = save(fixture, plan)
    assert api().read_plan(fixture.ws.store)['payload']['method_questions']
    with pytest.raises(ActionRejected, match='(?i)(method|review)'):
        approve(fixture, saved)
    assert plan_authority.decision_ref(fixture.ws.store) is None


def persistence_input(fixture):
    assessment = assessment_data()
    for row in assessment['indicators']:
        row['sources'] = [] if row['basis_kind'] == 'no_evidence_assumption' else [fixture.cite('design')]
        if row['basis_kind'] == 'applied_guideline':
            row['sources'].append(fixture.cite('guideline'))
        row['rank_reason'] = 'Relative importance judged from S1 design facts.'
        row['plausible_grades'] = ['g2', 'g3'] if row['basis_kind'] == 'indirect_assumption' else (
            ['g1', 'g2', 'g3', 'g4'] if row['basis_kind'] == 'no_evidence_assumption' else [])
        row.pop('low')
        row.pop('high')
    return assessment


def persist(fixture, actor, assessment=None, operation='save-assessment'):
    from report_agent.risk_scoring import save_assessment
    return save_assessment(fixture.cs, actor, operation,
                           assessment if assessment is not None else persistence_input(fixture))['result']


def test_v1_ranking_keeps_reasons_only_in_immutable_assessment_audit(method_commission):
    fixture = method_commission
    saved = save(fixture)
    approve(fixture, saved)
    receipt = persist(fixture, writer(fixture, saved))
    assessment = fixture.cs.read(receipt['assessment_ref'])['payload']
    ranking = fixture.cs.read(receipt['ranking_ref'])['payload']['body']
    assert ranking['columns'] == ['序号', '评估指标', '权重系数']
    assert all(len(row) == 3 for row in ranking['rows'])
    assert not ranking.get('cell_comments')
    for rows in (assessment['indicators'], assessment['result']['rows']):
        assert len(rows) == 4
        assert all(row['rank_reason'] == 'Relative importance judged from S1 design facts.' for row in rows)


def test_assessment_receipt_is_repeatable_and_bounds_come_from_plausible_grade_endpoints(method_commission):
    from decimal import Decimal
    fixture = method_commission
    saved = save(fixture)
    approve(fixture, saved)
    actor = writer(fixture, saved)
    receipt = persist(fixture, actor)
    object_count = len(fixture.cs.list_objects())
    assert persist(fixture, actor) == receipt
    assert len(fixture.cs.list_objects()) == object_count
    assert Decimal(receipt['result']['adopted']['total']) == Decimal('43.5')
    assert Decimal(receipt['result']['low']['total']) == Decimal('33')
    assert Decimal(receipt['result']['high']['total']) == Decimal('52.8')
    assert receipt['result']['affects_level'] is True
    assessment = fixture.cs.read(receipt['assessment_ref'])['payload']
    by_id = {row['indicator_id']: row for row in assessment['indicators']}
    assert (by_id['C']['low'], by_id['C']['high']) == ('25', '74')
    assert (by_id['D']['low'], by_id['D']['high']) == ('0', '100')
    evaluation = fixture.cs.read(receipt['evaluation_ref'])['payload']['body']
    assert len(evaluation['rows']) == sum(len(r['presentation_rows']) for r in fixture.plan['method_pack']['indicators']) + 1
    assert [merge for merge in evaluation['merges'] if merge['start_col'] == merge['end_col'] == 0] == [
        {'start_row': 0, 'end_row': len(evaluation['rows']) - 2, 'start_col': 0, 'end_col': 0}]
    assert len(evaluation['material_issues']) == 2
    assert all(issue['affects_level'] for issue in evaluation['material_issues'])
    assert all(issue['anchor']['column'] == 5 for issue in evaluation['material_issues'])
    assert fixture.cs.read(receipt['level_ref'])['payload']['body']['level_qualification']
    for key in ('assessment_ref', 'evidence_ref', 'ranking_ref', 'evaluation_ref', 'level_ref'):
        assert receipt[key] in receipt['refs'].values()


@pytest.mark.parametrize('fault', ['unconfirmed', 'coordinator', 'template', 'other-strategy',
    'other-object', 'missing-rank-reason', 'missing-plausible-grades'])
def test_assessment_persistence_enforces_authority_and_records_no_partial_result(method_commission, fault):
    fixture = method_commission
    saved = save(fixture)
    if fault == 'unconfirmed':
        actor = unapproved_writer(fixture, saved)
    else:
        approve(fixture, saved)
        actor = writer(fixture, saved)
    assessment = persistence_input(fixture)
    if fault == 'coordinator':
        actor = fixture.co
    elif fault == 'template':
        assessment['indicators'][0]['sources'] = [fixture.cite('template')]
    elif fault == 'other-strategy':
        assessment['weight_strategy_id'] = 'alternative-lookup'
    elif fault == 'other-object':
        assessment['object_id'] = 'S2'
    elif fault == 'missing-rank-reason':
        assessment['indicators'][0]['rank_reason'] = ''
    elif fault == 'missing-plausible-grades':
        assessment['indicators'][2]['plausible_grades'] = []
    before = len(fixture.cs.list_objects())
    with pytest.raises((ActionRejected, ActionForbidden, ValueError)):
        persist(fixture, actor, assessment)
    assert len(fixture.cs.list_objects()) == before


def test_generated_receipt_is_required_for_g3_outcomes_and_assumptions_are_assessed(method_commission):
    from test_m1_commission_coverage import content
    fixture = method_commission
    saved = save(fixture)
    approve(fixture, saved)
    actor = writer(fixture, saved)
    receipt = persist(fixture, actor)
    refs = fixture.cs.commit(actor, 'outcome-section', [
        {'client_key': 'section', 'type': 'ContentNode', 'payload': content('S1 assessment', 'chapter')},
        {'client_key': 'invented-score', 'type': 'ContentNode', 'payload': content('Invented score 1')},
        {'client_key': 'invented-level', 'type': 'ContentNode', 'payload': content('Invented level I')},
    ])['result']['refs']
    for score, level, basis, unresolved in [
        (refs['invented-score'], receipt['level_ref'], [receipt['evidence_ref']], []),
        (receipt['evaluation_ref'], refs['invented-level'], [receipt['evidence_ref']], []),
        (receipt['evaluation_ref'], receipt['level_ref'], [], []),
        (receipt['evaluation_ref'], receipt['level_ref'], [receipt['evidence_ref']], ['Assumptions unresolved']),
    ]:
        with pytest.raises((ActionRejected, ValueError)):
            api().record_outcome(fixture.cs, actor, 'invalid-' + str(len(basis)) + score['id'] + level['id'] + str(bool(unresolved)),
                'S1', refs['section'], score, level, basis, unresolved)
    result = api().record_outcome(fixture.cs, actor, 'valid-generated-outcome', 'S1',
        refs['section'], receipt['evaluation_ref'], receipt['level_ref'], [receipt['evidence_ref']], [])
    assert result['result']


def test_generated_assessment_freezes_with_source_plan_closure_and_complete_coverage(method_commission):
    from report_agent.review_coverage import commission_completion
    from test_m1_commission_coverage import content
    fixture = method_commission
    saved = save(fixture)
    approve(fixture, saved)
    actor = writer(fixture, saved)
    receipt = persist(fixture, actor)
    objects = [{'client_key': 'root', 'type': 'ContentNode',
                'payload': content('S1 assessment report', 'report')}]
    for position, key in enumerate(('ranking_ref', 'evaluation_ref', 'level_ref')):
        objects.append({'client_key': key + '-edge', 'type': 'Relation', 'payload': {
            'subject_ref': {'client_key': 'root'}, 'object_ref': receipt[key],
            'predicate': 'contains', 'position': position, 'provenance_kind': 'adopted_during_generation'}})
    root = fixture.cs.commit(actor, 'assessment-report-tree', objects)['result']['refs']['root']
    api().record_outcome(fixture.cs, actor, 'frozen-generated-outcome', 'S1', root,
        receipt['evaluation_ref'], receipt['level_ref'], [receipt['evidence_ref']], [])
    frozen = fixture.cs.freeze(fixture.co, 'freeze-generated-assessment', root, [],
        saved_receipt_ids=['save-assessment', 'assessment-report-tree'])['result']['snapshot_ref']
    snapshot = fixture.cs.read(frozen)
    assert receipt['assessment_ref'] in snapshot['payload']['refs']
    assert saved['plan_ref'] in snapshot['payload']['refs']
    assert fixture.sources['guideline'] in snapshot['payload']['refs']
    assert fixture.sources['scope'] in snapshot['payload']['refs']
    assert commission_completion(fixture.cs, snapshot)['complete'] is True


def section_plan(fixture, *, separate_slots=False):
    plan = deepcopy(fixture.plan)
    plan['sections'].insert(0, {'section_id': '1.1', 'title': 'Introduction', 'kind': 'fixed',
        'outline': fixture.cite('outline'), 'sources': [fixture.cite('template', 'Project OLD.'),
            fixture.cite('template', 'Exact method sentence.')],
        'replacements': [{'old': 'OLD', 'new': 'NEW'}]})
    derived = next(section for section in plan['sections'] if section['section_id'] == '5')
    derived['sources'] = [fixture.cite('template', 'Score {TOTAL}; level {LEVEL}.' if separate_slots else 'Summary: {SUMMARY}')]
    derived['result_bindings'] = ([
        {'old': '{TOTAL}', 'object_id': 'S1', 'field': 'total'},
        {'old': '{LEVEL}', 'object_id': 'S1', 'field': 'level'}] if separate_slots else [
        {'old': '{SUMMARY}', 'object_id': 'S1', 'field': 'assessment_text'}])
    return plan


def create_section(fixture, actor, section_id, assessment_refs=(), operation='create-section'):
    from report_agent.risk_scoring import create_planned_section
    return create_planned_section(fixture.cs, actor, operation, section_id, assessment_refs)['result']


def test_fixed_section_copies_exact_spans_and_only_declared_replacements(method_commission):
    fixture = method_commission
    saved = save(fixture, section_plan(fixture))
    approve(fixture, saved)
    actor = writer(fixture, saved, section_ids=['1.1', '4', '5'])
    result = create_section(fixture, actor, '1.1')
    record = fixture.cs.read(result['node_ref'])
    assert record['payload']['body']['text'] == 'Project NEW.\nExact method sentence.'
    assert result['node_ref'] in result['refs'].values()
    assert create_section(fixture, actor, '1.1') == result
    assert fixture.cs.read(result['node_ref']) == record


def source_view_plan(fixture):
    """Synthetic extracted pages exercise provenance checks, not image fidelity."""
    from report_agent.catalog import Catalog
    Catalog(fixture.cs.store)
    plan = section_plan(fixture)
    fixed = plan['sections'][0]
    source_id = fixture.cs.read(fixture.sources['template'])['payload']['source_id']
    with fixture.cs.store.connect() as db:
        text = ''.join(row[0] for row in db.execute(
            'SELECT text FROM source_blocks WHERE source_id=? AND locator LIKE ? ORDER BY ordinal',
            (source_id, 'manifest text;%')))
        assert text, 'Synthetic template text must exist before adding test page locations.'
        ordinal = db.execute('SELECT MAX(ordinal) FROM source_blocks WHERE source_id=?',
                             (source_id,)).fetchone()[0]
        for page in (1, 2):
            db.execute('INSERT INTO source_blocks(source_id,ordinal,locator,text) VALUES(?,?,?,?)',
                       (source_id, ordinal + page, f'page {page}', text))
    for citation in fixed['sources']:
        citation['locator'] = 'page 1'
    fixed['source_views'] = [{'source_indexes': [1], 'page': 1, 'crop': [.1, .2, .9, .8]}]
    return plan


@pytest.mark.parametrize('fault', ['negative-index', 'bool-index', 'empty-index', 'index-range',
    'noncontiguous', 'reversed-indexes', 'reversed-views', 'overlap', 'page-mismatch', 'mixed-page', 'mixed-source', 'not-fixed',
    'crop-short', 'crop-reversed', 'crop-nan', 'crop-outside', 'no-method'])
def test_source_view_plan_rejects_invalid_or_unbound_structure(method_commission, fault):
    fixture = method_commission
    plan = source_view_plan(fixture)
    fixed = plan['sections'][0]
    view = fixed['source_views'][0]
    if fault == 'negative-index': view['source_indexes'] = [-1]
    elif fault == 'bool-index': view['source_indexes'] = [True]
    elif fault == 'empty-index': view['source_indexes'] = []
    elif fault == 'index-range': view['source_indexes'] = [2]
    elif fault == 'noncontiguous':
        fixed['sources'].append(deepcopy(fixed['sources'][1]))
        view['source_indexes'] = [0, 2]
    elif fault == 'reversed-indexes': view['source_indexes'] = [1, 0]
    elif fault == 'reversed-views':
        fixed['source_views'].append({**deepcopy(view), 'source_indexes': [0]})
    elif fault == 'overlap': fixed['source_views'].append(deepcopy(view))
    elif fault == 'page-mismatch': view['page'] = 2
    elif fault == 'mixed-page':
        view['source_indexes'] = [0, 1]
        fixed['sources'][0]['locator'] = 'page 2'
    elif fault == 'mixed-source':
        view['source_indexes'] = [0, 1]
        fixed['sources'][0] = {**fixture.cite('design'), 'locator': 'page 1'}
    elif fault == 'not-fixed': fixed['kind'] = 'extracted'
    elif fault == 'crop-short': view['crop'] = [0, 0, 1]
    elif fault == 'crop-reversed': view['crop'] = [.8, .2, .1, .9]
    elif fault == 'crop-nan': view['crop'][0] = float('nan')
    elif fault == 'crop-outside': view['crop'][2] = 1.1
    else: plan.pop('method_pack')
    with pytest.raises((ValueError, ActionRejected)):
        api().CommissionPlan.model_validate(plan)


def test_source_view_materialization_preserves_text_and_binds_receipt(method_commission):
    from report_agent import report_state
    fixture = method_commission
    plan = source_view_plan(fixture)
    saved = save(fixture, plan)
    approve(fixture, saved)
    actor = writer(fixture, saved, section_ids=['1.1', '4', '5'])
    result = create_section(fixture, actor, '1.1')
    body = fixture.cs.read(result['node_ref'])['payload']['body']
    assert body['text'] == 'Project NEW.\nExact method sentence.'
    assert body['source_views'] == [{'text': 'Exact method sentence.',
        'source_ref': fixture.sources['template'],
        'source_id': fixture.cs.read(fixture.sources['template'])['payload']['source_id'],
        'page': 1, 'crop': [.1, .2, .9, .8]}]
    receipt = report_state.planned_section(fixture.cs.store, result['node_ref'])
    assert fixture.cs.read(receipt['node_ref'])['payload']['body']['source_views'] == body['source_views']
    assert 'source_views_digest' not in receipt
    assert receipt['node_ref'] == result['node_ref']
    assert receipt['commission_plan_ref'] == saved['plan_ref']
    assert create_section(fixture, actor, '1.1') == result


@pytest.mark.parametrize('fault', ['touched', 'ambiguous', 'replace-then-recreate'])
def test_source_view_refuses_changed_or_ambiguous_source_passage(method_commission, fault):
    fixture = method_commission
    plan = source_view_plan(fixture)
    fixed = plan['sections'][0]
    if fault == 'ambiguous':
        fixed['sources'].append(deepcopy(fixed['sources'][1]))
    elif fault == 'touched':
        fixed['replacements'].append({'old': 'method', 'new': 'changed'})
    else:
        fixed['replacements'] += [{'old': 'Exact method sentence.', 'new': 'Moved.'},
                                  {'old': 'Project NEW.', 'new': 'Exact method sentence.'}]
    with pytest.raises((ValueError, ActionRejected)):
        saved = save(fixture, plan)
        approve(fixture, saved)
        actor = writer(fixture, saved, section_ids=['1.1', '4', '5'])
        create_section(fixture, actor, '1.1')


@pytest.mark.parametrize('fault', ['forged-node', 'stale-plan', 'changed-crop'])
def test_source_view_export_requires_current_exact_materialized_receipt(method_commission, fault):
    from report_agent.g3_export import validate_export
    fixture = method_commission
    plan = source_view_plan(fixture)
    saved = save(fixture, plan)
    approve(fixture, saved)
    actor = writer(fixture, saved, section_ids=['1.1', '4', '5'])
    result = create_section(fixture, actor, '1.1')
    record = fixture.cs.read(result['node_ref'])
    sources = [fixture.cs.read(ref) for ref in fixture.sources.values()]
    plan_record = fixture.cs.read(saved['plan_ref'])
    def key(ref): return (ref['type'], ref['id'], ref['version'])
    def check(node, selected_plan):
        records = {key(r['ref']): r for r in [*sources, node, selected_plan]}
        snapshot = {'payload': {'root_ref': node['ref'], 'commission_plan_ref': selected_plan['ref']}}
        return validate_export(fixture.cs, snapshot, records)
    check(record, plan_record)
    if fault == 'forged-node':
        forged = fixture.cs.commit(actor, 'forge-source-view', [{'client_key': 'copy',
            'type': 'ContentNode', 'payload': deepcopy(record['payload'])}])['result']['refs']['copy']
        record = fixture.cs.read(forged)
    elif fault == 'stale-plan':
        plan['open_questions'] = ['Source view revision requires reconfirmation.']
        revised = save(fixture, plan, operation='revise-source-view-plan')
        plan_record = fixture.cs.read(revised['plan_ref'])
    else:
        record = deepcopy(record)
        record['payload']['body']['source_views'][0]['crop'][0] = .2
    with pytest.raises(ActionRejected, match='source view receipt'):
        check(record, plan_record)


@pytest.mark.parametrize('separate_slots', [False, True])
def test_derived_chapter_keeps_chapter4_result_and_qualification(method_commission, separate_slots):
    fixture = method_commission
    saved = save(fixture, section_plan(fixture, separate_slots=separate_slots))
    approve(fixture, saved)
    actor = writer(fixture, saved, section_ids=['1.1', '4', '5'])
    receipt = persist(fixture, actor)
    result = create_section(fixture, actor, '5', [receipt['assessment_ref']])
    level_body = fixture.cs.read(receipt['level_ref'])['payload']['body']
    text = fixture.cs.read(result['node_ref'])['payload']['body']['text']
    assert level_body['level_qualification']
    assert text.count(level_body['level_qualification']) == 1
    if separate_slots:
        assert receipt['result']['adopted']['total'] in text
        assert fixture.plan['table_specs']['evaluation']['level_labels'][receipt['result']['adopted']['level']] in text
    else:
        assert text == 'Summary: ' + level_body['text']
    assert result['assessment_refs'] == [receipt['assessment_ref']]


@pytest.mark.parametrize('fault', ['unknown-object', 'unknown-field', 'absent-slot', 'repeated-slot'])
def test_invalid_result_slots_cannot_create_a_derived_section(method_commission, fault):
    fixture = method_commission
    plan = section_plan(fixture)
    derived = next(section for section in plan['sections'] if section['section_id'] == '5')
    slot = derived['result_bindings'][0]
    if fault == 'unknown-object':
        slot['object_id'] = 'S2'
    elif fault == 'unknown-field':
        slot['field'] = 'invented-result'
    elif fault == 'absent-slot':
        slot['old'] = '{ABSENT}'
    else:
        derived['sources'] = [fixture.cite('template', 'Repeated {REPEAT} and {REPEAT}.')]
        slot['old'] = '{REPEAT}'
    with pytest.raises((ActionRejected, ValueError)):
        saved = save(fixture, plan)
        approve(fixture, saved)
        actor = writer(fixture, saved, section_ids=['4', '5'])
        receipt = persist(fixture, actor)
        create_section(fixture, actor, '5', [receipt['assessment_ref']])


def test_derived_section_refuses_assessment_from_previous_commission_version(method_commission):
    fixture = method_commission
    plan = section_plan(fixture)
    saved = save(fixture, plan)
    approve(fixture, saved)
    actor = writer(fixture, saved, section_ids=['4', '5'])
    receipt = persist(fixture, actor)
    revised = deepcopy(plan)
    revised['open_questions'] = ['Reconfirm this revised commissioned plan.']
    current = save(fixture, revised, operation='revised-planned-section')
    approve(fixture, current)
    current_actor = writer(fixture, current, section_ids=['4', '5'], operation='current-section-writer')
    with pytest.raises(ActionRejected, match='STALE'):
        create_section(fixture, current_actor, '5', [receipt['assessment_ref']])


def test_derived_section_requires_assigned_writer_and_unique_receipts(method_commission):
    fixture = method_commission
    saved = save(fixture, section_plan(fixture))
    approve(fixture, saved)
    actor = writer(fixture, saved)
    receipt = persist(fixture, actor)
    with pytest.raises(ActionRejected, match='ASSIGNMENT'):
        create_section(fixture, actor, '5', [receipt['assessment_ref']], operation='unassigned-section')
    assigned = writer(fixture, saved, section_ids=['5'], operation='derived-section-writer')
    with pytest.raises(ActionRejected, match='DUPLICATE'):
        create_section(fixture, assigned, '5', [receipt['assessment_ref'], receipt['assessment_ref']],
                       operation='duplicate-assessment-section')


def boundary_plan(fixture):
    plan = deepcopy(fixture.plan)
    plan['scope_boundary'] = {'start_meter': '1000', 'end_meter': '2000',
        'expected_object_count': 1,
        'source': fixture.cite('scope', 'Boundary K1+000 to K2+000; expected one in-range object.')}
    plan['inventory_attributes'].append('mileage')
    plan['objects'][0]['attributes'].append({'name': 'mileage', 'values': [
        {'value': 'K1+200-K1+400', 'source': fixture.cite('design', 'S1 K1+200-K1+400.'),
         'reason': 'Located range.'}]})
    outside = deepcopy(plan['objects'][0])
    outside.update(object_id='S2', label='Slope 2', included=False, reason='Outside commissioned boundary.')
    outside['attributes'][-1]['values'] = [{'value': 'K3+000-K3+200',
        'source': fixture.cite('design', 'S2 K3+000-K3+200.'), 'reason': 'Located external range.'}]
    plan['objects'].append(outside)
    return plan


@pytest.mark.parametrize('case,expected', [
    ('outside', True), ('inside', False), ('touching', False), ('conflicting', False),
    ('unknown', False), ('unsourced', False), ('unparseable', False),
])
def test_only_proven_outside_ranges_are_removed_from_scope_accounting(method_commission, case, expected):
    from report_agent.commission_plan import outside_boundary
    fixture = method_commission
    plan = boundary_plan(fixture)
    obj = deepcopy(plan['objects'][1])
    values = obj['attributes'][-1]['values']
    if case == 'inside':
        values[0]['value'] = 'K1+500-K1+700'
    elif case == 'touching':
        values[0]['value'] = 'K2+000-K2+200'
    elif case == 'conflicting':
        values.append({'value': 'K1+500-K1+700',
            'source': fixture.cite('design', 'Conflicting S2 K1+500-K1+700.'), 'reason': 'Contradictory source retained.'})
    elif case == 'unknown':
        values.append({'value': None, 'source': None, 'reason': 'Not established.'})
    elif case == 'unsourced':
        values[0]['source'] = None
    elif case == 'unparseable':
        values[0]['value'] = 'See site drawing; mileage not transcribed.'
    assert outside_boundary(plan, obj) is expected


def test_scope_count_discrepancy_is_question_not_silent_object_removal(method_commission):
    fixture = method_commission
    plan = boundary_plan(fixture)
    plan['scope_boundary']['expected_object_count'] = 5
    saved = save(fixture, plan)
    payload = api().read_plan(fixture.ws.store)['payload']
    assert len(payload['objects']) == 2
    assert payload['method_questions']
    with pytest.raises(ActionRejected):
        approve(fixture, saved)


@pytest.mark.parametrize('basis', ['design-and-scope', 'design-alone', 'template', 'guideline'])
def test_numeric_scope_boundary_needs_customer_selection_and_factual_range(method_commission, basis):
    fixture = method_commission
    plan = boundary_plan(fixture)
    boundary = plan['scope_boundary']
    boundary['source'] = fixture.cite('design', 'First contract K1+000-K2+000.')
    if basis != 'design-alone':
        boundary['customer_basis'] = fixture.cite('scope', 'Select first contract.')
    if basis in ('template', 'guideline'):
        boundary['source'] = fixture.cite(basis)
    if basis == 'design-and-scope':
        saved = save(fixture, plan)
        checkpoint, _ = approve(fixture, saved)
        brief = brief_text(fixture, checkpoint)
        assert 'Select first contract.' in brief
        assert 'First contract K1+000-K2+000.' in brief
    else:
        with pytest.raises((ActionRejected, ValueError)):
            save(fixture, plan)


def test_boundary_preserves_inventory_and_does_not_reduce_an_in_range_unassessed_object(method_commission):
    from report_agent.review_coverage import commission_completion
    from test_m1_commission_coverage import content
    fixture = method_commission
    plan = boundary_plan(fixture)
    plan['objects'][0].update(included=False, origin='interpretation', reason='Agent suggests omission.')
    saved = save(fixture, plan)
    approve(fixture, saved)
    actor = writer(fixture, saved)
    root = fixture.cs.commit(actor, 'boundary-report', [{'client_key': 'root', 'type': 'ContentNode',
        'payload': content('Inventory preserved; assessments absent.', 'report')}])['result']['refs']['root']
    frozen = fixture.cs.freeze(fixture.co, 'boundary-snapshot', root, [root])['result']['snapshot_ref']
    snapshot = fixture.cs.read(frozen)
    coverage = commission_completion(fixture.cs, snapshot)
    assert coverage['complete'] is False
    assert {obj['object_id'] for obj in coverage['missing_objects']} == {'S1'}
    assert coverage['reduced_objects'] == []
    assert all(ref in snapshot['payload']['refs'] for ref in saved['inventory_refs'])


def test_generic_content_commit_rejects_fabricated_source_quotation(method_commission):
    from test_m1_commission_coverage import content
    fixture = method_commission
    saved = save(fixture)
    approve(fixture, saved)
    actor = writer(fixture, saved)
    payload = content('Source-backed statement.')
    payload['citations'] = [fixture.cite('design', 'The design explicitly authorizes this fabricated assertion.')]
    before = len(fixture.cs.list_objects())
    with pytest.raises(ActionRejected, match='QUOTE'):
        fixture.cs.commit(actor, 'fabricated-quotation', [
            {'client_key': 'fake', 'type': 'ContentNode', 'payload': payload}])
    assert len(fixture.cs.list_objects()) == before


def aggregate_plan(fixture):
    plan = section_plan(fixture)
    second = deepcopy(plan['objects'][0])
    second.update(object_id='S2', label='Slope 2')
    plan['objects'].append(second)
    derived = next(section for section in plan['sections'] if section['section_id'] == '5')
    derived['sources'] = [fixture.cite('template', 'Objects {COUNT}; level II {II_COUNT}; level III {III_COUNT}.')]
    derived['result_bindings'] = [
        {'old': '{COUNT}', 'field': 'object_count'},
        {'old': '{II_COUNT}', 'field': 'level_count', 'level': 'II'},
        {'old': '{III_COUNT}', 'field': 'level_count', 'level': 'III'}]
    return plan


def second_assessment(fixture):
    assessment = persistence_input(fixture)
    assessment['object_id'] = 'S2'
    for row in assessment['indicators']:
        row.update(value='60', grade_id='g3', basis_kind='direct_evidence',
                   sources=[fixture.cite('design')], question='', plausible_grades=[])
    return assessment


def test_aggregate_summary_uses_exact_immutable_assessment_set(method_commission):
    fixture = method_commission
    saved = save(fixture, aggregate_plan(fixture))
    approve(fixture, saved)
    actor = writer(fixture, saved, section_ids=['4', '5'])
    first = persist(fixture, actor)
    second = persist(fixture, actor, second_assessment(fixture), operation='save-second-assessment')
    refs = [first['assessment_ref'], second['assessment_ref']]
    result = create_section(fixture, actor, '5', refs)
    body = fixture.cs.read(result['node_ref'])['payload']['body']
    assert body['text'] == 'Objects 2; level II 1; level III 1.'
    assert body['assessment_refs'] == refs
    assert body['commission_plan_ref'] == saved['plan_ref']


@pytest.mark.parametrize('fault', ['missing', 'duplicate', 'unknown-level'])
def test_aggregate_cannot_silently_count_partial_duplicate_or_unknown_level_results(method_commission, fault):
    fixture = method_commission
    plan = aggregate_plan(fixture)
    if fault == 'unknown-level':
        plan['sections'][-1]['result_bindings'][1]['level'] = 'V'
    saved = save(fixture, plan)
    approve(fixture, saved)
    actor = writer(fixture, saved, section_ids=['4', '5'])
    first = persist(fixture, actor)
    second = persist(fixture, actor, second_assessment(fixture), operation='save-second-assessment')
    refs = [first['assessment_ref'], second['assessment_ref']]
    if fault == 'missing':
        refs.pop()
    elif fault == 'duplicate':
        refs.append(first['assessment_ref'])
    with pytest.raises(ActionRejected):
        create_section(fixture, actor, '5', refs)


@pytest.mark.parametrize('exclusion', ['owner-reduction', 'proven-outside'])
def test_aggregate_excludes_only_owner_reductions_or_proven_outside_objects(method_commission, exclusion):
    fixture = method_commission
    plan = aggregate_plan(fixture)
    reductions = []
    if exclusion == 'owner-reduction':
        reductions = [{'object_id': 'S2', 'reason': 'Owner excludes S2 for this commission.'}]
    else:
        boundary = boundary_plan(fixture)
        for key in ('objects', 'inventory_attributes', 'scope_boundary'):
            plan[key] = boundary[key]
    saved = save(fixture, plan)
    approve(fixture, saved, reductions=reductions)
    actor = writer(fixture, saved, section_ids=['4', '5'])
    first = persist(fixture, actor)
    result = create_section(fixture, actor, '5', [first['assessment_ref']])
    assert fixture.cs.read(result['node_ref'])['payload']['body']['text'] == 'Objects 1; level II 1; level III 0.'


@pytest.mark.parametrize('fault', ['commission-basis', 'guideline-only-fact', 'applied-without-guideline'])
def test_indicator_basis_requires_the_planned_factual_source_and_applied_rule(method_commission, fault):
    fixture = method_commission
    saved = save(fixture)
    approve(fixture, saved)
    actor = writer(fixture, saved)
    assessment = persistence_input(fixture)
    if fault == 'commission-basis':
        assessment['indicators'][0]['sources'] = [fixture.cite('scope')]
    elif fault == 'guideline-only-fact':
        assessment['indicators'][0]['sources'] = [fixture.cite('guideline')]
    else:
        assessment['indicators'][1]['sources'] = [fixture.cite('design')]
    with pytest.raises(ActionRejected):
        persist(fixture, actor, assessment)


def test_multiple_extracted_assignments_require_explicit_assessment_section(method_commission):
    fixture = method_commission
    plan = deepcopy(fixture.plan)
    other = deepcopy(plan['sections'][0])
    other.update(section_id='1.3', title='Background')
    plan['sections'].append(other)
    saved = save(fixture, plan)
    approve(fixture, saved)
    actor = writer(fixture, saved, section_ids=['1.3', '4'])
    assessment = persistence_input(fixture)
    with pytest.raises(ActionRejected, match='SECTION'):
        persist(fixture, actor, assessment, operation='ambiguous-assessment-section')
    assessment['section_id'] = '4'
    receipt = persist(fixture, actor, assessment, operation='explicit-assessment-section')
    assert fixture.cs.read(receipt['evaluation_ref'])['payload']['body']['section_id'] == '4'


def test_no_evidence_shortlist_cannot_suppress_full_uncertainty(method_commission):
    fixture = method_commission
    saved = save(fixture)
    approve(fixture, saved)
    actor = writer(fixture, saved)
    assessment = persistence_input(fixture)
    assessment['indicators'][3]['plausible_grades'] = ['g4']
    receipt = persist(fixture, actor, assessment)
    row = next(row for row in fixture.cs.read(receipt['assessment_ref'])['payload']['indicators']
               if row['indicator_id'] == 'D')
    assert set(row['plausible_grades']) == {'g1', 'g2', 'g3', 'g4'}
    assert (row['low'], row['high']) == ('0', '100')
