"""Synthetic rescue prose projection: immutability, scope, and visible caveats."""
from copy import deepcopy

import pytest

from report_agent.content_models import Ref
from report_agent.errors import ActionForbidden, ActionRejected
from report_agent.store import digest
from report_agent.rescue_projection import project_rescue_prose, verify_projection
from test_m1_commission_plan import approve, save, writer
from test_m1_g3_integration import method_commission, section_plan


@pytest.fixture
def projection_input(method_commission):
    f = method_commission
    plan = section_plan(f)
    plan['sections'].insert(1, {'section_id': '2', 'title': 'Other extracted section', 'kind': 'extracted',
        'outline': f.cite('outline'), 'sources': [f.cite('design')]})
    saved = save(f, plan)
    approve(f, saved)
    actor = writer(f, saved, section_ids=['4'])
    source = {'kind': 'chapter', 'body': {'text': '4 Assessment\r\nDesign height is 30 m; survey evidence is incomplete.\nKeep this second line.'},
              'qualifiers': {'material_issues': ['Survey evidence is incomplete.', 'The height needs designer confirmation.'],
                             'generation_state': 'The formatter completed its node pass.'},
              'citations': [f.cite('design')], 'claim_kind': 'fact'}
    result = f.cs.commit(actor, 'projection-source', [
        {'client_key': 'root', 'type': 'ContentNode', 'payload': {'kind': 'report', 'body': {'text': 'Synthetic report'},
            'qualifiers': {}, 'citations': [], 'claim_kind': 'structure'}},
        {'client_key': 'prose', 'type': 'ContentNode', 'payload': source},
        {'client_key': 'edge', 'type': 'Relation', 'payload': {'subject_ref': {'client_key': 'root'},
            'object_ref': {'client_key': 'prose'}, 'predicate': 'contains', 'position': 0,
            'provenance_kind': 'adopted_during_generation'}}])['result']['refs']
    snapshot = f.cs.freeze(f.co, 'projection-source-snapshot', result['root'], list(result.values()))['result']['snapshot_ref']
    f.prose = result['prose']; f.snapshot = snapshot; f.actor = actor; f.plan = f.cs.read(saved['plan_ref'])
    f.dispositions = {f.prose['id']: {
        'material_issues': [{'index': index, 'kind': 'visible_issue', 'issue': {
            'id': 'rescue-caveat-' + str(index), 'kind': 'missing', 'object_label': 'Slope 1',
            'basis': caveat, 'sources': [{'document': 'design', 'page': 'manifest text'}],
            'adopted_value': '30 m', 'question': 'Designer to verify retained source limitations.',
            'anchor': {'paragraph_index': 0, 'start': 0, 'end': None}, 'affects_level': False}}
            for index, caveat in enumerate(source['qualifiers']['material_issues'])],
        'generation_state': [{'kind': 'generation_record', 'classification': 'execution_only',
            'rationale': 'Formatter status is execution metadata, not a source condition.',
            'evidence': 'The saved text reports a completed formatter node pass.'}]}}
    f.args = dict(source_snapshot_ref=snapshot, bindings={'4': [f.prose]}, qualifier_dispositions=f.dispositions)
    return f


def test_projection_requires_each_unsupported_qualifier_item_before_writes(projection_input):
    f = projection_input
    before = f.cs.list_objects()
    with pytest.raises(ActionRejected, match='RESCUE_QUALIFIER_DISPOSITIONS_INCOMPLETE') as exc:
        project_rescue_prose(f.cs, f.co, 'missing-dispositions', **{**f.args, 'qualifier_dispositions': {}})
    assert len(exc.value.diagnostic['missing']) == 3
    assert f.cs.list_objects() == before


