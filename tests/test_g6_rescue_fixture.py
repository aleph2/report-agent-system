"""Synthetic display arithmetic must not bypass canonical input checks."""
from contextlib import contextmanager
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from report_agent import plan_authority
from report_agent.content_models import Ref
from report_agent.content_store import Actor, ContentStore
from report_agent.errors import ActionRejected
from report_agent.material_issues import MaterialIssue, validate_required_issues
from report_agent.system_assembler import preflight_assembly


def fixture_data():
    return json.loads((Path(__file__).parent / 'fixtures/g6_g5_rescue.json').read_text())


def ref(kind, identity):
    return {'type': kind, 'id': identity, 'version': 1}


def frozen_registry(data):
    # Deliberately synthetic strings: no private G5 body, questions or sources.
    required = [{'id': row['id'], 'kind': row['kind'], 'object_label': 'Anonymous object',
                 'basis': 'Synthetic registry basis', 'sources': [],
                 'question': 'Synthetic clarification question'} for row in data['required_issues']]
    plan_ref, decision_ref = ref('CommissionPlan', 'plan'), ref('CommissionDecision', 'decision')
    records = {Ref.model_validate(plan_ref).key(): {'ref': plan_ref, 'payload': {}},
               Ref.model_validate(decision_ref).key(): {'ref': decision_ref, 'owner_id': 'operator',
                   'payload': {'approved': True, 'plan_ref': plan_ref, 'required_material_issues': required}}}
    snapshot = {'payload': {'commission_plan_ref': plan_ref, 'commission_confirmation_ref': decision_ref}}
    owners = {row['id'] for row in data['required_issues'] if row['origin'] == 'system_owner_record'}
    actual = [(ref('ContentNode', 'scope'), MaterialIssue.model_validate({**row,
        'adopted_value': 'Synthetic scope value', 'affects_level': False,
        'anchor': {'paragraph_index': 0}})) for row in required if row['id'] in owners]
    return required, records, snapshot, actual


def test_all_25_required_registry_obligations_reject_only_three_owner_records():
    data = fixture_data()
    required, records, snapshot, actual = frozen_registry(data)
    assert len(required) == 25 and len(actual) == 3
    missing = [row['id'] for row in required if row['id'] not in {issue.id for _, issue in actual}]
    assert missing == data['missing_required_issue_ids'] and len(missing) == 22
    with pytest.raises(ActionRejected) as caught:
        validate_required_issues(None, None, snapshot, records, actual)
    assert str(caught.value) == 'REQUIRED_MATERIAL_ISSUE_NOT_RENDERED: ' + missing[0]
    # The validator is fail-fast. Keep all 25 obligations, rotating each absent
    # one to the front, so every missing obligation must name its exact ID.
    decision = records[Ref.model_validate(snapshot['payload']['commission_confirmation_ref']).key()]
    for issue_id in missing:
        decision['payload']['required_material_issues'] = sorted(required, key=lambda row: row['id'] != issue_id)
        with pytest.raises(ActionRejected) as caught:
            validate_required_issues(None, None, snapshot, records, actual)
        assert str(caught.value) == 'REQUIRED_MATERIAL_ISSUE_NOT_RENDERED: ' + issue_id
    decision['payload']['required_material_issues'] = [row for row in required if row['id'] not in missing]
    validate_required_issues(None, None, snapshot, records, actual)


def test_g5_numeric_rows_recompute_exactly_without_implying_engineering_completion():
    data = fixture_data()
    assert len(data['tables']) == 5
    assert sum(len(table['rows']) for table in data['tables']) == 55
    for table in data['tables']:
        assert len(table['rows']) == 11
        assert sum(Decimal(row['weight']) for row in table['rows']) == Decimal('1.00')
        for row in table['rows']:
            assert Decimal(row['weight']) * Decimal(row['score']) == Decimal(row['product'])
        assert sum(Decimal(row['product']) for row in table['rows']) == Decimal(table['total'])
    assert data['canonical_assessment_refs'] == []
    assert data['canonical_assessment_record_count'] == 0
    assert data['internal_content_counts'] == {'qualifier_metadata': 34, 'prose_regex_matches': 0}


def test_complete_display_arithmetic_without_assessments_is_not_assembly_ready(tmp_path):
    data = fixture_data()
    # A minimal read-only projection isolates the canonical-assessment gate.
    # It is not a substitute for the separate real-case preflight evidence.
    plan_ref, decision_ref, root_ref = ref('CommissionPlan', 'plan'), ref('CommissionDecision', 'decision'), ref('ContentNode', 'root')
    snapshot_ref = ref('DocumentSnapshot', 'anonymized-g5-projection')
    plan = {'ref': plan_ref, 'owner_id': 'content:coordinator', 'payload': {
        'sections': [], 'objects': [{'object_id': table['object_id'], 'included': True, 'attributes': []} for table in data['tables']]}}
    decision = {'ref': decision_ref, 'owner_id': 'operator', 'payload': {'approved': True, 'plan_ref': plan_ref}}
    root = {'ref': root_ref, 'payload': {'kind': 'report', 'body': {'text': 'Synthetic report'}}}
    records = {Ref.model_validate(r['ref']).key(): r for r in [plan, decision, root]}
    for table in data['tables']:
        table_ref = ref('ContentNode', 'display-' + table['object_id'])
        records[Ref.model_validate(table_ref).key()] = {'ref': table_ref,
            'payload': {'kind': 'table', 'body': {'rows': deepcopy(table['rows'])}}}
    source = {'ref': snapshot_ref, 'payload': {'commission_plan_ref': plan_ref,
        'commission_confirmation_ref': decision_ref, 'root_ref': root_ref,
        'refs': [r['ref'] for r in records.values()]}}
    records[Ref.model_validate(snapshot_ref).key()] = source
    db = sqlite3.connect(':memory:')
    db.execute('CREATE TABLE state(key TEXT PRIMARY KEY,value TEXT)')
    db.execute('CREATE TABLE content_versions(type TEXT, id TEXT, version INTEGER, data TEXT, PRIMARY KEY(type,id,version))')
    db.executemany('INSERT INTO content_versions VALUES (?,?,?,?)',
                   [(*key, json.dumps(value)) for key, value in records.items()])
    plan_authority.install_historical_refs(db, plan_ref, decision_ref)
    db.commit()
    setup_writes = db.total_changes
    @contextmanager
    def connect():
        db.execute('PRAGMA query_only=ON')
        yield db
    store = SimpleNamespace(root=tmp_path, connect=connect, manifest={})
    cs = SimpleNamespace(store=store, _read=ContentStore._read)
    try:
        result = preflight_assembly(cs, Actor('content:coordinator', 'coordinator', 'fixture'),
            source_snapshot_ref=snapshot_ref, prose_bindings={},
            assessment_refs=data['canonical_assessment_refs'], issue_bindings={})
        assert result['ready'] is False
        assert result['missing_assessments'] == sorted(table['object_id'] for table in data['tables'])
        assert db.total_changes == setup_writes
    finally:
        db.close()
