"""R1-A internal review services preserve legacy saves and independent judgment."""
from copy import deepcopy
import sqlite3

import pytest

from report_agent.content_store import Actor, ContentStore
from report_agent.content_tasks import delegated_task
from report_agent.errors import ActionForbidden, ActionRejected
from report_agent.review_message import assemble_review_message, bind_review_message
from report_agent.store import Store, encode
from test_deliverable_declaration_v4 import case
from test_review_handles import bound_review
from test_review_message import message
from test_review_binding_v4 import review_call
from test_selected_companion_reviews import pair, ws
from test_review_message import export_unit


def observation_handle(cs, actor, receipt):
    from report_agent import review_handles as h
    return next(k for k, v in h.evidence_handles(cs, actor).items() if v == receipt)


def finding(cs, actor, operation, evidence_handle, **updates):
    from report_agent import review_steps as s
    return s.record_finding(cs, actor, operation, **{'check': 'C1', 'kind': 'confirmed_defect',
        'claim': 'The selected synthetic claim conflicts with the source.',
        'impact': 'This changes the stated classification.', 'needed_outcome': 'Correct from the actual source.',
        'location': 'S1.1', 'basis': 'supplied_content', 'evidence': [evidence_handle], **updates})


def mark(cs, actor, operation, evidence_handle, **updates):
    from report_agent import review_steps as s
    return s.mark_check(cs, actor, operation, **{'check': 'C1', 'execution_state': 'completed',
        'verdict': 'not_satisfied', 'assessment': 'Compared the actual synthetic body and supporting read.',
        'evidence': [evidence_handle], **updates})


def test_multiple_findings_keep_individual_evidence_locations_and_idempotent_save(case):
    from report_agent import review_steps as s
    with bound_review(case) as (cs, ws, actor, receipt, task, output):
        first = observation_handle(cs, actor, receipt)
        other_receipt = cs.read_context(actor, output['refs']['a-body'])['receipt_id']
        second = observation_handle(cs, actor, other_receipt)
        a = finding(cs, actor, 'r1a-f1', first)['result']['finding']
        b = finding(cs, actor, 'r1a-f2', second, claim='A separate synthetic defect.')['result']['finding']
        assert (a, b) == ('F1', 'F2') and not cs.list_objects('ReviewRecord')
        assert finding(cs, actor, 'r1a-f1', first)['result']['finding'] == a
        saved = mark(cs, actor, 'r1a-mark', first, evidence=[first, second])
        assert saved['result']['open_checks'] == []
        assert mark(cs, actor, 'r1a-mark', first, evidence=[first, second]) == saved
        ref = saved['result']['review_ref']; record = cs.read(ref)
        item, = record['payload']['items']
        assert len(item['findings']) == 2 and item['verdict'] == 'not_satisfied'
        for index, expected in enumerate((receipt, other_receipt)):
            indexes = item['findings'][index]['observation_indexes']
            assert [item['observations'][i]['receipt_id'] for i in indexes] == [expected]
        links = s.saved_findings(cs, actor, ref)
        assert [(x['finding'], x['item_index'], x['finding_index']) for x in links] == [('F1', 0, 0), ('F2', 0, 1)]
        assert all(x['review_ref'] == ref and x['location_ref'] == output['refs']['a-body']
            and x['snapshot_ref'] == task['payload']['review_snapshot_ref'] and x['actor_id'] == actor.id for x in links)
        assert len(cs.list_objects('ReviewRecord')) == 1
        assert ContentStore(Store(cs.store.root)).read(ref) == record


