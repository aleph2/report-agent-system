"""Exact task/snapshot material context. No retrieval index or semantic judge."""
from .store import encode
from .errors import ActionRejected

MAX_STRUCTURE_NODES = 200


def validate_native_submission(contents, db, actor, task, requirements, data):
    """Mechanical task/extent checks for native saves, not a content judge.

    The target is an identity anchor. Only explicitly declared material/body
    extents require read evidence; do not demand a decorative target citation.
    """
    from .task_supervision import review_identity, material_refs_in_observation
    import json
    if actor.role != 'reviewer' or not task or not requirements:
        raise ActionRejected('NATIVE_REVIEW_REQUIRES_ASSIGNED_REQUIREMENTS')
    if task.get('review_snapshot_ref') != data['snapshot_ref']:
        raise ActionRejected('REVIEW_SNAPSHOT_OUTSIDE_ASSIGNMENT')
    if task.get('review_interface_profile') == 'review-interfaces-v4' and any(
            ref not in [r['criterion_ref'] for r in requirements] for ref in data['criteria_refs']):
        raise ActionRejected('REVIEW_CRITERION_OUTSIDE_ASSIGNED_SCOPE')
    snapshot = contents.read(data['snapshot_ref'])
    _, children = snapshot_body_topology(contents, snapshot)
    for item_index, item in enumerate(data['items']):
        if task.get('review_interface_profile') == 'review-interfaces-v4' and not item.get('scope_id'):
            raise ActionRejected('V4_ASSIGNED_SCOPE_ID_REQUIRED')
        requirement = next((r for r in requirements if review_identity(r) == review_identity(item)), None)
        if requirement is None:
            raise ActionRejected('REVIEW_ITEM_OUTSIDE_ASSIGNMENT')
        checks = item.get('check_results') or []
        allowed = set(range(len(requirement['required_checks'])))
        indexes = {c['requirement_index'] for c in checks}
        if not indexes <= allowed or not set(item.get('checked_requirement_indexes') or []) <= allowed:
            raise ActionRejected('REVIEW_CHECK_INDEX_OUTSIDE_ASSIGNMENT')
        if item['execution_state'] == 'completed' and (indexes != allowed or any(
                c['execution_state'] != 'completed' for c in checks)):
            raise ActionRejected('COMPLETED_REVIEW_REQUIRES_EVERY_ASSIGNED_CHECK')
        by_check = {c['requirement_index']:c for c in checks}
        observed = {}
        for index, observation in enumerate(item['observations']):
            row = db.execute('SELECT actor_id,data FROM content_observations WHERE id=?',
                (observation['receipt_id'],)).fetchone()
            if row and row[0] == actor.id:
                observed[index] = json.loads(row[1])
        for finding_index, finding in enumerate(item['findings']):
            index = finding.get('requirement_index')
            if index not in allowed:
                raise ActionRejected('REVIEW_FINDING_OUTSIDE_ASSIGNED_CHECK', diagnostic={
                    'scope_id': requirement['scope_id'], 'allowed_requirement_indexes': sorted(allowed),
                    'parameter_path': ['review', 'items', item_index, 'findings', finding_index, 'requirement_index']})
            linked = finding.get('observation_indexes')
            if not linked or index not in by_check or not set(linked) <= set(by_check[index]['observation_indexes']):
                raise ActionRejected('REVIEW_FINDING_OUTSIDE_CHECK_OBSERVATIONS')
            evidence = [observed[i] for i in linked if i in observed]
            structures = [v['snapshot_structure'] for v in evidence if 'snapshot_structure' in v]
            if finding['basis_kind'] == 'supplied_content' and structures and len(structures) == len(evidence):
                raise ActionRejected('STRUCTURE_METADATA_IS_NOT_CONTENT_EVIDENCE')
            if finding['basis_kind'] == 'snapshot_structure':
                if not structures or any(v.get('snapshot_ref') != data['snapshot_ref'] or
                        v.get('manifest_digest') != snapshot['payload']['manifest_digest'] for v in structures):
                    raise ActionRejected('STRUCTURE_FINDING_REQUIRES_SNAPSHOT_EVIDENCE')
                if finding['locator_state'] == 'absent' and finding['finding_type'] == 'confirmed_defect':
                    # Exact paged index coverage, not a new semantic completeness
                    # marker. Metadata coverage still does not prove missing prose.
                    nodes = [r for r in snapshot['payload']['refs'] if r['type'] == 'ContentNode']
                    covered = set()
                    for page in structures:
                        offset, returned = page['offset'], page['returned_refs']
                        if (page['total_nodes'] != len(nodes) or returned != nodes[offset:offset+len(returned)]):
                            raise ActionRejected('STRUCTURE_INDEX_OUTSIDE_SNAPSHOT')
                        covered.update(range(offset, offset+len(returned)))
                    scoped_nodes = (body_extent_refs(children, {'node_ref':item['target_ref'], 'kind':'subtree_bodies'})
                                    if item['target_ref']['type'] == 'ContentNode' else nodes)
                    required_positions = {i for i, ref in enumerate(nodes) if ref in scoped_nodes}
                    if not required_positions <= covered:
                        raise ActionRejected('INCOMPLETE_INVENTORY_CANNOT_ESTABLISH_ABSENCE')
        for check_index, check in enumerate(checks):
            if check['execution_state'] != 'completed':
                continue
            cited = set()
            for index in check['observation_indexes']:
                receipt = item['observations'][index]['receipt_id']
                row = db.execute('SELECT actor_id,data FROM content_observations WHERE id=?', (receipt,)).fetchone()
                if row and row[0] == actor.id:
                    cited.update(material_refs_in_observation(json.loads(row[1])))
            required = [ref for extent in requirement.get('content_check_scopes', [])
                        if extent['requirement_index'] == check['requirement_index']
                        for ref in body_extent_refs(children, extent)]
            missing = [ref for ref in required if encode(ref) not in cited]
            if missing:
                raise ActionRejected('COMPLETED_CHECK_MISSING_BODY_EXTENT', diagnostic={
                    'reason': 'missing_linked_body_observations',
                    'scope_id': requirement['scope_id'], 'requirement_index': check['requirement_index'],
                    'parameter_path': ['review', 'items', item_index, 'check_results', check_index, 'observation_indexes'],
                    'missing_body_refs': missing})


