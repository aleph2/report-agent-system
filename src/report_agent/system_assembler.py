"""Trusted, deterministic assembly of frozen producer records; no model calls."""
from copy import deepcopy
import json

from .commission_plan import _confirmed, _set, _state, outside_boundary
from .content_models import ContentNode, Ref, refs_in
from .errors import ActionForbidden, ActionRejected
from .store import digest

CONTRACT = 'system-assembler-v1'


def _key(ref):
    return Ref.model_validate(ref).key()


def _closure(cs, db, refs):
    found, logical, pending = {}, {}, list(refs)
    while pending:
        ref = pending.pop()
        key = _key(ref)
        identity = key[:2]
        if identity in logical and logical[identity] != key:
            raise ActionRejected('MIXED_LOGICAL_VERSIONS: ' + str(identity))
        logical[identity] = key
        if key in found:
            continue
        found[key] = ref
        pending.extend(r.model_dump() for r in refs_in(cs._read(db, ref)['payload']))
    return list(found.values())


def _prepare(cs, db, actor, source_snapshot_ref, prose_bindings, assessment_refs, issue_bindings, *, current=False):
    issue_bindings = deepcopy(issue_bindings)
    if actor.role != 'coordinator':
        raise ActionForbidden('FORBIDDEN: system assembly requires coordinator')
    plan, decision = _confirmed(cs, db)
    if plan['owner_id'] != actor.id:
        raise ActionForbidden('FORBIDDEN: assembly commission owner')
    if current:
        seeds = [plan['ref'], decision['ref'], *assessment_refs,
                 *[r for refs in prose_bindings.values() for r in refs]]
        for ref in assessment_refs:
            receipt = _state(db, 'assessment_receipt:' + digest(ref))
            if receipt:
                seeds.extend(receipt['refs'].values())
        members = _closure(cs, db, seeds)
        source = {'payload': {'refs': members, 'manifest_digest': digest(sorted(members, key=_key)),
            'commission_plan_ref': plan['ref'], 'commission_confirmation_ref': decision['ref']},
            'root_payload': {'kind': 'report', 'body': {'text': plan['payload'].get('report_title') or '报告'},
                             'qualifiers': {}, 'citations': [], 'claim_kind': 'structure'}}
    else:
        if source_snapshot_ref is None:
            raise ActionRejected('ASSEMBLY_SOURCE_SNAPSHOT_REQUIRED')
        source = cs._read(db, source_snapshot_ref)
        if source_snapshot_ref['type'] != 'DocumentSnapshot':
            raise ActionRejected('ASSEMBLY_SOURCE_SNAPSHOT_REQUIRED')
        if (source['payload'].get('commission_plan_ref') != plan['ref'] or
                source['payload'].get('commission_confirmation_ref') != decision['ref']):
            raise ActionRejected('ASSEMBLY_FROZEN_CONFIRMATION_MISMATCH')
    records = {_key(r): cs._read(db, r) for r in source['payload']['refs']}
    sections = {s['section_id']: s for s in plan['payload']['sections']}
    if len(sections) != len(plan['payload']['sections']):
        raise ActionRejected('ASSEMBLY_DUPLICATE_PLANNED_SECTION')
    problems = []
    def problem(code, **where):
        problems.append({'code': code, **where})
    if current:
        from .material_issues import MaterialIssue
        for key, raw in db.execute("SELECT key,value FROM state WHERE key>=? AND key<?",
                                  ('g6_issue_record:', 'g6_issue_record;')):
            proposal = json.loads(raw)
            issue = proposal.get('issue', {})
            if key != 'g6_issue_record:' + digest([plan['ref'], issue.get('id')]):
                continue
            node_ref = proposal.get('node_ref')
            record = records.get(_key(node_ref)) if node_ref else None
            if record is None or node_ref['type'] != 'ContentNode':
                problem('stale_issue_proposal', issue_id=issue.get('id'), ref=node_ref)
                continue
            try:
                typed = MaterialIssue.model_validate(issue).model_dump()
            except ValueError:
                problem('issue_proposal_invalid', issue_id=issue.get('id'), ref=node_ref)
                continue
            record['payload']['body'].setdefault('material_issues', []).append(typed)
    def producer(record, sid):
        task_id = record.get('task_id')
        if (not task_id or record.get('owner_id') != 'content:writer:' + task_id or
                record.get('created_by') != record.get('owner_id')):
            problem('writer_identity_invalid', ref=record['ref'], section_id=sid)
            return
        try:
            task = cs._read(db, {'type': 'DelegatedTask', 'id': task_id, 'version': 1})
        except ActionRejected:
            problem('writer_task_missing', ref=record['ref'], section_id=sid)
            return
        p = task['payload']
        if (task['owner_id'] != actor.id or p.get('delegated_by') != actor.id or
                p.get('role') != 'writer' or p.get('commission_plan_ref') != plan['ref'] or
                sid not in p.get('section_ids', [])):
            problem('writer_section_unassigned', ref=record['ref'], section_id=sid)
    selected, seen = {}, set()
    for sid, refs in prose_bindings.items():
        if sid not in sections or sections[sid]['kind'] != 'extracted' or not isinstance(refs, list):
            problem('prose_section_invalid', section_id=sid)
            continue
        selected[sid] = []
        for ref in refs:
            key = _key(ref)
            record = records.get(key)
            if key in seen:
                problem('prose_binding_duplicate', ref=ref, section_id=sid)
                continue
            seen.add(key)
            if record is None or ref['type'] != 'ContentNode':
                problem('prose_not_frozen', ref=ref, section_id=sid)
                continue
            producer(record, sid)
            node = record['payload']; body = node['body']
            if (node['kind'] != 'block' or body.get('assessment_ref') or body.get('planned_section') or
                    body.get('section_id', sid) != sid or body.get('section_heading')):
                problem('prose_node_not_section_prose', ref=ref, section_id=sid)
                continue
            expected = {_key(c['source_ref']) for c in sections[sid]['sources']}
            if not expected.intersection(_key(c['source_ref']) for c in node.get('citations', [])):
                problem('prose_planned_citation_missing', ref=ref, section_id=sid)
            from .content_layout import STRUCTURAL
            unsupported = set(node.get('qualifiers', {})) - set(STRUCTURAL) - {'source_note'}
            if unsupported:
                problem('prose_unresolved_metadata', ref=ref, section_id=sid, fields=sorted(unsupported))
            selected[sid].append(record)
    missing_prose = [sid for sid, s in sections.items() if s['kind'] == 'extracted' and sid not in selected]
    reductions = {r['object_id'] for r in decision['payload'].get('reductions', [])}
    expected_objects = {o['object_id'] for o in plan['payload']['objects']
                        if not outside_boundary(plan['payload'], o)} - reductions
    assessments = {}
    for ref in assessment_refs:
        record = records.get(_key(ref))
        if ref['type'] != 'Assessment' or record is None:
            problem('assessment_not_frozen', ref=ref)
            continue
        p = record['payload']; obj = p['object_id']
        receipt = _state(db, 'assessment_receipt:' + digest(ref))
        if p.get('commission_plan_ref') != plan['ref'] or obj not in expected_objects or obj in assessments:
            problem('assessment_binding_invalid', ref=ref, object_id=obj)
            continue
        if not receipt or receipt.get('assessment_ref') != ref:
            problem('assessment_canonical_receipt_missing', ref=ref, object_id=obj)
            continue
        generated = [receipt.get(k) for k in ('ranking_ref', 'evaluation_ref', 'level_ref', 'evidence_ref')]
        if any(r is None or _key(r) not in records for r in generated):
            problem('assessment_generated_records_not_frozen', ref=ref, object_id=obj)
            continue
        sid = records[_key(receipt['evaluation_ref'])]['payload']['body']['section_id']
        producer(record, sid)
        if sid not in sections or sections[sid]['kind'] != 'extracted':
            problem('assessment_section_invalid', ref=ref, section_id=sid)
            continue
        from .risk_scoring import validate_outcome
        validate_outcome(cs, db, plan, obj, receipt['evaluation_ref'], receipt['level_ref'], [receipt['evidence_ref']], [])
        assessments[obj] = (record, receipt, sid)
    assessments = {o['object_id']: assessments[o['object_id']] for o in plan['payload']['objects']
                   if o['object_id'] in assessments}
    missing_assessments = sorted(expected_objects - assessments.keys())
    unbound_source_nodes = []
    if not current:
        canonical_refs = {_key(r) for _, receipt, _ in assessments.values() for r in receipt['refs'].values()}
        root_key = _key(source['payload']['root_ref'])
        for key, record in records.items():
            if key[0] != 'ContentNode' or key == root_key or key in seen or key in canonical_refs:
                continue
            node = record['payload']; body = node['body']
            sid = body.get('section_id')
            if node['kind'] == 'claim':
                continue
            if sid in sections and sections[sid]['kind'] in {'fixed', 'derived'}:
                continue
            if (sid in sections and body.get('section_heading') and
                    body.get('text') in {sections[sid]['title'], sid + ' ' + sections[sid]['title']}):
                continue
            unbound_source_nodes.append(record['ref'])
    for sid, bound in selected.items():
        if not bound and not any(a[2] == sid for a in assessments.values()):
            problem('empty_extracted_section', section_id=sid)
    required = {i['id']: i for i in decision['payload'].get('required_material_issues', [])}
    full_issues = {}
    for record in records.values():
        if record['ref']['type'] != 'ContentNode':
            continue
        for issue in record['payload']['body'].get('material_issues', []):
            if not isinstance(issue, dict) or 'id' not in issue:
                problem('issue_record_invalid', ref=record['ref'])
                continue
            old = full_issues.get(issue['id'])
            without_anchor = {k: v for k, v in issue.items() if k != 'anchor'}
            if old is not None and {k: v for k, v in old.items() if k != 'anchor'} != without_anchor:
                problem('issue_record_ambiguous', issue_id=issue['id'])
            full_issues[issue['id']] = issue
    from .commission_owner_records import material_issues
    for issue in material_issues(cs, plan['payload']):
        full_issues[issue.id] = issue.model_dump()
    # Origin IDs bind deterministic locations; ambiguous plan prose never supplies a route.
    template_ids = {'template-applicability:' + p['section_id'] for s in sections.values()
                    for p in s.get('result_composition', []) if p.get('applicability_question')}
    routes = {i: {'section_id': '1.3'} for i in full_issues if i.startswith('owner:')}
    inventory_ids = set()
    for obj in plan['payload']['objects']:
        for attribute in obj['attributes']:
            issue_id = digest([plan['ref'], ['inventory', obj['object_id'], attribute['name']]])
            inventory_ids.add(issue_id)
            if issue_id not in required:
                continue
            if obj['object_id'] in assessments:
                routes[issue_id] = {'section_id': assessments[obj['object_id']][2], 'object_id': obj['object_id']}
            elif obj['object_id'] not in expected_objects:
                routes[issue_id] = {'section_id': '1.3'}
    for issue_id in required.keys() - routes.keys() - template_ids - inventory_ids:
        saved = _state(db, 'g6_issue_route:' + digest([plan['ref'], issue_id]))
        if saved is not None:
            if (saved.get('reviewed_by') != 'operator' or not saved.get('reason', '').strip() or
                    saved.get('commission_plan_ref', plan['ref']) != plan['ref']):
                problem('operator_issue_route_invalid', issue_id=issue_id)
            else:
                routes[issue_id] = {k: saved[k] for k in ('section_id', 'object_id') if k in saved}
    missing_routes = sorted(required.keys() - routes.keys() - template_ids)
    missing_required_sections = sorted({r['section_id'] for r in routes.values() if r['section_id'] not in sections})
    for issue_id, route in routes.items():
        if issue_id in issue_bindings and issue_bindings[issue_id] != route:
            problem('issue_route_conflicts_with_system', issue_id=issue_id, expected=route,
                    supplied=issue_bindings[issue_id])
        else:
            issue_bindings[issue_id] = route
    missing_records = sorted(i for i in required if i not in full_issues and i not in template_ids)
    missing_bindings = sorted(i for i in required if i not in issue_bindings and i not in template_ids)
    for issue_id, binding in issue_bindings.items():
        sid = binding.get('section_id') if isinstance(binding, dict) else None
        obj = binding.get('object_id') if isinstance(binding, dict) else None
        if (issue_id not in required and issue_id not in full_issues or sid not in sections or
                set(binding) - {'section_id', 'object_id'} or
                (obj is not None and (obj not in assessments or assessments[obj][2] != sid))):
            problem('issue_binding_invalid', issue_id=issue_id, section_id=sid, object_id=obj)
        if issue_id.startswith('owner:') and (sid != '1.3' or obj is not None):
            problem('owner_issue_requires_section_1_3', issue_id=issue_id)
        if issue_id in template_ids:
            problem('template_issue_routed_by_system', issue_id=issue_id)
    retained_issues = {i['id'] for nodes in selected.values() for record in nodes
                       for i in record['payload']['body'].get('material_issues', []) if i['id'] not in required}
    canonical_issues = {i['id'] for _, receipt, _ in assessments.values()
                       for part in ('ranking_ref', 'evaluation_ref', 'level_ref')
                       for i in cs._read(db, receipt[part])['payload']['body'].get('material_issues', [])}
    for issue_id in full_issues.keys() - retained_issues - canonical_issues - issue_bindings.keys() - template_ids:
        if issue_id not in required:
            problem('saved_issue_has_no_output_binding', issue_id=issue_id)
    for issue_id in issue_bindings.keys() & canonical_issues:
        problem('canonical_issue_anchor_cannot_be_overridden', issue_id=issue_id)
    from .material_issues import MaterialIssue
    for issue_id, issue in full_issues.items():
        try:
            MaterialIssue.model_validate(issue)
        except ValueError:
            problem('full_issue_record_invalid', issue_id=issue_id)
    immutable_issue_fields = ('id', 'kind', 'object_label', 'basis', 'sources', 'question')
    for issue_id, expected in required.items():
        actual = full_issues.get(issue_id)
        if actual is not None and any(actual.get(k) != expected[k] for k in immutable_issue_fields):
            problem('required_issue_record_mismatch', issue_id=issue_id)
    report = {'ready': not (problems or missing_prose or missing_assessments or missing_records or missing_bindings or unbound_source_nodes or missing_required_sections or missing_routes),
              'source_snapshot_ref': source_snapshot_ref, 'missing_assessments': missing_assessments,
              'missing_prose_bindings': missing_prose, 'missing_issue_records': missing_records,
              'missing_issue_bindings': missing_bindings, 'missing_required_sections': missing_required_sections,
              'unbound_source_nodes': unbound_source_nodes, 'missing_issue_routes': missing_routes, 'problems': problems}
    return report, (source, plan, decision, selected, assessments, required, full_issues, issue_bindings)


