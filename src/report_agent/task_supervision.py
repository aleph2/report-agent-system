"""Reconcile delegated review requirements with saved evidence, not engineering truth.

No independent backlog or agent loop. The native task middleware uses these records
to retain gaps and reserve at most one completion follow-up per task identity.
"""
import json
from uuid import uuid4

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .content_models import ArtifactRef, Contract, Ref
from .content_store import ContentStore
from .errors import ActionRejected
from .store import encode, digest
from .evidence_analysis import SourceTableView
from .content_inputs import SourceRef
from .review_input import snapshot_body_topology, body_extent_refs, scope_body_pool


class ReviewSourceRange(Contract):
    source_ref: Ref
    offset: int = Field(ge=0, description="Zero-based existing text-block offset, not physical page.")
    limit: int = Field(ge=1, le=50, description="Exact task-linked eligible text-block span, not a whole-document request.")


class RequiredSourceSpan(ReviewSourceRange):
    source_ref: SourceRef
    table_detail: SourceTableView | None = Field(default=None,
        description="Required source view: references keeps frozen blocks and table references; full includes mechanical whole-page table supplements. Omit for historical full view. View does not prove truth or whole-file coverage.")


class RequiredReviewMaterial(Contract):
    requirement_index: int = Field(ge=0)
    purpose: str = Field(min_length=1)
    refs: list[Ref] = Field(default_factory=list,
        description="Exact required object LOCAL PAYLOADS, automatically supplied to the checker. A SourceArtifact here means its WHOLE frozen text body, not just its identity; use source_spans for located original text. No contains-linked descendants are implied.")
    source_spans: list[RequiredSourceSpan] = Field(default_factory=list,
        description="Mandatory located source text for this check, loaded from exact source versions and block spans. Each completed check must link observations of these actual supplied spans. refs and source_spans are cumulative; both empty means unresolved, never optional. Extra eligible ranges alone cannot fulfill this dependency.")


class ArtifactCheckScope(Contract):
    """Evidence extent of one assigned check, independent of the whole item."""
    requirement_index: int = Field(ge=0)
    kind: Literal["export_structure", "render_pages"]
    artifact_ref: Ref
    pages: list[Annotated[int, Field(ge=1, strict=True)]] = Field(default_factory=list)

    @model_validator(mode="after")
    def extent(self):
        if self.kind == "export_structure":
            if self.artifact_ref.type != "ExportArtifact" or self.pages:
                raise ValueError("EXPORT_CHECK_REQUIRES_EXPORT_WITHOUT_PAGES")
        elif (self.artifact_ref.type != "RenderArtifact" or not self.pages
                or any(type(p) is not int or p < 1 for p in self.pages)
                or len(set(self.pages)) != len(self.pages)):
            raise ValueError("RENDER_CHECK_REQUIRES_DISTINCT_POSITIVE_PAGES")
        return self


class ReferencePageBinding(Contract):
    render_ref: Ref
    page: int = Field(ge=1, strict=True)
    reference_page: int = Field(ge=1, strict=True)
    purpose: str = Field(min_length=1,
        description="Why these actual pages correspond for the assigned visual question; a label is not proof of semantic equivalence.")


class ContentCheckScope(Contract):
    """Declared body extent, not a method or authority to select extra material."""
    requirement_index: int = Field(ge=0)
    node_ref: Ref
    kind: Literal["local_body", "subtree_bodies"]


class ReviewRequirement(Contract):
    target_ref: Ref = Field(description="Exact assessment target. For bounded content review, select a ContentNode (including an explicitly scoped report root); review_snapshot_ref is the version anchor, not a content-tool target. Other review routes retain their own target capabilities.")
    criterion_ref: Ref
    scope_id: str = Field(min_length=1)
    assessment_kind: str = Field(default="content", pattern="^(content|export|render)$")
    required_checks: list[str] = Field(min_length=1)
    required_read_refs: list[Ref] = Field(default_factory=list)
    material_refs: list[Ref] = Field(default_factory=list,
        description="Task-linked material pool for this scoped check. The reviewer may select relevant portions; it does not expand the target/questions.")
    required_materials: list[RequiredReviewMaterial] = Field(default_factory=list,
        description="Evidence dependencies for specific required_checks. A completed check must cite its supplied dependencies; unresolved dependencies cannot pass.")
    source_ranges: list[ReviewSourceRange] = Field(default_factory=list,
        description="Task-defined original-source spans eligible for additional selection. Reviewer selections must stay inside these spans; file membership alone does not authorize a whole-source request.")
    content_check_scopes: list[ContentCheckScope] = Field(default_factory=list,
        description="Body extent needed by a specific content check: local_body or the contains-linked subtree_bodies of an exact node. Missing full bodies return a pre-call gap. This does not grant access beyond the task material pool or choose a checking workflow.")
    artifact_refs: list[ArtifactRef] = Field(default_factory=list)
    presentation_reference_ref: Ref | None = Field(default=None,
        description="Exact customer SourceArtifact version for Word visual comparison. All rendered Word pages require full-page paired observations; crops cannot establish completion.")
    artifact_check_scopes: list[ArtifactCheckScope] = Field(default_factory=list,
        description="Per-required-check evidence extent. Export structure needs its actual export read; page checks need the listed full pages. Unspecified checks retain the full assigned artifact coverage rule. This never narrows whole-item completion.")
    reference_page_bindings: list[ReferencePageBinding] = Field(default_factory=list,
        description="Task-bound Word/customer physical-page correspondences with purpose. When supplied, every page claimed covered must have its exact binding; an unbound or differently paired page remains unchecked.")
    require_check_evidence: bool = Field(default=False,
        description="Require per-check results linked to actual task observations. Does not prove substantive understanding or correctness.")

    @model_validator(mode="after")
    def distinct_checks(self):
        if any(not c.strip() for c in self.required_checks) or len(set(self.required_checks)) != len(self.required_checks):
            raise ValueError("REQUIRED_CHECKS_MUST_BE_DISTINCT_AND_NONEMPTY")
        if self.assessment_kind != "content" and not self.artifact_refs:
            raise ValueError("EXPORT_RENDER_ASSIGNMENT_REQUIRES_EXACT_ARTIFACTS")
        if any(m.requirement_index >= len(self.required_checks) for m in self.required_materials):
            raise ValueError("REQUIRED_MATERIAL_CHECK_OUTSIDE_ASSIGNMENT")
        indexes = [s.requirement_index for s in self.artifact_check_scopes]
        if (len(set(indexes)) != len(indexes)
                or any(i >= len(self.required_checks) for i in indexes)
                or (self.assessment_kind == "content" and indexes)):
            raise ValueError("ARTIFACT_CHECK_SCOPE_OUTSIDE_ASSIGNMENT")
        keys = [(b.render_ref.key(), b.page) for b in self.reference_page_bindings]
        if (len(set(keys)) != len(keys) or
                self.reference_page_bindings and (self.assessment_kind != "render" or not self.presentation_reference_ref)):
            raise ValueError("REFERENCE_PAGE_BINDING_REQUIRES_UNIQUE_RENDER_REFERENCE_SCOPE")
        return self