def snapshot_body_topology(contents, snapshot):
    """Exact frozen contains graph; no body reads, selection or grants."""
    members = snapshot['payload']['refs']
    nodes = [r for r in members if r['type']=='ContentNode']
    children = {encode(r): [] for r in nodes}
    relations = []
    for ref in members:
        if ref['type'] != 'Relation': continue
        p = contents.read(ref)['payload']
        if p['predicate'] != 'contains': continue
        relations.append((p['subject_ref'], p['object_ref'], p['position']))
    for parent, child, position in sorted(relations, key=lambda r:r[2]):
        children[encode(parent)].append(child)
    return nodes, children


def body_extent_refs(children, extent):
    """Expand only the caller's explicit extent, without inventory display limits."""
    refs, stack, seen = [], [extent['node_ref']], set()
    while stack:
        ref = stack.pop(); key = encode(ref)
        if key in seen: continue
        seen.add(key); refs.append(ref)
        if extent['kind'] == 'subtree_bodies':
            stack.extend(reversed(children[key]))
    return refs


def scope_body_pool(requirement):
    """Eligibility is scope-local and does not establish a supplied/read body."""
    return {encode(r) for r in [requirement['target_ref'],
        *requirement.get('required_read_refs', []), *requirement.get('material_refs', []),
        *[r for m in requirement.get('required_materials', []) for r in m['refs']]]
        if r['type'] == 'ContentNode'}


def review_material_context(contents, snapshot_ref, requirements, evidence, pool):
    snapshot = contents.read(snapshot_ref)
    nodes, children = snapshot_body_topology(contents, snapshot)
    supplied = set(); partial = set()
    for entry in evidence:
        obj = entry.get('object') or {}
        ref = obj.get('ref') or (entry.get('selection') or {}).get('ref')
        if not ref or ref['type'] != 'ContentNode': continue
        if obj or entry.get('complete_body_selection'):
            supplied.add(encode(ref))
        else: partial.add(encode(ref))
    # Metadata may reveal existing nodes, but never reads unassigned bodies into
    # the model or turns inventory into a body-inspection receipt.
    inventory = []
    for ref in nodes[:MAX_STRUCTURE_NODES]:
        key = encode(ref); node = contents.read(ref)['payload']
        row = {'ref':ref, 'kind':node['kind'], 'children':children[key],
            'body_input':'full' if key in supplied else 'partial' if key in partial else 'not_supplied',
            'eligible_for_body_selection':key in pool}
        if key in pool:
            heading = node['body'].get('text','').split('\n',1)[0]
            row.update(heading_preview=heading[:160], heading_preview_complete=len(heading)<=160)
        inventory.append(row)
    extents = []; gaps = []
    for req in requirements:
        task_pool = scope_body_pool(req)
        for extent in req.get('content_check_scopes', []):
            refs = body_extent_refs(children, extent)
            missing = [r for r in refs if encode(r) not in supplied]
            entry = {'scope_id':req['scope_id'], **extent, 'required_body_refs':refs,
                'missing_full_body_refs':missing,
                'unbound_body_refs':[r for r in refs if encode(r) not in task_pool]}
            extents.append(entry)
            if missing or entry['unbound_body_refs']: gaps.append(entry)
    return {'snapshot_ref':snapshot_ref, 'root_ref':snapshot['payload']['root_ref'],
        'manifest_digest':snapshot['payload']['manifest_digest'], 'total_nodes':len(nodes),
        'inventory':inventory, 'inventory_complete':len(nodes)<=MAX_STRUCTURE_NODES,
        'next_offset':MAX_STRUCTURE_NODES if len(nodes)>MAX_STRUCTURE_NODES else None,
        'body_extents':extents, 'missing_body_extents':gaps,
        'limitation':'Exact frozen snapshot metadata; heading previews are labels, not full-body observations. A body absent from this input is not absent from the report. A node body does not establish coverage of its contains-linked subtree; children may hold substantive text/tables. Incomplete inventory cannot establish absence. Task pool membership does not establish that a body was supplied or checked. No semantic verdict is supplied by this context.'}
