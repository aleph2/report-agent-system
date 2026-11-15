"""Offline contracts plus opt-in checks against the dedicated new graph.
"""


import pytest

from report_agent.errors import ActionRejected
from report_agent.knowledge import Knowledge


def test_description_and_embedding_are_lazy(monkeypatch):
    monkeypatch.setenv("REPORT_GRAPH_URI", "bolt://127.0.0.1:17687")
    k = Knowledge("offline")
    assert k._driver is None
    assert k.uri.endswith(":17687")


@pytest.mark.parametrize("project", ["", " ", None, 3, "x\x00y"])
def test_bad_namespace(project):
    with pytest.raises(ActionRejected):
        Knowledge(project)


def test_provenance_normalization_and_namespace():
    k = Knowledge("p", embedding=False)
    assert k._provenance(["s", {"id": "s2", "locator": "page 7", "project_id": "p"}]) == [
        {"source_id": "s", "locator": ""}, {"source_id": "s2", "locator": "page 7"}]
    assert k._driver is None


def test_read_many_empty_is_lazy():
    k = Knowledge("offline", embedding=False, writable=False)
    assert k.read_many([]) == []
    assert k._driver is None


@pytest.mark.parametrize("ids", [None, "fact-id", {"id": "fact-id"}, [""], ["valid", None]])
def test_read_many_invalid_input_before_connecting(ids):
    k = Knowledge("offline", embedding=False)
    with pytest.raises(ActionRejected):
        k.read_many(ids)
    assert k._driver is None
