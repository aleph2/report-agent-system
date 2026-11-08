from dataclasses import replace
from uuid import uuid4

import pytest

from report_agent import assertions
from report_agent import assertion_host


def test_failed_judgment_rolls_back_accompanying_question(tmp_path):
    host = assertion_host.AssertionHost(tmp_path)
    actor = str(uuid4())
    ask = assertion_host.Grant(actor, "writer", "task", "ask-attempt", "plan",
                               {"slope"}, set(), {"ask"})
    ask_ctx = host.issue_once(ask, "ask", "call-1")
    question = {"kind": "question", "text": "Which interval applies?", "affects": "other"}
    ref = assertion_host.question_id(ask_ctx, "slope", question)
    save = replace(ask, attempt="save-attempt", packet={ref}, actions={"save_judgment"})
    save_ctx = host.issue_once(save, "save_judgment", "call-1")
    with pytest.raises(ValueError):
        assertions.save_judgment(save_ctx, subject="slope",
                                 claim={"kind": "judgment", "basis": "gap", "question": ref},
                                 accompanying_question=(ask_ctx, question))
    assert host.recover_receipt(ask_ctx.operation_id) is None
    assert host.recover_receipt(save_ctx.operation_id) is None
    foreign = replace(ask, principal=str(uuid4()))
    foreign_ctx = host.issue_once(foreign, "ask", "call-1")
    with pytest.raises(PermissionError):
        assertions.save_judgment(save_ctx, subject="slope", claim={"question":ref},
                                 accompanying_question=(foreign_ctx, question))
    assert host.recover_receipt(foreign_ctx.operation_id) is None
