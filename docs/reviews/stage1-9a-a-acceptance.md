# Part a — accepted after the clean replacement regression

Acceptance-record production source **+0 / -0 / net 0**; checks/guards **+0 / -0**; legacy fallbacks **+0**. Whole part a remains **+503 / -129 / net +374**. [Measured record](../verification/stage1-9a-a-clean/results.json).

**Accepted under the owner's conditional decision.** The single authorized replacement full run on **dfebc40** completed **6,160 passed / 9 existing skips / 0 failures**, in **26m32s**. All 6,169 collected cases were accounted for once: no missing, duplicate, unexpected or collection-error outcomes, and all eight execution groups exited zero. Every one of the 35 earlier failed-case replacements passed in this run. This is one clean full pass, not reconciliation of partial runs. The [first failed run](stage1-9a-a-full-regression.md) remains recorded as failed.

Coverage is **90.58%**; all 13 existing M0 floors are met. The nine external-service tests skipped are unchanged from the accepted baseline. No paid model calls were made. G5 originals, historical cases, source originals, ledgers and holds were not modified.

The frozen inputs were checked unchanged across 1,238 files, including 51 explicitly imported, hash-verified private historical fixtures. Automatic cleanup removed the successful run's temporary source copy and retained **zero test database files**. Logs, outcomes, coverage and authorization evidence remain private under .private/stage1-9a-a-clean-20261110/.

The dispatcher remains byte-identical to the pre-part-a baseline. The accepted correction's production code differs only by the neutral local-name substitution already reviewed; no guard exemption, file approval or new compatibility path was added. The acceptance commit changes documentation only; source, tests and configuration remain exactly those tested at dfebc40.

The owner-authorized next Git action is fast-forwarding main and publishing the immutable stage1-9a-a-accepted-20261110 tag. The existing codex/stage1-9a branch is retained for the remaining reviewed parts, as the split plan requires.

Before b/c candidate tags, search retired names and tool-set literals, classify intentional historical/negative coverage versus active migration gaps, and run affected modules first. This habit is recorded in [the entry plan](stage1-9a-entry.md); no new scanner or runtime guard is added.

**Next is b:** unscored/provisional draft rendering, required conflict issue routes, paired Word/Excel checks and rendered-page QA. Paid Fake03 still requires accepted a/b/c and a separate owner launch scope/cap. Formal release remains refused until e; paid extraction quality, rendered output and engineering sign-off are not claimed by part a.
