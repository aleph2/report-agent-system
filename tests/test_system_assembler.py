"""Deterministic assembly preserves producer records and rejects incomplete inputs."""
from report_agent import issue_state, report_state
from copy import deepcopy

import pytest

from report_agent import plan_authority
from report_agent.content_models import Ref, refs_in
from report_agent.content_store import Actor
from report_agent.errors import ActionForbidden, ActionRejected
from report_agent.store import digest, encode
from report_agent.system_assembler import assemble_report, preflight_assembly
from test_m1_commission_plan import approve, save, writer
from test_m1_g3_integration import method_commission, persist, persistence_input, section_plan


@pytest.fixture
def assembly_input(method_commission, request):
    f = method_commission
    plan = section_plan(f)
    issue_mode = getattr(request, 'param', None)
    if issue_mode in {'missing-issue', 'complete-issue'}:
        plan['reconciliations'][0]['differences'] = ['Design has 30 metres; survey value is absent.']
    if issue_mode == 'owner-issue':
        from report_agent.commission_owner_records import install_owner_records
        from test_m1_g5_j1 import owner
        record = owner('object_fact', 'S1', {'height': '30 m'})
        record['open_facts'] = [{'id': 'retained-conflict', 'kind': 'conflict', 'object_label': 'Slope 1',
            'basis': 'A retained survey discrepancy needs designer review.', 'sources': [f.cite('design')],
            'adopted_value': 'Use the approved design inventory', 'question': 'Designer to clarify the survey difference.',
            'affects_level': False}]
        install_owner_records(f.cs, {'contract': 'owner-records-v1', 'records': [record],
            'documents': [], 'substitutions': [], 'objects': []}, list(f.sources.values()))
        plan['sections'].insert(1, {'section_id': '1.3', 'title': 'Scope', 'kind': 'extracted',
            'outline': f.cite('outline'), 'sources': [f.cite('design')]})
        from report_agent.commission_owner_records import decorate_plan
        with f.ws.store.connect() as db:
            plan = decorate_plan(f.cs, db, plan)
    saved = save(f, plan)
    approve(f, saved)
    actor = writer(f, saved, section_ids=[s['section_id'] for s in plan['sections']])
    assessment = persist(f, actor, {**persistence_input(f), "section_id": "4"})
    def node(text, kind='block'):
        return {'kind': kind, 'body': {'text': text}, 'qualifiers': {},
                'claim_kind': 'fact' if kind == 'block' else 'structure',
                'citations': [f.cite('design')]}
    objects = [
        {'client_key': 'root', 'type': 'ContentNode', 'payload': node('Synthetic report', 'report')},
        {'client_key': 'prose', 'type': 'ContentNode', 'payload': node('S1 design height is 30 metres.')},
    ]
    if issue_mode == 'owner-issue':
        objects.append({'client_key': 'scope', 'type': 'ContentNode', 'payload': node('The approved scope is S1.')})
    required = f.cs.read(plan_authority.decision_ref(f.ws.store))['payload']['required_material_issues']
    if issue_mode == 'complete-issue':
        from report_agent.system_assembler import record_issue_routes
        record_issue_routes(f.cs, Actor('operator', 'operator', 'synthetic-route'), 'reviewed-route',
            {required[0]['id']: {'section_id': '4', 'reason': 'The retained design discrepancy serves this assessment section.'}},
            note='Synthetic operator reviewed the source and destination.')
        objects[1]['payload']['body']['material_issues'] = [{**required[0], 'adopted_value': '30 metres',
            'affects_level': False, 'anchor': {'text': '30 metres'}}]
    for position, ref in enumerate([{'client_key': 'prose'}, *([{'client_key': 'scope'}] if issue_mode == 'owner-issue' else []), *[assessment[k] for k in ('ranking_ref', 'evaluation_ref', 'level_ref')]]):
        objects.append({'client_key': 'edge' + str(position), 'type': 'Relation', 'payload': {
            'subject_ref': {'client_key': 'root'}, 'object_ref': ref, 'predicate': 'contains',
            'position': position, 'provenance_kind': 'adopted_during_generation'}})
    tree = f.cs.commit(actor, 'initial-tree', objects)['result']['refs']
    snapshot = f.cs.freeze(f.co, 'initial-snapshot', tree['root'], [],
        saved_receipt_ids=['save-assessment', 'initial-tree'])['result']['snapshot_ref']
    f.inputs = dict(source_snapshot_ref=snapshot, prose_bindings={'4': [tree['prose']]},
                    assessment_refs=[assessment['assessment_ref']], issue_bindings={})
    if issue_mode == 'owner-issue':
        f.inputs['prose_bindings']['1.3'] = [tree['scope']]
    if issue_mode == 'complete-issue':
        f.inputs['issue_bindings'] = {required[0]['id']: {'section_id': '4'}}
    f.required = required
    f.prose, f.assessment, f.writer = tree['prose'], assessment, actor
    return f


