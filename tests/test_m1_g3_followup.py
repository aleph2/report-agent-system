"""G3 follow-up: immutable known-conflict obligations and source-exact tables."""
from copy import deepcopy

import pytest

from report_agent.errors import ActionRejected
from test_m1_commission_plan import api, approve, commission, save, writer
from test_m1_g3_integration import method_commission, persist, persistence_input, brief_text


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    import socket
    monkeypatch.setenv('LANGSMITH_TRACING', 'false')
    monkeypatch.setenv('LANGCHAIN_TRACING_V2', 'false')
    def forbidden(*args, **kwargs):
        raise AssertionError('NETWORK_FORBIDDEN_IN_G3_FOLLOWUP')
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket.socket, 'connect_ex', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)


def conflict_plan(fixture):
    plan = deepcopy(fixture.plan)
    plan['reconciliations'][0]['differences'] = [
        'Survey omits S5.', 'S2 design height30m differs from survey28m.']
    return plan


def confirmed_requirements(fixture):
    current = api().read_plan(fixture.cs.store)
    confirmation = fixture.cs.read(current['commission_confirmation_ref'])
    assert current['required_material_issues'] == confirmation['payload']['required_material_issues']
    return confirmation, current['required_material_issues']


@pytest.mark.parametrize('reduce_object', [False, True])
def test_confirmation_generates_each_known_conflict_without_writer(commission, reduce_object):
    fixture = commission
    saved = save(fixture, conflict_plan(fixture))
    assert api().read_plan(fixture.cs.store).get('required_material_issues', []) == []
    reductions = [{'object_id': 'S2', 'reason': 'Owner excludes this object from assessment.'}] if reduce_object else []
    approve(fixture, saved, reductions=reductions)
    confirmation, issues = confirmed_requirements(fixture)
    assert confirmation['payload']['plan_ref'] == saved['plan_ref']
    assert len(issues) == 3 and len({issue['id'] for issue in issues}) == 3
    assert not fixture.cs.list_objects('ContentNode')
    for issue in issues:
        assert set(issue) == {'id', 'kind', 'object_label', 'basis', 'sources', 'question'}
        assert issue['kind'] == 'conflict'
        assert issue['object_label'].strip() and issue['basis'].strip() and issue['question'].strip()
        assert issue['sources'] and all(source['document'] and source['page'] for source in issue['sources'])
    assert sum('Survey omits S5.' in issue['basis'] for issue in issues) == 1
    assert sum('S2 design height30m differs from survey28m.' in issue['basis'] for issue in issues) == 1
    attribute = next(issue for issue in issues if issue['object_label'] == 'Slope 2')
    assert 'height' in attribute['basis'] and '30 m' in attribute['basis'] and '28 m' in attribute['basis']
    assert {source['document'] for source in attribute['sources']} == {'design', 'survey'}


@pytest.mark.parametrize('second_value, expected_count', [('30 m', 2), (None, 3)])
def test_attribute_obligations_count_distinct_values_including_unknown(commission, second_value, expected_count):
    fixture = commission
    plan = conflict_plan(fixture)
    plan['objects'][1]['attributes'][0]['values'][1]['value'] = second_value
    saved = save(fixture, plan)
    approve(fixture, saved)
    _, issues = confirmed_requirements(fixture)
    assert len(issues) == expected_count


def test_declined_confirmation_does_not_create_accepted_issue_obligations(commission):
    fixture = commission
    saved = save(fixture, conflict_plan(fixture))
    checkpoint = api().request_checkpoint(fixture.ws)
    api().reply(fixture.ws, checkpoint['issue_id'], {'plan_ref': saved['plan_ref'],
        'approved': False, 'corrections': 'Recheck the height conflict.', 'reductions': []})
    decisions = fixture.cs.list_objects('CommissionDecision')
    assert len(decisions) == 1
    assert not decisions[0]['payload'].get('required_material_issues')
    current = api().read_plan(fixture.cs.store)
    assert not current.get('required_material_issues')
    assert not current.get('commission_confirmation_ref')


def test_confirmation_replay_preserves_required_ids_and_version(commission):
    fixture = commission
    saved = save(fixture, conflict_plan(fixture))
    checkpoint, decision = approve(fixture, saved)
    first = deepcopy(confirmed_requirements(fixture))
    api().reply(fixture.ws, checkpoint['issue_id'], decision)
    assert confirmed_requirements(fixture) == first
    assert len(fixture.cs.list_objects('CommissionDecision')) == 1