def test_projection_preserves_body_citations_and_original_writer(projection_input):
    f = projection_input
    original = deepcopy(f.cs.read(f.prose)); args_before = deepcopy(f.args)
    result = project_rescue_prose(f.cs, f.co, 'project', **f.args)['result']
    ref = result['section_bindings']['4'][0]
    projected = f.cs.read(ref)
    assert projected['owner_id'] == f.co.id
    assert projected['payload']['kind'] == 'block'
    assert projected['payload']['body']['text'] == original['payload']['body']['text'].partition('\n')[2]
    assert projected['payload']['citations'] == original['payload']['citations']
    assert projected['payload']['claim_kind'] == original['payload']['claim_kind']
    assert projected['payload']['qualifiers'] == {}
    assert len(projected['payload']['body']['material_issues']) == 2
    with f.ws.store.connect() as db:
        receipt = verify_projection(f.cs, db, projected, '4', f.plan, f.co)
    assert receipt['source_ref'] == f.prose
    assert receipt['archived_qualifiers'] == original['payload']['qualifiers']
    assert receipt['removed_structural_span']['text'] == '4 Assessment\r\n'
    assert f.cs.read(f.prose) == original and f.args == args_before
    assert project_rescue_prose(f.cs, f.co, 'project', **f.args)['result'] == result


def test_projection_refuses_lost_caveat_and_invented_issue_source(projection_input):
    f = projection_input
    bad = deepcopy(f.dispositions)
    bad[f.prose['id']]['material_issues'][0]['issue']['basis'] = 'General clarification.'
    with pytest.raises(ActionRejected, match='CAVEAT_NOT_PRESERVED'):
        project_rescue_prose(f.cs, f.co, 'lost-caveat', **{**f.args, 'qualifier_dispositions': bad})
    bad = deepcopy(f.dispositions)
    bad[f.prose['id']]['material_issues'][0]['issue']['sources'][0]['page'] = 99
    with pytest.raises(ActionRejected, match='ISSUE_SOURCE_NOT_BOUND'):
        project_rescue_prose(f.cs, f.co, 'invented-page', **{**f.args, 'qualifier_dispositions': bad})


def test_projection_does_not_allow_writer_impersonation_or_fixed_section(projection_input):
    f = projection_input
    with pytest.raises(ActionForbidden):
        project_rescue_prose(f.cs, f.actor, 'writer-projection', **f.args)
    with pytest.raises(ActionRejected, match='EXTRACTED_SECTION_REQUIRED'):
        project_rescue_prose(f.cs, f.co, 'fixed-projection', **{**f.args, 'bindings': {'1.1': [f.prose]}})


def test_projection_receipt_detects_body_tampering(projection_input):
    f = projection_input
    result = project_rescue_prose(f.cs, f.co, 'project-tamper', **f.args)['result']
    projected = f.cs.read(result['section_bindings']['4'][0])
    projected['payload']['body']['text'] += ' Changed grade IV.'
    with f.ws.store.connect() as db, pytest.raises(ActionRejected, match='PROJECTION_PAYLOAD_DIGEST'):
        verify_projection(f.cs, db, projected, '4', f.plan, f.co)


@pytest.mark.parametrize('text,expected,removed', [
    ('4 Assessment\nActual 30 m fact.', 'Actual 30 m fact.', True),
    ('4 Assessment \nActual 30 m fact.', '4 Assessment \nActual 30 m fact.', False),
    ('Introduction\n4 Assessment\nActual 30 m fact.', 'Introduction\n4 Assessment\nActual 30 m fact.', False),
])
def test_only_the_exact_first_heading_line_is_removed(text, expected, removed):
    from report_agent.rescue_projection import _text_projection
    value, span = _text_projection(text, '4', 'Assessment')
    assert value == expected and (span is not None) == removed


def test_heading_only_has_no_prose_to_project():
    from report_agent.rescue_projection import _text_projection
    with pytest.raises(ActionRejected, match='HEADING_ONLY'):
        _text_projection('4 Assessment\n', '4', 'Assessment')