def test_assembly_rejects_missing_canonical_assessments_without_creating_content(assembly_input):
    f = assembly_input
    args = {**f.inputs, 'assessment_refs': []}
    before = f.cs.list_objects()
    report = preflight_assembly(f.cs, f.co, **args)
    assert report['missing_assessments'] == ['S1']
    with pytest.raises(ActionRejected, match='ASSEMBLY_INPUT_INCOMPLETE') as exc:
        assemble_report(f.cs, f.co, 'missing-assessment', **args)
    assert exc.value.diagnostic['missing_assessments'] == ['S1']
    assert f.cs.list_objects() == before


def test_assembly_requires_explicit_prose_bindings_and_keeps_missing_sections_visible(assembly_input):
    f = assembly_input
    result = preflight_assembly(f.cs, f.co, **{**f.inputs, 'prose_bindings': {}})
    assert result['missing_prose_bindings'] == ['4']


def test_complete_assembly_preserves_originals_and_closes_all_references(assembly_input):
    f = assembly_input
    original = deepcopy(f.cs.read(f.prose))
    result = assemble_report(f.cs, f.co, 'assemble', **f.inputs)['result']
    snapshot = f.cs.read(result['snapshot_ref'])
    records = {Ref.model_validate(r).key(): f.cs.read(r) for r in snapshot['payload']['refs']}
    assert all(r.key() in records for record in records.values() for r in refs_in(record['payload']))
    assert f.cs.read(f.prose) == original
    assert f.prose not in snapshot['payload']['refs']
    prose = [r for r in records.values() if r['ref']['type'] == 'ContentNode'
             and r['payload']['body'].get('text') == original['payload']['body']['text']]
    assert len(prose) == 1
    assert prose[0]['payload']['citations'] == original['payload']['citations']
    assert prose[0]['payload']['body']['section_id'] == '4'
    assert all(f.assessment[k] in snapshot['payload']['refs'] for k in ('ranking_ref', 'evaluation_ref', 'level_ref'))
    assert snapshot['payload']['commission_outcome_refs']
    receipt = report_state.assembly(f.ws.store, result['snapshot_ref'])
    assert receipt['snapshot_ref'] == snapshot['ref']
    assert receipt['commission_plan_ref'] == snapshot['payload']['commission_plan_ref']
    assert 'manifest_digest' not in receipt
    assert receipt['source_snapshot_ref'] == f.inputs['source_snapshot_ref']
    assert assemble_report(f.cs, f.co, 'assemble', **f.inputs)['result'] == result


def test_assembly_rejects_wrong_caller_and_cross_task_section_binding(assembly_input):
    f = assembly_input
    with pytest.raises(ActionForbidden):
        assemble_report(f.cs, f.writer, 'writer-assemble', **f.inputs)
    with pytest.raises(ActionForbidden):
        assemble_report(f.cs, Actor('different-coordinator', 'coordinator', 'x'), 'foreign-assemble', **f.inputs)
    other = writer(f, {'plan_ref': f.cs.read(f.inputs['source_snapshot_ref'])['payload']['commission_plan_ref']},
                   section_ids=['5'], operation='other-writer')
    def change_owner(db):
        record = f.cs.read(f.prose)
        return f.cs._insert(db, other, 'ContentNode', record['payload'])
    # A saved node outside the frozen snapshot must not be smuggled in as prose.
    outside = f.cs.operation(f.co, 'outside-node', {}, change_owner)['result']
    with pytest.raises(ActionRejected, match='ASSEMBLY_INPUT_INCOMPLETE'):
        assemble_report(f.cs, f.co, 'outside-binding', **{**f.inputs, 'prose_bindings': {'4': [outside]}})


@pytest.mark.parametrize('assembly_input', ['missing-issue'], indirect=True)
def test_missing_full_issue_record_is_reported_without_inventing_adopted_value(assembly_input):
    f = assembly_input
    preflight = preflight_assembly(f.cs, f.co, **f.inputs)
    assert preflight['missing_issue_records'] == [f.required[0]['id']]
    assert preflight['missing_issue_bindings'] == [f.required[0]['id']]


