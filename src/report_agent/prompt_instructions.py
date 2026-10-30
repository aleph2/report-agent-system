"""Operator-managed instruction versions, delivered by existing task middleware.

No agent loop, semantic contradiction judge, learner or permission grant lives here.
System scope describes product applicability inside this isolated store; it does
not publish to every customer/project or rewrite the provider's instruction roles.
"""
from .prompt_sources import load_prompt
from collections import defaultdict
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .errors import ActionRejected
from .store import digest, encode

POLICY = "scoped-instructions-v1"
KEY = "prompt_instruction_registry"
Scope = Literal['system', 'report_category', 'project', 'report', 'assignment']
RANK = {'system': 0, 'report_category': 1, 'project': 2, 'report': 3, 'assignment': 4}


class InstructionRef(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    id: str = Field(min_length=1)
    version: int = Field(ge=1)


class InstructionInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    id: str = Field(min_length=1)
    topic: str = Field(min_length=1)
    text: str = Field(min_length=1)
    source_decision: str = Field(min_length=1)
    scope: Scope
    report_category: str | None = None
    report_id: str | None = None
    task_id: str | None = None
    roles: list[Literal['coordinator', 'writer', 'reviewer', 'layout']] = Field(default_factory=list)
    allow_override_scopes: list[Scope] = Field(default_factory=list)
    overrides: list[InstructionRef] = Field(default_factory=list)

    @model_validator(mode='after')
    def scoped(self):
        if any(not value.strip() for value in (self.id, self.topic, self.text, self.source_decision)):
            raise ValueError('Blank instruction field')
        if any(value is not None and not value.strip() for value in (self.report_category, self.report_id, self.task_id)):
            raise ValueError('Blank target identifier')
        if self.scope == 'report_category' and not self.report_category:
            raise ValueError('Report category scope requires report_category')
        if (self.scope in {'report', 'assignment'}) != bool(self.report_id):
            raise ValueError('Report/assignment scope requires report_id, other scopes forbid it')
        if (self.scope == 'assignment') != bool(self.task_id):
            raise ValueError('Only assignment scope requires task_id')
        if any(RANK[s] <= RANK[self.scope] for s in self.allow_override_scopes):
            raise ValueError('Only narrower scopes can override')
        if len(set(self.roles)) != len(self.roles) or len(set(self.allow_override_scopes)) != len(self.allow_override_scopes):
            raise ValueError('Duplicate scope or role')
        return self


def _read(db):
    row = db.execute('SELECT value FROM state WHERE key=?', (KEY,)).fetchone()
    import json
    return json.loads(row[0]) if row else {'versions': [], 'active': {}}


def _save(db, registry, kind, event):
    db.execute('INSERT OR REPLACE INTO state VALUES (?,?)', (KEY, encode(registry)))
    db.execute('INSERT INTO events(kind,data) VALUES (?,?)', (kind, encode(event)))


def _find(registry, ref):
    found = next((r for r in registry['versions'] if r['ref'] == ref), None)
    if found is None:
        raise ActionRejected('INSTRUCTION_VERSION_NOT_FOUND')
    return found


def save_instruction(store, payload, *, expected_version=0):
    """Host API only. Save a candidate; saving never activates it.

    An unchanged latest payload is deduplicated. Changed revisions require the
    exact latest version. Scope/identity migration requires a new instruction ID.
    """
    value = InstructionInput.model_validate(payload).model_dump()
    if type(expected_version) is not int or expected_version < 0:
        raise ActionRejected('INVALID_EXPECTED_INSTRUCTION_VERSION')
    store.manifest
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        registry = _read(db)
        previous = [r for r in registry['versions'] if r['ref']['id'] == value['id']]
        latest = previous[-1] if previous else None
        if latest and InstructionInput.model_validate(latest['payload']).model_dump() == value:
            return latest
        if expected_version != (latest['ref']['version'] if latest else 0):
            raise ActionRejected('INSTRUCTION_VERSION_CONFLICT')
        identity = ('id', 'topic', 'scope', 'report_category', 'report_id', 'task_id', 'roles')
        if latest and any(latest['payload'].get(k) != value[k] for k in identity):
            raise ActionRejected('INSTRUCTION_SCOPE_CHANGE_REQUIRES_NEW_ID')
        for ref in value['overrides']:
            parent = _find(registry, ref)['payload']
            if (parent['topic'] != value['topic'] or RANK[parent['scope']] >= RANK[value['scope']]
                    or value['scope'] not in parent['allow_override_scopes']):
                raise ActionRejected('INSTRUCTION_OVERRIDE_NOT_PERMITTED')
            if (parent['roles'] and (not value['roles'] or not set(value['roles']) <= set(parent['roles']))
                    or parent['report_id'] and parent['report_id'] != value['report_id']
                    or parent.get('report_category') and parent['report_category'] != value['report_category']):
                raise ActionRejected('INSTRUCTION_OVERRIDE_TARGET_MISMATCH')
        record = {'ref': {'id': value['id'], 'version': expected_version+1},
                  'previous_ref': latest['ref'] if latest else None, 'payload': value,
                  'payload_digest': digest(value), 'saved_at': datetime.now(timezone.utc).isoformat()}
        registry['versions'].append(record)
        _save(db, registry, 'prompt_instruction_saved', record)
        return record


def release_instruction(store, instruction_id, version, *, expected_active, reason):
    """Deliberate host release or withdrawal, with compare-and-swap protection."""
    if not isinstance(reason, str) or not reason.strip():
        raise ActionRejected('INSTRUCTION_RELEASE_REASON_REQUIRED')
    if version is not None and (type(version) is not int or version < 1):
        raise ActionRejected('INVALID_INSTRUCTION_RELEASE_VERSION')
    if expected_active is not None and (type(expected_active) is not int or expected_active < 1):
        raise ActionRejected('INVALID_EXPECTED_ACTIVE_VERSION')
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        registry = _read(db)
        current = registry['active'].get(instruction_id)
        if current != expected_active:
            raise ActionRejected('INSTRUCTION_RELEASE_CONFLICT')
        if version is not None:
            _find(registry, {'id': instruction_id, 'version': version})
            registry['active'][instruction_id] = version
        else:
            registry['active'].pop(instruction_id, None)
        result = {'id': instruction_id, 'previous_version': current, 'version': version, 'reason': reason}
        _save(db, registry, 'prompt_instruction_release', result)
        return result


def configure_report(store, report_id, *, report_category=None):
    """Host binds report identity/category; neither can drift during a run.

    An omitted category preserves old bindings and never implies applicability
    of a category rule. Agents, source quotations and titles do not classify it.
    """
    from .task_context import enabled
    from .hierarchical_tools import enabled as content_enabled
    from .workspace import Workspace
    ws = Workspace(store)
    if not enabled(ws) or not content_enabled(ws):
        raise ActionRejected('SCOPED_INSTRUCTIONS_REQUIRE_TASK_CONTEXT')
    if not isinstance(report_id, str) or not report_id.strip():
        raise ActionRejected('INSTRUCTION_REPORT_ID_REQUIRED')
    if report_category is not None and (not isinstance(report_category, str) or not report_category.strip()):
        raise ActionRejected('INSTRUCTION_REPORT_CATEGORY_REQUIRED')
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        import json
        row = db.execute("SELECT value FROM state WHERE key='prompt_instruction_config'").fetchone()
        value = {'policy': POLICY, 'report_id': report_id}
        if report_category is not None:
            value['report_category'] = report_category
        if row and json.loads(row[0]) != value:
            raise ActionRejected('REPORT_BINDING_IMMUTABLE_CREATE_NEW_PROJECT')
        db.execute("INSERT OR REPLACE INTO state VALUES ('prompt_instruction_config',?)", (encode(value),))
        db.execute("INSERT INTO events(kind,data) VALUES ('prompt_instructions_configured',?)", (encode(value),))
    return value


def instruction_context(store, role, *, task_id=None, db=None):
    """One coherent current snapshot; conflict isolation is per named topic."""
    import json
    from contextlib import nullcontext
    with (store.connect() if db is None else nullcontext(db)) as db:
        row = db.execute("SELECT value FROM state WHERE key='prompt_instruction_config'").fetchone()
        if not row:
            return None
        if role not in {'coordinator', 'writer', 'reviewer', 'layout'}:
            raise ActionRejected('INVALID_INSTRUCTION_ROLE')
        config = json.loads(row[0])
        if config['policy'] != POLICY:
            raise ActionRejected('UNKNOWN_PROMPT_INSTRUCTION_POLICY')
        registry = _read(db)
    applicable = []
    for record in registry['versions']:
        ref, value = record['ref'], record['payload']
        if registry['active'].get(ref['id']) != ref['version']:
            continue
        if value['roles'] and role not in value['roles']:
            continue
        if value.get('report_category') and value['report_category'] != config.get('report_category'):
            continue
        if value['report_id'] and value['report_id'] != config['report_id']:
            continue
        if value['task_id'] and value['task_id'] != task_id:
            continue
        applicable.append(record)
    topics = defaultdict(list)
    for record in applicable:
        topics[record['payload']['topic']].append(record)
    selected, conflicts, superseded = [], [], []
    for topic, records in sorted(topics.items()):
        records.sort(key=lambda r: (RANK[r['payload']['scope']], r['ref']['id']))
        overridden = {encode(ref) for r in records for ref in r['payload']['overrides']}
        remaining = [r for r in records if encode(r['ref']) not in overridden]
        superseded.extend(r['ref'] for r in records if encode(r['ref']) in overridden)
        if len({r['payload']['text'] for r in remaining}) > 1:
            conflicts.append({'topic': topic, 'instructions': remaining,
                              'state': 'needs_explicit_resolution'})
        else:
            selected.extend(remaining)
    packet = {'policy': POLICY, 'report_id': config['report_id'],
              'report_category': config.get('report_category'), 'role': role, 'task_id': task_id,
              'effective': selected, 'conflicts': conflicts, 'overridden_refs': superseded,
              'note': 'Only active, applicable versions are instructions. Resolve conflicting named topics with the coordinator/operator before dependent output; continue unrelated work. No automatic later-text wins. This checks declared topics/overrides, not arbitrary semantic contradictions with role prompts, learned guidance or prose. These instructions never grant tools, ownership or source truth.'}
    packet['digest'] = digest(packet)
    return packet


def review_commission(store, actor, prompt):
    """Use the same host instruction channel in both independent review tools.

    No configuration preserves the historical packet and system prompt exactly.
    The actual bound actor determines applicability, never caller parameters.
    """
    commission = {k: store.manifest.get(k) for k in ('goal', 'scope_instruction')}
    context = instruction_context(store, actor.role, task_id=actor.task_id)
    if context is not None:
        commission['scoped_instructions'] = context
        prompt += load_prompt('scoped-review-channel')
    return commission, prompt


def offered_context(store, packet, system_blocks):
    """Persist exact assembled input before invoking the existing model handler.

    Offered is not proof of provider receipt or semantic application. Response
    outcome is recorded separately by the middleware; no model retry here.
    """
    snapshot = {'scoped_instructions': packet, 'system_blocks': system_blocks}
    snapshot_id = digest(snapshot)
    call_id = str(uuid4())
    with store.connect() as db:
        db.execute('INSERT OR IGNORE INTO state VALUES (?,?)',
                   ('prompt_context_snapshot:'+snapshot_id, encode(snapshot)))
        db.execute("INSERT INTO events(kind,data) VALUES ('prompt_context_offered',?)",
                   (encode({'call_id': call_id, 'snapshot_id': snapshot_id,
                            'instruction_digest': packet['digest'], 'role': packet['role'],
                            'task_id': packet['task_id']}),))
    return {'call_id': call_id, 'snapshot_id': snapshot_id}
