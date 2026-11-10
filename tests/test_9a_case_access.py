"""Supplied files are a case boundary, not another approval or grant."""
from types import SimpleNamespace
import pytest
from report_agent import commission_imports
from report_agent.catalog import Catalog
from report_agent.content_store import ContentStore
from report_agent.errors import ActionRejected
from report_agent.hierarchical_tools import actor_for
from report_agent.source_use import validate_source_versions
from report_agent.store import Store


def test_fresh_supplied_files_need_no_file_policy_and_other_catalog_files_stay_out(tmp_path):
    store=Store(tmp_path)
    store.initialize(dict(goal="Report",commission_checkpoint_required=True,
        sources=[dict(id="supplied",title="Supplied",content="input",coverage="complete")],
        source_use=dict(source_ids=["supplied"],authorization_origin="Provided")))
    cs=ContentStore(store)
    assert commission_imports.source_policy_ref(store) is None
    workspace=SimpleNamespace(store=store)
    validate_source_versions(workspace,actor_for("coordinator"),["supplied"])
    other=Catalog(store).import_file("other.txt",b"Not supplied for this commission")["source"]["id"]
    with pytest.raises(ActionRejected,match="CASE_SOURCE"):
        validate_source_versions(workspace,actor_for("coordinator"),[other])
    with store.connect() as db:
        assert not db.execute("SELECT key FROM state WHERE key LIKE 'source_use_authority%'").fetchall()