def review_contract_issues(requirements):
    """Explain index errors from the original call; no validation or repair authority.

    Normal schema/domain validation still decides admission. This projection only
    supplies locations and the existing distinctness rules to the calling model.
    """
    issues = []
    if not isinstance(requirements, list):
        return issues
    for item_index, item in enumerate(requirements):
        if not isinstance(item, dict) or not isinstance(item.get('required_checks'), list):
            continue
        count = len(item['required_checks'])
        for field in ('required_materials', 'artifact_check_scopes', 'content_check_scopes'):
            extents = item.get(field, [])
            if not isinstance(extents, list):
                continue
            seen = set()
            for extent_index, extent in enumerate(extents):
                if not isinstance(extent, dict) or type(extent.get('requirement_index')) is not int:
                    continue
                index = extent['requirement_index']
                path = f'review_requirements/{item_index}/{field}/{extent_index}'
                detail = {'allowed_index_range': {'minimum': 0, 'exclusive_maximum': count},
                          'actual_index': index, 'index_owner': 'this ReviewRequirement.required_checks'}
                if not 0 <= index < count:
                    issues.append({'code': 'CHECK_INDEX_OUT_OF_RANGE',
                                   'path': path + '/requirement_index', **detail})
                if field == 'artifact_check_scopes':
                    key, code = index, 'ARTIFACT_CHECK_SCOPE_DUPLICATE_INDEX'
                elif field == 'content_check_scopes':
                    key, code = (index, encode(extent.get('node_ref'))), 'CONTENT_CHECK_SCOPE_DUPLICATE_NODE'
                else:
                    continue  # Multiple required materials may belong to one check.
                if key in seen:
                    issues.append({'code': code, 'path': path, **detail})
                seen.add(key)
    return issues


def assignment(contents, task_id):
    return contents.read({"type": "DelegatedTask", "id": task_id, "version": 1})["payload"]


def source_selection_bindings(contents, requirements):
    """Resolve only saved task spans to the source_id used by selection tools.

    SourceArtifact.ref.id identifies a captured business object; its payload's
    source_id identifies the file. Exposing this mapping does not add material,
    change a range, read file bodies or create a retrieval index.
    """
    result = [{"scope_id": requirement["scope_id"], "source_ref": span["source_ref"],
             "source_id": contents.read(span["source_ref"])["payload"]["source_id"],
             "offset": span["offset"], "limit": span["limit"]}
            for requirement in requirements for span in requirement.get("source_ranges", [])]
    result += [{**entry, 'source_id': contents.read(entry['source_ref'])['payload']['source_id'],
                'extent': 'required original blocks; automatically loaded if admitted'}
               for entry in required_source_spans(requirements)]
    return result


def required_source_spans(requirements):
    return [{'scope_id': r['scope_id'], 'requirement_index': m['requirement_index'],
             'purpose': m['purpose'], **s}
            for r in requirements for m in r.get('required_materials', []) for s in m.get('source_spans', [])]




def review_identity(value):
    return (encode(value['target_ref']), encode(value['criterion_ref']),
            value.get('scope_id') or value['scope'], value.get('assessment_kind', 'content'))


def historical_read_refs(requirement, members, observed=None):
    """Exact, task-declared comparison bodies; never target membership.

    Admission checks declaration. Publication/reconciliation additionally supply
    the actual owner's whole-body reads at that review's temporal boundary.
    """
    return {encode(r) for r in requirement.get('required_read_refs', [])
            if r['type'] == 'ContentNode' and encode(r) not in members
            and (observed is None or encode(r) in observed)}


def content_review_capability_issue(requirement):
    """Describe the content tool's actual capability; never change a saved scope."""
    target = requirement['target_ref']
    if requirement['assessment_kind'] == 'content' and target['type'] == 'ContentNode':
        return None
    return {'code': 'BOUNDED_TOOL_SUPPORTS_NODE_CONTENT_ONLY',
            'scope_id': requirement['scope_id'], 'target_ref': target,
            'assessment_kind': requirement['assessment_kind'],
            'tool': 'perform_assigned_review', 'supported_target_types': ['ContentNode'],
            'model_called': False,
            'reason': f"Unsupported review route: assessment_kind={requirement['assessment_kind']}, target type={target['type']}. perform_assigned_review requires assessment_kind=content and target type ContentNode.",
            'correction': 'The Coordinator must explicitly correct the task target or choose a compatible review route. Changing selections or operation_id does not change the saved target. Preserve the original checks, evidence requirements and versions; no automatic target conversion.'}


