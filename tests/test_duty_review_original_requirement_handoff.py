"""Native fake-model handoff controls, not engineering/semantic quality evidence.

The scripted checker explicitly supplies the gap. These tests measure whether
the real runtime delivers Agent-selected independent requirements and preserves
that response. The four handoff variants migrated from implicit runtime loading
to explicit selection; their original body/version/gap assertions remain. The historical oversize variant
now proves full delivery instead of the removed character-limit refusal.
"""
from copy import deepcopy
import json
import hashlib
import os
from pathlib import Path
import sys

import pytest
from langchain_core.messages import AIMessage, ToolMessage, messages_to_dict

from report_agent import deep_runtime
from report_agent.content_delivery import current_delivery
from report_agent.content_store import ContentStore
from report_agent.task_context import exact_task_context
from report_agent.task_supervision import reconcile
from test_agent_duty_trace_cases import action, result_value, tool_reply
from test_bounded_review import review_call
from test_decision_data import activate
from test_deep_runtime import Driver
from test_hierarchical_content import seed
from test_task_supervision import ws, offline


HISTORICAL_FIXTURE_THRESHOLD = 64000  # Fixture size only; not a product material limit.


ORIGINAL = ("Assess Objects A and B individually using their original design and guide.\n"
            "B's inclusion remains unresolved: disclosure alone is not its assessment.\n"
            "完整保留原要求末尾条件：重要结构物不能只因摘要缺高度而排除。")
GAP = "Object B applicability is unresolved; the narrower check does not establish its assessment."
OUTSIDE = "Other commissioned outcomes remain unreviewed; this local pass is not whole-report acceptance."


def prepare(ws, variant="normal"):
    text = ORIGINAL + ("文" * (HISTORICAL_FIXTURE_THRESHOLD - len(ORIGINAL) + 1) if variant == "oversize" else "")
    ws.store.set("manifest", {**ws.store.manifest, "goal": text})
    cs, actor, refs, snapshot, members = seed(ws)
    original_ref = next(r for r in members if r["type"] == "Requirement")
    original = cs.read(original_ref)
    call = review_call(snapshot, refs, id="original-review-task")
    call["args"]["review_requirements"][0]["content_check_scopes"] = [{
        "requirement_index": 0, "node_ref": refs["claim"], "kind": "local_body"}]
    if variant in {"shared-ref", "focused"}:
        payload = deepcopy(cs.read(refs["k"])["payload"])
        payload.update(purpose="Verify preservation of the adopted class qualifier",
            scope="Only the stated class condition in the target body",
            expected_outcome="The local target explicitly retains its class B condition.",
            evidence_expectation="Compare actual target body and its condition qualifier.",
            allowed_limits="This does not check the numeric score or all project objects.")
        local = cs.commit(actor, "local-criterion", [{"client_key": "local", "type": "Criterion",
            "payload": payload}])["result"]["refs"]["local"]
        snapshot = cs.freeze(actor, "local-snapshot", refs["root"], [*members, local])["result"]["snapshot_ref"]
        call["args"]["review_snapshot_ref"] = snapshot
    if variant == "shared-ref":
        other = deepcopy(call["args"]["review_requirements"][0])
        other.update(scope_id="second-local-comparison", criterion_ref=local,
            required_checks=["Verify the stated class B condition is retained"])
        call["args"]["review_requirements"].append(other)
    elif variant == "focused":
        call["args"]["review_requirements"][0].update(criterion_ref=local,
            required_checks=["Verify the stated class B condition is retained"])
    if variant == "old-version":
        # Host-only historical input fixture, not a native permission to commit
        # requirements. Exercise exact-version reading of an immutable old snapshot.
        from report_agent.content_models import Requirement
        payload = Requirement.model_validate({**original["payload"],
            "text": "A later requirement version must not replace this frozen input."}).model_dump()
        with ws.store.connect() as db:
            cs._insert(db, actor, "Requirement", payload, id=original_ref["id"],
                version=2, previous_ref=original_ref)
    # A current local task description must not accidentally supply a second
    # copy of the frozen original text and conceal the handoff deficiency.
    ws.store.set("manifest", {**ws.store.manifest,
        "goal": "Review the selected frozen report scope using its independent original commission; preserve unresolved work."})
    activate(ws)
    return cs, refs, snapshot, original, call


