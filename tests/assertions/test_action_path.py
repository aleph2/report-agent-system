from uuid import uuid4
from dataclasses import replace

import pytest

from report_agent import assertions
from report_agent.assertion_host import AssertionHost, Grant


def test_exact_repeat_survives_authority_change_but_not_read_revocation(tmp_path):
    host = AssertionHost(tmp_path)
    grant = Grant(str(uuid4()), "writer", "task", "attempt", "plan", {"object"}, set(), {"ask"})
    host.authorize(grant)
    ctx = host.bind(grant, native_call_id="call", action="ask")
    data = dict(subject="object", claim=dict(kind="question", text="Which issue?", affects="other"))
    saved = assertions.ask(ctx, **data)
    host.authorize(replace(grant, actions=set()))
    assert assertions.ask(ctx, **data) == saved
    with pytest.raises(ValueError, match="CONFLICT"):
        assertions.ask(ctx, **{**data, "claim": dict(data["claim"], text="Revised")})
    with pytest.raises(PermissionError):
        assertions.ask(host.bind(grant, native_call_id="next", action="ask"), **data)
    host.revoke(grant)
    with pytest.raises(PermissionError):
        assertions.ask(ctx, **data)


@pytest.mark.parametrize("quote", ["hidden sentence", "invented sentence"])
def test_unoffered_source_rejected_before_reading_page(tmp_path, quote):
    host = AssertionHost(tmp_path)
    grant = Grant(str(uuid4()), "coordinator", "task", "attempt", "plan", {"object"}, set(),
                  {"assert_source"}, resources={"sources": {"private": {"pages": {"1": "hidden sentence"}}}})
    ctx = host.issue(grant, "assert_source", "call")
    claim = dict(kind="source", predicate="example", state="value", value="test", coverage="object",
                 citation=dict(source_version="private", page=1, quote=quote))
    with pytest.raises(ValueError, match="^C4: a reference was outside the issued packet$"):
        assertions.assert_source(ctx, subject="object", claim=claim)
