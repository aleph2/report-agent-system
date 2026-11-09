"""Small Writer judgments; scope, source references and output positions are host-owned."""
from . import issue_state
from . import legacy_state as legacy
import json
import re
from typing import Literal
from pydantic import Field, field_validator
from pydantic_core import PydanticCustomError
from .content_models import Ref
from .content_store import Actor
from .errors import ActionForbidden, ActionRejected
from .material_issues import MaterialIssue, StrictRecord
from .store import digest
from .writer_assignments import bound_assignment


class ProseInput(StrictRecord):
    text: str = Field(min_length=1)
    quotes: list[str] = Field(default_factory=list)
    visual_pages: list[str] = Field(default_factory=list)


class IssueInput(StrictRecord):
    kind: Literal['conflict', 'unclear', 'missing']
    basis: str = Field(min_length=1)
    quotes: list[str] = Field(default_factory=list)
    visual_pages: list[str] = Field(default_factory=list)
    adopted_value: str = Field(min_length=1)
    question: str = Field(min_length=1)
    affects_level: bool


class IndicatorConflict(StrictRecord):
    """The competing facts and the engineering decision that will reach Word and Excel."""
    basis: str = Field(min_length=1, description="State both conflicting source values.")
    adopted_value: str = Field(min_length=1, description="State the chosen value and why it takes precedence.")
    quotes: list[str] = Field(min_length=2, description="At least two distinct nonblank exact quotations for both sides of the conflict.")
    question: str = Field(min_length=1, description="What should the engineer clarify?")
    affects_level: bool = Field(description="Whether this conflict could change the risk level.")

    @field_validator('quotes')
    @classmethod
    def distinct_quotes(cls, quotes):
        if any(not q.strip() for q in quotes) or len({q.strip() for q in quotes})<2:
            raise PydanticCustomError('conflict_quotes_distinct',
                'Provide at least two distinct nonblank exact quotations, one for each side of the conflict.')
        return quotes


def _sources(cs, db, actor, bound, value):
    from .writer_assessment import resolve_judgment_sources
    return resolve_judgment_sources(cs, db, actor, bound, value.quotes, value.visual_pages)


def _readable_sources(cs, db, citations):
    result = []
    for citation in citations:
        payload = cs._read(db, citation['source_ref'])['payload']
        title = payload.get('source_metadata', {}).get('title', '')
        if not title.strip():
            raise ActionRejected('MATERIAL_ISSUE_READABLE_SOURCE_TITLE_REQUIRED')
        locator = citation['locator']
        if match := re.fullmatch(r'page ([1-9][0-9]*)(?:;.*)?', locator):
            locator = f'PDF第{match[1]}页'
        elif locator == 'manifest text':
            locator = '全文'
        elif match := re.fullmatch(r'line ([1-9][0-9]*)', locator):
            locator = f'第{match[1]}行'
        item = {'document': title, 'page': locator}
        if item not in result:
            result.append(item)
    return result


def _binding(bound, kind):
    route = {'section_id': bound['section_id']}
    if kind != 'missing':
        route['object_id'] = bound['object']['object_id']
    return route


def save_section_prose(cs, actor, operation_id, payload):
    """Replace only this assignment's prose; repeat native calls keep their original receipt."""
    from .commission_plan import _state
    from .section_writing import prose_selection_key, save_section_prose as save
    value = ProseInput.model_validate(payload)
    with cs.store.connect() as db:
        bound = bound_assignment(cs, db, actor)
        citations = _sources(cs, db, actor, bound, value)
        previous = _state(db, prose_selection_key(cs, db, actor, bound['plan']['ref'], bound['section_id']))
    receipt = cs.receipt(actor, operation_id)
    if receipt['state'] == 'known_success':
        ref = receipt['response'].get('result', {}).get('refs', {}).get('prose')
        if ref:
            previous = cs.read(ref).get('previous_ref')
    return save(cs, actor, operation_id, bound['section_id'], value.text, citations, previous,
                _request_context={'assignment_digest': bound['assignment_digest'], 'judgment': value.model_dump()})


def propose_material_issue(cs, actor, operation_id, payload):
    """Record a source issue without requiring prose or an agent-authored location."""
    value = IssueInput.model_validate(payload)
    # Recheck current authority before operation receipt replay as well as during the transaction.
    with cs.store.connect() as db:
        scope = bound_assignment(cs, db, actor)
    request = {'writer_issue': value.model_dump(), 'assignment_digest': scope['assignment_digest']}
    def save(db):
        bound = bound_assignment(cs, db, actor)
        if bound['assignment_digest'] != scope['assignment_digest']:
            raise ActionRejected('WRITER_ASSIGNMENT_CHANGED')
        return _write_issue(cs, db, actor, operation_id, bound, value)
    return cs.operation(actor, operation_id, request, save)


def save_indicator_conflict(cs, db, actor, operation_id, bound, payload):
    """Use the existing issue record and the calling indicator's atomic operation receipt."""
    conflict = IndicatorConflict.model_validate(payload)
    value = IssueInput(kind='conflict', **conflict.model_dump())
    return _write_issue(cs, db, actor, operation_id, bound, value)