def test_legacy_assembler_keeps_full_byte_exact_single_finding_submission(case):
    from report_agent import review_message as rm
    with bound_review(case) as (cs, ws, actor, receipt, task, output):
        binding = bind_review_message(cs, actor, [receipt])
        value = message(verdict='not_satisfied', finding_type='confirmed_defect', finding_locator_state='located',
            finding_description='A synthetic defect.', finding_impact='A synthetic impact.',
            finding_needed_outcome='Resolve using the source.', finding_basis_kind='supplied_content')
        legacy = assemble_review_message(cs, actor, binding, value)
        assembled = rm.assemble_check(cs, actor, binding, value)
        req = task['payload']['review_requirements'][0]
        scope = '  Exact outcome 0\nPreserve this condition.  '
        assessment = 'The selected synthetic body was compared; no whole-report approval.'
        # Full independent rc3 capture, source SHA 13319834ddd1aceacd821dcb2eec47b5d554f530ebedf04c55d4aa93387947a6.
        # Only actual immutable refs, scope identity and receipt are substituted.
        # The test never reads an analysis artifact or derives expected from either assembler.
        expected = {'snapshot_ref': task['payload']['review_snapshot_ref'], 'target_ref': req['target_ref'],
            'scope': scope, 'criteria_refs': [req['criterion_ref']], 'dependency_refs': [], 'items': [{
                'target_ref': req['target_ref'], 'criterion_ref': req['criterion_ref'], 'scope_id': req['scope_id'],
                'scope': scope, 'assessment_kind': 'content', 'artifact_refs': [], 'execution_state': 'completed',
                'verdict': 'not_satisfied', 'observations': [{'receipt_id': receipt, 'locator': 'receipt:' + receipt,
                    'observation': 'Program-bound actual read receipt, not a reviewer-authored per-material judgment.',
                    'limitations': 'The reviewer judgment is saved separately in reason and check result.'}],
                'reason': assessment, 'findings': [{'finding_type': 'confirmed_defect', 'locator_state': 'located',
                    'description': 'A synthetic defect.', 'impact': 'A synthetic impact.', 'needed_outcome': 'Resolve using the source.',
                    'basis_kind': 'supplied_content', 'requirement_index': 0, 'observation_indexes': [0]}],
                'outside_assignment_notes': [], 'checked_requirement_indexes': [0], 'check_results': [{
                    'requirement_index': 0, 'execution_state': 'completed', 'result': assessment,
                    'observation_indexes': [0], 'remaining': ''}], 'coverage': {'checked': [scope],
                    'unchecked': [], 'blocked': [],
                    'basis': 'Model-declared progress for this assigned check only; not whole-report acceptance.'}}],
            'coverage_accounting': []}
        assert encode(legacy) == encode(expected)
        assert encode(assembled) == encode(expected)
        assert not cs.list_objects('ReviewRecord')


@pytest.mark.parametrize('changes', [
    {'execution_state': 'not_started', 'verdict': 'satisfied', 'remaining_work': 'Not done.'},
    {'execution_state': 'partial', 'verdict': 'satisfied', 'remaining_work': 'More work.'},
    {'execution_state': 'completed', 'remaining_work': 'Still unfinished.'},
    {'evidence': []}, {'assessment': ' '},
])
def test_existing_message_semantic_guards_still_refuse_without_saving(case, changes):
    with bound_review(case) as (cs, ws, actor, receipt, task, output):
        with pytest.raises(ActionRejected):
            mark(cs, actor, 'r1a-invalid', observation_handle(cs, actor, receipt), **changes)
        assert not cs.list_objects('ReviewRecord')


def test_confirmed_defect_cannot_pass_or_be_created_from_input_gap(case):
    with bound_review(case) as (cs, ws, actor, receipt, task, output):
        evidence = observation_handle(cs, actor, receipt)
        with pytest.raises(ActionRejected):
            finding(cs, actor, 'r1a-gap', evidence, basis='input_gap')
        finding(cs, actor, 'r1a-defect', evidence)
        with pytest.raises(ActionRejected):
            mark(cs, actor, 'r1a-false-pass', evidence, verdict='satisfied')
        assert not cs.list_objects('ReviewRecord')


def test_receipt_bytes_bound_when_finding_was_recorded_cannot_change_before_mark(case):
    with bound_review(case) as (cs, ws, actor, receipt, task, output):
        evidence = observation_handle(cs, actor, receipt)
        finding(cs, actor, 'r1a-evidence-bound-finding', evidence)
        with cs.store.connect() as db:
            assert db.execute('UPDATE content_observations SET data=? WHERE id=?',
                (encode({'synthetic': 'changed after the recorded finding'}), receipt)).rowcount == 1
        with pytest.raises(ActionRejected):
            mark(cs, actor, 'r1a-evidence-drift-save', evidence)
        assert not cs.list_objects('ReviewRecord')


