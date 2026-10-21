"""Transport and native validation tests; no model-quality evidence."""
import json
from copy import deepcopy

import httpx
import pytest
from langchain_core.messages import AIMessage, ToolMessage

from report_agent import deep_runtime
from report_agent.tool_transport import decode_object_arguments
from test_deep_runtime import Driver, invoke, observation, events
from test_hierarchical_content import ws, seed, review_item, submission


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv('LANGSMITH_TRACING', 'false')
    monkeypatch.setenv('LANGCHAIN_TRACING_V2', 'false')
    def denied(*a, **k):
        pytest.fail('NETWORK_FORBIDDEN')
    monkeypatch.setattr(httpx.Client, 'send', denied)
    monkeypatch.setattr(httpx.AsyncClient, 'send', denied)


SCHEMA = {'$defs': {'Ref': {'type': 'object'}}, 'properties': {
    'ref': {'anyOf': [{'$ref': '#/$defs/Ref'}, {'type': 'null'}]},
    'text': {'anyOf': [{'type': 'object'}, {'type': 'string'}]},
    'unknown': {}, 'missing': {'$ref': '#/$defs/Missing'}}}


@pytest.mark.parametrize('value', ['[]', '1', 'null', '"{}"', "{'id':1}",
    '<parameter>1</parameter>', '{"a":1} trailing', '{"a":1,"a":2}',
    '{"a":{"x":1,"x":2}}', '{"x":NaN}', '{"x":Infinity}', '{"x":1e999}'])
def test_ambiguous_or_nonobject_json_not_repaired(value):
    args = {'ref': value}
    assert decode_object_arguments(args, SCHEMA) == (args, [])


def test_schema_driven_once_only_no_mutation():
    args = {k: '{"id":"x","nested":"{}"}' for k in ('ref', 'text', 'unknown', 'missing', 'extra')}
    before = deepcopy(args)
    decoded, fields = decode_object_arguments(args, SCHEMA)
    assert fields == ['ref']
    assert decoded['ref'] == {'id': 'x', 'nested': '{}'}
    assert all(decoded[k] == before[k] for k in args if k != 'ref')
    assert args == before


