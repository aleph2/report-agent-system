"""Bounded review interface/security checks; scripted outputs are not quality evidence."""
import json

import httpx
import pytest
from langchain_core.messages import AIMessage

from report_agent.bounded_review import perform_review, review_tool
from report_agent.content_tasks import delegated_task
from report_agent.deep_runtime import business_tools
from report_agent.errors import ActionForbidden, ActionRejected
from report_agent.task_supervision import reconcile
from test_task_supervision import ws, offline, review_call as base_review_call
from test_hierarchical_content import seed


def review_call(snapshot, refs, id="review-task", reads=()):
    call = base_review_call(snapshot, refs, id, reads)
    call["args"]["review_requirements"][0]["required_materials"] = [{
        "requirement_index": 0, "purpose": "Assigned target and comparison material",
        "refs": [refs["claim"], *reads]}]
    return call


class Model:
    model_name = "offline-review"
    def __init__(self, response=None):
        self.calls = []
        self.response = response
    async def ainvoke(self, messages):
        self.calls.append(messages)
        if self.response is not None:
            if isinstance(self.response, Exception):
                raise self.response
            return AIMessage(content=self.response)
        return AIMessage(content=json.dumps({"items": [{
            "scope_id": "rule-comparison", "checked_requirement_indexes": [0],
            "execution_state": "completed", "verdict": "not_satisfied",
            "observations": [{"evidence_index": 0, "locator": "claim", "observation": "Adopted B, value 70."},
                             {"evidence_index": 1, "locator": "source", "observation": "B permits 75–100."}],
            "check_results": [{"requirement_index": 0, "execution_state": "completed",
                "result": "70 is outside 75–100.", "observation_indexes": [0, 1], "remaining": ""}],
            "coverage": {"checked": ["Compared the original interval and adopted value."], "unchecked": [], "blocked": [], "basis": "Original source and claim."},
            "reason": "70 outside the supplied interval.", "findings": []}]}))


