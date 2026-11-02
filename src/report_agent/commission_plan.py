"""Versioned commission proposals; only operator replies authorize writing or reductions."""
from pathlib import Path
import json
import re
from typing import Literal

from pydantic import Field, model_validator

from .content_models import Contract, Ref, SourceCitation, InventoryObject, refs_in
from .content_store import Actor, ContentStore
from .errors import ActionForbidden, ActionRejected
from .store import digest, encode


class SectionPlan(Contract):
    section_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    kind: Literal['fixed', 'extracted', 'derived']
    outline: SourceCitation
    sources: list[SourceCitation]
    pending_sources: list[str] = Field(default_factory=list,
        description='Named required sources not yet located. Preserve the gap; supply or explicitly substitute them in a revised plan before approval.')
    text: str = ''
    substitutions: list[str] = Field(default_factory=list)
    derived_from: list[str] = Field(default_factory=list)
    rule: str = ''
    examples: list[SourceCitation] = Field(default_factory=list,
        description='Outline drawing examples identify what to inspect; they are not project facts.')

    @model_validator(mode='after')
    def basis(self):
        if not self.sources and not self.pending_sources:
            raise ValueError('SECTION_SOURCE_OR_PENDING_SOURCE_REQUIRED')
        if any(not name.strip() for name in self.pending_sources):
            raise ValueError('SECTION_PENDING_SOURCE_NAME_REQUIRED')
        if not self.outline.quote.strip():
            raise ValueError('SECTION_OUTLINE_QUOTE_REQUIRED')
        if self.kind == 'fixed' and not self.text.strip():
            raise ValueError('FIXED_SECTION_TEXT_REQUIRED')
        if self.kind == 'derived' and (not self.derived_from or not self.rule.strip()):
            raise ValueError('DERIVED_SECTION_RULE_REQUIRED')
        return self


class Convention(Contract):
    source: SourceCitation
    interpretation: str = Field(description='Agent interpretation, separate from the original customer quotation.')


class Reconciliation(Contract):
    sources: list[SourceCitation] = Field(min_length=2)
    result: str = Field(min_length=1)
    differences: list[str]


class CommissionPlan(Contract):
    sections: list[SectionPlan] = Field(min_length=1)
    inventory_attributes: list[str] = Field(min_length=1,
        description='Required object attributes from this commission; record every one, using explicit unknowns rather than omissions.')
    objects: list[InventoryObject] = Field(min_length=1)
    conventions: list[Convention]
    deliverables: list[str] = Field(min_length=1)
    reconciliations: list[Reconciliation] = Field(min_length=1)
    open_questions: list[str] = Field(description='Only questions the supplied materials cannot settle.')

    @model_validator(mode='after')
    def complete_inventory(self):
        names = self.inventory_attributes
        if any(not n.strip() for n in names) or len(set(names)) != len(names):
            raise ValueError('COMMISSION_INVENTORY_ATTRIBUTE_CONTRACT_INVALID')
        for obj in self.objects:
            actual = [a.name for a in obj.attributes]
            if len(actual) != len(set(actual)) or set(actual) != set(names):
                raise ValueError('COMMISSION_INVENTORY_ATTRIBUTES_INCOMPLETE: ' + obj.object_id)
        return self


class Reduction(Contract):
    object_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class OwnerDecision(Contract):
    plan_ref: Ref
    approved: bool = Field(strict=True)
    corrections: str
    reductions: list[Reduction]

    @model_validator(mode='after')
    def unambiguous(self):
        if (self.approved and self.corrections.strip()) or (not self.approved and not self.corrections.strip()):
            raise ValueError('COMMISSION_APPROVAL_OR_CORRECTIONS_REQUIRED')
        if not self.approved and self.reductions:
            raise ValueError('COMMISSION_REDUCTION_REQUIRES_APPROVAL')
        if any(not r.reason.strip() for r in self.reductions):
            raise ValueError('COMMISSION_REDUCTION_REASON_REQUIRED')
        return self


def enabled(store):
    from .handoff_release import manifest
    return manifest(store).get('commission_checkpoint_required') is True


