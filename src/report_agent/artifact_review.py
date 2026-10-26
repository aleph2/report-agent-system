"""Task-bound artifact publication and actual page coverage, without a model loop."""
from .prompt_sources import load_prompt
import json

from .content_models import Ref, ReviewSubmission
from .content_store import ContentStore
from .content_tasks import bound_actor
from .errors import ActionRejected
from .output_contract import received_output
from .store import encode


def matching_requirement(requirements, item):
    from .task_supervision import review_identity
    return next((r for r in requirements if review_identity(r) == review_identity(item)), None)


def artifact_gaps(contents, requirement, item, observations, *, check_scope=None):
    """Successful cited images establish access/coverage, not visual correctness."""
    gaps = []
    reference = requirement.get('presentation_reference_ref')
    source = contents.read(reference)['payload'] if reference else None
    if source:
        current = contents.store.sources([source['source_id']])[0]
        if not current.get('current', True) or contents.source_payload(current) != source:
            return [{'reference_ref': reference, 'reason': 'presentation_reference_changed'}]
    refs = [check_scope['artifact_ref']] if check_scope else requirement['artifact_refs']
    for ref in refs:
        if ref['type'] != 'RenderArtifact':
            if (requirement['assessment_kind'] == 'export' or check_scope and check_scope['kind'] == 'export_structure') and not any(
                    o.get('export_ref') == ref and 'structure' in o and o.get('status') != 'failed'
                    and o.get('ok') is not False and o.get('execution_state') != 'blocked' for o in observations):
                gaps.append({'artifact_ref': ref, 'reason': 'missing_export_observation'})
            continue
        render = contents.read(ref)['payload']
        assets = render.get('page_assets', [])
        if not assets:
            gaps.append({'artifact_ref': ref, 'reason': 'render_pages_unavailable'})
            continue
        seen = set()
        for observation in observations:
            observed = observation.get('source', {})
            paired = observed.get('presentation_reference', {})
            if (observation.get('status') != 'observed' or not observation.get('observation')
                    or not observation.get('image_sha256') or observed.get('render_ref') != ref
                    or observed.get('export_ref') != render['export_ref']
                    or observed.get('coverage') != 'full_page_image' or observed.get('crop') is not None):
                continue
            if source and (paired.get('source_id') != source['source_id']
                    or paired.get('source_sha256') != source['file_digest']
                    or paired.get('coverage') != 'full_page_image' or paired.get('crop') is not None
                    or type(paired.get('page')) is not int or paired['page'] < 1):
                continue
            bindings = requirement.get('reference_page_bindings', [])
            if bindings:
                binding = next((b for b in bindings if b['render_ref'] == ref and b['page'] == observed.get('page')), None)
                if not binding or paired.get('page') != binding['reference_page']:
                    continue
            if type(observed.get('page')) is int and 1 <= observed['page'] <= len(assets):
                seen.add(observed['page'])
        expected = set(check_scope['pages']) if check_scope else set(range(1, len(assets) + 1))
        missing = sorted(expected - seen)
        if missing:
            gaps.append({'artifact_ref': ref, 'reason': 'missing_full_page_observations', 'pages': missing})
    return gaps