def review_readiness(contents, snapshot_ref, requirements, *, commission_basis=None):
    """Read-only static diagnostics; never binds evidence or judges its adequacy.

    Exact objects are resolved once per analysis, with no cache across calls.
    Structural validity and bounded-content admission are separate: an explicitly
    unresolved dependency may be a valid exploratory assignment.
    """
    issues, objects, automatically_loaded_refs = [], {}, []

    def issue(code, path, reason, scope=None, check=None, ref=None,
              kind='structural', **details):
        issues.append({'code': code, 'kind': kind, 'scope_id': scope,
            'requirement_index': check, 'path': path, 'ref': ref,
            'reason': reason, **details})

    def read(ref, path, scope=None, check=None):
        key = encode(ref)
        if key not in objects:
            try:
                objects[key] = contents.read(ref)
            except ActionRejected as exc:
                objects[key] = exc
        value = objects[key]
        if isinstance(value, ActionRejected):
            issue(str(value).split(':')[0], path, str(value), scope, check, ref)
            return None
        return value

    if not snapshot_ref:
        issue('REVIEW_REQUIREMENTS_REQUIRED', '/review_snapshot_ref', 'No review snapshot is bound.')
        return {'execution_ready': False, 'issues': issues}
    snap = read(snapshot_ref, '/review_snapshot_ref')
    if not snap or snap['ref']['type'] != 'DocumentSnapshot' or not requirements:
        if snap or not issues:
            issue('REVIEW_REQUIREMENTS_REQUIRED', '/review_requirements',
                  'A DocumentSnapshot and nonempty saved requirements are required.')
        return {'execution_ready': False, 'issues': issues}
    members = {encode(r) for r in [snap['ref'], *snap['payload']['refs']]}
    keys, scopes, topology = set(), {}, None
    from .handoff_release import manifest as bound_manifest
    manifest = {**contents.store.manifest, **bound_manifest(contents.store)}
    designated = manifest.get('presentation_references', [])
    for ri, requirement in enumerate(requirements):
        base, scope = f'/review_requirements/{ri}', requirement['scope_id']
        kind = requirement['assessment_kind']
        if manifest.get('review_execution_mode') == 'bounded-tool-v1' and kind == 'content':
            capability = content_review_capability_issue(requirement)
            if capability:
                issue(capability['code'], f'{base}/target_ref', capability['reason'], scope,
                      ref=capability['target_ref'], kind='capability',
                      tool=capability['tool'], supported_target_types=capability['supported_target_types'],
                      correction=capability['correction'], model_called=False)
        key = review_identity(requirement)
        if scope in scopes:
            issue('DUPLICATE_TASK_REVIEW_SCOPE', base,
                  'scope_id must identify one assigned outcome; no automatic selection or renaming.', scope,
                  matching_requirement_indexes=[scopes[scope], ri])
        scopes[scope] = ri
        if key in keys:
            issue('DUPLICATE_TASK_REVIEW_REQUIREMENT', base, 'Duplicate target, criterion, scope and assessment kind.', scope)
        keys.add(key)
        for field in ('target_ref', 'criterion_ref'):
            ref = requirement[field]
            allowed = ({encode(r) for r in commission_basis['criterion_refs']}
                       if field == 'criterion_ref' and commission_basis is not None else members)
            if encode(ref) not in allowed or field == 'criterion_ref' and ref['type'] != 'Criterion':
                issue('TASK_REVIEW_REQUIREMENT_OUTSIDE_SNAPSHOT', f'{base}/{field}',
                      'Exact target and Criterion must belong to the assigned snapshot.', scope, ref=ref)
        for i, ref in enumerate(requirement['required_read_refs']):
            path = f'{base}/required_read_refs/{i}'
            read(ref, path, scope)
            if ref['type'] not in {'ContentNode', 'SourceArtifact'}:
                issue('TASK_READ_REQUIRES_CONTENT_OR_SOURCE', path, 'Whole-body reads accept ContentNode or SourceArtifact.', scope, ref=ref)
        materials = [(r, f'{base}/material_refs/{i}', None) for i, r in enumerate(requirement.get('material_refs', []))]
        materials += [(r, f'{base}/required_materials/{i}/refs/{j}', m['requirement_index'])
                      for i, m in enumerate(requirement.get('required_materials', [])) for j, r in enumerate(m['refs'])]
        for i, material in enumerate(requirement.get('required_materials', [])):
            for j, span in enumerate(material.get('source_spans', [])):
                path, ref = f'{base}/required_materials/{i}/source_spans/{j}', span['source_ref']
                if kind != 'content' or ref['type'] != 'SourceArtifact':
                    issue('REQUIRED_SOURCE_SPAN_REQUIRES_CONTENT_AND_SOURCE', path,
                          'Required original spans belong to content checks and exact SourceArtifact versions.',
                          scope, material['requirement_index'], ref)
                materials.append((ref, path+'/source_ref', material['requirement_index']))
        for i, span in enumerate(requirement.get('source_ranges', [])):
            path, ref = f'{base}/source_ranges/{i}/source_ref', span['source_ref']
            if ref['type'] != 'SourceArtifact':
                issue('TASK_SOURCE_RANGE_REQUIRES_SOURCE_VERSION', path, 'Eligible ranges require an exact SourceArtifact.', scope, ref=ref)
            materials.append((ref, path, None))
        for ref, path, check in materials:
            read(ref, path, scope, check)
            if ref['type'] not in {'ContentNode', 'Evidence', 'SourceArtifact'}:
                issue('TASK_MATERIAL_REQUIRES_CONTENT_EVIDENCE_OR_SOURCE', path, 'Material must be content, located evidence or source.', scope, check, ref)
            if ref['type'] != 'SourceArtifact' and encode(ref) not in members:
                issue('TASK_MATERIAL_OUTSIDE_SNAPSHOT', path, 'Exact non-source material must belong to the assigned snapshot.', scope, check, ref)
        body_pool = scope_body_pool(requirement)
        extent_keys = set()
        for i, extent in enumerate(requirement.get('content_check_scopes', [])):
            ref, check = extent['node_ref'], extent['requirement_index']
            ek = (check, encode(ref))
            reasons = []
            if kind != 'content': reasons.append('not a content assessment')
            if check >= len(requirement['required_checks']): reasons.append('check index outside assignment')
            if ref['type'] != 'ContentNode': reasons.append('extent is not a ContentNode')
            if ek[1] not in body_pool: reasons.append('node is outside this scope material pool')
            if ek[1] not in members: reasons.append('exact node version is outside snapshot')
            if ek in extent_keys: reasons.append('duplicate check/node extent')
            if reasons:
                issue('CONTENT_CHECK_SCOPE_OUTSIDE_ASSIGNMENT', f'{base}/content_check_scopes/{i}',
                      '; '.join(reasons), scope, check, ref)
            elif manifest.get('review_execution_mode') == 'bounded-tool-v1' and kind == 'content':
                if topology is None:
                    _, topology = snapshot_body_topology(contents, snap)
                required = body_extent_refs(topology, extent)
                missing = [r for r in required if encode(r) not in body_pool]
                if missing:
                    issue('REVIEW_BODY_EXTENT_OUTSIDE_MATERIAL_POOL', f'{base}/content_check_scopes/{i}',
                          'Declared body extent includes nodes outside this scope material pool. '
                          'Coordinator must explicitly correct the assignment; no access is granted. '
                          'Eligible but unselected bodies are not this admission gap.',
                          scope, check, ref, kind='unbound_body', missing_refs=missing,
                          required_body_count=len(required), bound_body_count=len(required)-len(missing),
                          unbound_body_count=len(missing), missing_refs_complete=True,
                          state='extent_not_authorized', model_called=False)
            extent_keys.add(ek)
        for i, ref in enumerate(requirement['artifact_refs']):
            path = f'{base}/artifact_refs/{i}'
            artifact = read(ref, path, scope)
            if ref['type'] not in {'ExportArtifact', 'RenderArtifact'} or artifact and artifact['payload'].get('snapshot_ref') != snapshot_ref:
                issue('TASK_ARTIFACT_OUTSIDE_SNAPSHOT', path, 'Artifact must be an export/render from the exact assigned snapshot.', scope, ref=ref)
        for i, extent in enumerate(requirement.get('artifact_check_scopes', [])):
            ref, check, path = extent['artifact_ref'], extent['requirement_index'], f'{base}/artifact_check_scopes/{i}'
            if ref not in requirement['artifact_refs']:
                issue('CHECK_ARTIFACT_OUTSIDE_ASSIGNED_SCOPE', path, 'Check artifact is not assigned to this scope.', scope, check, ref)
            if extent['kind'] == 'render_pages':
                artifact = read(ref, path, scope, check)
                if artifact and any(p > len(artifact['payload'].get('page_assets', [])) for p in extent['pages']):
                    issue('CHECK_PAGE_OUTSIDE_RENDER', path, 'Check page exceeds saved render extent.', scope, check, ref)
        for i, binding in enumerate(requirement.get('reference_page_bindings', [])):
            ref, path = binding['render_ref'], f'{base}/reference_page_bindings/{i}'
            if ref not in requirement['artifact_refs'] or ref['type'] != 'RenderArtifact':
                issue('REFERENCE_BINDING_OUTSIDE_RENDER_SCOPE', path, 'Paired page requires an assigned render.', scope, ref=ref)
            artifact = read(ref, path, scope)
            if artifact and binding['page'] > len(artifact['payload'].get('page_assets', [])):
                issue('REFERENCE_BINDING_PAGE_OUTSIDE_RENDER', path, 'Paired page exceeds saved render extent.', scope, ref=ref)
        reference = requirement.get('presentation_reference_ref')
        if reference:
            path = f'{base}/presentation_reference_ref'
            if kind != 'render' or reference['type'] != 'SourceArtifact':
                issue('PRESENTATION_REFERENCE_REQUIRES_RENDER_AND_SOURCE', path, 'Customer reference requires render scope and SourceArtifact.', scope, ref=reference)
            source = read(reference, path, scope)
            if source and designated and source['payload'].get('source_id') not in {r['source_id'] for r in designated}:
                issue('PRESENTATION_REFERENCE_NOT_DESIGNATED', path, 'Reference is not designated for this commission.', scope, ref=reference)
        if manifest.get('review_execution_mode') == 'bounded-tool-v1' and kind == 'render':
            if not any(r['type'] == 'RenderArtifact' for r in requirement['artifact_refs']):
                issue('WORD_LAYOUT_ASSIGNMENT_REQUIRES_RENDER', f'{base}/artifact_refs', 'Bounded layout comparison requires actual render.', scope)
            if designated and not reference:
                issue('WORD_LAYOUT_ASSIGNMENT_REQUIRES_CUSTOMER_REFERENCE', f'{base}/presentation_reference_ref', 'Designated customer reference is required.', scope)
        if kind != 'content':
            continue
        automatically_loaded_refs.append({'scope_id': scope, 'refs': list({encode(r): r for r in [
            requirement['target_ref'], requirement['criterion_ref'], *requirement['required_read_refs'],
            *[r for m in requirement.get('required_materials', []) for r in m['refs']]]}.values()),
            'extent': 'exact saved object local payload; no contains-linked descendants',
            'state': 'planned only; loaded by checker if admitted, not a reading receipt'})
        declared = {m['requirement_index'] for m in requirement.get('required_materials', [])}
        for check, question in enumerate(requirement['required_checks']):
            if check not in declared:
                issue('REQUIRED_REVIEW_MATERIAL_UNRESOLVED', f'{base}/required_checks/{check}',
                      'Declare supporting exact refs or source_spans; both empty declares an unresolved dependency.',
                      scope, check, kind='undeclared', purpose=question, missing_refs=[], state='evidence_contract_not_declared')
        for i, material in enumerate(requirement.get('required_materials', [])):
            if not material['refs'] and not material.get('source_spans'):
                issue('REQUIRED_REVIEW_MATERIAL_UNRESOLVED', f'{base}/required_materials/{i}/refs',
                      'Explicit dependency remains unresolved; available selections do not replace its saved binding.',
                      scope, material['requirement_index'], kind='unresolved', purpose=material['purpose'],
                      missing_refs=[], state='unresolved_binding')
        # Only mandatory whole-body refs count here; a material pool or eligible
        # source range is not a requirement to read the entire source.
        mandatory = [(r, f'{base}/required_read_refs/{i}', None) for i, r in enumerate(requirement['required_read_refs'])]
        mandatory += [(r, f'{base}/required_materials/{i}/refs/{j}', m['requirement_index'])
                      for i, m in enumerate(requirement.get('required_materials', [])) for j, r in enumerate(m['refs'])]
        for ref, path, check in mandatory:
            if ref['type'] == 'SourceArtifact':
                source = read(ref, path, scope, check)
    result = {'execution_ready': not issues, 'issues': issues,
            'automatically_loaded_refs': automatically_loaded_refs,
            'limitation': 'Static readiness for all assigned scopes, not a source reading receipt or verdict. False does not prohibit a supported selected scope: inspect issue.scope_id. Unfinished scopes remain unfinished; partial execution is not whole-task completion.'}
    spans = required_source_spans(requirements)
    if spans:
        result['automatically_loaded_source_spans'] = spans
    return result


