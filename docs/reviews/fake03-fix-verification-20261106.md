# Fake03 fix verification — Gate 1 candidate

Scope: F1, F3, F4 and F5 in `fake03-end-to-end-fix-plan-20261106.md`. The Coordinator handoff and complete delivery gates remain open. Original G5 and rescue records are unchanged.

## Implemented behavior

- Three outcome tools expose their own accepted fields. Gaps allow rationale and require the missing fact and review question; scored fields are refused. Public feedback retains field paths, reasons and corrections in the next actual SDK request.
- A structured conflict is stored atomically with its indicator outcome through the existing material-issue path. Exact duplicate reports share an issue ID even with reversed source ordering; previously saved IDs are reused. Invalid quotes roll back the indicator save as well as the issue.
- Two distinct rejected saves produce a durable `interrupted: save rejected` record, with public reasons. Independent indicators and slopes continue. Interrupted indicators remain absent from scored/gap rows; no incomplete slope is scored.
- A material issue can be reported after the third page read. Failed reads consume an attempt, but do not count as rejected saves.
- The documented module CLI calls the canonical package entry, sharing its verified binding and ContextVar with the Writer.

## Observed verification

| Check | Result | Evidence |
|---|---|---|
| Conflict and existing issue tests | 28 passed (latest combined check) | `tests/test_writer_indicator_conflicts.py`, `tests/test_writer_issue_tools.py`; operator `f4-focused-verification.json` |
| Actual SDK refusal replay | 9 passed, 23.92 s | `tests/test_writer_save_feedback.py`; replays preserved Run 02 mistakes, then a corrected save |
| Approved guideline binding | 1 passed, 3.83 s | `tests/test_writer_indicator_outcomes.py`; project-only and method-only refused, combined evidence accepted |
| Loop and related regressions | 99 passed, 74.49 s | Native verification `gate1-f5-20261107T013722Z/result.json` with command and hashes |
| CLI and guarded launch mock | 6 passed, 40.05 s | `tests/test_fake_verification_launcher.py`; actual subprocess identify/prepare/check/run/duplicate refusal with mock SDK and unknown-hold preservation |

The F4 reproduction originally failed because structured contrary evidence was rejected by the old string schema. The F5 reproduction originally failed because the issue tool disappeared at the third read. The subprocess F3 reproduction failed on duplicate package identity before the entry fix. These are focused causal checks, not a full regression or live semantic acceptance.

The full regression will pin source, tests, fixtures, `pyproject.toml` and `uv.lock` when present. Its separate gate record must match the frozen candidate before paid dispatch. No new paid calls were made during these fixes.

## Boundaries and remaining work

The conflict export regression exercises real Word comments and Excel rows on a complete synthetic assessment. It does not prove gap-only report delivery. Exact duplicate issue identity and source-order invariance are tested, not semantic equivalence of differently worded reports. Gate 1 additionally requires 22 substantively checked outcomes against the extended fixture; an all-gap output or row-count success alone fails. Engineering judgments and precise within-grade values remain subject to human review.

Independent alignment review identified and checked corrections for malformed-JSON save refusals, complete CLI subprocess coverage, and source-order-stable issue identity. Its read-only findings are preserved in operator `fix-alignment-review.md`; Main retains test execution responsibility. Full regression remains the next gate. Live Coordinator handoff, closed-incomplete assembly, reviewer negative control and rendered delivery verification remain subsequent plan gates.

## Skills and roles

Main used the debugging/TDD workflow and Ponytail to reuse the existing transactional save, native diagnostic and issue/export paths; evidence is the red/green reproduction and tests above. The storage, loop and launcher workers owned separate files; Main alone operates the Git index. Graphify was checked for dependency exploration: no graph or CLI exists in the native checkout, so current source and callers were inspected without rebuilding. Local model-wire tests were used; no live tracing upload is claimed. The independent alignment reviewer examines the actual diff and current approved bounded workflow before acceptance.

The review follow-up reproduced two malformed native save arguments bypassing the counter. The final middleware consumes existing parser feedback before tool execution, blocks every unexecuted pending save after the second observed refusal and preserves committed earlier rows. No provider-list-order adapter or transport metadata was added.

Final parser-path verification: **50 passed in 51.43 s**, evidence `/home/dysun/report-agent-m1/verification/gate1-f5-parser-20261107T015004Z/result.json`. This includes malformed-only and mixed responses through the SDK, later-step/slope progress, committed-row preservation, no third save execution and deduplicated metrics.