def test_correction_keeps_both_records_and_lineage_atomic_on_failure(case, monkeypatch):
    from report_agent import review_steps as s
    with bound_review(case) as (cs, ws, actor, receipt, task, output):
        evidence = observation_handle(cs, actor, receipt)
        saved_finding = finding(cs, actor, 'r1a-initial-finding', evidence)['result']['finding']
        first = mark(cs, actor, 'r1a-first-mark', evidence)['result']['review_ref']
        original_record = deepcopy(cs.read(first)); original_insert = cs._insert
        def refuse_supersession(db, owner, kind, payload, **kwargs):
            if kind == 'ReviewSupersession':
                raise ActionRejected('SYNTHETIC_SUPERSESSION_FAILURE')
            return original_insert(db, owner, kind, payload, **kwargs)
        monkeypatch.setattr(cs, '_insert', refuse_supersession)
        with pytest.raises(ActionRejected, match='SYNTHETIC_SUPERSESSION_FAILURE'):
            mark(cs, actor, 'r1a-failed-correction', evidence, findings=[saved_finding],
                correction_reason='The earlier assessment omitted a verified condition.',
                assessment='Explicit correction: better grounded detail.')
        assert cs.list_objects('ReviewRecord') == [original_record]
        assert not cs.list_objects('ReviewSupersession')
        monkeypatch.setattr(cs, '_insert', original_insert)
        fixed = mark(cs, actor, 'r1a-good-correction', evidence, findings=[saved_finding],
            correction_reason='The earlier assessment omitted a verified condition.',
            assessment='Explicit correction: better grounded detail.')['result']['review_ref']
        assert fixed != first and cs.read(first) == original_record
        supersession, = cs.list_objects('ReviewSupersession')
        assert supersession['payload']['review_ref'] == first and supersession['payload']['replacement_ref'] == fixed
        assert supersession['payload']['reason'] == 'The earlier assessment omitted a verified condition.'
        assert s.saved_findings(cs, actor, first)[0]['location_ref'] == output['refs']['a-body']
        assert s.saved_findings(cs, actor, fixed)[0]['location_ref'] == output['refs']['a-body']


def test_finish_lists_all_open_items_withdraw_requires_reason_and_metrics_count_once(case):
    from report_agent import review_steps as s
    with bound_review(case, two=True) as (cs, ws, actor, receipt, task, output):
        evidence = observation_handle(cs, actor, receipt)
        a = finding(cs, actor, 'r1a-draft-a', evidence)['result']['finding']
        b = finding(cs, actor, 'r1a-draft-b', evidence)['result']['finding']
        with pytest.raises(ActionRejected) as error:
            s.finish_review(cs, actor, 'r1a-too-early', summary='Not finished.')
        assert error.value.diagnostic['open_checks'] == ['C1', 'C2']
        assert error.value.diagnostic['open_drafts'] == [a, b]
        with pytest.raises(ActionRejected):
            s.withdraw_finding(cs, actor, 'r1a-no-reason', a, ' ')
        withdrawn = s.withdraw_finding(cs, actor, 'r1a-withdraw', a, 'Source reread disproved this candidate.')
        assert s.withdraw_finding(cs, actor, 'r1a-withdraw', a, 'Source reread disproved this candidate.') == withdrawn
        assert s.metrics(cs.store, task_id=actor.task_id)['withdrawals'] == 1
        assert cs.store.status()['reviewer_steps']['withdrawals'] == 1
        assert 'Source reread disproved this candidate.' in encode(cs.store.get('review_draft:' + actor.task_id + ':' + a))
        assert mark(cs, actor, 'r1a-mark-c1', evidence)['result']['open_checks'] == ['C2']
        last_mark = mark(cs, actor, 'r1a-mark-c2', evidence, check='C2', execution_state='blocked', verdict=None,
            assessment='The second check is blocked.', remaining_work='Await the actual missing comparison material.')
        assert last_mark['result']['open_checks'] == []
        closed = s.finish_review(cs, actor, 'r1a-close', summary='One unresolved blocked check remains explicit.')
        assert closed['ok'] and closed['result']['unresolved_checks'] == ['C2']
        assert not closed['result'].get('whole_report_acceptance')
        assert s.finish_review(cs, actor, 'r1a-close', summary='One unresolved blocked check remains explicit.') == closed
        with pytest.raises(ActionRejected, match='REVIEW_FINISHED'):
            finding(cs, actor, 'r1a-after-close', evidence)
        with pytest.raises(ActionRejected, match='REVIEW_FINISHED'):
            mark(cs, actor, 'r1a-after-close-mark', evidence)
        with pytest.raises(ActionRejected, match='REVIEW_FINISHED'):
            s.withdraw_finding(cs, actor, 'r1a-after-close-withdraw', b, 'Do not silently reopen a closed task.')