async def test_native_review_transport_preserves_actor_receipt_and_idempotency(tmp_path):
    from test_agent_duty_trace_cases import result_value
    from test_bounded_review import review_call
    from test_decision_data import activate
    from test_task_supervision import ws as native_ws

    ws = native_ws.__wrapped__(tmp_path)
    activate(ws)
    cs, _, refs, snapshot, _ = seed(ws)
    original_nodes = deepcopy(cs.list_objects("ContentNode"))
    original_sources = deepcopy(ws.store.manifest["sources"])
    source = next(r for r in cs.read(snapshot)["payload"]["refs"] if r["type"] == "SourceArtifact")
    captured, packets = {}, []

    def received(messages, name):
        return result_value(next(m for m in reversed(messages) if isinstance(m, ToolMessage) and m.name == name))

    def check_call(identity):
        action = invoke("perform_assigned_review", operation_id="same-review", scope_ids=["rule-comparison"],
            source_selections=[], content_selections=[])
        action.tool_calls[0]["id"] = identity
        return action

    def first_check(messages):
        context = received(messages, "read_context")
        assert context["result"]["objects"] == [cs.read(refs["claim"])]
        captured["read_receipt"] = context["receipt_id"]
        return check_call("first-check")

    def repeat(messages):
        first = received(messages, "perform_assigned_review")
        captured["first"] = deepcopy(first)
        captured["record"] = deepcopy(cs.read(first["review_ref"]))
        return check_call("repeat-check")

    def verify_repeat(messages):
        second = received(messages, "perform_assigned_review")
        assert second["reused"] is True
        assert {k: v for k, v in second.items() if k != "reused"} == {
            k: v for k, v in captured["first"].items() if k != "reused"}
        assert cs.read(second["review_ref"]) == captured["record"]
        return AIMessage(content="Same-operation replay retained the exact original review.")

    def parent_observes(messages):
        records = received(messages, "read_feedback")["result"]["records"]
        assert records == [captured["record"]]
        captured["parent_observed"] = True
        return AIMessage(content="The scoped defect is recorded once; no whole-report approval.")

    def checker(messages):
        packet = json.loads(messages[-1].content)
        packets.append(deepcopy(packet))
        indexes = [next(i for i, entry in enumerate(packet["evidence"])
            if entry.get("object", {}).get("ref") == ref) for ref in (refs["claim"], source)]
        assert [packet["evidence"][i]["object"] for i in indexes] == [cs.read(refs["claim"]), cs.read(source)]
        return AIMessage(content=json.dumps({"items": [{
            "scope_id": "rule-comparison", "checked_requirement_indexes": [0],
            "execution_state": "completed", "verdict": "not_satisfied",
            "observations": [{"evidence_index": indexes[0], "locator": "claim", "observation": "For adopted class B use 70."},
                             {"evidence_index": indexes[1], "locator": "source", "observation": "Class B permits 75 to 100."}],
            "check_results": [{"requirement_index": 0, "execution_state": "completed",
                "result": "70 falls outside 75 to 100.", "observation_indexes": [0, 1], "remaining": ""}],
            "coverage": {"checked": ["rule comparison"], "unchecked": [], "blocked": [], "basis": "Original assigned inputs."},
            "reason": "Retain this local defect.", "findings": []}]}))

    driver = Driver(coordinator=[AIMessage(content="", tool_calls=[review_call(snapshot, refs, reads=[source])]),
        invoke("read_feedback"), parent_observes],
        reviewer=[invoke("read_context", target_ref=json.dumps(refs["claim"])), first_check, repeat, verify_repeat],
        text_tool=[checker])
    result = await deep_runtime.run_report(ws, driver)
    assert result["last_error"] is None, result
    records = cs.list_objects("ReviewRecord")
    assert records == [captured["record"]] and captured["parent_observed"]
    record = records[0]
    assert record["owner_id"] == "content:reviewer:" + record["task_id"]
    assert len(packets) == 1 and sum(role == "text_tool" for role, _, _ in driver.calls) == 1
    assert [e["fields"] for e in events(ws, "deep_tool_argument_decoded")] == [["target_ref"]]
    raw_reads = [e for e in events(ws, "deep_tool_start") if e["tool"] == "read_context"]
    assert raw_reads[0]["arguments"]["target_ref"] == json.dumps(refs["claim"])
    checks = [e for e in events(ws, "deep_tool_start") if e["tool"] == "perform_assigned_review"]
    assert len(checks) == 2 and checks[0]["arguments"] == checks[1]["arguments"]
    receipt_ids = [captured["read_receipt"], *[o["receipt_id"] for o in record["payload"]["items"][0]["observations"]]]
    with ws.store.connect() as db:
        for receipt_id in receipt_ids:
            observed = db.execute("SELECT actor_id FROM content_observations WHERE id=?", (receipt_id,)).fetchone()
            assert observed is not None and observed[0] == record["owner_id"]
    assert cs.list_objects("ContentNode") == original_nodes
    assert ws.store.manifest["sources"] == original_sources
    assert "rubric_grader" not in driver.created
    assert "submit_review" not in {tool["name"] for tool in driver.bindings["reviewer"][0]}


