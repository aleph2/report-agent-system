"""An issued action and its read projections survive a cold restore."""
from dataclasses import replace

import pytest

from report_agent.assertion_host import AssertionHost, Grant
from report_agent.assertions import ask, followups, open_questions, packet, report_view, stale_derivations, status


def test_offline_archive_restores_queries_and_replays_only_the_original_action(tmp_path):
    writer = Grant(principal="a56607cd-9b2a-49bd-9202-76217334caab", role="writer",
                   task="work-item-1", attempt="attempt-1", plan="plan-1", subjects=frozenset({"A"}),
                   packet=frozenset(), actions=frozenset({"ask"}))
    original = AssertionHost(tmp_path/"original")

    def issue_question(host):
        host.authorize(writer)
        ctx = host.bind(writer, native_call_id="call-1", action="ask")
        return ask(ctx, subject="A", claim={"kind": "question", "text": "Which source applies?", "affects": "other"})

    saved = issue_question(original)
    key = saved["id"]
    snapshot = "review-snapshot"
    resource = {"members": {"one": key}, "word": b"frozen Word", "excel": b"frozen Excel"}
    reader = replace(writer, task="work-item-2", attempt="attempt-2", snapshot=snapshot,
                     packet=frozenset({key, snapshot}), resources={"snapshots": {snapshot: resource}})

    def views(host):
        host.authorize(reader)
        ctx = host.bind(reader, native_call_id="read-1", action="ask")
        return (status(ctx, key), packet(ctx), stale_derivations(ctx, key), followups(ctx),
                open_questions(ctx), report_view(ctx, snapshot))

    before = views(original)
    archive = tmp_path/"assertions.jsonl"
    original.commission.export(archive)
    reopened = AssertionHost(tmp_path/"reopened")
    reopened.commission.restore(archive)
    # Migrating assertion history does not grant access to a new host.
    unissued = reopened.bind(writer, native_call_id="call-1", action="ask")
    with pytest.raises(PermissionError):
        ask(unissued, subject="A", claim={"kind": "question", "text": "Which source applies?", "affects": "other"})
    assert issue_question(reopened) == saved
    substitution = replace(reader, resources={"snapshots": {
        snapshot: {**resource, "word": b"substituted after restore"},
    }})
    with pytest.raises(ValueError, match="Frozen resource binding conflict"):
        reopened.authorize(substitution)
    with pytest.raises(PermissionError):
        packet(reopened.bind(substitution, native_call_id="read-1", action="ask"))
    assert views(reopened) == before
    assert before[3]["open_questions"] == [key]
    assert before[4][0]["id"] == key
    assert before[5]["members"] == {"one": key}
    with reopened.commission._store.reader() as db:
        assert db.execute("SELECT count(*) FROM operations").fetchone()[0] == 1
