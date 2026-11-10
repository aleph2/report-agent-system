# 9a-b — clean replacement full verification

Reader-fix production Python **+43 / −23 / net +20 lines** from `335f9f5`; Writer prompt **+2 / −0**. Rejection raise expressions **237 → 237**; new check/guard families **0**, new legacy fallbacks **0**. This follow-up changes documentation only. [Reader fixes and measurements](stage1-9a-b-reader-fixes.md).

**Main ran the owner-authorized replacement full offline regression on exact commit `2b55f6c91d9eadd4f51a6b999271a05b2a816902`. Result: 6,175 passed, 9 unchanged skips, zero failures.** It ran from 19:20:16 to 19:52:28 UTC on 10 November 2026 (32m12s). No paid model calls. The earlier approval naming `3f3493c` was superseded; only one replacement full run was launched.

All **6,184 collected tests** ran exactly once: no missing, duplicate or unexpected cases, no collection errors and all eight shard exit codes zero. All 61 cases that failed in the earlier full run pass here. The skip set matches the prior run exactly. Combined source coverage is **90.61%**; all nine required M0 module floors pass. [Gate, coverage and cleanup](../verification/stage1-9a-b-reader-fixes/clean-full.json).

The frozen copy included all 51 private fixture files verified against the prior clean-run manifest. All **1,250 frozen files** retained their original hashes. After success, automatic cleanup removed the disposable source copy; **zero test databases** remain in this run’s temporary folders. The runner and cleanup processes are absent. Logs, coverage, phase records and the previous failed run are preserved privately at `.private/stage1-9a-b-reader-fixes-20261110/`.

The earlier rendered-page review remains valid: final-source output is pixel-identical across all six inspected Word pages. There are 22 indicator rows (three trial values, 19 unscored), no adopted risk level, all three planning conflicts and **23 Word comments paired with 23 Excel issue rows** from one snapshot. Chinese explanatory text, reader citations, printed pending-item disclosure, numbered headings/TOC and project/date cover are verified. The delivery artifacts remain in `delivery-25cd16c/`; source/tests at `25cd16c` and `2b55f6c` are byte-identical.

No application or test changes followed this full run. Dispatcher, S2, original records, ledgers and holds remain unchanged. **Main stays at accepted part a `5e6c2ee`; part b is ready for owner review, not accepted by this record.** No formal release or engineering sign-off is claimed. Excel layout is outside scope; real-model Chinese-language adherence remains unmeasured.
