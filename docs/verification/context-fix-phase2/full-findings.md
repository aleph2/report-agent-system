# Phase2 first full regression — confirmed corrections

Source +2/−1; checks/guards added/removed: 0/0 (existing type check corrected); new legacy fallback paths: 0. Existing test expectations +7/−5; new test functions: 0.

The frozen `f7ad188` full run finished FAILED: 6262 passed,25 failed,9 unchanged skips; all6296 nodes accounted once in2234.3s. Its frozen source and failed artifacts remain unchanged. Neo confirmed two P2 causes that block claiming that candidate passed:

- Item3 used the replaceable FilesystemMiddleware constructor as the `isinstance` type. Existing offload tests replace it with a factory, producing TypeError before graph execution. The correction imports the stable SDK class for type membership while retaining the replaceable constructor and its selected allowance.
- The probe fixture still expected the former unbatched script's call count. Actual scenarios reached the correct page-sheet checkpoint before failing old count assertions. Existing expectations now derive the text-call count from the prepared script before consumption and include observed vision invocations in combined accounting. All hold, settled-usage, no-Writer, trace, checkpoint and no-relaunch assertions remain.

Main ran the existing reproduced offload case, the repro-judgments module and the existing probe module: **56 passed in 370.68s**. No new test case was added for these fixture/value changes. Neo reviewed source and terminal logs and approved the separate correction and new frozen offline candidate. Neo did not independently rerun tests.

Evidence: `.private/context-fix-phase2-20261112/implementation/full-findings-focused.log` and frozen `.private/context-fix-phase2-full-20261112/full/`. This record is not a clean full-regression result. The original full is terminal and remains failed; the corrected candidate still requires a clean replacement full, actual-candidate replay review, immutable tag and preflight. No paid model call or financial mutation occurred.
