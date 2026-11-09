"""Surviving Writer contracts exercised through the per-indicator route."""
from copy import deepcopy

import pytest
from pydantic import ValidationError

from report_agent import writer_assessment as api
from report_agent.errors import ActionForbidden, ActionRejected
from test_m1_commission_plan import approve, save, writer
from test_m1_g3_integration import method_commission


@pytest.fixture
def assigned(method_commission):
    f=method_commission
    f.ws.store.set('manifest',{**f.ws.store.manifest,'assembly_contract':'system-assembler-v1'})
    saved=save(f);approve(f,saved)
    f.actor = writer(f, saved, section_ids=['4'], assessment_object_id='S1', operation='host-assessment-assignment')
    f.plan_ref=saved['plan_ref']
    return f


@pytest.fixture
def ranked_case(method_commission):
    from test_writer_indicator_outcomes import attach_ranks, make_assignment
    attach_ranks(method_commission)
    return make_assignment(method_commission)


@pytest.mark.parametrize("method_commission", ["with-owner-ranks"], indirect=True)
def test_system_owned_fields_excluded_from_all_save_tools(ranked_case):
    f = ranked_case
    private = {"operation_id", "subject", "object_id", "section_id", "plan_ref", "method_id",
               "method_version", "weight_strategy_id", "indicator_id", "grade_id", "source_ref", "locator", "rank"}
    for kind in ("evidence", "assumption", "gap"):
        model = api.step_outcome_schema(f.cs, f.actor, "A", kind)
        assert not private.intersection(model.model_fields)
        assert model.model_json_schema()["additionalProperties"] is False
    gap = api.step_outcome_schema(f.cs, f.actor, "A", "gap")
    payload = {"missing": "Bench heights", "question": "What are the bench heights?"}
    gap.model_validate(payload)
    for field in private:
        with pytest.raises(ValidationError):
            gap.model_validate({**payload, field: "forged"})


@pytest.mark.parametrize("method_commission", ["with-owner-ranks"], indirect=True)
def test_revision_refuses_read_and_save_under_superseded_assignment(ranked_case):
    f = ranked_case
    api.read_indicator_step(f.cs, f.actor)
    revised = deepcopy(f.plan)
    revised["objects"][0]["reason"] = "Reconfirmed scope in a new plan version."
    approve(f, save(f, revised, operation="revised-plan"))
    with pytest.raises((ActionForbidden, ActionRejected)):
        api.read_indicator_step(f.cs, f.actor)
    with pytest.raises((ActionForbidden, ActionRejected)):
        api.save_indicator_outcome(f.cs, f.actor, "stale-save", "A",
                                   {"kind": "gap", "missing": "Height", "question": "What is the height?"})


@pytest.mark.parametrize(("quote", "code"), [
    ("S1", "QUOTE_AMBIGUOUS"), ("not present in an authorized source", "QUOTE_NOT_FOUND")])
def test_ambiguous_or_absent_quote_cannot_be_bound_to_an_arbitrary_page(assigned, quote, code):
    with assigned.ws.store.connect() as db:
        scope = api._assignment(assigned.cs, db, assigned.actor)
        with pytest.raises(ActionRejected, match=code):
            api.resolve_judgment_sources(assigned.cs, db, assigned.actor, scope, [quote])


def test_duplicate_indicator_labels_refused():
    pack = {"indicators": [{"display_label": "Same label"}, {"display_label": "Same label"}]}
    with pytest.raises(ActionRejected, match="DUPLICATE_INDICATOR_LABEL"):
        api._validate_labels(pack)


def test_shared_quote_resolver_deduplicates_repeated_authorized_refs(assigned):
    from report_agent.writer_assignments import bound_assignment
    f=assigned
    with f.ws.store.connect() as db:
        context=bound_assignment(f.cs,db,f.actor)
        context['sources'] += list(context['sources'])
        result=api.resolve_judgment_sources(f.cs,db,f.actor,context,[f.cite('design')['quote']])
    assert len(result)==1 and result[0]['source_ref']==f.sources['design']


def test_resolved_manifest_quote_remains_export_readable(assigned):
    from report_agent.g3_export import citation_text
    f = assigned
    with f.ws.store.connect() as db:
        scope = api._assignment(f.cs, db, f.actor)
        citations = api.resolve_judgment_sources(f.cs, db, f.actor, scope, [f.cite('design')['quote']])
    assert citations[0]['locator'] == 'manifest text'
    from report_agent.content_models import Ref
    records = {Ref.model_validate(c['source_ref']).key(): f.cs.read(c['source_ref']) for c in citations}
    assert 'design' in citation_text({'kind': 'paragraph', 'citations': citations}, records)


@pytest.mark.parametrize("method_commission", ["with-owner-ranks"], indirect=True)
def test_compact_assignment_includes_bound_inventory_and_approved_method(ranked_case):
    f = ranked_case
    packet = api.read_indicator_step(f.cs, f.actor)
    assert packet['inventory_facts'][0]['name'] == 'height'
    assert packet['inventory_facts'][0]['values'][0]['value'] == '30 m'
    assert packet['owner_conventions'][0]['interpretation'] == f.plan['conventions'][0]['interpretation']
    assert packet['approved_method']['indicator_count'] == 4
    assert packet['approved_method']['weight_rule']['interpretation'] == f.plan['method_conventions'][0]['interpretation']
    assert packet['approved_method']['rank_weights'] == ['0.4', '0.3', '0.2', '0.1']
    assert packet['boundary']['excluded_objects'] == []
    assert 'source_ref' not in str(packet['inventory_facts']) and 'method_id' not in packet['approved_method']