@pytest.mark.parametrize('assembly_input', ['complete-issue'], indirect=True)
def test_required_issue_receives_position_anchor_and_word_excel_match(assembly_input):
    from zipfile import ZipFile
    from xml.etree import ElementTree as ET
    from openpyxl import load_workbook
    from report_agent.content_export import export_snapshot
    from report_agent.material_issues import rendered_issues, validate_required_issues
    from report_agent.g3_export import validate_export
    f = assembly_input
    assembled = assemble_report(f.cs, f.co, 'complete-issue-assembly', **f.inputs)['result']
    snapshot = f.cs.read(assembled['snapshot_ref'])
    records = {_key(r): f.cs.read(r) for r in snapshot['payload']['refs']}
    issues = rendered_issues(records, snapshot['payload']['root_ref'])
    required = next(i for _, i in issues if i.id == f.required[0]['id'])
    assert required.anchor.model_dump() == {'paragraph_index': 0, 'start': 0, 'end': None}
    validate_export(f.cs, snapshot, records)
    with f.ws.store.connect() as db:
        validate_required_issues(f.cs, db, snapshot, records, issues)
    output = export_snapshot(f.cs, f.co, 'assembled-pair', assembled['snapshot_ref'], {'toc': False})['result']
    with ZipFile(f.ws.store.root / output['file_ref']) as archive:
        comments = ET.fromstring(archive.read('word/comments.xml'))
        texts = [''.join(c.itertext()) for c in comments]
    assert len(texts) == len(issues)
    assert any('Design has 30 metres' in t for t in texts)
    book = load_workbook(f.ws.store.root / output['workbook']['file_ref'])
    rows = list(book['资料澄清清单'].values)
    assert len(rows) - 1 == len(issues)
    mapping = f.cs.read(output['workbook']['mapping_ref'])['payload']['anchor_records']
    for _, issue in issues:
        anchors = [m for m in mapping if m.get('issue_id') == issue.id]
        assert len(anchors) == 1
        row = rows[anchors[0]['row_start'] - 1]
        assert row[4:7] == (issue.basis, issue.adopted_value, issue.question)


def _key(ref):
    return Ref.model_validate(ref).key()


def test_assembly_preserves_mixed_version_refusal(assembly_input):
    from report_agent.system_assembler import _closure
    f = assembly_input
    original = f.cs.read(f.prose)
    def revise(db):
        return f.cs._insert(db, f.writer, 'ContentNode', original['payload'], id=f.prose['id'], version=2, previous_ref=f.prose)
    revised = f.cs.operation(f.writer, 'version-two', {}, revise)['result']
    with f.ws.store.connect() as db, pytest.raises(ActionRejected, match='MIXED_LOGICAL_VERSIONS'):
        _closure(f.cs, db, [f.prose, revised])


def select_current(f):
    plan = f.cs.read(f.inputs['source_snapshot_ref'])['payload']['commission_plan_ref']
    report_state.select_prose(f.ws.store, 'prose:' + encode([plan, '4', None]), f.prose, actor=f.writer)
    f.ws.store.set('g6_assessment:' + digest([plan, 'S1']), f.assessment['assessment_ref'])
    for issue_id, binding in f.inputs['issue_bindings'].items():
        issue_state.set_g6_issue_binding(f.ws.store, digest([plan, issue_id]), binding)
    return plan


@pytest.mark.parametrize('assembly_input', ['complete-issue'], indirect=True)
def test_route_revision_preserves_history_and_frozen_export(assembly_input):
    from report_agent.content_export import export_snapshot
    from report_agent.system_assembler import record_issue_routes, require_assembled
    f = assembly_input
    plan = f.cs.read(f.inputs['source_snapshot_ref'])['payload']['commission_plan_ref']
    issue_id = f.required[0]['id']
    key = digest([plan, issue_id])
    frozen = assemble_report(f.cs, f.co, 'before-route-revision', **f.inputs)['result']['snapshot_ref']
    with f.ws.store.connect() as db:
        original = issue_state.get_g6_issue_route(db, key)
    operator = Actor('operator', 'operator', 'route-revision')
    response = record_issue_routes(f.cs, operator, 'revise-route',
        {issue_id: {'section_id': '4', 'object_id': 'S1', 'reason': 'Reviewed for this slope.'}},
        note='Revised placement.')
    assert record_issue_routes(f.cs, operator, 'revise-route',
        {issue_id: {'section_id': '4', 'object_id': 'S1', 'reason': 'Reviewed for this slope.'}},
        note='Revised placement.') == response
    with f.ws.store.connect() as db:
        versions = db.execute("SELECT data FROM content_versions WHERE type='IssueRoute' AND id=? ORDER BY version", (key,)).fetchall()
        import json
        assert len(versions) == 2 and json.loads(versions[0][0])['payload'] == original
        receipt = require_assembled(f.cs, db, f.cs._read(db, frozen))
        assert receipt['operator_issue_routes'][issue_id] == original
    pair = export_snapshot(f.cs, f.co, 'frozen-route-pair', frozen, {'toc': False})['result']
    assert (f.ws.store.root / pair['workbook']['file_ref']).is_file()