def test_all_checks_marked_does_not_hide_open_unattached_findings(case):
    from report_agent import review_steps as s
    with bound_review(case) as (cs, ws, actor, receipt, task, output):
        evidence = observation_handle(cs, actor, receipt)
        first = finding(cs, actor, 'r1a-open-first', evidence)['result']['finding']
        second = finding(cs, actor, 'r1a-open-second', evidence)['result']['finding']
        mark(cs, actor, 'r1a-checked-but-unattached', evidence, findings=[])
        with pytest.raises(ActionRejected) as error:
            s.finish_review(cs, actor, 'r1a-open-finish', summary='The check was performed; drafts remain.')
        assert error.value.diagnostic['open_checks'] == []
        assert error.value.diagnostic['open_drafts'] == [first, second]
        s.withdraw_finding(cs, actor, 'r1a-withdraw-first', first, 'This draft duplicated the second observation.')
        with pytest.raises(ActionRejected) as error:
            s.finish_review(cs, actor, 'r1a-still-open', summary='One draft remains.')
        assert error.value.diagnostic['open_drafts'] == [second]
        s.withdraw_finding(cs, actor, 'r1a-withdraw-second', second, 'Further supplied evidence disproved the draft.')
        assert s.finish_review(cs, actor, 'r1a-final-finish', summary='All drafts explicitly disposed of.')['ok']
        assert s.metrics(cs.store, task_id=actor.task_id)['withdrawals'] == 2


def test_unresolved_native_operation_cannot_be_replayed_or_release_saved_lineage(case):
    from report_agent import review_steps as s
    with bound_review(case) as (cs, ws, actor, receipt, task, output):
        evidence = observation_handle(cs, actor, receipt)
        result = mark(cs, actor, 'r1a-lost-return', evidence)
        op = result['receipt_id']
        pending = {'ok': False, 'code': 'OPERATION_OUTCOME_UNRESOLVED',
            'message': 'OPERATION_OUTCOME_UNRESOLVED: synthetic lost completion',
            'retryable': False, 'receipt_id': op}
        # Model a durable unresolved receipt without inventing a new recovery API
        # or touching any financial/provider ledger.
        with cs.store.connect() as db:
            assert db.execute('UPDATE content_operations SET response=? WHERE operation_id=?', (encode(pending), op)).rowcount == 1
            before = db.execute('SELECT * FROM content_operations WHERE operation_id=?', (op,)).fetchone()
        records = deepcopy(cs.list_objects('ReviewRecord'))
        with pytest.raises(ActionRejected, match='OPERATION_OUTCOME_UNRESOLVED'):
            mark(cs, actor, 'r1a-lost-return', evidence)
        assert cs.list_objects('ReviewRecord') == records
        with cs.store.connect() as db:
            assert db.execute('SELECT * FROM content_operations WHERE operation_id=?', (op,)).fetchone() == before
        assert cs.receipt(actor, op)['state'] == 'outcome_unresolved'


def test_saved_finding_locations_cannot_be_read_or_changed_by_another_task(case):
    from report_agent import review_steps as s
    with bound_review(case) as (cs, ws, actor, receipt, task, output):
        evidence = observation_handle(cs, actor, receipt)
        finding(cs, actor, 'r1a-owned-f', evidence)
        saved = mark(cs, actor, 'r1a-owned-mark', evidence)['result']['review_ref']
        links = deepcopy(s.saved_findings(cs, actor, saved))
        req = task['payload']['review_requirements'][0]
        call = review_call([req['criterion_ref']], identity='r1a-foreign-task', scope={'kind': 'mapped', 'items': [{
            'criterion_ref': req['criterion_ref'], 'target_ref': req['target_ref'],
            'assessment_kind': 'content', 'extent': 'local_body'}]})
        with delegated_task(ws, 'coordinator', call) as (_, other):
            with pytest.raises(ActionForbidden):
                s.saved_findings(cs, other, saved)
            with pytest.raises(ActionForbidden):
                finding(cs, actor, 'r1a-spoof-owner', evidence)
            assert s.metrics(cs.store, task_id=other.task_id)['withdrawals'] == 0
        assert s.saved_findings(cs, actor, saved) == links


