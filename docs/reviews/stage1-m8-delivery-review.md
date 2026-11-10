# M8 draft-only delivery storage — review candidate

**Production source: 73 added / 44 removed. Guards: one application release refusal added; two redundant native self-comparisons removed, along with the digest-name filter. Legacy: two historical selection readers and the O5 rubric route remain; no new compatibility path.**

Implementation: `6c680af50191e8de907c1207429401ba67849a78`, branch `codex/stage1-m8`. Main remains accepted M7 (`5dfe607`) until owner acceptance.

Delivery and final-review selections use immutable case versions and the caller's case transaction. Identical redo reuses the version; explicit clearing cannot revive historical state. Existing CLI/web queries read through stable facades, so the dispatcher is unchanged. Selections do not count as fresh review evidence. Native scoped/partial/null review outcomes remain intact; the UI continues to label delivery as a draft.

The owner's added condition is enforced at `AssertionHost._authorized`: formal release raises `FORMAL_RELEASE_DEFERRED_TO_9A` before an assertion transaction or receipt replay. Six entry/role cases and otherwise-eligible reviewed deliveries prove refusal with no release operation. S2's component lifecycle tests retain their review, pair, authority, withdrawal and sign-off checks; they are explicitly component tests, not an application release claim.

**Verification: 6,172 passed; nine unchanged conditional skips; zero unresolved failures, missing, duplicate or unexpected cases.** This is reconciled evidence, not one clean invocation. The fixed `f75204f` full run had 6,162 passes, four failures and nine skips in 33m45s. The failures expected zero added case objects after selection; the corrected tests require exactly one selection record while preserving all earlier objects, file bytes and no-replay checks. All 25 prototype cases passed. Final-source checks passed 114 guard/contract/storage cases and 54 delivery/reuse cases. Two renamed foundation cases have explicit replacements; no test was skipped to pass.

Coverage: **30,289 / 33,357 statements (90.80%)**; all affected M0 floors met. Pyright retains exactly **676 existing diagnostics**, none added or removed; it still exits nonzero. All 985 source/test/configuration files match the final test copy; 51 fixture inputs remain unchanged. Automatic failed-only retention is enabled. Final passing checks leave no case databases; failed/red roots retain small failure/shared-fixture evidence.

Main ran the tests. Independent M8 review inspected code/tests read-only and found no blocker. S2 and dispatcher files are byte-identical to accepted M7; `.ase`, source originals and financial history are untouched. No paid model run occurred.

The owner approved deferring case-target findings/formal-release integration to [9a](stage1-9a-consolidated.md): findings and release decisions become assertions with typed case-version targets; C12 binds the snapshot and both file digests. Assembly provenance stays case data, with no placeholder content assertions. M8 claims no formal release or engineering acceptance.

[Detailed results and mappings](../verification/stage1-m8/results.json) · [Post-full-run changes](https://github.com/aleph2/report-agent-system/compare/f75204f9ae7c9704e2badeeafc9ee76e3c03e269...6c680af50191e8de907c1207429401ba67849a78). Public-history privacy handling remains open; no data/history cleanup or visibility change was performed.
