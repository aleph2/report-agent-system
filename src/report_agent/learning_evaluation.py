"""Host-owned, persisted optimization experiments; never auto-publishes a policy."""
from __future__ import annotations

import json
import math
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from .store import digest


def strategy_texts(program):
    return {name: predictor.signature.instructions for name, predictor in program.named_predictors()}


def _write(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def run_experiment(student, trainset, valset, holdout, metric, reflection_model, *,
                   output_directory, max_metric_calls, evaluator_version, model_identity,
                   optimizer=None):
    """Call only with explicit model authorization. Datasets contain DSPy Examples.

    The optimizer receives train/validation only. Holdout is evaluated afterwards
    with the same host metric, whose version is recorded. IDs and input digests
    detect accidental duplicate inputs across splits; they cannot prove semantic
    independence. Output files contain strategy/evaluation data, not credentials.
    """
    if not evaluator_version.strip() or not model_identity.strip():
        raise ValueError("EVALUATOR_AND_MODEL_IDENTITY_REQUIRED")
    if not 1 <= max_metric_calls <= 1000:
        raise ValueError("INVALID_METRIC_CALL_LIMIT")
    seen_ids, seen_inputs, identities = set(), set(), {}
    for split, rows in (("train", trainset), ("validation", valset), ("holdout", holdout)):
        if not rows:
            raise ValueError("NONEMPTY_DATA_SPLITS_REQUIRED")
        identities[split] = []
        for row in rows:
            identifier = row["case_id"]
            fingerprint = digest(dict(row.inputs()))
            if identifier in seen_ids or fingerprint in seen_inputs:
                raise ValueError("EVALUATION_SPLIT_LEAKAGE")
            seen_ids.add(identifier)
            seen_inputs.add(fingerprint)
            identities[split].append({"case_id": identifier, "input_digest": fingerprint})
    root = Path(output_directory)
    root.mkdir(parents=True, exist_ok=False)
    baseline_program = deepcopy(student)
    baseline = strategy_texts(baseline_program)
    record = {"schema_version": 1, "state": "running", "started_at": datetime.now(timezone.utc).isoformat(),
              "model_identity": model_identity, "evaluator_version": evaluator_version,
              "max_metric_calls": max_metric_calls, "datasets": identities,
              "baseline": baseline, "automatic_release": False,
              "limit_note": "GEPA metric-call limit excludes holdout and is not a monetary cap."}
    _write(root / "experiment.json", record)
    try:
        if optimizer is None:
            from .learning_runtime import optimize_with_gepa
            optimizer = optimize_with_gepa
        candidate = optimizer(student, trainset, valset, metric, reflection_model,
                              max_metric_calls=max_metric_calls)
        results = []
        for example in holdout:
            pair = {}
            for name, program in (("baseline", baseline_program), ("candidate", candidate)):
                prediction = program(**dict(example.inputs()))
                value = metric(example, prediction, None, None, None)
                score = float(value["score"] if hasattr(value, "__getitem__") else value)
                if not math.isfinite(score) or not 0 <= score <= 1:
                    raise ValueError("INVALID_EVALUATION_SCORE")
                feedback = value.get("feedback", "") if hasattr(value, "get") else ""
                pair[name] = {"score": score, "feedback": feedback}
            results.append({"case_id": example["case_id"], **pair})
        import importlib.metadata
        versions = {}
        for package in ("dspy", "gepa"):
            try:
                versions[package] = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError:
                versions[package] = None
        record.update(state="completed", candidate=strategy_texts(candidate), holdout=results,
                      packages=versions, regressions=[r["case_id"] for r in results
                      if r["candidate"]["score"] < r["baseline"]["score"]])
        details = getattr(candidate, "detailed_results", None)
        if details:
            record["optimizer_summary"] = {key: getattr(details, key, None) for key in
                ("total_metric_calls", "num_full_val_evals", "val_aggregate_scores")}
        _write(root / "experiment.json", record)
        return candidate, record
    except BaseException as exc:
        record.update(state="failed", error_type=type(exc).__name__)
        _write(root / "experiment.json", record)
        raise