def preflight_assembly(cs, actor, *, source_snapshot_ref, prose_bindings, assessment_refs, issue_bindings):
    """Read-only input accounting; no content or operation receipt is written."""
    with cs.store.connect() as db:
        db.execute('PRAGMA query_only=ON')
        return _prepare(cs, db, actor, source_snapshot_ref, prose_bindings, assessment_refs, issue_bindings)[0]


def _execute_assembly(cs, db, actor, request, *, current=False):
    assessment_refs, issue_bindings = request['assessment_refs'], request['issue_bindings']
    report, data = _prepare(cs, db, actor, **request, current=current)
    if not report['ready']:
        raise ActionRejected('ASSEMBLY_INPUT_INCOMPLETE', diagnostic=report)
    source, plan, decision, selected, assessments, required, full_issues, issue_bindings = data
    refs, copies = [], []
    def insert(node):
        ref = cs._insert(db, actor, 'ContentNode', ContentNode.model_validate(node).model_dump(mode='json'))
        refs.append(ref)
        return ref
    def contains(parent, child, position):
        refs.append(cs._insert(db, actor, 'Relation', {'subject_ref': parent, 'object_ref': child,
            'predicate': 'contains', 'position': position, 'provenance_kind': 'adopted_during_generation'}))
    def positioned(issue):
        return {**deepcopy(issue), 'anchor': {'paragraph_index': 0, 'start': 0, 'end': None}}
    def bound_issues(sid, obj=None):
        issues = [positioned(full_issues[i]) for i, binding in issue_bindings.items()
                  if binding.get('section_id') == sid and binding.get('object_id') == obj]
        return issues
    root_payload = deepcopy(source.get('root_payload') or cs._read(db, source['payload']['root_ref'])['payload'])
    root_payload['body'].pop('material_issues', None)
    root = insert(root_payload)
    object_heads = {}
    for index, section in enumerate(plan['payload']['sections']):
        sid = section['section_id']
        heading_body = {'text': sid + ' ' + section['title'], 'section_id': sid, 'section_heading': True}
        issues = bound_issues(sid)
        if issues:
            heading_body['material_issues'] = issues
        head = insert({'kind': 'block', 'body': heading_body, 'qualifiers': {},
                       'claim_kind': 'structure', 'citations': section['sources']})
        contains(root, head, index)
        child_index = 0
        if section['kind'] in {'fixed', 'derived'}:
            from .risk_scoring import create_planned_section_in_transaction
            generated = create_planned_section_in_transaction(cs, db, actor, plan, sid,
                assessment_refs if section['kind'] == 'derived' else [], positional_anchors=True)
            refs.extend(generated['refs'].values()); contains(head, generated['node_ref'], child_index)
            continue
        for record in selected.get(sid, []):
            node = deepcopy(record['payload']); node['body']['section_id'] = sid
            retained = []
            for issue in node['body'].get('material_issues', []):
                if issue['id'] not in issue_bindings:
                    retained.append(positioned(issue))
            if retained:
                node['body']['material_issues'] = retained
            else:
                node['body'].pop('material_issues', None)
            ref = insert(node); contains(head, ref, child_index); child_index += 1
            copies.append({'source_ref': record['ref'], 'assembled_ref': ref, 'section_id': sid})
        for obj, (record, receipt, assessment_sid) in assessments.items():
            if assessment_sid != sid:
                continue
            label = next(o['label'] for o in plan['payload']['objects'] if o['object_id'] == obj)
            body = {'text': label, 'section_id': sid}
            issues = bound_issues(sid, obj)
            if issues:
                body['material_issues'] = issues
            object_head = insert({'kind': 'block', 'body': body, 'qualifiers': {},
                'claim_kind': 'structure', 'citations': section['sources']})
            contains(head, object_head, child_index); child_index += 1; object_heads[obj] = object_head
            refs.extend(receipt['refs'].values())
            for position, part in enumerate(('ranking_ref', 'evaluation_ref', 'level_ref')):
                contains(object_head, receipt[part], position)
    from .risk_scoring import validate_outcome
    outcomes = []
    for obj, (record, receipt, sid) in assessments.items():
        assessment_ref = validate_outcome(cs, db, plan, obj, receipt['evaluation_ref'], receipt['level_ref'], [receipt['evidence_ref']], [])
        object_ref = next(r for r in plan['payload']['inventory_refs']
                          if cs._read(db, r)['payload']['inventory_object']['object_id'] == obj)
        outcome = cs._insert(db, actor, 'CommissionOutcome', {'object_id': obj,
            'section_ref': object_heads[obj], 'score_ref': receipt['evaluation_ref'], 'level_ref': receipt['level_ref'],
            'basis_refs': [receipt['evidence_ref']], 'unresolved': [], 'commission_plan_ref': plan['ref'],
            'object_ref': object_ref, 'assessment_ref': assessment_ref})
        _set(db, 'commission_outcome:' + digest([plan['ref'], obj]) + ':' + digest([actor.id, root]), outcome)
        outcomes.append(outcome)
    closed = _closure(cs, db, refs)
    result = cs._freeze_in_transaction(db, actor, root, closed, [])
    snapshot = cs._read(db, result['snapshot_ref'])
    from .material_issues import rendered_issues, validate_required_issues
    records = {_key(r): cs._read(db, r) for r in snapshot['payload']['refs']}
    actual_issues = rendered_issues(records, root)
    validate_required_issues(cs, db, snapshot, records, actual_issues)
    issue_targets = {issue.id: node_ref for node_ref, issue in actual_issues}
    _set(db, 'assembly_receipt:' + digest(result['snapshot_ref']), {
        'contract': CONTRACT, 'snapshot_ref': result['snapshot_ref'], 'manifest_digest': result['manifest_digest'],
        'source_snapshot_ref': request['source_snapshot_ref'], 'source_manifest_digest': source['payload']['manifest_digest'],
        'source_kind': 'current-selections' if current else 'frozen-snapshot',
        'commission_plan_ref': plan['ref'], 'commission_confirmation_ref': decision['ref'],
        'bindings_digest': digest(request), 'resolved_issue_bindings': issue_bindings,
        'operator_issue_routes': {i: saved for i in issue_bindings
            if (saved := _state(db, 'g6_issue_route:' + digest([plan['ref'], i]))) is not None},
        'prose_copies': copies, 'assessment_refs': list(request['assessment_refs']),
        'issue_targets': issue_targets, 'outcome_refs': outcomes,
        'records_digest': digest([cs._read(db, r) for r in snapshot['payload']['refs']])})
    return {**result, 'assembly_contract': CONTRACT}