def readiness_metadata(readiness):
    """Bounded server control data, not assignment prose or a semantic verdict.

    Keep exact issue locations and refs as whole entries. When an unusually large
    assignment cannot fit, its original remains recoverable and counts say so.
    """
    issues = [{k: issue[k] for k in ('code', 'kind', 'scope_id', 'requirement_index', 'path', 'ref', 'characters', 'state', 'tool', 'supported_target_types', 'required_body_count', 'bound_body_count', 'unbound_body_count', 'utf8_bytes', 'maximum_utf8_bytes', 'capacity_policy_ref')
               if k in issue} for issue in readiness['issues']]
    for shown, original in zip(issues, readiness['issues']):
        if 'missing_refs' in original:
            shown['missing_refs_location'] = 'Full exact list in original observation; not reproduced in bounded metadata.'
        if 'reason' in original:
            shown.update(reason=original['reason'][:160], reason_complete=len(original['reason']) <= 160)
            if len(original['reason']) > 160:
                shown['reason_characters'] = len(original['reason'])
    loads = [{'scope_id': scope['scope_id'], 'ref': ref}
             for scope in readiness.get('automatically_loaded_refs', []) for ref in scope['refs']]
    result = {'kind': 'review_readiness', 'execution_ready': readiness['execution_ready'],
              'issues': {'entries': [], 'shown': 0, 'total': len(issues), 'complete': not issues},
              'automatically_loaded_refs': {'entries': [], 'shown': 0, 'total': len(loads), 'complete': not loads},
              'automatic_load_extent': 'Exact saved local payloads only; no contains descendants. Planned checker inputs, not a reading receipt.',
              'limitation': 'Static readiness only; no comparison, verdict or acceptance. Full assignment and reasons remain in the original observation.'}
    groups = [('issues', issues), ('automatically_loaded_refs', loads)]
    spans = readiness.get('automatically_loaded_source_spans', [])
    if spans:
        result['automatically_loaded_source_spans'] = {'entries': [], 'shown': 0, 'total': len(spans), 'complete': False}
        groups.append(('automatically_loaded_source_spans', spans))
    # Alternate the two inventories so even an overflowing issue list cannot
    # hide the existence/count of automatic inputs. Never split a ref or path.
    for i in range(max(len(items) for _, items in groups)):
        for key, items in groups:
            if i >= len(items):
                continue
            group = result[key]
            if len(group['entries']) >= 20:
                continue
            group['entries'].append(items[i])
            group['shown'] = len(group['entries'])
            group['complete'] = group['shown'] == group['total']
            if len(encode(result)) > 4800:
                group['entries'].pop()
                group['shown'] = len(group['entries'])
                group['complete'] = False
    return result


