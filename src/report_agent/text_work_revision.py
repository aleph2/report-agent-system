"""One scoped semantic revision: qualifiers, with immutable body preservation."""
from copy import deepcopy
from typing import Literal

from pydantic import Field

from .content_models import Contract, ContentNode, Ref
from .content_store import ContentStore
from .errors import ActionForbidden, ActionRejected
from .store import digest, encode


class RevisionTarget(Ref):
    type: Literal['ContentNode']


class ContentRevision(Contract):
    scope: Literal['qualifiers']
    targets: list[RevisionTarget] = Field(min_length=1, max_length=32,
        description='Ordered exact owned ContentNode versions. Only qualifiers may change; each output index retains this target identity, body, kind and claim_kind. Old report text is draft data, not source truth.')


class QualifierOutput(Contract):
    qualifiers: ContentNode.model_fields['qualifiers'].annotation = Field(
        description=ContentNode.model_fields['qualifiers'].description)


def bind_revision(workspace, actor, revision, object_type, output_count):
    spec = ContentRevision.model_validate(revision)
    if object_type != 'ContentNode' or output_count != len(spec.targets):
        raise ActionRejected('TEXT_WORK_REVISION_TYPE_OR_COUNT_MISMATCH')
    refs = [r.model_dump() for r in spec.targets]
    if len({(r['type'], r['id']) for r in refs}) != len(refs):
        raise ActionRejected('TEXT_WORK_REVISION_DUPLICATE_TARGET')
    targets = []
    for ref in refs:
        obj = ContentStore(workspace.store).read(ref)
        if obj['owner_id'] != actor.id:
            raise ActionForbidden('FORBIDDEN: revision target belongs to another owner')
        targets.append({'ref': ref, 'payload_digest': digest(obj['payload'])})
    return {'scope': spec.scope, 'targets': targets}


def check_current_targets(db, revision):
    for target in revision['targets']:
        ref = target['ref']
        head = db.execute('SELECT version FROM content_heads WHERE type=? AND id=?',
                          (ref['type'], ref['id'])).fetchone()
        if not head or head[0] != ref['version']:
            raise ActionRejected('TEXT_WORK_REVISION_VERSION_CONFLICT')


def compose_revision(packet, deltas, schema=ContentNode):
    """Rebuild from exact archived inputs, shared by production and verification."""
    revision = packet['revision']
    if revision['scope'] != 'qualifiers' or len(revision['targets']) != len(deltas):
        raise ActionRejected('TEXT_WORK_REVISION_BINDING_INVALID')
    bases = {encode(item['object']['ref']): item['object']
             for item in packet['evidence'] if item['kind'] == 'saved_object'}
    payloads = []
    for target, delta in zip(revision['targets'], deltas):
        base = bases.get(encode(target['ref']))
        if (not base or base['owner_id'] != packet['actor']['id']
                or digest(base['payload']) != target['payload_digest']):
            raise ActionRejected('TEXT_WORK_REVISION_BASE_CHANGED')
        payload = deepcopy(base['payload'])
        payload['qualifiers'] = QualifierOutput.model_validate(delta).qualifiers
        payloads.append(schema.model_validate(payload).model_dump())
    return payloads


def check_adoption(stored, index, previous_ref):
    revision = stored.get('revision')
    if revision is None:
        return
    target = revision['targets'][index]['ref']
    if previous_ref is None or Ref.model_validate(previous_ref).model_dump() != target:
        raise ActionRejected('TEXT_WORK_REVISION_REQUIRES_EXACT_PREVIOUS_REF')
