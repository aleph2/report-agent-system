"""Malformed received output is not a failure of valid Reviewer arguments."""
from copy import deepcopy
import json
import os
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest

from duty_probe_visual_packets import prepare_visual, perform_public_visual_and_artifact
from test_bounded_review import Model
from test_task_supervision import ws, offline
from test_vision import VisionModel


async def test_malformed_received_artifact_json_has_output_phase_and_original_receipt(ws, tmp_path, monkeypatch):
    import langgraph.prebuilt.tool_node as tool_node
    folder = Path(os.environ.get("ARTIFACT_PHASE_EVIDENCE", str(tmp_path / "evidence")))
    folder.mkdir(parents=True, exist_ok=True)
    prepared = await prepare_visual(ws, folder, include_note_column=True)
    cs = prepared["cs"]
    originals = deepcopy(cs.list_objects())
    raw = '{"items": [broken output'
    model = Model(raw)
    vision = VisionModel(content="Synthetic visible table; no semantic acceptance.")
    constructions = []
    original_constructor = tool_node.ToolInvocationError.__init__
    def observe(self, tool_name, source, tool_kwargs, filtered_errors=None):
        original_constructor(self, tool_name, source, tool_kwargs, filtered_errors)
        constructions.append({"tool": tool_name, "schema": source.title, "arguments": deepcopy(tool_kwargs),
                              "errors": source.errors(include_input=False, include_context=False)})
    monkeypatch.setattr(tool_node.ToolInvocationError, "__init__", observe)
    capture = {"raw": raw, "originals": originals}
    try:
        result = await perform_public_visual_and_artifact(ws, prepared, folder, vision_client=vision,
            artifact_model=model, operation_prefix="malformed-output")
        capture["result"] = result
    except Exception as exc:
        capture["execution_error"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        capture.update(constructions=constructions, calls=model.calls)
        (folder / "phase-capture.json").write_text(json.dumps(capture, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            await vision.close()
            with ws.store.connect() as db:
                capture["analyses"] = {row[0]: json.loads(row[1]) for row in db.execute("SELECT operation,data FROM analyses")}
            capture.update(objects=cs.list_objects(), events=ws.store.events())
        except Exception as exc:
            capture["observer_error"] = {"type": type(exc).__name__, "message": str(exc)}
            raise
        finally:
            (folder / "phase-capture.json").write_text(json.dumps(capture, ensure_ascii=False, indent=2), encoding="utf-8")
    assert result["runtime_result"]["last_error"] is None
    schema = next(t["parameters"] for t in result["bindings"]["reviewer"][0] if t["name"] == "perform_assigned_artifact_review")
    Draft202012Validator(schema).validate(result["actual_caller_args"])
    assert len(model.calls) == len(vision.calls) == 1
    assert not any(entry["tool"] == "perform_assigned_artifact_review" and entry["schema"] == "ReviewSubmission" for entry in constructions)
    message = result["next_reviewer_tool_message"]["content"]
    assert "ARTIFACT_REVIEW_OUTPUT_CONTRACT_INVALID" in message
    assert "raw_operation" in message and "raw_response_received" in message
    original_raw, = [record for record in capture["analyses"].values() if record.get("analysis") == raw]
    assert original_raw["operation"] in message
    assert not cs.list_objects("ReviewRecord") and result["saved_review"] is None
    assert all(cs.read(record["ref"]) == record for record in originals)