def validate_artifact_items(contents, db, requirements, data, *, skip_content=False):
    """Only this exact delegated artifact scope may publish through the new route."""
    for item_index, item in enumerate(data['items']):
        if item['assessment_kind'] == 'content':
            if skip_content:  # Native content is validated separately; preserve mixed-item positions.
                continue
            raise ActionRejected('CONTENT_JUDGMENT_REQUIRES_BOUNDED_CHECKER')
        requirement = matching_requirement(requirements, item)
        if requirement is None:
            raise ActionRejected('ARTIFACT_REVIEW_OUTSIDE_ASSIGNED_SCOPE', diagnostic={
                'reason': 'artifact_scope_identity_not_assigned',
                'parameter_path': ['review', 'items', item_index], 'scope_id': item.get('scope_id')})
        expected, provided = requirement['artifact_refs'], item['artifact_refs']
        expected_keys, provided_keys = set(map(encode, expected)), set(map(encode, provided))
        if provided_keys != expected_keys:
            raise ActionRejected('ARTIFACT_REVIEW_OUTSIDE_ASSIGNED_SCOPE', diagnostic={
                'reason': 'artifact_ref_set_mismatch', 'scope_id': requirement.get('scope_id'),
                'parameter_path': ['review', 'items', item_index, 'artifact_refs'],
                'expected_artifact_refs': expected, 'provided_artifact_refs': provided,
                'missing_artifact_refs': [r for r in expected if encode(r) not in provided_keys],
                'extra_artifact_refs': [r for r in provided if encode(r) not in expected_keys]})
        observations = []
        for obs in item['observations']:
            row = db.execute('SELECT data FROM content_observations WHERE id=?', (obs['receipt_id'],)).fetchone()
            if row:
                observations.append(json.loads(row[0]))
        if item['execution_state'] == 'completed':
            gaps = artifact_gaps(contents, requirement, item, observations)
            if gaps:
                raise ActionRejected('ARTIFACT_REVIEW_COVERAGE_INCOMPLETE: ' + encode(gaps))
        for check in item.get('check_results') or []:
            if check['execution_state'] == 'completed':
                cited = []
                for index in check['observation_indexes']:
                    receipt = item['observations'][index]['receipt_id']
                    row = db.execute('SELECT data FROM content_observations WHERE id=?', (receipt,)).fetchone()
                    if row:
                        cited.append(json.loads(row[0]))
                extent = next((s for s in requirement.get('artifact_check_scopes', [])
                    if s['requirement_index'] == check['requirement_index']), None)
                gaps = artifact_gaps(contents, requirement, item, cited, check_scope=extent)
                if gaps:
                    raise ActionRejected('ARTIFACT_CHECK_REQUIRES_LINKED_PAGE_COVERAGE: ' + encode({
                        'requirement_index': check['requirement_index'], 'artifact_coverage_gaps': gaps}))
    for check_index, check in enumerate(data['delivery_checks']):
        selected = [i for i in data['items'] if i['assessment_kind'] == check['kind']]
        allowed_refs = [r for i in selected for r in i['artifact_refs']]
        allowed = {encode(r) for r in allowed_refs}
        if not selected or not set(map(encode, check['artifact_refs'])) <= allowed:
            raise ActionRejected('DELIVERY_CHECK_OUTSIDE_ASSIGNED_ARTIFACTS', diagnostic={
                'kind': check['kind'], 'allowed_artifact_refs': allowed_refs,
                'parameter_path': ['review', 'delivery_checks', check_index, 'artifact_refs']})
        if check['execution_state'] == 'completed':
            for item in selected:
                requirement = matching_requirement(requirements, item)
                observations = []
                for obs in check['observations']:
                    row = db.execute('SELECT data FROM content_observations WHERE id=?', (obs['receipt_id'],)).fetchone()
                    if row:
                        observations.append(json.loads(row[0]))
                if artifact_gaps(contents, requirement, item, observations):
                    raise ActionRejected('DELIVERY_CHECK_COVERAGE_INCOMPLETE')


def artifact_review_tool(workspace):
    def submit_artifact_review(operation_id: str, review: ReviewSubmission,
                               delivery_export_ref: Ref | None = None) -> dict:
        """Publish only assigned export/Word layout judgments using your actual receipts.

        Content judgments must use perform_assigned_review. Completed Word layout
        scopes require full images of every page in the exact RenderArtifact and
        its assigned customer reference; crops and wrong versions do not count.
        Save partial/blocked findings truthfully when pages are missing. This does
        not require each sub-check to cover the whole report: follow the saved
        artifact_check_scopes for its exact evidence extent. Without such a scope
        a completed sub-check retains the whole-artifact rule. In check_results,
        completed requires cited observation_indexes and an empty remaining;
        unfinished checks require a remaining reason. Reference page bindings,
        when assigned, must match the actual paired page receipts. This does
        not revise artifacts, invoke a model, or grant whole-report acceptance.
        """
        from .hierarchical_tools import actor_for
        actor = bound_actor(workspace, 'reviewer', actor_for('reviewer'))
        return ContentStore(workspace.store).submit_review(actor, operation_id,
            review.model_dump(), {'mode': 'assigned-artifact-review-v1'},
            delivery_export_ref.model_dump() if delivery_export_ref else None)
    return submit_artifact_review


