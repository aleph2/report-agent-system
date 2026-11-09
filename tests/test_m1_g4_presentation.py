"""New runs require table specifications without rewriting historical records."""
from copy import deepcopy

import pytest

from report_agent import plan_authority
from report_agent.errors import ActionRejected
from report_agent.store import Store
from test_m1_commission_plan import api, approve, save, writer, commission
from test_m1_g3_integration import method_commission, persist, persistence_input
from test_m1_g3_followup import synthetic_pilot_plan
from test_pilot_m1_preparation import host_case


def new_contract(fixture):
    manifest = deepcopy(fixture.ws.store.manifest)
    manifest['assessment_presentation'] = 'table-spec-v1'
    fixture.ws.store.set('manifest', manifest)


def test_new_host_requires_specs_only_when_an_assessment_method_is_used(tmp_path, monkeypatch):
    state = host_case(tmp_path, monkeypatch)
    state['prepare']()
    assert Store(state['CASE']).manifest['assessment_presentation'] == 'table-spec-v1'


def test_new_plan_cannot_choose_method_without_table_specs(method_commission):
    fixture = method_commission
    new_contract(fixture)
    with pytest.raises(ActionRejected, match='(?i)(table.*spec|spec.*table)'):
        save(fixture)
    assert not fixture.cs.list_objects('CommissionPlan')


def test_new_contract_refuses_confirmation_of_old_plan_without_rewriting_it(method_commission):
    fixture = method_commission
    saved = save(fixture)
    before = deepcopy(fixture.cs.read(saved['plan_ref']))
    new_contract(fixture)
    with pytest.raises(ActionRejected, match='(?i)(table.*spec|spec.*table)'):
        approve(fixture, saved)
    assert plan_authority.decision_ref(fixture.ws.store) is None
    assert fixture.cs.read(saved['plan_ref']) == before


def test_new_contract_refuses_legacy_assessment_before_any_calculated_records(method_commission):
    fixture = method_commission
    saved = save(fixture)
    approve(fixture, saved)
    actor = writer(fixture, saved)
    new_contract(fixture)
    before = deepcopy(fixture.cs.list_objects())
    with pytest.raises(ActionRejected, match='(?i)(table.*spec|spec.*table)'):
        persist(fixture, actor)
    assert fixture.cs.list_objects() == before


def test_new_contract_does_not_reissue_legacy_confirmation_on_operator_replay(method_commission):
    fixture = method_commission
    saved = save(fixture)
    checkpoint, decision = approve(fixture, saved)
    historical = deepcopy(plan_authority.decision_ref(fixture.ws.store))
    new_contract(fixture)
    with pytest.raises(ActionRejected, match='(?i)(table.*spec|spec.*table)'):
        api().reply(fixture.ws, checkpoint['issue_id'], decision)
    assert plan_authority.decision_ref(fixture.ws.store) == historical


def test_historical_assessment_path_remains_readable_and_unchanged(method_commission):
    fixture = method_commission
    saved = save(fixture)
    approve(fixture, saved)
    receipt = persist(fixture, writer(fixture, saved))
    historical = deepcopy(fixture.cs.read(receipt['assessment_ref']))
    assert 'table_records' not in historical['payload']
    new_contract(fixture)
    assert fixture.cs.read(receipt['assessment_ref']) == historical


def test_new_specified_assessment_uses_saved_records_for_both_tables(method_commission):
    fixture = method_commission
    fixture.plan = synthetic_pilot_plan(fixture)
    new_contract(fixture)
    saved = save(fixture)
    approve(fixture, saved)
    assessment = persistence_input(fixture)
    assessment['method_version'] = 2
    receipt = persist(fixture, writer(fixture, saved), assessment)
    record = fixture.cs.read(receipt['assessment_ref'])['payload']
    assert {'ranking', 'evaluation'} <= set(record['table_records'])
    ranking = fixture.cs.read(receipt['ranking_ref'])['payload']['body']
    evaluation = fixture.cs.read(receipt['evaluation_ref'])['payload']['body']
    assert ranking['columns'] == ['序号', '评估指标', '权重系数']
    assert len(evaluation['header_rows']) == 2


def test_nonassessment_commission_does_not_require_irrelevant_table_specs(commission):
    fixture = commission
    new_contract(fixture)
    saved = save(fixture)
    approve(fixture, saved)
    assert plan_authority.decision_ref(fixture.ws.store)