def _state(db, key, default=None):
    row = db.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()
    return json.loads(row[0]) if row else default


def _set(db, key, value):
    db.execute('INSERT OR REPLACE INTO state VALUES (?,?)', (key, encode(value)))


def read_plan(store):
    ref = store.get('commission_plan')
    return ContentStore(store).read(ref) if ref else None


def _citations(value):
    if isinstance(value, dict):
        if 'source_ref' in value and 'locator' in value:
            yield value
        else:
            for child in value.values():
                yield from _citations(child)
    elif isinstance(value, list):
        for child in value:
            yield from _citations(child)


def _validate_sources(cs, db, actor, plan):
    from .deliverables import source_authority
    records = {}
    for citation in _citations(plan):
        ref = citation['source_ref']
        key = Ref.model_validate(ref).key()
        source = records.setdefault(key, cs._read(db, ref))
        if ref['type'] != 'SourceArtifact':
            raise ActionRejected('COMMISSION_SOURCE_ARTIFACT_REQUIRED')
        payload = source['payload']
        rows = list(db.execute('SELECT locator,text FROM source_blocks WHERE source_id=?',
                               (payload['source_id'],)))
        located = [text for loc, text in rows if loc == citation['locator'] or loc.startswith(citation['locator'] + ';')]
        quote = citation.get('quote', '')
        if quote and quote not in ''.join(located):
            raise ActionRejected('COMMISSION_QUOTE_NOT_AT_SOURCE_LOCATION')
        if not located:
            # Image-only PDF pages have no extracted text; verify physical page existence.
            page = re.fullmatch(r'page ([1-9][0-9]*)', citation['locator'])
            if page is None or quote:
                raise ActionRejected('COMMISSION_SOURCE_LOCATION_UNAVAILABLE')
            from .document_tools import _original
            from .workspace import Workspace
            from pypdf import PdfReader
            from io import BytesIO
            _, data = _original(Workspace(cs.store), payload['source_id'])
            if int(page[1]) > len(PdfReader(BytesIO(data)).pages):
                raise ActionRejected('COMMISSION_SOURCE_PAGE_OUTSIDE_DOCUMENT')
    source_authority(cs, db, actor, list(records.values()))


def save_plan(cs, actor, operation_id, plan):
    if actor.role != 'coordinator':
        raise ActionForbidden('FORBIDDEN: commission proposal owner')
    if not enabled(cs.store):
        raise ActionRejected('COMMISSION_CHECKPOINT_NOT_ENABLED')
    plan = CommissionPlan.model_validate(plan).model_dump()
    ids = [o['object_id'] for o in plan['objects']]
    sections = [s['section_id'] for s in plan['sections']]
    if len(set(ids)) != len(ids) or len(set(sections)) != len(sections):
        raise ActionRejected('COMMISSION_DUPLICATE_OBJECT_OR_SECTION')
    if any(not set(s['derived_from']) <= set(sections) or s['section_id'] in s['derived_from'] for s in plan['sections']):
        raise ActionRejected('COMMISSION_DERIVED_SECTION_INVALID')
    dependencies = {s['section_id']: s['derived_from'] for s in plan['sections']}
    visited, active = set(), set()
    def visit(section):
        if section in active:
            raise ActionRejected('COMMISSION_DERIVED_SECTION_CYCLE')
        if section not in visited:
            active.add(section)
            for dependency in dependencies[section]:
                visit(dependency)
            active.remove(section)
            visited.add(section)
    for section in sections:
        visit(section)
    if any(not c['source']['quote'].strip() for c in plan['conventions']):
        raise ActionRejected('COMMISSION_CONVENTION_QUOTE_REQUIRED')
    def save(db):
        _validate_sources(cs, db, actor, plan)
        roles = _state(db, 'commission_source_roles', {})
        if roles:
            customer_sources = {r['id'] for r in roles.values() if r['purpose'] == 'commission'}
            if any(cs._read(db, c['source']['source_ref'])['payload']['source_id'] not in customer_sources
                   for c in plan['conventions']):
                raise ActionRejected('COMMISSION_CONVENTION_REQUIRES_CUSTOMER_SOURCE')
        old_ref = _state(db, 'commission_plan')
        old = cs._read(db, old_ref) if old_ref else None
        prior = {cs._read(db, r)['payload']['inventory_object']['object_id']: cs._read(db, r)
                 for r in old['payload']['inventory_refs']} if old else {}
        if not prior.keys() <= set(ids):
            raise ActionRejected('COMMISSION_OBJECT_REMOVAL_REQUIRES_RETAINED_RECORD')
        inventory = []
        for obj in plan['objects']:
            previous = prior.get(obj['object_id'])
            payload = {'text': obj['label'] + ': ' + obj['reason'], 'origin': obj['origin'],
                       'scope': 'assessment object', 'inventory_object': obj}
            if previous and previous['payload'] == payload:
                inventory.append(previous['ref'])
            else:
                inventory.append(cs._insert(db, actor, 'Requirement', payload,
                    **({'id': previous['ref']['id'], 'version': previous['ref']['version'] + 1,
                        'previous_ref': previous['ref']} if previous else {})))
        ref = cs._insert(db, actor, 'CommissionPlan', {**plan, 'inventory_refs': inventory},
            **({'id': old_ref['id'], 'version': old_ref['version'] + 1, 'previous_ref': old_ref} if old_ref else {}))
        _set(db, 'commission_plan', ref)
        return {'plan_ref': ref, 'inventory_refs': inventory}
    return cs.operation(actor, operation_id, {'commission_plan': plan}, save)


