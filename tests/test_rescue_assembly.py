"""Assembler integration for provenance-verified rescue prose and structural parents."""
from report_agent import issue_state
from copy import deepcopy

import pytest

from report_agent.errors import ActionRejected
from report_agent.store import digest
from report_agent.rescue_projection import project_rescue_prose
from report_agent.system_assembler import assemble_current_report
from test_m1_commission_plan import approve, save, writer
from test_m1_g3_integration import method_commission, section_plan, persist, persistence_input


@pytest.fixture
def rescued_input(method_commission, request):
    f = method_commission
    plan = section_plan(f)
    extra = [{'section_id': sid, 'title': title, 'kind': 'extracted',
              'outline': f.cite('outline'), 'sources': [f.cite('design')]}
             for sid, title in [('2', 'Project'), ('2.1', 'Project facts'), ('2.2', 'Setting')]]
    plan['sections'][1:1] = extra
    mode = getattr(request, 'param', None)
    if mode == 'site':
        plan['objects'][0]['object_id'] = 'HP-01-K1p200-R'
        for section in plan['sections']:
            for binding in section.get('result_bindings', []):
                if binding.get('object_id') == 'S1':
                    binding['object_id'] = 'HP-01-K1p200-R'
    saved = save(f, plan); approve(f, saved)
    f.plan_ref = saved['plan_ref']
    actor = writer(f, saved, section_ids=[s['section_id'] for s in plan['sections']])
    assessment = persist(f, actor, {**persistence_input(f), 'section_id': '4', 'object_id': plan['objects'][0]['object_id']})
    def prose(sid, title, text):
        return {'kind': 'chapter' if sid == '2.1' else 'block',
                'body': {'text': sid + ' ' + title + '\n' + text}, 'qualifiers': {},
                'citations': [f.cite('design')], 'claim_kind': 'fact'}
    objects = [
        {'client_key': 'root', 'type': 'ContentNode', 'payload': {'kind': 'report',
            'body': {'text': 'Preserved original project report title'}, 'qualifiers': {}, 'citations': [], 'claim_kind': 'structure'}},
        {'client_key': 'parent', 'type': 'ContentNode', 'payload': {'kind': 'chapter',
            'body': {'text': '2 Project'}, 'qualifiers': {}, 'citations': [], 'claim_kind': 'structure'}},
        {'client_key': 'assessment-head', 'type': 'ContentNode', 'payload': {'kind': 'chapter',
            'body': {'text': '4 Assessment'}, 'qualifiers': {}, 'citations': [], 'claim_kind': 'structure'}},
        {'client_key': 'p1', 'type': 'ContentNode', 'payload': prose('2.1', 'Project facts', 'The design height is 30 m.')},
        {'client_key': 'p2', 'type': 'ContentNode', 'payload': prose('2.2', 'Setting', 'The design supplies the project setting.')},
    ]
    if mode == 'parent-prose':
        objects[1]['payload']['body']['text'] += '\nUnique parent facts must not disappear.'
    if mode == 'site':
        objects.append({'client_key': 'site', 'type': 'ContentNode', 'payload': {
            'kind': 'block', 'body': {'text': 'HP-01设计边坡高度30 m，保留独有现场事实。'
                '本边坡综合得分F＝56.32，风险等级Ⅲ级，需开展专项施工安全风险评估。'},
            'qualifiers': {}, 'citations': [f.cite('design')], 'claim_kind': 'fact'}})
    pairs = [('root', 'parent', 0), ('root', 'assessment-head', 1), ('parent', 'p1', 0), ('parent', 'p2', 1)]
    if mode == 'site':
        pairs.append(('assessment-head', 'site', 0))
    for index, (parent, child, position) in enumerate(pairs):
        objects.append({'client_key': 'edge' + str(index), 'type': 'Relation', 'payload': {
            'subject_ref': {'client_key': parent}, 'object_ref': {'client_key': child}, 'position': position,
            'predicate': 'contains', 'provenance_kind': 'adopted_during_generation'}})
    refs = f.cs.commit(actor, 'rescue-original-tree', objects)['result']['refs']
    frozen = f.cs.freeze(f.co, 'rescue-original-snapshot', refs['root'], list(refs.values()))['result']['snapshot_ref']
    bindings = {'2.1': [refs['p1']], '2.2': [refs['p2']]}
    replacement = {}
    if mode == 'site':
        bindings['4'] = [refs['site']]
        replacement[refs['site']['id']] = assessment['assessment_ref']
    projected = project_rescue_prose(f.cs, f.co, 'rescue-projections', source_snapshot_ref=frozen,
        bindings=bindings, qualifier_dispositions={}, assessment_replacements=replacement)['result']['section_bindings']
    for sid, selected in projected.items():
        f.ws.store.set('g6_section_prose:' + digest([saved['plan_ref'], sid]), selected)
    f.ws.store.set('g6_assessment:' + digest([saved['plan_ref'], plan['objects'][0]['object_id']]), assessment['assessment_ref'])
    f.original_refs, f.original_snapshot, f.projected, f.writer = refs, frozen, projected, actor
    f.assessment = assessment
    return f


