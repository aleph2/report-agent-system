"""Internal flat-message compatibility; no changed model tools or provider calls."""
from contextlib import contextmanager
from copy import deepcopy
import json

import pytest

from report_agent.content_store import ContentStore
from report_agent.content_tasks import delegated_task, native_review_submission_schema
from report_agent.errors import ActionForbidden, ActionRejected
from report_agent.store import Store, digest
from report_agent.workspace import Workspace
from test_deliverable_declaration_v4 import case
from test_review_binding_v4 import prepared, review_call, task_record
from test_selected_companion_reviews import pair, ws


@contextmanager
def unit(case):
    cs, output, criteria, _ = prepared(case)
    call = review_call(criteria, scope={'kind': 'mapped', 'items': [{
        'criterion_ref': criteria[0], 'target_ref': output['refs']['a-body'],
        'assessment_kind': 'content', 'extent': 'local_body'}]})
    with delegated_task(Workspace(cs.store), 'coordinator', call) as (_, actor):
        receipt = cs.read_context(actor, output['refs']['a-body'])['receipt_id']
        yield cs, actor, receipt, task_record(cs, actor)['payload']


def message(**updates):
    return {'execution_state': 'completed', 'verdict': 'satisfied',
            'assessment': 'The selected synthetic body was compared; no whole-report approval.',
            'evidence_indexes': [0], **updates}


def test_assembly_is_reusable_without_a_second_save_path(case):
    from report_agent.review_message import assemble_review_message, bind_review_message, save_review_message
    with unit(case) as (cs, actor, receipt, _):
        binding = bind_review_message(cs, actor, [receipt])
        assembled = assemble_review_message(cs, actor, binding, message())
        assert not cs.list_objects('ReviewRecord')
        saved = save_review_message(cs, actor, 'assembled-save', binding, message())
        record = cs.read(saved['result']['review_ref'])['payload']
        from report_agent.content_models import ReviewSubmission
        assert record['items'] == ReviewSubmission.model_validate(assembled).model_dump()['items']
        assert record['snapshot_ref'] == assembled['snapshot_ref']


def test_flat_judgment_preserves_finding_notes_and_object_coverage(case):
    from report_agent.review_message import bind_review_message, save_review_message
    with unit(case) as (cs, actor, receipt, task):
        binding = bind_review_message(cs, actor, [receipt])
        target = task['review_requirements'][0]['target_ref']
        index = binding['coverage_refs'].index(target)
        result = save_review_message(cs, actor, 'negative-flat', binding, message(
            verdict='not_satisfied', finding_type='confirmed_defect', finding_locator_state='located',
            finding_description='The selected claim contradicts the synthetic source.',
            finding_impact='This changes the stated risk classification.',
            finding_needed_outcome='Correct the claim using the actual authorized source.',
            finding_basis_kind='supplied_content', outside_assignment_notes=['A different task must assess design adequacy.'],
            coverage_object_indexes=[index], coverage_state='assessed', coverage_reason='Compared the selected body.'))
        record = cs.read(result['result']['review_ref'])['payload']
        item, = record['items']
        finding, = item['findings']
        assert finding['finding_type'] == 'confirmed_defect'
        assert finding['impact'] == 'This changes the stated risk classification.'
        assert finding['observation_indexes'] == [0]
        assert item['outside_assignment_notes'] == ['A different task must assess design adequacy.']
        accounting, = record['coverage_accounting']
        assert accounting['target_refs'] == [target]
        assert accounting['state'] == 'assessed' and accounting['item_indexes'] == [0]


