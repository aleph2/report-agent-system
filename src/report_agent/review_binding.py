"""Bind the coordinator's three business choices using existing saved objects."""
import json
from copy import deepcopy
from typing import Annotated, Literal

from pydantic import Field, ValidationError

from .content_models import Contract, Ref
from .deliverables import DeliverableHandle, SavedSnapshot, resolve_snapshot, key
from .errors import ActionForbidden, ActionRejected
from .store import digest
from .task_supervision import ReviewRequirement, ArtifactCheckScope, ReferencePageBinding, validate_requirements


class Criteria(Contract):
    kind: Literal['criteria']
    criterion_refs: list[Ref] = Field(min_length=1)


class AssignmentBasis(Contract):
    kind: Literal['assignment_basis']
    assignment_ref: Ref


class WholeContent(Contract):
    kind: Literal['whole_content']


class MappedArtifactExtent(ArtifactCheckScope):
    requirement_index: Literal[0] = 0


class MappedItem(Contract):
    criterion_ref: Ref = Field(description='One exact standard from the complete selected basis.')
    target_ref: Ref = Field(description='Assigned Snapshot/member; artifacts go in artifact_refs, not here.')
    assessment_kind: Literal['content', 'export', 'render'] = Field(default='content',
        description='Choose the actual question: report content, saved export fidelity, or rendered-page presentation.')
    artifact_refs: list[Ref] = Field(default_factory=list,
        description='Export/render questions require actual saved artifacts of the selected Snapshot.')
    extent: Literal['local_body', 'subtree_bodies'] | MappedArtifactExtent | None = Field(default=None,
        description='Optional content body extent, or artifact extent {kind:export_structure,artifact_ref,pages:[]} / {kind:render_pages,artifact_ref,pages:[actual physical pages]}. The program assigns local check0; no inventory transcription.')
    presentation_reference_ref: Ref | None = Field(default=None,
        description='Exact authorized customer Word presentation reference when assigning such comparison.')
    reference_page_bindings: list[ReferencePageBinding] = Field(default_factory=list)


class Mapped(Contract):
    kind: Literal['mapped']
    items: list[MappedItem] = Field(min_length=1)


class SavedAssignment(Contract):
    kind: Literal['saved_assignment']
    assignment_ref: Ref
    scope_ids: list[str] | None = Field(default=None, min_length=1)


class ReviewSelection(Contract):
    deliverable: Annotated[DeliverableHandle | SavedSnapshot, Field(discriminator='kind')]
    standards: Annotated[Criteria | AssignmentBasis, Field(discriminator='kind')]
    scope: Annotated[WholeContent | Mapped | SavedAssignment, Field(discriminator='kind')]


class ReuseMapping(Contract):
    old_item_index: int = Field(ge=0, strict=True)
    new_scope_id: str = Field(min_length=1)


def canonical_selection(value):
    """Normalize only unordered choices, leaving check and extent text untouched."""
    value = deepcopy(value.model_dump() if hasattr(value, 'model_dump') else value)
    try:
        value = ReviewSelection.model_validate(value).model_dump()
    except ValidationError:
        pass  # Invalid input is rejected and receipted inside the original transaction.
    if isinstance(value, dict):
        standards, scope = value.get('standards'), value.get('scope')
        if isinstance(standards, dict) and standards.get('kind') == 'criteria' and isinstance(standards.get('criterion_refs'), list):
            from .store import encode
            standards['criterion_refs'] = sorted(standards['criterion_refs'], key=encode)
        if isinstance(scope, dict):
            from .store import encode
            if scope.get('kind') == 'mapped' and isinstance(scope.get('items'), list):
                scope['items'] = sorted(scope['items'], key=encode)
            if scope.get('kind') == 'saved_assignment' and isinstance(scope.get('scope_ids'), list):
                scope['scope_ids'] = sorted(scope['scope_ids'], key=encode)
    return value


def saved_task(cs, db, actor, ref, snapshot):
    record = cs._read(db, ref)
    if (record['ref']['type'] != 'DelegatedTask' or record['owner_id'] != actor.id
            or record['payload'].get('role') != 'reviewer'
            or record['payload'].get('delegated_by') != actor.id):
        raise ActionForbidden('FORBIDDEN: review assignment owner')
    if snapshot is not None and record['payload'].get('review_snapshot_ref') != snapshot:
        raise ActionRejected('REVIEW_ASSIGNMENT_SNAPSHOT_MISMATCH')
    return record


def instruction_versions(packet):
    """Task applicability is provenance; effective version identity is stable."""
    return None if packet is None else {k:v for k,v in packet.items() if k not in {'task_id','digest'}}


