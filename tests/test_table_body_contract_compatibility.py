"""Table shape constraints preserve original cells, auxiliary keys and dicts."""
from copy import deepcopy
import json
import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from report_agent.content_models import ContentNode
from report_agent.content_tasks import delegated_task
from report_agent.errors import ActionRejected
from test_bounded_review import Model
from test_hierarchical_content import seed
from test_task_supervision import ws, offline
from test_text_work import tools, writer_call


@pytest.mark.parametrize("variant", ["preserve", "width", "empty-columns"])
async def test_table_body_registered_production_constraints(ws, tmp_path, variant):
    cs, _, refs, _, _ = seed(ws)
    originals = deepcopy(cs.list_objects())
    body = {"columns": ["A", "B", "C", "D"], "rows": [[None, False, 0, ""]],
            "title": "Synthetic table", "footnote": "Preserve complete note.",
            "dynamic": {"unknown": None, "ordered": [2, 1]}}
    if variant == "width":
        body["rows"] = [[1, 2]]
    elif variant == "empty-columns":
        body["columns"] = []
    payload = {"kind": "table", "body": body, "qualifiers": {}, "claim_kind": "structure"}
    schema = ContentNode.model_json_schema()
    table_schema = next(rule["then"]["properties"]["body"] for rule in schema["allOf"]
                        if rule["if"]["properties"]["kind"].get("const") == "table")
    assert table_schema["properties"]["columns"]["minItems"] == 1
    assert table_schema["properties"]["rows"]["items"]["type"] == "array"
    empty = {**payload, "body": {"columns": ["A"], "rows": []}}
    assert ContentNode.model_validate(empty).body == empty["body"]
    model = Model(json.dumps(payload))
    capture = {"variant": variant, "payload": payload, "public_schema": schema,
               "originals": originals}
    with delegated_task(ws, "coordinator", writer_call()) as (_, actor):
        capture["actor"] = actor.__dict__
        t = tools(ws, "writer", model)
        try:
            work = await t["process_report_content"]("table", "Format the selected synthetic table", "ContentNode", [refs["claim"]])
            capture["work"] = work
            capture["receipt"] = deepcopy(ws.store.get("text_work_receipt:" + work["text_work_id"]))
            saved = t["save_text_node"]("save", work["text_work_id"])
            capture["saved"] = saved
        except ActionRejected as exc:
            capture["rejection"] = str(exc)
        finally:
            capture.update(events=ws.store.events(), objects=cs.list_objects(), independent_calls=model.calls)
            root = Path(os.environ.get("TABLE_COMPAT_EVIDENCE", str(tmp_path / "evidence")))
            root.mkdir(parents=True, exist_ok=True)
            (root / (variant + ".json")).write_text(json.dumps(capture, ensure_ascii=False, indent=2), encoding="utf-8")
        if variant == "preserve":
            assert "rejection" not in capture
            node = cs.read(capture["saved"]["result"]["refs"]["text"])
            actual = node["payload"]
            assert node["owner_id"] == capture["receipt"]["result"]["actor_id"] == actor.id
            assert capture["receipt"]["result"]["task_id"] == actor.task_id
            assert json.dumps(actual["body"], sort_keys=True) == json.dumps(body, sort_keys=True)
            assert type(actual["body"]["rows"][0][1]) is bool
            assert type(actual["body"]["rows"][0][2]) is int
        else:
            assert "TEXT_WORK_OUTPUT_CONTRACT_INVALID" in capture.get("rejection", "")
            assert "work" not in capture
            assert not any(event["kind"] == "text_work_completed" for event in capture["events"])
            assert cs.list_objects("ContentNode") == [o for o in originals if o["ref"]["type"] == "ContentNode"]
        assert len(model.calls) == 1
        assert all(cs.read(o["ref"]) == o for o in originals)


@pytest.mark.parametrize("body", [
    {"columns": ["A"], "rows": ([1],)},
    {"columns": ["A"], "rows": [(1,)]},
])
def test_non_json_host_containers_cannot_evade_advertised_array_shape(body, tmp_path):
    # Host-only containers: JSON model responses cannot themselves contain tuples.
    capture = {"input_repr": repr(body), "rows_type": type(body["rows"]).__name__,
               "row_type": type(body["rows"][0]).__name__}
    try:
        ContentNode.model_validate({"kind": "table", "body": body, "qualifiers": {}, "claim_kind": "structure"})
    except ValidationError as exc:
        capture["validation_error"] = exc.errors(include_input=False, include_context=False)
    finally:
        (tmp_path / "host-input-capture.json").write_text(json.dumps(capture, indent=2), encoding="utf-8")
    assert "validation_error" in capture