def test_new_plan_requires_new_conflict_ids_and_hides_previous_approval(commission):
    fixture = commission
    plan = conflict_plan(fixture)
    saved = save(fixture, plan)
    approve(fixture, saved)
    original_confirmation, original_issues = confirmed_requirements(fixture)
    revised = deepcopy(plan)
    revised['reconciliations'][0]['result'] = 'Retain the same conflicts for explicit renewed review.'
    current = save(fixture, revised, operation='revised-conflict-plan')
    assert not api().read_plan(fixture.cs.store).get('required_material_issues')
    assert not api().read_plan(fixture.cs.store).get('commission_confirmation_ref')
    approve(fixture, current)
    new_confirmation, new_issues = confirmed_requirements(fixture)
    assert new_confirmation['ref'] != original_confirmation['ref']
    assert len(new_issues) == len(original_issues) == 3
    assert {i['id'] for i in original_issues}.isdisjoint(i['id'] for i in new_issues)
    assert fixture.cs.read(original_confirmation['ref']) == original_confirmation


def test_operator_input_cannot_inject_required_issue_records(commission):
    fixture = commission
    saved = save(fixture, conflict_plan(fixture))
    checkpoint = api().request_checkpoint(fixture.ws)
    with pytest.raises((ValueError, ActionRejected)):
        api().reply(fixture.ws, checkpoint['issue_id'], {'plan_ref': saved['plan_ref'],
            'approved': True, 'corrections': '', 'reductions': [], 'required_material_issues': []})
    assert not fixture.cs.list_objects('CommissionDecision')


def test_snapshot_freezes_confirmation_and_its_required_issues(commission):
    fixture = commission
    plan = conflict_plan(fixture)
    saved = save(fixture, plan)
    approve(fixture, saved)
    confirmation, issues = confirmed_requirements(fixture)
    actor = writer(fixture, saved, section_ids=['4'])
    node = fixture.cs.commit(actor, 'conflict-draft', [{'client_key': 'root', 'type': 'ContentNode',
        'payload': {'kind': 'report', 'body': {'text': 'Conflict review draft.', 'section_id': '4'},
                    'claim_kind': 'structure', 'qualifiers': {}}}])['result']['refs']['root']
    frozen = fixture.cs.freeze(actor, 'conflict-snapshot', node, [node])['result']['snapshot_ref']
    snapshot = fixture.cs.read(frozen)
    assert snapshot['payload']['commission_confirmation_ref'] == confirmation['ref']
    assert confirmation['ref'] in snapshot['payload']['refs']
    assert saved['plan_ref'] in snapshot['payload']['refs']
    assert fixture.cs.read(confirmation['ref'])['payload']['required_material_issues'] == issues
    revised = deepcopy(plan)
    revised['open_questions'] = ['New version, same known material conflicts.']
    current = save(fixture, revised, operation='next-conflict-plan')
    approve(fixture, current)
    assert fixture.cs.read(frozen) == snapshot
    assert confirmed_requirements(fixture)[0]['ref'] != confirmation['ref']


def test_separate_reconciliations_preserve_every_difference(commission):
    fixture = commission
    plan = conflict_plan(fixture)
    second = deepcopy(plan['reconciliations'][0])
    second['differences'] = ['S3 mileage differs between design and survey.']
    second['result'] = 'Keep this independent discrepancy for review.'
    plan['reconciliations'].append(second)
    saved = save(fixture, plan)
    approve(fixture, saved)
    _, issues = confirmed_requirements(fixture)
    assert len(issues) == len({issue['id'] for issue in issues}) == 4
    for reconciliation in plan['reconciliations']:
        for difference in reconciliation['differences']:
            assert sum(issue['basis'] == difference for issue in issues) == 1


