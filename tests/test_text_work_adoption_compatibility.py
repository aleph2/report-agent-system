"""Preserve existing Any equality and the original received representation."""
from copy import deepcopy
import json
import math
import os
from pathlib import Path

import pytest

from report_agent.content_tasks import delegated_task
from report_agent.errors import ActionRejected
from report_agent.text_work import AdoptionObject, encode
from test_bounded_review import Model
from test_hierarchical_content import seed
from test_task_supervision import ws, offline
from test_text_work import content, tools, writer_call


@pytest.mark.parametrize("variant", ["int-float", "signed-zero", "key-order", "changed-value"])
async def test_adoption_preserves_existing_equality_and_received_payload(ws, tmp_path, variant):
    cs, _, refs, _, _ = seed(ws)
    originals = deepcopy(cs.list_objects())
    original = content()
    original["qualifiers"]["measurement"] = -0.0 if variant == "signed-zero" else 1
    original["qualifiers"]["nested"] = {"dynamic": None, "flag": False, "zero": 0,
                                        "empty": "", "sequence": [2, 1]}
    model = Model(json.dumps(original))
    capture = {"variant": variant, "originals": originals, "raw_output": json.dumps(original)}
    with delegated_task(ws, "coordinator", writer_call()) as (_, actor):
        t = tools(ws, "writer", model)
        work = await t["process_report_content"]("produce", "Describe the selected synthetic rule",
                                                  "ContentNode", [refs["claim"]])
        receipt_key = "text_work_receipt:" + work["text_work_id"]
        receipt = deepcopy(ws.store.get(receipt_key))
        submitted = deepcopy(work["payload"])
        if variant == "int-float":
            submitted["qualifiers"]["measurement"] = 1.0
        elif variant == "signed-zero":
            submitted["qualifiers"]["measurement"] = 0.0
        elif variant == "key-order":
            submitted["qualifiers"]["nested"] = dict(reversed(list(submitted["qualifiers"]["nested"].items())))
        else:
            submitted["qualifiers"]["measurement"] = 2
        capture.update(actor=actor.__dict__, receipt_before=receipt, submitted=submitted)
        try:
            args = [AdoptionObject(client_key="node", type="ContentNode", payload=submitted,
                                   text_work_id=work["text_work_id"])]
            if variant == "changed-value":
                with pytest.raises(ActionRejected, match="TEXT_WORK_OUTPUT_CHANGED") as error:
                    t["commit_objects"]("adopt", args)
                capture["rejection"] = str(error.value)
            else:
                saved = t["commit_objects"]("adopt", args)
                capture["saved_result"] = saved
        finally:
            capture.update(receipt_after=ws.store.get(receipt_key), objects=cs.list_objects(),
                           independent_calls=model.calls, events=ws.store.events())
            root = Path(os.environ.get("ADOPTION_COMPAT_EVIDENCE", str(tmp_path / "evidence")))
            root.mkdir(parents=True, exist_ok=True)
            (root / (variant + ".json")).write_text(json.dumps(capture, ensure_ascii=False, indent=2), encoding="utf-8")

        new_nodes = [o for o in cs.list_objects("ContentNode") if o["ref"] not in [x["ref"] for x in originals]]
        assert len(model.calls) == 1
        assert ws.store.get(receipt_key) == receipt
        assert all(cs.read(o["ref"]) == o for o in originals)
        if variant == "changed-value":
            assert new_nodes == []
        else:
            assert len(new_nodes) == 1
            node = new_nodes[0]
            assert node["owner_id"] == actor.id
            assert encode(node["payload"]) == encode(receipt["result"]["payloads"][0])
            if variant == "int-float":
                assert type(node["payload"]["qualifiers"]["measurement"]) is int
            elif variant == "signed-zero":
                assert math.copysign(1, node["payload"]["qualifiers"]["measurement"]) == -1
