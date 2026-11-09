# M7 generation records: review candidate

Implementation: 5230b92cc34c609f84236d6830e11f77a84de14d. Review tag: stage1-m7-case-provenance-20261109, on codex/stage1-m7. Main remains accepted M6 (48fabae) until owner acceptance. The verification commit changes documentation only.

## Behavior

All six M7 families use existing immutable case-content versions: planned sections, assembly, outcomes, rescue projections, section prose and object prose. Output and its generation record share one case transaction. Selections advance while preserving prior versions; exact redo reuses the operation result. Historical state readers remain read-only, and the rescue route stays available.

Generation is operational case data, not an assertion. The artifact_ref proposal is withdrawn. S2 vocabulary/catalog/checks, assertion actions/queries, dispatcher, task supervision and host script match M6 byte-for-byte. The only assertion-package addition is a public read-only status lookup. [Protected files](protected-files.json)

Native generation records name the assembler and compare exact immutable references and content instead of receipt digests. Existing generic case/operation integrity, source-version pins, calculator contracts and O7 release-file digests stay outside this migration. Historical formats keep their validation.

Assembly freezes the actual selected calculator assertion IDs and exact plan/owner-act IDs. Their existing lineage reaches source facts and Writer judgments. Word and Excel preflight reject missing, inactive, stale or challenged inputs before returning cached exports. A real synthetic pair is exported, an upstream judgment is withdrawn, replay is refused and old file bytes remain intact. Existing affected-node G3 diagnostics are preserved. Free prose receives no guessed semantic support; further role/reference work remains in 9a.

Agent context reads cannot return host-only generation payloads directly or through a wrapper snapshot. Required issues, fixed text, source views, ownership, assessment and transformation checks remain enforced.

## Complete offline verification

**6,160 passed; nine unchanged conditional skips; zero missing, duplicate, unexpected or uncollected cases.** This is reconciled evidence across executions, not a single clean invocation. [Full result](regression.json)

All eight full-suite shards finished on fixed application bytes, from 2026-11-09 20:21:29 to 21:06:40 UTC (45 minutes 12 seconds). The first pass had 6,158 passes, two failures and nine skips. Both failures were obsolete test-store targets: a source-view test read a retired state receipt, and a rescue fault wrote a retired state key. Their four current-version cases passed on rerun, without application changes.

The cleanup audit then found passing artifacts outside pytest ownership. The two affected modules were corrected and all 27 cases passed again. Reconciliation selects the current-version outcome once per collected node. Other test functions, production, scripts and configuration are unchanged. The original failures, exact test patch and passing reruns are preserved. All 975 committed source/test/script/configuration files match these tested versions. [Source equality](source-integrity.json) · [Patch](test-repair.patch) · [Diagnostics](diagnostics.json)

Coverage is **30,276/33,344 statements (90.80%)**. Every affected module meets its M0 floor; new report_state coverage is 97.87%. Standard coverage.py aliases normalize the identical application paths from the full snapshot and focused rerun. The raw duplicate-path report remains local and is not used as the coverage gate. [Coverage](coverage.json)

Pyright reports the exact **676 existing diagnostics**, zero added and zero removed. It still exits nonzero; the repository is not type-clean. [Type comparison](type-comparison.json)

The state census removes 23 legacy access signatures and adds five explicitly classified historical readers. Its scanner is unchanged; all six migrated families have no production legacy writes. No whole test function was removed. Five parameterized IDs have individual replacements, and the net collection increases by ten. [Census](census.json) · [Test migration](test-migration.json)

The independent reviewer found no blocking issue and independently passed 18 focused checks. It rechecked the corrected tests and cleanup boundaries. Its count is separate from the full-suite total; no independent full run or artificial mutation test is claimed. Main verified the conditional rerun and cleanup evidence. [Review](independent-review.json) · [Focused checks](focused-checks.json) · [Skills](skills.json)

## Fake03 and cleanup

The offline checkpoint retains 16 saved judgments/reviewer views: ten controls, four original refusals saved as gaps, A/X32 at 27 with its question, and owner-deferred A/X51 without an adopted value. This is recorded replay, not a new model-quality run. All 51 imported historical fixture files were hash-verified before and after. [Fake03 checkpoint](fake03-checkpoint.json)

Pytest retains failed cases only, count one, without explicit basetemp. Passing-case files outside caches are **zero** after correction. The 18 original failure files remain. Source/export siblings now share a pytest-owned parent; the expression rule tree uses function tmp_path. One-time cleanup removed 94 old passing files from exactly three checked paths. Future cleanup is automatic. Logs, snapshots, coverage and failure evidence remain. [Retention](retention.json) · [One-time cleanup](passing-artifact-cleanup.json)

## Limits and handoff

No report/provider model calls, report restart, ledger/hold changes, original-source edits, deployment or main promotion occurred. Nine opt-in Neo4j/vector integrations remain skipped. The 11 criteria and HP02 page 115 still await engineering review.

This tag is for owner review. Later slices, paid verification, real-report delivery and engineering sign-off remain separate. See [M7 scope](../../reviews/stage1-m7-report-provenance.md) and [9a list](../../reviews/stage1-9a-consolidated.md).