def assemble_report(cs, actor, operation_id, *, source_snapshot_ref, prose_bindings, assessment_refs, issue_bindings):
    """Build from a frozen rescue snapshot; all original records remain immutable."""
    request = dict(source_snapshot_ref=source_snapshot_ref, prose_bindings=prose_bindings,
                   assessment_refs=list(assessment_refs), issue_bindings=issue_bindings)
    return cs.operation(actor, operation_id, {'assemble_report': request},
                        lambda db: _execute_assembly(cs, db, actor, request))


def _current_selections(cs, db):
    plan, decision = _confirmed(cs, db)
    prose, assessments, bindings = {}, [], {}
    for section in plan['payload']['sections']:
        sid = section['section_id']
        if section['kind'] != 'extracted':
            continue
        selected = _state(db, 'g6_section_prose:' + digest([plan['ref'], sid]))
        if selected is not None:
            prose[sid] = selected if isinstance(selected, list) else [selected]
    for obj in plan['payload']['objects']:
        selected = _state(db, 'g6_assessment:' + digest([plan['ref'], obj['object_id']]))
        if selected is not None:
            assessments.append(selected)
    issue_ids = {i['id'] for i in decision['payload'].get('required_material_issues', [])}
    for key, raw in db.execute("SELECT key,value FROM state WHERE key>=? AND key<?",
                               ('g6_issue_record:', 'g6_issue_record;')):
        proposal = json.loads(raw)
        issue_id = proposal.get('issue', {}).get('id')
        if key == 'g6_issue_record:' + digest([plan['ref'], issue_id]):
            issue_ids.add(issue_id)
    for issue_id in sorted(issue_ids):
        selected = _state(db, 'g6_issue_binding:' + digest([plan['ref'], issue_id]))
        if selected is not None:
            bindings[issue_id] = selected
    return dict(source_snapshot_ref=None, prose_bindings=prose, assessment_refs=assessments, issue_bindings=bindings)