def test_original_writer_task_limits_projection_to_assigned_sections(projection_input):
    f = projection_input
    with pytest.raises(ActionForbidden, match='section assignment'):
        project_rescue_prose(f.cs, f.co, 'wrong-section', **{**f.args, 'bindings': {'2': [f.prose]}})


def test_generation_archive_needs_evidence_and_real_system_replacement(projection_input):
    f = projection_input
    bad = deepcopy(f.dispositions)
    bad[f.prose['id']]['generation_state'][0].pop('evidence')
    with pytest.raises(ActionRejected, match='DISPOSITION_EVIDENCE_REQUIRED'):
        project_rescue_prose(f.cs, f.co, 'archive-without-evidence', **{**f.args, 'qualifier_dispositions': bad})
    def fake(db):
        return f.cs._insert(db, f.actor, 'ContentNode', {'kind': 'block', 'body': {'text': 'Fabricated fixed marker',
            'planned_section': True}, 'qualifiers': {}, 'citations': [], 'claim_kind': 'structure'})
    fake_ref = f.cs.operation(f.actor, 'fake-replacement', {}, fake)['result']
    bad = deepcopy(f.dispositions)
    bad[f.prose['id']]['generation_state'][0].update(classification='superseded', replacement_ref=fake_ref)
    with pytest.raises(ActionRejected, match='SYSTEM_REPLACEMENT_REQUIRED'):
        project_rescue_prose(f.cs, f.co, 'fake-replacement-projection', **{**f.args, 'qualifier_dispositions': bad})


def test_broad_writer_assignment_does_not_authorize_mislabelling_source_section(projection_input):
    f = projection_input
    broad = writer(f, {'plan_ref': f.plan['ref']}, section_ids=['2', '4'], operation='broad-writer')
    source = deepcopy(f.cs.read(f.prose)['payload'])
    def insert(db):
        root = f.cs._insert(db, broad, 'ContentNode', {'kind': 'report', 'body': {'text': 'Synthetic report'},
            'qualifiers': {}, 'citations': [], 'claim_kind': 'structure'})
        node = f.cs._insert(db, broad, 'ContentNode', source)
        edge = f.cs._insert(db, broad, 'Relation', {'subject_ref': root, 'object_ref': node,
            'predicate': 'contains', 'position': 0, 'provenance_kind': 'adopted_during_generation'})
        return {'root':root, 'node':node, 'edge':edge}
    refs = f.cs.operation(broad, 'mislabelling-source', {}, insert)['result']
    frozen = f.cs.freeze(f.co, 'mislabelling-snapshot', refs['root'], list(refs.values()))['result']['snapshot_ref']
    with pytest.raises(ActionRejected, match='SECTION_IDENTITY_AMBIGUOUS'):
        project_rescue_prose(f.cs, f.co, 'mislabelling-projection', source_snapshot_ref=frozen,
            bindings={'2':[refs['node']]}, qualifier_dispositions={refs['node']['id']: f.dispositions[f.prose['id']]})


@pytest.fixture
def site_projection(method_commission):
    from test_m1_g3_integration import persist, persistence_input
    f = method_commission
    f.plan['objects'][0]['object_id'] = 'HP-01-K1p200-R'
    plan = section_plan(f)
    saved = save(f, plan)
    approve(f, saved)
    f.actor = writer(f, saved, section_ids=['4'])
    f.plan = f.cs.read(saved['plan_ref'])
    assessment = persistence_input(f)
    assessment['object_id'] = 'HP-01-K1p200-R'
    f.canonical = persist(f, f.actor, assessment)
    return f


