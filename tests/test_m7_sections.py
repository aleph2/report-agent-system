"""M7 section and rescue provenance stays in immutable case records."""
from copy import deepcopy

import pytest

from report_agent.errors import ActionRejected
from report_agent.rescue_projection import project_rescue_prose, verify_projection
from report_agent.store import digest
from test_m1_g3_integration import method_commission
from test_m1_g5_j2 import composed_runtime, materialize_composition
from test_rescue_projection import projection_input


def test_composition_provenance_keeps_exact_refs_without_receipt_hashes(composed_runtime):
    f = composed_runtime
    result = materialize_composition(f)
    refs = [ref for ref in result['refs'].values() if ref['type'] == 'ContentNode']
    assert f.cs.store.get('planned_section_receipt:' + digest(result['node_ref'])) is None
    from report_agent.report_state import native, planned_section
    for ref in refs:
        assert native(f.cs.store, 'SectionProvenance', ref)
        provenance = planned_section(f.cs.store, ref)
        assert provenance['node_ref'] == ref
        assert provenance['commission_plan_ref'] == f.saved['plan_ref']
        assert provenance['assessment_refs'] == [f.assessment_receipt['assessment_ref']]
        assert provenance['group_ref'] == result['node_ref']
        assert not any(key.endswith('_digest') for key in provenance)
    assert planned_section(f.cs.store, result['node_ref'])['node_refs'] == refs
    before = f.cs.read(result['node_ref'])
    assert materialize_composition(f) == result
    assert f.cs.read(result['node_ref']) == before


def test_native_composition_checks_the_immutable_payload_directly(composed_runtime):
    from report_agent.content_models import Ref
    from report_agent.g3_export import validate_export
    f = composed_runtime
    result = materialize_composition(f)
    records = {Ref.model_validate(row['ref']).key(): deepcopy(row) for row in f.cs.list_objects()}
    snapshot = {'payload': {'root_ref': result['node_ref'], 'commission_plan_ref': f.saved['plan_ref']}}
    validate_export(f.cs, snapshot, records)
    table = next(row['payload'] for row in records.values()
                 if row['ref'] in result['refs'].values() and row['payload'].get('kind') == 'table')
    table['body']['rows'][0][0] = 'Wrong assembled result'
    with pytest.raises(ActionRejected, match='(?i)(composition|receipt)'):
        validate_export(f.cs, snapshot, records)


def test_rescue_projection_is_reference_bound_and_rechecks_its_transform(projection_input):
    f = projection_input
    original = f.cs.read(f.prose)
    result = project_rescue_prose(f.cs, f.co, 'm7-project', **f.args)['result']
    ref = result['section_bindings']['4'][0]
    assert f.cs.store.get('rescue_projection:' + digest(ref)) is None
    from report_agent.report_state import native, projection
    assert native(f.cs.store, 'RescueProjection', ref)
    provenance = projection(f.cs.store, ref)
    assert provenance['projection_ref'] == ref
    assert provenance['source_snapshot_ref'] == f.snapshot
    assert provenance['source_ref'] == f.prose
    assert not any(key.endswith('_digest') for key in provenance)
    saved = f.cs.read(ref)
    with f.cs.store.connect() as db:
        assert verify_projection(f.cs, db, saved, '4', f.plan, f.co) == provenance
        altered = deepcopy(saved)
        altered['payload']['body']['text'] += ' Unsupported result.'
        with pytest.raises(ActionRejected, match='PROJECTION_(TRANSFORM|PAYLOAD)'):
            verify_projection(f.cs, db, altered, '4', f.plan, f.co)
    assert project_rescue_prose(f.cs, f.co, 'm7-project', **f.args)['result'] == result
    assert f.cs.read(f.prose) == original
