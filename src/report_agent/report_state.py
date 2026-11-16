"""Immutable case records of generation, not claims or approval authority."""
import json

from . import legacy_state as legacy
from .content_models import Ref
from .errors import ActionRejected
from .store import Store, digest, encode

PRIVATE_TYPES = frozenset({'SectionProvenance', 'AssemblyProvenance', 'RescueProjection',
                           'ProseSelection', 'OutcomeSelection', 'DeliverySelection', 'FinalReviewSelection'})


def _head(db, kind, key):
    from .content_store import ContentStore
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='content_heads'").fetchone():
        return None
    row = db.execute('SELECT version FROM content_heads WHERE type=? AND id=?', (kind, key)).fetchone()
    return ContentStore._read(db, dict(type=kind, id=key, version=row[0])) if row else None


def _get(storage, kind, key, default=None):
    if isinstance(storage, Store):
        with storage.connect() as db:
            return _get(db, kind, key, default)
    record = _head(storage, kind, key)
    return record['payload'] if record else default


def _save(storage, kind, key, value, *, advance=False, actor=None):
    from .content_store import Actor, ContentStore
    if isinstance(storage, Store):
        with storage.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            return _save(db, kind, key, value, advance=advance, actor=actor)
    ContentStore.ensure_schema(storage)
    previous = _head(storage, kind, key)
    if previous and previous['payload'] == value:
        return previous['ref']
    if previous and not advance:
        raise ActionRejected('REPORT_PROVENANCE_IMMUTABLE: ' + key)
    owner = actor or Actor('system:report-assembler', 'service', 'report-generation')
    return ContentStore._insert(storage, owner, kind, value, id=key,
        version=previous['ref']['version'] + 1 if previous else 1,
        previous_ref=previous['ref'] if previous else None)


def _key(ref):
    return encode(Ref.model_validate(ref).model_dump())


def native(storage, kind, ref):
    return bool(ref and _get(storage, kind, _key(ref)) is not None)


def record_section(storage, ref, value):
    return _save(storage, 'SectionProvenance', _key(ref), value)


def planned_section(storage, ref):
    if not ref:
        return None
    return _get(storage, 'SectionProvenance', _key(ref)) or legacy.get_planned_section_receipt(storage, digest(ref))


def record_assembly(storage, ref, value):
    return _save(storage, 'AssemblyProvenance', _key(ref), value)


def assembly(storage, ref):
    return _get(storage, 'AssemblyProvenance', _key(ref)) or legacy.get_assembly_receipt(storage, digest(ref))


def record_projection(storage, ref, value):
    return _save(storage, 'RescueProjection', _key(ref), value)


def projection(storage, ref):
    return _get(storage, 'RescueProjection', _key(ref)) or legacy.get_rescue_projection(storage, digest(ref))


def select_prose(storage, scope, ref, *, actor):
    return _save(storage, 'ProseSelection', scope, ref, advance=True, actor=actor)


def prose_ref(storage, scope, default=None):
    ref = _get(storage, 'ProseSelection', scope)
    if ref is not None:
        return ref
    plan, section, obj = json.loads(scope.removeprefix('prose:'))
    return legacy.historical_prose(storage, plan, section, obj, default)


def select_outcome(storage, plan, obj, slot, ref, *, actor):
    return _save(storage, 'OutcomeSelection', encode([plan, obj, slot]),
        dict(plan_ref=plan, object_id=obj, outcome_ref=ref), advance=True, actor=actor)


def outcomes(db, plan, obj):
    from .content_store import ContentStore
    refs = []
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='content_heads'").fetchone():
        for key, version in db.execute("SELECT id,version FROM content_heads WHERE type='OutcomeSelection'"):
            row = ContentStore._read(db, dict(type='OutcomeSelection', id=key, version=version))['payload']
            if row['plan_ref'] == plan and row['object_id'] == obj:
                refs.append(row['outcome_ref'])
    return refs or [json.loads(raw) for raw, in legacy.iter_commission_outcomes(db, digest([plan, obj]))]


_SELECTION_MISSING = object()


def selected_delivery(storage, default=None):
    value = _get(storage, 'DeliverySelection', 'selected', _SELECTION_MISSING)
    return legacy.get_historical_content_delivery(storage, default) if value is _SELECTION_MISSING else value


def selected_final_review(storage, default=None):
    value = _get(storage, 'FinalReviewSelection', 'selected', _SELECTION_MISSING)
    return legacy.get_historical_content_final_review(storage, default) if value is _SELECTION_MISSING else value


def set_content_delivery(storage, value, *, actor=None):
    from .content_store import Actor
    return _save(storage, 'DeliverySelection', 'selected', value, advance=True,
                 actor=actor or Actor('host', 'host', 'delivery-selection'))


def set_content_final_review(storage, value, *, actor=None):
    from .content_store import Actor
    return _save(storage, 'FinalReviewSelection', 'selected', value, advance=True,
                 actor=actor or Actor('host', 'host', 'review-selection'))


def assertion_refs(db, refs, plan=None, decision=None):
    """Freeze explicit calculator inputs and the actual plan authority, without guessing factual support."""
    from .content_store import ContentStore
    from .plan_authority import _actions, _entries
    selected = set()
    for ref in refs:
        payload = ContentStore._read(db, ref)['payload']
        if payload.get('derived_assertion_id'):
            selected.add(payload['derived_assertion_id'])
    proposals, acts = _entries(_actions(db))
    selected.update(body['id'] for ref, body, _ in proposals if ref == plan)
    selected.update(body['id'] for ref, body, _ in acts if ref == decision)
    return sorted(selected)


def require_current(storage, snapshot_ref):
    from .assertions.launch import Commission
    from .plan_authority import _directory
    saved = _get(storage, 'AssemblyProvenance', _key(snapshot_ref))
    ids = saved.get('assertion_refs', []) if saved else []
    states = Commission.current_references(_directory(storage), ids)
    invalid = [key for key in ids if not states.get(key, {}).get('active')
               or states[key]['stale'] or states[key]['challenged']]
    if invalid:
        raise ActionRejected('REPORT_INPUT_ASSERTION_NOT_CURRENT: ' + ', '.join(invalid))
