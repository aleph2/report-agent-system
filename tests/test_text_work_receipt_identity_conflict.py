"""Synthetic stored-receipt fault injection must not be hidden by cache reuse."""
from copy import deepcopy
import json
import os
from pathlib import Path

from langchain_core.messages import AIMessage

from report_agent.store import encode
from test_agent_duty_trace_cases import action, result_value, tool_reply
from test_agent_result_delivery import run_role
from test_bounded_review import Model
from test_decision_data import activate
from test_hierarchical_content import seed
from test_task_supervision import ws, offline
from test_text_work import content


async def test_same_receipt_key_with_different_stored_identity_is_explicitly_rejected(ws, tmp_path):
    cs, _, refs, snapshot, _ = seed(ws)
    activate(ws)
    originals = deepcopy(cs.list_objects())
    model = Model(json.dumps(content()))
    root = Path(os.environ.get("RECEIPT_CONFLICT_EVIDENCE", str(tmp_path / "evidence")))
    root.mkdir(parents=True, exist_ok=True)
    args = {"objective": "Describe the supplied synthetic rule", "object_type": "ContentNode", "input_refs": [refs["claim"]]}
    observed = {"fault_injection": "Host changes only authority_digest of a synthetic completed receipt; no real historical data touched."}

    def inject_fault(messages):
        message = tool_reply(messages, "first")
        observed["first_public"] = message.model_dump()
        (root / "capture.json").write_text(json.dumps(observed, ensure_ascii=False, indent=2), encoding="utf-8")
        work = result_value(message)
        key = "text_work_receipt:" + work["text_work_id"]
        original_receipt = deepcopy(ws.store.get(key))
        corrupted = deepcopy(original_receipt)
        corrupted["authority_digest"] += ":synthetic-conflict"
        ws.store.set(key, corrupted)
        observed.update(first_work=work, key=key, receipt_before_fault=original_receipt,
                        injected_receipt=deepcopy(corrupted), actor_id=work["actor_id"],
                        first_parent=deepcopy(ws.store.get("text_work:" + work["actor_id"] + ":first")))
        return action("process_report_content", "second", operation_id="second", **args)

    def inspect(messages):
        observed["second_public"] = tool_reply(messages, "second").model_dump()
        return AIMessage(content="Received synthetic receipt-conflict outcome; no retry or adoption.")

    try:
        await run_role(ws, "writer", [action("process_report_content", "first", operation_id="first", **args),
            inject_fault, inspect], refs, snapshot, model)
    except Exception as exc:
        observed["execution_error"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        observed["calls"] = model.calls
        (root / "capture.json").write_text(json.dumps(observed, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            with ws.store.connect() as db:
                observed["producer_state"] = {r[0]: json.loads(r[1]) for r in db.execute(
                    "SELECT key,value FROM state WHERE key LIKE 'text_work:%' OR key LIKE 'text_work_receipt:%'")}
                observed["analyses"] = {r[0]: json.loads(r[1]) for r in db.execute("SELECT operation,data FROM analyses")}
            observed.update(events=ws.store.events(), objects=cs.list_objects())
        except Exception as exc:
            observed["observer_error"] = {"type": type(exc).__name__, "message": str(exc)}
            raise
        finally:
            (root / "capture.json").write_text(json.dumps(observed, ensure_ascii=False, indent=2), encoding="utf-8")
    assert "TEXT_WORK_RECEIPT_IDENTITY_CONFLICT" in observed["second_public"]["content"]
    assert len(model.calls) == 1
    assert encode(ws.store.get(observed["key"])) == encode(observed["injected_receipt"])
    assert observed["producer_state"]["text_work:" + observed["actor_id"] + ":first"] == observed["first_parent"]
    assert observed["producer_state"]["text_work:" + observed["actor_id"] + ":second"]["state"] == "reserved"
    assert all(cs.read(o["ref"]) == o for o in originals)
    assert cs.list_objects("ContentNode") == [o for o in originals if o["ref"]["type"] == "ContentNode"]
