"""Re-derive one commissioned assessment explicitly after the owner has reviewed its inputs."""
import argparse
import json
from pathlib import Path

from .assessment_projection import assessment_receipt, selected_assessment
from .assessment_results import lookup_committed_derivation
from .commission_plan import _confirmed
from .content_store import Actor, ContentStore
from .errors import ActionForbidden, ActionRejected
from .risk_scoring import save_assessment_in_transaction
from .store import Store
from .writer_assessment import _assignment, _derivation_scope
from .writer_judgments import read_progress


def refresh_selected_assessment(contents, object_id):
    with contents.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        plan, _ = _confirmed(contents, db)
        ref = selected_assessment(db, plan['ref'], object_id)
        prior = assessment_receipt(db, ref) if ref else None
        if not prior or not prior.get('derived_assertion_id'):
            raise ActionRejected('ASSESSMENT_NATIVE_DERIVATION_REQUIRED')
        record = contents._read(db, ref)
        actor = Actor(record['owner_id'], 'writer', record['task_id'])
        operation = 'reviewed-assessment:' + prior['derived_assertion_id']
        status = prior['derivation_status']
        scope = (_assignment(contents, db, actor) if status == 'scored'
                 else _derivation_scope(contents, db, actor, operation))
        if scope['object']['object_id'] != object_id:
            raise ActionForbidden('FORBIDDEN: assessment outside producer assignment')
        if status == 'scored':
            return {'assessment_ref': ref, 'status': status}
        if status != 'pending_review' and not lookup_committed_derivation(contents.store, scope['assignment_digest'], operation):
            raise ActionRejected('ASSESSMENT_REFRESH_INELIGIBLE: ' + status)
        if prior['result'].get('review_status') != 'pending_review':
            raise ActionRejected('ASSESSMENT_PENDING_DRAFT_REQUIRED')
        draft = read_progress(contents.store, scope['assignment_digest'], db)
        new = save_assessment_in_transaction(contents, db, actor, operation, scope=scope,
                                             draft=draft, require_reviewed=True)
        current = assessment_receipt(db, new['assessment_ref'])
        return {'assessment_ref': new['assessment_ref'], 'previous_ref': ref, 'status': current['derivation_status']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case', type=Path)
    parser.add_argument('object_id')
    args = parser.parse_args(argv)
    if not (args.case / 'state.db').is_file():
        parser.error('An existing commissioned case is required.')
    try:
        result = refresh_selected_assessment(ContentStore(Store(args.case)), args.object_id)
    except (ActionRejected, ActionForbidden) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
