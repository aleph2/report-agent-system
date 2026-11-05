"""Assigned prose and issue proposals; document structure remains system-owned."""
from typing import Literal
from pydantic import Field
from .material_issues import StrictRecord, IssueSource
from .content_models import Ref
from .errors import ActionForbidden, ActionRejected
from .store import digest


class IssueProposal(StrictRecord):
    id: str = Field(min_length=1)
    kind: Literal['conflict', 'unclear', 'missing', 'indirect_assumption', 'no_evidence_assumption']
    object_label: str = Field(min_length=1)
    basis: str = Field(min_length=1)
    sources: list[IssueSource]
    adopted_value: str = Field(min_length=1)
    question: str = Field(min_length=1)
    affects_level: bool

CONTRACT = 'system-assembler-v1'


def enabled(store):
    from .handoff_release import manifest
    value = manifest(store).get('assembly_contract')
    if value not in (None, CONTRACT):
        raise ActionRejected('UNKNOWN_ASSEMBLY_CONTRACT')
    return value == CONTRACT


def prose_selection_key(cs, db, actor, plan_ref, section_id):
    task = cs._read(db, {'type': 'DelegatedTask', 'id': actor.task_id, 'version': 1})['payload']
    object_id = task.get('assessment_object_id')
    if object_id is not None:
        from .writer_assignments import bound_assignment
        bound = bound_assignment(cs, db, actor)
        if bound['plan']['ref'] != plan_ref or bound['section_id'] != section_id:
            raise ActionRejected('PROSE_ASSIGNMENT_BINDING_MISMATCH')
        return 'g6_object_prose:' + digest([plan_ref, section_id, object_id])
    return 'g6_section_prose:' + digest([plan_ref, section_id])


def validate_prose(cs, db, actor, node, previous_ref=None):
    from .commission_plan import assert_writing_allowed, _state
    from .g3_export import _INTERNAL
    plan = assert_writing_allowed(cs, db, actor)
    sid = node.get('body', {}).get('section_id')
    task = cs._read(db, {'type': 'DelegatedTask', 'id': actor.task_id, 'version': 1})['payload']
    section = next((s for s in plan['payload']['sections'] if s['section_id'] == sid), None)
    if section is None or section['kind'] != 'extracted' or sid not in task['section_ids']:
        raise ActionRejected('PROSE_ASSIGNED_EXTRACTED_SECTION_REQUIRED')
    if node['kind'] != 'block' or set(node['body']) != {'text', 'section_id'} or node.get('qualifiers'):
        raise ActionRejected('PROSE_ONLY_SYSTEM_OWNS_STRUCTURE_AND_ANCHORS')
    current = _state(db, prose_selection_key(cs, db, actor, plan['ref'], sid))
    if current and current != previous_ref:
        raise ActionRejected('PROSE_CURRENT_VERSION_REQUIRED', diagnostic={'section_id': sid, 'current_ref': current})
    if previous_ref and cs._read(db, previous_ref)['payload']['body'].get('section_id') != sid:
        raise ActionRejected('PROSE_REVISION_SECTION_MISMATCH')
    text = node['body']['text']
    spans = [{'reason': 'internal_content', 'field': 'text', 'start': m.start(), 'end': m.end()}
             for m in _INTERNAL.finditer(text)]
    from .exporting import markdown_table_spans
    lines = text.splitlines(keepends=True)
    for _, start_line, end_line in markdown_table_spans(text):
        spans.append({'reason': 'system_table_required', 'field': 'text',
                      'start': sum(map(len, lines[:start_line])), 'end': sum(map(len, lines[:end_line]))})
    actual = {Ref.model_validate(x['source_ref']).key() for x in node.get('citations', [])}
    expected = {Ref.model_validate(x['source_ref']).key() for x in section['sources']}
    if not actual.intersection(expected):
        spans.append({'reason': 'planned_citation_missing', 'field': 'text', 'start': 0, 'end': len(text)})
    roles = _state(db, 'commission_source_roles', {})
    template_ids = {r['id'] for r in roles.values() if r['purpose'] == 'template'}
    for citation in node.get('citations', []):
        source = cs._read(db, citation['source_ref'])['payload']
        if source['source_id'] in template_ids:
            spans.append({'reason': 'template_is_not_project_fact_evidence', 'field': 'text', 'start': 0, 'end': len(text)})
    if spans:
        raise ActionRejected('SECTION_PROSE_CHECK_FAILED', diagnostic={'section_id': sid, 'node_ref': previous_ref, 'spans': spans})
    return plan


def save_section_prose(cs, actor, operation_id, section_id, text, citations, previous_ref=None, *, _request_context=None):
    if not enabled(cs.store):
        raise ActionRejected('SYSTEM_ASSEMBLER_CONTRACT_REQUIRED')
    obj = {'client_key': 'prose', 'type': 'ContentNode', 'payload': {'kind': 'block',
           'body': {'text': text, 'section_id': section_id}, 'qualifiers': {}, 'claim_kind': 'fact', 'citations': citations}}
    if previous_ref:
        obj['previous_ref'] = previous_ref
    return cs.commit(actor, operation_id, [obj], _request_context=_request_context)


def propose_material_issue(cs, actor, operation_id, node_ref, issue):
    """Record engineering facts for an owned current node; assign position in system code."""
    from .commission_plan import assert_writing_allowed, _confirmed, _state, _set
    from .material_issues import MaterialIssue
    if not enabled(cs.store):
        raise ActionRejected('SYSTEM_ASSEMBLER_CONTRACT_REQUIRED')
    if 'anchor' in issue:
        raise ActionRejected('ISSUE_ANCHOR_IS_SYSTEM_OWNED')
    def save(db):
        plan = assert_writing_allowed(cs, db, actor)
        record = cs._read(db, node_ref)
        if node_ref['type'] != 'ContentNode' or record['owner_id'] != actor.id or record['task_id'] != actor.task_id:
            raise ActionForbidden('FORBIDDEN: material issue node owner')
        sid = record['payload']['body'].get('section_id')
        if _state(db, prose_selection_key(cs, db, actor, plan['ref'], sid)) != node_ref:
            raise ActionRejected('ISSUE_CURRENT_PROSE_NODE_REQUIRED')
        value = MaterialIssue.model_validate({**issue, 'anchor': {'paragraph_index': 0, 'start': 0, 'end': None}}).model_dump()
        _, decision = _confirmed(cs, db)
        expected = next((i for i in decision['payload'].get('required_material_issues', []) if i['id'] == value['id']), None)
        if expected and any(value.get(k) != expected[k] for k in ('id', 'kind', 'object_label', 'basis', 'sources', 'question')):
            raise ActionRejected('REQUIRED_MATERIAL_ISSUE_MISMATCH: ' + value['id'])
        key = digest([plan['ref'], value['id']])
        old = _state(db, 'g6_issue_record:' + key)
        if old and (not old.get('node_ref') or cs._read(db, old['node_ref'])['owner_id'] != actor.id):
            raise ActionForbidden('FORBIDDEN: material issue proposal owner')
        _set(db, 'g6_issue_record:' + key, {'node_ref': node_ref, 'issue': value})
        _set(db, 'g6_issue_binding:' + key, {'section_id': sid})
        return {'issue_id': value['id'], 'node_ref': node_ref, 'section_id': sid}
    return cs.operation(actor, operation_id, {'propose_material_issue': {'node_ref': node_ref, 'issue': issue}}, save)