def alternate_table_spec():
    """A different table shape proves the compiler is not slope-specific."""
    return {'table_type': 'asset_summary', 'version': 1,
        'sources': [{'source_ref': {'type': 'SourceArtifact', 'id': 'template', 'version': 1},
                     'locator': 'page 3', 'quote': 'Asset summary header.'}],
        'headers': [{'text': '资产', 'columns': ['asset']},
                    {'text': '测量', 'children': [{'text': '次序', 'columns': ['rank']},
                                                {'text': '结果（Q）', 'columns': ['result']}]}],
        'column_bindings': {'asset': 'asset_label', 'rank': 'rank', 'result': 'measurement'},
        'row_groups': [{'binding': 'measurements.rows', 'merges': []}],
        'caption_pattern': '表{number} {name}',
        'caption_bindings': {'number': 'measurements.number', 'name': 'object_label'},
        'sort': [{'binding': 'rank', 'direction': 'ascending'}], 'level_labels': {}}


class SavedTableRecords:
    """Read-only record API unit fixture; real persistence is tested in commission tests."""
    def __init__(self, spec=None):
        self.plan_ref = {'type': 'CommissionPlan', 'id': 'plan', 'version': 3}
        self.assessment_ref = {'type': 'Assessment', 'id': 'assessment', 'version': 2}
        self.plan = {'table_specs': {'asset_summary': spec or alternate_table_spec()}}
        self.assessment = {'commission_plan_ref': deepcopy(self.plan_ref),
            'table_records': {'object_label': '东侧资产', 'measurements': {'number': '7-2', 'rows': [
                {'asset_label': 'B', 'rank': 10, 'measurement': '17.250'},
                {'asset_label': 'A', 'rank': 2, 'measurement': '0.006'}]}}}
        self.reads = []

    def _read(self, db, ref):
        assert db == 'read-only-db'
        self.reads.append(deepcopy(ref))
        if ref == self.plan_ref:
            return {'ref': ref, 'payload': deepcopy(self.plan)}
        if ref == self.assessment_ref:
            return {'ref': ref, 'payload': deepcopy(self.assessment)}
        raise ActionRejected('UNKNOWN_FIXTURE_REF')

    def render(self):
        from report_agent.table_spec import render_saved_table
        return render_saved_table(self, 'read-only-db', self.plan_ref, self.assessment_ref, 'asset_summary')


def test_header_tree_compiles_exact_text_and_two_axis_spans():
    from report_agent.table_spec import compile_header
    header = compile_header(alternate_table_spec())
    assert header['columns'] == ['资产', '次序', '结果（Q）']
    assert header['header_rows'] == [['资产', '测量', ''], ['', '次序', '结果（Q）']]
    assert sorted(header['header_merges'], key=lambda m: m['start_col']) == [
        {'start_row': 0, 'end_row': 1, 'start_col': 0, 'end_col': 0},
        {'start_row': 0, 'end_row': 0, 'start_col': 1, 'end_col': 2}]


def test_generic_projection_reads_pinned_records_preserves_values_and_numeric_rank_order():
    saved = SavedTableRecords()
    body = saved.render()
    assert body['rows'] == [['A', '2', '0.006'], ['B', '10', '17.250']]
    assert body['row_origins'] == [{'binding': 'measurements.rows', 'index': 1},
                                   {'binding': 'measurements.rows', 'index': 0}]
    assert body['caption'] == '表7-2 东侧资产'
    assert saved.plan_ref in saved.reads and saved.assessment_ref in saved.reads
    # The source values are strings: presentation cannot round or recompute them.
    saved.assessment['table_records']['measurements']['rows'][1]['measurement'] = '9.0010'
    assert saved.render()['rows'][0][2] == '9.0010'


@pytest.mark.parametrize('mutation', ['literal_rows', 'widths', 'formula', 'binding_literal',
                                    'numeric_binding', 'duplicate_leaf', 'missing_leaf', 'group_and_leaf',
                                    'unknown_operation', 'caption_expression'])
def test_table_spec_rejects_data_and_unsupported_operations(mutation):
    from report_agent.table_spec import TableSpec
    spec = alternate_table_spec()
    if mutation == 'literal_rows': spec['rows'] = [['invented', '1', '99']]
    elif mutation == 'widths': spec['column_weights'] = [1, 2, 3]
    elif mutation == 'formula': spec['column_bindings']['result'] = {'formula': 'rank * 2'}
    elif mutation == 'binding_literal': spec['column_bindings']['result'] = {'value': '99'}
    elif mutation == 'numeric_binding': spec['column_bindings']['result'] = '99'
    elif mutation == 'duplicate_leaf': spec['headers'][1]['children'][1]['columns'] = ['rank']
    elif mutation == 'missing_leaf': spec['headers'].pop()
    elif mutation == 'group_and_leaf': spec['headers'][0]['children'] = [{'text': 'extra', 'columns': ['asset']}]
    elif mutation == 'unknown_operation': spec['row_groups'][0]['merges'] = [{'axis': 'diagonal', 'columns': ['asset']}]
    else: spec['caption_pattern'] = '{name.__class__}'
    with pytest.raises((ValueError, ActionRejected)):
        TableSpec.model_validate(spec)