def test_verified_rescue_assembles_empty_parents_and_preserves_title(rescued_input):
    from report_agent.content_export import export_snapshot
    f = rescued_input
    before = {k: f.cs.read(r) for k,r in f.original_refs.items()}
    result = assemble_current_report(f.cs, f.co, 'rescue-assemble')['result']
    snapshot = f.cs.read(result['snapshot_ref'])
    root = f.cs.read(snapshot['payload']['root_ref'])['payload']
    assert root['body']['text'] == 'Preserved original project report title'
    assert not set(r['id'] for r in snapshot['payload']['refs']).intersection(r['id'] for r in f.original_refs.values())
    assert all(f.cs.read(f.original_refs[k]) == record for k,record in before.items())
    receipt = f.ws.store.get('assembly_receipt:' + digest(result['snapshot_ref']))
    assert set(receipt['structural_parent_refs']) == {'2', '4'}
    assert receipt['rescue_source_snapshot_ref'] == f.original_snapshot
    pair = export_snapshot(f.cs, f.co, 'rescue-pair', result['snapshot_ref'], {'toc': False})['result']
    assert (f.ws.store.root / pair['workbook']['file_ref']).exists()


def test_fake_coordinator_prose_is_still_rejected(rescued_input):
    f = rescued_input
    original = f.cs.read(f.projected['2.1'][0])['payload']
    def fake(db):
        return f.cs._insert(db, f.co, 'ContentNode', original)
    ref = f.cs.operation(f.co, 'fake-coordinator-copy', {}, fake)['result']
    f.ws.store.set('g6_section_prose:' + digest([f.plan_ref, '2.1']), ref)
    with pytest.raises(ActionRejected, match='ASSEMBLY_INPUT_INCOMPLETE') as exc:
        assemble_current_report(f.cs, f.co, 'fake-rescue-assemble')
    assert any(p['code'] == 'rescue_projection_invalid' for p in exc.value.diagnostic['problems'])


def test_heading_parent_cannot_hide_missing_descendant(rescued_input):
    f = rescued_input
    f.ws.store.set('g6_section_prose:' + digest([f.plan_ref, '2.2']), [])
    with pytest.raises(ActionRejected, match='ASSEMBLY_INPUT_INCOMPLETE') as exc:
        assemble_current_report(f.cs, f.co, 'missing-child')
    assert any(p['code'] == 'empty_extracted_section' and p['section_id'] == '2.2'
               for p in exc.value.diagnostic['problems'])
    assert '2' in exc.value.diagnostic['missing_prose_bindings']


def test_projections_from_mixed_source_snapshots_are_not_combined(rescued_input):
    f = rescued_input
    old = f.cs.read(f.original_snapshot)
    second = f.cs.freeze(f.co, 'second-source-snapshot', old['payload']['root_ref'], old['payload']['refs'])['result']['snapshot_ref']
    copied = project_rescue_prose(f.cs, f.co, 'second-source-projection', source_snapshot_ref=second,
        bindings={'2.2':[f.original_refs['p2']]}, qualifier_dispositions={})['result']['section_bindings']['2.2']
    f.ws.store.set('g6_section_prose:' + digest([f.plan_ref, '2.2']), copied)
    with pytest.raises(ActionRejected, match='ASSEMBLY_INPUT_INCOMPLETE') as exc:
        assemble_current_report(f.cs, f.co, 'mixed-rescue')
    assert any(p['code'] == 'rescue_source_snapshots_mixed' for p in exc.value.diagnostic['problems'])


