"""Origin-issued source observations, carried by native ToolMessage artifacts.

Receipts prove which public bytes were returned, not semantic truth or reading
completeness. They never capture a new business source version or choose work.
"""
import hashlib
import json

from langchain_core.messages import ToolMessage

from .content_store import ContentStore
from .errors import ActionForbidden, ActionRejected
from .store import digest, encode

CONTRACT = 'source-material-v1'


def issue(workspace, actor, tool, text, materials):
    """Called only by a trusted source-reading boundary with its actual result."""
    sha = hashlib.sha256(text.encode('utf-8')).hexdigest()
    body_ref = digest({'owner':actor.id, 'tool':tool, 'sha256':sha})
    parts = []
    for material in materials:
        source = workspace.store.sources([material['source_id']])[0]
        payload = ContentStore.source_payload(source)
        with workspace.store.connect() as db:
            has_objects = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='content_heads'").fetchone()
            rows = db.execute("SELECT v.data FROM content_heads h JOIN content_versions v USING(type,id,version) "
                "WHERE h.type='SourceArtifact' AND json_extract(v.data,'$.payload.source_id')=?",
                (source['id'],)).fetchall() if has_objects else []
        versions = [obj['ref'] for obj in (json.loads(row[0]) for row in rows) if obj['payload']==payload]
        parts.append({**material, 'source_payload_digest':digest(payload), 'source_version_refs':versions,
            'file_digest':payload['file_digest'], 'text_digest':digest(source['content']),
            'parser_identity':source.get('parser', source.get('extraction_method')),
            'source_coverage':source['coverage'], 'source_limitations':source.get('limitations', [])})
    value = {'contract':CONTRACT, 'actor':actor.__dict__, 'tool':tool,
        'public_sha256':sha, 'body_ref':body_ref, 'materials':parts,
        'note':'Exact returned selections/observations only; no semantic verification or whole-source reading claim.'}
    receipt = digest(value)
    with workspace.store.connect() as db:
        db.execute('INSERT OR IGNORE INTO state VALUES (?,?)',
            ('source_material:'+receipt, encode(value)))
        db.execute('INSERT OR IGNORE INTO state VALUES (?,?)',
            ('tool_observation:'+body_ref, encode({'owner':actor.id,'tool':tool,'text':text,'sha256':sha})))
        index_key = 'source_material_observation:'+body_ref
        row = db.execute('SELECT value FROM state WHERE key=?', (index_key,)).fetchone()
        refs = json.loads(row[0]) if row else []
        if receipt not in refs:
            db.execute('INSERT OR REPLACE INTO state VALUES (?,?)', (index_key,encode([*refs,receipt])))
    return public_metadata(value,receipt)


def public_metadata(record,receipt):
    versions = {encode(ref):ref for part in record['materials'] for ref in part['source_version_refs']}
    return {'contract':CONTRACT,'receipt':receipt,'body_ref':record['body_ref'],
        'public_sha256':record['public_sha256'],
        'source_ids':list(dict.fromkeys(p['source_id'] for p in record['materials'])),
        'source_version_refs':list(versions.values())}


def returned(workspace, role, tool, value, materials, runtime):
    if runtime is None:
        return value  # Direct host calls preserve the existing return contract.
    from .text_work import actor_for_tool
    # Match native LangChain dict serialization exactly; artifact is not content.
    text = json.dumps(value, ensure_ascii=False)
    artifact = issue(workspace, actor_for_tool(workspace, role), tool, text, materials)
    return ToolMessage(text, name=tool, tool_call_id=runtime.tool_call_id,
                       artifact={'source_material':artifact})


def verify(workspace, actor, ref, text, tool):
    record = workspace.store.get('source_material:'+ref)
    if not record or digest(record) != ref or record.get('contract') != CONTRACT:
        raise ActionRejected('SOURCE_MATERIAL_RECEIPT_INVALID')
    if record['actor'] != actor.__dict__:
        raise ActionForbidden('FORBIDDEN: source material belongs to another task')
    sha = hashlib.sha256(text.encode('utf-8')).hexdigest()
    body_ref = digest({'owner':actor.id,'tool':tool,'sha256':sha})
    if (record['tool'] != tool or record['public_sha256'] != sha or record['body_ref'] != body_ref):
        raise ActionRejected('SOURCE_MATERIAL_PUBLIC_RETURN_CHANGED')
    original = workspace.store.get('tool_observation:'+body_ref)
    if original != {'owner':actor.id,'tool':tool,'text':text,'sha256':sha}:
        raise ActionRejected('SOURCE_MATERIAL_ORIGINAL_CHANGED')
    return record


def owned_materials(workspace, actor, observation_ref, text, tool):
    refs = workspace.store.get('source_material_observation:'+observation_ref)
    if refs is None:
        return None  # Explicit legacy adapter owns historical shape parsing.
    return [part for ref in refs for part in verify(workspace,actor,ref,text,tool)['materials']]


def block_material(page):
    """Called at the actual block-reading boundary, including table supplements."""
    blocks = page['blocks']
    return [] if not blocks else [{'source_id':page['source']['id'], 'kind':'frozen_source_selection',
        'selection':{'units':'zero-based text blocks','ordinals':[b['ordinal'] for b in blocks],
                     'locators':[b['locator'] for b in blocks]},
        'selected_value_digest':digest(blocks),
        'supplement_digest':digest(page.get('source_table_views', [])),
        'coverage':{'total_blocks':page['total_blocks'],'next_offset':page['next_offset'],
                    'complete_frozen_text_selection':page['offset']==0 and page['next_offset'] is None},
        'limitations':['Mechanical table supplements can cover whole pages; no semantic verification.']}]


def representation_identity(workspace, actor, evidence):
    """Conservative same-source/range identity, independent of table expansion.

    This is an admission association, never a new producer packet or claim that
    the views contain identical information. Other selected inputs stay exact.
    Historical shapes belong only to the existing explicit legacy adapter.
    """
    values = []
    recognized = False
    for item in evidence:
        if item['kind'] == 'source_version_binding':
            continue
        parts = None
        if item['kind'] == 'source_blocks':
            from .source_material_legacy import frozen_read_materials
            parts = frozen_read_materials(workspace, item['observation'])
        elif item['kind'] == 'public_tool_return' and item['tool'] == 'read_source_page':
            parts = owned_materials(workspace, actor, item['observation_ref'], item['text'], item['tool'])
            if parts is None:
                from .source_material_legacy import frozen_read_identity
                record = workspace.store.get('tool_observation:'+item['observation_ref'])
                if record and record.get('text') == item['text'] and record.get('sha256') == item['sha256']:
                    parts = frozen_read_identity(workspace, actor, item['observation_ref'], record)
        if parts and all(p['kind']=='frozen_source_selection' for p in parts):
            recognized = True
            values.extend({'kind':'same_selected_frozen_source', **{k:p[k] for k in
                ('source_id','source_payload_digest','selection','selected_value_digest')}} for p in parts)
        elif item['kind'] == 'public_tool_return':
            values.append({k:item[k] for k in ('kind','tool','sha256','text')})
        else:
            values.append(item)
    return digest(sorted({encode(v) for v in values})) if recognized else None
