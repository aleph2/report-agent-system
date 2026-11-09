# M7 opening: full regression of accepted main

The owner accepted M6 and requested that M7 begin with a full repository run on `48fabae8606d25bd4ca20df219fc9968f2b07df4`, because the last reply fix had only focused verification. This record closes that baseline gap. It does not claim an M7 implementation.

**Result: 6,150 passed, 9 unchanged conditional skips, zero failures.** All 6,159 collected cases are accounted for, with no missing, duplicate or unexpected cases and no collection errors. All eight test groups exited zero. The run covered the complete repository test suite at the accepted revision, including the two added M6 revision-interruption cases.

- Started: 2026-11-09 14:00:58 UTC.
- Finished: 2026-11-09 14:31:46 UTC.
- Elapsed: 1,848.2 seconds (30 minutes 48 seconds).
- Runtime: Ubuntu-24.04, user `dysun`, the native Python virtual environment with `-B`.
- Isolation: detached worktree at the exact accepted revision; all 51 imported historical fixture files verified before and after the run; the existing offline network guard; zero application model calls.
- Cleanup: existing pytest `failed` retention policy, count one, separate temporary roots per group, no `--basetemp`. Zero passing-case files remained outside caches in any group or the collection root. Source snapshot, fixture manifest, coverage and logs remain as verification evidence.

[Machine-readable result and skip list](regression.json)

Full-suite statement coverage was 30,153 / 33,217 (90.78%). The nine conditional graph/vector skips match the earlier M6 full run exactly. No source, test, dispatcher or S2 contract bytes were changed for this baseline. The local run used the checked-in `tests/support/run_offline_tests.py` across the complete collected test set. No type-check rerun or new model-quality test is claimed here.

The recorded Fake03 replay preserved 16 rows: ten controls, four refused original proposals followed by scripted gaps, A/X32's assumption and visible question, and the owner-deferred unscored A/X51 with low/moderate alternatives. This remains an offline replay, not evidence of a new Writer model run or engineering acceptance.

## Next step

M7 application implementation awaits acknowledgment of the [minimal S2 amendment](../../reviews/stage1-m7-report-provenance.md): an optional typed artifact result reference on `Derived`, reusing the existing trusted calculator action. Main remains at the fully tested `48fabae`; the M7 branch currently contains only this baseline record and its proposal. The final M7 implementation will need its own regression, tag and owner review.

The engineering lead remains unnamed. The 11 criteria and HP02 page 115 remain pending human review and are not supplied by this baseline run.
