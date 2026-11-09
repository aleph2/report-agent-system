"""Keep the 32 inventoried families behind the temporary migration accessors."""
import ast
from pathlib import Path
import re

import pytest


FAMILIES = frozenset("""
fake03_qualitative_profile fake03_qualitative_actor: writer_indicator_steps:
writer_page_read: writer_assessment_draft: assessment_receipt: g6_assessment:
g6_assessment_producer: commission_plan commission_confirmation commission_skeleton
commission_planning_draft commission_text_profiles commission_requirements
commission_requirements_checkpoint: commission_source_roles commission_owner_records
commission_checkpoint: report_issues g6_issue_record: g6_issue_binding: g6_issue_route:
planned_section_receipt: assembly_receipt: commission_outcome: rescue_projection:
content_delivery content_final_review corrections source_changes
result_impact_assessments decision_observation
""".split())
RETIRED = {"fake03_qualitative_profile", "fake03_qualitative_actor:"}
STATE_SQL = re.compile(r'\b(?:from|into|update|join)\s+["\x60\[]?state\b', re.I)
SQL_KEY = re.compile(r"""['"]([a-z0-9_:]+)%?['"]""", re.I)


def is_family(value):
    return any(value == key or (key.endswith(":") and value.startswith(key)) for key in FAMILIES)


def direct_accesses(source):
    tree = ast.parse(source)
    # Follow simple key aliases and grouped SQL parameters. Public response fields
    # use the same spelling, so only inspect operands reaching storage calls.
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    aliases.setdefault(target.id, []).append(node.value)

    def strings(expr, visited=frozenset()):
        if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
            yield expr.value
        elif isinstance(expr, ast.Name) and expr.id not in visited:
            for value in aliases.get(expr.id, []):
                yield from strings(value, visited | {expr.id})
        elif isinstance(expr, (ast.Tuple, ast.List, ast.Set, ast.BinOp, ast.JoinedStr)):
            for child in ast.iter_child_nodes(expr):
                yield from strings(child, visited)

    failures = []
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call) or not call.args:
            continue
        name = getattr(call.func, "attr", getattr(call.func, "id", ""))
        args = []
        if name in {"execute", "executemany", "executescript"}:
            statements = [s for s in strings(call.args[0]) if STATE_SQL.search(s)]
            if statements:
                args = [s for sql in statements for s in SQL_KEY.findall(sql)]
                args.extend(s for arg in call.args[1:] for s in strings(arg))
        elif name in {"get", "set"} and isinstance(call.func, ast.Attribute):
            receiver = ast.unparse(call.func.value).lower()
            if receiver in {"store", "storage"} or receiver.endswith(("store", ".storage")):
                args = list(strings(call.args[0]))
        elif name in {"_get", "_set", "_state", "_prefixed", "_context_change"}:
            args = [s for arg in call.args[:2] for s in strings(arg)]
        for key in sorted({s for s in args if is_family(s)}):
            failures.append((call.lineno, key))
    return failures


@pytest.mark.parametrize("source", [
    "workspace.store.get('report_issues')",
    "key = 'writer_page_read:' + slope\nstore.set(key, row)",
    """conn.execute("SELECT value FROM state WHERE key IN ('corrections','source_changes')")""",
    """keys = ('commission_plan', 'public')\nconn.execute('SELECT * FROM state WHERE key IN (?, ?)', keys)""",
    """conn.execute("SELECT value FROM state WHERE key LIKE 'g6_issue_record:%'")""",
    """_context_change(db, 'report_issues', obj)""",
])
def test_guard_detects_storage_bypasses(source):
    assert direct_accesses(source)


def test_guard_permits_public_fields_and_unrelated_tables():
    assert not direct_accesses("""payload.get('content_delivery')
db.execute("SELECT 'corrections' FROM figures")
""")


def test_legacy_state_ownership():
    package = Path(__file__).resolve().parents[1] / "src/report_agent"
    assert len(FAMILIES) == 32
    assert all(key not in (package / "legacy_state.py").read_text() for key in RETIRED)
    project = package.parents[1]
    files = sorted(package.rglob("*.py")) + sorted((project / "scripts").rglob("*.py"))
    violations = [(str(path.relative_to(project)), line, key)
                  for path in files
                  if path != package / "legacy_state.py"
                  for line, key in direct_accesses(path.read_text(encoding="utf-8"))]
    assert violations == []


# These are existing public payload fields, dictionary projections and exporter
# module filenames. They contain no per-family storage access.
PUBLIC_USES = {
    ("plan_authority", "propose", "keyword"): {"commission_plan"},
    ("commission_assertions", "record_interpretation", "Dict"): {"commission_requirements"},
    ("commission_plan", "save_plan", "Dict"): {"commission_plan"},
    ("commission_plan", "request_checkpoint", "Dict"): {"corrections", "commission_plan"},
    ("content_export", "execute", "Tuple"): {"commission_owner_records"},
    ("content_workbook", "_export_workbook", "Tuple"): {"commission_owner_records"},
    ("deep_runtime", "project_view", "Subscript"): {"commission_source_roles", "content_final_review", "content_delivery"},
    ("knowledge_state", "project_state", "Subscript"): {"content_delivery"},
    ("mini_commission", "prepare_mini_commission", "Dict"): {"corrections"},
    ("review_context", "capture", "Dict"): {"corrections"},
    ("review_context", "capture", "Subscript"): {"corrections"},
    ("workspace", "_dependency_snapshot", "Dict"): {"source_changes"},
    ("workspace", "delivery", "Dict"): {"source_changes"},
    ("workspace", "status", "Dict"): {"corrections", "result_impact_assessments", "source_changes"},
}