def capture(ws, request, driver, held):
    root = Path(os.environ.get("REPORT_REQUIREMENT_HANDOFF_OUT", str(ws.store.root / "captures")))
    root.mkdir(parents=True, exist_ok=True)
    name = request.node.name.replace("[", "-").replace("]", "") + ".json"
    path = root / name
    data = {"nodeid": request.node.nodeid, "scripted_semantic_response": True,
        "project_provider_calls": 0, "model_calls": [
            {"role": role, "step": step, "messages": messages_to_dict(messages)}
            for role, step, messages in driver.calls],
        "held": held}
    # Raw model/tool evidence survives even if the saved-state observer fails.
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), "utf-8")
    try:
        cs = ContentStore(ws.store)
        data.update(saved_reviews=cs.list_objects("ReviewRecord"), tasks=cs.list_objects("DelegatedTask"),
            issues=ws.store.get("report_issues", []), delivery=current_delivery(ws.store), events=ws.store.events())
        with ws.store.connect() as db:
            data["observations"] = [{"id": r[0], "actor_id": r[1], "data": json.loads(r[2])}
                for r in db.execute("SELECT id,actor_id,data FROM content_observations")]
    except Exception as exc:
        data["observer_error"] = {"type": type(exc).__name__, "message": str(exc)}
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), "utf-8")
        raise
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), "utf-8")
    request.node.user_properties.append(("handoff_capture", str(path)))


def checker(held, *, focused=False):
    def respond(messages):
        packet = json.loads(messages[-1].content)
        held.setdefault("checker_inputs", []).append(deepcopy(packet))
        original_index = next((i for i, entry in enumerate(packet["evidence"])
            if entry.get("object", {}).get("ref", {}).get("type") == "Requirement"), 0)
        items = []
        for assigned in packet["assignment"]["review_requirements"]:
            if focused:
                target = packet["evidence"][0]["object"]["payload"]
                assert target["qualifiers"]["condition"] == "class B"
                assert "class B" in target["body"]["text"]
                observations = [{"evidence_index": 0, "locator": "target local body",
                                 "observation": "Both target body and condition qualifier explicitly retain class B."}]
                item = {"checked_requirement_indexes": [0], "execution_state": "completed",
                    "verdict": "satisfied", "observations": observations,
                    "check_results": [{"requirement_index": 0, "execution_state": "completed",
                        "result": "Assigned local condition checked.", "observation_indexes": [0], "remaining": ""}],
                    "outside_assignment_notes": [OUTSIDE],
                    "coverage": {"checked": ["Local condition"], "unchecked": [], "blocked": [], "basis": "Target body only"},
                    "reason": "Supported local check only."}
            else:
                item = {"checked_requirement_indexes": [], "execution_state": "blocked",
                    "verdict": "undetermined", "observations": [{"evidence_index": original_index,
                        "locator": "Independent original requirement", "observation": GAP}],
                    "check_results": [{"requirement_index": 0, "execution_state": "partial",
                        "result": "Disclosure observed; applicability comparison incomplete.",
                        "observation_indexes": [0], "remaining": GAP}],
                    "outside_assignment_notes": ["No engineering approval is established."],
                    "coverage": {"checked": ["Observed pending disclosure"], "unchecked": [GAP],
                        "blocked": [GAP], "basis": "Scripted observation, not autonomous discovery"},
                    "reason": GAP}
            items.append({"scope_id": assigned["scope_id"], **item, "findings": []})
        raw = {"items": items}
        held["scripted_output"] = deepcopy(raw)
        return AIMessage(content=json.dumps(raw, ensure_ascii=False))
    return respond