async def test_tool_loads_original_task_and_evidence_saves_own_result_once(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    source = next(r for r in cs.read(snapshot)["payload"]["refs"] if r["type"] == "SourceArtifact")
    before = cs.list_objects("ContentNode"), cs.list_objects("Criterion")
    model = Model()
    with delegated_task(ws, "coordinator", review_call(snapshot, refs, reads=[source])) as (_, reviewer):
        result = await perform_review(ws, reviewer, model, "check", ["rule-comparison"])
        packet = json.loads(model.calls[0][1][1])
        assert packet["assignment"]["review_requirements"][0]["required_checks"] == ["rule comparison"]
        assert packet["criteria"][0]["ref"] == refs["k"]
        assert packet["evidence"][1]["object"]["ref"] == source
        assert result["items"][0]["verdict"] == "not_satisfied"
        assert reconcile(cs, reviewer.task_id)["execution_complete"]
        again = await perform_review(ws, reviewer, model, "check", ["rule-comparison"])
        assert again["review_ref"] == result["review_ref"] and len(model.calls) == 1
        assert cs.read(result["review_ref"])["owner_id"] == reviewer.id
    assert before == (cs.list_objects("ContentNode"), cs.list_objects("Criterion"))


async def test_new_operation_reuses_exact_judgment_but_changed_service_does_not(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    source = next(r for r in cs.read(snapshot)["payload"]["refs"] if r["type"] == "SourceArtifact")
    model = Model()
    model.openai_api_base = 'https://first.invalid/v1'
    with delegated_task(ws, "coordinator", review_call(snapshot, refs, reads=[source])) as (_, reviewer):
        first = await perform_review(ws, reviewer, model, 'first', ['rule-comparison'])
        repeat = await perform_review(ws, reviewer, model, 'new-operation', ['rule-comparison'])
        assert repeat['reused'] and repeat['review_ref'] == first['review_ref']
        assert len(model.calls) == 1 and len(cs.list_objects('ReviewRecord')) == 1
        model.openai_api_base = 'https://second.invalid/v1'
        with pytest.raises(ActionRejected, match='OPERATION_CONFLICT'):
            await perform_review(ws, reviewer, model, 'first', ['rule-comparison'])
        changed = await perform_review(ws, reviewer, model, 'new-service', ['rule-comparison'])
        assert changed['review_ref'] != first['review_ref'] and len(model.calls) == 2



async def test_tool_permissions_and_scope_rejected_before_paid_request(ws):
    cs, actor, refs, snapshot, _ = seed(ws)
    model = Model()
    with pytest.raises(ActionForbidden):
        await perform_review(ws, actor, model, "bad", ["rule-comparison"])
    with pytest.raises(ActionForbidden):
        await review_tool(ws, model)("bad", ["rule-comparison"], [], [])
    with delegated_task(ws, "coordinator", review_call(snapshot, refs)) as (_, reviewer):
        with pytest.raises(ActionRejected, match="REQUESTED_SCOPES"):
            await perform_review(ws, reviewer, model, "bad", ["other"])
    assert not model.calls


async def test_unknown_model_return_is_not_automatically_retried(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    model = Model(httpx.ReadTimeout("unknown transport result"))
    with delegated_task(ws, "coordinator", review_call(snapshot, refs)) as (_, reviewer):
        with pytest.raises(httpx.ReadTimeout):
            await perform_review(ws, reviewer, model, "first", ["rule-comparison"])
        with pytest.raises(ActionRejected, match="PREVIOUS_ATTEMPT_UNRESOLVED"):
            await perform_review(ws, reviewer, model, "different-operation", ["rule-comparison"])
    assert len(model.calls) == 1 and not cs.list_objects("ReviewRecord")


async def test_partial_judgment_and_unchecked_work_are_preserved(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    model = Model(json.dumps({"items": [{"scope_id": "rule-comparison", "checked_requirement_indexes": [],
        "execution_state": "blocked", "verdict": None, "observations": [],
        "check_results": [{"requirement_index": 0, "execution_state": "blocked",
            "result": "Comparison not performed.", "observation_indexes": [], "remaining": "Need original rule."}],
        "coverage": {"checked": [], "unchecked": ["Original rule comparison"], "blocked": ["Need original rule."], "basis": "Only claim supplied."},
        "reason": "Source not selected; cannot assert the source is absent."}]}))
    with delegated_task(ws, "coordinator", review_call(snapshot, refs)) as (_, reviewer):
        result = await perform_review(ws, reviewer, model, "partial", ["rule-comparison"])
        assert result["items"][0]["verdict"] is None
        assert reconcile(cs, reviewer.task_id)["remaining"]


def test_opt_in_tool_mode_does_not_allow_organizer_to_replace_verdicts(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    ws.store.set("manifest", {**ws.store.manifest, "review_execution_mode": "bounded-tool-v1"})
    names = {t.__name__ for t in business_tools(ws, "reviewer", None, Model())}
    assert "perform_assigned_review" in names
    assert not ({"submit_review", "correct_own_review", "analyze_evidence"} & names)


@pytest.mark.parametrize('managed_context',[False,True])
async def test_native_delegation_calls_tool_and_returns_immutable_judgment(ws,managed_context):
    from report_agent import deep_runtime
    from test_deep_runtime import Driver, invoke
    cs, _, refs, snapshot, _ = seed(ws)
    source = next(r for r in cs.read(snapshot)["payload"]["refs"] if r["type"] == "SourceArtifact")
    ws.store.set("manifest", {**ws.store.manifest, "review_execution_mode": "bounded-tool-v1"})
    if managed_context:
        ws.store.set('context_policy','stateful-tools-v1')
    response = await Model().ainvoke([])
    driver = Driver(coordinator=[AIMessage(content="", tool_calls=[review_call(snapshot, refs, reads=[source])]),
        AIMessage(content="Scoped defect recorded; no whole report acceptance.")],
        reviewer=[invoke("perform_assigned_review", operation_id="local", scope_ids=["rule-comparison"],
                         source_selections=[], content_selections=[]),
                  AIMessage(content="Saved tool finding returned unchanged.")], text_tool=[response])
    result = await deep_runtime.run_report(ws, driver)
    assert result["last_error"] is None, result
    review = cs.list_objects("ReviewRecord")[0]
    assert review["payload"]["runtime_identity"]["mode"] == "bounded-review-v1"
    assert review["payload"]["items"][0]["verdict"] == "not_satisfied"
    assert reconcile(cs, review["task_id"])["execution_complete"]
    assert len([c for c in driver.calls if c[0] == "text_tool"]) == 1


async def test_inconsistent_pass_is_preserved_raw_and_never_silently_repaired(ws):
    from pydantic import ValidationError
    cs, _, refs, snapshot, _ = seed(ws)
    raw = json.loads((await Model().ainvoke([])).content)
    raw["items"][0].update(verdict="satisfied", observations=[])
    raw["items"][0]["coverage"]["unchecked"] = ["Actual missing comparison"]
    model = Model(json.dumps(raw))
    with delegated_task(ws, "coordinator", review_call(snapshot, refs)) as (_, reviewer):
        with pytest.raises(ValidationError):
            await perform_review(ws, reviewer, model, "invalid", ["rule-comparison"])
    assert not cs.list_objects("ReviewRecord")
    with ws.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM analyses").fetchone()[0] == 1


async def test_supported_local_pass_saves_with_outside_assignment_notes(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    raw = json.loads((await Model().ainvoke([])).content)
    item = raw["items"][0]
    item.update(verdict="satisfied", findings=[], reason="Assigned disclosure is present.",
                outside_assignment_notes=["Engineering approval and layout are outside this assignment."])
    item["check_results"][0]["result"] = "Assigned disclosure was compared."
    source = next(r for r in cs.read(snapshot)["payload"]["refs"] if r["type"] == "SourceArtifact")
    with delegated_task(ws, "coordinator", review_call(snapshot, refs, reads=[source])) as (_, reviewer):
        result = await perform_review(ws, reviewer, Model(json.dumps(raw)), "local", ["rule-comparison"])
        saved = cs.read(result["review_ref"])["payload"]["items"][0]
        assert saved["outside_assignment_notes"] == item["outside_assignment_notes"]
        assert saved["verdict"] == "satisfied" and not saved["coverage"]["unchecked"]
        assert reconcile(cs, reviewer.task_id)["execution_complete"]


@pytest.mark.parametrize("overclaim", [False, True])
async def test_compound_partial_check_remains_incomplete_and_cannot_claim_completed_index(ws, overclaim):
    from pydantic import ValidationError
    cs, _, refs, snapshot, _ = seed(ws)
    raw = json.loads((await Model().ainvoke([])).content)
    item = raw["items"][0]
    item.update(verdict="undetermined", checked_requirement_indexes=[0, 1] if overclaim else [0])
    item["check_results"].append({"requirement_index": 1, "execution_state": "partial",
        "result": "Arithmetic compared; grade not established.", "observation_indexes": [0],
        "remaining": "Grade thresholds not supplied."})
    item["coverage"]["unchecked"] = ["Grade thresholds not supplied."]
    source = next(r for r in cs.read(snapshot)["payload"]["refs"] if r["type"] == "SourceArtifact")
    call = review_call(snapshot, refs, reads=[source])
    call["args"]["review_requirements"][0]["required_checks"].append("Recompute arithmetic and verify grade.")
    call["args"]["review_requirements"][0]["required_materials"].append({
        "requirement_index": 1, "purpose": "Second comparison material", "refs": [refs["claim"]]})
    with delegated_task(ws, "coordinator", call) as (_, reviewer):
        if overclaim:
            with pytest.raises(ValidationError, match="CHECK_DECLARATION_CONFLICTS"):
                await perform_review(ws, reviewer, Model(json.dumps(raw)), "partial", ["rule-comparison"])
            assert not cs.list_objects("ReviewRecord")
        else:
            result = await perform_review(ws, reviewer, Model(json.dumps(raw)), "partial", ["rule-comparison"])
            assert result["items"][0]["check_results"][1]["execution_state"] == "partial"
            assert reconcile(cs, reviewer.task_id)["remaining"]


async def test_unrequested_assignments_and_previous_checker_messages_are_excluded(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    source = next(r for r in cs.read(snapshot)["payload"]["refs"] if r["type"] == "SourceArtifact")
    call = review_call(snapshot, refs, reads=[source])
    call["args"]["description"] += " Unrequested broad discussion should not be replayed."
    call["args"]["review_requirements"].append({
        **call["args"]["review_requirements"][0], "scope_id": "unrequested",
        "required_checks": ["UNREQUESTED_ASSIGNMENT_SENTINEL"]})
    model = Model()
    with delegated_task(ws, "coordinator", call) as (_, reviewer):
        for operation in ["first", "second"]:
            await perform_review(ws, reviewer, model, operation, ["rule-comparison"])
    # Same packet reuses the immutable analysis; no second assessment or history.
    assert len(model.calls) == 1
    assert [m[0] for m in model.calls[0]] == ["system", "user"]
    packet = json.loads(model.calls[0][1][1])
    assert len(packet["assignment"]["review_requirements"]) == 1
    assert "UNREQUESTED_ASSIGNMENT_SENTINEL" not in json.dumps(packet)
    assert "Unrequested broad discussion" not in json.dumps(packet)


async def test_missing_per_check_account_is_rejected_without_paid_retry(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    source = next(r for r in cs.read(snapshot)["payload"]["refs"] if r["type"] == "SourceArtifact")
    call = review_call(snapshot, refs, reads=[source])
    call["args"]["review_requirements"][0]["required_checks"].append("Additional assigned comparison.")
    call["args"]["review_requirements"][0]["required_materials"].append({
        "requirement_index": 1, "purpose": "Additional comparison material", "refs": [refs["claim"]]})
    raw = (await Model().ainvoke([])).content
    model = Model(raw)
    with delegated_task(ws, "coordinator", call) as (_, reviewer):
        for operation in ["first", "second"]:
            with pytest.raises(ActionRejected, match="EVERY_ASSIGNED_CHECK_RESULT"):
                await perform_review(ws, reviewer, model, operation, ["rule-comparison"])
    assert len(model.calls) == 1 and not cs.list_objects("ReviewRecord")


async def test_native_invalid_output_returns_feedback_instead_of_crashing_graph(ws):
    from report_agent import deep_runtime
    from test_deep_runtime import Driver, invoke
    cs, _, refs, snapshot, _ = seed(ws)
    source = next(r for r in cs.read(snapshot)["payload"]["refs"] if r["type"] == "SourceArtifact")
    ws.store.set("manifest", {**ws.store.manifest, "review_execution_mode": "bounded-tool-v1"})
    raw = json.loads((await Model().ainvoke([])).content)
    raw["items"][0]["check_results"] = []
    driver = Driver(coordinator=[AIMessage(content="", tool_calls=[review_call(snapshot, refs, reads=[source])]),
        AIMessage(content="Assigned review remains incomplete.")],
        reviewer=[invoke("perform_assigned_review", operation_id="invalid", scope_ids=["rule-comparison"],
                         source_selections=[], content_selections=[]),
                  AIMessage(content="Contract failure preserved; no assessment retry.")],
        text_tool=[AIMessage(content=json.dumps(raw))])
    result = await deep_runtime.run_report(ws, driver)
    assert result["last_error"] is None, result
    assert not cs.list_objects("ReviewRecord")
    assert len([c for c in driver.calls if c[0] == "text_tool"]) == 1
    assert any("REVIEW_OUTPUT_CONTRACT_INVALID" in str(c) for c in driver.calls)


def test_checker_schema_explicitly_requires_observation_links():
    from report_agent.bounded_review import Assessments
    schema = Assessments.model_json_schema()
    assert "observation_indexes" in schema["$defs"]["ToolCheckResult"]["required"]


async def test_completed_output_with_omitted_observation_links_is_rejected(ws):
    from pydantic import ValidationError
    cs, _, refs, snapshot, _ = seed(ws)
    raw = json.loads((await Model().ainvoke([])).content)
    del raw["items"][0]["check_results"][0]["observation_indexes"]
    model = Model(json.dumps(raw))
    with delegated_task(ws, "coordinator", review_call(snapshot, refs)) as (_, reviewer):
        with pytest.raises(ValidationError, match="observation_indexes"):
            await perform_review(ws, reviewer, model, "missing-links", ["rule-comparison"])
    assert len(model.calls) == 1 and not cs.list_objects("ReviewRecord")


@pytest.mark.parametrize("declare_unresolved", [True, False])
async def test_unresolved_or_undeclared_material_contract_stops_before_model(ws, declare_unresolved):
    cs, _, refs, snapshot, _ = seed(ws)
    call = review_call(snapshot, refs)
    call["args"]["review_requirements"][0]["required_materials"] = ([{
        "requirement_index": 0, "purpose": "Applicable classification rule", "refs": []}] if declare_unresolved else [])
    model = Model()
    with delegated_task(ws, "coordinator", call) as (_, reviewer):
        result = await perform_review(ws, reviewer, model, "missing", ["rule-comparison"])
        assert result["code"] == "REQUIRED_REVIEW_MATERIAL_UNRESOLVED"
        assert result["model_called"] is False and result["review_ref"] is None
        assert reconcile(cs, reviewer.task_id)["remaining"]
    assert not model.calls and not cs.list_objects("ReviewRecord")


async def test_large_whole_source_binding_never_enters_model_request(ws):
    manifest = ws.store.manifest
    ws.store.set("manifest", {**manifest, "sources": [{**manifest["sources"][0],
        "content": "Class B permits 75 to 100. " * 1000}]})
    cs, _, refs, snapshot, _ = seed(ws)
    source = next(r for r in cs.read(snapshot)["payload"]["refs"] if r["type"] == "SourceArtifact")
    model = Model()
    with delegated_task(ws, "coordinator", review_call(snapshot, refs, reads=[source])) as (_, reviewer):
        result = await perform_review(ws, reviewer, model, "large-source", ["rule-comparison"])
        assert result["code"] == "REVIEW_SOURCE_RANGE_REQUIRED"
        assert result["model_called"] is False and not result["review_ref"]
        assert result["oversized_source_bindings"][0]["ref"] == source
        assert reconcile(cs, reviewer.task_id)["remaining"]
    assert not model.calls and not cs.list_objects("ReviewRecord")


async def test_located_evidence_does_not_automatically_include_its_whole_source(ws):
    manifest = ws.store.manifest
    whole = "Class B permits 75 to 100. " * 1000
    ws.store.set("manifest", {**manifest, "sources": [{**manifest["sources"][0], "content": whole}]})
    cs, _, refs, snapshot, _ = seed(ws)
    source = next(r for r in cs.read(snapshot)["payload"]["refs"] if r["type"] == "SourceArtifact")
    call = review_call(snapshot, refs)
    call["args"]["review_requirements"][0]["required_materials"][0]["refs"].append(refs["evidence"])
    call["args"]["review_requirements"][0]["material_refs"] = [source]
    model = Model()
    with delegated_task(ws, "coordinator", call) as (_, reviewer):
        result = await perform_review(ws, reviewer, model, "located", ["rule-comparison"])
        assert result["review_ref"] and reconcile(cs, reviewer.task_id)["execution_complete"]
    packet = json.loads(model.calls[0][1][1])
    assert [e["object"]["ref"] for e in packet["evidence"] if e['kind']=='saved_object'] == [refs["claim"], refs["evidence"]]
    assert whole not in model.calls[0][1][1]


async def test_evidence_source_version_is_validated_before_model(ws, monkeypatch):
    cs, _, refs, snapshot, _ = seed(ws)
    original = ws.store.sources(["s"])[0]
    monkeypatch.setattr(ws.store, "sources", lambda ids: [{**original, "content": "Changed rule."}])
    call = review_call(snapshot, refs)
    call["args"]["review_requirements"][0]["required_materials"][0]["refs"].append(refs["evidence"])
    model = Model()
    with delegated_task(ws, "coordinator", call) as (_, reviewer):
        with pytest.raises(ActionRejected, match="SOURCE_VERSION_CHANGED"):
            await perform_review(ws, reviewer, model, "changed", ["rule-comparison"])
    assert not model.calls and not cs.list_objects("ReviewRecord")


@pytest.mark.parametrize('declare_range',[False,True])
async def test_file_membership_does_not_authorize_arbitrary_source_spans(ws,declare_range):
    from report_agent.evidence_analysis import SourceSelection
    cs, _, refs, snapshot, _ = seed(ws)
    source = next(r for r in cs.read(snapshot)["payload"]["refs"] if r["type"] == "SourceArtifact")
    call=review_call(snapshot,refs)
    call['args']['review_requirements'][0]['material_refs']=[source]
    if declare_range:
        call['args']['review_requirements'][0]['source_ranges']=[{'source_ref':source,'offset':0,'limit':1}]
    model=Model()
    with delegated_task(ws,'coordinator',call) as (_,reviewer):
        with pytest.raises(ActionRejected,match='SOURCE_RANGE_OUTSIDE_TASK'):
            await perform_review(ws,reviewer,model,'too-wide',['rule-comparison'],
                source_selections=[SourceSelection(source_id='s',offset=0,limit=2)])
    assert not model.calls


async def test_additional_source_span_is_exactly_task_bound(ws):
    from report_agent.evidence_analysis import SourceSelection
    cs, _, refs, snapshot, _ = seed(ws)
    source=next(r for r in cs.read(snapshot)['payload']['refs'] if r['type']=='SourceArtifact')
    call=review_call(snapshot,refs)
    requirement=call['args']['review_requirements'][0]
    requirement['required_materials'][0]['refs'].append(refs['evidence'])
    requirement['source_ranges']=[{'source_ref':source,'offset':0,'limit':1}]
    model=Model()
    with delegated_task(ws,'coordinator',call) as (_,reviewer):
        result=await perform_review(ws,reviewer,model,'exact-span',['rule-comparison'],
            source_selections=[SourceSelection(source_id='s',offset=0,limit=1)])
        assert result['review_ref'] and reconcile(cs,reviewer.task_id)['execution_complete']
    packet=json.loads(model.calls[0][1][1])
    assert next(e for e in packet['evidence'] if e['kind']=='source_blocks')['selection']=={'source_id':'s','offset':0,'limit':1}


async def test_source_object_id_error_exposes_file_id_without_paid_call(ws):
    from report_agent.evidence_analysis import SourceSelection
    cs, _, refs, snapshot, _ = seed(ws)
    source=next(r for r in cs.read(snapshot)['payload']['refs'] if r['type']=='SourceArtifact')
    call=review_call(snapshot,refs)
    requirement=call['args']['review_requirements'][0]
    requirement['required_materials'][0]['refs'].append(refs['evidence'])
    requirement['source_ranges']=[{'source_ref':source,'offset':0,'limit':1}]
    model=Model()
    with delegated_task(ws,'coordinator',call) as (_,reviewer):
        with pytest.raises(ActionRejected,match='SOURCE_OUTSIDE_ASSIGNED_POOL') as caught:
            await perform_review(ws,reviewer,model,'wrong-id',['rule-comparison'],
                source_selections=[SourceSelection(source_id=source['id'],offset=0,limit=1)])
        correction=json.loads(str(caught.value).split(': ',1)[1])
        assert correction['model_called'] is False and correction['allowed_source_ids']==['s']
        assert correction['source_selection_bindings'][0]['source_ref']==source
        assert correction['source_selection_bindings'][0]['source_id']=='s'
        assert not model.calls
        result=await perform_review(ws,reviewer,model,'correct-id',['rule-comparison'],
            source_selections=[SourceSelection(source_id='s',offset=0,limit=1)])
        assert result['review_ref'] and len(model.calls)==1


def test_native_assignment_exposes_only_task_declared_source_mapping(ws):
    from report_agent.hierarchical_tools import content_tools
    cs, _, refs, snapshot, _ = seed(ws)
    source=next(r for r in cs.read(snapshot)['payload']['refs'] if r['type']=='SourceArtifact')
    call=review_call(snapshot,refs)
    call['args']['review_requirements'][0]['source_ranges']=[{'source_ref':source,'offset':0,'limit':1}]
    with delegated_task(ws,'coordinator',call):
        read=next(t for t in content_tools(ws,'reviewer') if t.__name__=='read_task_assignment')
        result=read()
        assert result['source_selection_bindings']==[{'scope_id':'rule-comparison','source_ref':source,
            'source_id':'s','offset':0,'limit':1}]
        assert 'content' not in result['source_selection_bindings'][0]


async def test_snapshot_members_do_not_automatically_expand_task_material_pool(ws):
    from report_agent.content_selection import ContentSelection
    cs, _, refs, snapshot, _ = seed(ws)
    model = Model()
    with delegated_task(ws, "coordinator", review_call(snapshot, refs)) as (_, reviewer):
        with pytest.raises(ActionRejected, match="OUTSIDE_ASSIGNED_POOL"):
            await perform_review(ws, reviewer, model, "outside", ["rule-comparison"],
                content_selections=[ContentSelection(ref=refs["root"])])
    assert not model.calls


async def test_completed_check_must_cite_declared_rule_not_just_have_it_loaded(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    source = next(r for r in cs.read(snapshot)["payload"]["refs"] if r["type"] == "SourceArtifact")
    call = review_call(snapshot, refs, reads=[source])
    call["args"]["review_requirements"][0]["required_materials"][0]["refs"].append(refs["evidence"])
    model = Model()
    with delegated_task(ws, "coordinator", call) as (_, reviewer):
        with pytest.raises(ActionRejected, match="COMPLETED_CHECK_MISSING_REQUIRED_MATERIAL"):
            await perform_review(ws, reviewer, model, "uncited", ["rule-comparison"])
    assert len(model.calls) == 1 and not cs.list_objects("ReviewRecord")
    assert json.loads(model.calls[0][1][1])["evidence"][2]["object"]["ref"] == refs["evidence"]


def test_direct_submission_cannot_bypass_required_evidence(ws):
    from test_hierarchical_content import review_item, submission
    cs, _, refs, snapshot, _ = seed(ws)
    call = review_call(snapshot, refs)
    call["args"]["review_requirements"][0]["required_materials"][0]["refs"].append(refs["evidence"])
    with delegated_task(ws, "coordinator", call) as (_, reviewer):
        receipt = cs.read_context(reviewer, refs["claim"])["receipt_id"]
        item = review_item(refs["claim"], refs["k"], receipt)
        item.update(scope_id="rule-comparison", checked_requirement_indexes=[0], check_results=[{
            "requirement_index": 0, "execution_state": "completed", "result": "Compared claim with rule.",
            "observation_indexes": [0], "remaining": ""}])
        with pytest.raises(ActionRejected, match="MISSING_REQUIRED_MATERIAL"):
            cs.submit_review(reviewer, "bypass", submission(snapshot, refs, item), {})
        source_receipt = cs.read_context(reviewer, refs["evidence"])["receipt_id"]
        item["observations"].append({"receipt_id": source_receipt, "locator": "rule excerpt",
            "observation": "B permits75–100, so70 conflicts."})
        item["check_results"][0]["observation_indexes"].append(1)
        saved = cs.submit_review(reviewer, "supported", submission(snapshot, refs, item), {})
        assert cs.read(saved["result"]["review_ref"])["payload"]["items"][0]["verdict"] == "not_satisfied"


async def test_source_selection_requires_declared_source_pool(ws):
    from report_agent.evidence_analysis import SourceSelection
    cs, _, refs, snapshot, _ = seed(ws)
    model = Model()
    with delegated_task(ws, "coordinator", review_call(snapshot, refs)) as (_, reviewer):
        with pytest.raises(ActionRejected, match="SOURCE_OUTSIDE_ASSIGNED_POOL"):
            await perform_review(ws, reviewer, model, "outside-source", ["rule-comparison"],
                source_selections=[SourceSelection(source_id="s")])
    assert not model.calls


async def test_selected_already_required_node_is_not_duplicated_in_checker_input(ws):
    from report_agent.content_selection import ContentSelection
    cs, _, refs, snapshot, _ = seed(ws)
    source = next(r for r in cs.read(snapshot)["payload"]["refs"] if r["type"] == "SourceArtifact")
    model = Model()
    with delegated_task(ws, "coordinator", review_call(snapshot, refs, reads=[source])) as (_, reviewer):
        await perform_review(ws, reviewer, model, "selected", ["rule-comparison"],
            content_selections=[ContentSelection(ref=refs["claim"])])
    evidence = json.loads(model.calls[0][1][1])["evidence"]
    assert len([e for e in evidence if e['kind']=='saved_object']) == 2
    assert len([e for e in evidence if e['kind']=='snapshot_structure']) == 1
