"""Actual failed handoff class: describe constraints without changing arguments."""
from copy import deepcopy
import json

import pytest
from langchain_core.messages import AIMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

from report_agent.content_tasks import task_tool
from report_agent.deep_runtime import BusinessBoundary
from report_agent.prompt_sources import NATIVE_REVIEW, load_prompt
from test_hierarchical_content import ws, seed
from test_native_task_error_boundary import registered_task
from test_native_review_handoff import wire_run, handoff
from test_reviewer_native_profile import native
from test_deep_runtime import call


@pytest.fixture(autouse=True)
def clarified_interface(ws):
    ws.store.set('manifest', {**ws.store.manifest, 'review_interface_profile': 'review-interfaces-v2'})


def index_fields(value):
    if isinstance(value, dict):
        if "requirement_index" in value.get("properties", {}):
            yield value["properties"]["requirement_index"]
        for child in value.values():
            yield from index_fields(child)
    elif isinstance(value, list):
        for child in value:
            yield from index_fields(child)


async def test_final_sdk_explains_local_indexes_and_distinct_scope_rules(ws):
    _, _, _, wires = await wire_run(ws, delegate=False)
    body = next(body for role, body in wires if role == "coordinator")
    task = next(t["function"] for t in body["tools"] if t["function"]["name"] == "task")
    fields = list(index_fields(task["parameters"]))
    assert len(fields) >= 3
    for field in fields:
        text = field.get("description", "")
        assert "required_checks" in text and "zero-based" in text.lower()
        assert "outer" in text and "less than" in text
    public = json.dumps(task)
    assert "at most one" in public and "different nodes" in public
    assert "artifact_check_scopes" in load_prompt("native-review-handoff-v2")
    item = task['parameters']['properties']['review_requirements']['anyOf'][0]['items']
    target = item['properties']['target_ref']['description']
    assert 'snapshot' in target and 'member' in target and 'artifact_refs' in target


async def test_invalid_scope_feedback_names_local_range_duplicates_and_keeps_original(ws):
    native(ws)
    cs, _, refs, snapshot, _ = seed(ws)
    args = handoff(snapshot, refs)
    item = args["review_requirements"][0]
    item["assessment_kind"] = "export"
    artifact = {"type": "ExportArtifact", "id": "not-admitted", "version": 1}
    item["required_checks"] = ["Compare two assigned artifact versions"]
    item["artifact_refs"] = [artifact]
    item["artifact_check_scopes"] = [
        {"requirement_index": 3, "kind": "export_structure", "artifact_ref": artifact},
        {"requirement_index": 3, "kind": "export_structure", "artifact_ref": artifact},
    ]
    original = deepcopy(args)
    action = call("task", args, "scope-error")
    tool = registered_task()
    request = ToolCallRequest(tool_call=action, tool=tool,
        state={"messages": [AIMessage("", tool_calls=[action])]}, runtime=None)
    reached = []

    async def handler(request):
        reached.append(request)
        raise AssertionError("Invalid contract must not reach native child")

    message = await BusinessBoundary(ws, "coordinator").awrap_tool_call(request, handler)
    data = json.loads(message.content)
    assert data["code"] == "INVALID_REVIEW_REQUIREMENTS"
    issues = data["review_contract_issues"]
    assert {i["code"] for i in issues} >= {"CHECK_INDEX_OUT_OF_RANGE", "ARTIFACT_CHECK_SCOPE_DUPLICATE_INDEX"}
    invalid = next(i for i in issues if i["code"] == "CHECK_INDEX_OUT_OF_RANGE")
    assert invalid["path"] == "review_requirements/0/artifact_check_scopes/0/requirement_index"
    assert invalid["allowed_index_range"] == {"minimum": 0, "exclusive_maximum": 1}
    assert invalid["actual_index"] == 3
    assert not reached and args == original
    assert not cs.list_objects("DelegatedTask")


def test_native_contract_preserves_valid_multiple_content_nodes_and_materials_per_check(ws):
    native(ws)
    _, _, refs, snapshot, _ = seed(ws)
    args = handoff(snapshot, refs)
    item = args["review_requirements"][0]
    item["content_check_scopes"] = [
        {"requirement_index": 0, "node_ref": node, "kind": "local_body"}
        for node in [refs["root"], refs["claim"]]
    ]
    item["required_materials"] = [
        {"requirement_index": 0, "purpose": "Required evidence " + str(i), "refs": [node]}
        for i, node in enumerate([refs["root"], refs["claim"]])
    ]
    original = deepcopy(args)
    projected = task_tool(registered_task(), review_profile=NATIVE_REVIEW, interface_profile='review-interfaces-v2')
    assert projected.tool_call_schema.model_validate(args)
    assert args == original


