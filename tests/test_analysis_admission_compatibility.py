"""Original text preservation and read-only refusal of historical invalid cache."""
from copy import deepcopy
import json
import os
from pathlib import Path

import pytest

from report_agent.content_tasks import delegated_task
from report_agent.errors import ActionRejected
from report_agent.evidence_analysis import ANALYSIS_PROMPT, model_identity, selected_evidence
from report_agent.store import digest
from test_bounded_review import Model
from test_hierarchical_content import seed
from test_task_supervision import ws, offline
from test_text_work import tools, writer_call


@pytest.mark.parametrize("variant", ["padded-nonblank", "legacy-blank"])
async def test_shared_analysis_success_admission_preserves_original_and_history(ws, tmp_path, variant):
    cs, _, _, _, _ = seed(ws)
    originals = deepcopy(cs.list_objects())
    question = "Describe only the supplied synthetic rule."
    selections = [{"source_id": "s", "offset": 0, "limit": 1}]
    model = Model(" \nComplete synthetic observation.\t ")
    inputs = {"question": question, "evidence": selected_evidence(ws, selections, [])}
    operation = digest({"system": ANALYSIS_PROMPT, "input": inputs,
                        "model": model_identity(model), "contract": "selected-evidence-v3"})
    attempt_key = "bounded_review_attempt:" + operation
    historical = {"operation": operation, "analysis": " \n\t ", "model": model_identity(model),
                  "evidence": inputs["evidence"], "usage": {"total_tokens": 17},
                  "duration_seconds": 0.1, "scope_note": "Historical fixture, not a new response."}
    prior_attempt = {"state": "completed", "operation": operation, "result": historical}
    if variant == "legacy-blank":
        ws.store.analysis(operation, historical)
        ws.store.set(attempt_key, prior_attempt)
    capture = {"variant": variant, "inputs": inputs, "historical_fixture": historical,
               "originals": originals, "operation": operation}
    with delegated_task(ws, "coordinator", writer_call()):
        t = tools(ws, "writer", model)
        try:
            capture["first"] = await t["analyze_text"]("s", question, 0, 1)
            capture["second"] = await t["analyze_text"]("s", question, 0, 1)
        except ActionRejected as exc:
            capture["rejection"] = str(exc)
        finally:
            capture.update(cached_after=ws.store.analysis(operation), attempt_after=ws.store.get(attempt_key),
                           events=ws.store.events(), independent_calls=model.calls, objects=cs.list_objects())
            root = Path(os.environ.get("ANALYSIS_COMPAT_EVIDENCE", str(tmp_path / "evidence")))
            root.mkdir(parents=True, exist_ok=True)
            (root / (variant + ".json")).write_text(json.dumps(capture, ensure_ascii=False, indent=2), encoding="utf-8")
    assert all(cs.read(o["ref"]) == o for o in originals)
    if variant == "legacy-blank":
        assert "EVIDENCE_ANALYSIS_EMPTY_RESPONSE" in capture.get("rejection", "")
        assert "cache_read" in capture["rejection"]
        assert model.calls == []
        assert capture["cached_after"] == historical
        assert capture["attempt_after"] == prior_attempt
        assert not any(e["kind"] == "evidence_analysis_reused" for e in capture["events"])
    else:
        assert "rejection" not in capture
        assert capture["first"]["analysis"] == capture["second"]["analysis"] == model.response
        assert capture["first"]["reused"] is False and capture["second"]["reused"] is True
        assert len(model.calls) == 1
