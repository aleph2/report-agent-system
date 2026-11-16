"""One compiled material representation for preflight, producer and adoption."""
from dataclasses import dataclass
import json

from .content_inputs import SourceRef
from .content_store import ContentStore
from .store import digest, encode

@dataclass(frozen=True)
class PreparedMaterial:
    encoded: str
    allowed_refs: frozenset[str]

    @property
    def evidence(self):
        return json.loads(self.encoded)

    @property
    def encoded_characters(self):
        return len(self.encoded)

    @property
    def evidence_digest(self):
        return digest(self.evidence)




def compile_material(workspace, actor, evidence, source_version_refs=(), source_materials=()):
    """No new reading: version bindings must match actual origin-issued material."""
    cs = ContentStore(workspace.store)
    from .source_use import validate_source_versions
    validate_source_versions(workspace, actor, source_refs=source_version_refs, materials=source_materials)
    result = list(evidence)
    for raw in source_version_refs:
        ref = SourceRef.model_validate(raw).model_dump()
        obj = cs.read(ref)
        source = workspace.store.sources([obj['payload']['source_id']])[0]
        payload = cs.source_payload(source)
        matching = [part for part in source_materials
            if part['source_id']==source['id'] and part['source_payload_digest']==digest(payload)]
        result.append({'kind':'source_version_binding','object':{
            **obj, 'payload':{k:v for k,v in payload.items() if k!='content'},
            'content_digest':digest(payload['content']), 'content_supplied':'matching selected source material only'},
            'material_kinds':sorted({part['kind'] for part in matching}),
            'note':'Version binding only; no additional source text, complete reading or truth established.'})
    return PreparedMaterial(encode(result), frozenset(encode(item['object']['ref']) for item in result
        if item['kind'] in {'saved_object','source_version_binding'}))