def test_flat_message_saves_real_review_and_reopens_without_inventing_reads(case):
    from report_agent.review_message import bind_review_message, save_review_message
    with unit(case) as (cs, actor, receipt, task):
        old_schema = native_review_submission_schema(v4=True, scope_selectors=True).model_json_schema()
        with cs.store.connect() as db:
            before = db.execute('SELECT count(*) FROM content_observations').fetchone()[0]
        evidence = cs.list_objects('Evidence')[0]['ref']
        source_receipt = cs.read_context(actor, evidence)['receipt_id']
        with cs.store.connect() as db:
            before = db.execute('SELECT count(*) FROM content_observations').fetchone()[0]
        binding = bind_review_message(cs, actor, [receipt, source_receipt])
        result = save_review_message(cs, actor, 'flat-save', binding, message(evidence_indexes=[0, 1]))
        ref = result['result']['review_ref']
        assert ref['type'] == 'ReviewRecord'
        record = cs.read(ref)
        item, = record['payload']['items']
        assert item['reason'] == item['check_results'][0]['result'] == message()['assessment']
        assert item['observations'][0]['receipt_id'] == receipt
        assert 'receipt' in item['observations'][0]['observation'].lower()
        assert message()['assessment'] not in item['observations'][0]['observation']
        assert item['artifact_refs'] == task['review_requirements'][0]['artifact_refs']
        assert item['verdict'] == 'satisfied'
        assert any(ref['type'] == 'SourceArtifact' for ref in record['payload']['dependency_refs'])
        with cs.store.connect() as db:
            assert db.execute('SELECT count(*) FROM content_observations').fetchone()[0] == before
        reopened = ContentStore(Store(cs.store.root))
        assert reopened.read(ref) == record
        from report_agent.review_status import read_status
        status = read_status(reopened, task['review_snapshot_ref'])
        assert message()['assessment'] in json.dumps(status)
        assert receipt in json.dumps(status)
        assert native_review_submission_schema(v4=True, scope_selectors=True).model_json_schema() == old_schema
        assert not (cs.store.root / 'experimental-flat-records').exists()


def test_flat_replay_is_idempotent_and_changed_judgment_conflicts(case):
    from report_agent.review_message import bind_review_message, save_review_message
    with unit(case) as (cs, actor, receipt, _):
        binding = bind_review_message(cs, actor, [receipt])
        first = save_review_message(cs, actor, 'same-call', binding, message())
        again = save_review_message(cs, actor, 'same-call', binding, message())
        assert again['result'] == first['result']
        assert len(cs.list_objects('ReviewRecord')) == 1
        with pytest.raises(ActionRejected, match='OPERATION_CONFLICT'):
            save_review_message(cs, actor, 'same-call', binding, message(assessment='Changed judgment.'))


@pytest.mark.parametrize('update', [
    {'evidence_indexes': [99]}, {'evidence_indexes': [0, 0]}, {'evidence_indexes': []},
    {'execution_state': 'partial'}, {'remaining_work': None}, {'target_ref': {}},
])
def test_invalid_message_cannot_save_a_review(case, update):
    from report_agent.review_message import bind_review_message, save_review_message
    from pydantic import ValidationError
    with unit(case) as (cs, actor, receipt, _):
        binding = bind_review_message(cs, actor, [receipt])
        with pytest.raises((ActionRejected, ValidationError)):
            save_review_message(cs, actor, 'invalid', binding, message(**update))
        assert cs.list_objects('ReviewRecord') == []


def test_receipt_drift_and_foreign_owner_fail_before_save(case):
    from report_agent.review_message import bind_review_message, save_review_message
    with unit(case) as (cs, actor, receipt, _):
        binding = bind_review_message(cs, actor, [receipt])
        with cs.store.connect() as db:
            db.execute('UPDATE content_observations SET data=? WHERE id=?', ('{}', receipt))
        with pytest.raises(ActionRejected, match='RECEIPT_BINDING_CHANGED'):
            save_review_message(cs, actor, 'drift', binding, message())
        with cs.store.connect() as db:
            db.execute('UPDATE content_observations SET actor_id=? WHERE id=?', ('foreign', receipt))
        with pytest.raises((ActionRejected, ActionForbidden)):
            bind_review_message(cs, actor, [receipt])
        assert cs.list_objects('ReviewRecord') == []


