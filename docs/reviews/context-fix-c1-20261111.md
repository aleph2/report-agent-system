# Context fix C1 — Step 2 review candidate

Production Python **+42 / −198, net −156**. Explicit raise sites **+1 / −9** (other check-site totals not remeasured). Legacy fallback paths **0**.

**Implemented:** current effective state is one call-local tail, never a saved frame. Removed frame classifier, receipt writer and full/delta reconstruction. History format version **2** refuses pre-C1 live history before startup side effects; originals stay unchanged. Current-format owner waits still work. Standalone Reviewer/prose paths reuse the existing prompt boundary; ToolTrace adds only the existing prompt call ID.

**Protected:** dispatcher routing/scheduling is unchanged. Its only control-code deletion is the unreachable rubric-upgrade branch, verified by AST comparison. S2, calculation/export, request/token budgets, recovery code and historical data are unchanged. A new regression caught resource caching after a supporting request; final-boundary resource refresh was restored to baseline behavior.

| Focused check | Result |
| --- | --- |
| Clean affected batch | **200 passed, 0 failed**, 14 modules, 202.81 s; all 902 checked files unchanged during execution |
| V1, complete scripted flow | 151 calls; **4,361,682 local proxy input tokens**, not provider usage |
| Coordinator | 61 calls; total 3,357,596; maximum 66,851; first 32,666 |
| Indicator Writer / prose Writer | 26 / 13 calls; maxima 5,791 / 37,228 |
| Qualitative Reviewer / text service | 48 / 3 calls; maxima 21,210 / 4,948 |
| Complete native review materials | 17,242 characters in a separate synthetic Reviewer fixture; real-report size unmeasured |
| V2 | All 61 native-flow state comparisons passed; Writer/Reviewer/Layout direct boundaries preserve exact projection, removals and original task |
| V6, scoped to this step | Scripted owner-checkpoint → Writer → Reviewer → Word/Excel passes; actual Coordinator waits without calls, then reopens after saved reply |
| Admission / identity | Old and unknown-version histories refuse with unchanged test DB bytes and zero dispatch; current owner waits, unknown outcomes and held-token checks pass |
| Trace join | Real prompt-boundary model/tool rows join their captures; in-memory removal of the ID makes the check fail |

The initial baseline checks failed as expected. Earlier failed focused attempts remain failed in private evidence: three obsolete budget/frame expectations were migrated, and the added measurement code needed to handle string source names. No product checks were weakened. [Each of the 20 retired frame-protocol test functions has a specific replacement](../verification/context-fix-c1/retired-tests.tsv); two renamed parameter cases are noted there too.

[Machine-readable per-call/component measurements and limits](../verification/context-fix-c1/focused.json). Raw RED/GREEN logs, clean JUnit/integrity and protected-code checks: private path `.private/context-fix-c1-20261111/`.

**Review:** the owner's advisor and delegated Neo reviewer cleared Step 1. Neo's final read-only implementation review found no blockers; Main ran the tests. This candidate still needs the owner's code review/acceptance. Main remains accepted 7da4f94; no main move.

**Next:** Step 3's separate C2 tool/session inventory and review. It must decide whether stock C2 replaces the existing preview/identity clearers. Measure complete review materials in V1. No C2 edit or summary-trigger change is included here.

**Not verified:** full repository regression, provider cache effectiveness or real-model judgment quality. Step 5's full run and Step 6's newly sized probe still need separate owner authorization. No report-model calls or live financial-record access occurred.
