"""Native known-write repetition cases, with real receipts and unchanged ownership."""
from langchain_core.messages import AIMessage

from report_agent import deep_runtime
from report_agent.content_store import ContentStore
from test_deep_runtime import Driver, call, invoke
from test_task_supervision import ws as native_workspace


async def known_write_repetition_case(tmp_path, *, managed=False, progress=False, reference=False, mixed_invalid=False):
    ws = native_workspace.__wrapped__(tmp_path)
    if managed:
        ws.store.set("context_policy", "stateful-tools-v1")
    if reference:
        assert managed
        ws.store.set("manifest", {**ws.store.manifest, "decision_data_policy": "reference-data-v1"})
    args = {"operation_id": "same-structural-plan", "objects": [{
        "client_key": "plan", "type": "ContentNode", "payload": {"kind": "chapter",
            "body": {"text": "Synthetic saved structural plan"}, "qualifiers": {}, "claim_kind": "structure"}}]}
    seen = {}
    def after_notice(messages):
        import json
        blocks = [b['text'] for m in messages if m.type == 'system'
                  for b in m.content_blocks if b.get('type') == 'text']
        from support.task_state_contract import moved_blocks
        blocks.extend(part['text'] for part in moved_blocks(messages))
        notice, = [json.loads(b)['execution_observation'] for b in blocks
                   if b.startswith('{"execution_observation":')]
        assert notice == {'tool': 'commit_objects', 'identical_successful_exchanges': 3,
                          'semantic_progress_assessed': False}
        proof, = [json.loads(b)['known_write_repetition'] for b in blocks
                  if b.startswith('{"known_write_repetition":')]
        assert proof['operation_id'] == args['operation_id'] and proof['receipt_state'] == 'known_success'
        assert proof['observed_call_ids'] and set(proof['observed_call_ids']) <= {
            m.tool_call_id for m in messages if m.type == 'tool' and m.status == 'success'}
        seen["advisory_observed"] = True
        if mixed_invalid:
            return AIMessage(content="", tool_calls=[call("commit_objects", args, "valid-sibling-replay")],
                invalid_tool_calls=[{"name": "calculate", "args": '{"terms":', "id": "invalid-new-action", "error": "Incomplete JSON"}])
        if progress:
            return AIMessage(content="", tool_calls=[call("commit_objects", {
                "operation_id": "useful-next-structural-step", "objects": [{"client_key": "next", "type": "ContentNode",
                    "payload": {"kind": "chapter", "body": {"text": "A useful new structural decision"},
                        "qualifiers": {}, "claim_kind": "structure"}}]}, "post-advisory-progress")])
        return AIMessage(content="", tool_calls=[call("commit_objects", args, "post-advisory-repeat")])
    # First creation and cached return have distinct JSON key order. An initial
    # write plus three actual cached observations supplies the existing exact
    # public advisory; no assumption about a third-call stop is introduced.
    actions = [AIMessage(content="", tool_calls=[call("commit_objects", args, f"same-plan-{i}")]) for i in range(4)]
    actions += [after_notice]
    if mixed_invalid:
        def correct_invalid(messages):
            from langchain_core.messages import ToolMessage
            errors = [m for m in messages if isinstance(m, ToolMessage) and m.tool_call_id == "invalid-new-action"]
            assert errors and errors[-1].status == "error"
            seen["invalid_feedback_observed"] = True
            return invoke("calculate", terms=[["1"]])
        actions.append(correct_invalid)
    elif not progress:
        actions += [AIMessage(content="", tool_calls=[call("commit_objects", args, f"same-plan-{i}")]) for i in range(5, 8)]
    else:
        # More than eight productive decisions remain permitted; no total-call quota.
        actions += [AIMessage(content="", tool_calls=[call("commit_objects", {
            "operation_id": f"productive-{i}", "objects": [{"client_key": "step", "type": "ContentNode",
                "payload": {"kind": "chapter", "body": {"text": f"Useful distinct structural step {i}"},
                    "qualifiers": {}, "claim_kind": "structure"}}]}, f"productive-{i}")]) for i in range(7)]
    actions.append(AIMessage(content="Saved structural work only; no approval claim."))
    driver = Driver(coordinator=[invoke("task", subagent_type="writer", description="Save one goal-level structural plan and act from actual results."),
        AIMessage(content="Saved Writer state retained.")], writer=actions)
    result = await deep_runtime.run_report(ws, driver)
    if reference:
        assert ws.store.get("decision_data_binding") == {"policy": "reference-data-v1"}
    return ws, ContentStore(ws.store), driver, seen, result