def test_partial_negative_remains_visible_after_blocked_record(case):
    from report_agent.review_message import bind_review_message, save_review_message
    from report_agent.review_status import read_status
    with unit(case) as (cs, actor, receipt, task):
        binding = bind_review_message(cs, actor, [receipt])
        save_review_message(cs, actor, 'negative', binding, message(execution_state='partial',
            verdict='not_satisfied', assessment='A discrepancy remains.', remaining_work='Check the remaining source.'))
        save_review_message(cs, actor, 'blocked', binding, message(execution_state='blocked',
            verdict=None, evidence_indexes=[], assessment='Cannot continue yet.', remaining_work='Await missing source.'))
        records = cs.list_objects('ReviewRecord')
        assert len(records) == 2
        assert records[0]['payload']['items'][0]['execution_state'] == 'running'
        status = json.dumps(read_status(cs, task['review_snapshot_ref']))
        assert 'not_satisfied' in status and 'A discrepancy remains.' in status


def test_binding_is_actor_owned_and_cannot_silently_retarget(case):
    from report_agent.review_message import bind_review_message, save_review_message
    with unit(case) as (cs, actor, receipt, _):
        binding = bind_review_message(cs, actor, [receipt])
        changed = deepcopy(binding)
        changed['task_id'] = 'another-task'
        with pytest.raises((ActionForbidden, ActionRejected)):
            save_review_message(cs, actor, 'foreign-binding', changed, message())
        assert cs.list_objects('ReviewRecord') == []


def test_unoffered_or_reordered_evidence_cannot_reinterpret_a_saved_directory(case):
    from report_agent.review_message import bind_review_message, save_review_message
    with unit(case) as (cs, actor, receipt, task):
        binding = bind_review_message(cs, actor, [receipt])
        later = cs.read_context(actor, task['review_requirements'][0]['target_ref'])['receipt_id']
        forged = deepcopy(binding)
        with cs.store.connect() as db:
            import hashlib
            data = db.execute('SELECT data FROM content_observations WHERE id=?', (later,)).fetchone()[0]
        forged['receipts'] = [{'receipt_id': later, 'sha256': hashlib.sha256(data.encode()).hexdigest()}]
        with pytest.raises(ActionRejected, match='BINDING'):
            save_review_message(cs, actor, 'unoffered', forged, message())
        extended = bind_review_message(cs, actor, [receipt, later])
        assert extended['receipts'][:1] == binding['receipts']
        with pytest.raises(ActionRejected, match='REORDER'):
            bind_review_message(cs, actor, [later, receipt])
        assert ContentStore(Store(cs.store.root)).store.get('review_message_binding:' + digest(binding)) == binding


def test_receipt_change_between_assembly_and_transaction_is_rejected(case, monkeypatch):
    from report_agent.review_message import bind_review_message, save_review_message
    with unit(case) as (cs, actor, receipt, _):
        binding = bind_review_message(cs, actor, [receipt])
        original = cs.submit_review
        def change_then_save(*args, **kwargs):
            with cs.store.connect() as db:
                value = json.loads(db.execute('SELECT data FROM content_observations WHERE id=?', (receipt,)).fetchone()[0])
                db.execute('UPDATE content_observations SET data=? WHERE id=?',
                           (json.dumps({**value, 'changed_after_assembly': True}), receipt))
            return original(*args, **kwargs)
        monkeypatch.setattr(cs, 'submit_review', change_then_save)
        with pytest.raises(ActionRejected, match='RECEIPT_BINDING_CHANGED'):
            save_review_message(cs, actor, 'raced', binding, message())
        assert cs.list_objects('ReviewRecord') == []


@contextmanager
def export_unit(pair):
    workspace, cs, _, snapshot, _, refs, word, excel, _ = pair
    workspace.store.set('manifest', {**workspace.store.manifest,
        'review_execution_mode': 'native-reviewer-v2', 'review_interface_profile': 'review-interfaces-v4',
        'delegation_prompt_profile': 'separate-description-v1',
        'operation_identity_profile': 'native-tool-runtime-v1'})
    call = review_call([refs['k']], identity='message-export', scope={'kind': 'mapped', 'items': [{
        'criterion_ref': refs['k'], 'target_ref': snapshot, 'assessment_kind': 'export',
        'artifact_refs': [word, excel]}]})
    call['args']['review']['deliverable'] = {'kind': 'snapshot', 'snapshot_ref': snapshot}
    from report_agent.content_export import read_export
    with delegated_task(workspace, 'coordinator', call) as (_, actor):
        receipts = [read_export(cs, actor, ref)['receipt_id'] for ref in (word, excel)]
        yield workspace, cs, actor, snapshot, receipts


