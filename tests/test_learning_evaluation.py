"""Pure offline experiment persistence and holdout boundaries."""
import json
from types import SimpleNamespace

import pytest

from report_agent.learning_evaluation import run_experiment


class Case(dict):
    def inputs(self):
        return {"question": self["question"]}


class Program:
    def __init__(self, instruction):
        self.instruction = instruction

    def named_predictors(self):
        return [("answer", SimpleNamespace(signature=SimpleNamespace(instructions=self.instruction)))]

    def __call__(self, **inputs):
        return {"answer": self.instruction}


def data():
    return [[Case(case_id=name, question=name)] for name in ("train", "validation", "holdout")]


def metric(example, prediction, *args):
    return {"score": 1 if prediction["answer"] == "new" else 0, "feedback": "synthetic fixture"}


def test_experiment_preserves_baseline_and_withholds_holdout(tmp_path):
    train, val, holdout = data()
    def optimize(student, trainset, valset, evaluator, model, **kwargs):
        assert trainset == train and valset == val
        assert kwargs["max_metric_calls"] == 5
        student.instruction = "new"  # Baseline must survive in-place optimization.
        return student
    root = tmp_path / "trial"
    _, record = run_experiment(Program("old"), train, val, holdout, metric, None,
        output_directory=root, max_metric_calls=5, evaluator_version="synthetic-v1",
        model_identity="offline-fixture", optimizer=optimize)
    assert record["state"] == "completed"
    assert record["baseline"]["answer"] == "old"
    assert record["candidate"]["answer"] == "new"
    assert record["holdout"][0]["case_id"] == "holdout"
    assert record["holdout"][0]["baseline"]["score"] == 0
    assert not record["automatic_release"]
    assert json.loads((root / "experiment.json").read_text()) == record
    with pytest.raises(FileExistsError):
        run_experiment(Program("old"), train, val, holdout, metric, None, output_directory=root,
            max_metric_calls=5, evaluator_version="v1", model_identity="fixture", optimizer=optimize)


def test_different_ids_cannot_hide_duplicate_inputs(tmp_path):
    train, val, holdout = data()
    holdout[0]["question"] = train[0]["question"]
    with pytest.raises(ValueError, match="SPLIT_LEAKAGE"):
        run_experiment(Program("old"), train, val, holdout, metric, None,
            output_directory=tmp_path / "trial", max_metric_calls=5,
            evaluator_version="v1", model_identity="fixture")
    assert not (tmp_path / "trial").exists()


def test_failure_is_persisted_without_exception_payload(tmp_path):
    def fail(*args, **kwargs):
        raise RuntimeError("private provider payload")
    with pytest.raises(RuntimeError):
        run_experiment(Program("old"), *data(), metric, None, output_directory=tmp_path / "trial",
            max_metric_calls=5, evaluator_version="v1", model_identity="fixture", optimizer=fail)
    result = (tmp_path / "trial" / "experiment.json").read_text()
    assert json.loads(result)["state"] == "failed"
    assert "private provider" not in result
