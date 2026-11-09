"""Host intake records retain their origin and cannot grant plan approval."""
import pytest

from report_agent import commission_imports as intake, plan_authority
from report_agent.content_store import ContentStore
from report_agent.errors import ActionRejected
from report_agent.store import Store


def test_file_roles_keep_versioned_provenance_without_approving_a_plan(tmp_path):
    store = Store(tmp_path)
    cs = ContentStore(store)
    roles = {"scope.txt": {"id": "scope", "purpose": "commission"}}
    first = intake.install_source_roles(store, roles)
    assert intake.install_source_roles(store, roles) == first
    newer = intake.install_source_roles(store, {**roles, "drawing.pdf": {"id": "drawing", "purpose": "template"}})
    assert newer["version"] == first["version"] + 1
    with pytest.raises(ActionRejected, match="SOURCE_ROLE_IMMUTABLE"):
        intake.install_source_roles(store, {"scope.txt": {"id": "scope", "purpose": "template"}})
    assert cs.read(first)["payload"] == roles and cs.read(first)["owner_id"] == "host"
    assert intake.source_roles(store)["drawing.pdf"]["purpose"] == "template"
    assert store.get("commission_source_roles") is None
    assert plan_authority.decision_ref(store) is None
