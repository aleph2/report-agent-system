"""Immutable pre-run owner authority, separate from proposals and plan approval."""
from . import plan_inputs
from . import legacy_state as legacy
from . import plan_authority
from copy import deepcopy
from hashlib import sha256
from typing import Literal
from pydantic import Field, ValidationError
from .content_models import Contract, SourceCitation, InventoryObject, Ref
from .errors import ActionRejected
from .store import digest, encode
from .commission_plan import _validate_sources, _citations, SourceSubstitution

KEY = legacy.COMMISSION_OWNER_RECORDS_KEY


def refuse(section, field, item, reason):
    section = section or 'plan'
    raise ActionRejected('OWNER_RECORD_CONTRACT: ' + str(section) + '/' + field + '/' + item + ': ' + reason,
                         diagnostic={'fields': [{'section_id': section, 'field': field, 'item_id': item, 'reason': reason}]})


class OpenFact(Contract):
    id: str = Field(min_length=1)
    kind: Literal['conflict', 'unclear', 'missing']
    object_label: str = Field(min_length=1)
    basis: str = Field(min_length=1)
    sources: list[SourceCitation] = Field(min_length=1)
    adopted_value: str = Field(min_length=1)
    question: str = Field(min_length=1)
    affects_level: bool = Field(strict=True)


class OwnerRecord(Contract):
    id: str = Field(min_length=1)
    kind: Literal['scope_exclusion', 'object_fact', 'withdrawal', 'substitution_authorization', 'indicators']
    target: str = Field(min_length=1)
    value: dict
    reason: str = Field(min_length=1, pattern=r'\S')
    text: str = Field(min_length=1)
    evidence_sha256: str = Field(pattern='^[0-9a-f]{64}$')
    open_facts: list[OpenFact] = Field(default_factory=list)


class Document(Contract):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    section_ids: list[str] = Field(min_length=1)


class Substitution(SourceSubstitution):
    document_id: str = Field(min_length=1)
    section_id: str = Field(min_length=1)


class OwnerFile(Contract):
    contract: Literal['owner-records-v1']
    records: list[OwnerRecord]
    documents: list[Document] = Field(default_factory=list)
    substitutions: list[Substitution] = Field(default_factory=list)
    objects: list[InventoryObject] = Field(default_factory=list)


