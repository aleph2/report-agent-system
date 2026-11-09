import ast
import re
from pathlib import Path

from report_agent.assertions.schema.kinds import Assertion


def test_assertions_do_not_import_the_task_runtime_or_store_task_state():
    package = Path(__file__).parents[1] / "src/report_agent/assertions"
    for path in package.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom):
                assert node.level <= 1, path
                assert not (node.module or "").startswith("report_agent."), path
            if isinstance(node, ast.Import):
                assert not any(alias.name.startswith("report_agent.") for alias in node.names), path
    assert {"attempt", "packet", "lease", "dispatch", "runtime_status", "reservation"}.isdisjoint(
        Assertion.model_fields
    )


def test_launch_host_cannot_open_content_transactions():
    host = Path(__file__).parents[1] / "src/report_agent/assertion_host.py"
    tree = ast.parse(host.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or "").endswith("assertions.store")
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"_store", "transaction", "reader"}


def test_only_assertion_package_opens_or_attaches_its_database():
    root = Path(__file__).parents[1]
    package = root / "src/report_agent/assertions"
    for directory in (root / "src", root / "scripts"):
        for path in directory.rglob("*.py"):
            if path.is_relative_to(package):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            # Existing consumers can ask whether the database exists.
            existence_checks = {
                node.func.value.right for node in ast.walk(tree)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "is_file" and isinstance(node.func.value, ast.BinOp)
                and isinstance(node.func.value.op, ast.Div)
            }
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    module = (node.module or "") if isinstance(node, ast.ImportFrom) else ""
                    names = [module, *(f"{module}.{item.name}" for item in node.names)]
                    assert not any(name.endswith("assertions.store") for name in names), (path, node.lineno)
                if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                    continue
                value = node.value
                if value in {"assertions.sqlite3-shm", "assertions.sqlite3-wal"}:
                    continue
                if node in existence_checks and value == "assertions.sqlite3":
                    continue
                assert "assertions.sqlite3" not in value.lower(), (path, node.lineno)
                # A bound or interpolated ATTACH target can hide the database filename.
                assert not re.search(r"\bATTACH\s+(?:DATABASE\s+)?(?:[?:@$\{]|$)", value, re.I), (path, node.lineno)
