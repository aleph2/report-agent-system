"""Opt-in offline inventory: pytest -p support.record_tool_inventory; raw output stays private."""
from contextvars import ContextVar
from functools import wraps
import inspect
import json
import os
from pathlib import Path
import re

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.tools import StructuredTool
from langchain_core.tracers.context import register_configure_hook

ROOT = Path(__file__).resolve().parents[2]
CATALOG, WORKSPACES, PENDING, EVENTS, ERRORS = {}, {}, {}, [], []


def register(workspace, role, tools, origin):
    from report_agent.operation_identity import profile
    operation_profile = profile(workspace.store)
    WORKSPACES[id(workspace)] = workspace
    for fn in tools:
        try:
            tool = fn if isinstance(fn, StructuredTool) else StructuredTool.from_function(fn)
            schema = tool.tool_call_schema
            schema = schema if isinstance(schema, dict) else schema.model_json_schema()
            target = inspect.unwrap(tool.func) if tool.func else None
            location = inspect.getsourcefile(target) if target else None
            if location:
                try:
                    location = str(Path(location).relative_to(ROOT))
                except ValueError:
                    location = 'platform:' + (getattr(target, '__module__', None) or type(target).__module__)
            key = role, tool.name, operation_profile, origin, json.dumps(schema, sort_keys=True)
            CATALOG[key] = dict(role=role, tool=tool.name, operation_profile=operation_profile, origin=origin, schema=schema, source=location,
                                line=getattr(getattr(target, '__code__', None), 'co_firstlineno', None))
            if isinstance(fn, StructuredTool):
                fn.metadata = {**(fn.metadata or {}), '_inventory_workspace':id(workspace),
                               '_inventory_role':role}
        except Exception as error:
            ERRORS.append(dict(phase='schema', role=role, tool=getattr(fn, 'name', None) or fn.__name__,
                               error=type(error).__name__ + ': ' + str(error)))
    return tools


def identity(name, metadata):
    from report_agent.content_tasks import bound_actor
    from report_agent.text_work import actor_for_tool
    role = metadata.get('_inventory_role')
    workspace = WORKSPACES.get(metadata.get('_inventory_workspace'))
    if workspace is not None and role is not None:
        try:
            actor = actor_for_tool(workspace, role)
            return str(workspace.store.root), actor.role, actor.id
        except Exception:
            return str(workspace.store.root), role, None
    candidates = []
    roles = {entry['role'] for entry in CATALOG.values() if entry['tool'] == name}
    for workspace in WORKSPACES.values():
        for role in roles:
            try:
                actor = bound_actor(workspace, role, None)
                if actor is not None:
                    candidates.append((str(workspace.store.root), actor.role, actor.id))
            except Exception:
                pass
    candidates = list(dict.fromkeys(candidates))
    return candidates[0] if len(candidates) == 1 else (None, None, None)


class Capture(BaseCallbackHandler):
    run_inline = True

    def on_tool_start(self, serialized, input_str, *, run_id, metadata=None, inputs=None,
                      tool_call_id=None, **kwargs):
        name = serialized.get('name')
        if name not in {entry['tool'] for entry in CATALOG.values()}:
            return
        case, role, actor = identity(name, metadata or {})
        PENDING[str(run_id)] = dict(run_id=str(run_id), case=case, role=role, actor=actor,
            tool=name, native_call_id=tool_call_id, input_fields=sorted((inputs or {}).keys()))

    def finish(self, run_id, *, error=None, output=None):
        row = PENDING.pop(str(run_id), None)
        if row is None:
            return
        row['rejected'] = error is not None or getattr(output, 'status', None) == 'error'
        row['codes'], row['raise_sites'], row['validation_errors'] = [], [], []
        seen = set()
        while error is not None and id(error) not in seen:
            seen.add(id(error))
            message = str(error)
            if callable(getattr(error, 'errors', None)):
                row['validation_errors'].extend({'type':e['type'], 'loc':e['loc']} for e in error.errors())
            codes = re.findall(r'\bC(?:1[0-2]|[1-9]):', message)
            row['codes'].extend(code[:-1] for code in codes)
            if not codes:
                row['codes'].append(message.split(':', 1)[0] if re.match(r'^[A-Z][A-Z0-9_]+(?=:|$)', message)
                                    else type(error).__name__)
            tb = error.__traceback__
            while tb is not None:
                path = Path(tb.tb_frame.f_code.co_filename)
                try:
                    path = path.relative_to(ROOT/'src')
                except ValueError:
                    tb = tb.tb_next
                    continue
                row['raise_sites'].append(dict(file='src/'+str(path), line=tb.tb_lineno))
                tb = tb.tb_next
            error = error.__cause__
        row['codes'] = sorted(set(row['codes']))
        EVENTS.append(row)

    def on_tool_error(self, error, *, run_id, **kwargs):
        self.finish(run_id, error=error)

    def on_tool_end(self, output, *, run_id, **kwargs):
        self.finish(run_id, output=output)


def pytest_configure(config):
    import pytest
    import report_agent.native_operation_tools as native
    import report_agent.writer_runtime as writer
    import report_agent.deep_runtime as runtime
    patcher = pytest.MonkeyPatch()
    config._inventory_patcher = patcher
    capture = Capture()
    hook = ContextVar('offline_tool_inventory', default=capture)
    config._inventory_hook = hook
    register_configure_hook(hook, inheritable=True)

    def factory(module, name, role_at):
        original = getattr(module, name)
        @wraps(original)
        def observed(workspace, *args, **kwargs):
            result = original(workspace, *args, **kwargs)
            role = role_at(args, kwargs)
            register(workspace, role, result if isinstance(result, list) else [result], module.__name__ + '.' + name)
            return result
        patcher.setattr(module, name, observed)
    factory(native, '_native_write', lambda args, kwargs:args[0])
    factory(native, 'native_write_tools', lambda args, kwargs:args[0])
    factory(writer, 'writer_tools', lambda args, kwargs:args[0].role)
    factory(runtime, 'business_tools', lambda args, kwargs:args[0])
    # IndicatorRun also holds the imported public native-write factory.
    import report_agent.writer_indicator_steps as steps
    patcher.setattr(steps, '_native_write', native._native_write)


def pytest_sessionfinish(session, exitstatus):
    destination = os.environ.get('REPORT_TOOL_INVENTORY')
    if destination:
        Path(destination).write_text(json.dumps(dict(exit_code=int(exitstatus),
            catalog=list(CATALOG.values()), observations=EVENTS, incomplete=list(PENDING.values()),
            instrumentation_errors=ERRORS), ensure_ascii=False, indent=2), encoding='utf-8')


def pytest_unconfigure(config):
    config._inventory_hook.set(None)
    config._inventory_patcher.undo()