@pytest.mark.parametrize('mutation', ['stale_plan', 'missing_binding', 'missing_rows', 'missing_caption'])
def test_saved_table_projection_refuses_unbound_inputs(mutation):
    saved = SavedTableRecords()
    if mutation == 'stale_plan': saved.assessment['commission_plan_ref']['version'] = 2
    elif mutation == 'missing_binding': del saved.assessment['table_records']['measurements']['rows'][0]['measurement']
    elif mutation == 'missing_rows': del saved.assessment['table_records']['measurements']['rows']
    else: del saved.assessment['table_records']['object_label']
    with pytest.raises(ActionRejected, match='TABLE_SPEC'):
        saved.render()


def test_group_merges_are_contiguous_column_local_and_do_not_erase_data():
    saved = SavedTableRecords()
    spec = saved.plan['table_specs']['asset_summary']
    spec['sort'] = []
    spec['row_groups'][0]['merges'] = [{'axis': 'vertical', 'columns': ['asset'], 'group_by': ['group']}]
    saved.assessment['table_records']['measurements']['rows'] = [
        {'asset_label': label, 'rank': rank, 'measurement': value, 'group': group}
        for label, rank, value, group in [('A', 1, '4', 'a'), ('A', 2, '7', 'a'),
                                         ('B', 3, '8', 'b'), ('A', 4, '9', 'a')]]
    body = saved.render()
    assert body['merges'] == [{'start_row': 0, 'end_row': 1, 'start_col': 0, 'end_col': 0}]
    assert [row[2] for row in body['rows']] == ['4', '7', '8', '9']
    saved.assessment['table_records']['measurements']['rows'][1]['asset_label'] = 'different'
    with pytest.raises(ActionRejected, match='TABLE_SPEC'):
        saved.render()


def test_conditional_horizontal_merge_requires_empty_saved_field_and_preserves_totals():
    saved = SavedTableRecords()
    spec = saved.plan['table_specs']['asset_summary']
    spec['sort'] = []
    spec['row_groups'] = [
        {'binding': 'measurements.rows', 'merges': [
            {'axis': 'horizontal', 'columns': ['asset', 'rank'], 'when_empty': 'rank'}]},
        {'binding': 'measurements.total_rows', 'merges': [
            {'axis': 'horizontal', 'columns': ['asset', 'rank']}]}]
    saved.assessment['table_records']['measurements'].update(
        rows=[{'asset_label': '普通条件', 'rank': '', 'measurement': '8'},
              {'asset_label': '附加条件', 'rank': '条件B', 'measurement': '9'}],
        total_rows=[{'asset_label': '合计', 'rank': '', 'measurement': '17.000'}])
    body = saved.render()
    assert body['rows'] == [['普通条件', '', '8'], ['附加条件', '条件B', '9'], ['合计', '', '17.000']]
    assert body['merges'] == [
        {'start_row': 0, 'end_row': 0, 'start_col': 0, 'end_col': 1},
        {'start_row': 2, 'end_row': 2, 'start_col': 0, 'end_col': 1}]
    saved.assessment['table_records']['measurements']['total_rows'][0]['rank'] = 'must survive'
    with pytest.raises(ActionRejected, match='TABLE_SPEC'):
        saved.render()


def test_optional_record_contract_checks_capability_without_hardcoding_report_fields():
    from report_agent.table_spec import validate_table_specs
    specs = {'custom_role': alternate_table_spec()}
    contract = {'rows': {'measurements.rows': ['asset_label', 'rank', 'measurement']},
                'values': ['measurements.number', 'object_label']}
    assert validate_table_specs(specs, record_contract=contract)['custom_role']['table_type'] == 'asset_summary'
    contract['rows']['measurements.rows'].remove('measurement')
    with pytest.raises((ValueError, ActionRejected), match='TABLE_SPEC'):
        validate_table_specs(specs, record_contract=contract)
    # The structure itself is still generic; only this record producer lacks the field.
    assert validate_table_specs(specs)['custom_role']['table_type'] == 'asset_summary'