@pytest.mark.parametrize('changes,diagnostic_word', [
    ({'execution_state': 'blocked', 'verdict': None, 'remaining_work': ''}, 'remaining'),
    ({'execution_state': 'partial', 'verdict': None, 'remaining_work': ' '}, 'remaining'),
    ({'remaining_work': ' '}, 'remaining'),
    ({'evidence': ['obs-1', 'obs-1']}, 'evidence'),
    ({'evidence': ['obs-999']}, 'evidence'),
    ({'evidence': [0]}, 'evidence'),
    ({'check': 'C999'}, 'check'),
    ({'findings': ['F999']}, 'finding'),
])
def test_additional_mark_diagnostics_do_not_silently_normalize_invalid_fields(case, changes, diagnostic_word):
    with bound_review(case) as (cs, ws, actor, receipt, task, output):
        evidence = observation_handle(cs, actor, receipt)
        with pytest.raises(ActionRejected) as error:
            mark(cs, actor, 'r1a-bad-mark-fields', evidence, **changes)
        text = (str(error.value) + encode(error.value.diagnostic)).lower()
        assert diagnostic_word in text
        assert not cs.list_objects('ReviewRecord')


@pytest.mark.parametrize('changes', [
    {'claim': ' '}, {'impact': ' '}, {'needed_outcome': ' '},
    {'location': None}, {'location': 'S999'},
])
def test_finding_component_and_location_guards_apply_before_any_draft_is_saved(case, changes):
    from report_agent import review_steps as s
    with bound_review(case) as (cs, ws, actor, receipt, task, output):
        with pytest.raises(ActionRejected):
            finding(cs, actor, 'r1a-bad-finding-fields', observation_handle(cs, actor, receipt), **changes)
        assert s.metrics(cs.store, task_id=actor.task_id)['drafts'] == 0
        assert not cs.list_objects('ReviewRecord')


@pytest.mark.parametrize('location,state', [('absent', 'absent'), ('unclear', 'ambiguous')])
def test_nonlocated_findings_preserve_locator_state_without_inventing_reference(case, location, state):
    from report_agent import review_steps as s
    with bound_review(case) as (cs, ws, actor, receipt, task, output):
        evidence = observation_handle(cs, actor, receipt)
        handle = finding(cs, actor, 'r1a-unlocated', evidence, kind='unresolved', location=location,
            basis='input_gap' if location == 'absent' else 'supplied_content')['result']['finding']
        ref = mark(cs, actor, 'r1a-unlocated-mark', evidence, verdict='undetermined',
            findings=[handle])['result']['review_ref']
        item, = cs.read(ref)['payload']['items']
        assert item['findings'][0]['locator_state'] == state
        link, = s.saved_findings(cs, actor, ref)
        assert link['finding'] == handle and link['location_ref'] is None


def test_multifinding_selection_cannot_pass_or_repeat_a_finding_handle(case):
    with bound_review(case) as (cs, ws, actor, receipt, task, output):
        evidence = observation_handle(cs, actor, receipt)
        confirmed = finding(cs, actor, 'r1a-multi-confirmed', evidence)['result']['finding']
        candidate = finding(cs, actor, 'r1a-multi-candidate', evidence, kind='candidate')['result']['finding']
        with pytest.raises(ActionRejected):
            mark(cs, actor, 'r1a-multi-false-pass', evidence, verdict='satisfied', findings=[candidate, confirmed])
        with pytest.raises(ActionRejected):
            mark(cs, actor, 'r1a-duplicate-finding', evidence, findings=[confirmed, confirmed])
        assert not cs.list_objects('ReviewRecord')


