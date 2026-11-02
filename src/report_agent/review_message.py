"""Single-check message model and assembler for the existing ReviewRecord contract."""
from copy import deepcopy
import hashlib
import json
from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .content_tasks import bound_actor
from .errors import ActionForbidden, ActionRejected
from .store import digest, encode
from .workspace import Workspace


class ReviewMessage(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    diagnostic_errors: ClassVar[dict] = {
        'ASSESSMENT_REQUIRED': (['assessment'], 'Provide a non-blank actual assessment.'),
        'NOT_STARTED_VERDICT_MUST_BE_NULL': (['execution_state', 'verdict'], 'Unperformed work has no judgment; use null.'),
        'SATISFIED_REQUIRES_COMPLETED': (['execution_state', 'verdict'], 'Satisfied requires actually completed work; do not invent completion.'),
        'REMAINING_WORK_REQUIRED': (['execution_state', 'remaining_work'], 'Explain the actual remaining work or obstacle for unfinished checks.'),
        'COMPLETED_REMAINING_WORK_CONFLICT': (['execution_state', 'remaining_work'], 'Completed work has no remaining work; report the true progress.'),
        'JUDGMENT_EVIDENCE_REQUIRED': (['verdict', 'evidence_indexes'], 'Select the actual-read receipts supporting the judgment.'),
        'INVALID_EVIDENCE_SELECTION': (['evidence_indexes'], 'Select distinct non-negative positions from this request receipt directory.'),
        'FINDING_FIELDS_REQUIRED': (['finding_type', 'finding_locator_state', 'finding_description', 'finding_impact', 'finding_needed_outcome'], 'A declared finding needs its actual category, location state, problem, impact and needed outcome; omit the whole group when not declaring a finding.'),
        'FINDING_CANNOT_PASS': (['finding_type', 'verdict'], 'A confirmed defect under this criterion cannot be reported as satisfied.'),
        'INPUT_GAP_NOT_CONFIRMED_DEFECT': (['finding_type', 'finding_basis_kind'], 'Missing input is not a confirmed defect in supplied report content.'),
        'COVERAGE_FIELDS_REQUIRED': (['coverage_object_indexes', 'coverage_state', 'coverage_reason'], 'Select actual coverage objects and give their true accounting state and reason together.'),
        'INVALID_COVERAGE_SELECTION': (['coverage_object_indexes'], 'Coverage object positions must be distinct, non-negative and from this request directory.'),
    }
    assigned_scope_index: int | None = Field(default=None, ge=0,
        description="Select one zero-based index from assigned_scopes supplied with THIS request. This selects the exact assigned criterion/target question, not an evidence receipt or a coverage object. Omit or use null only if exactly one scope is assigned. New assignments bind one required check per scope; never guess, merge checks or claim another scope.")
    execution_state: Literal['not_started', 'partial', 'completed', 'blocked'] = Field(
        description="Required progress for the one assigned check: not_started (not performed), partial (some work remains), blocked (cannot proceed; explain why), or completed (the assigned check was actually performed). Available materials or a statement of uncertainty alone do not establish completed work. This is not whole-report acceptance.")
    verdict: Literal['satisfied', 'not_satisfied', 'undetermined'] | None = Field(
        description="Required key. Use null if no judgment has been made; this is different from undetermined, which records a judgment that available evidence does not resolve the question. Allowed non-null values: satisfied, not_satisfied, undetermined. not_started requires null; satisfied requires completed. Every non-null verdict requires at least one selected actual-read receipt. Report the true judgment; do not invent completed work to satisfy validation.")
    assessment: str = Field(min_length=1, description="Required non-blank text containing your actual judgment, grounds and limitations for the selected check. Return the actual assessment, not a resource reference. Text alone does not replace actual-read evidence.")
    evidence_indexes: list[Annotated[int, Field(ge=0)]] = Field(
        description="Required list of distinct integer positions in actual_read_receipts supplied with THIS request, starting at zero. Every i must satisfy 0 <= i < directory length. Select only receipts actually used for this judgment, not source IDs, page numbers, criterion codes or assigned_scope_index. [] explicitly selects none; null and omission are invalid. A non-null verdict OR completed check requires at least one receipt. An empty directory has no selectable indexes.")
    remaining_work: str = Field(default='',
        description="Optional key, default empty string. For not_started, partial or blocked, provide non-blank text explaining the actual remaining work or obstacle. For completed, omit this key or return exactly the empty string; whitespace-only text and null are invalid. Do not claim completed merely to omit the remaining-work explanation.")
    finding_type: Literal['candidate', 'confirmed_defect', 'unresolved', 'suggestion'] | None = Field(default=None,
        description='Optional category of a finding actually made under this check. Omission declares no structured finding in this submission, not that the report has no defects. A confirmed defect cannot accompany a satisfied verdict. The selected evidence supports this finding.')
    finding_locator_state: Literal['located', 'absent', 'ambiguous'] | None = Field(default=None,
        description='Required when finding_type is supplied: located means the problem is located in the examined material; absent means required content is missing; ambiguous means the location remains uncertain. Not a reference or a judgment of correctness.')
    finding_description: str = Field(default='', description='Required non-blank actual problem when declaring finding_type. Otherwise omit. Describe the issue without copying stored identity fields.')
    finding_impact: str = Field(default='', description='Required non-blank actual consequence when declaring finding_type. Otherwise omit; do not invent severity or consequences.')
    finding_needed_outcome: str = Field(default='', description='Required non-blank needed correction or resolution when declaring finding_type. Otherwise omit. State the required outcome without guessing replacement values.')
    finding_basis_kind: Literal['supplied_content', 'snapshot_structure', 'input_gap'] | None = Field(default=None,
        description='Optional factual basis of the declared finding. supplied_content concerns material actually supplied; snapshot_structure concerns saved structure; input_gap means missing input and cannot establish a confirmed content defect.')
    outside_assignment_notes: list[str] = Field(default_factory=list,
        description='Optional actual issues outside this saved assignment. These notes neither cancel assigned checks nor count as completing the original commission. Omit or use [] when no such note is made.')
    coverage_object_indexes: list[Annotated[int, Field(ge=0)]] = Field(default_factory=list,
        description='Optional distinct zero-based positions from THIS request coverage_objects directory. They identify exact ContentNode/Requirement objects, not evidence indexes or assigned scopes. Select only objects whose coverage you actually account for; program does not infer whole-snapshot coverage.')
    coverage_state: Literal['assessed', 'partial', 'not_assessed', 'not_applicable'] | None = Field(default=None,
        description='Required with non-empty coverage_object_indexes: actual accounting status for all selected objects. assessed is not satisfied; partial/unassessed stays unfinished. Non-applicability needs actual grounds and cannot cancel a commissioned Requirement. Otherwise omit or use null.')
    coverage_reason: str = Field(default='', description='Required non-blank grounds and limits with coverage_object_indexes/state. Otherwise omit. Coverage is not inferred from successful reading or saving.')

    def consistency_errors(self, known_fields=None):
        # Partial diagnostics inspect only independently schema-valid fields.
        def known(*names):
            return known_fields is None or set(names) <= known_fields
        errors = []
        if known('assessment') and not self.assessment.strip():
            errors.append('ASSESSMENT_REQUIRED')
        if known('execution_state', 'verdict') and self.execution_state == 'not_started' and self.verdict is not None:
            errors.append('NOT_STARTED_VERDICT_MUST_BE_NULL')
        if known('verdict', 'execution_state') and self.verdict == 'satisfied' and self.execution_state != 'completed':
            errors.append('SATISFIED_REQUIRES_COMPLETED')
        if known('execution_state', 'remaining_work') and self.execution_state != 'completed' and not self.remaining_work.strip():
            errors.append('REMAINING_WORK_REQUIRED')
        if known('execution_state', 'remaining_work') and self.execution_state == 'completed' and self.remaining_work:
            errors.append('COMPLETED_REMAINING_WORK_CONFLICT')
        if known('verdict', 'evidence_indexes') and self.verdict is not None and not self.evidence_indexes:
            errors.append('JUDGMENT_EVIDENCE_REQUIRED')
        if known('evidence_indexes') and (any(i < 0 for i in self.evidence_indexes) or len(set(self.evidence_indexes)) != len(self.evidence_indexes)):
            errors.append('INVALID_EVIDENCE_SELECTION')
        finding_names = ('finding_description', 'finding_impact', 'finding_needed_outcome')
        finding = [getattr(self, name) for name in finding_names if known(name)]
        if known('finding_type') and self.finding_type is not None:
            if (known('finding_locator_state') and self.finding_locator_state is None) or not all(v.strip() for v in finding):
                errors.append('FINDING_FIELDS_REQUIRED')
        elif known('finding_type', 'finding_locator_state', 'finding_basis_kind', *finding_names) and (self.finding_locator_state is not None or any(finding) or self.finding_basis_kind is not None):
            errors.append('FINDING_FIELDS_REQUIRED')
        if known('finding_type', 'verdict') and self.finding_type == 'confirmed_defect' and self.verdict == 'satisfied':
            errors.append('FINDING_CANNOT_PASS')
        if known('finding_type', 'finding_basis_kind') and self.finding_type == 'confirmed_defect' and self.finding_basis_kind == 'input_gap':
            errors.append('INPUT_GAP_NOT_CONFIRMED_DEFECT')
        if known('coverage_object_indexes', 'coverage_state', 'coverage_reason') and self.coverage_object_indexes:
            if self.coverage_state is None or not self.coverage_reason.strip():
                errors.append('COVERAGE_FIELDS_REQUIRED')
        elif known('coverage_object_indexes', 'coverage_state', 'coverage_reason') and (self.coverage_state is not None or self.coverage_reason):
            errors.append('COVERAGE_FIELDS_REQUIRED')
        if known('coverage_object_indexes') and len(set(self.coverage_object_indexes)) != len(self.coverage_object_indexes):
            errors.append('INVALID_COVERAGE_SELECTION')
        return errors

    @model_validator(mode='after')
    def consistent(self):
        errors = self.consistency_errors()
        if errors:
            raise ValueError(errors[0])
        return self


def _task(contents, actor):
    if actor.role != 'reviewer' or bound_actor(Workspace(contents.store), 'reviewer', None) != actor:
        raise ActionForbidden('REVIEW_MESSAGE_TASK_BINDING_REQUIRED')
    task = contents.read({'type': 'DelegatedTask', 'id': actor.task_id, 'version': 1})
    if task['payload'].get('role') != 'reviewer':
        raise ActionForbidden('REVIEW_MESSAGE_TASK_BINDING_REQUIRED')
    return task


def bind_review_message(contents, actor, receipt_ids):
    """Freeze an internal evidence directory; this does not read materials anew."""
    task = _task(contents, actor)
    if len(set(receipt_ids)) != len(receipt_ids):
        raise ActionRejected('DUPLICATE_EVIDENCE_REFERENCE')
    with contents.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        task = contents._read(db, task['ref'])
        receipts = []
        for receipt in receipt_ids:
            row = db.execute('SELECT actor_id,data FROM content_observations WHERE id=?', (receipt,)).fetchone()
            if not row or row[0] != actor.id:
                raise ActionForbidden('EVIDENCE_NOT_AUTHORIZED')
            receipts.append({'receipt_id': receipt, 'sha256': hashlib.sha256(row[1].encode()).hexdigest()})
        snapshot = contents._read(db, task['payload']['review_snapshot_ref'])
        from .review_coverage import inventory
        binding = {'actor_id': actor.id, 'task_id': actor.task_id, 'task_sha256': digest(task), 'receipts': receipts,
                   'snapshot_sha256': digest(snapshot), 'coverage_refs': inventory(snapshot)}
        # Compare and append in one write transaction, including receipt capture.
        latest_key = 'review_message_latest:' + actor.id
        row = db.execute('SELECT value FROM state WHERE key=?', (latest_key,)).fetchone()
        if row:
            previous = json.loads(row[0])
            previous_ids = [r['receipt_id'] for r in previous['receipts']]
            if receipt_ids[:len(previous_ids)] != previous_ids:
                raise ActionRejected('EVIDENCE_DIRECTORY_REORDERED')
            if receipts[:len(previous_ids)] != previous['receipts']:
                raise ActionRejected('RECEIPT_BINDING_CHANGED')
        encoded = json.dumps(binding, sort_keys=True, ensure_ascii=False)
        db.execute('INSERT OR IGNORE INTO state(key,value) VALUES (?,?)',
                   ('review_message_binding:' + digest(binding), encoded))
        db.execute('INSERT OR REPLACE INTO state(key,value) VALUES (?,?)', (latest_key, encoded))
    return binding


def verified_source_observation(contents, actor, value):
    """Use the existing native source receipt verifier, including exact public-return bytes."""
    native = value.get('native_source_material_receipt')
    if not native:
        return None
    record = contents.store.get('source_material:' + native)
    original = contents.store.get('tool_observation:' + record['body_ref']) if record else None
    if not record or not original:
        raise ActionRejected('SOURCE_MATERIAL_ORIGINAL_CHANGED')
    from .source_materials import verify
    return verify(Workspace(contents.store), actor, native, original['text'], record['tool'])


def validate_message_binding(contents, db, actor, binding):
    """Revalidate the original directory inside the existing review save transaction."""
    if binding.get('actor_id') != actor.id or binding.get('task_id') != actor.task_id:
        raise ActionForbidden('REVIEW_MESSAGE_BINDING_CHANGED')
    row = db.execute('SELECT value FROM state WHERE key=?',
                     ('review_message_binding:' + digest(binding),)).fetchone()
    if not row or json.loads(row[0]) != binding:
        raise ActionRejected('REVIEW_MESSAGE_BINDING_UNAVAILABLE')
    task = contents._read(db, {'type': 'DelegatedTask', 'id': actor.task_id, 'version': 1})
    if binding['task_sha256'] != digest(task):
        raise ActionRejected('REVIEW_MESSAGE_BINDING_CHANGED')
    snapshot = contents._read(db, task['payload']['review_snapshot_ref'])
    from .review_coverage import inventory
    if binding['snapshot_sha256'] != digest(snapshot) or binding['coverage_refs'] != inventory(snapshot):
        raise ActionRejected('REVIEW_MESSAGE_BINDING_CHANGED')
    for receipt in binding['receipts']:
        row = db.execute('SELECT actor_id,data FROM content_observations WHERE id=?',
                         (receipt['receipt_id'],)).fetchone()
        if not row or row[0] != actor.id or hashlib.sha256(row[1].encode()).hexdigest() != receipt['sha256']:
            raise ActionRejected('RECEIPT_BINDING_CHANGED')
        verified_source_observation(contents, actor, json.loads(row[1]))


def assemble_check(contents, actor, binding, message, findings=None):
    """Assemble known structure without saving or inventing a material read."""
    from .message_fields import validate_message
    value = validate_message(ReviewMessage, message)
    finding_values = ([validate_message(ReviewMessage, {**message, **finding}) for finding in findings]
                      if findings is not None else [value] if value.finding_type is not None else [])
    task = _task(contents, actor)
    if (binding.get('actor_id') != actor.id or binding.get('task_id') != actor.task_id
            or binding.get('task_sha256') != digest(task)):
        raise ActionRejected('REVIEW_MESSAGE_BINDING_CHANGED')
    receipts = binding['receipts']
    with contents.store.connect() as db:
        validate_message_binding(contents, db, actor, binding)
    requirements = task['payload'].get('review_requirements') or []
    index = value.assigned_scope_index
    if index is None:
        if len(requirements) != 1:
            raise ActionRejected('REVIEW_SCOPE_SELECTION_REQUIRED')
        index = 0
    if index >= len(requirements):
        raise ActionRejected('REVIEW_SCOPE_SELECTOR_INVALID')
    requirement = requirements[index]
    if len(requirement['required_checks']) != 1:
        raise ActionRejected('REVIEW_MESSAGE_REQUIRES_SINGLE_CHECK')
    observations = []
    selected_indexes = list(dict.fromkeys([*value.evidence_indexes,
        *(i for finding in finding_values for i in finding.evidence_indexes)]))
    for evidence_index in selected_indexes:
        if evidence_index >= len(receipts):
            raise ActionRejected('UNKNOWN_EVIDENCE')
        receipt = receipts[evidence_index]['receipt_id']
        observations.append({'receipt_id': receipt, 'locator': 'receipt:' + receipt,
            'observation': 'Program-bound actual read receipt, not a reviewer-authored per-material judgment.',
            'limitations': 'The reviewer judgment is saved separately in reason and check result.'})
    completed = value.execution_state == 'completed'
    scope = requirement['required_checks'][0]
    item = {k: deepcopy(requirement[k]) for k in ('target_ref', 'criterion_ref', 'scope_id')}
    findings = [{'finding_type': finding.finding_type, 'locator_state': finding.finding_locator_state,
        'description': finding.finding_description, 'impact': finding.finding_impact,
        'needed_outcome': finding.finding_needed_outcome, 'basis_kind': finding.finding_basis_kind,
        'requirement_index': 0,
        'observation_indexes': [selected_indexes.index(i) for i in finding.evidence_indexes] or None}
        for finding in finding_values]
    item.update(scope=scope, assessment_kind=requirement.get('assessment_kind', 'content'),
        artifact_refs=deepcopy(requirement.get('artifact_refs', [])),
        execution_state='running' if value.execution_state == 'partial' else value.execution_state,
        verdict=value.verdict, observations=observations, reason=value.assessment, findings=findings,
        outside_assignment_notes=value.outside_assignment_notes,
        checked_requirement_indexes=[0] if completed else [],
        check_results=[{'requirement_index': 0, 'execution_state': value.execution_state,
            'result': value.assessment, 'observation_indexes': [selected_indexes.index(i) for i in value.evidence_indexes],
            'remaining': value.remaining_work}],
        coverage={'checked': [scope] if completed else [],
            'unchecked': [scope] if value.execution_state in {'partial', 'not_started'} else [],
            'blocked': [scope] if value.execution_state == 'blocked' else [],
            'basis': 'Model-declared progress for this assigned check only; not whole-report acceptance.'})
    snapshot = task['payload']['review_snapshot_ref']
    from .content_models import refs_in
    from .task_supervision import historical_read_refs, material_refs_in_observation
    required = [*requirement.get('required_read_refs', []),
        *requirement.get('required_materials', [])]
    source_dependencies = [ref.model_dump() for ref in refs_in(required) if ref.type == 'SourceArtifact']
    with contents.store.connect() as db:
        observed = set()
        for observation in observations:
            data = db.execute('SELECT data FROM content_observations WHERE id=?', (observation['receipt_id'],)).fetchone()
            actual = json.loads(data[0])
            observed.update(material_refs_in_observation(actual))
            for obj in actual.get('objects', []):
                if obj.get('ref', {}).get('type') == 'SourceArtifact':
                    source_dependencies.append(obj['ref'])
                elif obj.get('ref', {}).get('type') == 'Evidence':
                    source_dependencies.extend(obj.get('payload', {}).get('source_refs', []))
        members = {encode(ref) for ref in contents._read(db, snapshot)['payload']['refs']}
    dependencies = {encode(ref): ref for ref in source_dependencies}
    dependencies.update({key: json.loads(key) for key in historical_read_refs(requirement, members, observed)})
    coverage = []
    if value.coverage_object_indexes:
        if any(i >= len(binding['coverage_refs']) for i in value.coverage_object_indexes):
            raise ActionRejected('UNKNOWN_COVERAGE_OBJECT')
        coverage = [{'target_refs': [binding['coverage_refs'][i] for i in value.coverage_object_indexes],
            'state': value.coverage_state, 'reason': value.coverage_reason, 'item_indexes': [0]}]
    return {'snapshot_ref': snapshot, 'target_ref': item['target_ref'], 'scope': scope,
        'criteria_refs': [item['criterion_ref']], 'dependency_refs': list(dependencies.values()),
        'items': [item], 'coverage_accounting': coverage}


def save_review_message(contents, actor, operation_id, binding, message, *, runtime_identity=None):
    """Keep the existing save API on the same assembler and native transaction."""
    submission = assemble_review_message(contents, actor, binding, message)
    return contents.submit_review(actor, operation_id, submission, runtime_identity or {},
                                  review_message_binding=binding)


def assemble_review_message(contents, actor, binding, message):
    """Compatibility entry point for the deployed single-finding interface."""
    return assemble_check(contents, actor, binding, message)
