"""R1-A internal handles: real immutable tasks, snapshots and receipt transactions.

The planned modules need reviewed executable skeletons before behavioral RED;
missing modules/collection failures are not evidence for these contracts.
"""
from contextlib import contextmanager
from copy import deepcopy
import json

import pytest

from report_agent.content_store import Actor, ContentStore
from report_agent.content_tasks import delegated_task
from report_agent.errors import ActionForbidden, ActionRejected
from report_agent.store import Store, encode
from report_agent.workspace import Workspace
from test_deliverable_declaration_v4 import case
from test_review_binding_v4 import prepared, review_call, task_record


@contextmanager
def bound_review(case, *, two=False):
    cs, output, criteria, _ = prepared(case)
    call = review_call(criteria, identity='r1a-review', scope={'kind': 'mapped', 'items': [
        {'criterion_ref': c, 'target_ref': output['refs']['a-body'],
         'assessment_kind': 'content', 'extent': 'local_body'} for c in criteria[:2 if two else 1]]})
    workspace = Workspace(cs.store)
    with delegated_task(workspace, 'coordinator', call) as (_, actor):
        receipt = cs.read_context(actor, output['refs']['a-body'])['receipt_id']
        yield cs, workspace, actor, receipt, task_record(cs, actor), output


def test_check_and_evidence_handles_survive_reopen_without_inventing_reads(case):
    from report_agent import review_handles as h
    with bound_review(case, two=True) as (cs, ws, actor, receipt, task, output):
        assert h.check_handles(task) == {'C1': 0, 'C2': 1}
        before = cs.list_objects()
        with cs.store.connect() as db:
            observed = db.execute('SELECT count(*) FROM content_observations').fetchone()[0]
            first = h.assign_evidence_handle(db, actor.id, receipt)
            assert h.assign_evidence_handle(db, actor.id, receipt) == first
        assert first.startswith('obs-') and h.evidence_handles(cs, actor)[first] == receipt
        reopened = ContentStore(Store(cs.store.root))
        assert h.evidence_handles(reopened, actor) == h.evidence_handles(cs, actor)
        assert h.resolve(reopened, actor, 'check', 'C2') == task['payload']['review_requirements'][1]
        assert h.resolve(reopened, actor, 'evidence', first) == receipt
        with cs.store.connect() as db:
            assert db.execute('SELECT count(*) FROM content_observations').fetchone()[0] == observed
        assert cs.list_objects() == before


def test_allocator_uses_callers_transaction_and_rejects_foreign_receipt(case):
    from report_agent import review_handles as h
    with bound_review(case) as (cs, ws, actor, receipt, task, output):
        original = deepcopy(h.evidence_handles(cs, actor))
        class Rollback(Exception):
            pass
        with pytest.raises(Rollback):
            with cs.store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                db.execute('INSERT INTO content_observations VALUES (?,?,?)',
                    ('r1a-rolled-back-read', actor.id, encode({'synthetic': 'rolled back'})))
                assert h.assign_evidence_handle(db, actor.id, 'r1a-rolled-back-read').startswith('obs-')
                raise Rollback()
        assert h.evidence_handles(cs, actor) == original
        foreign = Actor('another-reviewer', 'reviewer', 'another-task')
        foreign_receipt = cs.observe(foreign, {'synthetic': 'foreign read'})['receipt_id']
        with cs.store.connect() as db:
            with pytest.raises(ActionForbidden):
                h.assign_evidence_handle(db, actor.id, foreign_receipt)
        assert h.evidence_handles(cs, actor) == original


@pytest.mark.parametrize('kind,handle', [('check', 'C99'), ('evidence', 'obs-999'),
    ('content', 'S99'), ('material', 'M999')])
def test_unknown_handle_lists_only_current_bound_valid_handles(case, kind, handle):
    from report_agent import review_handles as h
    with bound_review(case) as (cs, ws, actor, receipt, task, output):
        valid = {'check': h.check_handles(task), 'evidence': h.evidence_handles(cs, actor),
            'content': h.content_handles(cs, task['payload']['review_snapshot_ref']),
            'material': h.material_handles(cs, actor)}[kind]
        with pytest.raises(ActionRejected) as error:
            h.resolve(cs, actor, kind, handle)
        assert error.value.diagnostic == {'kind': kind, 'handle': handle, 'valid_handles': list(valid)}
        assert receipt not in json.dumps(error.value.diagnostic)
        with pytest.raises(ActionForbidden):
            h.resolve(cs, Actor(actor.id + '-foreign', 'reviewer', actor.task_id), kind, handle)


