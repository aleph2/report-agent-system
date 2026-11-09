# M6 issue migration: review candidate

The implementation is pinned at `5ea36cc3fc75daf7b1306864f73e7cb5ee361c36`, based on accepted M5 `64c9b4e`. The branch is `codex/stage1-m6`. Main remains at M5 pending owner review and acceptance.

## Result

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