def test_overlapping_projection_merges_refuse_even_when_all_text_is_identical():
    saved = SavedTableRecords()
    spec = saved.plan['table_specs']['asset_summary']
    spec['sort'] = []
    spec['row_groups'][0]['merges'] = [
        {'axis': 'vertical', 'columns': ['asset'], 'group_by': ['group']},
        {'axis': 'horizontal', 'columns': ['asset', 'rank']}]
    saved.assessment['table_records']['measurements']['rows'] = [
        {'asset_label': 'same', 'rank': 'same', 'measurement': '1', 'group': 'a'},
        {'asset_label': 'same', 'rank': 'same', 'measurement': '2', 'group': 'a'}]
    with pytest.raises(ActionRejected, match='TABLE_SPEC.*OVERLAP'):
        saved.render()


def synthetic_pilot_plan(fixture):
    """Synthetic reviewed presentation data; source transcription is tested separately."""
    plan = deepcopy(fixture.plan)
    pack = plan['method_pack']
    pack['version'] = 2
    pack['presentation_sources'] = [fixture.cite('template')]
    pack['display_labels'] = {'total': '合计'}
    for indicator in pack['indicators']:
        indicator['display_label'] = '指标 ' + indicator['id']
        indicator['category_display_label'] = '地质条件'
        indicator['presentation_rows'] = []
        for grade in indicator['grades']:
            conditions = ['条件甲', '条件乙'] if indicator['id'] == 'C' and grade['id'] in ('g2', 'g3') else ['']
            for condition in conditions:
                indicator['presentation_rows'].append({'grade_id': grade['id'],
                    'description': grade['description'], 'condition': condition,
                    'description_group_id': grade['id']})
    from report_agent.method_pack import register_reviewed_method_pack
    register_reviewed_method_pack(fixture.cs.store, pack, 'Independent synthetic table contract fixture.')
    common = {'version': 1, 'sources': [fixture.cite('template')], 'sort': [],
              'level_labels': {'I': 'Ⅰ级（低度风险）', 'II': 'Ⅱ级（中度风险）',
                               'III': 'Ⅲ级（高度风险）', 'IV': 'Ⅳ级（极高风险）'}}
    rank = {**deepcopy(common), 'table_type': 'synthetic_rank',
        'headers': [{'text': text, 'columns': [key]} for key, text in (
            ('rank', '序号'), ('indicator', '评估指标'), ('weight', '权重系数'))],
        'column_bindings': {key: key for key in ('rank', 'indicator', 'weight')},
        'row_groups': [{'binding': 'ranking.rows', 'merges': []}],
        'caption_pattern': '表{number} {object_label}权重系数排序',
        'caption_bindings': {'number': 'ranking.number', 'object_label': 'object_label'},
        'sort': [{'binding': 'rank', 'direction': 'ascending'}]}
    keys = ['category', 'indicator', 'description', 'condition', 'range', 'value', 'weight', 'score', 'explanation']
    evaluation = {**deepcopy(common), 'table_type': 'synthetic_evaluation',
        'headers': [{'text': '分类', 'columns': ['category']},
                    {'text': '评估指标', 'columns': ['indicator']},
                    {'text': '分级', 'columns': ['description', 'condition']},
                    {'text': '基本分值（Rᵢⱼ）', 'children': [
                        {'text': '分值范围', 'columns': ['range']}, {'text': '取值', 'columns': ['value']}]},
                    {'text': '权重系数（γᵢⱼ）', 'columns': ['weight']},
                    {'text': '评估分值（Xᵢⱼ）', 'columns': ['score']},
                    {'text': '说明', 'columns': ['explanation']}],
        'column_bindings': {key: key for key in keys},
        'row_groups': [{'binding': 'evaluation.rows', 'merges': [
            {'axis': 'vertical', 'columns': ['category'], 'group_by': ['category_id']},
            {'axis': 'vertical', 'columns': ['indicator', 'value', 'weight', 'score', 'explanation'], 'group_by': ['indicator_id']},
            {'axis': 'vertical', 'columns': ['range'], 'group_by': ['indicator_id', 'grade_id']},
            {'axis': 'vertical', 'columns': ['description'], 'group_by': ['indicator_id', 'description_group_id']},
            {'axis': 'horizontal', 'columns': ['description', 'condition'], 'when_empty': 'condition'}]},
            {'binding': 'evaluation.total_rows', 'merges': [
                {'axis': 'horizontal', 'columns': keys[:6]}]}],
        'caption_pattern': '表{number} {object_label}施工安全总体风险评估表',
        'caption_bindings': {'number': 'evaluation.number', 'object_label': 'object_label'}}
    plan['table_specs'] = {'ranking': rank, 'evaluation': evaluation}
    return plan