def test_content_numbering_uses_frozen_contains_positions_and_snapshot_versions(case):
    from report_agent import review_handles as h
    with bound_review(case) as (cs, ws, actor, receipt, task, output):
        old = task['payload']['review_snapshot_ref']
        assert h.content_handles(cs, old) == {'S1': output['refs']['a'], 'S1.1': output['refs']['a-body']}
        table = lambda key: {'client_key': key, 'type': 'ContentNode', 'payload': {
            'kind': 'table', 'body': {'columns': ['value'], 'rows': [[1]]},
            'qualifiers': {}, 'claim_kind': 'fact'}}
        edge = lambda key, child, position: {'client_key': key, 'type': 'Relation', 'payload': {
            'subject_ref': output['refs']['a'], 'object_ref': {'client_key': child},
            'predicate': 'contains', 'position': position, 'provenance_kind': 'adopted_during_generation'}}
        # Commit order differs from display order; no title parsing or UUID sorting.
        added = cs.commit(case[2], 'r1a-tables', [table('last'), table('first'),
            edge('last-edge', 'last', 2), edge('first-edge', 'first', 1)])['result']['refs']
        new = cs.freeze(case[2], 'r1a-new-snapshot', output['refs']['a'],
            [*cs.read(old)['payload']['refs'], *added.values()],
            workbook_refs=cs.read(old)['payload'].get('workbook_refs', []))['result']['snapshot_ref']
        mapping = h.content_handles(cs, new)
        assert mapping['T1'] == mapping['S1.2'] == added['first']
        assert mapping['T2'] == mapping['S1.3'] == added['last']
        assert h.content_handles(ContentStore(Store(cs.store.root)), old) == {
            'S1': output['refs']['a'], 'S1.1': output['refs']['a-body']}
        assert h.resolve(cs, actor, 'content', 'S1.1') == output['refs']['a-body']
        with pytest.raises((ActionRejected, ActionForbidden)):
            h.resolve_content(cs, actor, added['first'])  # Membership in a new snapshot grants no old-task authority.


def test_material_aliases_resolve_exact_assigned_versions_after_restart(case):
    from report_agent import review_handles as h
    with bound_review(case) as (cs, ws, actor, receipt, task, output):
        mapping = h.material_handles(cs, actor)
        assert mapping and list(mapping) == ['M' + str(i + 1) for i in range(len(mapping))]
        assert mapping == h.material_handles(ContentStore(Store(cs.store.root)), actor)
        for handle, ref in mapping.items():
            assert h.resolve(cs, actor, 'material', handle) == ref
            assert cs.read(ref)['ref'] == ref


@pytest.mark.parametrize('fault', ['cycle', 'duplicate-position'])
def test_ambiguous_frozen_tree_is_refused_instead_of_renumbered(case, fault):
    from report_agent import review_handles as h
    with bound_review(case) as (cs, ws, actor, receipt, task, output):
        snapshot = cs.read(task['payload']['review_snapshot_ref'])
        def malformed(db):
            edge = cs._insert(db, case[1], 'Relation', {
                'subject_ref': output['refs']['a-body'] if fault == 'cycle' else output['refs']['a'],
                'object_ref': output['refs']['a'] if fault == 'cycle' else output['refs']['a-body'],
                'predicate': 'contains', 'position': 0, 'provenance_kind': 'adopted_during_generation'})
            # Deliberately corrupt persisted input bypasses freeze's normal checks;
            # the reader must not loop or silently invent an ordering.
            payload = {**deepcopy(snapshot['payload']), 'refs': [*snapshot['payload']['refs'], edge]}
            return {'snapshot': cs._insert(db, case[1], 'DocumentSnapshot', payload)}
        bad = cs.operation(case[1], 'r1a-malformed-' + fault, {}, malformed)['result']['snapshot']
        with pytest.raises(ActionRejected):
            h.content_handles(cs, bad)
