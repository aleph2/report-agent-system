"""Optional task-supervision implementations around the native delegation boundary.

Plugins receive the already-authorized task and its bound native invocation.
They cannot grant roles or artifact ownership. Business evidence exists separately.
"""
from dataclasses import dataclass
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
from pathlib import Path
from datetime import datetime

_resume_permit = ContextVar("native_local_busy_resume", default=None)
from typing import Protocol

from .errors import ActionRejected


class SupervisionPlugin(Protocol):
    id: str
    description: str
    requires_check_evidence: bool

    async def wrap_return(self, contents, actor, call, invoke): ...


@dataclass(frozen=True)
class SavedTaskChecks:
    id: str
    description: str
    requires_check_evidence: bool = False

    async def wrap_return(self, contents, actor, call, invoke):
        from .task_supervision import supervised_return
        return await supervised_return(contents, actor, call, invoke)


PLUGINS: dict[str, SupervisionPlugin] = {
    "task-checks-v1": SavedTaskChecks("task-checks-v1", "Saved checklist and actual required-read reconciliation; one completion follow-up; preserve remaining work."),
    "task-checks-evidence-v2": SavedTaskChecks("task-checks-evidence-v2", "Per-check results linked to actual observations, separate outside-task notes; one completion follow-up. Evidence links do not prove semantic depth.", True),
}


def resolve_plugin(plugin_id):
    if plugin_id is None:
        return None
    if plugin_id not in PLUGINS:
        raise ActionRejected("UNKNOWN_SUPERVISION_PLUGIN")
    return PLUGINS[plugin_id]


def selected_plugin(contract):
    # Historical tasks predate optional selection; preserve their actual policy.
    # New tasks explicitly save None when no plugin was selected.
    plugin_id = contract.get("supervision_plugin", "task-checks-v1") if contract.get("review_requirements") else None
    return resolve_plugin(plugin_id)


def plugin_catalog():
    return {"optional": True, "default": None,
            "plugins": [{"id": p.id, "description": p.description,
                         "requires_check_evidence": p.requires_check_evidence} for p in PLUGINS.values()],
            "limitation": "Selection changes supervision behavior, not permissions, standards or evidence of correctness. Existing tasks retain their selected policy."}


@contextmanager
def local_busy_resume(store, *, call_id, task_id, diagnostic_id, diagnostic_sha256, on_verified=None):
    """Host-only permit for one proven local persistence interruption."""
    path = store.root / 'diagnostics' / 'private' / (diagnostic_id + '.json')
    if path.resolve().parent != (store.root / 'diagnostics' / 'private').resolve():
        raise ActionRejected('NATIVE_RESUME_DIAGNOSTIC_INVALID')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != diagnostic_sha256:
        raise ActionRejected('NATIVE_RESUME_DIAGNOSTIC_INVALID')
    diagnostic = json.loads(raw)
    exceptions = diagnostic.get('exceptions', [])
    top = exceptions[0] if exceptions and isinstance(exceptions[0], dict) else {}
    frames = {(Path(f['file']).name, f['function']) for f in top.get('frames', [])}
    if (diagnostic.get('id') != diagnostic_id or diagnostic.get('phase') != 'native_graph'
            or top.get('type') != 'OperationalError' or top.get('sqlite_errorcode') != 5
            or not {('execution_progress.py', 'abefore_model'), ('execution_progress.py', 'save'),
                    ('store.py', 'connect')} <= frames):
        raise ActionRejected('NATIVE_RESUME_DIAGNOSTIC_INVALID')
    if on_verified is not None and not callable(on_verified):
        raise ActionRejected('NATIVE_RESUME_DIAGNOSTIC_INVALID')
    permit = {'root':str(store.root.resolve()), 'call_id':call_id, 'task_id':task_id,
              'diagnostic_at':datetime.fromisoformat(diagnostic['at']), 'diagnostic_sha256':diagnostic_sha256,
              'on_verified':on_verified, 'used':False}
    token = _resume_permit.set(permit)
    try:
        yield
    finally:
        _resume_permit.reset(token)