def bounded_artifact_review_tool(workspace, model):
    """The agent selects actual observations; a one-shot tool compares them."""
    from .evidence_analysis import analyze_evidence_packet, model_identity
    from .store import digest
    from .task_supervision import assignment, validate_requirements

    def public_result(cs, actor, snapshot, result, reused):
        # Read the exact immutable saved version for fresh and cached outcomes.
        # The execution receipt alone says nothing about the review's verdict.
        record = cs.read(result['result']['review_ref'])
        if (record['ref'] != result['result']['review_ref'] or record['ref']['type'] != 'ReviewRecord'
                or record['owner_id'] != actor.id or record['task_id'] != actor.task_id
                or record['payload']['snapshot_ref'] != snapshot
                or digest(record['payload']) != record['payload_digest']):
            raise ActionRejected('ARTIFACT_REVIEW_PUBLIC_IDENTITY_CHANGED')
        return {**result, 'reused': reused, 'review': record['payload'],
                'review_identity': {'ref': record['ref'], 'payload_digest': record['payload_digest'],
                                    'owner_id': record['owner_id'], 'task_id': record['task_id']},
                'limitation': 'Scoped saved judgments; no inferred whole-report or engineering acceptance.'}

    async def perform_assigned_artifact_review(operation_id: str, scope_ids: list[str],
            observation_receipts: list[str], delivery_export_ref: Ref | None = None) -> dict:
        """Perform independent assigned export/Word-page comparisons on exact saved
        observations. Choose relevant owned receipts and scope IDs. No agent-authored
        verdict is accepted. Actual version/page/reference/coverage guards still apply;
        incomplete observation supports partial findings only. No new vision calls,
        search, delegation, correction, publication or engineering acceptance.
        """
        from .hierarchical_tools import actor_for
        actor = bound_actor(workspace, 'reviewer', actor_for('reviewer'))
        cs = ContentStore(workspace.store)
        task = assignment(cs, actor.task_id)
        requirements = [r for r in task.get('review_requirements', []) if r['scope_id'] in scope_ids]
        if (not operation_id.strip() or not scope_ids or len(set(scope_ids)) != len(scope_ids)
                or len(requirements) != len(scope_ids) or any(r['assessment_kind'] == 'content' for r in requirements)):
            raise ActionRejected('ASSIGNED_ARTIFACT_SCOPES_REQUIRED')
        snapshot = task['review_snapshot_ref']
        validate_requirements(cs, snapshot, requirements, commission_basis=task.get('review_commission_basis'))
        observations = []
        with workspace.store.connect() as db:
            for receipt in observation_receipts:
                row = db.execute('SELECT actor_id,data FROM content_observations WHERE id=?', (receipt,)).fetchone()
                if not row or row[0] != actor.id:
                    raise ActionRejected('ARTIFACT_OBSERVATION_REQUIRES_CURRENT_TASK_RECEIPT')
                observations.append({'receipt_id': receipt, 'actual_observation': json.loads(row[1])})
        if not observations:
            raise ActionRejected('ARTIFACT_OBSERVATIONS_REQUIRED')
        from .source_use import validate_observation_sources, resolve_source_use_binding
        policy_ref = resolve_source_use_binding(workspace, actor)
        if policy_ref:
            for observation in observations:
                validate_observation_sources(workspace, actor, observation['actual_observation'])
        prompt = load_prompt('artifact-analysis')
        from .prompt_instructions import review_commission
        commission, prompt = review_commission(workspace.store, actor, prompt)
        criteria = {encode(r['criterion_ref']): cs.read(r['criterion_ref']) for r in requirements}
        inputs = {'task_id': actor.task_id, 'snapshot_ref': snapshot, 'requirements': requirements,
            'criteria': list(criteria.values()), 'commission': commission,
            'evidence': observations, 'output_schema': ReviewSubmission.model_json_schema()}
        if policy_ref:
            inputs['source_use_policy_ref'] = policy_ref
        request_hash = digest({'input': inputs, 'model': model_identity(model), 'prompt': prompt})
        key = 'artifact_text_work:' + actor.id + ':' + operation_id
        with workspace.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()
            if row:
                saved = json.loads(row[0])
                if saved['request_hash'] != request_hash:
                    raise ActionRejected('OPERATION_CONFLICT')
                if saved.get('state') == 'not_dispatched':
                    raise ActionRejected('ARTIFACT_TEXT_WORK_NOT_DISPATCHED: ' + encode({
                        'provider_outcome': 'not_dispatched', 'raw_response_received': False,
                        'usage': None, 'admission_proof': saved['admission_proof'],
                        'refusal_context': saved.get('result'),
                        'note': 'Known local refusal; no automatic retry or additional authorization.'}))
                if 'result' not in saved:
                    raise ActionRejected('ARTIFACT_TEXT_WORK_OUTCOME_UNRESOLVED: no automatic retry')
                return public_result(cs, actor, snapshot, saved['result'], True)
            db.execute('INSERT INTO state VALUES (?,?)', (key, encode({
                'request_hash': request_hash, 'state': 'reserved'})))
        raw = await analyze_evidence_packet(workspace, model, inputs, prompt,
            'assigned-artifact-text-work-v1', reserve_attempt=True,
            parent_reservation=(key, {'request_hash': request_hash}), allow_parent_readmission=False,
            owner=actor, caller_operation_id=operation_id)
        with received_output('ARTIFACT_REVIEW_OUTPUT_CONTRACT_INVALID', raw['operation']):
            review = ReviewSubmission.model_validate_json(raw['analysis']).model_dump()
        if review['snapshot_ref'] != snapshot or len(review['items']) != len(requirements):
            raise ActionRejected('ARTIFACT_TEXT_WORK_CHANGED_SCOPE: raw response preserved')
        matched = [matching_requirement(requirements, i) for i in review['items']]
        if any(r is None for r in matched) or len({r['scope_id'] for r in matched}) != len(scope_ids):
            raise ActionRejected('ARTIFACT_TEXT_WORK_CHANGED_SCOPE: raw response preserved')
        supplied = set(observation_receipts)
        for item in [*review['items'], *review['delivery_checks']]:
            if any(o['receipt_id'] not in supplied for o in item['observations']):
                raise ActionRejected('ARTIFACT_TEXT_WORK_INVENTED_OBSERVATION: raw response preserved')
        with workspace.store.connect() as db:
            validate_artifact_items(cs, db, requirements, review)
        result = cs.submit_review(actor, operation_id, review,
            {'mode': 'bounded-artifact-text-work-v1', 'operation': raw['operation'], 'model': raw['model']},
            delivery_export_ref.model_dump() if delivery_export_ref else None)
        workspace.store.set(key, {'request_hash': request_hash, 'result': result})
        return public_result(cs, actor, snapshot, result, False)
    return perform_assigned_artifact_review
