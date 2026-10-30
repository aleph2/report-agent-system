import json
from pathlib import Path

import pytest

from report_agent.report_learning import (CHECKS, COMPONENT, candidate_visible,
    score_judgment, validate_splits, validate_candidate, prepare_rollout, read_json)
from report_agent.learning import LearningLibrary, LearningScope, guidance_context
from report_agent.store import digest
from report_agent.errors import ActionRejected


def example(identifier, text):
    return {"case_id": identifier, "goal": "Ordinary report and issues workbook",
            "sources": [{"content": text}]}


def test_holdout_leakage_rejected_even_with_different_ids():
    splits = {"train": [example("a", "first")], "validation": [example("b", "second")],
              "holdout": [example("c", "first")]}
    with pytest.raises(ValueError, match="LEAKAGE"):
        validate_splits(splits)
    splits["holdout"] = [example("c", "third")]
    validate_splits(splits)


def test_strategy_only_and_fixed_constraints_visible():
    with pytest.raises(ValueError):
        validate_candidate({COMPONENT: "test", "conditions": "weakened"})
    strategy = "First line\nSecond line"
    assert candidate_visible([{"content": json.dumps({"strategy": strategy})}], {COMPONENT: strategy})
    assert not candidate_visible([{"content": "mentioning an ID is insufficient"}], {COMPONENT: strategy})


def test_unknown_and_unsubstantiated_judgments_cannot_get_perfect_score():
    judgment = {"checks": {k: {"status": "pass", "evidence": "B3 actual cell", "reason": "supported by source"} for k in CHECKS}}
    assert score_judgment(judgment) == 1
    judgment["checks"][CHECKS[0]]["status"] = "unknown"
    assert score_judgment(judgment) == pytest.approx(5 / 6)
    judgment["checks"][CHECKS[1]]["evidence"] = ""
    with pytest.raises(ValueError, match="UNGROUNDED"):
        score_judgment(judgment)


def test_actual_candidate_delivery_uses_copied_library_and_preserves_canonical(tmp_path):
    import hashlib
    origin = LearningScope("customer", str(tmp_path / "origin"))
    library = LearningLibrary(tmp_path / "canonical")
    feedback = library.feedback(origin, {"id": "snapshot"}, {"id": "target"}, "Customer correction", {}, [{"id": "source"}])
    seed = library.propose(origin, [feedback["id"]], "customer_preference", "Purpose", "Old strategy", "Fixed customer requirement", "Pending")
    library.release(origin, seed["id"], 1, "Existing release")
    before = digest(library.list_versions(origin))
    source = tmp_path / "original.txt"
    source.write_text("Real immutable source")
    case = {**example("one", "Real immutable source"), "sources": [{"id": "source", "title": "Source", "content": "Real immutable source",
        "coverage": "partial", "byte_path": str(source), "copied_path": "sources/source.txt",
        "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}]}
    case["visual_page_exclusions"] = {"source": [2, 3]}
    ws = prepare_rollout(tmp_path / "rollout", case, {COMPONENT: "GEPA-authored revision"}, seed, tmp_path / "canonical")
    assert ws.store.manifest['review_execution_mode']=='native-reviewer-v2'
    assert ws.store.get("visual_page_exclusions") is None
    preference = guidance_context(ws)["customer_preferences"][0]
    assert preference["strategy"] == "GEPA-authored revision"
    assert preference["conditions"] == seed["conditions"] and preference["version"] == 2
    assert digest(library.list_versions(origin)) == before
    with pytest.raises(FileExistsError):
        prepare_rollout(tmp_path / "rollout", case, {COMPONENT: "GEPA-authored revision"}, seed, tmp_path / "canonical")


def test_source_byte_change_blocks_before_model_call(tmp_path):
    source = tmp_path / "source"
    source.write_text("changed")
    case = {"case_id": "bad", "sources": [{"byte_path": str(source), "sha256": "old"}]}
    with pytest.raises(ValueError, match="SOURCE_BYTES_CHANGED"):
        prepare_rollout(tmp_path / "bad", case, {COMPONENT: "test"}, {}, tmp_path / "missing")


def test_exact_saved_outcome_reused_without_subprocess_and_unknown_not_retried(tmp_path):
    from report_agent.gepa_report_learning import ReportExperiment
    from report_agent.report_learning import EVALUATOR_VERSION, save_json
    config = {"splits": {"train": [example("a", "one")], "validation": [example("b", "two")],
        "holdout": [example("c", "three")]}, "seed": {"strategy": "test"}}
    experiment = ReportExperiment(config, tmp_path, runtime_python="forbidden", driver="forbidden")
    candidate = {COMPONENT: "test"}
    case = config["splits"]["train"][0]
    key = digest({"candidate": candidate, "case": case, "evaluator": EVALUATOR_VERSION, "seed": config["seed"]})
    output = tmp_path / "rollouts" / key
    save_json(output / "response.json", {"score": 0, "feedback": "unknown old response", "runtime_result": {"terminal": True}})
    assert experiment.rollout(candidate, case)["feedback"] == "unknown old response"
    (output / "response.json").unlink()
    with pytest.raises(RuntimeError, match="UNKNOWN_ROLLOUT"):
        experiment.rollout(candidate, case)
