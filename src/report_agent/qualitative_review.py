"""Frozen, slope-scoped Reviewer assignments over saved qualitative Writer rows."""
from .writer_judgments import read_progress
from contextlib import contextmanager
from uuid import uuid4

from .commission_plan import _state
from .content_store import Actor, ContentStore
from .errors import ActionForbidden, ActionRejected
from .store import digest, encode


def freeze_writer_rows(cs, db, writer_ref):
    """Coordinator transaction: resolve the draft only through a verified Writer assignment."""
    from .writer_assessment import _assignment
    if not isinstance(writer_ref, dict) or writer_ref.get('type') != 'DelegatedTask' or writer_ref.get('version') != 1:
        raise ActionRejected('QUALITATIVE_REVIEW_WRITER_TASK_REQUIRED')
    task = cs._read(db, writer_ref)
    if task['payload'].get('role') != 'writer' or task['owner_id'] != 'content:coordinator':
        raise ActionForbidden('QUALITATIVE_REVIEW_WRITER_TASK_REQUIRED')
    writer = Actor('content:writer:' + writer_ref['id'], 'writer', writer_ref['id'])
    scope = _assignment(cs, db, writer)
    draft = read_progress(cs.store, scope['assignment_digest'], db)
    if 'object_facts' not in scope or not draft or not draft['rows']:
        raise ActionRejected('QUALITATIVE_REVIEW_SAVED_ROWS_REQUIRED')
    oid = scope['object']['object_id']
    plan = scope['plan']
    pack = plan['payload']['method_pack']
    facts = scope['object_facts']
    methods = {r['id']: r for r in pack['indicators'] if r['id'] in scope['assigned_indicators']}
    if not set(draft['rows']).issubset(methods):
        raise ActionRejected('QUALITATIVE_REVIEW_ROW_OUTSIDE_SCOPE')
    from .commission_plan import _citations
    from .deliverables import source_authority
    for citation in _citations(draft['rows']):
        if citation['source_ref'] not in scope['sources']:
            raise ActionForbidden('QUALITATIVE_REVIEW_SOURCE_OUTSIDE_ASSIGNMENT')

    from .hierarchical_tools import actor_for
    records = [cs._read(db, ref) for ref in scope['sources']]
    source_authority(cs, db, actor_for('coordinator'), records)
    sources = []
    for record in records:
        ref, source = record['ref'], record['payload']
        sources.append({'ref':ref, 'source_id':source['source_id'], 'file_digest':source['file_digest']})
    provenance = {'writer_task_ref':writer_ref, 'assignment_digest':scope['assignment_digest'],
                  'plan_ref':plan['ref'], 'decision_ref':scope['decision']['ref'],
                  'requirements_ref':plan['payload'].get('requirements_ref'),
                  'profile_digest':digest([scope['assigned_indicators'], facts, scope.get('midpoint_convention')]),
                  'method_digest':digest(pack), 'register_sha256':scope.get('register_sha256'),
                  'fact_digest':digest(facts), 'source_versions':sources}
    frozen = {'object_id':oid, 'provenance':provenance, 'object_facts':facts, 'methods':methods,
              'midpoint_convention':scope.get('midpoint_convention'), 'rows':draft['rows']}
    pin = digest(frozen)
    db.execute('INSERT OR IGNORE INTO state(key,value) VALUES (?,?)',
               ('qualitative_reviewer_snapshot:'+pin, encode(frozen)))
    return {'qualitative_review_digest':pin,
            'write_scope':'Record separate findings against the assigned frozen rows. Engineering acceptance belongs to humans.'}


def _assigned(cs, db, reviewer):
    from .content_tasks import bound_actor
    from .workspace import Workspace
    if reviewer.role != 'reviewer' or bound_actor(Workspace(cs.store), 'reviewer', None) != reviewer:
        raise ActionForbidden('QUALITATIVE_REVIEW_DELEGATION_REQUIRED')
    ref = {'type':'DelegatedTask','id':reviewer.task_id,'version':1}
    task = cs._read(db, ref)
    pin = task['payload'].get('qualitative_review_digest')
    if not pin or task['owner_id'] != 'content:coordinator' or task['payload']['role'] != 'reviewer':
        raise ActionForbidden('QUALITATIVE_REVIEW_DELEGATION_REQUIRED')
    frozen = _state(db, 'qualitative_reviewer_snapshot:' + pin)
    if not frozen or digest(frozen) != pin:
        raise ActionRejected('QUALITATIVE_REVIEW_FROZEN_DIGEST_MISMATCH')
    return ref, pin, frozen
