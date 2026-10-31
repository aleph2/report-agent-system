"""Native handoff regression: final SDK input and real task admission, no paid model.

Scripted responses prove interface and ownership behavior, not autonomous choice.
"""
import json
from copy import deepcopy
from collections import Counter

import httpx
import pytest

from report_agent import deep_runtime
from report_agent.content_tasks import delegated_task
from report_agent.deep_models import GLMChatOpenAI, model_async_client
from report_agent.errors import ActionRejected, ActionForbidden
from test_hierarchical_content import ws, seed
from test_reviewer_native_profile import native
from test_deep_runtime import call
from test_prompt_native_sdk_inputs import completion
from test_native_task_error_boundary import registered_task


CHECKS = [f"Original outcome {i}: verify against independently available source." for i in range(7)]


def handoff(snapshot, refs):
    return {"description": "Review the retained deliverable against its seven existing outcomes; independently plan and verify.",
            "subagent_type": "reviewer", "review_snapshot_ref": snapshot,
            "review_requirements": [{"target_ref": refs["root"], "criterion_ref": refs["k"],
                "scope_id": "first-review", "required_checks": CHECKS}]}


def invalidate(args, invalid, refs):
    if invalid == "snapshot": args["review_snapshot_ref"]["version"] = 999
    if invalid == "criterion": args["review_requirements"][0]["criterion_ref"] = refs["claim"]
    if invalid == "target-version": args["review_requirements"][0]["target_ref"]["version"] = 999
    if invalid == "check": args["review_requirements"][0]["required_checks"] = []
    return args


async def wire_run(ws, *, delegate, invalid=None):
    native(ws)
    cs, _, refs, snapshot, _ = seed(ws)
    models, wires, steps = {}, [], Counter()
    def factory(role):
        if role in models:
            return models[role]
        client = model_async_client(ws.store, role)
        async def transport(request):
            body = json.loads(request.content)
            wires.append((role, body))
            step = steps[role]
            steps[role] += 1
            if role == "coordinator" and delegate and step == 0:
                return completion(request, "", ("task", invalidate(deepcopy(handoff(snapshot, refs)), invalid, refs)))
            return completion(request, "Assigned work remains unreviewed; no acceptance claimed.")
        client._transport = httpx.MockTransport(transport)
        client._mounts.clear()
        model = GLMChatOpenAI(model="glm-5.3", api_key="fixture-only",
            base_url="https://fixture.invalid/v1", use_responses_api=False,
            http_async_client=client, max_retries=0, disable_streaming=True)
        models[role] = model
        return model
    try:
        result = await deep_runtime.run_report(ws, factory)
        assert result["last_error"] is None, result
        return cs, refs, snapshot, wires
    finally:
        for model in models.values():
            await model.root_async_client.close()
            model.root_client.close()


async def test_final_native_sdk_task_does_not_require_co_to_prepare_checker_material(ws):
    _, _, _, wires = await wire_run(ws, delegate=False)
    coordinator = next(body for role, body in wires if role == "coordinator")
    task = next(t["function"] for t in coordinator["tools"] if t["function"]["name"] == "task")
    public = json.dumps(task)
    assert "automatically supplied to the checker" not in public
    assert "Missing full bodies return a pre-call gap" not in public
    assert "Both lists empty means unresolved" not in public
    # Required business identities and optional declared evidence still exist.
    props = task["parameters"]["properties"]
    assert {"review_snapshot_ref", "review_requirements"} <= props.keys()
    assert "required_materials" in public and "source_ranges" in public


async def test_actual_native_co_role_is_preserved_and_task_uses_configured_handoff_boundary(ws):
    from report_agent.prompt_sources import load_prompt
    _, _, _, wires = await wire_run(ws, delegate=False)
    coordinator = next(body for role, body in wires if role == "coordinator")
    system = "\n".join(m["content"] if isinstance(m["content"], str) else
        "\n".join(b.get("text", "") for b in m["content"]) for m in coordinator["messages"] if m["role"] == "system")
    task = next(t["function"] for t in coordinator["tools"] if t["function"]["name"] == "task")
    configured = load_prompt("native-review-handoff").strip()
    expected = '\n\n'.join(t for t in [load_prompt('agent-common'), load_prompt('agent-coordinator')] if t.strip())
    if expected:
        assert system.startswith(expected)
    assert configured in task["description"]
    captures = [ws.store.get(e["data"]["capture_key"]) for e in ws.store.events()
                if e["kind"] == "prompt_final_http_input"]
    assert captures and all(c["status"] == "exact" for c in captures)
    assert all(next(s['files'] for s in c['sources'] if s['source'] == 'configured_role_files') ==
               ['agent-common', 'agent-' + c['purpose']] for c in captures)
    assert all(not c["limitation"] or isinstance(c["limitation"], str) for c in captures)


