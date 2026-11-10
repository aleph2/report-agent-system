# M8 delivery and final review — scope and decision

Source delta, first cleanup: **6 added / 15 removed** across 3 production files. Two native assembly self-comparison guards and broad digest-name filtering are removed; no application guard is added. Historical receipt readers and historical digest validation remain. Required current-assertion export checks remain.

## Authorized work

Owner authorized M8 and public code review on 2026-11-09. Dispatcher control flow, old runs, sources, ledgers and holds are unchanged. New AGENTS rules replace the old active instructions; dated history is evidence only. No new ASE process or skills-evidence file is introduced. Automatic passing-test cleanup remains enabled.

The first commit changes system_assembler.py, report_state.py and rescue_projection.py. Writers already build explicit native fields, so clean() is unnecessary. Two in-memory tamper assertions belonging only to the retired self-comparisons are removed; immutable case versions, redo, real Word/Excel exports, required issues, rescue transformation and stale-input refusal retain their tests.

## Storage migration

The census assigns content_delivery, content_final_review, rubric_reviews and rubric_status to M8. Move operational delivery/final-review selections to case versions; keep existing immutable ReviewRecord content and its null, partial and scoped outcomes. Query the case records through existing CLI/web interfaces. Keep O5-only rubric routes behind accessors until their separately agreed decision; do not turn selection into approval.

## Case-target review/release — owner deferred to 9a

Native ReviewRecord items target case ContentNodes/DocumentSnapshots and case Criterion refs. The fresh review-interfaces-v4 route deliberately reports scoped evidence with no whole-report verdict (content_delivery._v4_delivery). No production S2 record_finding/release caller currently exists.

S2 Finding requires its target to be an actual assertion member of the frozen pair (assertions/authority.py, review binding). Its release projection indexes every member through assertion states and C12 requires the full owner-confirmed output list. M7 deliberately keeps assembled sections and snapshots as case data. Passing only assessment assertion IDs would omit prose; creating dummy artifact assertions would reverse the accepted M7 decision.

Owner answered "Yes, defer it to 9a" on 2026-11-09 (local date). Complete M8 storage/query migration, preserving native review behavior. Case-target findings/formal-release integration moves to 9a with the typed-reference/role work. M8 makes no formal-release claim and changes no S2 contract.

This P2 gap blocks claiming full case-target review/formal release integration. It does not block storage migration or delivery of a draft. Main traced the current code; the independent reviewer confirmed the mismatch read-only. Keep engineering sign-off separate and human.

## Owner conditions and current application behavior

The owner requires draft-only delivery and an actual formal-release refusal until 9a. AssertionHost checks the bound action at authorization time, before an assertion transaction or receipt replay. Six host entry/role cases and otherwise-eligible release attempts require FORMAL_RELEASE_DEFERRED_TO_9A and no saved release operation. S2 component contract tests remain explicitly component-only. Existing UI delivery labels say draft; M8 makes no formal-release or engineering-acceptance claim. The [9a direction](stage1-9a-consolidated.md) now specifies findings/releases as assertions with typed case-version references, provenance as case data, no placeholder assertions, and one amendment covering C12's exact snapshot/Word/Excel output list.

Public-code permission did not settle private-history handling. Current public history still includes .ase and email addresses in instruction/history files. No private originals or history have been deleted or rewritten as part of M8.
