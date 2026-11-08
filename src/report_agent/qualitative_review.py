"""Frozen, slope-scoped Reviewer assignments over saved qualitative Writer rows."""
from . import legacy_state as legacy
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
    draft = legacy.get_writer_indicator_steps(db, scope['assignment_digest'])
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
                  'profile_digest':digest([scope['assigned_indicators'], facts, scope['midpoint_convention']]),
                  'method_digest':digest(pack), 'register_sha256':scope['register_sha256'],
                  'fact_digest':digest(facts), 'source_versions':sources}
    frozen = {'object_id':oid, 'provenance':provenance, 'object_facts':facts, 'methods':methods,
              'midpoint_convention':scope['midpoint_convention'], 'rows':draft['rows']}
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


def reviewer_tools(cs, actor):
    def read_qualitative_row(indicator_id: str | None = None) -> dict:
        """List this assignment's frozen rows or inspect one row, its facts, method and provenance."""
        with cs.store.connect() as db:
            task, pin, view = _assigned(cs, db, actor())
        header = {'review_task_ref':task, 'snapshot_digest':pin, 'object_id':view['object_id'],
                  'provenance':view['provenance']}
        if indicator_id is None:
            return {**header, 'rows':{k:digest(v) for k,v in view['rows'].items()}}
        if indicator_id not in view['rows']:
            raise ActionRejected('QUALITATIVE_REVIEW_ROW_OUTSIDE_SCOPE')
        row = view['rows'][indicator_id]
        return {**header, 'indicator_id':indicator_id, 'row_digest':digest(row), 'saved_row':row,
                'indicator_method':view['methods'][indicator_id], 'object_facts':view['object_facts'],
                'midpoint_convention':view['midpoint_convention']}

    def record_qualitative_finding(operation_id: str, indicator_id: str, row_digest: str,
                                   finding: str) -> dict:
        """Record a separate Reviewer finding against one exact frozen row; the Writer retains row ownership."""
        reviewer = actor()
        def record(db):
            task, pin, view = _assigned(cs, db, reviewer)
            if indicator_id not in view['rows'] or digest(view['rows'][indicator_id]) != row_digest:
                raise ActionRejected('QUALITATIVE_REVIEW_ROW_DIGEST_MISMATCH')
            if not finding.strip():
                raise ActionRejected('QUALITATIVE_REVIEW_FINDING_REQUIRED')
            payload = {'review_task_ref':task, 'snapshot_digest':pin, 'object_id':view['object_id'],
                       'indicator_id':indicator_id, 'row_digest':row_digest, 'finding':finding}
            return {'finding_ref':cs._insert(db, reviewer, 'QualitativeRowFinding', payload)}
        return cs.operation(reviewer, operation_id, {'indicator_id':indicator_id, 'row_digest':row_digest,
                            'qualitative_finding':finding}, record)
    return [read_qualitative_row, record_qualitative_finding]


@contextmanager
def qualitative_reviewer_session(workspace, writer_task_ref):
    """Trusted offline operator entry, with native Coordinator delegation and restricted Reviewer tools."""
    from .content_tasks import delegated_task
    from .hierarchical_tools import content_tools
    call = {'name':'task', 'id':'qualitative-review-'+uuid4().hex,
            'args':{'subagent_type':'reviewer', 'description':('Review the assigned rows against their cited excerpts, confirmed facts and method. '
                                   'Check the grade, rationale, assumptions, adjustment and follow-up question together. '
                                   'Record findings against exact row digests and refer weak bases to engineers.'),
                    'qualitative_writer_task_ref':writer_task_ref}}
    with delegated_task(workspace, 'coordinator', call):
        yield {tool.__name__:tool for tool in content_tools(workspace,'reviewer')}
