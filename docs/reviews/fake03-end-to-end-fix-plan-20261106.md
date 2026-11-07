# Fake03 end-to-end verification fix plan

**Decision requested:** review the proposed fixes and tests. **Status:** plan, 6 November 2026. The code and run evidence below refer to commit `4113ce81debfc9d7b07ecdff4a4e359559b9dd1d`. The target is a synthetic commission that starts with source files and finishes with reviewed Word and Excel files for the same snapshot.

## 1. Bug report and reproduction

| ID | Observed behavior | Expected behavior | Impact and containment |
|---|---|---|---|
| **F1 · Writer cannot recover from a rejected gap save** | A–X12 identified missing evidence, attempted four gap saves and received four validation refusals. The graph reached its recursion limit. Only A–X11 survived. | Tell the Writer which fields to supply or omit. A corrected save should persist the gap once and advance to X21. | **P1 for completing the assessment.** The run interrupted safely and produced no unsupported overall score. Repair offline before another paid verification. |
| **F2 · The verification route exercises only the assessment Writer** | Preparation supplied a plan and scripted its approval. The launcher called the two-slope assessment runner. Even if all 22 saves had succeeded, this route would have stopped before prose, review and export. | The live Coordinator produces a plan from the fixture. Only human checkpoint answers are scripted. The report runtime carries that approved plan through the Writers, review and paired delivery. | **P1 for end-to-end verification.** The existing route remains useful as a narrow Writer test. Its completion cannot establish full-system delivery. |
| **F3 · The documented module entry point loses its run identity** | On run 01, invoking the launcher with `python -m` raised `VERIFIED_FAKE_RUN_REQUIRED` before transport. The package-import entry point worked on a fresh case. | The advertised command should share the same verified run identity as the runner and keep its one-launch guard. | **P2 for launching.** The canonical import invocation is a verified workaround. Preserve both receipts and test the advertised entry point before the full run. |

**Reproduce F1 offline.** From the native checkout at the baseline commit, use its owning Python environment. This minimal call uses the same outcome validator and feedback projection as the failing contract. It requires neither a provider nor a case database.

```bash
PYTHONPATH=src /home/dysun/.venvs/report-agent-system-native/bin/python -B - <<'PY'
from report_agent.errors import ActionRejected
from report_agent.message_fields import validate_message
from report_agent.writer_assessment import _step_schema

schema = _step_schema(("low", "moderate"))
try:
    validate_message(schema, {
        "kind": "gap", "missing": "Natural slope angle",
        "rationale": "Cannot calculate the angle difference."
    })
except ActionRejected as exc:
    print(exc.diagnostic)
corrected = validate_message(schema, {
    "kind": "gap", "missing": "Natural slope angle",
    "question": "What is the natural slope angle at A?"
})
print(corrected.kind)
PY
```

Observed output at the baseline: `{'fields': [{'field': [], 'reason': 'value_error', 'definition': None}]}`, then `gap`. This reproduces the missing diagnostic. To reproduce the interrupted loop deterministically, feed a scripted model the four rejected X12 argument shapes recorded below through the real tool middleware, with A–X11 already saved. Use a temporary synthetic case and simulated transport throughout.

**Reproduce F2 offline.** Run `tests/support/run_offline_tests.py -q tests/test_fake_verification_launcher.py tests/test_mini_assessment_runner.py` with the native Python. Follow the positive test from preparation to the terminal receipt. Its explicit scope is `assessment_writer_only`. The existing success test permits **all 22 indicator outcomes to be gaps** and requires no exported files. It cannot fail merely because Coordinator planning or delivery was bypassed.

