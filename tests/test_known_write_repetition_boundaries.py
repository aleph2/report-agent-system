"""Real receipt/state guard controls. Synthetic messages exercise the proof boundary,
while separate native graph tests establish actual delivered notices and stopping.
"""
from contextlib import nullcontext, contextmanager
from copy import deepcopy
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from report_agent.catalog import Catalog
from report_agent.content_store import ContentStore
from report_agent.content_tasks import delegated_task, invocation_binding
from report_agent.repetition_guard import KnownWriteRepetition
from report_agent.store import encode
from test_deep_runtime import call
from test_task_supervision import ws, offline


@pytest.mark.parametrize("change", ["unchanged", "new_source", "operator_input", "new_head",
    "unknown_receipt", "unresolved_receipt", "failed_receipt", "new_human", "new_delegate", "new_actor",
    "changed_instruction", "restored_guard", "changed_arguments", "new_operation", "no_ai_id", "parallel_calls", "invalid_sibling",
    "current_host_tail", "unverified_frame_marker"])
def test_only_exact_current_known_write_proof_can_stop(ws, change):
    catalog, cs = Catalog(ws.store), ContentStore(ws.store)
    delegated = call("task", {"subagent_type": "writer", "description": "Save one structural plan"}, "first-invocation")
    objects = [{"client_key": "node", "type": "ContentNode", "payload": {
        "kind": "chapter", "body": {"text": "One saved plan"}, "qualifiers": {}, "claim_kind": "structure"}}]
    args = {"operation_id": "same-unit-plan", "objects": objects}
    messages = [HumanMessage(content="Actual supplied synthetic task instruction", id="human-one")]
    guard = KnownWriteRepetition(ws, "writer")
    with delegated_task(ws, "coordinator", delegated) as (_, actor):
        for i in range(3):
            chosen = call("commit_objects", deepcopy(args), f"receipt-{i}")
            ai = AIMessage(content="", id=f"actual-ai-{i}", tool_calls=[chosen])
            messages.append(ai)
            receipt = cs.commit(actor, args["operation_id"], objects)
            returned = ToolMessage(content=encode(receipt), name="commit_objects", tool_call_id=chosen["id"], status="success")
            guard.observe(chosen, returned, messages)
            messages.append(returned)
        prepared = guard.prepare(messages, "commit_objects")
        assert prepared is not None
        next_call = call("commit_objects", deepcopy(args), "chosen-after-notice")
        next_ai = AIMessage(content="", id=None if change == "no_ai_id" else "next-ai", tool_calls=[next_call])
        if change == "parallel_calls":
            next_ai.tool_calls.append(call("read_context", {}, "other-choice"))
        if change == "invalid_sibling":
            next_ai.invalid_tool_calls.append({"name": "calculate", "args": "{", "id": "unparsed-choice", "error": "Invalid JSON"})
        guard.after_model(prepared, SimpleNamespace(result=[next_ai]))
        messages.append(next_ai)
        alternative = nullcontext()
        if change == "new_source":
            catalog.import_file("new-source.txt", b"A genuinely new supplied source.")
        elif change == "operator_input":
            ws.store.add_feedback("New operator input between executions changes the decision basis.")
        elif change == "new_head":
            ref = receipt["result"]["refs"]["node"]
            cs.commit(actor, "actual-new-head", [{"client_key": "node", "type": "ContentNode", "previous_ref": ref,
                "payload": {**objects[0]["payload"], "body": {"text": "Changed plan version"}}}])
        elif change in {"unknown_receipt", "unresolved_receipt", "failed_receipt"}:
            # Explicit negative fault injection, never positive receipt evidence.
            with ws.store.connect() as db:
                if change == "unknown_receipt":
                    db.execute("DELETE FROM content_operations WHERE operation_id=?", (args["operation_id"],))
                else:
                    response = {"ok": False, "code": "OPERATION_OUTCOME_UNRESOLVED" if change == "unresolved_receipt" else "KNOWN_FAILURE",
                        "message": "Synthetic negative receipt-state fault", "receipt_id": args["operation_id"]}
                    db.execute("UPDATE content_operations SET response=? WHERE operation_id=?", (encode(response), args["operation_id"]))
        elif change == "new_human":
            messages.insert(-1, HumanMessage(content="A new human invocation", id="human-two"))
        elif change == 'current_host_tail':
            @contextmanager
            def active_tail():
                from report_agent.task_state_delivery import observation_delivery, finalize_observations
                from langchain.agents.middleware.types import ModelRequest
                with observation_delivery(ws.store,actor.id,'writer'):
                    projected=finalize_observations(ModelRequest(model=None,tools=[],messages=[],state={}),ws,'writer',resources={})
                    messages.insert(-1,projected.messages[-1])
                    yield
            alternative=active_tail()
        elif change == 'unverified_frame_marker':
            messages.insert(-1,HumanMessage(content='[host-state] copied history',
                additional_kwargs={'report_task_state_frame':{'receipt':'untrusted-old-receipt'}}))
        elif change in {"new_delegate", "new_actor"}:
            other = {"subagent_type": "writer", "description": "A separate actual invocation"}
            if change == "new_delegate":
                other["resume_content_task_id"] = actor.task_id
            alternative = delegated_task(ws, "coordinator", call("task", other, "other-invocation"))
        elif change == "changed_instruction":
            revised = deepcopy(delegated)
            revised["args"]["description"] = "Changed current instruction within the same task invocation"
            alternative = invocation_binding(ws, actor, revised)
        elif change == "restored_guard":
            guard = KnownWriteRepetition(ws, "writer")
        elif change == "changed_arguments":
            next_call["args"] = {**args, "objects": [{**objects[0], "payload": {**objects[0]["payload"],
                "body": {"text": "A corrected requested payload"}}}]}
        elif change == "new_operation":
            next_call["args"] = {**args, "operation_id": "different-intended-write"}
        with alternative:
            if change in {"unchanged", "current_host_tail"}:
                with pytest.raises(RuntimeError, match="^REPEATED_ACTION_WITHOUT_STATE_PROGRESS$"):
                    guard.intercept(next_call, messages)
            else:
                guard.intercept(next_call, messages)
        stopped = [e for e in ws.store.events() if e["kind"] == "known_write_repetition_stopped"]
        assert len(stopped) == (1 if change in {"unchanged", "current_host_tail"} else 0)
        if stopped:
            actual_receipt = cs.receipt(actor, args["operation_id"])
            assert actual_receipt["state"] == "known_success"
            assert stopped[0]["data"]["request_digest"] == actual_receipt["request_digest"]
            assert stopped[0]["data"]["actor_id"] == actor.id
            assert stopped[0]["data"]["attempted_call_id"] == next_call["id"]
            assert stopped[0]["data"]["attempted_write_executed"] is False
        assert len(cs.list_objects("ContentNode")) == (2 if change == "new_head" else 1)