def validate_basis(cs, db, task):
    basis = task.get('review_commission_basis')
    if (task.get('review_interface_profile') != 'review-interfaces-v4' or not isinstance(basis, dict)
            or basis.get('contract') != 'review-commission-basis-v1'
            or not basis.get('criterion_refs') or not isinstance(basis.get('original_requirement_refs'), list)
            or not isinstance(basis.get('commission_origin'), dict)
            or basis.get('digest') != digest({k:v for k,v in basis.items() if k != 'digest'})):
        raise ActionRejected('COMPLETE_REVIEW_BASIS_REQUIRED')
    for refs, records, kind in [('criterion_refs','criteria','Criterion'),
                                ('original_requirement_refs','original_requirements','Requirement')]:
        values = basis.get(records)
        if (not isinstance(values, list) or len(values) != len(basis[refs])
                or len({key(r) for r in basis[refs]}) != len(basis[refs])):
            raise ActionRejected('COMPLETE_REVIEW_BASIS_REQUIRED')
        for ref, record in zip(basis[refs], values):
            if ref['type'] != kind or cs._read(db, ref) != record:
                raise ActionRejected('REVIEW_BASIS_VERSION_MISMATCH')
    return basis


def bind(cs, db, actor, selection, intent, task_id):
    value = ReviewSelection.model_validate(selection).model_dump()
    snapshot = resolve_snapshot(cs, db, actor, value['deliverable'])
    snap = cs._read(db, snapshot)['payload']
    from .prompt_instructions import instruction_context
    current_instructions = instruction_versions(instruction_context(cs.store, 'reviewer', task_id=task_id, db=db))
    standards = value['standards']
    if standards['kind'] == 'assignment_basis':
        prior = saved_task(cs, db, actor, standards['assignment_ref'], None)['payload']
        basis = deepcopy(validate_basis(cs, db, prior))
        if basis.get('scoped_instructions') != current_instructions:
            raise ActionRejected('REVIEW_INSTRUCTION_BASIS_CHANGED')
    else:
        refs = sorted(standards['criterion_refs'], key=key)
        if len({key(r) for r in refs}) != len(refs):
            raise ActionRejected('DUPLICATE_REVIEW_CRITERION')
        criteria = [cs._read(db, r) for r in refs]
        if any(c['ref']['type'] != 'Criterion' for c in criteria):
            raise ActionRejected('REVIEW_STANDARD_REQUIRES_CRITERION')
        originals = [json.loads(row[0]) for row in db.execute(
            "SELECT v.data FROM content_versions v JOIN content_heads h ON "
            "v.type=h.type AND v.id=h.id AND v.version=h.version WHERE v.type='Requirement' ORDER BY v.rowid")]
        from .handoff_release import manifest
        commission = manifest(cs.store)
        basis = {'contract': 'review-commission-basis-v1', 'criterion_refs': refs,
            'criteria': criteria, 'original_requirement_refs': [r['ref'] for r in originals],
            'original_requirements': originals,
            'commission_origin': {k: commission.get(k) for k in ('goal', 'scope_instruction')},
            'scoped_instructions': current_instructions}
        basis['digest'] = digest(basis)
    available = {key(r) for r in basis['criterion_refs']}
    scope = value['scope']
    provenance = None
    if scope['kind'] == 'saved_assignment':
        prior = saved_task(cs, db, actor, scope['assignment_ref'], snapshot)
        prior_basis = prior['payload'].get('review_commission_basis')
        if prior_basis is None and standards['kind'] != 'criteria':
            raise ActionRejected('LEGACY_SCOPE_REQUIRES_EXPLICIT_CRITERIA_BASIS')
        if prior_basis and prior_basis['digest'] != basis['digest']:
            raise ActionRejected('REVIEW_ASSIGNMENT_BASIS_MISMATCH')
        requested = scope['scope_ids']
        old = prior['payload'].get('review_requirements', [])
        if requested is not None and (len(set(requested)) != len(requested)
                or set(requested) - {r['scope_id'] for r in old}):
            raise ActionRejected('UNKNOWN_SAVED_REVIEW_SCOPE')
        requirements = [deepcopy(r) for r in old if requested is None or r['scope_id'] in requested]
        provenance = {'assignment_ref': prior['ref'], 'scope_ids': [r['scope_id'] for r in requirements]}
    else:
        items = (scope['items'] if scope['kind'] == 'mapped' else [
            {'criterion_ref': r, 'target_ref': snap['root_ref'], 'assessment_kind': 'content'}
            for r in basis['criterion_refs']])
        requirements = []
        for item in items:
            criterion = cs._read(db, item['criterion_ref'])
            requirement = {'target_ref': item['target_ref'], 'criterion_ref': item['criterion_ref'],
                'assessment_kind': item['assessment_kind'], 'scope_id': 'pending',
                'required_checks': [criterion['payload']['expected_outcome']], 'require_check_evidence': True,
                **{k:item[k] for k in ('artifact_refs', 'presentation_reference_ref', 'reference_page_bindings') if item.get(k)}}
            if isinstance(item.get('extent'), dict):
                requirement['artifact_check_scopes'] = [item['extent']]
            elif item.get('extent'):
                requirement['content_check_scopes'] = [{'requirement_index': 0,
                    'node_ref': item['target_ref'], 'kind': item['extent']}]
                requirement['material_refs'] = [r for r in snap['refs'] if r['type'] in {'ContentNode','Evidence','SourceArtifact'}]
            requirements.append(requirement)
    members = {key(r) for r in [snapshot, *snap['refs']]}
    for item in requirements:
        if key(item['criterion_ref']) not in available:
            raise ActionRejected('REVIEW_CRITERION_OUTSIDE_BASIS')
        if key(item['target_ref']) not in members:
            raise ActionRejected('REVIEW_TARGET_OUTSIDE_SNAPSHOT')
        item['scope_id'] = 'v4:' + digest({'intent': intent, 'mapping': {k:v for k,v in item.items() if k != 'scope_id'}})
    requirements = [ReviewRequirement.model_validate(r).model_dump() for r in requirements]
    class TransactionRead:
        store = cs.store
        def read(self, ref):
            return cs._read(db, ref)
    validate_requirements(TransactionRead(), snapshot, requirements, commission_basis=basis)
    return {'review_interface_profile': 'review-interfaces-v4', 'review_snapshot_ref': snapshot,
        'review_requirements': requirements, 'review_commission_basis': basis,
        'review_selection': value, **({'review_scope_provenance': provenance} if provenance else {})}