def _current_identity(cs, db):
    plan, _ = _confirmed(cs, db)
    proposals = []
    for key, raw in db.execute("SELECT key,value FROM state WHERE key>=? AND key<? ORDER BY key",
                              ('g6_issue_record:', 'g6_issue_record;')):
        proposal = json.loads(raw)
        if key == 'g6_issue_record:' + digest([plan['ref'], proposal.get('issue', {}).get('id')]):
            proposals.append(proposal)
    routes = [(key, json.loads(raw)) for key, raw in db.execute(
        "SELECT key,value FROM state WHERE key>=? AND key<? ORDER BY key", ('g6_issue_route:', 'g6_issue_route;'))]
    return digest([_current_selections(cs, db), proposals, routes])


def assemble_current_report(cs, actor, operation_id):
    """Next-run entry point: read exact system selections, never scan latest producer drafts."""
    return cs.operation(actor, operation_id, {'assemble_current_report': True},
        lambda db: _execute_assembly(cs, db, actor, _current_selections(cs, db), current=True),
        binding_identity=lambda db, result: _current_identity(cs, db))


def require_assembled(cs, db, snapshot, records=None):
    """Verify assembly provenance without changing legacy export behavior."""
    receipt = _state(db, 'assembly_receipt:' + digest(snapshot['ref']))
    from .section_writing import enabled as system_writing
    if receipt is None and not system_writing(cs.store):
        return None
    p = snapshot['payload']
    if (not receipt or receipt.get('contract') != CONTRACT or receipt.get('snapshot_ref') != snapshot['ref'] or
            receipt.get('manifest_digest') != p.get('manifest_digest') or
            receipt.get('commission_plan_ref') != p.get('commission_plan_ref') or
            receipt.get('commission_confirmation_ref') != p.get('commission_confirmation_ref')):
        raise ActionRejected('SYSTEM_ASSEMBLY_RECEIPT_REQUIRED_OR_INVALID')
    records = records if records is not None else {_key(r): cs._read(db, r) for r in p['refs']}
    if receipt.get('records_digest') != digest([records[_key(r)] for r in p['refs']]):
        raise ActionRejected('SYSTEM_ASSEMBLY_RECORDS_DIGEST_MISMATCH')
    decision = records.get(_key(p['commission_confirmation_ref']))
    if (not decision or decision.get('owner_id') != 'operator' or
            decision['payload'].get('approved') is not True or
            decision['payload'].get('plan_ref') != p['commission_plan_ref']):
        raise ActionRejected('SYSTEM_ASSEMBLY_CONFIRMATION_INVALID')
    from .material_issues import rendered_issues, PassageAnchor
    for node_ref, issue in rendered_issues(records, p['root_ref']):
        if isinstance(issue.anchor, PassageAnchor):
            raise ActionRejected(f'SYSTEM_ASSEMBLY_POSITION_REQUIRED: {issue.id}; node={node_ref}')
    return receipt


