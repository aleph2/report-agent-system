import pytest

from report_agent import plan_inputs
from report_agent.content_store import Actor, ContentStore
from report_agent.errors import ActionForbidden
from report_agent.store import Store


def test_versioned_inputs_freeze_and_roll_back_with_the_proposal(tmp_path):
    store = Store(tmp_path)
    store.initialize({"goal": "test", "sources": [{"id": "a", "title": "a", "content": "synthetic", "coverage": "complete"}]})
    cs = ContentStore(store)
    actor = Actor("coordinator", "coordinator", "plan")
    with store.connect() as db:
        assert plan_inputs.get_draft(db) is None
        plan_inputs.save_skeleton(db, {"sections": [], "version": 1})
        plan_inputs.save_text_profiles(db, {"reviewed": {"id": "a"}})
        plan_inputs.save_draft(db, {"revision": 1, "items": {}}, actor=actor)
        initial = plan_inputs.current_refs(db)
        assert {ref["type"] for ref in plan_inputs.frozen_refs(db)} == {"PlanSkeleton", "PlanTextProfiles"}
    with pytest.raises(RuntimeError, match="rollback"), store.connect() as db:
        plan_inputs.save_draft(db, {"revision": 2, "items": {"object": {}}}, actor=actor)
        raise RuntimeError("rollback")
    reopened = Store(tmp_path)
    with reopened.connect() as db:
        assert plan_inputs.current_refs(db) == initial
        plan_inputs.save_draft(db, {"revision": 2, "items": {"object": {}}}, actor=actor)
        current = plan_inputs.current_refs(db)
        assert db.execute("SELECT key FROM state WHERE key IN (?,?,?)", (
            "commission_skeleton", "commission_text_profiles", "commission_planning_draft")).fetchall() == []
    old, new = (next(ref for ref in refs if ref["type"] == "PlanDraft") for refs in (initial, current))
    assert cs.read(old)["payload"]["revision"] == 1
    assert cs.read(new)["previous_ref"] == old
    assert cs.read(new)["owner_id"] == actor.id
    assert plan_inputs.get_draft(reopened)["revision"] == 2
    writer = Actor("writer", "writer", "write")
    for ref in current:
        with pytest.raises(ActionForbidden):
            cs.read_context(writer, ref)
    with store.connect() as db:
        snapshot = cs._insert(db, actor, "DocumentSnapshot", {"refs": current})
    with pytest.raises(ActionForbidden):
        cs.read_context(writer, snapshot)


def test_historical_inputs_read_without_writes_and_pin_on_proposal(tmp_path):
    store = Store(tmp_path)
    store.initialize({"goal": "test", "sources": [{"id": "a", "content": "synthetic", "coverage": "complete"}]})
    profile = {"template": {"id": "template"}}
    store.set("commission_text_profiles", profile)
    with store.connect() as db:
        db.execute("PRAGMA query_only=ON")
        assert plan_inputs.get_text_profiles(db) == profile
        assert plan_inputs.current_refs(db) == []
        assert plan_inputs.get_skeleton(db, "missing") == "missing"
    cs = ContentStore(store)
    with store.connect() as db:
        refs = plan_inputs.frozen_refs(db)
        assert plan_inputs.save_text_profiles(db, profile) == refs[0]
        assert plan_inputs.frozen_refs(db) == refs
    assert len(refs) == 1 and cs.read(refs[0])["payload"] == profile
    assert store.get("commission_text_profiles") == profile
