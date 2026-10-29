import copy
import pytest
from report_agent.task_context import pool_review_material_refs, expand_review_material_refs


def test_identical_lists_share_pool_and_round_trip_without_changing_scope():
    refs=[{"type":"ContentNode","id":str(i),"version":1} for i in range(24)]
    packet={"objects_complete":True,"requirements":[{"scope_id":str(i),"material_refs":copy.deepcopy(refs)} for i in range(10)],"objects":[{"ref":refs[0]}]}
    original=copy.deepcopy(packet)
    view=pool_review_material_refs(packet)
    assert packet==original and expand_review_material_refs(view)==original
    assert len(view["material_refs_pool"])==1 and all(r["material_refs_pool_index"]==0 for r in view["requirements"])
    assert all("material_refs" not in r for r in view["requirements"])


def test_different_versions_or_order_are_not_conflated():
    refs=[{"type":"ContentNode","id":str(i),"version":1} for i in range(12)]
    other=copy.deepcopy(refs);other[0]["version"]=2
    packet={"requirements":[{"material_refs":refs},{"material_refs":other},{"material_refs":list(reversed(refs))}]}
    view=pool_review_material_refs(packet)
    assert expand_review_material_refs(view)==packet and "material_refs_pool" not in view


def test_invalid_reference_fails_closed():
    with pytest.raises(ValueError):
        expand_review_material_refs({"material_refs_pool":[],"requirements":[{"material_refs_pool_index":0}]})