def test_v2_assessment_saves_source_rows_and_projects_both_confirmed_table_types(method_commission):
    from decimal import Decimal
    fixture = method_commission
    plan = synthetic_pilot_plan(fixture)
    saved = save(fixture, plan)
    checkpoint, _ = approve(fixture, saved)
    brief = brief_text(fixture, checkpoint)
    assert '基本分值（Rᵢⱼ）' in brief and 'synthetic_evaluation' in brief
    actor = writer(fixture, saved)
    assessment = persistence_input(fixture)
    assessment['method_version'] = 2
    for row in assessment['indicators']:
        row['rank'] = 5 - row['rank']
    receipt = persist(fixture, actor, assessment)
    payload = fixture.cs.read(receipt['assessment_ref'])['payload']
    assert payload['commission_plan_ref'] == saved['plan_ref']
    records = payload['table_records']
    assert len(records['evaluation']['rows']) == 18
    split = [row for row in records['evaluation']['rows'] if row['indicator_id'] == 'C']
    assert [row['grade_id'] for row in split] == ['g1', 'g2', 'g2', 'g3', 'g3', 'g4']
    assert [row['condition'] for row in split] == ['', '条件甲', '条件乙', '条件甲', '条件乙', '']
    assert Decimal(receipt['result']['adopted']['total']) == Decimal('54')
    ranking = fixture.cs.read(receipt['ranking_ref'])['payload']['body']
    evaluation = fixture.cs.read(receipt['evaluation_ref'])['payload']['body']
    assert ranking['columns'] == ['序号', '评估指标', '权重系数']
    assert [row[:2] for row in ranking['rows']] == [['1', '指标 D'], ['2', '指标 C'], ['3', '指标 B'], ['4', '指标 A']]
    assert not ranking.get('cell_comments') and not ranking.get('material_issues')
    for audit_rows in (payload['indicators'], payload['result']['rows'], records['ranking']['rows']):
        assert len(audit_rows) == 4
        assert all(row['rank_reason'] == 'Relative importance judged from S1 design facts.' for row in audit_rows)
    assert evaluation['header_rows'] == [
        ['分类', '评估指标', '分级', '', '基本分值（Rᵢⱼ）', '', '权重系数（γᵢⱼ）', '评估分值（Xᵢⱼ）', '说明'],
        ['', '', '', '', '分值范围', '取值', '', '', '']]
    assert len(evaluation['rows']) == 19 and all(len(row) == 9 for row in evaluation['rows'])
    assert evaluation['rows'][-1][0] == '合计' and Decimal(evaluation['rows'][-1][7]) == Decimal('54')
    assert {row[8] for row in evaluation['rows'][:-1]} == {'Located basis.', 'No indirect source exists.'}
    assert {issue['anchor']['column'] for issue in evaluation['material_issues']} == {5}
    assert {issue['anchor']['row'] for issue in evaluation['material_issues']} == {8, 14}
    assert all(issue['affects_level'] == receipt['result']['affects_level'] for issue in evaluation['material_issues'])
    assert 'Ⅲ级（高度风险）' in fixture.cs.read(receipt['level_ref'])['payload']['body']['text']


def test_v2_spec_bad_binding_blocks_existing_checkpoint_before_assessment(method_commission):
    fixture = method_commission
    plan = synthetic_pilot_plan(fixture)
    plan['table_specs']['evaluation']['column_bindings']['score'] = 'invented_result'
    try:
        saved = save(fixture, plan)
    except (ValueError, ActionRejected):
        pass
    else:
        with pytest.raises(ActionRejected, match='(?i)(table|spec|binding|method)'):
            approve(fixture, saved)
    assert not fixture.cs.list_objects('Assessment')
    assert fixture.cs.store.get('commission_confirmation') is None


