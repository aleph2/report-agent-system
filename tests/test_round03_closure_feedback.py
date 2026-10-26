"""Fresh03 public first-error contracts; never unwrap or adopt changed content."""
import json
from copy import deepcopy

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from pydantic import BaseModel, ConfigDict

from report_agent.tool_argument_feedback import compact_native_tool_error
from report_agent.content_tasks import delegated_task
from report_agent.errors import ActionRejected
from report_agent.text_work import AdoptionObject
from test_task_supervision import ws
from test_hierarchical_content import seed
from test_bounded_review import Model
from test_text_work import content, tools, writer_call
from test_deliverable_declaration_v4 import case


class Submission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    review: dict | str
    delivery_export_ref: dict | None = None


@pytest.mark.parametrize("schema", [Submission, Submission.model_json_schema()])
def test_wrong_wrapper_names_root_keys_without_repair_or_echo(ws, schema):
    supplied = {"arguments": json.dumps({"review": {"private_long_body": "x" * 26000}})}
    before = deepcopy(supplied)
    native = ToolMessage("Error invoking tool 'submit_review' with error: review: Field required",
                         tool_call_id="wrong-wrapper", name="submit_review", status="error")
    result = compact_native_tool_error(native, ws.store, args=supplied, schema=schema)
    value = json.loads(result.content)
    assert value["root_contract"] == {
        "received_keys": ["arguments"], "required_keys": ["review"],
        "allowed_keys": ["delivery_export_ref", "review"],
        "missing_required_keys": ["review"], "unexpected_keys": ["arguments"]}
    assert value["execution_state"] == "not_established"
    assert supplied == before and "private_long_body" not in result.content
    assert result.tool_call_id == native.tool_call_id and result.status == "error"


@pytest.mark.parametrize("review", [{"items": []}, '{"items":[]}'])
def test_legal_object_and_string_review_stay_legal(review):
    supplied = {"review": review}
    assert Submission.model_validate(supplied).review == review


async def test_actual_native_graph_returns_root_contract_without_creating_task(ws):
    from report_agent.deep_runtime import run_report
    from test_deep_runtime import Driver, invoke, observation
    feedback=[]
    def inspect(messages):
        value=observation(messages, "task")
        feedback.append(value)
        return AIMessage(content="Wrong outer shape remains unexecuted; no automatic dispatch.")
    driver=Driver(coordinator=[invoke("task", arguments=json.dumps(writer_call()["args"])), inspect])
    await run_report(ws, driver)
    assert feedback
    assert feedback[0]["root_contract"]["received_keys"] == ["arguments"]
    assert "subagent_type" in feedback[0]["root_contract"]["missing_required_keys"]
    assert feedback[0]["root_contract"]["unexpected_keys"] == ["arguments"]
    from report_agent.content_store import ContentStore
    assert ContentStore(ws.store).list_objects("DelegatedTask") == []
    assert not any(role in {"writer", "reviewer", "text_tool"} for role, _, _ in driver.calls)


async def test_added_qualifier_reports_exact_candidate_field_and_preserves_guard(ws):
    cs, _, refs, _, _ = seed(ws)
    model = Model(json.dumps(content()))
    with delegated_task(ws, "coordinator", writer_call()) as (_, actor):
        t = tools(ws, "writer", model)
        work = await t["process_report_content"]("produce", "Describe selected synthetic rule", "ContentNode", [refs["claim"]])
        original = deepcopy(cs.list_objects())
        changed = deepcopy(work["payload"])
        changed["qualifiers"]["basis_priority"] = "Keep the genuine source priority"
        objects = [AdoptionObject(client_key="block", type="ContentNode", payload=changed,
                                  text_work_id=work["text_work_id"])]
        with pytest.raises(ActionRejected, match="TEXT_WORK_OUTPUT_CHANGED") as first:
            t["commit_objects"]("changed", objects)
        diagnostic=first.value.diagnostic
        assert diagnostic["object_type"] == "ContentNode"
        assert diagnostic["output_index"] == 0
        assert diagnostic["changed_fields"] == ["qualifiers"]
        assert diagnostic["changed_qualifier_keys"] == ["basis_priority"]
        with pytest.raises(ActionRejected) as repeated:
            t["commit_objects"]("changed", objects)
        assert repeated.value.diagnostic == diagnostic
        assert cs.list_objects() == original and len(model.calls) == 1
        saved=t["commit_objects"]("unchanged", [AdoptionObject(client_key="block", type="ContentNode",
            payload=work["payload"], text_work_id=work["text_work_id"])])
        assert saved["result"]["refs"]["block"]