def identity(cs, db, actor, result):
    record = cs._read(db, result['task_ref'])
    if record['owner_id'] != actor.id:
        raise ActionForbidden('FORBIDDEN: review binding owner')
    payload = record['payload']
    return {k:payload.get(k) for k in ('review_snapshot_ref', 'review_requirements',
        'review_commission_basis', 'review_selection', 'review_scope_provenance', 'source_use_policy_ref',
        'handoff_release_digest', 'commission_origin', 'scoped_instructions')}


def confirm_reuse(cs, db, actor, review_ref, snapshot, reason, mappings):
    mappings = [ReuseMapping.model_validate(m).model_dump() for m in mappings]
    old = cs._read(db, review_ref)
    current = cs._read(db, {'type': 'DelegatedTask', 'id': actor.task_id, 'version': 1})
    if (actor.role != 'reviewer' or actor.id != 'content:reviewer:'+actor.task_id
            or current['payload'].get('review_snapshot_ref') != snapshot
            or current['payload'].get('review_interface_profile') != 'review-interfaces-v4'):
        raise ActionForbidden('FORBIDDEN: current V4 reviewer assignment required')
    producer = cs._read(db, {'type': 'DelegatedTask', 'id': old['task_id'], 'version': 1})
    if old['ref']['type'] != 'ReviewRecord' or producer['owner_id'] != current['owner_id']:
        raise ActionForbidden('FORBIDDEN: review reuse parent')
    if (not reason.strip() or not mappings or len({m['old_item_index'] for m in mappings}) != len(mappings)
            or len({m['new_scope_id'] for m in mappings}) != len(mappings)):
        raise ActionRejected('REVIEW_REUSE_MAPPING_REQUIRED')
    from .task_supervision import review_identity
    original = producer['payload'].get('review_requirements', [])
    assigned = current['payload']['review_requirements']
    for mapping in mappings:
        index = mapping['old_item_index']
        if type(index) is not int or index < 0 or index >= len(old['payload']['items']):
            raise ActionRejected('REVIEW_ITEM_INDEX_INVALID')
        item = old['payload']['items'][index]
        prior = next((r for r in original if review_identity(r) == review_identity(item)), None)
        target = next((r for r in assigned if r['scope_id'] == mapping['new_scope_id']), None)
        if (not prior or not target or {k:v for k,v in prior.items() if k!='scope_id'} !=
                {k:v for k,v in target.items() if k!='scope_id'}):
            raise ActionRejected('INCOMPATIBLE_REVIEW_REUSE_MAPPING')
        if cs.changed_review_sources(old['payload'], item):
            raise ActionRejected('CHANGED_DEPENDENCY_REQUIRES_RECHECK')
        members = {key(r) for r in [snapshot, *cs._read(db, snapshot)['payload']['refs']]}
        members.update(key(r) for r in current['payload']['review_commission_basis']['criterion_refs'])
        for ref in [item['target_ref'], item['criterion_ref'], *cs.item_dependencies(old['payload'], item)]:
            if key(ref) not in members and ref['type'] != 'SourceArtifact':
                raise ActionRejected('CHANGED_DEPENDENCY_REQUIRES_RECHECK')
        from .deliverables import source_authority
        source_authority(cs, db, actor, [cs._read(db, ref) for ref in cs.item_dependencies(old['payload'], item)])
        if any(cs._read(db, ref)['payload'].get('snapshot_ref') != snapshot for ref in item['artifact_refs']):
            raise ActionRejected('CHANGED_ARTIFACT_REQUIRES_RECHECK')
    return {'reuse_ref': cs._insert(db, actor, 'ReviewReuse', {'review_ref': review_ref,
        'snapshot_ref': snapshot, 'reason': reason, 'target_task_ref': current['ref'],
        'item_mappings': mappings, 'item_indexes': [m['old_item_index'] for m in mappings],
        'applicability_to_snapshot': 'current'})}
