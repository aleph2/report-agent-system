"""Exact task/snapshot material context. No retrieval index or semantic judge."""
from .store import encode

MAX_STRUCTURE_NODES = 200


def review_material_context(contents, snapshot_ref, requirements, evidence, pool):
    snapshot = contents.read(snapshot_ref)
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
        task_pool = {encode(r) for r in [req['target_ref'], *req.get('required_read_refs', []),
            *req.get('material_refs', []),
            *[r for m in req.get('required_materials', []) for r in m['refs']]]}
        for extent in req.get('content_check_scopes', []):
            refs = []; stack = [extent['node_ref']]; seen = set()
            while stack:
                ref = stack.pop(); key = encode(ref)
                if key in seen: continue
                seen.add(key); refs.append(ref)
                if extent['kind']=='subtree_bodies': stack.extend(reversed(children[key]))
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
