"""Round 0 measurement only: existing tests, coverage.py, native tool observations.

Run with the project WSL Python. coverage.py may be provided through --tools-dir.
No application/test source is changed. In-process TCP/UDP connections are denied. This
records invocation evidence, NOT semantic correctness or MC/DC coverage.
"""
from __future__ import annotations

import argparse
import contextvars
import functools
import hashlib
import inspect
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[3]
ROLE = contextvars.ContextVar("round0_observed_role", default="unattributed")
CONFIG = contextvars.ContextVar("round0_observed_config", default=None)


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def source_hashes():
    files = [*ROOT.joinpath("src").rglob("*.py"), *ROOT.joinpath("src").rglob("*.md"),
             *ROOT.joinpath("tests").rglob("*.py"), *ROOT.joinpath("tests").rglob("*.json"),
             *Path(__file__).parent.glob("*.py"), ROOT / "pyproject.toml"]
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(files)}


class Observe:
    def __init__(self, out):
        self.out, self.nodeid = out, "<collection>"
        self.calls, self.reports, self.collection, self.errors = [], [], [], []
        self.schemas, self.denied_connections = {}, []
        self.restore = []

    def patch(self, obj, name, replacement):
        self.restore.append((obj, name, getattr(obj, name)))
        setattr(obj, name, replacement)

    def guard_network(self):
        for name in ("connect", "connect_ex", "sendto"):
            original = getattr(socket.socket, name)
            def deny(sock, *args, _original=original, **kwargs):
                if sock.family in (socket.AF_INET, socket.AF_INET6):
                    self.denied_connections.append({"test": self.nodeid, "method": _original.__name__})
                    raise OSError("ROUND0_OFFLINE_NETWORK_DENIED")
                return _original(sock, *args, **kwargs)
            self.patch(socket.socket, name, deny)
        os.environ.update(LANGSMITH_TRACING="false", LANGCHAIN_TRACING_V2="false")
        # Optional live-service tests must not inherit a user's service target.
        os.environ.pop("REPORT_GRAPH_TEST_URI", None)

    def schema(self, role, tool, origin):
        name = getattr(tool, "name", getattr(tool, "__name__", type(tool).__name__))
        try:
            from langchain_core.utils.function_calling import convert_to_openai_tool
            value = convert_to_openai_tool(tool)["function"]
            key = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
            row = self.schemas.setdefault((role, name, key), {"role": role, "name": name,
                "schema_sha256": key, "schema": value, "origins": set(), "observed_at": set()})
            row["origins"].add(origin)
            row["observed_at"].add(json.dumps({"test": self.nodeid, "origin": origin,
                "config": CONFIG.get()}, sort_keys=True))
        except Exception as exc:
            self.errors.append({"stage": "schema", "role": role, "tool": name,
                                "error": type(exc).__name__})

    def install(self):
        from report_agent import deep_runtime
        from langchain_core.tools import BaseTool
        from test_deep_runtime import ScriptedChat
        original_model = deep_runtime.BusinessBoundary.awrap_model_call
        async def model(boundary, request, handler):
            async def observe_next(effective):
                for tool in effective.tools:
                    self.schema(boundary.role, tool, "business_boundary_next_handler")
                return await handler(effective)
            manifest = boundary.workspace.store.manifest
            token = CONFIG.set({key: manifest.get(key) for key in
                ("content_contract", "context_policy", "review_entrypoint", "review_execution_mode", "decision_data_policy")})
            try:
                return await original_model(boundary, request, observe_next)
            finally:
                CONFIG.reset(token)
        self.patch(deep_runtime.BusinessBoundary, "awrap_model_call", model)
        original_tool = deep_runtime.BusinessBoundary.awrap_tool_call
        async def boundary_call(boundary, request, handler):
            token = ROLE.set(boundary.role)
            row = {"test": self.nodeid, "role": boundary.role,
                   "name": request.tool_call["name"], "boundary": "business_middleware"}
            self.calls.append(row)
            try:
                result = await original_tool(boundary, request, handler)
                row.update(returned=True, result_type=type(result).__name__,
                           status=getattr(result, "status", None))
                return result
            except BaseException as exc:
                row.update(returned=False, exception=type(exc).__name__)
                raise
            finally:
                ROLE.reset(token)
        self.patch(deep_runtime.BusinessBoundary, "awrap_tool_call", boundary_call)
        original_bind = ScriptedChat.bind_tools
        def bind(model, tools, **kwargs):
            for tool in tools:
                self.schema(model.role, tool, "actual_scripted_model_bind_tools")
            return original_bind(model, tools, **kwargs)
        self.patch(ScriptedChat, "bind_tools", bind)
        for method in ("run", "arun"):
            original = getattr(BaseTool, method)
            if method == "arun":
                async def async_call(tool, *args, _original=original, **kwargs):
                    row = {"test": self.nodeid, "role": ROLE.get(), "name": tool.name,
                           "boundary": "native_base_tool"}
                    self.calls.append(row)
                    try:
                        result = await _original(tool, *args, **kwargs)
                        row.update(returned=True, result_type=type(result).__name__, status=getattr(result, "status", None))
                        return result
                    except BaseException as exc:
                        row.update(returned=False, exception=type(exc).__name__)
                        raise
                self.patch(BaseTool, method, async_call)
            else:
                def sync_call(tool, *args, _original=original, **kwargs):
                    row = {"test": self.nodeid, "role": ROLE.get(), "name": tool.name,
                           "boundary": "native_base_tool_sync"}
                    self.calls.append(row)
                    try:
                        result = _original(tool, *args, **kwargs)
                        row.update(returned=True, result_type=type(result).__name__, status=getattr(result, "status", None))
                        return result
                    except BaseException as exc:
                        row.update(returned=False, exception=type(exc).__name__)
                        raise
                self.patch(BaseTool, method, sync_call)

    def pytest_collection_finish(self, session):
        self.collection = [item.nodeid for item in session.items]
        save(self.out / "collected.json", self.collection)

    def pytest_runtest_setup(self, item):
        self.nodeid = item.nodeid
        save(self.out / "progress.json", {"current_test": self.nodeid,
             "completed_phases": len(self.reports), "updated_at_epoch": time.time()})

    def pytest_runtest_logreport(self, report):
        self.reports.append({"test": report.nodeid, "phase": report.when,
            "outcome": report.outcome, "duration": report.duration,
            "detail": str(report.longrepr) if report.failed or report.skipped else None})
        if report.when == "teardown":
            self.nodeid = "<between-tests>"

    def pytest_collectreport(self, report):
        if report.failed:
            self.errors.append({"stage": "collection", "nodeid": report.nodeid,
                                "detail": str(report.longrepr)})

    def finish(self):
        try:
            schemas = [{**row, "origins": sorted(row["origins"]),
                "observed_at": [json.loads(v) for v in sorted(row["observed_at"])]} for row in self.schemas.values()]
            save(self.out / "observations.json", {"schemas": schemas, "calls": self.calls,
                "reports": self.reports, "errors": self.errors,
                "denied_connections": self.denied_connections})
        finally:
            for obj, name, original in reversed(self.restore):
                setattr(obj, name, original)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--tools-dir", type=Path)
    parser.add_argument("--collect-only", action="store_true")
    parser.add_argument("--observe", action="store_true")
    parser.add_argument("tests", nargs="*", default=["tests"])
    args = parser.parse_args()
    if args.tools_dir:
        sys.path.insert(0, str(args.tools_dir))
    sys.path.insert(0, str(ROOT / "tests"))
    sys.path.insert(0, str(ROOT / "src"))
    os.chdir(ROOT)
    args.out.mkdir(parents=True, exist_ok=True)
    import coverage
    import pytest
    before = source_hashes()
    save(args.out / "source-before.json", before)
    save(args.out / "environment.json", {"python": sys.version, "coverage": coverage.__version__,
        "pytest": pytest.__version__, "source_root": str(ROOT), "observe": args.observe,
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()})
    plugin = Observe(args.out)
    plugin.guard_network()
    cov = coverage.Coverage(branch=True, source=[str(ROOT / "src" / "report_agent")],
                            data_file=str(args.out / ".coverage"), config_file=False)
    start = time.monotonic()
    code = None
    try:
        cov.start()
        if args.observe:
            plugin.install()
        with tempfile.TemporaryDirectory(prefix="report-round0-") as tmp:
            options = [*args.tests, "-q", "--continue-on-collection-errors", "-p", "no:cacheprovider",
                       "--basetemp=" + tmp + "/pytest", "--junitxml=" + str(args.out / "junit.xml")]
            if args.collect_only:
                options.append("--collect-only")
            code = pytest.main(options, plugins=[plugin])
    finally:
        cleanup_errors, changed = [], None
        for label, action in [("coverage_stop", cov.stop), ("coverage_save", cov.save),
                ("coverage_json", lambda: cov.json_report(outfile=str(args.out / "coverage.json"), pretty_print=True))]:
            try:
                action()
            except Exception as exc:
                cleanup_errors.append({"stage": label, "error": repr(exc)})
        try:
            after = source_hashes()
            save(args.out / "source-after.json", after)
            changed = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
        except Exception as exc:
            cleanup_errors.append({"stage": "source_after", "error": repr(exc)})
        try:
            plugin.finish()
        except Exception as exc:
            cleanup_errors.append({"stage": "observer_finish", "error": repr(exc)})
        save(args.out / "result.json", {"pytest_exit_code": int(code) if code is not None else None,
            "elapsed_seconds": time.monotonic() - start, "source_changes": changed,
            "network_connections_denied": len(plugin.denied_connections),
            "provider_calls_allowed": False, "network_guard_scope": "This Python process only; not a provider audit or subprocess firewall.",
            "cleanup_errors": cleanup_errors, "conditions_measured_by_coverage_py": False})
    return int(code or 0)


if __name__ == "__main__":
    raise SystemExit(main())
