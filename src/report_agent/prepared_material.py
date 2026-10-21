"""One compiled material representation for preflight, producer and adoption."""
from dataclasses import dataclass
import json

from .content_inputs import SourceRef
from .content_store import ContentStore
from .errors import ActionRejected
from .store import digest, encode

MAX_EVIDENCE_CHARACTERS = 64000

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

    def require_bounded_size(self, code='TEXT_WORK_SELECT_SMALLER_LOCATED_EVIDENCE', dependencies=None):
        """One size calculation for the exact encoded material; never trims it."""
        evidence = self.evidence
        if self.encoded_characters <= MAX_EVIDENCE_CHARACTERS:
            return
        parts = []
        for index, item in enumerate(evidence):
            detail = {'index': index, 'kind': item['kind'], 'encoded_characters': len(encode(item))}
            if item['kind'] == 'source_blocks':
                detail['selection'] = item['selection']
                observation = item['observation']
                detail['text_blocks_characters'] = len(encode(observation.get('blocks', [])))
                detail['table_supplements_characters'] = len(encode(observation.get('source_table_views', [])))
            if dependencies is not None:
                detail['dependencies'] = dependencies.get(index, [])
            parts.append(detail)
        diagnostic = {'encoded_characters': self.encoded_characters,
            'maximum_encoded_characters': MAX_EVIDENCE_CHARACTERS,
            'item_count': len(evidence), 'items': parts[:20], 'unlisted_items': max(0, len(parts)-20),
            'size_unit': 'Unicode characters of the complete encoded evidence JSON, including separators',
            'producer_invoked': False,
            'note': 'The limit is encoded evidence size, not selection count. Whole-page table supplements can dominate size. Choose relevant located material or your own supported public observations; do not treat unread or unselected information as absent. No evidence was automatically removed.'}
        raise ActionRejected(code + ': ' + encode(diagnostic))

    def require_source(self):
        if not any(json.loads(ref)['type']=='SourceArtifact' for ref in self.allowed_refs):
            raise ActionRejected('TEXT_WORK_EVIDENCE_SOURCE_POOL_EMPTY: select actual source material '
                'and bind its existing SourceArtifact with input_refs or source_version_refs; '
                'objective text and source IDs alone are not legal source refs. Producer not invoked.')

    def check_returned_refs(self, payload):
        if any(encode(ref) not in self.allowed_refs
               for ref in [*payload['source_refs'], *payload['input_refs']]):
            raise ActionRejected('TEXT_WORK_RETURNED_UNSUPPLIED_REFERENCE: raw response preserved')


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
        if obj['payload'] != payload:
            raise ActionRejected('TEXT_WORK_SOURCE_VERSION_NOT_CURRENT_FOR_SELECTION')
        matching = [part for part in source_materials
            if part['source_id']==source['id'] and part['source_payload_digest']==digest(payload)]
        if not matching:
            raise ActionRejected('TEXT_WORK_SOURCE_BINDING_REQUIRES_MATCHING_MATERIAL: '
                                 + encode({'ref':ref,'source_id':source['id'],'producer_invoked':False}))
        result.append({'kind':'source_version_binding','object':{
            **obj, 'payload':{k:v for k,v in payload.items() if k!='content'},
            'content_digest':digest(payload['content']), 'content_supplied':'matching selected source material only'},
            'material_kinds':sorted({part['kind'] for part in matching}),
            'note':'Version binding only; no additional source text, complete reading or truth established.'})
    return PreparedMaterial(encode(result), frozenset(encode(item['object']['ref']) for item in result
        if item['kind'] in {'saved_object','source_version_binding'}))
