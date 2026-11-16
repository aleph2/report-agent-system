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


def issue(workspace, actor, tool, text, materials, *, review_observation_id=None):
    """Called only by a trusted source-reading boundary with its actual result."""
    return _issue(workspace, actor, tool, text, materials,
                  review_observation_id=review_observation_id)[0]


def _issue(workspace, actor, tool, text, materials, *, review_observation_id=None, reviewer_handles=False):
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
    with workspace.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if review_observation_id is not None:
            db.execute('INSERT INTO content_observations VALUES (?,?,?)',
                       (review_observation_id, actor.id, '{}'))
            from .review_handles import assign_evidence_handle
            handle = assign_evidence_handle(db, actor.id, review_observation_id)
            if reviewer_handles:
                text = json.dumps({**json.loads(text), 'evidence_handle': handle}, ensure_ascii=False)
        sha = hashlib.sha256(text.encode('utf-8')).hexdigest()
        body_ref = digest({'owner':actor.id, 'tool':tool, 'sha256':sha})
        value = {'contract':CONTRACT, 'actor':actor.__dict__, 'tool':tool,
            'public_sha256':sha, 'body_ref':body_ref, 'materials':parts,
            'note':'Exact returned selections/observations only; no semantic verification or whole-source reading claim.'}
        if review_observation_id is not None:
            value['review_observation_id'] = review_observation_id
        receipt = digest(value)
        db.execute('INSERT OR IGNORE INTO state VALUES (?,?)',
            ('source_material:'+receipt, encode(value)))
        db.execute('INSERT OR IGNORE INTO state VALUES (?,?)',
            ('tool_observation:'+body_ref, encode({'owner':actor.id,'tool':tool,'text':text,'sha256':sha})))
        index_key = 'source_material_observation:'+body_ref
        row = db.execute('SELECT value FROM state WHERE key=?', (index_key,)).fetchone()
        refs = json.loads(row[0]) if row else []
        if receipt not in refs:
            db.execute('INSERT OR REPLACE INTO state VALUES (?,?)', (index_key,encode([*refs,receipt])))
        if review_observation_id is not None:
            public = json.loads(text)
            db.execute('UPDATE content_observations SET data=? WHERE id=? AND actor_id=?',
                (encode({
                    'native_source_material_receipt': receipt,
                    'ok': public.get('ok', True), 'status': public.get('status'),
                    'execution_state': public.get('execution_state')}), review_observation_id, actor.id))
    return public_metadata(value,receipt), text


def public_metadata(record,receipt):
    versions = {encode(ref):ref for part in record['materials'] for ref in part['source_version_refs']}
    return {'contract':CONTRACT,'receipt':receipt,'body_ref':record['body_ref'],
        **({'review_observation_receipt_id':record['review_observation_id']} if record.get('review_observation_id') else {}),
        'public_sha256':record['public_sha256'],
        'source_ids':list(dict.fromkeys(p['source_id'] for p in record['materials'])),
        'source_version_refs':list(versions.values())}


def returned(workspace, role, tool, value, materials, runtime, *, reviewer_handles=False):
    if runtime is None and not reviewer_handles:
        return value  # Direct host calls preserve the existing return contract.
    from .text_work import actor_for_tool
    actor = actor_for_tool(workspace, role)
    if reviewer_handles:
        from .review_handles import _task
        _task(ContentStore(workspace.store), actor)
    from .prompt_sources import native_reviewer
    observation_id = None
    if role == 'reviewer' and (native_reviewer(workspace.store) or reviewer_handles):
        # A server-bound native read has a real receipt usable by submit_review.
        # Allocate before hashing the final public return, avoiding a hash cycle.
        from uuid import uuid4
        observation_id = str(uuid4())
        value = {**value, 'receipt_id': observation_id}
    # Match native LangChain dict serialization exactly; artifact is not content.
    text = json.dumps(value, ensure_ascii=False)
    artifact, text = _issue(workspace, actor, tool, text, materials,
                           review_observation_id=observation_id, reviewer_handles=reviewer_handles)
    if runtime is None:
        return json.loads(text)
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


def analysis_materials(result):
    """Exact direct source inputs of this real analysis, not semantic lineage.

    Model interpretations are not original facts. Empty means no direct source
    blocks supplied to this analysis; it grants neither access nor completeness.
    """
    return [{**part, 'kind': 'model_text_interpretation',
             'analysis_operation': result['operation'],
             'limitations': [*part['limitations'],
                 'Model interpretation of these direct inputs; semantic correctness is unverified.']}
            for entry in result['evidence'] if entry['kind'] == 'source_blocks'
            for part in block_material(entry['observation'])]
