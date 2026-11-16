"""One scoped semantic revision: qualifiers, with immutable body preservation."""
from copy import deepcopy
from typing import Literal

from pydantic import Field

from .content_models import Contract, ContentNode, Ref
from .content_store import ContentStore
from .errors import ActionForbidden
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
    refs = [r.model_dump() for r in spec.targets]
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
        db.execute('SELECT version FROM content_heads WHERE type=? AND id=?',
                          (ref['type'], ref['id'])).fetchone()


def compose_revision(packet, deltas, schema=ContentNode):
    """Rebuild from exact archived inputs, shared by production and verification."""
    revision = packet['revision']
    bases = {encode(item['object']['ref']): item['object']
             for item in packet['evidence'] if item['kind'] == 'saved_object'}
    payloads = []
    for target, delta in zip(revision['targets'], deltas):
        base = bases.get(encode(target['ref']))
        payload = deepcopy(base['payload'])
        payload['qualifiers'] = QualifierOutput.model_validate(delta).qualifiers
        payloads.append(schema.model_validate(payload).model_dump())
    return payloads


def check_adoption(stored, index, previous_ref):
    revision = stored.get('revision')
    if revision is None:
        return
    revision['targets'][index]['ref']