def validate_requirements(contents, snapshot_ref, requirements, *, commission_basis=None):
    readiness = review_readiness(contents, snapshot_ref, requirements, commission_basis=commission_basis)
    structural = [i for i in readiness['issues'] if i['kind'] == 'structural']
    if structural:
        raise ActionRejected(structural[0]['code'] + ': ' + encode(readiness))
    return readiness


def observed_refs(contents, actor_id, observations):
    """Only returned bodies, never unreturned inventory/manifest references.

This establishes a read, not that the reader understood or compared the material.
Partial selections remain partial and cannot satisfy a required whole-body read.
"""
    refs = set()
    with contents.store.connect() as db:
        for observation in observations:
            row = db.execute("SELECT actor_id,data FROM content_observations WHERE id=?",
                             (observation["receipt_id"],)).fetchone()
            if not row or row[0] != actor_id:
                continue
            refs.update(material_refs_in_observation(json.loads(row[1])))
    return refs


def material_refs_in_observation(value):
    if value.get("status") == "failed" or value.get("execution_state") == "blocked" or value.get("ok") is False:
        return set()
    refs = {encode(obj["ref"]) for obj in value.get("objects", [])
        if obj.get("ref", {}).get("type") in {"ContentNode", "Evidence", "SourceArtifact"} and "payload" in obj}
    refs.update(encode(s["selection"]["ref"]) for s in value.get("selections", []) if s.get("complete_body_selection"))
    return refs


def source_extents_in_observation(contents, actor_id, value):
    """Verify original returned bytes and source version, never metadata alone."""
    from types import SimpleNamespace
    from .content_store import Actor
    from .source_materials import verify
    extents = []
    if value.get('ok') is False or value.get('status') == 'failed' or value.get('execution_state') == 'blocked':
        return extents
    native = value.get('native_source_material_receipt')
    if native:
        stored = contents.store.get('source_material:' + native)
        if not stored or stored.get('actor', {}).get('id') != actor_id:
            raise ActionRejected('REVIEW_SOURCE_RECEIPT_OWNER_MISMATCH')
        original = contents.store.get('tool_observation:' + stored['body_ref'])
        if not original:
            raise ActionRejected('SOURCE_MATERIAL_ORIGINAL_CHANGED')
        record = verify(SimpleNamespace(store=contents.store), Actor(**stored['actor']),
                        native, original['text'], stored['tool'])
        page = json.loads(original['text'])
        # Only actual frozen block reads prove block spans. Images, snippets,
        # character excerpts and model analyses do not become whole-source reads.
        for material in record['materials']:
            if (stored['tool'] != 'read_source_page' or material['kind'] != 'frozen_source_selection'
                    or material['selected_value_digest'] != digest(page.get('blocks', []))
                    or material['supplement_digest'] != digest(page.get('source_table_views', []))):
                continue
            for ref in material['source_version_refs']:
                payload = contents.read(SourceRef.model_validate(ref).model_dump())['payload']
                if material['source_payload_digest'] == digest(payload):
                    extents.append({'source_ref':ref, 'ordinals':material['selection']['ordinals'],
                                    'table_detail':page.get('table_detail') or 'full'})
    for entry in value.get('evidence', []):
        if entry.get('kind') != 'source_blocks' or not entry.get('source_material_receipt'):
            continue
        receipt = entry['source_material_receipt']
        stored = contents.store.get('source_material:' + receipt)
        if not stored or stored.get('actor', {}).get('id') != actor_id:
            raise ActionRejected('REVIEW_SOURCE_RECEIPT_OWNER_MISMATCH')
        page = entry['observation']
        original = contents.store.get('tool_observation:' + stored['body_ref'])
        if not original or json.loads(original['text']) != page:
            raise ActionRejected('SOURCE_MATERIAL_PUBLIC_RETURN_CHANGED')
        # Packet encoding may reorder JSON keys. Verify the archived original
        # bytes, then exact parsed payload equality; do not reserialize a receipt.
        record = verify(SimpleNamespace(store=contents.store), Actor(**stored['actor']), receipt,
                        original['text'], 'read_source_page')
        view = page.get('table_detail') or 'full'
        if view != (entry['selection'].get('table_detail') or 'full'):
            raise ActionRejected('REVIEW_SOURCE_RECEIPT_VIEW_MISMATCH')
        for ref in entry.get('source_version_refs', []):
            payload = contents.read(SourceRef.model_validate(ref).model_dump())['payload']
            for material in record['materials']:
                if (material['kind'] == 'frozen_source_selection'
                        and material['source_id'] == payload['source_id']
                        and material['source_payload_digest'] == digest(payload)
                        and material['selected_value_digest'] == digest(page['blocks'])
                        and material['supplement_digest'] == digest(page.get('source_table_views', []))):
                    extents.append({'source_ref': ref, 'ordinals': material['selection']['ordinals'],
                                    'table_detail': view})
    return extents


