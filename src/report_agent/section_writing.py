"""Assigned prose and issue proposals; document structure remains system-owned."""
from . import issue_state, report_state
from pydantic import Field
from .material_issues import StrictRecord, IssueSource
from .errors import ActionForbidden
from .store import digest, encode


class IssueProposal(StrictRecord):
    id: str = Field(min_length=1)
    kind: str
    object_label: str
    basis: str
    sources: list[IssueSource]
    adopted_value: str
    question: str
    affects_level: bool

CONTRACT = 'system-assembler-v1'


def enabled(store):
    from .handoff_release import manifest
    value = manifest(store).get('assembly_contract')
    return value == CONTRACT


def prose_selection_key(cs, db, actor, plan_ref, section_id):
    task = cs._read(db, {'type': 'DelegatedTask', 'id': actor.task_id, 'version': 1})['payload']
    object_id = task.get('assessment_object_id')
    if object_id is not None:
        from .writer_assignments import bound_assignment
        bound_assignment(cs, db, actor)
    return 'prose:' + encode([plan_ref, section_id, object_id])


def validate_prose(cs, db, actor, node, previous_ref=None):
    from .commission_plan import assert_writing_allowed
    plan = assert_writing_allowed(cs, db, actor)
    sid = node.get('body', {}).get('section_id')
    cs._read(db, {'type': 'DelegatedTask', 'id': actor.task_id, 'version': 1})['payload']
    next((s for s in plan['payload']['sections'] if s['section_id'] == sid), None)
    report_state.prose_ref(db, prose_selection_key(cs, db, actor, plan['ref'], sid))
    return plan


def save_section_prose(cs, actor, operation_id, section_id, text, citations, previous_ref=None, *, _request_context=None):
    obj = {'client_key': 'prose', 'type': 'ContentNode', 'payload': {'kind': 'block',
           'body': {'text': text, 'section_id': section_id}, 'qualifiers': {}, 'claim_kind': 'fact', 'citations': citations}}
    if previous_ref:
        obj['previous_ref'] = previous_ref
    return cs.commit(actor, operation_id, [obj], _request_context=_request_context)


def propose_material_issue(cs, actor, operation_id, node_ref, issue):
    """Record engineering facts for an owned current node; assign position in system code."""
    from .commission_plan import assert_writing_allowed, _confirmed
    from .material_issues import MaterialIssue
    def save(db):
        plan = assert_writing_allowed(cs, db, actor)
        record = cs._read(db, node_ref)
        if node_ref['type'] != 'ContentNode' or record['owner_id'] != actor.id or record['task_id'] != actor.task_id:
            raise ActionForbidden('FORBIDDEN: material issue node owner')
        sid = record['payload']['body'].get('section_id')
        value = MaterialIssue.model_validate({**issue, 'anchor': {'paragraph_index': 0, 'start': 0, 'end': None}}).model_dump()
        _, decision = _confirmed(cs, db)
        next((i for i in decision['payload'].get('required_material_issues', []) if i['id'] == value['id']), None)
        key = digest([plan['ref'], value['id']])
        old = issue_state.get_g6_issue_record(db, key)
        if old and (not old.get('node_ref') or cs._read(db, old['node_ref'])['owner_id'] != actor.id):
            raise ActionForbidden('FORBIDDEN: material issue proposal owner')
        issue_state.set_g6_issue_record(db, key, {'node_ref': node_ref, 'issue': value}, actor=actor)
        issue_state.set_g6_issue_binding(db, key, {'section_id': sid}, actor=actor)
        return {'issue_id': value['id'], 'node_ref': node_ref, 'section_id': sid}
    return cs.operation(actor, operation_id, {'propose_material_issue': {'node_ref': node_ref, 'issue': issue}}, save)