def record_issue_routes(cs, actor, operation_id, routes, *, note):
    """Trusted operator records locations only; no issue content or engineering decision changes."""
    if actor.id != 'operator' or actor.role != 'operator':
        raise ActionForbidden('FORBIDDEN: issue routes require trusted operator')
    if not isinstance(note, str) or not note.strip() or not isinstance(routes, dict) or not routes:
        raise ActionRejected('ASSEMBLY_OPERATOR_ROUTE_NOTE_AND_ROUTES_REQUIRED')
    def execute(db):
        plan, decision = _confirmed(cs, db)
        required = {i['id'] for i in decision['payload'].get('required_material_issues', [])}
        sections = {s['section_id'] for s in plan['payload']['sections']}
        objects = {o['object_id'] for o in plan['payload']['objects']}
        inventory = {digest([plan['ref'], ['inventory', o['object_id'], a['name']]])
                     for o in plan['payload']['objects'] for a in o['attributes']}
        for issue_id, route in routes.items():
            if (issue_id not in required or issue_id.startswith(('owner:', 'template-applicability:')) or
                    issue_id in inventory or not isinstance(route, dict) or
                    set(route) - {'section_id', 'object_id', 'reason'} or route.get('section_id') not in sections or
                    ('object_id' in route and route['object_id'] not in objects) or not route.get('reason', '').strip()):
                raise ActionRejected('ASSEMBLY_OPERATOR_ROUTE_INVALID: ' + str(issue_id))
        for issue_id, route in routes.items():
            _set(db, 'g6_issue_route:' + digest([plan['ref'], issue_id]), {
                **route, 'commission_plan_ref': plan['ref'], 'reviewed_by': 'operator', 'note': note})
        return {'commission_plan_ref': plan['ref'], 'routed_issue_ids': sorted(routes)}
    return cs.operation(actor, operation_id, {'assembly_issue_routes': routes, 'note': note}, execute,
                        binding_identity=lambda db, result: _confirmed(cs, db)[0]['ref'])