def missing_required_materials(requirement, available_refs, check_indexes=None, source_extents=()):
    """Presence of declared exact material, not its semantic adequacy or truth."""
    missing = []
    for material in requirement.get("required_materials", []):
        if check_indexes is not None and material["requirement_index"] not in check_indexes:
            continue
        absent = [r for r in material["refs"] if encode(r) not in available_refs]
        spans = material.get('source_spans', [])
        absent_spans = []
        for span in spans:
            ordinals = {n for actual in source_extents
                        if actual['source_ref'] == span['source_ref']
                        and actual['table_detail'] == (span.get('table_detail') or 'full')
                        for n in actual['ordinals']}
            if not set(range(span['offset'], span['offset'] + span['limit'])).issubset(ordinals):
                absent_spans.append(span)
        unresolved = not material['refs'] and not spans
        if unresolved or absent or absent_spans:
            gap = {"requirement_index": material["requirement_index"],
                "purpose": material["purpose"], "missing_refs": absent,
                "state": "unresolved_binding" if unresolved else "not_supplied"}
            if spans:
                gap['missing_source_spans'] = absent_spans
            missing.append(gap)
    return missing


def review_read_refs(contents, record):
    """Task-local reads preceding submission; historical records use batch citations.

    These are access receipts, not substitutes for each judgment's support links.
    Old records lack a temporal boundary: do not pool later uncited observations.
    Reused judgments retain the originating task's evidence, not another actor's.
    """
    boundary = record["payload"].get("observation_rowid")
    if boundary is None:
        observations = [o for i in record["payload"]["items"] for o in i["observations"]]
    else:
        with contents.store.connect() as db:
            observations = [{"receipt_id": r[0]} for r in db.execute(
                "SELECT id FROM content_observations WHERE actor_id=? AND rowid<=?",
                (record["owner_id"], boundary))]
    return observed_refs(contents, record["owner_id"], observations)


def missing_required_checks(requirement, item):
    checks = requirement["required_checks"]
    results = item.get("check_results")
    if results is not None:
        indexes = [c["requirement_index"] for c in results]
        if len(set(indexes)) != len(indexes) or any(i < 0 or i >= len(checks) for i in indexes):
            return checks, "invalid_check_result_indexes"
        completed = {c["requirement_index"] for c in results if c["execution_state"] == "completed"}
        return [c for i, c in enumerate(checks) if i not in completed], "per_check_linked_observations"
    if requirement.get("require_check_evidence"):
        return checks, "check_evidence_missing"
    indexes = item.get("checked_requirement_indexes")
    if indexes is not None:
        if any(i < 0 or i >= len(checks) for i in indexes):
            return checks, "invalid_check_indexes"
        return [c for i, c in enumerate(checks) if i not in indexes], "indexed_declaration"
    # A legacy single-outcome scope already has an exact target/criterion/scope
    # identity. Nonempty checked prose need not copy its one assignment label.
    if len(checks) == 1 and item["coverage"]["checked"]:
        return [], "legacy_single_scope_declaration"
    # Preserve explicit old multi-action evidence; do not guess equivalence or
    # promote one broad statement to completion of every assigned action.
    return [c for c in checks if c not in item["coverage"]["checked"]], "legacy_multi_check_labels"