async def test_content_outer_index_is_rejected_by_actual_readiness_before_reviewer(ws):
    native(ws)
    cs, _, refs, snapshot, _ = seed(ws)
    args = handoff(snapshot, refs)
    item = args['review_requirements'][0]
    item['required_checks'] = ['First check', 'Second check', 'Third check']
    item['content_check_scopes'] = [
        {'requirement_index': 4, 'node_ref': refs['root'], 'kind': 'local_body'}]
    action = call('task', args, 'content-scope-range')
    request = ToolCallRequest(tool_call=action, tool=registered_task(),
        state={'messages': [AIMessage('', tool_calls=[action])]}, runtime=None)
    reached = []

    async def handler(request):
        reached.append(request)
        raise AssertionError('Out-of-range scope cannot start Reviewer')

    message = await BusinessBoundary(ws, 'coordinator').awrap_tool_call(request, handler)
    assert message.status == 'error'
    assert 'CONTENT_CHECK_SCOPE_OUTSIDE_ASSIGNMENT' in message.content
    assert 'check index outside assignment' in message.content
    assert not reached and not cs.list_objects('DelegatedTask')


def property_fields(value, name):
    if isinstance(value, dict):
        if name in value.get('properties', {}):
            yield value['properties'][name]
        for child in value.values():
            yield from property_fields(child, name)
    elif isinstance(value, list):
        for child in value:
            yield from property_fields(child, name)


async def test_actual_reviewer_sdk_submission_explains_item_local_check_and_observation_indexes(ws):
    _, _, _, wires = await wire_run(ws, delegate=True)
    body = next(body for role, body in wires if role == 'reviewer')
    submit = next(t['function'] for t in body['tools'] if t['function']['name'] == 'submit_review')
    indexes = list(property_fields(submit['parameters'], 'requirement_index'))
    assert len(indexes) == 2
    for field in indexes:
        text = field.get('description', '')
        assert 'scope' in text and 'required_checks' in text and 'zero-based' in text.lower()
        assert 'outer' in text
    for field in property_fields(submit['parameters'], 'observation_indexes'):
        text = field.get('description', '')
        assert 'this ReviewItem.observations' in text and 'zero-based' in text.lower()
    for field in property_fields(submit['parameters'], 'target_ref'):
        assert 'artifact_refs' in field.get('description', '')


def test_native_submission_keeps_two_items_local_zero_and_original_rejections(ws):
    from report_agent.content_tasks import native_review_submission_schema
    from report_agent.content_models import ReviewSubmission
    from test_hierarchical_content import review_item, submission
    native(ws)
    _, _, refs, snapshot, _ = seed(ws)
    legacy = deepcopy(ReviewSubmission.model_json_schema())
    item = review_item(refs['claim'], refs['k'], 'offline-schema-fixture', verdict='undetermined')
    item['check_results'] = [{'requirement_index': 0, 'execution_state': 'completed',
        'result': 'Synthetic schema comparison only', 'observation_indexes': [0], 'remaining': ''}]
    item['checked_requirement_indexes'] = [0]
    item['findings'] = [{'finding_type': 'candidate', 'locator_state': 'located',
        'description': 'Synthetic candidate', 'impact': 'Fixture only', 'needed_outcome': 'Verify',
        'requirement_index': 0, 'observation_indexes': [0]}]
    value = submission(snapshot, refs, item)
    value['items'].append(deepcopy(item))
    projected = native_review_submission_schema()
    assert projected.model_validate(value).model_dump() == ReviewSubmission.model_validate(value).model_dump()
    for change in ['duplicate-check', 'observation-outside-item']:
        invalid = deepcopy(value)
        if change == 'duplicate-check':
            invalid['items'][0]['check_results'] *= 2
        else:
            invalid['items'][1]['check_results'][0]['observation_indexes'] = [1]
        for schema in [projected, ReviewSubmission]:
            with pytest.raises(ValueError):
                schema.model_validate(invalid)
    assert ReviewSubmission.model_json_schema() == legacy


@pytest.mark.parametrize('target', ['export', 'render', 'snapshot', 'member'])
def test_artifact_assignments_require_snapshot_targets_not_external_artifacts(ws, target):
    from test_artifact_review import setup
    from report_agent.content_tasks import delegated_task
    from report_agent.errors import ActionRejected
    cs, refs, snapshot, export, render, _, action = setup(ws, pages=1, reference=False)
    native(ws)
    targets = {'export': export, 'render': render, 'snapshot': snapshot, 'member': refs['root']}
    action = deepcopy(action)
    action['args']['review_requirements'][0]['target_ref'] = targets[target]
    if target in {'export', 'render'}:
        with pytest.raises(ActionRejected, match='TASK_REVIEW_REQUIREMENT_OUTSIDE_SNAPSHOT'):
            with delegated_task(ws, 'coordinator', action):
                pytest.fail('External artifacts cannot become saved review targets')
        assert not cs.list_objects('DelegatedTask')
    else:
        with delegated_task(ws, 'coordinator', action) as (_, reviewer):
            assert reviewer.role == 'reviewer'
        assert len(cs.list_objects('DelegatedTask')) == 1