def test_current_route_assembles_without_agent_snapshot_and_requires_receipt(assembly_input):
    from report_agent.system_assembler import assemble_current_report, require_assembled
    from report_agent.content_export import export_snapshot
    f = assembly_input
    select_current(f)
    result = assemble_current_report(f.cs, f.co, 'current-assembly')['result']
    snapshot = f.cs.read(result['snapshot_ref'])
    with f.ws.store.connect() as db:
        receipt = require_assembled(f.cs, db, snapshot)
    assert receipt['source_snapshot_ref'] is None
    assert receipt['source_kind'] == 'current-selections'
    assert assemble_current_report(f.cs, f.co, 'current-assembly')['result'] == result
    pair = export_snapshot(f.cs, f.co, 'current-pair', result['snapshot_ref'], {'toc': False})['result']
    assert (f.ws.store.root / pair['workbook']['file_ref']).exists()
    with pytest.raises(ActionRejected, match='REPORT_PROVENANCE_IMMUTABLE'):
        report_state.record_assembly(f.ws.store, result['snapshot_ref'], {**receipt, 'source_kind': 'altered'})


def test_current_route_rejects_stale_issue_proposal_and_preserves_saved_prose(assembly_input):
    from report_agent.system_assembler import assemble_current_report
    f = assembly_input
    plan = select_current(f)
    original = deepcopy(f.cs.read(f.prose))
    issue = {'id': 'extra-proof', 'kind': 'missing', 'object_label': 'Slope 1',
             'basis': 'The source omits a survey measurement.', 'sources': [],
             'adopted_value': '30 metres', 'question': 'Verify the missing measurement.',
             'affects_level': False, 'anchor': {'paragraph_index': 0, 'start': 0, 'end': None}}
    key = 'g6_issue_record:' + digest([plan, issue['id']])
    issue_state.set_g6_issue_record(f.ws.store, key.split(':', 1)[1], {'node_ref': f.prose, 'issue': issue})
    result = assemble_current_report(f.cs, f.co, 'current-with-issue')['result']
    snapshot = f.cs.read(result['snapshot_ref'])
    from report_agent.material_issues import rendered_issues
    records = {_key(r): f.cs.read(r) for r in snapshot['payload']['refs']}
    assert any(i.id == issue['id'] for _, i in rendered_issues(records, snapshot['payload']['root_ref']))
    assert f.cs.read(f.prose) == original
    issue_state.set_g6_issue_record(f.ws.store, key.split(':', 1)[1], {'node_ref': {**f.prose, 'id': 'unselected-node'}, 'issue': issue})
    with pytest.raises(ActionRejected, match='ASSEMBLY_INPUT_INCOMPLETE') as exc:
        assemble_current_report(f.cs, f.co, 'stale-proposal')
    assert any(p['code'] == 'stale_issue_proposal' for p in exc.value.diagnostic['problems'])


@pytest.mark.parametrize('assembly_input', ['owner-issue'], indirect=True)
def test_owner_issue_routes_automatically_to_1_3_and_exports_once(assembly_input):
    from report_agent.content_export import export_snapshot
    from report_agent.commission_owner_records import material_issues
    from docx import Document
    from openpyxl import load_workbook
    f = assembly_input
    result = assemble_report(f.cs, f.co, 'owner-auto-assembly', **f.inputs)['result']
    receipt = report_state.assembly(f.ws.store, result['snapshot_ref'])
    owner_id = next(i['id'] for i in f.required if i['id'].startswith('owner:'))
    target = f.cs.read(receipt['issue_targets'][owner_id])['payload']
    assert target['body']['section_id'] == '1.3'
    snapshot = f.cs.read(result['snapshot_ref'])
    plan = f.cs.read(snapshot['payload']['commission_plan_ref'])['payload']
    expected = next(i.model_dump() for i in material_issues(f.cs, plan) if i.id == owner_id)
    actual = next(i for i in target['body']['material_issues'] if i['id'] == owner_id)
    assert {k:v for k,v in actual.items() if k != 'anchor'} == {k:v for k,v in expected.items() if k != 'anchor'}
    pair = export_snapshot(f.cs, f.co, 'owner-auto-pair', result['snapshot_ref'], {'toc': False})['result']
    doc = Document(f.ws.store.root / pair['file_ref'])
    assert sum('A retained survey discrepancy' in i.text for i in doc.comments) == 1
    rows = list(load_workbook(f.ws.store.root / pair['workbook']['file_ref'])['资料澄清清单'].values)
    assert sum('A retained survey discrepancy' in str(row) for row in rows) == 1
    with pytest.raises(ActionRejected, match='ASSEMBLY_INPUT_INCOMPLETE') as exc:
        assemble_report(f.cs, f.co, 'wrong-owner-route', **{**f.inputs, 'issue_bindings': {owner_id: {'section_id': '4'}}})
    assert any(p['code'] in {'owner_issue_requires_section_1_3', 'issue_route_conflicts_with_system'} for p in exc.value.diagnostic['problems'])