@pytest.mark.parametrize('fault', ['missing', 'unknown', 'wrong_version_type', 'missing_version', 'fake_receipt', 'foreign_receipt'])
async def test_decoded_review_still_requires_schema_and_observation(tmp_path, fault):
    from test_agent_duty_trace_cases import result_value
    from test_bounded_review import review_call
    from test_decision_data import activate
    from test_task_supervision import ws as native_ws

    ws = native_ws.__wrapped__(tmp_path)
    activate(ws)
    cs, owner, refs, snapshot, _ = seed(ws)
    original_nodes = deepcopy(cs.list_objects("ContentNode"))
    original_sources = deepcopy(ws.store.manifest["sources"])
    source = next(r for r in cs.read(snapshot)["payload"]["refs"] if r["type"] == "SourceArtifact")
    task_call = review_call(snapshot, refs, reads=[source])
    # This input/output-boundary test selects no optional completion-followup
    # plugin; it does not change task supervision or retry product policy.
    task_call["args"].pop("supervision_plugin")
    captured, packets = {}, []
    with ws.store.connect() as db:
        original_operations = db.execute("SELECT * FROM content_operations ORDER BY operation_id").fetchall()
    foreign = cs.read_context(owner, refs["claim"])["receipt_id"] if fault == "foreign_receipt" else None
    version_fault = fault in {"wrong_version_type", "missing_version"}
    if version_fault:
        version = "1" if fault == "wrong_version_type" else 999
        task_call["args"]["review_snapshot_ref"] = {**snapshot, "version": version}

    def received(messages, name):
        message = next(m for m in reversed(messages) if isinstance(m, ToolMessage) and m.name == name)
        return message, result_value(message)

    def checker(messages):
        packet = json.loads(messages[-1].content)
        packets.append(deepcopy(packet))
        assert not version_fault, "Invalid version must not reach independent checker"
        indexes = [next(i for i, e in enumerate(packet["evidence"])
            if e.get("object", {}).get("ref") == ref) for ref in (refs["claim"], source)]
        raw = {"items": [{"scope_id": "rule-comparison", "checked_requirement_indexes": [0],
            "execution_state": "completed", "verdict": "not_satisfied",
            "observations": [{"evidence_index": indexes[0], "locator": "claim", "observation": "Adopted B uses 70."},
                {"evidence_index": indexes[1], "locator": "source", "observation": "Class B permits 75 to 100."}],
            "check_results": [{"requirement_index": 0, "execution_state": "completed",
                "result": "70 is outside the supplied interval.", "observation_indexes": [0, 1], "remaining": ""}],
            "coverage": {"checked": ["rule comparison"], "unchecked": [], "blocked": [], "basis": "Exact assigned materials."},
            "reason": "Scoped comparison only.", "findings": []}]}
        if fault == "missing":
            del raw["items"]
        elif fault == "unknown":
            raw["owner_id"] = "content:coordinator"
        else:
            # The evidence_index remains valid: reject precisely the unsupported
            # receipt override, not a missing index masking the intended fault.
            raw["items"][0]["observations"][0]["receipt_id"] = foreign or "invented-receipt"
        captured["raw"] = json.dumps(raw)
        return AIMessage(content=captured["raw"])

    def reviewer_sees_rejection(messages):
        message, public = received(messages, "perform_assigned_review")
        assert message.status == "error" and public["ok"] is False
        assert public["code"] == "REVIEW_OUTPUT_CONTRACT_INVALID"
        diagnostic = json.loads(public["message"].split(": ", 1)[1])
        assert diagnostic["failure_phase"] == "output" and diagnostic["raw_response_received"] is True
        expected_location = ["items"] if fault == "missing" else ["owner_id"] if fault == "unknown" else ["items", 0, "observations", 0, "receipt_id"]
        expected_type = "missing" if fault == "missing" else "extra_forbidden"
        assert [(e["loc"], e["type"]) for e in diagnostic["errors"]] == [(expected_location, expected_type)]
        captured["diagnostic"] = diagnostic
        return AIMessage(content=json.dumps(public))

    def parent_sees_rejection(messages):
        message, public = received(messages, "task")
        if version_fault:
            assert message.status == "error" and public["ok"] is False
            if fault == "wrong_version_type":
                assert public["code"] == "NATIVE_TOOL_VALIDATION_ERROR", public
                assert "version" in public["diagnostic"] and "int_type" in public["diagnostic"]
            else:
                assert public["code"] == "NOT_FOUND", public
                assert snapshot["id"] in public["message"] and "999" in public["message"]
        else:
            assert public["code"] == "REVIEW_OUTPUT_CONTRACT_INVALID"
            assert captured["diagnostic"]["raw_operation"] in public["message"]
        captured["parent"] = deepcopy(public)
        return AIMessage(content="Actual rejection retained; no review saved or approval implied.")

    driver = Driver(coordinator=[AIMessage(content="", tool_calls=[task_call]), parent_sees_rejection],
        reviewer=[invoke("perform_assigned_review", operation_id="invalid-review", scope_ids=["rule-comparison"],
            source_selections=[], content_selections=[]), reviewer_sees_rejection], text_tool=[checker])
    result = await deep_runtime.run_report(ws, driver)
    assert result["last_error"] is None, result
    assert captured["parent"] and cs.list_objects("ReviewRecord") == []
    assert len(packets) == (0 if version_fault else 1)
    assert sum(role == "text_tool" for role, _, _ in driver.calls) == len(packets)
    if version_fault:
        assert not any(role == "reviewer" for role,_,_ in driver.calls)
        assert cs.list_objects("DelegatedTask") == []
        with ws.store.connect() as db:
            assert db.execute("SELECT * FROM content_operations ORDER BY operation_id").fetchall() == original_operations
        assert events(ws, "deep_tool_argument_decoded") == []
        start = next(e for e in events(ws, "deep_tool_start") if e["tool"] == "task")
        assert start["arguments"]["review_snapshot_ref"] == task_call["args"]["review_snapshot_ref"]
    else:
        with ws.store.connect() as db:
            analyses = [json.loads(row[0]) for row in db.execute("SELECT data FROM analyses")]
        raw_record, = [a for a in analyses if a.get("operation") == captured["diagnostic"]["raw_operation"]]
        assert raw_record["analysis"] == captured["raw"]
        if fault == "foreign_receipt":
            with ws.store.connect() as db:
                row = db.execute("SELECT actor_id FROM content_observations WHERE id=?", (foreign,)).fetchone()
            assert row[0] == owner.id  # Deliberate malicious fixture injection, not checker access.
    assert cs.list_objects("ContentNode") == original_nodes
    assert ws.store.manifest["sources"] == original_sources
    assert "rubric_grader" not in driver.created