def _write_issue(cs, db, actor, operation_id, bound, value):
    from .commission_plan import _confirmed, _state
    citations = _sources(cs, db, actor, bound, value)
    issue = {k: getattr(value, k) for k in ('kind', 'basis', 'adopted_value', 'question', 'affects_level')}
    issue.update(object_label=bound['object']['label'], sources=_readable_sources(cs, db, citations),
                 anchor={'paragraph_index': 0, 'start': 0, 'end': None})
    _, decision = _confirmed(cs, db)
    fields = ('kind', 'object_label', 'basis', 'sources', 'question')
    def identity(item):
        return {k: sorted(item[k], key=digest) if k=='sources' else item[k] for k in fields}
    signature = identity(issue)
    matches = [i for i in decision['payload'].get('required_material_issues', [])
               if identity(i) == signature]
    if len(matches) > 1:
        raise ActionRejected('REQUIRED_MATERIAL_ISSUE_IDENTITY_AMBIGUOUS')
    if not matches:
        # Reuse historical IDs even when their source order differed; never rewrite old keys.
        for _, raw in issue_state.iter_g6_issue_record(db):
            previous = json.loads(raw)
            if (previous.get('writer_task_ref') == bound['task_ref']
                    and previous.get('commission_plan_ref') == bound['plan']['ref']
                    and identity(previous['issue']) == signature):
                matches.append(previous['issue'])
        if len(matches)>1:
            raise ActionRejected('MATERIAL_ISSUE_IDENTITY_AMBIGUOUS')
    issue['id'] = matches[0]['id'] if matches else 'writer-issue:' + digest(
        [bound['task_ref'], bound['plan']['ref'], signature])
    if matches:
        # The confirmed source order is part of the export obligation, even when incoming quotes reverse it.
        issue['sources'] = matches[0]['sources']
        citations.sort(key=lambda c: issue['sources'].index(_readable_sources(cs, db, [c])[0]))
    issue = MaterialIssue.model_validate(issue).model_dump()
    proposal = {'issue': issue, 'writer_task_ref': bound['task_ref'],
        'commission_plan_ref': bound['plan']['ref'], 'binding': _binding(bound, value.kind),
        'source_citations': citations, 'receipt_id': operation_id}
    key = digest([bound['plan']['ref'], issue['id']])
    old = issue_state.get_g6_issue_record(db, key)
    if old and old.get('writer_task_ref') != bound['task_ref']:
        raise ActionForbidden('FORBIDDEN: material issue proposal owner')
    issue_state.set_g6_issue_record(db, key, proposal, actor=actor)
    issue_state.set_g6_issue_binding(db, key, proposal['binding'], actor=actor)
    return {'issue_id': issue['id'], 'binding': proposal['binding'], 'proposal_digest': digest(proposal)}



def verify_issue_proposal(cs, db, proposal, plan, coordinator):
    """Validate the durable proposal against immutable task, sources and operation receipt."""
    from .commission_plan import _validate_sources
    if set(proposal) != {'issue', 'writer_task_ref', 'commission_plan_ref', 'binding', 'source_citations', 'receipt_id'}:
        raise ActionRejected('WRITER_ISSUE_PROPOSAL_FIELDS_INVALID')
    task_ref = Ref.model_validate(proposal['writer_task_ref']).model_dump()
    if task_ref['type'] != 'DelegatedTask' or task_ref['version'] != 1:
        raise ActionRejected('WRITER_ISSUE_TASK_REQUIRED')
    task = cs._read(db, task_ref)
    if task['owner_id'] != coordinator.id or task['payload'].get('delegated_by') != coordinator.id:
        raise ActionForbidden('FORBIDDEN: material issue assignment owner')
    writer = Actor('content:writer:' + task_ref['id'], 'writer', task_ref['id'])
    bound = bound_assignment(cs, db, writer)
    if bound['plan']['ref'] != plan['ref'] or proposal['commission_plan_ref'] != plan['ref']:
        raise ActionRejected('WRITER_ISSUE_PLAN_CHANGED')
    issue = MaterialIssue.model_validate(proposal['issue']).model_dump()
    if issue['kind'] not in ('conflict', 'unclear', 'missing'):
        raise ActionRejected('WRITER_ISSUE_ASSUMPTIONS_REQUIRE_ASSESSMENT')
    if (issue['object_label'] != bound['object']['label'] or proposal['binding'] != _binding(bound, issue['kind'])
            or issue['anchor'] != {'paragraph_index': 0, 'start': 0, 'end': None}):
        raise ActionRejected('WRITER_ISSUE_SYSTEM_BINDING_MISMATCH')
    citations = proposal['source_citations']
    allowed = {Ref.model_validate(ref).key() for ref in bound['sources']}
    if any(Ref.model_validate(c['source_ref']).key() not in allowed for c in citations):
        raise ActionForbidden('FORBIDDEN: material issue source pool')
    _validate_sources(cs, db, writer, citations)
    if issue['sources'] != _readable_sources(cs, db, citations):
        raise ActionRejected('WRITER_ISSUE_SOURCE_BINDING_MISMATCH')
    row = db.execute('SELECT actor_id,response FROM content_operations WHERE operation_id=?',
                     (proposal['receipt_id'],)).fetchone()
    response = json.loads(row[1]) if row else {}
    if (not row or row[0] != writer.id or not response.get('ok')
            or response.get('receipt_id') != proposal['receipt_id']
            or response.get('result', {}).get('issue_id') != issue['id']
            or response.get('result', {}).get('proposal_digest') != digest(proposal)):
        raise ActionRejected('WRITER_ISSUE_RECEIPT_MISMATCH')
    return proposal


def tool_functions(cs, actor):
    def prose(operation_id: str, **judgment) -> dict:
        """Save assigned prose with exact source quotes or actually read visual page handles."""
        return save_section_prose(cs, actor(), operation_id, judgment)
    def issue(operation_id: str, **judgment) -> dict:
        """Propose a conflict, unclear source fact or missing information; system assigns its comment location."""
        return propose_material_issue(cs, actor(), operation_id, judgment)
    prose.__name__ = 'save_section_prose'; prose.message_model = ProseInput
    issue.__name__ = 'propose_material_issue'; issue.message_model = IssueInput
    return [prose, issue]
