"""Recovery and producer exclusivity through the normal host-issued actions."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from threading import Barrier
from uuid import uuid4

import pytest

from report_agent import assertions
from report_agent.assertion_host import AssertionHost, Grant

from .test_action_checks import Case


def receipt(host, operation):
    with host.commission._store.reader() as db:
        found = db.execute("SELECT result FROM operations WHERE id=?", (operation,)).fetchone()
        return json.loads(found[0]) if found else None


def test_lost_first_reply_does_not_complete_second_action_or_recheck_old_target(tmp_path):
    case = Case(tmp_path)
    targets = [
        case.apply("owner", "assert_source", dict(
            kind="source", predicate=predicate, state="unknown", coverage="sample"
        ))
        for predicate in ("area", "size")
    ]
    owner = Grant(str(uuid4()), "owner", "check-both", "attempt", "pilot", {"sample"},
                  frozenset(case.packet), {"confirm", "retract"})
    host = case.host
    host.authorize(owner)
    first = host.bind(owner, native_call_id="first", action="confirm")
    second = host.bind(owner, native_call_id="second", action="confirm")
    confirmations = [dict(subject="sample", claim=dict(
        kind="act", effect="confirm", target=key, reason="reviewed"
    )) for key in targets]

    # The public call commits. Only delivery of its return value to the caller fails.
    with pytest.raises(ConnectionError, match="reply lost"):
        assertions.confirm(first, **confirmations[0])
        raise ConnectionError("reply lost")
    original = receipt(host, first.operation_id)
    assert original is not None and receipt(host, second.operation_id) is None
    assert assertions.status(second, targets[1])["status"] == "proposed"

    withdrawal = host.bind(owner, native_call_id="withdraw", action="retract")
    assertions.retract(withdrawal, subject="sample", claim=dict(
        kind="act", effect="retract", target=targets[0], reason="withdrawn after confirmation"
    ))
    # New host instance and the two *original* logical operation IDs.
    restored = AssertionHost(tmp_path)
    first = restored.bind(owner, native_call_id="first", action="confirm")
    second = restored.bind(owner, native_call_id="second", action="confirm")
    assert assertions.status(first, targets[0])["status"] == "retracted"
    assert assertions.confirm(first, **confirmations[0]) == original
    assert receipt(restored, second.operation_id) is None
    fresh_first = restored.bind(owner, native_call_id="different-first", action="confirm")
    with pytest.raises(ValueError, match="C11"):
        assertions.confirm(fresh_first, **confirmations[0])
    finalized = assertions.confirm(second, **confirmations[1])
    assert finalized == receipt(restored, second.operation_id)
    assert assertions.confirm(second, **confirmations[1]) == finalized
    assert assertions.status(second, targets[1])["status"] == "confirmed"


def test_valid_writers_race_for_same_producer_and_out_of_scope_writer_is_independent(tmp_path):
    case = Case(tmp_path)
    fact = case.fact()
    criterion = case.method([[dict(classification="some", when=[dict(predicate="points", value=4)])]])
    row = dict(subject="sample", claim=case.judgment(criterion),
               grounds=[dict(assertion_id=fact, purpose="classification", proposition="points")])
    grants = [Grant(str(uuid4()), "writer", "work-"+str(i), "first", "pilot",
                    {"sample"}, frozenset(case.packet), {"save_judgment"}, resources=case.resources)
              for i in range(2)]
    outside = replace(grants[0], subjects=frozenset({"elsewhere"}), task="outside")
    invalid = case.host.issue(outside, "save_judgment", "unauthorized")
    with pytest.raises(PermissionError, match="outside assignment"):
        assertions.save_judgment(invalid, **row)
    assert receipt(case.host, invalid.operation_id) is None

    ready = Barrier(2)
    contexts = [case.host.issue(g, "save_judgment", "save-native") for g in grants]

    def save(ctx):
        ready.wait(timeout=10)
        try:
            return assertions.save_judgment(ctx, **row)
        except ValueError as error:
            assert "C11" in str(error), str(error)
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, contexts))
    [winner] = [i for i, saved in enumerate(results) if saved is not None]
    loser = 1 - winner
    assert receipt(case.host, contexts[winner].operation_id) == results[winner]
    assert receipt(case.host, contexts[loser].operation_id) is None
    assert assertions.save_judgment(contexts[winner], **row) == results[winner]
    with case.host.commission._store.reader() as db:
        assert db.execute("SELECT actor FROM producers WHERE plan=? AND subject=?",
                          ("pilot", "sample")).fetchone()[0] == grants[winner].principal
        assert db.execute("SELECT COUNT(*) FROM assertions WHERE action='save_judgment'").fetchone()[0] == 1