def test_rescue_accounts_for_unbound_saved_prose(assembly_input):
    f = assembly_input
    report = preflight_assembly(f.cs, f.co, **{**f.inputs, 'prose_bindings': {'4': []}})
    assert report['unbound_source_nodes'] == [f.prose]
    assert report['ready'] is False


@pytest.mark.parametrize('assembly_input', ['complete-issue'], indirect=True)
def test_writer_binding_cannot_replace_operator_issue_route(assembly_input):
    from report_agent.system_assembler import record_issue_routes
    f = assembly_input
    issue_id = f.required[0]['id']
    with pytest.raises(ActionForbidden):
        record_issue_routes(f.cs, f.writer, 'writer-route',
            {issue_id: {'section_id': '5', 'reason': 'Wrong location'}}, note='Untrusted writer route')
    args = {**f.inputs, 'issue_bindings': {issue_id: {'section_id': '5'}}}
    report = preflight_assembly(f.cs, f.co, **args)
    assert not report['ready']
    assert any(p['code'] == 'issue_route_conflicts_with_system' for p in report['problems'])


def test_selected_frozen_prose_still_requires_original_writer_section_assignment(assembly_input):
    f = assembly_input
    source = f.cs.read(f.inputs['source_snapshot_ref'])
    wrong_writer = writer(f, {'plan_ref': source['payload']['commission_plan_ref']}, section_ids=['5'], operation='wrong-task')
    def insert(db):
        node = f.cs._insert(db, wrong_writer, 'ContentNode', f.cs.read(f.prose)['payload'])
        edge = f.cs._insert(db, wrong_writer, 'Relation', {'subject_ref': source['payload']['root_ref'],
            'object_ref': node, 'predicate': 'contains', 'position': 100, 'provenance_kind': 'adopted_during_generation'})
        return {'node': node, 'edge': edge}
    added = f.cs.operation(wrong_writer, 'wrong-owned-node', {}, insert)['result']
    frozen = f.cs.freeze(f.co, 'wrong-owned-snapshot', source['payload']['root_ref'],
                         [*source['payload']['refs'], *added.values()])['result']['snapshot_ref']
    report = preflight_assembly(f.cs, f.co, **{**f.inputs, 'source_snapshot_ref': frozen,
        'prose_bindings': {'4': [f.prose, added['node']]}})
    assert any(p['code'] == 'writer_section_unassigned' for p in report['problems'])


@pytest.mark.parametrize('assembly_input', ['owner-issue'], indirect=True)
def test_automatic_owner_routes_do_not_mutate_inputs_or_break_operation_retry(assembly_input):
    f = assembly_input
    original = deepcopy(f.inputs)
    assert preflight_assembly(f.cs, f.co, **f.inputs)['ready']
    assert f.inputs == original
    first = assemble_report(f.cs, f.co, 'owner-idempotent', **f.inputs)
    assert f.inputs == original
    assert assemble_report(f.cs, f.co, 'owner-idempotent', **f.inputs) == first
    receipt = report_state.assembly(f.ws.store, first['result']['snapshot_ref'])
    assert receipt['resolved_issue_bindings'] == {f.required[0]['id']: {'section_id': '1.3'}}


def test_current_assembly_retry_rechecks_later_score_withdrawal(assembly_input, monkeypatch):
    from report_agent import system_assembler as assembly
    f = assembly_input
    select_current(f)
    operation = 'selected-score-retry'
    saved = assembly.assemble_current_report(f.cs, f.co, operation)
    monkeypatch.setattr(assembly, 'assessment_receipt',
                        lambda db, ref: {**f.assessment, 'derivation_status': 'stale'})
    with pytest.raises(ActionRejected, match='CURRENT_SCORE_UNAVAILABLE: stale'):
        assembly.assemble_current_report(f.cs, f.co, operation)
    assert f.cs.receipt(f.co, operation)['response'] == saved