def reconcile(contents, task_id):
    contract = assignment(contents, task_id)
    from .supervision_plugins import selected_plugin
    plugin = selected_plugin(contract)
    requirements = contract.get("review_requirements", [])
    snapshot_ref = contract.get("review_snapshot_ref")
    history = (contents.list_objects("ReviewSupersession"), contents.list_objects("ReviewReuse"))
    records = contents.list_objects("ReviewRecord")
    task_contracts = {t["ref"]["id"]: t["payload"].get("review_requirements", [])
                      for t in contents.list_objects("DelegatedTask")}
    result = []
    for requirement in requirements:
        candidates = []
        for record in records:
            # Reuse already reviewed unaffected work only when it explicitly applies.
            for index, item in enumerate(record["payload"]["items"]):
                original_item = item
                if contract.get('review_interface_profile') == 'review-interfaces-v4' and record['task_id'] != task_id:
                    mapped = any(r['payload'].get('target_task_ref', {}).get('id') == task_id
                        and r['payload']['review_ref'] == record['ref']
                        and {'old_item_index': index, 'new_scope_id': requirement['scope_id']} in r['payload'].get('item_mappings', [])
                        for r in history[1])
                    if not mapped:
                        continue
                    item = {**item, 'scope_id':requirement['scope_id']}
                if review_identity(item) != review_identity(requirement):
                    continue
                original = next((r for r in task_contracts.get(record["task_id"], []) if
                    review_identity(r) == review_identity(original_item)), None)
                if original is None and requirement.get("content_check_scopes"):
                    # A legacy declaration with no assignment cannot establish
                    # compatibility with a newly explicit body extent.
                    continue
                if original and (original["required_checks"] != requirement["required_checks"] or
                        any(original.get(k, []) != requirement.get(k, []) for k in ("required_read_refs", "material_refs", "required_materials", "source_ranges", "content_check_scopes", "artifact_check_scopes", "reference_page_bindings")) or
                        original.get("presentation_reference_ref") != requirement.get("presentation_reference_ref")):
                    # Same scope name with changed obligations cannot reuse the
                    # old checklist indexes as evidence of new work.
                    continue
                withdrawn, applicable, _ = contents.review_item_state(record, snapshot_ref, index, history)
                if withdrawn or not applicable or contents.changed_review_sources(record["payload"], item):
                    continue
                candidates.append((record, index, item))
        # A later explicit partial result must not disappear behind an earlier pass.
        if not candidates:
            result.append({"requirement": requirement, "state": "missing", "reason": "No applicable saved review item."})
            continue
        record, index, item = candidates[-1]
        reads = review_read_refs(contents, record)
        evidence_requirement = {**requirement, "require_check_evidence": requirement.get("require_check_evidence", False) or bool(plugin and plugin.requires_check_evidence)}
        missing_checks, check_basis = missing_required_checks(evidence_requirement, item)
        missing_reads = [r for r in requirement["required_read_refs"] if encode(r) not in reads]
        if required_source_spans([requirement]):
            # The new extent contract is per check, not a union of other checks'
            # reads. Reused records retain the original reviewer's receipts.
            missing_materials = []
            with contents.store.connect() as db:
                for n in range(len(requirement['required_checks'])):
                    check = next((c for c in item.get('check_results') or [] if c['requirement_index'] == n), None)
                    cited, extents = set(), []
                    for index in (check or {}).get('observation_indexes', []):
                        row = db.execute('SELECT actor_id,data FROM content_observations WHERE id=?',
                                         (item['observations'][index]['receipt_id'],)).fetchone()
                        if row and row[0] == record['owner_id']:
                            observation = json.loads(row[1])
                            cited.update(material_refs_in_observation(observation))
                            extents.extend(source_extents_in_observation(contents, record['owner_id'], observation))
                    missing_materials += missing_required_materials(requirement, cited, {n}, extents)
        else:
            missing_materials = missing_required_materials(requirement, reads)
        missing_artifacts = [r for r in requirement["artifact_refs"] if r not in item.get("artifact_refs", [])]
        artifact_coverage_gaps = []
        scoped_artifact_assignment = False
        from .handoff_release import manifest as bound_manifest
        if requirement["assessment_kind"] != "content" and bound_manifest(contents.store).get('review_execution_mode') == "bounded-tool-v1":
            from .artifact_review import artifact_gaps
            with contents.store.connect() as db:
                observations = [json.loads(row[0]) for obs in item["observations"]
                    if (row := db.execute("SELECT data FROM content_observations WHERE id=?", (obs["receipt_id"],)).fetchone())]
            extents = requirement.get('artifact_check_scopes', [])
            scoped_artifact_assignment = ({s['requirement_index'] for s in extents}
                == set(range(len(requirement['required_checks']))))
            if scoped_artifact_assignment:
                # Reconcile the assigned question extents, not an unassigned
                # whole render. Whole-item publication remains unchanged.
                for extent in extents:
                    check = next((c for c in item.get('check_results') or []
                        if c['requirement_index']==extent['requirement_index']), None)
                    cited=[]
                    if check:
                        with contents.store.connect() as db:
                            for n in check['observation_indexes']:
                                receipt=item['observations'][n]['receipt_id']
                                row=db.execute('SELECT data FROM content_observations WHERE id=?',(receipt,)).fetchone()
                                if row: cited.append(json.loads(row[0]))
                    artifact_coverage_gaps += artifact_gaps(contents,requirement,item,cited,check_scope=extent)
            else:
                artifact_coverage_gaps = artifact_gaps(contents, requirement, item, observations)
        completed_declaration = (item["execution_state"] == "completed" and item["verdict"] is not None)
        completed_extents = (scoped_artifact_assignment and item['execution_state'] in {'running','completed'}
            and bool(item.get('check_results')) and not missing_checks)
        complete = ((completed_declaration or completed_extents)
                    and not item["coverage"]["unchecked"] and not item["coverage"]["blocked"]
                    and not missing_checks and not missing_reads and not missing_artifacts and not missing_materials and not artifact_coverage_gaps)
        result.append({"requirement": requirement, "state": "completed" if complete else "incomplete",
            "review_ref": record["ref"], "item_index": index, "verdict": item["verdict"],
            "reason": item["reason"], "missing_checks": missing_checks, "missing_read_refs": missing_reads,
            "check_accounting_basis": check_basis,
            "completion_extent": "declared_artifact_subchecks" if scoped_artifact_assignment else "whole_item",
            "whole_item_execution_state": item['execution_state'],
            "missing_required_materials": missing_materials,
            "missing_artifact_refs": missing_artifacts,
            "artifact_coverage_gaps": artifact_coverage_gaps,
            "unchecked": item["coverage"]["unchecked"], "blocked": item["coverage"]["blocked"],
            "check_results": item.get("check_results"),
            "outside_assignment_notes": item.get("outside_assignment_notes", []),
            "evidence_level": "linked_observations" if check_basis == "per_check_linked_observations" else "declarations_and_access_receipts"})
    return {"task_id": task_id, "snapshot_ref": snapshot_ref, "requirements": result,
            "supervision_plugin": plugin.id if plugin else None,
            "remaining": [r for r in result if r["state"] != "completed"],
            "execution_complete": bool(requirements) and all(r["state"] == "completed" for r in result),
            "semantic_coverage_verified": False,
            "limitation": "Saved declarations and actual whole-body read receipts only. Completion is not correctness, full commissioned coverage or engineering approval."}


def save_reconciliation(contents, actor, call_id, outcome):
    def save(db):
        db.execute("INSERT OR REPLACE INTO state VALUES (?,?)",
                   ("content_task_supervision:" + actor.task_id, encode(outcome)))
        return outcome
    return contents.operation(actor, "task-reconcile:" + call_id + ":" + digest(outcome), outcome, save)


def reserve_followup(contents, actor, call_id):
    """Reserve before execution. Recovery cannot silently consume a second attempt."""
    def save(db):
        key = "content_task_followup:" + actor.task_id
        row = db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        if row:
            return {"reserved": False, "prior": json.loads(row[0])}
        value = {"call_id": call_id, "state": "reserved", "task_id": actor.task_id}
        db.execute("INSERT INTO state VALUES (?,?)", (key, encode(value)))
        return {"reserved": True, **value}
    # A fresh operation can observe a prior reservation; the task key enforces
    # the durable once-only limit even when the original receipt is replayed.
    response = contents.operation(actor, "task-followup-reserve:" + str(uuid4()),
                                  {"task_id": actor.task_id, "call_id": call_id}, save)
    value = response["result"]
    return value["reserved"]