def test_real_word_excel_review_survives_delivery_and_reopen(pair):
    from report_agent.review_message import bind_review_message, save_review_message
    from report_agent.content_delivery import current_delivery
    with export_unit(pair) as (workspace, cs, actor, snapshot, receipts):
        binding = bind_review_message(cs, actor, receipts)
        result = save_review_message(cs, actor, 'joint-negative', binding,
            message(verdict='not_satisfied', evidence_indexes=[0, 1], assessment='Synthetic export discrepancy.'))
        ref = result['result']['review_ref']
        reopened = Store(cs.store.root)
        delivery = current_delivery(reopened)
        assert any(row['review_ref'] == ref for row in delivery['confirmed_violations'])
        assert 'Synthetic export discrepancy.' in json.dumps(delivery)
        assert ContentStore(reopened).read(ref)['payload']['items'][0]['findings'] == []


@pytest.mark.parametrize('selected', [[0], [1]])
def test_completed_export_cannot_omit_one_actual_artifact(pair, selected):
    from report_agent.review_message import bind_review_message, save_review_message
    with export_unit(pair) as (_, cs, actor, _, receipts):
        binding = bind_review_message(cs, actor, receipts)
        with pytest.raises(ActionRejected):
            save_review_message(cs, actor, 'incomplete-exports', binding, message(evidence_indexes=selected))
        assert cs.list_objects('ReviewRecord') == []


def test_unselected_material_pool_does_not_become_a_source_dependency(case):
    from report_agent.review_message import bind_review_message, save_review_message
    with unit(case) as (cs, actor, receipt, _):
        evidence_receipt = cs.read_context(actor, cs.list_objects('Evidence')[0]['ref'])['receipt_id']
        binding = bind_review_message(cs, actor, [receipt, evidence_receipt])
        result = save_review_message(cs, actor, 'only-body', binding, message())
        record = cs.read(result['result']['review_ref'])
        assert record['payload']['dependency_refs'] == []


def test_concurrent_directory_extensions_cannot_overwrite_one_another(case):
    from concurrent.futures import ThreadPoolExecutor
    from contextvars import copy_context
    from report_agent.review_message import bind_review_message
    with unit(case) as (cs, actor, receipt, task):
        original = bind_review_message(cs, actor, [receipt])
        more = [cs.read_context(actor, task['review_requirements'][0]['target_ref'])['receipt_id'] for _ in range(2)]
        def append(receipt_id):
            try:
                return bind_review_message(cs, actor, [receipt, receipt_id])
            except ActionRejected as error:
                return error
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [pool.submit(copy_context().run, append, row) for row in more]
            outcomes = [job.result() for job in jobs]
        successes = [row for row in outcomes if isinstance(row, dict)]
        assert len(successes) == 1
        assert cs.store.get('review_message_latest:' + actor.id) == successes[0]
        assert cs.store.get('review_message_binding:' + digest(original)) == original


@pytest.mark.parametrize('append_new_read', [False, True])
def test_rebinding_cannot_accept_changed_bytes_under_an_existing_receipt_id(case, append_new_read):
    from report_agent.review_message import bind_review_message
    with unit(case) as (cs, actor, receipt, task):
        original = bind_review_message(cs, actor, [receipt])
        ids = [receipt]
        if append_new_read:
            ids.append(cs.read_context(actor, task['review_requirements'][0]['target_ref'])['receipt_id'])
        with cs.store.connect() as db:
            data = json.loads(db.execute('SELECT data FROM content_observations WHERE id=?', (receipt,)).fetchone()[0])
            db.execute('UPDATE content_observations SET data=? WHERE id=?',
                       (json.dumps({**data, 'changed_after_first_binding': True}), receipt))
        with pytest.raises(ActionRejected, match='RECEIPT_BINDING_CHANGED'):
            bind_review_message(cs, actor, ids)
        assert cs.store.get('review_message_latest:' + actor.id) == original
        assert cs.store.get('review_message_binding:' + digest(original)) == original