async def run_review(ws, call, held, request, *, focused=False):
    def reviewer_return(messages):
        message = tool_reply(messages, "bounded-original-check")
        held["reviewer_tool_return"] = message.model_dump()
        # Return the actual result; do not insert the expected gap from a host fixture.
        if message.status == "error":
            return AIMessage(content=message.content)
        return AIMessage(content=json.dumps(result_value(message), ensure_ascii=False))

    def parent_return(messages):
        held["parent_task_return"] = tool_reply(messages, "original-review-task").model_dump()
        return AIMessage(content="Scoped result retained. Full commissioned scope is not accepted.")

    # Approved migration: discover the exact original through actual registered
    # tools, then choose it. No host-supplied original body/ref bypasses that path.
    def choose_criterion(value):
        saved = value["assignment"]
        held["discovered_assignment"] = deepcopy(saved)
        held["selected_scope_ids"] = [r["scope_id"] for r in saved["review_requirements"]]
        return action("read_context", "read-original-criterion",
            target_ref=saved["review_requirements"][0]["criterion_ref"])

    def assignment_read(messages):
        value = result_value(tool_reply(messages, "read-original-assignment"))
        if "assignment" in value:
            return choose_criterion(value)
        assert value["offset"] == 0 and not value["complete_tool_result"]
        held["assignment_page_binding"] = {
            k: value[k] for k in ("observation_ref", "sha256", "total_characters")}
        held["assignment_page_text"] = ""
        return consume_assignment_page(value)

    def consume_assignment_page(value):
        binding = held["assignment_page_binding"]
        assert all(value[k] == v for k, v in binding.items())
        assert value["offset"] == len(held["assignment_page_text"])
        assert value["end"] == value["offset"] + len(value["text"])
        held["assignment_page_text"] += value["text"]
        if value["next_offset"] is not None:
            assert value["next_offset"] == value["end"]
            return action("read_tool_observation", "read-assignment-page",
                observation_ref=binding["observation_ref"], offset=value["next_offset"], characters=6000)
        text = held["assignment_page_text"]
        assert len(text) == binding["total_characters"]
        assert hashlib.sha256(text.encode("utf-8")).hexdigest() == binding["sha256"]
        # Each page may honestly report complete_tool_result=False. Contiguous
        # total coverage + original digest establishes this assembled JSON only.
        held.setdefault("assignment_recoveries", []).append({**binding, "all_pages_recovered": True})
        return choose_criterion(json.loads(text))

    def criterion_read(messages):
        value = result_value(tool_reply(messages, "read-original-criterion"))
        objects = value.get("result", value)["objects"]
        criterion = objects[0]
        held["discovered_criterion"] = deepcopy(criterion)
        original_ref = criterion["payload"]["requirement_refs"][0]
        held["selected_original_ref"] = deepcopy(original_ref)
        return action("read_context", "read-selected-original", target_ref=original_ref)

    def original_read(messages):
        value = result_value(tool_reply(messages, "read-selected-original"))
        original = value.get("result", value)["objects"][0]
        assert original["ref"] == held["selected_original_ref"]
        held["discovered_original"] = deepcopy(original)
        # Two selected scopes share this same exact original; duplicate choices
        # deliberately exercise transport dedup, never semantic merging.
        return action("perform_assigned_review", "bounded-original-check", operation_id="original-check",
            scope_ids=held["selected_scope_ids"], source_selections=[], content_selections=[],
            original_requirement_refs=[original["ref"]] * len(held["selected_scope_ids"]))

    local_only = action("perform_assigned_review", "bounded-original-check", operation_id="original-check",
        scope_ids=[r["scope_id"] for r in call["args"]["review_requirements"]],
        source_selections=[], content_selections=[])
    def discovery_response(messages):
        latest = next((m for m in reversed(messages) if isinstance(m, ToolMessage)), None)
        if latest is None:
            return action("read_task_assignment", "read-original-assignment")
        routes = {"read-original-assignment": assignment_read,
            "read-original-criterion": criterion_read, "read-selected-original": original_read,
            "bounded-original-check": reviewer_return,
            "read-assignment-page": lambda current: consume_assignment_page(
                result_value(tool_reply(current, "read-assignment-page")))}
        assert latest.tool_call_id in routes, latest
        return routes[latest.tool_call_id](messages)

    reviewer_steps = [local_only, reviewer_return] if focused else [discovery_response] * 16
    driver = Driver(coordinator=[AIMessage(content="", tool_calls=[call]), parent_return],
        reviewer=reviewer_steps, text_tool=[checker(held, focused=focused)])
    try:
        held["runtime"] = await deep_runtime.run_report(ws, driver)
    except Exception as exc:
        held["execution_error"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        execution_error = sys.exc_info()[0] is not None
        try:
            capture(ws, request, driver, held)
        except Exception:
            if not execution_error:
                raise
    return driver


@pytest.mark.parametrize("variant", ["normal", "shared-ref", "old-version", "oversize"])
async def test_original_requirement_and_declared_gap_use_native_handoff(ws, request, variant):
    cs, refs, snapshot, original, call = prepare(ws, variant)
    held = {"original": original, "assignment": call}
    driver = await run_review(ws, call, held, request)
    assert held["runtime"]["last_error"] is None, held["runtime"]
    if variant == "oversize":
        assert len(original['payload']['text']) > HISTORICAL_FIXTURE_THRESHOLD
        assert held['reviewer_tool_return']['status'] != 'error'
        assert 'REVIEW_REQUIREMENTS_EXCEED_BOUNDED_INPUT' not in held['reviewer_tool_return']['content']
    packet = held["checker_inputs"][0]
    assert held["discovered_original"] == original
    assert packet["selected_original_requirement_refs"] == [original["ref"]]
    assert original["payload"]["text"] not in str(packet["commission"])
    # Whole object equality covers text tail, origin, scope, ref version and metadata.
    loaded = [e["object"] for e in packet["evidence"] if e.get("object", {}).get("ref", {}).get("type") == "Requirement"]
    assert loaded == [original], "INDEPENDENT_ORIGINAL_MUST_REACH_CHECKER_EXACTLY_ONCE"
    assert loaded[0]["payload"]["text"] == original["payload"]["text"]
    assert packet["evidence"][0]["object"]["ref"] == refs["claim"]
    assert packet["evidence"][1]["kind"] == "snapshot_structure"
    assert packet["evidence"][-1] == {"kind": "saved_object", "object": original}
    review = cs.list_objects("ReviewRecord")[0]
    assert original["ref"] in review["payload"]["dependency_refs"]
    actual = result_value(tool_reply_from_dump(held["reviewer_tool_return"]))
    for saved, returned, scripted in zip(review["payload"]["items"], actual["items"], held["scripted_output"]["items"], strict=True):
        for field in ("scope_id", "execution_state", "verdict", "check_results", "coverage", "reason", "outside_assignment_notes"):
            assert saved[field] == returned[field] == scripted[field]
        assert saved["check_results"][0]["requirement_index"] == 0
        assert original["ref"] in saved["dependency_refs"]
        observation = saved["observations"][0]
        with ws.store.connect() as db:
            receipt = json.loads(db.execute("SELECT data FROM content_observations WHERE id=?",
                (observation["receipt_id"],)).fetchone()[0])
        assert receipt["objects"] == [original]
    assert GAP in held["parent_task_return"]["content"]
    status = reconcile(cs, review["task_id"])
    assert not status["execution_complete"] and status["remaining"]
    assert status["semantic_coverage_verified"] is False
    assert current_delivery(ws.store)["overall_verdict"] is None
    assert cs.read(original["ref"]) == original


def tool_reply_from_dump(value):
    from langchain_core.messages import ToolMessage
    return ToolMessage.model_validate(value)


async def test_focused_review_can_complete_without_global_promotion(ws, request):
    cs, refs, snapshot, original, call = prepare(ws, "focused")
    held = {"original": original}
    driver = await run_review(ws, call, held, request, focused=True)
    assert held["runtime"]["last_error"] is None, held["runtime"]
    assert not any(e.get("object", {}).get("ref", {}).get("type") == "Requirement"
        for e in held["checker_inputs"][0]["evidence"])
    assert held["checker_inputs"][0]["selected_original_requirement_refs"] == []
    review = cs.list_objects("ReviewRecord")[0]
    item = review["payload"]["items"][0]
    assert item["execution_state"] == "completed" and item["verdict"] == "satisfied"
    assert item["outside_assignment_notes"] == [OUTSIDE]
    assert reconcile(cs, review["task_id"])["execution_complete"]
    assert OUTSIDE in held["parent_task_return"]["content"]
    assert current_delivery(ws.store)["overall_verdict"] is None
    from report_agent.task_supervision import obligation_coverage
    obligations = obligation_coverage(cs, snapshot)
    assert refs["k"] in obligations["criteria_without_assignment"]
    assert obligations["semantic_coverage_verified"] is False
    # The original global Criterion was not silently replaced by this local one.
    assert refs["k"] in cs.read(snapshot)["payload"]["criteria_refs"]
    assert refs["k"] != call["args"]["review_requirements"][0]["criterion_ref"]
    assert not ws.store.get("report_issues", [])  # Pending prose is not an actual human request.


async def test_explicit_nonblocking_human_issue_preserves_supported_draft(ws, request):
    cs, _, snapshot, original, _ = prepare(ws)
    held = {"original": original, "prose_only_issue_count": len(ws.store.get("report_issues", []))}

    def continue_draft(messages):
        message = tool_reply(messages, "human-decision")
        value = result_value(message)
        held["human_return"] = message.model_dump()
        assert value["waiting_for_human"] and value["execution_paused"] is False
        return action("export_content_snapshot", "supported-draft", operation_id="qualified-draft", snapshot_ref=snapshot)

    def finish(messages):
        message = tool_reply(messages, "supported-draft")
        held["draft_export_return"] = message.model_dump()
        assert message.status == "success", message
        return AIMessage(content="Qualified draft preserved; Object B still needs the registered human decision. No full acceptance.")

    driver = Driver(coordinator=[action("ask_human", "human-decision", category="requirement",
        description=GAP, source_ids=[], pause=False), continue_draft, finish])
    try:
        held["runtime"] = await deep_runtime.run_report(ws, driver)
        held["context_after"] = exact_task_context(ws, "coordinator")
    except Exception as exc:
        held["execution_error"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        execution_error = sys.exc_info()[0] is not None
        try:
            capture(ws, request, driver, held)
        except Exception:
            if not execution_error:
                raise
    assert held["runtime"]["last_error"] is None, held["runtime"]
    assert held["prose_only_issue_count"] == 0
    issues = ws.store.get("report_issues", [])
    assert len(issues) == 1 and issues[0]["description"] == GAP and issues[0]["resolved"] is False
    assert held["context_after"]["issues"] == issues
    assert len(cs.list_objects("ExportArtifact")) == 1 and not cs.list_objects("ReviewRecord")
    import hashlib
    artifact = cs.list_objects("ExportArtifact")[0]
    assert artifact["payload"]["snapshot_ref"] == snapshot
    asset = ws.store.root / artifact["payload"]["file_ref"]
    assert asset.is_file()
    assert hashlib.sha256(asset.read_bytes()).hexdigest() == artifact["payload"]["file_digest"]
    mapping = cs.list_objects("MappingArtifact")[0]["payload"]
    assert mapping["export_ref"] == artifact["ref"] and mapping["snapshot_ref"] == snapshot
    assert current_delivery(ws.store)["overall_verdict"] is None
    assert cs.read(original["ref"]) == original