def frozen_site(f, text, ancestor='4 Assessment', body_sid=None):
    def insert(db):
        def node(kind, text):
            return f.cs._insert(db, f.actor, 'ContentNode', {'kind': kind, 'body': {'text': text},
                'qualifiers': {}, 'citations': [f.cite('design')], 'claim_kind': 'fact'})
        root = node('report', 'Synthetic report')
        heading = node('chapter', ancestor)
        object_heading = node('chapter', '4.2 HP-01')
        payload = {'kind': 'block', 'body': {'text': text}, 'qualifiers': {},
            'citations': [f.cite('design')], 'claim_kind': 'fact'}
        if body_sid is not None:
            payload['body']['section_id'] = body_sid
        prose = f.cs._insert(db, f.actor, 'ContentNode', payload)
        refs = {'root': root, 'heading': heading, 'object_heading': object_heading, 'prose': prose}
        for i, (parent, child) in enumerate([(root, heading), (heading, object_heading), (object_heading, prose)]):
            refs['edge' + str(i)] = f.cs._insert(db, f.actor, 'Relation', {'subject_ref': parent,
                'object_ref': child, 'predicate': 'contains', 'position': 0,
                'provenance_kind': 'adopted_during_generation'})
        return refs
    refs = f.cs.operation(f.actor, 'site-source', {}, insert)['result']
    snapshot = f.cs.freeze(f.co, 'site-snapshot', refs['root'], list(refs.values()))['result']['snapshot_ref']
    return refs['prose'], dict(source_snapshot_ref=snapshot, bindings={'4': [refs['prose']]},
        qualifier_dispositions={})


@pytest.mark.parametrize('sentence', [
    '本边坡综合得分F＝56.32，风险等级Ⅲ级，需开展专项施工安全风险评估。',
    '本边坡综合得分F＝34.10，风险等级Ⅱ级，不需开展专项施工安全风险评估。',
])
def test_terminal_result_replacement_preserves_exact_site_facts_and_source(site_projection, sentence):
    f = site_projection
    prefix = 'HP-01 边坡设计最大高度30m；地勘未覆盖。\n原有限制条件保留。'
    prose, args = frozen_site(f, prefix + sentence)
    original = deepcopy(f.cs.read(prose))
    result = project_rescue_prose(f.cs, f.co, 'replace-site-result', **args,
        assessment_replacements={prose['id']: f.canonical['assessment_ref']})['result']
    projected = f.cs.read(result['section_bindings']['4'][0])
    assert projected['payload']['body'] == {'text': prefix, 'section_id': '4'}
    assert projected['payload']['citations'] == original['payload']['citations']
    assert f.cs.read(prose) == original
    with f.ws.store.connect() as db:
        receipt = verify_projection(f.cs, db, projected, '4', f.plan, f.co)
    assert receipt['assessment_replacement'] == {'assessment_ref': f.canonical['assessment_ref'],
        'object_id': 'HP-01-K1p200-R', 'removed_result_span': {
            'start': len(prefix), 'end': len(prefix + sentence), 'text': sentence}}
    assert 'assessment_ref' not in projected['payload']['body']


@pytest.mark.parametrize('text', [
    'HP-01 设计高度30m。',
    'HP-01 设计高度30m。本边坡综合得分F＝56.32，风险等级Ⅲ级，需开展专项施工安全风险评估。后续事实。',
    'HP-01 本边坡综合得分F＝56.32，风险等级Ⅲ级，需开展专项施工安全风险评估。'
        '本边坡综合得分F＝56.32，风险等级Ⅲ级，需开展专项施工安全风险评估。',
    'HP-010 设计高度30m。本边坡综合得分F＝56.32，风险等级Ⅲ级，需开展专项施工安全风险评估。',
])
def test_result_replacement_refuses_absent_nonterminal_multiple_or_wrong_object(site_projection, text):
    f = site_projection
    prose, args = frozen_site(f, text)
    before = f.cs.list_objects()
    with pytest.raises(ActionRejected, match='RESCUE_(RESULT|ASSESSMENT)'):
        project_rescue_prose(f.cs, f.co, 'invalid-result', **args,
            assessment_replacements={prose['id']: f.canonical['assessment_ref']})
    assert f.cs.list_objects() == before