@pytest.mark.parametrize('role,field', [('ranking', 'indicator'), ('evaluation', 'value')])
def test_v2_annotation_semantics_are_validated_before_owner_checkpoint(method_commission, role, field):
    fixture = method_commission
    plan = synthetic_pilot_plan(fixture)
    spec = plan['table_specs'][role]
    spec['column_bindings'][field] = 'weight'  # Valid saved field, but removes the required comment anchor.
    with pytest.raises((ValueError, ActionRejected), match='(?i)(table|annotation|binding)'):
        save(fixture, plan)


@pytest.mark.parametrize('label', [None, ''])
def test_v2_missing_total_label_is_refused_before_checkpoint(method_commission, label):
    fixture = method_commission
    plan = synthetic_pilot_plan(fixture)
    if label is None:
        plan['method_pack']['display_labels'].pop('total')
    else:
        plan['method_pack']['display_labels']['total'] = label
    with pytest.raises((ValueError, ActionRejected), match='(?i)(table|display|total)'):
        save(fixture, plan)


def test_approved_confirmation_checklist_is_exact_durable_and_rules_only(method_commission):
    from pathlib import Path
    from report_agent.store import digest
    fixture = method_commission
    saved = save(fixture, synthetic_pilot_plan(fixture))
    checkpoint, decision = approve(fixture, saved)
    approved = api().reply(fixture.ws, checkpoint['issue_id'], decision)
    relative = Path(approved['confirmation_checklist_path'])
    assert not relative.is_absolute()
    path = fixture.cs.store.root / relative
    assert path.is_file() and path.suffix == '.md'
    original = path.read_bytes()
    text = original.decode('utf-8')
    plan = fixture.cs.read(saved['plan_ref'])['payload']
    confirmation = fixture.cs.store.get('commission_confirmation')
    assert saved['plan_ref']['id'] in text and confirmation['id'] in text
    assert 'synthetic-four' in text and 'rank-lookup' in text
    assert plan['method_conventions'][0]['source']['quote'] in text
    assert '基本分值（Rᵢⱼ）' in text and '权重系数排序' in text
    for spec in plan['table_specs'].values():
        assert spec['table_type'] in text and digest(spec) in text
    assert '复用范围：规则与表式；不复用历史报告数值。' in text
    assert api().read_plan(fixture.cs.store)['confirmation_checklist_path'] == str(relative)
    state = fixture.cs.store.get('commission_checkpoint:' + checkpoint['issue_id'])
    assert state['confirmation_checklist_path'] == str(relative)
    actor = writer(fixture, saved)
    assessment = persistence_input(fixture)
    assessment['method_version'] = 2
    persist(fixture, actor, assessment)
    before_count = len(fixture.cs.list_objects('CommissionDecision'))
    path.unlink()
    replay = api().reply(fixture.ws, checkpoint['issue_id'], decision)
    assert replay['confirmation_checklist_path'] == str(relative)
    assert path.read_bytes() == original  # Newly saved report values never enter the reusable checklist.
    assert len(fixture.cs.list_objects('CommissionDecision')) == before_count == 1


def test_declined_checkpoint_never_emits_approved_confirmation_checklist(method_commission):
    fixture = method_commission
    saved = save(fixture, synthetic_pilot_plan(fixture))
    checkpoint = api().request_checkpoint(fixture.ws)
    before = set(fixture.cs.store.root.rglob('*.md'))
    answer = api().reply(fixture.ws, checkpoint['issue_id'], {'plan_ref': saved['plan_ref'],
        'approved': False, 'corrections': 'Revise the table specification.', 'reductions': []})
    assert not answer.get('confirmation_checklist_path')
    assert not api().read_plan(fixture.cs.store).get('confirmation_checklist_path')
    assert set(fixture.cs.store.root.rglob('*.md')) == before