**Reproduce F3 offline.** The preserved [CLI reproduction script](<//wsl.localhost/Ubuntu-24.04/home/dysun/report-agent-m1/fake-verification-20261106/operator/cli-reproduction-offline.py>) and [result](<//wsl.localhost/Ubuntu-24.04/home/dysun/report-agent-m1/fake-verification-20261106/operator/cli-reproduction-offline.json>) compare both entry points with fresh disposable cases and simulated SDK responses. The module invocation made zero simulated requests. Importing `main` from `report_agent.fake_verification` exercised 22 steps. Do not replay the original live cases.

## 2. Root cause and evidence

**F1 — a conditional rule is validated but its repair instruction is lost.** In [writer_assessment.py](../../src/report_agent/writer_assessment.py), `_step_schema.matches_kind` requires nonempty `missing` and `question` for a gap and rejects a nonempty `rationale` or scoring fields. These rules depend on `kind`. The list of fields allowed for the tool as a whole cannot explain which are allowed for a gap. [message_fields.py](../../src/report_agent/message_fields.py) projects unmapped model-level validator failures to an empty field path and `value_error`. [tool_argument_feedback.py](../../src/report_agent/tool_argument_feedback.py) records the raw native error and formats the tool response. The Writer received a root field inventory and that generic error. It needed an instruction such as “For a gap, omit rationale. Supply the missing natural slope angle in missing and ask for it in question.”

| Run 02 event sequence | What the record establishes |
|---|---|
| 36, 48 | Two X11 evidence-save refusals. The Writer later saved A–X11 as direct evidence, low, rank 1, value 22.5. |
| 105, 117, 129, 141 | Four X12 gap-save refusals. Every attempt had a nonempty `rationale`. The last two also omitted `question`. |
| 110, 122, 134, 146 | The next model inputs contain the public feedback: `NATIVE_TOOL_VALIDATION_ERROR`, field path `[]`, reason `value_error`. The raw native error ended with “Please fix the error and try again.” |
| Terminal receipt | `GraphRecursionError`. The per-indicator graph uses a recursion limit of 30 graph steps in [writer_indicator_steps.py](../../src/report_agent/writer_indicator_steps.py). X12 took eight model turns. Graph steps and model turns are distinct counts. |

**Engineering expectation for X12.** Use the design ratio 1:0.75 and record the survey disagreement (1:1.0). The method grades the difference between the cut-slope angle and the natural slope angle. The source omits the latter. A saved gap with that question is the expected result. A–X11’s saved low grade has source support. Its exact value of 22.5 remains subject to review because three stages do not establish three equal stage heights.

**F2 — the test starts downstream of the behavior in question.** [mini_commission.py](../../src/report_agent/mini_commission.py) explicitly constructs and confirms a scripted plan. [fake_verification.py](../../src/report_agent/fake_verification.py) invokes `run_mini_assessment`, which allows exactly A and B and records Writer outcomes. The normal Coordinator-led entry is `run_report` in [deep_runtime.py](../../src/report_agent/deep_runtime.py). The [historical handoff comparison](writer-handoff-comparison.md) preserved an explicit owner rank order in both Coordinator versions under controlled inputs. It identified a missing structured rank field in the older compact Writer interface. It did not establish that the Coordinator refactor caused the observed X12 failure.

**F3 — duplicate module identity.** The `-m` route created the verified-run context in `__main__`. The runner imported the guard from the package module, which has a different context variable and class identity. The guard correctly refused the unmatched identity. This defect and F1 occurred on different attempts.

**Audit records (local operator machine).** [Full regression](<//wsl.localhost/Ubuntu-24.04/home/dysun/report-agent-m1/verification/phase1-release-20261106T222211Z/gate.json>) accounted for 5,725 tests: 5,716 passed, 9 skipped, zero failures. [Run 02 receipt](<//wsl.localhost/Ubuntu-24.04/home/dysun/report-agent-m1/fake-verification-20261106/grant/runs/mini-assessment-20261106-02/result.json>) and [verified saved rows](<//wsl.localhost/Ubuntu-24.04/home/dysun/report-agent-m1/fake-verification-20261106/operator/mini-assessment-20261106-02-writer-rows.json>) show 12 completed requests, 62,027 tokens settled, zero held, one saved row, zero saved gaps and 21 unsaved indicators. The event numbers above are in the same run’s `case/state.db` (`events.sequence`). Use owning Linux Python, short read-only connections and `PRAGMA query_only=ON` for inspection.

## 3. Fix plan, TDD cases and file impact

Implement each row by first observing the failing assertion on the baseline, then making the smallest change at the production boundary and rerunning the relevant existing tests. Keep the assessment-only test as a fast control. The full-run acceptance test must enter through the advertised operator command.

| Order | Failing test to add first | Proposed change and files |
|---|---|---|
| **1. Make save errors actionable** | Replay the rejected evidence and gap payloads. For X12 assert that the **next request seen by the model** identifies forbidden `rationale` and, when absent, required `question`. A corrected save must retain X11, persist X12 exactly once, and offer X21. A scored gap, unsupported evidence and an assumption without a basis must still be refused. | Give the conditional validator stable error codes and field-specific explanations in `src/report_agent/writer_assessment.py`. Reuse the existing `diagnostic_errors` mechanism in `message_fields.py`; change the shared feedback adapter only if the wire-level test shows those codes are lost. Update `src/report_agent/rules/writer-indicator-step.md` with one valid gap example. Extend `tests/test_writer_indicator_outcomes.py` and `tests/test_writer_indicator_steps.py`. Preserve the execution limit. |
| **2. Correct launcher identity and scope** | Run the documented CLI in a subprocess against a mock SDK. Verify one run identity, one claim, same-case binding, and refusal of a duplicate launch or foreign case. Add a distinct end-to-end workflow whose fresh case has nine fixture inputs and the pinned system method, but no plan, approval or assessment. | Fix the module entry point in `src/report_agent/fake_verification.py`. Separate import-only preparation from the scripted Writer fixture in `src/report_agent/mini_commission.py`. Extend `tests/test_fake_verification_launcher.py` and `tests/test_mini_commission_prep.py`. Pin the workflow type, fixture hashes and candidate at launch. |
| **3. Exercise the live plan handoff** | Through the normal report runtime, require a Coordinator-authored plan and a scripted response only to an actual owner checkpoint. Verify A/B scope, C exclusion at the checkpoint, ranks, revision, source precedence and candidate pages as received by the Writer. A missing handoff field must fail visibly. Keep owner replies and verifier answers outside agent inputs. | Connect the full fake workflow to `src/report_agent/deep_runtime.py` and the existing assessment session in `src/report_agent/writer_runtime.py`. Preserve the current role responsibilities. Extend `tests/test_writer_handoff_comparison.py`; add `tests/test_fake_commission_e2e.py` for the whole route. |
| **4. Prove delivery with gaps** | Close A and B with 11 recorded outcomes apiece. Require a real gap to suppress the corresponding overall score. Separately interrupt a model request and verify that an absent row stays absent. Exercise prose, reviewer verdicts, revision/re-check, and paired export. On an isolated negative-control copy, change B’s height from 25 m to 52 m and require the Reviewer to identify its location and source. | Reuse `src/report_agent/system_assembler.py`, `content_delivery.py` and the existing export checks. Extend `tests/test_g6_offline_assembly.py` and the new end-to-end test. If a consumer currently insists on a scored assessment, add explicit support for **closed incomplete assessments** there. Keep required-issue, fixed-text, citation and internal-content checks intact. |
| **5. Enforce the full-run budget** | Simulate each enabled model role, including any helper or vision call. Prove per-model reservation admission, 3.7M per run, 10M cumulative, charging settled plus held usage, and preservation of an unknown hold. Reject an unbound role before dispatch. | Reuse `src/report_agent/fake_verification_budget.py` and the transport hooks. Extend `tests/test_fake_verification_budget.py` and launcher tests for the mixed-role case. The 1,179,648 bound was verified for the text-only Writer. Verify each other service bound separately. |

**Release gate.** Run the complete offline regression on the frozen candidate, reconcile the collection and results, and record the Git commit and fixture digest. The full-run simulation must reach both export artifacts. Then allow one paid full-workflow test under the agreed caps. At the recorded baseline the fake-data campaign has **9,937,973 tokens available**. Recheck the ledger immediately before dispatch.

**Acceptance record.** Capture the live plan and checkpoint, all 22 indicator outcomes or the precise interruption point, source quotes and ranks, Reviewer findings and revisions, and Word and Excel tied to the same approved snapshot. Verify fixed template text, corrected date, missing-groundwater wording, and one-to-one material-issue comments and spreadsheet rows. Inspect rendered pages and the table of contents. Report per-role requests, decision turns, tool rejections, model-call time, settled tokens and holds. If the cap stops the run, publish the last completed stage and partial results; end-to-end acceptance requires reviewed delivery of both files.