def task_status(contents, offset=0, limit=20):
    if offset < 0 or not 1 <= limit <= 100:
        raise ActionRejected("INVALID_PAGE")
    tasks = [r for r in contents.list_objects("DelegatedTask") if r["payload"].get("review_requirements")]
    page = tasks[offset:offset + limit]
    return {"tasks": [{"task_ref": t["ref"], "goal": t["payload"]["goal"],
                      **({'review_commission_basis':t['payload']['review_commission_basis'],
                          'review_interface_profile':'review-interfaces-v4'} if t['payload'].get('review_commission_basis') else {}),
                      **reconcile(contents, t["ref"]["id"]),
                      "followup": contents.store.get("content_task_followup:" + t["ref"]["id"])} for t in page],
            "total": len(tasks), "next_offset": offset + limit if offset + limit < len(tasks) else None}


def obligation_coverage(contents, snapshot_ref):
    """Expose independent outcomes and actual assigned scopes; never infer full coverage."""
    snap = contents.read(snapshot_ref)
    if snap["ref"]["type"] != "DocumentSnapshot":
        raise ActionRejected("SNAPSHOT_REQUIRED")
    tasks = [t for t in contents.list_objects("DelegatedTask")
             if t["payload"].get("review_snapshot_ref") == snapshot_ref]
    criteria = []
    bases = {t['payload']['review_commission_basis']['digest']: t['payload']['review_commission_basis']
             for t in tasks if t['payload'].get('review_commission_basis')}
    refs = {encode(r):r for r in snap['payload']['criteria_refs']}
    for basis in bases.values():
        refs.update({encode(r):r for r in basis['criterion_refs']})
    for ref in refs.values():
        criterion = contents.read(ref)
        scopes = [{"task_ref": t["ref"], "requirement": r}
                  for t in tasks for r in t["payload"].get("review_requirements", []) if r["criterion_ref"] == ref]
        criteria.append({"criterion": criterion,
                         "requirements": [contents.read(r) for r in criterion["payload"]["requirement_refs"]],
                         "assigned_scopes": scopes, "assignment_present": bool(scopes)})
    return {"snapshot_ref": snapshot_ref, "criteria": criteria,
            **({'commission_bases':list(bases.values()), 'semantic_coverage_verified':False} if bases else {}),
            "criteria_without_assignment": [c["criterion"]["ref"] for c in criteria if not c["assignment_present"]],
            "semantic_coverage_verified": False,
            "limitation": "Assigned scopes are not proof that every independent outcome is covered or substantively checked. Compare outcomes and actual checks; scoped rechecks do not close other commissioned omissions."}


def batch_needs_review_decision(messages, call):
    """A queued layout cannot incorporate another task's not-yet-returned result."""
    from langchain_core.messages import AIMessage
    if call["args"].get("subagent_type") != "layout":
        return False
    for message in reversed(messages):
        if isinstance(message, AIMessage) and any(c["id"] == call["id"] for c in message.tool_calls):
            return any(c["name"] == "task" and c["args"].get("subagent_type") == "reviewer"
                       and c["args"].get("review_snapshot_ref") in (None, call["args"].get("layout_snapshot_ref"))
                       for c in message.tool_calls)
    return False


async def supervised_return(contents, actor, call, invoke):
    """One native delegated invocation plus at most one task-local completion follow-up.

    An exception is not an incomplete semantic return and is never retried here.
    The reservation survives failure/cancellation; an uncertain attempt stays visible.
    """
    from langchain_core.messages import ToolMessage
    from langgraph.types import Command
    contract = assignment(contents, actor.task_id)
    if not contract.get("review_requirements"):
        return await invoke(call)
    prior = contents.store.get("content_task_followup:" + actor.task_id)
    if prior and prior["call_id"] == call["id"]:
        # Native checkpoint replay after a cancellation/unknown return must not
        # start either delegated invocation again. Native trace + saved objects
        # retain the evidence; report the reservation rather than guessing effects.
        return ToolMessage(encode({"task_supervision": reconcile(contents, actor.task_id), "followup": prior,
            "execution_replayed": False, "note": "Prior completion follow-up was already reserved; inspect saved results. No automatic retry."}),
            tool_call_id=call["id"], name="task")
    if prior and reconcile(contents, actor.task_id)["remaining"]:
        raise ActionRejected("COMPLETION_FOLLOWUP_EXHAUSTED: Preserve incomplete requirements and reasons; no further completion request for this task.")
    existing = reconcile(contents, actor.task_id)
    if existing["execution_complete"]:
        return ToolMessage(encode({"task_supervision": existing, "reused_existing_evidence": True,
            "note": "All assigned exact scopes already have applicable completed evidence. Verdicts and human-pending conclusions are retained; no duplicate reviewer invocation."}),
            tool_call_id=call["id"], name="task")
    result = await invoke(call)
    outcome = reconcile(contents, actor.task_id)
    save_reconciliation(contents, actor, call["id"], outcome)
    if outcome["remaining"] and reserve_followup(contents, actor, call["id"]):
        followup = {**call, "args": {**call["args"], "description":
            "Completion follow-up for the same saved task. Check only the incomplete requirements below; "
            "retain applicable completed work and genuine human-pending conclusions. "
            "Do not change content or broaden the assignment. If still incomplete, save the true "
            "execution/coverage and reasons; this supervisor will not request another completion follow-up.\n" +
            encode({"task_id": actor.task_id, "snapshot_ref": outcome["snapshot_ref"], "remaining": outcome["remaining"]})}}
        result = await invoke(followup)
        contents.store.set("content_task_followup:" + actor.task_id,
                           {"call_id": call["id"], "task_id": actor.task_id, "state": "returned"})
        outcome = reconcile(contents, actor.task_id)
        save_reconciliation(contents, actor, call["id"], outcome)
    outcome["followup"] = contents.store.get("content_task_followup:" + actor.task_id)
    notice = "\nTask supervision (execution bookkeeping, not acceptance):\n" + encode(outcome)
    def annotate(message):
        if isinstance(message, ToolMessage):
            content = message.content if isinstance(message.content, str) else encode(message.content)
            return message.model_copy(update={"content": content + notice})
        return message
    if isinstance(result, Command) and isinstance(result.update, dict):
        return Command(graph=result.graph, goto=result.goto, resume=result.resume,
                       update={**result.update, "messages": [annotate(m) for m in result.update.get("messages", [])]})
    return annotate(result)
