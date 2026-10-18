"""Host-managed direct requirements synced before native dispatch, no agent loop."""
import json
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .errors import ActionRejected
from .prompt_instructions import KEY, InstructionInput, InstructionRef, configure_report, release_instruction, save_instruction
from .store import digest

DEFAULT_PACK = Path(__file__).resolve().parents[2] / '.operator' / 'instructions.json'

class OperatorPack(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    policy: str
    id: str = Field(min_length=1)
    version: int = Field(ge=1)
    authority: str
    provenance: str = Field(min_length=1)
    instructions: list[InstructionInput]
    active: list[InstructionRef]
    history: dict[str, list[InstructionInput]] = Field(default_factory=dict)

    @model_validator(mode='after')
    def confirmed(self):
        if self.policy != 'confirmed-operator-instructions-v1' or self.authority != 'direct_user_confirmed':
            raise ValueError('Only directly confirmed operator requirements are supported')
        if len({v.id for v in self.instructions}) != len(self.instructions) or len({v.id for v in self.active}) != len(self.active):
            raise ValueError('Duplicate operator instruction ID')
        if any(ref.id not in {v.id for v in self.instructions} for ref in self.active):
            raise ValueError('Active instruction missing from pack')
        if any(v.scope not in {'report_category', 'report'} for v in self.instructions):
            raise ValueError('Shared pack supports explicit category/report applicability only')
        for ident, values in self.history.items():
            if ident not in {v.id for v in self.instructions} or any(v.id != ident for v in values):
                raise ValueError('History must belong to a declared instruction')
        return self

def sync_operator_instructions(store):
    """Caller holds project run lock. Idempotent exact-version import before models.

    Pack versions preserve registry history and active-version CAS. Interrupted
    imports recover exact saved records; they never overwrite unrelated rules.
    """
    manifest = store.manifest
    declared = manifest.get('operator_instruction_pack')
    if not declared and not manifest.get('report_category') and not store.get('operator_instruction_binding'):
        return None
    path = Path(declared) if declared else DEFAULT_PACK
    if not path.is_absolute(): path = store.root / path
    path = path.resolve()
    if not path.exists():
        if declared or manifest.get('report_category') or store.get('operator_instruction_binding'):
            raise ActionRejected('OPERATOR_INSTRUCTION_PACK_MISSING')
        return None
    pack = OperatorPack.model_validate(json.loads(path.read_text(encoding='utf-8-sig')))
    fingerprint = digest(pack.model_dump())
    prior = store.get('operator_instruction_binding')
    if prior:
        if prior['pack_id'] != pack.id or prior['path'] != str(path):
            raise ActionRejected('OPERATOR_PACK_BINDING_IMMUTABLE')
        if pack.version < prior['version'] or (pack.version == prior['version'] and fingerprint != prior['digest']):
            raise ActionRejected('OPERATOR_PACK_VERSION_CONFLICT')
    category = manifest.get('report_category')
    report_id = manifest.get('report_id') or str(store.root)
    policy = store.get('context_policy', manifest.get('context_policy'))
    if policy not in {None, 'stateful-tools-v1'}:
        raise ActionRejected('OPERATOR_PACK_REQUIRES_STATEFUL_TASK_CONTEXT')
    if not policy: store.set('context_policy', 'stateful-tools-v1')
    binding = {'policy': 'scoped-instructions-v1', 'report_id': report_id}
    if category is not None: binding['report_category'] = category
    if store.get('prompt_instruction_config') != binding:
        configure_report(store, report_id, report_category=category)
    registry = store.get(KEY, {'versions': [], 'active': {}})
    desired = {r.id: r.version for r in pack.active}
    owned = set(prior['managed_ids']) if prior else set()
    pending=store.get('operator_instruction_sync_intent')
    if pending:
        if pending['digest'] != fingerprint or pending['path'] != str(path) or pending['pack_id'] != pack.id:
            raise ActionRejected('OPERATOR_PACK_SYNC_OUTCOME_UNRESOLVED')
        owned.update(pending['managed_ids'])
    payloads = {p.id: p.model_dump() for p in pack.instructions}
    sequences = {ident:[v.model_dump() for v in pack.history.get(ident,[])] + [payload]
                 for ident,payload in payloads.items()}
    # Preflight all changes. Saving/releasing below is restart-idempotent.
    for ident, payload in payloads.items():
        history = [r for r in registry['versions'] if r['ref']['id'] == ident]
        latest = history[-1] if history else None
        requested = desired.get(ident)
        versions = sequences[ident]
        for record in history:
            version = record['ref']['version']
            if version > len(versions) or InstructionInput.model_validate(record['payload']).model_dump() != versions[version-1]:
                raise ActionRejected('OPERATOR_INSTRUCTION_HISTORY_CONFLICT')
        if requested is None:
            if registry['active'].get(ident) is not None and ident not in owned:
                raise ActionRejected('INACTIVE_OPERATOR_INSTRUCTION_UNMANAGED_ACTIVE')
        elif requested != len(versions):
            raise ActionRejected('OPERATOR_INSTRUCTION_HISTORY_REQUIRED')
        if latest:
            if len(versions) > latest['ref']['version'] and ident not in owned:
                raise ActionRejected('OPERATOR_PACK_CANNOT_REVISE_UNMANAGED_INSTRUCTION')
        active = registry['active'].get(ident)
        expected = prior['active'].get(ident) if prior else None
        if active not in {expected, requested}:
            raise ActionRejected('OPERATOR_INSTRUCTION_ACTIVE_CONFLICT')
    for ident in owned - set(desired):
        if registry['active'].get(ident) not in {None, (prior or {'active':{}})['active'].get(ident)}:
            raise ActionRejected('OPERATOR_WITHDRAWAL_ACTIVE_CONFLICT')
    store.set('operator_instruction_sync_intent',{'digest':fingerprint,'path':str(path),
        'pack_id':pack.id,'managed_ids':sorted(owned | set(payloads))})
    for ident, payload in payloads.items():
        history = [r for r in registry['versions'] if r['ref']['id'] == ident]
        current = history[-1]['ref']['version'] if history else 0
        for version,past in enumerate(sequences[ident],1):
            if version <= current: continue
            record=save_instruction(store, past, expected_version=version-1)
            if record['ref']['version'] != version:
                raise ActionRejected('OPERATOR_DUPLICATE_REVISION_PAYLOAD')
        active = store.get(KEY)['active'].get(ident)
        if ident in desired and active != desired[ident]:
            release_instruction(store, ident, desired[ident], expected_active=active,
                reason='Direct confirmed operator pack '+pack.id+' v'+str(pack.version))
    for ident in owned - set(desired):
        active = store.get(KEY)['active'].get(ident)
        if active is not None:
            release_instruction(store, ident, None, expected_active=active,
                reason='Explicit withdrawal from direct operator pack '+pack.id)
    receipt = {'pack_id': pack.id, 'version': pack.version, 'digest': fingerprint,
        'path': str(path), 'authority': pack.authority, 'provenance': pack.provenance,
        'report_binding': binding, 'active': desired, 'managed_ids': sorted(owned | set(payloads)),
        'note': 'Loaded direct requirements, not learner promotion, provider receipt or semantic acceptance.'}
    if receipt != prior:
        store.set('operator_instruction_binding', receipt)
        store.event('operator_instructions_synced', receipt)
    store.set('operator_instruction_sync_intent',None)
    return receipt