async def test_sparse_native_handoff_reaches_reviewer_with_all_seven_checks_without_co_reads(ws):
    cs, refs, snapshot, wires = await wire_run(ws, delegate=True)
    task, = cs.list_objects("DelegatedTask")
    assigned = task["payload"]["review_requirements"]
    assert assigned[0]["required_checks"] == CHECKS
    assert assigned[0]["target_ref"] == refs["root"]
    assert assigned[0]["criterion_ref"] == refs["k"]
    assert task["payload"]["review_snapshot_ref"] == snapshot
    assert not assigned[0].get("required_materials")
    reviewer = next(body for role, body in wires if role == "reviewer")
    visible = json.dumps(reviewer["messages"], ensure_ascii=False)
    assert all(check in visible for check in CHECKS)
    tools = {t["function"]["name"] for t in reviewer["tools"]}
    assert {"read_source_page", "read_context", "read_content_index", "submit_review"} <= tools
    calls = [c["function"]["name"] for role, b in wires if role == "coordinator"
             for m in b["messages"] for c in m.get("tool_calls", [])]
    assert set(calls) <= {"task"}
    assert cs.list_objects("ReviewRecord") == []  # dispatch alone is never acceptance


@pytest.mark.parametrize("invalid", ["snapshot", "criterion", "target-version", "check", "caller"])
def test_sparse_handoff_retains_version_scope_and_authority_checks(ws, invalid):
    native(ws)
    cs, _, refs, snapshot, _ = seed(ws)
    args = deepcopy(handoff(snapshot, refs))
    invalidate(args, invalid, refs)
    with pytest.raises((ActionRejected, ActionForbidden, ValueError)):
        with delegated_task(ws, "writer" if invalid == "caller" else "coordinator",
                            call("task", args, "invalid-sparse-handoff")):
            pytest.fail("Invalid handoff must not reach the native child")
    assert not cs.list_objects("DelegatedTask")


def test_native_schema_changes_descriptions_only_and_leaves_legacy_models_unmodified(ws):
    from report_agent.content_tasks import task_tool
    from report_agent.task_supervision import ReviewRequirement, RequiredReviewMaterial
    from report_agent.prompt_sources import NATIVE_REVIEW, BOUNDED_REVIEW
    from langchain_core.utils.function_calling import convert_to_openai_tool
    before = (ReviewRequirement.model_json_schema(), RequiredReviewMaterial.model_json_schema())
    tool = registered_task()
    legacy = task_tool(tool)
    explicit_legacy = task_tool(tool, review_profile=BOUNDED_REVIEW)
    projected = task_tool(tool, review_profile=NATIVE_REVIEW)
    assert convert_to_openai_tool(legacy) == convert_to_openai_tool(explicit_legacy)
    def shape(value):
        if isinstance(value, dict):
            return {k: shape(v) for k, v in value.items() if k not in {"description", "title"}}
        return [shape(v) for v in value] if isinstance(value, list) else value
    assert shape(convert_to_openai_tool(legacy)) == shape(convert_to_openai_tool(projected))
    assert before == (ReviewRequirement.model_json_schema(), RequiredReviewMaterial.model_json_schema())
    native(ws)
    _, _, refs, snapshot, _ = seed(ws)
    args = handoff(snapshot, refs)
    args["review_requirements"][0]["required_materials"] = [{
        "requirement_index": 0, "purpose": "Declared exact dependency remains binding", "refs": [refs["claim"]]}]
    a = legacy.tool_call_schema.model_validate(args).model_dump()
    b = projected.tool_call_schema.model_validate(args).model_dump()
    assert a == b
    args["review_requirements"][0]["required_materials"][0]["requirement_index"] = 999
    for schema in (legacy.tool_call_schema, projected.tool_call_schema):
        with pytest.raises(ValueError, match="REQUIRED_MATERIAL_CHECK_OUTSIDE_ASSIGNMENT"):
            schema.model_validate(args)


@pytest.mark.parametrize("invalid", ["snapshot", "criterion", "target-version", "check"])
async def test_final_sdk_sparse_handoff_rejections_do_not_start_reviewer(ws, invalid):
    cs, _, _, wires = await wire_run(ws, delegate=True, invalid=invalid)
    assert not cs.list_objects("DelegatedTask")
    assert not any(role == "reviewer" for role, _ in wires)
    co = [body for role, body in wires if role == "coordinator"]
    assert len(co) == 2
    assert any(m["role"] == "tool" and "error" in m["content"].lower() for m in co[-1]["messages"])


@pytest.mark.parametrize("invalid", ["unregistered-profile", None, ""])
def test_unknown_task_profile_fails_closed(invalid):
    from report_agent.content_tasks import task_tool
    with pytest.raises(ActionRejected, match="UNKNOWN_REVIEW_EXECUTION_PROFILE"):
        task_tool(registered_task(), review_profile=invalid)


@pytest.mark.parametrize("invalid", ["extra-material-field", "negative-source-span", "invalid-ref-version"])
def test_native_material_projection_keeps_original_nested_rejections(ws, invalid):
    from report_agent.content_tasks import task_tool
    from report_agent.prompt_sources import NATIVE_REVIEW
    _, _, refs, snapshot, _ = seed(ws)
    args = deepcopy(handoff(snapshot, refs))
    material = {"requirement_index": 0, "purpose": "Declared dependency", "refs": [refs["claim"]]}
    if invalid == "extra-material-field": material["permission_override"] = True
    if invalid == "negative-source-span":
        material["source_spans"] = [{"source_ref": {"type":"SourceArtifact", "id":"s", "version":1},
                                      "offset": -1, "limit": 1}]
    if invalid == "invalid-ref-version": material["refs"][0]["version"] = 0
    args["review_requirements"][0]["required_materials"] = [material]
    for tool in (task_tool(registered_task()), task_tool(registered_task(), review_profile=NATIVE_REVIEW)):
        with pytest.raises(ValueError):
            tool.tool_call_schema.model_validate(args)
