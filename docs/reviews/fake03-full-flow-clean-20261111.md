# Fake03 full-flow replacement — clean offline regression

Production source +0 / −0; tests +0 / −0; runtime checks/guards +0 / −0; legacy fallback changes 0. This commit records results only. The dispatcher, S2, main, historical cases and ledgers are unchanged.

## Result on the authorized revision

Main ran the owner's single authorized replacement full offline regression on exact frozen **`f35ea764588735d666f36f32f66b488fcde49e59`**: **6,196 passed, 9 skipped, 0 failures**, in **33m26s** (2,006.1 seconds). All **6,205** collected nodes ran exactly once, with no collection errors, missing, duplicate or unexpected nodes. All eight test processes exited zero.

Statistical timestamp: **2026-11-11 20:47:43 UTC**. Test window: 20:13:07–20:46:33 UTC. [Machine-readable result, unchanged skips and coverage floors](../verification/fake03-post-9a/full-regression-f35ea76.json).

- Coverage **90.68%**; all nine existing M0 module floors pass.
- The nine skips are identical to accepted b2; no new skip or retired test.
- All **1,283** frozen files were unchanged. All **57** supplemental fixture hashes matched the prior verified bytes, including **51** private files. Each copy owns its bytes.
- Offline wrapper/network guards were enabled; **0 paid model calls**. G5 remained stopped; no grants, holds or ledger records changed.
- Automatic cleanup removed the passing source copy and all nine temporary directories; **0 temporary test databases remain**. Logs, coverage, collection/results, fixture manifest and authority remain private.
- Driver and cleanup exited zero; exact run processes are absent. Main remains accepted b2 **`14484f8`**.

## Earlier failure stays failed

The original `cd48c0a` run remains **6,184 passed / 9 skipped / 11 failed**; its frozen failed copy and evidence are preserved. The two stale test inventories were corrected before this separate replacement, with one additional regression case. Neither result is reconciled or relabelled. [Diagnosis and test-only correction](fake03-full-flow-regression-20261111.md).

## Review boundary and next gate

This proves the repository's offline suite, including the scripted live-role flow, passes on `f35ea76`. It does **not** measure live-model extraction, binding or judgment quality. Independent review is pending. The shared multi-role budget/launch binding and the owner's paid scope/cap remain pending; this record authorizes no paid run or main move.

Private evidence: `.private/fake03-full-flow-replacement-20261111/full/`. Source and tests at this result-only commit are byte-identical to the tested revision.