def _confirmed(cs, db):
    ref = _state(db, 'commission_plan')
    confirmation = _state(db, 'commission_confirmation')
    if not ref or not confirmation:
        raise ActionRejected('COMMISSION_CHECKPOINT_CONFIRMATION_REQUIRED')
    decision = cs._read(db, confirmation)
    if (decision['owner_id'] != 'operator' or decision['payload'].get('plan_ref') != ref
            or decision['payload'].get('approved') is not True):
        raise ActionRejected('COMMISSION_CHECKPOINT_CONFIRMATION_STALE')
    return cs._read(db, ref), decision


def assert_writing_allowed(cs, db, actor):
    if not enabled(cs.store):
        return None
    plan, _ = _confirmed(cs, db)
    if actor.role != 'writer':
        raise ActionForbidden('FORBIDDEN: commissioned writing belongs to assigned writer')
    task = cs._read(db, {'type': 'DelegatedTask', 'id': actor.task_id, 'version': 1})
    payload = task['payload']
    if (actor.id != 'content:writer:' + actor.task_id or payload.get('role') != 'writer'
            or payload.get('commission_plan_ref') != plan['ref'] or not payload.get('section_ids')):
        raise ActionRejected('COMMISSION_WRITER_TASK_STALE_OR_UNASSIGNED')
    if not set(payload['section_ids']) <= {s['section_id'] for s in plan['payload']['sections']}:
        raise ActionRejected('COMMISSION_SECTION_NOT_IN_PLAN')
    return plan


def writer_assignment(cs, db, section_ids):
    plan, _ = _confirmed(cs, db)
    if not section_ids or len(set(section_ids)) != len(section_ids):
        raise ActionRejected('COMMISSION_SECTION_ASSIGNMENT_REQUIRED')
    selected = [s for s in plan['payload']['sections'] if s['section_id'] in section_ids]
    if len(selected) != len(section_ids):
        raise ActionRejected('COMMISSION_SECTION_NOT_IN_PLAN')
    return {'commission_plan_ref': plan['ref'], 'section_ids': section_ids,
            'section_plan': selected, 'customer_conventions': plan['payload']['conventions']}