@pytest.mark.parametrize('reason', [None, ' '], ids=['omitted', 'blank'])
def test_re_mark_requires_a_separate_explicit_correction_reason(case, reason):
    with bound_review(case) as (cs, ws, actor, receipt, task, output):
        evidence = observation_handle(cs, actor, receipt)
        first = mark(cs, actor, 'r1a-correction-original', evidence)['result']['review_ref']
        before = deepcopy(cs.read(first))
        fields = {} if reason is None else {'correction_reason': reason}
        with pytest.raises(ActionRejected):
            mark(cs, actor, 'r1a-correction-no-reason', evidence,
                assessment='A new assessment alone does not explain why the original was wrong.', **fields)
        assert cs.list_objects('ReviewRecord') == [before]
        assert not cs.list_objects('ReviewSupersession')


def test_completed_coverage_is_only_frozen_check_target_and_partial_never_assessed(case):
    with bound_review(case, two=True) as (cs, ws, actor, receipt, task, output):
        evidence = observation_handle(cs, actor, receipt)
        complete = mark(cs, actor, 'r1a-target-accounting', evidence)['result']['review_ref']
        accounting, = cs.read(complete)['payload']['coverage_accounting']
        assert accounting['target_refs'] == [task['payload']['review_requirements'][0]['target_ref']]
        assert accounting['state'] == 'assessed' and accounting['item_indexes'] == [0] and accounting['reason'].strip()
        partial = mark(cs, actor, 'r1a-partial-accounting', evidence, check='C2', execution_state='partial',
            verdict=None, remaining_work='The assigned comparison still needs work.')['result']['review_ref']
        assert not any(e['state'] == 'assessed' for e in cs.read(partial)['payload']['coverage_accounting'])
        with pytest.raises(ActionRejected):
            mark(cs, actor, 'r1a-forged-accounting', evidence, coverage_object_indexes=[0],
                correction_reason='This caller-provided accounting is forbidden, not an authorized replacement.',
                coverage_state='assessed', coverage_reason='Caller cannot choose coverage or another target.')


def test_export_check_records_progress_without_fabricating_object_accounting(pair):
    with export_unit(pair) as (workspace, cs, actor, snapshot, receipts):
        handles = [observation_handle(cs, actor, receipt) for receipt in receipts]
        saved = mark(cs, actor, 'r1a-export-check', handles[0], evidence=handles,
            assessment='Actual Word and Excel were read for this export check.')
        record = cs.read(saved['result']['review_ref'])['payload']
        assert record['target_ref'] == snapshot and record['items'][0]['execution_state'] == 'completed'
        assert record['coverage_accounting'] == [], 'Snapshot/export targets are not invented ContentNode accounting objects'
        assert saved['result']['open_checks'] == []


def test_validation_reports_bad_handles_and_all_blank_finding_fields_together(case):
    from report_agent import review_steps as s
    with bound_review(case) as (cs, ws, actor, receipt, task, output):
        with pytest.raises(ActionRejected) as error:
            finding(cs, actor, 'r1a-aggregate-fields', observation_handle(cs, actor, receipt),
                check='C999', claim=' ', impact=' ', needed_outcome=' ', location='S999', evidence=['obs-999'])
        diagnostic = encode(error.value.diagnostic)
        assert all(word in diagnostic for word in ('claim', 'impact', 'needed_outcome', 'C999', 'S999', 'obs-999', 'valid_handles'))
        assert receipt not in diagnostic and s.metrics(cs.store, task_id=actor.task_id)['drafts'] == 0


@pytest.mark.parametrize('invalid,field', [({'check': 42}, 'check'),
    ({'evidence': [42]}, 'evidence')], ids=['invalid-check-type', 'invalid-evidence-type'])
