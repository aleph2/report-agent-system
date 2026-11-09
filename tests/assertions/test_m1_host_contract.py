from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from report_agent import assertions
from report_agent.assertion_host import AssertionHost, Grant


def source_case(root):
    version = "edition"
    quote = "Observed on 2025-04-19. Height was 18 m."
    source = {"pages": {"1": quote}}
    host = AssertionHost(root)
    grant = Grant(str(uuid4()), "coordinator", "t1", "try1", "p", {"A"}, {version},
                  {"assert_source"}, resources={"sources": {version: source}})
    ctx = host.issue(grant, "assert_source", "native-1")
    claim = dict(kind="source", predicate="height", state="value", value=18,
                 unit="m", coverage="A", citation=dict(source_version=version, page=1, quote=quote))
    return host, grant, ctx, claim


def test_recover_after_revocation_is_read_only_and_case_scoped(tmp_path):
    host, grant, ctx, claim = source_case(tmp_path / "original")
    saved = assertions.assert_source(ctx, subject="A", claim=claim)
    host.revoke(grant)
    with pytest.raises(PermissionError):
        assertions.assert_source(ctx, subject="A", claim=claim)
    recovered = AssertionHost(tmp_path / "original").recover_receipt(ctx.operation_id)
    assert recovered["result"] == saved and recovered["binding"] == grant.binding
    assert recovered["digest"] and recovered["created_at"] == saved["recorded_at"]
    assert host.recover_receipt("unknown") is None
    assert AssertionHost(tmp_path / "other").recover_receipt(ctx.operation_id) is None
    assert "recover_receipt" not in assertions.__all__
    assert not hasattr(ctx, "recover_receipt")


def test_produced_ids_are_narrowed_by_issuer_task_subject_and_kind(tmp_path):
    host, grant, ctx, claim = source_case(tmp_path)
    record = assertions.assert_source(ctx, subject="A", claim=claim)
    params = dict(actor=grant.principal, task=grant.task, subject="A", kind="source")
    assert host.commission.produced_ids(**params) == {record["id"]}
    for k in params:
        assert not host.commission.produced_ids(**(params | {k: "different"}))


def test_source_action_refuses_removed_observation_time_without_saving(tmp_path):
    host, grant, ctx, claim = source_case(tmp_path)
    with pytest.raises(TypeError, match="unexpected keyword argument 'observed_at'"):
        assertions.assert_source(ctx, subject="A", claim=claim, observed_at="1999-01-01")
    assert host.recover_receipt(ctx.operation_id) is None
    assert not host.commission.produced_ids(actor=grant.principal, task=grant.task, subject="A", kind="source")


def test_engineering_date_is_a_cited_value(tmp_path):
    host, _, ctx, claim = source_case(tmp_path)
    claim.update(predicate="survey_date", value="2025-04-19", unit=None)
    saved = assertions.assert_source(ctx, subject="A", claim=claim)
    assert saved["claim"]["value"] == "2025-04-19"
    assert saved["claim"]["citation"] == claim["citation"]
    assert saved["observed_at"] is None and saved["recorded_at"]
    assert host.recover_receipt(ctx.operation_id)["result"] == saved


def test_old_tagged_archive_roundtrips_without_rewriting_legacy_times(tmp_path):
    archive = Path(__file__).parents[2] / "docs/verification/stage1-s3-20261108/fake03-assertions.jsonl"
    host = AssertionHost(tmp_path / "new")
    host.commission.restore(archive)
    target = tmp_path / "copy.jsonl"
    host.commission.export(target)
    assert archive.read_bytes() == target.read_bytes()

def test_issue_once_is_atomic_and_cannot_reactivate_a_revoked_native_call(tmp_path):
    host, base, _, _ = source_case(tmp_path)
    grant = replace(base, attempt="native-7", actions={"ask"}, resources={})
    def ask():
        ctx = host.issue_once(grant, "ask", "7")
        return assertions.ask(ctx, subject="A", claim=dict(kind="question", text="Why?", affects="other"))
    with ThreadPoolExecutor(2) as pool:
        first, second = pool.map(lambda _: ask(), range(2))
    assert first == second and host.lookup(grant.key) == grant
    with pytest.raises(ValueError, match="CONFLICT"):
        host.issue_once(replace(grant, plan="other"), "ask", "7")
    host.revoke(grant)
    assert host.lookup(grant.key) is None
    with pytest.raises(PermissionError):
        ask()
    assert AssertionHost(tmp_path).recover_receipt(first["operation_id"])["result"] == first