@pytest.mark.parametrize("internal_failure", [False, True], ids=["legal-public-dict", "internal-error-propagates"])
async def test_task_preflight_preserves_raw_and_does_not_swallow_internal_validation(tmp_path, monkeypatch, internal_failure):
    from contextlib import contextmanager
    from report_agent import content_tasks
    from report_agent.content_models import Ref
    from report_agent.content_store import ContentStore
    from test_task_supervision import ws as native_ws
    from test_deep_runtime import call

    ws = native_ws.__wrapped__(tmp_path)
    raw = {"subagent_type": "writer", "description": "Observe only; no generated report."}
    original_raw = deepcopy(raw)
    seen = []
    if internal_failure:
        original = content_tasks.delegated_task
        @contextmanager
        def internal_error_after_valid_input(*args, **kwargs):
            with original(*args, **kwargs) as bound:
                # A deliberate business-internal failure after input validation,
                # not malformed model task arguments. It must remain visible.
                Ref.model_validate({"type": "ContentNode", "id": "injected-internal", "version": "bad"})
                yield bound
        monkeypatch.setattr(content_tasks, "delegated_task", internal_error_after_valid_input)
    def parent(messages):
        message = next(m for m in reversed(messages) if isinstance(m, ToolMessage) and m.tool_call_id == "valid-task")
        assert message.status == "success" and "Valid native child executed." in message.content
        seen.append(message.content)
        return AIMessage(content="Actual child return observed; no report acceptance.")
    driver = Driver(coordinator=[AIMessage(content="", tool_calls=[call("task", raw, "valid-task")]), parent],
        writer=[AIMessage(content="Valid native child executed.")])
    result = await deep_runtime.run_report(ws, driver)
    assert raw == original_raw
    start = next(e for e in events(ws,"deep_tool_start") if e["tool"] == "task")
    assert start["arguments"] == original_raw
    assert events(ws,"deep_tool_argument_decoded") == []
    if internal_failure:
        assert result["status"] == "failed" and result["last_error"]["type"] == "ValidationError", result
        assert result["last_error"]["diagnostic_id"]
        assert not seen and not any(role == "writer" for role,_,_ in driver.calls)
        assert events(ws,"native_tool_schema_error") == []
    else:
        assert result["last_error"] is None and seen, result
        assert sum(role == "writer" for role,_,_ in driver.calls) == 1
    assert not ContentStore(ws.store).list_objects("ReviewRecord")