@pytest.mark.parametrize("profile, public_id, interface", [
    ("caller-operation-v1", None, "legacy"),
    ("caller-operation-v1", "real-public-caller-id", "legacy"),
    ("native-tool-runtime-v1", None, "legacy"),
    ("native-tool-runtime-v1", None, "v4")])
async def test_actual_sdk_wrong_submit_wrapper_reports_offered_root_keys(request, profile, public_id, interface):
    import httpx
    from collections import Counter
    from report_agent import deep_runtime
    from report_agent.deep_models import GLMChatOpenAI, model_async_client
    from test_prompt_native_sdk_inputs import completion
    from test_reviewer_native_profile import native, commission
    if interface == "v4":
        from test_review_binding_v4 import prepared, review_call
        from test_reviewer_complete_materials import configure
        cs, _, criteria, _ = prepared(request.getfixturevalue("case"))
        cs.store.set("manifest", {**cs.store.manifest,
            "report_prompt_profile":"concise-v1", "report_expression_profile":"reader-expression-v2"})
        ws = configure(cs)
        request = review_call(criteria)["args"]
    else:
        ws = request.getfixturevalue("ws")
        native(ws)
        cs, _, refs, snapshot, _ = seed(ws)
        request = commission(snapshot, refs)
    ws.store.set("manifest", {**ws.store.manifest,"operation_identity_profile":profile})
    wrong_args = {"arguments":json.dumps({"review":{"items":[]}})}
    if public_id is not None:
        wrong_args["operation_id"] = public_id
    counts, models, captured = Counter(), {}, []
    def factory(role):
        if role in models:
            return models[role]
        client = model_async_client(ws.store, role)
        def transport(http_request):
            body = json.loads(http_request.content)
            step=counts[role]
            counts[role]+=1
            if role == "coordinator":
                return completion(http_request, "Fixture done.", ("task",request) if step == 0 else None)
            if step == 0:
                offered=next(t["function"]["parameters"] for t in body["tools"]
                             if t["function"]["name"] == "submit_review")
                packet = None
                if interface == "v4":
                    from test_round26_native_receipt_binding import state_packet
                    packet = state_packet(body)
                captured.append({"schema":offered,"state":packet,"objects":deepcopy(cs.list_objects())})
                return completion(http_request, "", ("submit_review", wrong_args))
            feedback=json.loads(next(m["content"] for m in reversed(body["messages"]) if m["role"]=="tool"))
            captured.append({"feedback":feedback,"objects":deepcopy(cs.list_objects())})
            return completion(http_request, "Wrong shape remains unexecuted, no auto unwrap.")
        client._transport=httpx.MockTransport(transport)
        client._mounts.clear()
        models[role]=GLMChatOpenAI(model="glm-5.3",api_key="fixture-only",base_url="https://fixture.invalid/v1",
            use_responses_api=False,http_async_client=client,max_retries=0,disable_streaming=True)
        return models[role]
    try:
        result=await deep_runtime.run_report(ws,factory)
        assert result["last_error"] is None,result
        assert len(captured)==2
        schema,feedback=captured[0]["schema"],captured[1]["feedback"]
        assert feedback["code"]=="NATIVE_TOOL_VALIDATION_ERROR"
        assert feedback["root_contract"]["allowed_keys"]==sorted(schema["properties"])
        assert feedback["root_contract"]["required_keys"]==sorted(schema.get("required",[]))
        assert feedback["root_contract"]["received_keys"]==sorted(wrong_args)
        assert captured[0]["objects"] == captured[1]["objects"]
        if profile == "native-tool-runtime-v1":
            assert "operation_id" not in schema["properties"]
        if public_id is not None:
            assert "operation_id" in feedback["root_contract"]["received_keys"]
        if interface == "v4":
            assert captured[0]["state"]["review_materials"]["objects_complete"] is True
            assert cs.store.get("context_projection_binding") == "review-materials-v1"
        assert "review" in feedback["root_contract"]["missing_required_keys"]
        assert feedback["root_contract"]["unexpected_keys"]==["arguments"]
        assert not cs.list_objects("ReviewRecord")
        assert not any(role=="text_tool" for role in counts)
    finally:
        for model in models.values():
            await model.root_async_client.close()
            model.root_client.close()