async def _resume_original_checkpoint(contents, actor, call, previous, runtime):
    """Prove the framework is resuming this reserved child, then consume the permit."""
    from .store import digest
    permit = _resume_permit.get()
    if (not permit or permit['used'] or permit['root'] != str(contents.store.root.resolve())
            or permit['call_id'] != call['id'] or permit['task_id'] != actor.task_id
            or previous != {'task_id':actor.task_id, 'native_tool_call_id':call['id'],
                            'request_digest':digest({'actor':actor.__dict__, 'call':call}), 'state':'reserved'}):
        return False
    config = getattr(runtime, 'config', None) or {}
    cfg = config.get('configurable', {})
    task_id, namespace = cfg.get('__pregel_task_id'), cfg.get('checkpoint_ns')
    saver = cfg.get('__pregel_checkpointer')
    if (cfg.get('__pregel_resuming') is not True or cfg.get('thread_id') != 'report'
            or not isinstance(task_id, str) or not isinstance(namespace, str)
            or namespace.rsplit('|', 1)[-1] != 'tools:' + task_id
            or saver is None or not callable(getattr(saver, 'aget_tuple', None))):
        return False
    saved = await saver.aget_tuple({'configurable':{'thread_id':cfg['thread_id'], 'checkpoint_ns':namespace}})
    if (not saved or saved.config.get('configurable', {}).get('checkpoint_ns') != namespace
            or saved.config.get('configurable', {}).get('thread_id') != cfg['thread_id']
            or saved.metadata.get('parents') != cfg.get('checkpoint_map')
            or saved.metadata.get('lc_agent_name') != actor.role
            or not saved.checkpoint.get('channel_versions')):
        return False
    try:
        checkpoint_at = datetime.fromisoformat(saved.checkpoint['ts'])
    except (KeyError, TypeError, ValueError):
        return False
    errors = [row[2] for row in (saved.pending_writes or []) if row[1] == '__error__']
    active = [key for key in saved.checkpoint.get('channel_values', {}) if key.startswith('branch:to:')]
    if (checkpoint_at > permit['diagnostic_at'] or errors != ["OperationalError('database is locked')"]
            or active != ['branch:to:ExecutionProgress.before_model'] or permit['used']):
        return False
    permit['used'] = True
    if permit['on_verified'] is not None:
        permit['on_verified']({'call_id':call['id'], 'task_id':actor.task_id, 'thread_id':cfg['thread_id'],
            'checkpoint_ns':namespace, 'checkpoint_id':saved.config['configurable']['checkpoint_id'],
            'parent_checkpoints':saved.metadata['parents'], 'node':'ExecutionProgress.before_model',
            'diagnostic_sha256':permit['diagnostic_sha256']})
    return True


async def delegated_return(contents, actor, call, invoke, *, runtime=None):
    from .task_supervision import assignment
    task = assignment(contents, actor.task_id)
    plugin = selected_plugin(task)
    v4 = task.get('review_interface_profile') == 'review-interfaces-v4'
    reservation = 'native_delegation:'+call['id']
    if v4:
        from .store import encode, digest
        request = digest({'actor': actor.__dict__, 'call': call})
        with contents.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT value FROM state WHERE key=?', (reservation,)).fetchone()
            if not previous:
                db.execute('INSERT INTO state VALUES (?,?)', (reservation, encode({
                    'task_id': actor.task_id, 'native_tool_call_id': call['id'],
                    'request_digest': request, 'state': 'reserved'})))
                db.execute("INSERT INTO events(kind,data) VALUES ('native_delegation_reserved',?)",
                           (encode({'task_id': actor.task_id, 'native_tool_call_id': call['id'], 'request_digest': request}),))
        if previous and not await _resume_original_checkpoint(contents, actor, call, json.loads(previous[0]), runtime):
            raise ActionRejected('NATIVE_DELEGATION_OUTCOME_UNRESOLVED: original native intent already reserved; recover its native checkpoint/result before any continuation')
    result = await invoke(call) if plugin is None else await plugin.wrap_return(contents, actor, call, invoke)
    if v4:
        # The native graph owns Command/checkpoint serialization; never serialize a second copy.
        try:
            contents.store.set(reservation, {'task_id': actor.task_id, 'native_tool_call_id': call['id'],
                'request_digest': request, 'state': 'returned', 'recovery': 'original_native_checkpoint_only'})
        except Exception:
            pass  # A failed audit update must not discard a completed native result or retry it.
    return result
