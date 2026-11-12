# Context C1 — authorized full regression and corrections

Production **+0 / −0**; test correction **+9 / −5**; census correction **+0 / −2 rows**. Runtime checks/guards changed **0**; new legacy fallbacks **0**. No C2 implementation or main move.

**Main ran the owner's one authorized full offline regression on frozen C1 346f1ba:** **6,206 passed / 3 failed / 9 skipped**, **36m30s**. All **6,218** collected nodes ran exactly once; no collection errors, missing, duplicate or unexpected nodes. This is a **failed full run**, not a reconciled pass. [Complete result](../verification/context-fix-c2/full-regression-346f1ba.json).

Statistical timestamp: **2026-11-12 02:53 UTC**; test window **02:15:54–02:52:24 UTC**.

| Failure | Confirmed cause and correction |
| --- | --- |
| SDK batch wire test, both GLM and strict DeepSeek configurations | Required a saved host-state frame retired by accepted C1. **a412688** now requires no frame, one current tail after both intact tool results, and latest feedback; reasoning, IDs, order, content and schema checks stay |
| State-census guard | Two inventory rows still named deleted verified_frame/persist_frame access sites. **3eeb5e6** removes exactly those rows; scanner and guard unchanged |

These are **P2 stale test/inventory defects**: they block claiming a clean full suite, not C2 development. Main ran **2 SDK cases passing in 8.37 s** and **4 census cases passing in 3.30 s** after correction. Neo independently inspected both diffs and the saved red evidence and found no production defect. [Separate focused record](../verification/context-fix-c2/full-corrections.json). Neither correction has had a clean full run.

- Coverage **90.72%**; all nine existing module floors pass. Nine skips match the accepted baseline.
- All **1,300** frozen files stayed unchanged. **57** supplemental fixtures, including **51 private**, matched verified prior hashes.
- Offline runner/network guards enabled; **0 paid model calls**. No ledger, hold, historical case, source original, dispatcher routing or S2 change.
- Automatic pytest retention is enabled. Failed evidence stays: source snapshot and **11 temporary databases**, about **3.4 MiB** of temporary files; no passing-data cleanup is falsely claimed. Passing disposable baseline/catalog copies were removed separately.
- Exact run processes and supervisor are absent; driver exited **1**, cleanup **0**. Private evidence: .private/context-fix-c1-full-20261111/full/.

**Next:** [independently reviewed C2 inventory](context-fix-c2-inventory-20261111.md), then the next planned Step 4 TDD work. Catalog filtering remains a separate scope proposal. No second full run was started; the final C2 candidate still needs the plan's separately authorized clean full run. Main remains **7da4f94**; no paid probe.