def test_schema_errors_do_not_hide_other_safe_semantic_diagnostics(case, invalid, field):
    from report_agent import review_steps as s
    with bound_review(case) as (cs, ws, actor, receipt, task, output):
        evidence = observation_handle(cs, actor, receipt)
        records = deepcopy(cs.list_objects())
        metrics = deepcopy(s.metrics(cs.store, task_id=actor.task_id))
        finished = [e for e in cs.store.events() if e['kind'] == 'review_finished']
        with cs.store.connect() as db:
            reads = db.execute('SELECT count(*) FROM content_observations').fetchone()[0]
        with pytest.raises(ActionRejected) as error:
            finding(cs, actor, 'r1a-mixed-schema', evidence, claim=' ', impact=' ', needed_outcome=' ',
                location='S999', **invalid)
        diagnostic = encode(error.value.diagnostic)
        reported = {name for issue in error.value.diagnostic['fields']
            for name in [*issue.get('field', []), *issue.get('related_fields', [])] if isinstance(name, str)}
        assert {field, 'claim', 'impact', 'needed_outcome'} <= reported
        assert receipt not in diagnostic
        assert cs.list_objects() == records
        assert s.metrics(cs.store, task_id=actor.task_id) == metrics
        assert [e for e in cs.store.events() if e['kind'] == 'review_finished'] == finished
        assert cs.receipt(actor, 'r1a-mixed-schema')['state'] != 'known_success'
        with cs.store.connect() as db:
            assert db.execute('SELECT count(*) FROM content_observations').fetchone()[0] == reads
        # Lazy immutable alias caches may be persisted by diagnostic lookups;
        # these are not a new read, operation success or business mutation.


def test_invalid_finding_selection_does_not_default_to_all_saved_drafts(case):
    from report_agent import review_steps as s
    with bound_review(case) as (cs, ws, actor, receipt, task, output):
        evidence = observation_handle(cs, actor, receipt)
        confirmed = finding(cs, actor, 'r1a-selection-draft', evidence)['result']['finding']
        records = deepcopy(cs.list_objects())
        metrics = deepcopy(s.metrics(cs.store, task_id=actor.task_id))
        with pytest.raises(ActionRejected) as error:
            mark(cs, actor, 'r1a-invalid-selection', evidence, findings=[42], verdict='satisfied')
        issues = error.value.diagnostic['fields']
        assert any(issue.get('field') == ['findings', 0]
            and issue.get('reason') == 'string_type' for issue in issues)
        assert not any(issue.get('reason') == 'FINDING_CANNOT_PASS' for issue in issues)
        # A valid explicit selection still enforces the confirmed-defect rule.
        with pytest.raises(ActionRejected) as valid_selection:
            mark(cs, actor, 'r1a-valid-selection-cannot-pass', evidence,
                findings=[confirmed], verdict='satisfied')
        assert any(issue.get('reason') == 'FINDING_CANNOT_PASS'
            for issue in valid_selection.value.diagnostic['fields'])
        assert cs.list_objects() == records
        assert s.metrics(cs.store, task_id=actor.task_id) == metrics
        assert cs.receipt(actor, 'r1a-invalid-selection')['state'] != 'known_success'


def test_finish_event_and_operation_proof_commit_together_exactly_once(case):
    from report_agent import review_steps as s
    with bound_review(case) as (cs, ws, actor, receipt, task, output):
        evidence = observation_handle(cs, actor, receipt)
        mark(cs, actor, 'r1a-finish-ready-check', evidence)
        with cs.store.connect() as db:
            db.execute("CREATE TRIGGER r1a_reject_finish BEFORE INSERT ON events WHEN NEW.kind='review_finished' "
                "BEGIN SELECT RAISE(ABORT,'SYNTHETIC_FINISH_EVENT_FAILURE'); END")
        with pytest.raises((sqlite3.DatabaseError, ActionRejected)):
            s.finish_review(cs, actor, 'r1a-finish-fails', summary='Do not close without the event.')
        assert cs.receipt(actor, 'r1a-finish-fails')['state'] != 'known_success'
        assert not [e for e in cs.store.events() if e['kind'] == 'review_finished']
        with cs.store.connect() as db:
            db.execute('DROP TRIGGER r1a_reject_finish')
        # A failed transaction cannot leave the task read-only/closed.
        handle = finding(cs, actor, 'r1a-after-failed-close', evidence, kind='candidate')['result']['finding']
        s.withdraw_finding(cs, actor, 'r1a-dispose-after-failure', handle, 'Explicitly dispose of the post-failure draft.')
        result = s.finish_review(cs, actor, 'r1a-finish-success', summary='Transaction and event now commit.')
        assert s.finish_review(cs, actor, 'r1a-finish-success', summary='Transaction and event now commit.') == result
        event, = [e for e in cs.store.events() if e['kind'] == 'review_finished']
        assert event['data']['task_id'] == actor.task_id