def install_owner_records(cs, bundle, source_refs):
    """Trusted host API only. Resolve portable source hashes against enrolled inputs."""
    sources = {}
    for ref in source_refs:
        if ref['type'] != 'SourceArtifact':
            refuse(None, 'source_refs', ref['id'], 'source artifact required')
        file_hash = cs.read(ref)['payload']['file_digest']
        sources.setdefault(file_hash, {})[Ref.model_validate(ref).key()] = ref
    def bind(value):
        if isinstance(value, dict):
            if 'source_hash' in value:
                choices = sources.get(value['source_hash'], {})
                if len(choices) != 1:
                    refuse(None, 'source_hash', value['source_hash'], 'missing or ambiguous source')
                value = {k: v for k, v in value.items() if k != 'source_hash'} | {'source_ref': next(iter(choices.values()))}
            return {k: bind(v) for k, v in value.items()}
        return [bind(v) for v in value] if isinstance(value, list) else value
    bundle = bind(bundle)
    try:
        bundle = OwnerFile.model_validate(bundle).model_dump(mode='json')
    except ValidationError as error:
        issue = error.errors(include_input=False, include_url=False)[0]
        item = bundle
        for part in issue['loc'][:-1]:
            try:
                item = item[part]
            except (KeyError, IndexError, TypeError):
                break
        refuse(item.get('section_id') if isinstance(item, dict) else None,
               '.'.join(map(str, issue['loc'])), str(item.get('id', item.get('document_id', 'unknown'))) if isinstance(item, dict) else 'unknown', issue['msg'])
    documents = {d['id']: d for d in bundle['documents']}
    if len(documents) != len(bundle['documents']):
        refuse(None, 'documents', 'duplicate', 'document IDs must be unique')
    ids, facts = set(), set()
    for record in bundle['records']:
        if record['id'] in ids or sha256(record['text'].encode()).hexdigest() != record['evidence_sha256']:
            refuse(None, 'records', record['id'], 'duplicate ID or altered evidence')
        ids.add(record['id'])
        if record['kind'] == 'withdrawal' and (record['target'] not in documents or record['value'] != {'withdrawn': True}):
            refuse(None, 'withdrawal', record['id'], 'registered document and explicit withdrawal required')
        for fact in record['open_facts']:
            if fact['id'] in facts:
                refuse(None, 'open_facts', fact['id'], 'duplicate ID')
            facts.add(fact['id'])
    for sub in bundle['substitutions']:
        if sub['section_id'] not in documents.get(sub['document_id'], {}).get('section_ids', []):
            refuse(sub['section_id'], 'substitutions', sub['document_id'], 'document not registered for section')
    for record in bundle['records']:
        if record['kind'] == 'substitution_authorization':
            sections = record['value'].get('section_ids', [])
            if not sections or any(not any(s['document_id'] == record['target'] and s['section_id'] == sid
                                          for s in bundle['substitutions']) for sid in sections):
                refuse(None, 'substitution_authorization', record['id'], 'exact selected substitutions required')
    allowed = {Ref.model_validate(r).key() for r in source_refs}
    for citation in _citations(bundle):
        if Ref.model_validate(citation['source_ref']).key() not in allowed:
            refuse(None, 'source_ref', citation['source_ref']['id'], 'source is not pinned for these owner records')
    pins = [{'ref': r, 'file_digest': cs.read(r)['payload']['file_digest']} for r in source_refs]
    entry = {'bundle': bundle, 'source_pins': pins}
    fingerprint = digest(entry)
    with cs.store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        previous = legacy.get_commission_owner_records(db)
        if previous:
            if previous['digest'] != fingerprint:
                refuse(None, 'registry', fingerprint, 'owner records are immutable')
            return fingerprint
        if plan_inputs.get_skeleton(db) or plan_authority.plan_ref(db) or plan_authority.decision_ref(db) or plan_inputs.get_draft(db, {}).get('revision'):
            refuse(None, 'registry', fingerprint, 'fresh preparation required')
        from .hierarchical_tools import actor_for
        _validate_sources(cs, db, actor_for('coordinator'), bundle)
        legacy.set_commission_owner_records(db, {**entry, 'digest': fingerprint})
        db.execute('INSERT INTO events(kind,data) VALUES (?,?)', ('owner_records_installed', encode({'digest': fingerprint, 'approved': False})))
    return fingerprint


def _registry(cs, db):
    record = legacy.get_commission_owner_records(db)
    if record:
        if digest({k: record[k] for k in ('bundle', 'source_pins')}) != record['digest']:
            refuse(None, 'registry', record['digest'], 'registry changed')
        for pin in record['source_pins']:
            if cs._read(db, pin['ref'])['payload']['file_digest'] != pin['file_digest']:
                refuse(None, 'source_pins', pin['ref']['id'], 'source changed')
    return record


def _documents(bundle, section_id, skeleton=None):
    withdrawals = {r['target']: r['id'] for r in bundle['records'] if r['kind'] == 'withdrawal'}
    return [dict(id=d['id'], name=d['name'], section_id=section_id, withdrawn_by=withdrawals.get(d['id']))
            for d in (skeleton['documents'] if skeleton else bundle['documents']) if section_id in d['section_ids']]


def decorate_plan(cs, db, plan):
    record = _registry(cs, db)
    if not record:
        skeleton = plan_inputs.get_skeleton(db)
        if skeleton:
            plan = deepcopy(plan)
            for section in plan.get('sections', []):
                section['missing_documents'] = _documents({'records': [], 'documents': []}, section['section_id'], skeleton)
        return plan
    result = deepcopy(plan);bundle = record['bundle']
    result.update(owner_records_digest=record['digest'], owner_records=deepcopy(bundle['records']))
    objects = {o['object_id']: deepcopy(o) for o in bundle['objects']}
    objects.update({o['object_id']: o for o in result.get('objects', [])})
    result['objects'] = list(objects.values())
    for section in result.get('sections', []):
        sid = section['section_id']
        section['notes'] = list(dict.fromkeys([*section.get('notes', []), *section.get('pending_sources', [])]))
        section['pending_sources'] = []
        section['missing_documents'] = _documents(bundle, sid, plan_inputs.get_skeleton(db))
        # Historical string-keyed replacements are history, never authority in the new contract.
        current = {s['document_id']: s for s in section.get('source_substitutions', []) if s.get('document_id')}
        current.update({s['document_id']: {k: deepcopy(v) for k, v in s.items() if k != 'section_id'}
                        for s in bundle['substitutions'] if s['section_id'] == sid})
        section['source_substitutions'] = list(current.values())
        for sub in section['source_substitutions']:
            for citation in sub['replacement_sources']:
                if citation not in section['sources']:
                    section['sources'].append(deepcopy(citation))
    return result


