import ast
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