def request_checkpoint(workspace):
    cs = ContentStore(workspace.store)
    record = read_plan(workspace.store)
    if not record:
        raise ActionRejected('COMMISSION_PLAN_REQUIRED')
    plan, ref = record['payload'], record['ref']
    path = workspace.store.root / 'outputs' / ('commission-checkpoint-' + digest(ref) + '.md')
    lines = ['# Commission checkpoint', '', 'Approve this exact plan or provide corrections.',
             'Proposed exclusions still require explicit owner reductions.', '', '## Objects', '']
    for obj in plan['objects']:
        lines.append(f"- {obj['object_id']} — {obj['label']}: {'included' if obj['included'] else 'proposed exclusion'}; {obj['reason']} ({obj['origin']})")
        for attribute in obj['attributes']:
            values = '; '.join((v['value'] or 'unknown') + ': ' + v['reason'] for v in attribute['values'])
            lines.append('  ' + attribute['name'] + ': ' + values)
    lines += ['', '## Section plan', '']
    for section in plan['sections']:
        locations = ', '.join(cs.read(c['source_ref'])['payload']['source_metadata'].get('title', c['source_ref']['id']) + ' / ' + c['locator'] for c in section['sources'])
        if section['pending_sources']:
            locations += '; PENDING: ' + '; '.join(section['pending_sources'])
        lines.append(f"- {section['section_id']} {section['title']} — {section['kind']}: {locations}")
    lines += ['', '## Deliverables', '', *['- ' + item for item in plan['deliverables']], '', '## Conventions', '']
    for convention in plan['conventions']:
        lines += ['- Customer quotation: ' + convention['source']['quote'], '  Agent interpretation: ' + convention['interpretation']]
    lines += ['', '## Source reconciliation', '']
    for item in plan['reconciliations']:
        lines += ['- ' + item['result'], *['  - ' + text for text in item['differences']]]
    lines += ['', '## Open questions', '', *['- ' + item for item in plan['open_questions']]]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    description = 'Confirm commission plan ' + digest(ref) + '. Brief: ' + str(path.relative_to(workspace.store.root))
    source_ids = list(dict.fromkeys(cs.read(c['source_ref'])['payload']['source_id'] for c in _citations(plan)))
    issue = workspace.issue('requirement', description, source_ids)
    workspace.store.set('commission_checkpoint:' + issue['id'], {'plan_ref': ref, 'brief_path': str(path.relative_to(workspace.store.root))})
    path.with_suffix('.json').write_text(json.dumps({'issue_id': issue['id'], 'plan_ref': ref,
        'reply_command': 'report-agent commission-reply --project CASE --issue-id ISSUE_ID --file DECISION.json',
        'decision_shape': {'plan_ref': ref, 'approved': True, 'corrections': '', 'reductions': []},
        'note': 'Approve only after reviewing the brief. Explicit reductions require object_id and reason. Corrections use approved=false.'}, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'issue_id': issue['id'], 'plan_ref': ref, 'brief_path': str(path.relative_to(workspace.store.root)),
            'description': description, 'source_ids': source_ids}


def reply(workspace, issue_id, decision):
    """Trusted operator entry point, deliberately absent from agent tools."""
    decision = OwnerDecision.model_validate(decision).model_dump()
    cs = ContentStore(workspace.store)
    with workspace.store.run_lock(), workspace.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        checkpoint = _state(db, 'commission_checkpoint:' + issue_id)
        if (not checkpoint or checkpoint['plan_ref'] != decision['plan_ref']
                or _state(db, 'commission_plan') != decision['plan_ref']):
            raise ActionRejected('COMMISSION_CHECKPOINT_REPLY_STALE')
        issues = _state(db, 'report_issues', [])
        issue = next((i for i in issues if i['id'] == issue_id), None)
        if issue is None:
            raise ActionRejected('COMMISSION_CHECKPOINT_ISSUE_MISSING')
        answer = encode(decision)
        if issue.get('decision_origin') == 'operator':
            if issue.get('decision') != answer:
                raise ActionRejected('COMMISSION_CHECKPOINT_ALREADY_ANSWERED')
            return issue
        plan = cs._read(db, decision['plan_ref'])['payload']
        pending = list(dict.fromkeys(name for s in plan['sections'] for name in s['pending_sources']))
        if decision['approved'] and pending:
            raise ActionRejected('COMMISSION_PENDING_SOURCES: ' + '; '.join(pending))
        reduced = [r['object_id'] for r in decision['reductions']]
        if len(set(reduced)) != len(reduced) or not set(reduced) <= {o['object_id'] for o in plan['objects']}:
            raise ActionRejected('COMMISSION_REDUCTION_OBJECT_INVALID')
        owner = Actor('operator', 'operator', 'commission-checkpoint:' + issue_id)
        ref = cs._insert(db, owner, 'CommissionDecision', decision)
        issue.update(decision=answer, decision_origin='operator', resolved=True)
        _set(db, 'commission_confirmation', ref)
        _set(db, 'report_issues', issues)
        _set(db, 'context_revision', _state(db, 'context_revision', 0) + 1)
        _set(db, 'report_status', 'ready')
        db.execute('INSERT INTO events(kind,data) VALUES (?,?)', ('commission_owner_decision', encode({'issue_id': issue_id, 'decision_ref': ref})))
        return issue


def snapshot_inventory(cs, db, refs):
    if not enabled(cs.store):
        return refs, None
    plan, _ = _confirmed(cs, db)
    found = {Ref.model_validate(r).key(): r for r in refs}
    if len(found) != len(refs):
        raise ActionRejected('INVALID_MANIFEST')
    pending = list(plan['payload']['inventory_refs'])
    while pending:
        ref = pending.pop()
        key = Ref.model_validate(ref).key()
        if key not in found:
            found[key] = ref
            pending.extend(r.model_dump() for r in refs_in(cs._read(db, ref)['payload']))
    return list(found.values()), plan['ref']


def snapshot_outcomes(cs, db, plan_ref, refs):
    """Freeze matching producer outcomes, so later drafts cannot alter selected evidence."""
    members = {Ref.model_validate(r).key() for r in refs}
    result = []
    for obj in cs._read(db, plan_ref)['payload']['objects']:
        prefix = 'commission_outcome:' + digest([plan_ref, obj['object_id']]) + ':'
        matches = []
        for (value,) in db.execute('SELECT value FROM state WHERE key LIKE ? ORDER BY key', (prefix + '%',)):
            ref = json.loads(value)
            outcome = cs._read(db, ref)['payload']
            dependencies = [outcome['object_ref'], outcome['section_ref'], outcome['score_ref'],
                            outcome['level_ref'], *outcome['basis_refs']]
            if all(Ref.model_validate(r).key() in members for r in dependencies):
                matches.append(ref)
        if len(matches) > 1:
            raise ActionRejected('COMMISSION_OUTCOME_SELECTION_AMBIGUOUS')
        result.extend(matches)
    return result


def record_outcome(cs, actor, operation_id, object_id, section_ref, score_ref, level_ref, basis_refs, unresolved):
    request = {'object_id': object_id, 'section_ref': section_ref, 'score_ref': score_ref,
               'level_ref': level_ref, 'basis_refs': basis_refs, 'unresolved': unresolved}
    def save(db):
        plan = assert_writing_allowed(cs, db, actor)
        if plan is None or not basis_refs:
            raise ActionRejected('COMMISSION_OUTCOME_BASIS_REQUIRED')
        object_ref = next((ref for ref in plan['payload']['inventory_refs']
            if cs._read(db, ref)['payload']['inventory_object']['object_id'] == object_id), None)
        if object_ref is None:
            raise ActionRejected('COMMISSION_OUTCOME_OBJECT_NOT_IN_PLAN')
        for ref in (section_ref, score_ref, level_ref):
            record = cs._read(db, ref)
            if ref['type'] != 'ContentNode' or record['owner_id'] != actor.id:
                raise ActionForbidden('FORBIDDEN: commission outcome writer ownership')
        for ref in basis_refs:
            if ref['type'] != 'Evidence':
                raise ActionRejected('COMMISSION_OUTCOME_EVIDENCE_REQUIRED')
            cs._read(db, ref)
        ref = cs._insert(db, actor, 'CommissionOutcome', {**request,
            'commission_plan_ref': plan['ref'], 'object_ref': object_ref})
        _set(db, 'commission_outcome:' + digest([plan['ref'], object_id]) + ':' + digest(actor.id), ref)
        return {'outcome_ref': ref}
    return cs.operation(actor, operation_id, {'commission_outcome': request}, save)
