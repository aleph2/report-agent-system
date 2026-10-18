"""Actual optional optimizer integration, scripted local LMs, never quality proof."""
import json
import os
import socket

import pytest

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
dspy = pytest.importorskip("dspy")
from dspy.utils import DummyLM

from report_agent.learning_evaluation import run_experiment


def test_actual_gepa_compile_and_persist_without_network(tmp_path, monkeypatch):
    def forbid(*args, **kwargs):
        raise AssertionError("External network forbidden in optimizer smoke test")
    monkeypatch.setattr(socket.socket, "connect", forbid)
    student = dspy.Predict("question -> answer")
    task_model = DummyLM([{"answer": "yes"}] * 100)
    student.set_lm(task_model)
    reflection = DummyLM([{"new_instructions": "Return yes for this synthetic fixture."}] * 100)
    def metric(gold, pred, trace=None, pred_name=None, pred_trace=None):
        return dspy.Prediction(score=float(pred.answer == "yes"), feedback="Synthetic fixture only")
    def case(name):
        return dspy.Example(case_id=name, question=name, answer="yes").with_inputs("question")
    _, record = run_experiment(student, [case("train")], [case("val")], [case("holdout")],
        metric, reflection, output_directory=tmp_path / "experiment", max_metric_calls=4,
        evaluator_version="synthetic-yes-v1", model_identity="dspy-DummyLM-offline")
    assert record["state"] == "completed"
    assert record["automatic_release"] is False
    assert record["packages"]["dspy"] == "3.4.0"
    assert record["packages"]["gepa"] == "0.1.4"
    saved = json.loads((tmp_path / "experiment" / "experiment.json").read_text())
    assert saved["holdout"][0]["baseline"]["score"] == 1
    assert saved["holdout"][0]["candidate"]["score"] == 1