def test_new_family_literals_require_review():
    package = Path(__file__).resolve().parents[1] / "src/report_agent"
    violations = []
    for path in sorted(package.rglob("*.py")):
        if path == package / "legacy_state.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        for node, parent in parents.items():
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str) or not is_family(node.value):
                continue
            scope = parent
            while scope in parents and not isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
                scope = parents[scope]
            key = path.stem, getattr(scope, "name", None), type(parent).__name__
            # The business import drops these legacy keys from the isolated state copy.
            if key == ("probe_case", "prepare_probe_case", "Call") and ast.unparse(parent.func) == "state.pop":
                if node.value in {"commission_source_roles", "commission_owner_records", "commission_requirements"}:
                    continue
            if node.value not in PUBLIC_USES.get(key, ()):
                violations.append((str(path.relative_to(package)), node.lineno, node.value))
    assert violations == []


HISTORICAL_READERS = {"writer_assessment_draft:", "writer_indicator_steps:", "writer_page_read:",
                      "assessment_receipt:", "g6_assessment:", "g6_assessment_producer:"}


M4_HISTORICAL_READERS = {"commission_plan", "commission_confirmation", "commission_skeleton",
                         "commission_planning_draft", "commission_text_profiles"}


@pytest.mark.parametrize("family", sorted(M4_HISTORICAL_READERS))
def test_old_planning_keys_are_readable_without_a_write_accessor(tmp_path, family):
    from report_agent import legacy_state
    from report_agent.store import Store

    store = Store(tmp_path)
    store.set(family, {"historical": True})
    assert getattr(legacy_state, "get_" + family)(store) == {"historical": True}
    assert not hasattr(legacy_state, "set_" + family)


@pytest.mark.parametrize("family", sorted(HISTORICAL_READERS))
def test_old_writer_keys_are_readable_without_a_write_accessor(tmp_path, family):
    from report_agent import legacy_state
    from report_agent.store import Store

    store = Store(tmp_path)
    name = family.rstrip(":")
    assert not hasattr(legacy_state, "set_" + name)
    # Create the exact state a pre-M2 case would already contain.
    store.set(family + "old-id", {"v": 1})
    assert getattr(legacy_state, "get_" + name)(store, "old-id") == {"v": 1}


M5_HISTORICAL_READERS = {
    "commission_requirements", "commission_requirements_checkpoint:", "commission_owner_records",
    "commission_source_roles", "commission_checkpoint:",
}

M6_HISTORICAL_READERS = {'report_issues', 'g6_issue_record:', 'g6_issue_binding:', 'g6_issue_route:'}


@pytest.mark.parametrize("family", sorted(M5_HISTORICAL_READERS))
def test_old_commission_key_is_readable_without_a_write_accessor(tmp_path, family):
    from report_agent import commission_assertions, commission_imports, commission_requirements, legacy_state
    from report_agent.store import Store

    store = Store(tmp_path)
    name = family.rstrip(":")
    issue = "existing-issue"
    raw_key = family + issue if family.endswith(":") else family
    ref = {"type": "CommissionRequirements", "id": "old", "version": 1}
    old = ref if family == "commission_requirements" else {"historical": True}
    store.set(raw_key, old)
    assert not hasattr(legacy_state, "set_" + name)
    legacy_read = getattr(legacy_state, "get_" + name)
    suffix = (issue,) if family.endswith(":") else ()
    assert legacy_read(store, *suffix) == old
    if family == "commission_checkpoint:" or family == "commission_requirements_checkpoint:":
        kind = "plan" if family == "commission_checkpoint:" else "requirements"
        assert commission_assertions.checkpoint(store, kind, issue) == old
        assert commission_assertions.checkpoint_answer(store, kind, issue) is None
    else:
        readers = {"commission_requirements": commission_requirements.requirements_ref,
                   "commission_source_roles": commission_imports.source_roles,
                   "commission_owner_records": commission_imports.owner_records}
        assert readers[family](store) == old
    assert store.get(raw_key) == old
    assert not (tmp_path / "assertions.sqlite3").exists()


def test_host_input_records_are_private_in_direct_and_snapshot_reads(tmp_path):
    from report_agent import commission_imports
    from report_agent.content_store import Actor, ContentStore
    from report_agent.errors import ActionForbidden
    from report_agent.store import Store

    cs = ContentStore(Store(tmp_path))
    host = Actor("host", "host", "intake")
    writer = Actor("writer", "writer", "section")
    for kind in commission_imports.TYPES:
        with cs.store.connect() as db:
            ref = cs._insert(db, host, kind, {})
            wrapped = cs._insert(db, host, "DocumentSnapshot", {"refs": [ref]})
        for target in (ref, wrapped):
            with pytest.raises(ActionForbidden):
                cs.read_context(writer, target)


@pytest.mark.parametrize("family", sorted(FAMILIES - RETIRED - HISTORICAL_READERS
                                          - M4_HISTORICAL_READERS - M5_HISTORICAL_READERS - M6_HISTORICAL_READERS))
def test_accessor_preserves_storage_key_and_rollback(tmp_path, family):
    from report_agent import legacy_state
    from report_agent.store import Store

    store = Store(tmp_path)
    suffix = ("审阅:1",) if family.endswith(":") else ()
    raw_key = family + "".join(suffix)
    read = getattr(legacy_state, "get_" + family.rstrip(":"))
    write = getattr(legacy_state, "set_" + family.rstrip(":"))
    missing = object()
    assert read(store, *suffix, default=missing) is missing
    write(store, *suffix, {"v": 1})
    assert store.get(raw_key) == {"v": 1}
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        write(db, *suffix, None)
        assert read(db, *suffix, default=missing) is None
        db.rollback()
    assert read(store, *suffix) == {"v": 1}