@pytest.mark.parametrize('rescued_input', ['site'], indirect=True)
def test_verified_site_facts_precede_their_own_canonical_tables(rescued_input):
    f = rescued_input
    result = assemble_current_report(f.cs, f.co, 'site-interleaved')['result']
    snapshot = f.cs.read(result['snapshot_ref'])
    outcome = f.cs.read(snapshot['payload']['commission_outcome_refs'][0])['payload']
    edges = [f.cs.read(r)['payload'] for r in snapshot['payload']['refs'] if r['type'] == 'Relation']
    children = [p['object_ref'] for p in sorted(
        (p for p in edges if p['predicate'] == 'contains' and p['subject_ref'] == outcome['section_ref']),
        key=lambda p: p['position'])]
    assert children[1:] == [f.assessment[k] for k in ('ranking_ref', 'evaluation_ref', 'level_ref')]
    text = f.cs.read(children[0])['payload']['body']['text']
    assert text == 'HP-01设计边坡高度30 m，保留独有现场事实。'
    assert '本边坡综合得分' not in text
    assert '本边坡综合得分F＝56.32' in f.cs.read(f.original_refs['site'])['payload']['body']['text']


def test_current_issue_proposal_does_not_change_projection_verification(rescued_input):
    from report_agent.material_issues import rendered_issues
    from report_agent.content_models import Ref
    f = rescued_input
    issue = {'id':'retained-current-source-issue', 'kind':'unclear', 'object_label':'Project facts',
        'basis':'Designer must resolve the retained source uncertainty.', 'sources':[{'document':'design','page':'manifest text'}],
        'adopted_value':'30 m', 'question':'Verify the original source discrepancy.', 'affects_level':True,
        'anchor':{'paragraph_index':0,'start':0,'end':None}}
    ref = f.projected['2.1'][0]
    original = deepcopy(f.cs.read(ref))
    issue_state.set_g6_issue_record(f.ws.store, digest([f.plan_ref,issue['id']]), {'node_ref':ref,'issue':issue})
    result = assemble_current_report(f.cs, f.co, 'projection-with-current-issue')['result']
    snapshot = f.cs.read(result['snapshot_ref'])
    records = {Ref.model_validate(r).key():f.cs.read(r) for r in snapshot['payload']['refs']}
    assert sum(i.id == issue['id'] for _,i in rendered_issues(records,snapshot['payload']['root_ref'])) == 1
    assert f.cs.read(ref) == original


@pytest.mark.parametrize('rescued_input', ['parent-prose'], indirect=True)
def test_real_parent_prose_is_not_mistaken_for_an_empty_structural_heading(rescued_input):
    f = rescued_input
    with pytest.raises(ActionRejected, match='ASSEMBLY_INPUT_INCOMPLETE') as exc:
        assemble_current_report(f.cs, f.co, 'missing-parent-facts')
    assert '2' in exc.value.diagnostic['missing_prose_bindings']


def test_forged_projection_payload_keeps_digest_check_with_current_issue_overlay(rescued_input):
    f = rescued_input
    original_ref = f.projected['2.1'][0]
    changed = deepcopy(f.cs.read(original_ref)['payload'])
    changed['body']['text'] += ' Unsupported extra grade IV.'
    def insert(db):
        return f.cs._insert(db, f.co, 'ContentNode', changed)
    fake = f.cs.operation(f.co, 'forged-projection-payload', {}, insert)['result']
    receipt = f.ws.store.get('rescue_projection:' + digest(original_ref))
    receipt['projection_ref'] = fake
    f.ws.store.set('rescue_projection:' + digest(fake), receipt)
    f.ws.store.set('g6_section_prose:' + digest([f.plan_ref,'2.1']), fake)
    with pytest.raises(ActionRejected, match='ASSEMBLY_INPUT_INCOMPLETE') as exc:
        assemble_current_report(f.cs, f.co, 'forged-projection-assembly')
    assert any(p['code'] == 'rescue_projection_invalid' and 'PAYLOAD_DIGEST_MISMATCH' in p['reason']
               for p in exc.value.diagnostic['problems'])