def test_source_pilot_keeps_literal_headers_six_x22_rows_and_unchanged_arithmetic():
    """Literal oracle independently checked against guideline PDF pages18/19/24."""
    from report_agent.table_spec import read_prepared_tables, compile_header
    from report_agent.method_pack import bind_guideline
    guideline = {'type': 'SourceArtifact', 'id': 'actual-guideline', 'version': 1}
    template = {'type': 'SourceArtifact', 'id': 'actual-template', 'version': 1}
    guideline_hash = 'f063d3f281232a2c7057a8ab832e1e5d0f2262222df72fdf4edbe941b6ac8e98'
    template_hash = 'be51ef3a26782a4c1563c4e496ec0f59828610e1841892c23d72ba43e0e26c99'
    specs = read_prepared_tables(guideline, guideline_hash, template, template_hash)
    evaluation = compile_header(specs['evaluation'])
    assert evaluation['header_rows'] == [
        ['分类', '评估指标', '分级', '', '基本分值（Rᵢⱼ）', '', '权重系数（γᵢⱼ）', '评估分值（Xᵢⱼ）', '说明'],
        ['', '', '', '', '分值范围', '取值', '', '', '']]
    assert {'start_row': 0, 'end_row': 1, 'start_col': 2, 'end_col': 3} in evaluation['header_merges']
    assert compile_header(specs['ranking'])['header_rows'] == [['序号', '评估指标', '权重系数']]
    assert specs['evaluation']['level_labels'] == {
        'I': 'Ⅰ级（低度风险）', 'II': 'Ⅱ级（中度风险）', 'III': 'Ⅲ级（高度风险）', 'IV': 'Ⅳ级（极高风险）'}
    v1 = bind_guideline(guideline, guideline_hash)
    v2 = bind_guideline(guideline, guideline_hash, template, template_hash)
    assert v1['version'] == 1 and v2['version'] == 2
    assert v1['weight_tables'] == v2['weight_tables'] and v1['risk_bands'] == v2['risk_bands']
    assert [i['grades'] for i in v1['indicators']] == [i['grades'] for i in v2['indicators']]
    assert all('presentation_rows' not in indicator for indicator in v1['indicators'])
    x22 = next(indicator for indicator in v2['indicators'] if indicator['id'] == 'X22')
    assert x22['display_label'] == '坡体结构 X₂₂'
    assert [(row['grade_id'], row['condition']) for row in x22['presentation_rows']] == [
        ('very_high', '贯通'), ('high', '不贯通'), ('high', '贯通'),
        ('moderate', '不贯通'), ('moderate', ''), ('low', '')]
    descriptions = [row['description'] for row in x22['presentation_rows']]
    assert descriptions[:2] == ['坡体中存在顺坡向缓倾的软弱结构面或组合体'] * 2
    assert descriptions[2:4] == ['坡体中存在顺坡向缓倾的硬性结构面或组合体'] * 2
    assert descriptions[4:] == ['坡体中存在其他方向结构面，且贯通和发育', '坡体中其他方向的结构面，不贯通，不发育']
    with pytest.raises(ValueError, match='HASH'):
        read_prepared_tables(guideline, guideline_hash, template, '0' * 64)
    with pytest.raises(ValueError, match='HASH'):
        bind_guideline(guideline, guideline_hash, template, '0' * 64)


@pytest.mark.parametrize('tool_name', ['read_prepared_method', 'read_prepared_tables'])
def test_prepared_adapters_bind_both_actual_source_hashes(method_commission, monkeypatch, tool_name):
    from langchain_core.tools import StructuredTool
    from report_agent.hierarchical_tools import content_tools
    from report_agent import method_pack, table_spec
    fixture = method_commission
    calls = []
    def capture(*args):
        calls.append(args)
        return {'prepared': tool_name}
    monkeypatch.setattr(method_pack if tool_name == 'read_prepared_method' else table_spec,
                        'bind_guideline' if tool_name == 'read_prepared_method' else 'read_prepared_tables', capture)
    function = next(t for t in content_tools(fixture.ws, 'coordinator') if t.__name__ == tool_name)
    result = StructuredTool.from_function(function).invoke({
        'source_ref': fixture.sources['guideline'], 'template_ref': fixture.sources['template']})
    assert result == {'prepared': tool_name}
    assert calls == [(fixture.sources['guideline'],
                      fixture.cs.read(fixture.sources['guideline'])['payload']['file_digest'],
                      fixture.sources['template'],
                      fixture.cs.read(fixture.sources['template'])['payload']['file_digest'])]


@pytest.mark.parametrize('role', ['writer', 'reviewer'])
def test_prepared_capability_tools_do_not_expand_role_permissions(method_commission, role):
    from report_agent.hierarchical_tools import content_tools
    names = {t.__name__ for t in content_tools(method_commission.ws, role)}
    assert not {'read_prepared_method', 'read_prepared_tables'} & names
