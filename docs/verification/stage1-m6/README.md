# M6 issue migration and reply revision fix

The original review candidate is pinned at `5ea36cc3fc75daf7b1306864f73e7cb5ee361c36`, based on accepted M5 `64c9b4e`. It was prepared on `codex/stage1-m6`; main remained at M5 during the review and correction.

## Owner review correction

The owner conditionally accepted M6 after fixing revised human replies. The correction is pinned at `f68eba434012a159aec7d67cf74f9adf7b1cff5d`. It replaces the duplicate-question and last-row-wins behavior: the first reply records one fixed question operation for the issue; a revision retracts the previous answer as the authenticated owner, reopening that same question, and then answers it. Only the unique active answer supplies authority. The original answer and its retraction remain visible. The existing S2 contract already supports re-answer after retraction; no amendment or dispatcher change is needed.

The regression first reproduced two questions for “A only” followed by “Reopen for B”. On the corrected commit, **302 surrounding offline tests passed**, including both revision interruption points, exact redo, reverse read order, stale runtime projection suppression, host resume, the S2 contract and Fake03 replays. The independent reviewer separately ran 17 tests, all passing. Changed-module coverage is 95% for `issue_authority.py` and 96.91% for `issue_state.py`; the type diagnostic set remains exactly the same 676 existing errors, zero added. Automatic cleanup left zero passing case files outside caches. No tests were retired, no model calls were made, and historical cases were not modified. [Correction and individual passing checks](reply-revision.json)

The **6,148-test full run below predates this three-file correction**; it is retained as baseline evidence, not presented as a new full run of the fix. The correction's focused regression is separate. The conditional acceptance is satisfied, so the agreed closeout is a new tag, normal fast-forward of main, and deletion of the M6 branch. The original review tag remains unchanged.

## Original full regression

The fresh full offline regression at `5ea36cc` passed **6,148 tests**, with **9 unchanged conditional skips**, zero failures, zero missing or duplicate cases and no collection errors. It ran from 2026-11-09 12:21:08 UTC to 12:49:25 UTC (28 minutes 17 seconds). [Full result](regression.json)

Type diagnostics are unchanged: 676 existing errors, zero added. The checked `src/` package is byte-identical from the initial implementation through the final pin. All affected modules meet their M0 coverage floors after three additional successful operator checks. The full suite alone covered planning at 728/814 statements (89.43%); the separate operator workflows bring it to 737/814 (90.54%), above the 90.10% M0 floor. Both figures remain in the record. [Coverage](coverage.json) · [Operator checks](operator-checks.json) · [Exact operator test source](test_owner_workflow.py)

The offline Fake03 checkpoint retains 16 rows: ten controls, four refused original proposals saved as explicit gaps, A/X32's assumption at 27 with its question visible, and the owner-deferred A/X51 gap without an adopted value. This replays recorded inputs; it is not a new model-quality run. [Fake03 checkpoint](fake03-checkpoint.json)

## Behavior and boundaries

The four issue families now use immutable case content versions. Genuine generic human replies and planning/export-resume replies are recorded through the existing S2 question/decision actions. Their runtime projection is a later, separately redoable case transaction. Plan and requirements checkpoints retain their M4/M5 authority paths. Historical state values remain readable and are not rewritten.

`report-agent issues --project CASE` provides the trusted operator view of human waits, material issues and assertion questions, gaps, assumptions, conditionals, conflicts and findings. It associates known node, section or slope locations and leaves unknown locations explicitly empty. It is not an unrestricted agent query. Runtime guards continue to consider actual human waits rather than pausing on ordinary report uncertainty.

Writer assignment ownership, citation and proposal-receipt checks remain. Required issues still use the existing Word-comment/Excel-row path. Revising a route preserves its earlier immutable version and the route held by an already frozen export.

The three S2 contract files and the protected task/dispatch modules are unchanged. The complete `deep_runtime.py` and host-script ASTs match M5 after normalizing only the issue-reader import and call. No polling or dispatch control flow changed. The repetition guard already fingerprints every exact content head, including all five native issue types; a direct offline check confirmed that each changes its fingerprint. [Protected boundaries](protected-files.json)

The reviewed state census removes 51 legacy access signatures and adds none: 32 report-issue, 10 issue-record, four binding and five route accesses. Its scanner is unchanged, and the retired-write check now includes all four M6 families. [Census](census.json)

## Verification and diagnostic history

The final full run uses a detached snapshot with 51 hash-verified historical fixture files and the existing offline network guard. Source bytes, test collection, individual outcomes, conditional skips, coverage and the unchanged type-diagnostic set are checked before the tag. No application model/provider call or engineering review is part of this verification.

Earlier diagnostics exposed a misplaced import in a test-helper docstring, an obsolete joint-transaction expectation, the stale census and a missed host-script issue reader. The import and expectation were corrected at `80a6f6c`; the host reader and census were corrected at `5ea36cc`. The host defect could leave an answered checkpoint safely paused. Failed-run logs and cases are retained. [Diagnostic history](diagnostics.json)

The old trunk test is replaced by a stronger check of the accepted transaction boundary: a case projection and its revision roll back on failure, an already committed owner act survives, and exact redo completes the projection once. Every retired test has a specific replacement. [Test migration](test-migration.json)

The independent alignment reviewer `/root/m6_review` rechecked the implementation, recovery, location propagation, host AST and census. Its final focused checks include the nine host/census cases; earlier focused implementation and test-repair checks are recorded separately, not added to the full-suite total. [Independent review](independent-review.json)

## Temporary data and remaining scope

The final full suite left **zero passing-test files outside caches**. The external operator checks were rerun with the project configuration explicitly selected, so their passing temporary directory was automatically removed too. Forty-two stale files from the earlier unconfigured, successful external invocation were removed once after verifying its passing results; logs and test source remain. Failed diagnostic runs retain their evidence separately.

The existing pytest policy is `tmp_path_retention_policy = "failed"`, `tmp_path_retention_count = 1`. Shards have separate temporary roots and no explicit `--basetemp`. Logs, manifests, coverage, the pinned source snapshot and failure evidence are outside disposable passing cases. [Cleanup record](retention.json)

The original G5 case, historical ledgers, holds and source originals are not modified by M6. The 11 pilot criteria and HP02 page 115 still await a named engineering lead; the owner confirms resulting project conventions before the real report. Current A/X51 remains unscored. Report-model quality and engineering sign-off are not established by offline replay.

See the [M6 scope](../../reviews/stage1-m6-issues.md) and [consolidated section 9a handoff](../../reviews/stage1-9a-consolidated.md). After owner acceptance, the agreed closeout is to fast-forward main and delete the M6 branch.