@pytest.mark.parametrize('fault', ['missing_receipt', 'wrong_ref', 'wrong_object', 'wrong_plan'])
def test_result_replacement_requires_canonical_assessment_bound_to_source(site_projection, fault):
    from report_agent.commission_plan import _set
    f = site_projection
    prose, args = frozen_site(f, 'HP-01 设计高度30m。本边坡综合得分F＝56.32，风险等级Ⅲ级，需开展专项施工安全风险评估。')
    ref = f.canonical['assessment_ref']
    if fault == 'missing_receipt':
        with f.ws.store.connect() as db:
            _set(db, 'assessment_receipt:' + digest(ref), None)
    elif fault == 'wrong_ref':
        ref = prose
    else:
        payload = deepcopy(f.cs.read(ref)['payload'])
        payload['object_id' if fault == 'wrong_object' else 'commission_plan_ref'] = ('HP-02-K1p400-L' if fault == 'wrong_object' else prose)
        def insert(db):
            new = f.cs._insert(db, f.actor, 'Assessment', payload)
            _set(db, 'assessment_receipt:' + digest(new), {**f.canonical, 'assessment_ref': new})
            return new
        ref = f.cs.operation(f.actor, 'forged-assessment', {}, insert)['result']
    with pytest.raises(ActionRejected, match='RESCUE_ASSESSMENT'):
        project_rescue_prose(f.cs, f.co, 'noncanonical-result', **args,
            assessment_replacements={prose['id']: ref})


@pytest.mark.parametrize('heading', ['4 Assessment ', '2 Other extracted section', 'Unlabelled heading'])
def test_unlabelled_prose_requires_exact_approved_heading_ancestor(site_projection, heading):
    f = site_projection
    _, args = frozen_site(f, 'HP-01 设计高度30m。', ancestor=heading)
    with pytest.raises(ActionRejected, match='SECTION_(IDENTITY|ANCESTRY)'):
        project_rescue_prose(f.cs, f.co, 'ambiguous-ancestor', **args)


def test_exact_heading_ancestor_authorizes_unlabelled_site_prose(site_projection):
    f = site_projection
    prose, args = frozen_site(f, 'HP-01 设计高度30m。')
    result = project_rescue_prose(f.cs, f.co, 'exact-ancestor', **args)['result']
    projected = f.cs.read(result['section_bindings']['4'][0])
    assert projected['payload']['body']['text'] == f.cs.read(prose)['payload']['body']['text']


@pytest.mark.parametrize('fault', ['stale', 'outcome_link', 'span'])
def test_canonical_identity_and_exact_removed_span_are_rechecked(site_projection, fault):
    from report_agent.commission_plan import _set
    f = site_projection
    prose, args = frozen_site(f, 'HP-01 设计高度30m。本边坡综合得分F＝56.32，风险等级Ⅲ级，需开展专项施工安全风险评估。')
    result = project_rescue_prose(f.cs, f.co, 'recheck-result', **args,
        assessment_replacements={prose['id']: f.canonical['assessment_ref']})['result']
    projected = f.cs.read(result['section_bindings']['4'][0])
    with f.ws.store.connect() as db:
        if fault == 'stale':
            _set(db, 'g6_assessment:' + digest([f.plan['ref'], 'HP-01-K1p200-R']), prose)
        elif fault == 'outcome_link':
            invalid = {**f.canonical, 'level_ref': prose}
            _set(db, 'assessment_receipt:' + digest(f.canonical['assessment_ref']), invalid)
        else:
            receipt = verify_projection(f.cs, db, projected, '4', f.plan, f.co)
            receipt['assessment_replacement']['removed_result_span']['start'] += 1
            _set(db, 'rescue_projection:' + digest(projected['ref']), receipt)
        with pytest.raises(ActionRejected, match='(ASSESSMENT|OUTCOME)'):
            verify_projection(f.cs, db, projected, '4', f.plan, f.co)