def validate_owner_records(cs, db, plan):
    registry = _registry(cs, db)
    typed = plan.get('owner_records_digest') or plan.get('owner_records') or any(s.get('missing_documents') for s in plan.get('sections', []))
    if not registry:
        if typed and not (plan_inputs.get_skeleton(db) and not plan.get('owner_records_digest') and not plan.get('owner_records')):
            refuse(None, 'owner_records', 'unbound', 'trusted registry required')
        return
    bundle = registry['bundle']
    if plan.get('owner_records_digest') != registry['digest'] or plan.get('owner_records') != bundle['records']:
        refuse(None, 'owner_records', registry['digest'], 'binding mismatch')
    sections = {s['section_id']: s for s in plan.get('sections', [])}
    for sid, section in sections.items():
        if section.get('missing_documents', []) != _documents(bundle, sid, plan_inputs.get_skeleton(db)) or section.get('pending_sources'):
            refuse(sid, 'missing_documents', 'registry', 'retain ID-based documents; legacy text belongs in notes')
        for sub in section.get('source_substitutions', []):
            if not sub.get('document_id') or sub['document_id'] not in {d['id'] for d in _documents(bundle, sid, plan_inputs.get_skeleton(db))}:
                refuse(sid, 'source_substitutions', sub.get('document_id') or sub['requested_source'], 'registered document ID required')
    objects = {o['object_id']: o for o in plan.get('objects', [])}
    for record in bundle['records']:
        target, value = record['target'], record['value']
        if record['kind'] == 'scope_exclusion':
            obj = objects.get(target, {})
            if obj.get('included') is not False or any(obj.get(k) != v for k, v in value.items()):
                refuse(None, 'objects', target, 'owner scope exclusion not retained')
        elif record['kind'] == 'object_fact':
            obj = objects.get(target, {});attrs = {a['name']: a for a in obj.get('attributes', [])}
            for key, v in value.items():
                if (obj.get('included') is not v if key == 'included' else not any(x['value'] == v for x in attrs.get(key, {}).get('values', []))):
                    refuse(None, 'objects.' + key, target, 'owner-provided value not retained')
        elif record['kind'] == 'substitution_authorization':
            for sid in value['section_ids']:
                expected = [{k: v for k, v in s.items() if k != 'section_id'} for s in bundle['substitutions']
                            if s['section_id'] == sid and s['document_id'] == target]
                actual = [s for s in sections.get(sid, {}).get('source_substitutions', []) if s.get('document_id') == target]
                if actual != expected:
                    refuse(sid, 'source_substitutions', target, 'owner-selected replacement changed')
        elif record['kind'] == 'indicators' and len(plan.get('method_pack', {}).get('indicators', [])) != value.get('count'):
            refuse('3', 'indicators', record['id'], 'owner indicator count not retained')


def effective_reductions(plan, explicit):
    result = {r['object_id']: deepcopy(r) for r in explicit}
    for r in plan.get('owner_records', []):
        if r['kind'] == 'scope_exclusion':
            result[r['target']] = {'object_id': r['target'], 'reason': r['reason']}
    return list(result.values())


def material_issues(cs, plan):
    from .material_issues import MaterialIssue
    result = []
    for record in plan.get('owner_records', []):
        for fact in record.get('open_facts', []):
            sources = []
            for citation in fact['sources']:
                payload = cs.read(citation['source_ref'])['payload']
                sources.append({'document': payload['source_metadata']['title'], 'page': citation['locator']})
            result.append(MaterialIssue.model_validate({**fact, 'id': 'owner:' + record['id'] + ':' + fact['id'],
                'sources': sources, 'anchor': {'text': fact['adopted_value']}}))
    return result


def frozen_material_issues(cs, snapshot, records):
    ref = snapshot['payload'].get('commission_plan_ref')
    if not ref:
        return []
    record = records.get(Ref.model_validate(ref).key())
    if record is None:
        refuse('plan', 'snapshot', ref['id'], 'owner-record plan must be frozen')
    plan = record['payload']
    return material_issues(cs, plan)
