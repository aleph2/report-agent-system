"""Supported GEPA LangChainAdapter connected to actual report execution traces.

GEPA runs in the optional learning environment. Runtime/model subprocesses use
the established report environment, keeping its installed dependencies unchanged.
No automatic retries, terminal-job replay or canonical policy publication.
"""
from __future__ import annotations

import json
import subprocess
import sqlite3
from pathlib import Path

from .store import digest
from .report_learning import (COMPONENT, EVALUATOR_VERSION, read_json, save_json,
                              validate_candidate, validate_splits)


class ReportExperiment:
    def __init__(self, config, output, *, runtime_python, driver):
        validate_splits(config["splits"])
        self.config, self.root = config, Path(output)
        self.python, self.driver = str(runtime_python), str(driver)
        self.count = 0

    def invoke(self, mode, request, output):
        output = Path(output)
        output.mkdir(parents=True, exist_ok=True)
        request_path = output / "request.json"
        if request_path.exists():
            raise RuntimeError("TERMINAL_OPERATION_MUST_NOT_RETRY")
        save_json(request_path, request)
        with (output / "stdout.log").open("w") as stdout, (output / "stderr.log").open("w") as stderr:
            # A bounded child writes terminal evidence itself; do not kill and retry
            # an unknown provider outcome at the host subprocess boundary.
            result = subprocess.run([self.python, self.driver, mode, "--request", str(request_path),
                                     "--output", str(output)], stdout=stdout, stderr=stderr)
        if result.returncode:
            raise RuntimeError("REPORT_LEARNING_SUBPROCESS_FAILED")
        return read_json(output / "response.json")

    def rollout(self, candidate, example):
        validate_candidate(candidate)
        key = digest({"candidate": candidate, "case": example,
                      "evaluator": EVALUATOR_VERSION, "seed": self.config["seed"]})
        output = self.root / "rollouts" / key
        if (output / "response.json").exists():
            # Exact outcome reuse includes failures/unknowns. Never relaunch them.
            state = read_json(output / "response.json")
            save_json(self.root / "cache" / (key + ".json"), {"state": "exact_saved_outcome_reused", "path": str(output)})
            return state
        if output.exists():
            raise RuntimeError("UNKNOWN_ROLLOUT_OUTCOME_RECONCILE_REQUIRED")
        if self.count >= self.config.get("maximum_unique_rollouts", 8):
            raise RuntimeError("REPORT_EXPERIMENT_ROLLOUT_CAP_REACHED")
        self.count += 1
        save_json(self.root / "progress.json", {"state": "rollout_running", "unique_rollouts": self.count,
            "case_id": example["case_id"], "candidate_digest": digest(candidate), "path": str(output)})
        return self.invoke("rollout", {**self.config["runtime"], "case": example,
            "candidate": candidate, "seed": self.config["seed"], "library_root": self.config["library_root"]}, output)

    @staticmethod
    def evaluate(example, state):
        if state.get("error"):
            raise RuntimeError("REPORT_EVALUATOR_FAILURE_MUST_NOT_SCORE_AS_QUALITY")
        return state["score"], state["feedback"]

    @staticmethod
    def reflective_record(example, state, score, feedback):
        return {"Inputs": {"case_id": example["case_id"], "goal": example["goal"],
                           "source_selections": example["sources"]},
                "Execution Trace": state.get("execution_trace"),
                "Generated Outputs": state.get("artifact_observation"),
                "Feedback": feedback, "Score": score,
                "Evidence Limits": "Scores are source-grounded model judgments with deterministic artifact checks; no engineering sign-off or visual acceptance."}

    def reflect(self, prompt):
        index = len(list((self.root / "reflections").glob("*/request.json"))) if (self.root / "reflections").exists() else 0
        if index >= self.config.get("maximum_reflections", 4):
            raise RuntimeError("REPORT_EXPERIMENT_REFLECTION_CAP_REACHED")
        return self.invoke("reflect", {**self.config["runtime"], "prompt": prompt,
            "fixed_conditions": self.config["seed"]["conditions"],
            "existing_feedback": self.config.get("existing_feedback", [])},
            self.root / "reflections" / str(index))["text"]

    def run(self, max_metric_calls):
        from gepa import optimize
        from gepa.adapters.langchain_adapter import LangChainAdapter
        from gepa.utils.stop_condition import MaxCandidateProposalsStopper, ScoreThresholdStopper
        validate_candidate({COMPONENT: self.config["seed"]["strategy"]})
        if not 4 <= max_metric_calls <= 100:
            raise ValueError("BOUNDED_REPORT_METRIC_CALLS_REQUIRED")
        if (self.root / "experiment.json").exists():
            raise RuntimeError("GEPA_EXPERIMENT_MUST_NOT_REPLAY")
        record = {"state": "running", "framework": "gepa.LangChainAdapter", "evaluator": EVALUATOR_VERSION,
            "max_metric_calls": max_metric_calls, "holdout_excluded_from_optimization": True,
            "automatic_release": False, "configuration_digest": digest(self.config),
            "baseline": {COMPONENT: self.config["seed"]["strategy"]}}
        exercise = bool(self.config.get('exercise_reflection', False))
        proposals = self.config.get('max_proposals', 1)
        if type(proposals) is not int or not 1 <= proposals <= 10:
            raise ValueError('BOUNDED_CANDIDATE_PROPOSALS_REQUIRED')
        stoppers = [MaxCandidateProposalsStopper(proposals)]
        if not exercise:
            stoppers.append(ScoreThresholdStopper(1.0))
        record.update(max_proposals=proposals, exercise_reflection=exercise,
            stopping='Supported GEPA proposal bound; stop at metric ceiling unless explicit capability exercise.')
        save_json(self.root / "config.json", self.config)
        save_json(self.root / "experiment.json", record)
        adapter = LangChainAdapter(rollout_fn=self.rollout, eval_fn=self.evaluate,
            reflective_record_fn=self.reflective_record, num_threads=1, show_progress=False)
        try:
            result = optimize(seed_candidate=record["baseline"], trainset=self.config["splits"]["train"],
                valset=self.config["splits"]["validation"], adapter=adapter, reflection_lm=self.reflect,
                max_metric_calls=max_metric_calls, reflection_minibatch_size=1, skip_perfect_score=not exercise,
                stop_callbacks=stoppers,
                run_dir=str(self.root / "gepa"), seed=0, raise_on_exception=True, track_best_outputs=False)
            selected = validate_candidate(result.best_candidate)
            save_json(self.root / "gepa-result.json", result.to_dict())
            save_json(self.root / "selected-guidance.json", {"schema_version": 1, "components": selected,
                "component_digest": digest(selected), "conditions": self.config["seed"]["conditions"],
                "seed_ref": {k: self.config["seed"][k] for k in ("id", "version", "customer", "kind")},
                "selected_by": "GEPA validation score; heldout assessment follows", "published": False})
            from .learning import LearningLibrary, LearningScope
            target = self.root / "selected-library"
            target.mkdir()
            with sqlite3.connect(Path(self.config["library_root"]) / "state.db") as src, sqlite3.connect(target / "state.db") as dst:
                src.backup(dst)
            library = LearningLibrary(target)
            seed = self.config["seed"]
            selected_entry = seed
            if selected[COMPONENT] != seed["strategy"]:
                with library.store.connect() as db:
                    row = db.execute("SELECT project FROM learning_feedback WHERE id=?", (seed["feedback_ids"][0],)).fetchone()
                scope = LearningScope(seed["customer"], row[0])
                head = max(r["version"] for r in library.list_versions(scope) if r["id"] == seed["id"])
                selected_entry = library.propose(scope, seed["feedback_ids"], seed["kind"], seed["title"],
                    selected[COMPONENT], seed["conditions"], "GEPA selection; holdout pending; no automatic release.",
                    experience_id=seed["id"], expected_version=head)
            save_json(self.root / "selected-experience.json", {**selected_entry, "active": False,
                "selection_record": "gepa-result.json", "library_path": str(target)})
            holdout = []
            for example in self.config["splits"]["holdout"]:
                pair = {name: self.rollout(candidate, example)
                        for name, candidate in (("baseline", record["baseline"]), ("candidate", selected))}
                holdout.append({"case_id": example["case_id"], **pair})
            record.update(state="completed", candidate=selected, holdout=holdout,
                num_candidates=result.num_candidates, selected_idx=result.best_idx,
                validation_scores=result.val_aggregate_scores, metric_calls=result.total_metric_calls,
                unique_rollouts=self.count, regressions=[r["case_id"] for r in holdout
                    if r["candidate"]["score"] < r["baseline"]["score"]],
                limits="One project, one case per split; no statistical/general engineering or visual acceptance. No automatic canonical release.")
            save_json(self.root / "experiment.json", record)
            return record
        except BaseException as exc:
            record.update(state="failed", error_type=type(exc).__name__, unique_rollouts=self.count,
                automatic_retry=False, original_outcomes_preserved=True)
            save_json(self.root / "experiment.json", record)
            raise
