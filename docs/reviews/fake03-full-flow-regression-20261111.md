# Fake03 full-flow regression — failed run and test-only correction

Production source +0 / −0; runtime checks/guards +0 / −0; fallback changes 0. Tests +16 / −1, one case added, none retired or skipped. Two exact test inventories updated. The dispatcher, S2, report behavior, main, ledgers and historical cases are unchanged.

## Authorized full result

Main ran the owner's one authorized full offline regression on frozen `cd48c0a90e9aefbb34907330d6167f3eac8d753d`: **6,184 passed, 9 skipped, 11 failed**, in **41m12s**. This result remains **failed**, not reconciled to green after focused fixes. [Results, coverage and node lists](../verification/fake03-post-9a/full-regression-cd48c0a.json).

All 6,204 collected nodes ran exactly once. There were no collection failures, missing nodes, duplicates or unexpected nodes. The nine skips match accepted b2. Coverage is **90.68%**; all nine M0 floors pass. All **1,281** frozen files were unchanged, including **57** verified supplemental fixtures (**51** private). Offline guards were enabled; **0 paid model calls**. The full scripted Fake03 flow cases passed within this run; they do not establish real-model judgment quality.

## Diagnosis and correction

| Finding | Confirmed evidence and fix | Exact action blocked |
| --- | --- | --- |
| **F1 / P2**, ten parity failures | Every case stopped at the same offered-tool assertion: its list lacked `publish_planning_draft`. Keep the exact inventory assertion and explicitly include the new tool. A separate case checks its schema, host-owned identities, incomplete-plan gap diagnostic and absence of publication on refusal. | Clean full regression gate |
| **F2 / P2**, one structural failure | The new `commission_plan` dictionary key is the canonical operation request already used by `commission_plan.save_plan`, not legacy state access. Add only `(commission_planning, submit_plan, Dict)` to reviewed public uses, with a public-request example. Existing SQL and aliased-storage bypass checks remain. | Clean full regression gate |

Both failures were independently reproduced before editing. The corrected modules pass **58 focused tests** in **36.6 seconds**. Production source and validation rules did not change. The frozen test copy was never edited; the full run was not restarted. These test inventories were missed during candidate preparation; the full run caught them.

## Retention and next gate

Pytest removed passing test cases automatically. The failed run retains its frozen source copy, logs, coverage and **30 failed-fixture database files**; originals and live run data were not touched. Exact run processes are absent. Private evidence: `.private/fake03-full-flow-regression-20261111/`.

The fix is for review on the existing `codex/stage1-9a` branch. Main stays accepted b2 `14484f8`. A replacement clean full run needs a fresh explicit owner authorization under AGENTS.md §1; none has been launched. The separate multi-role budget/launch binding and paid scope/cap remain pending. No paid launch or main move is inferred.
