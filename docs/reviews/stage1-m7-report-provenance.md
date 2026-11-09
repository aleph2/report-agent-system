# M7: immutable case records of report generation

The owner's latest decision on 2026-11-09 supersedes the earlier artifact-assertion proposal: **keep C5 and S2 unchanged; store generation provenance as immutable case records; check referenced assertions at export.** The earlier proposal and C5 reproduction remain preserved at `0c5781a`.

## Boundary and consumers

Assembly provenance records a completed system operation. Existing review code reviews frozen content and scoring results; it does not challenge, endorse or supersede generation provenance as a world claim. Independent reviewer `/root/m6_review` confirmed this from the actual readers.

| Family | Current representation | Consumer |
| --- | --- | --- |
| planned_section_receipt:* | SectionProvenance case version | fixed/derived section validation, group/order checks, export |
| assembly_receipt:* | AssemblyProvenance case version | source/plan bindings, issue placement, frozen input-currentness at export |
| commission_outcome:* | Existing CommissionOutcome plus versioned OutcomeSelection | exact object outcomes included when freezing a snapshot |
| rescue_projection:* | RescueProjection case version | exact source/task/transformation validation |
| g6_section_prose:*, g6_object_prose:* | Versioned ProseSelection | current assigned prose and revision validation |

The four receipt families follow the owner's new decision. The two prose-selection families already belong to M7 in the full M0 census. Migrating rescue storage does not retire or change its route. The dispatcher, role prompts and later task-store work remain unchanged.

## Atomic writes and history

Output and generation metadata are saved together in the same case transaction using the existing content_versions/content_heads component. A failed transaction leaves neither partial output nor its provenance. An identical completed operation returns its recorded result. Generation metadata for an exact output version cannot be replaced; changes require another output. Operational prose/outcome selections may advance their versioned head while retaining earlier selections.

Metadata uses plain case references. It introduces no new assertion, role, action, approval authority, backlink, joint database commit or repair service. The record's producer is `system:report-assembler`, not the calculator. Historical state readers remain read-only.

M7 provenance payloads drop the former body/text/composition/decision/source/record/binding hashes. Native checks compare exact immutable records, references and recomputed transformations directly. Historical readers retain validation of their original formats. Existing generic case-storage/operation integrity, source-version pins and O7 Word/Excel release digests remain outside the provenance-payload migration.

## Actual staleness consumer

AssemblyProvenance freezes the existing calculator assertion IDs actually referenced by the selected assessments and the exact plan/owner-act IDs. Calculator lineage already reaches the original source facts and Writer judgments. The system does not guess additional semantic support from shared page numbers or free prose.

Both Word and Excel export preflight read those IDs through a public read-only assertion-status helper before returning a cached export result. Missing, inactive, stale or challenged inputs refuse export. Existing plan/approval and source-access checks run first. Existing score failures still identify the affected generated nodes and derived sections through G3 diagnostics.

A native integration test generates a reviewed score, assembles and exports Word/Excel, confirms same-operation replay, retracts an upstream judgment, then refuses the repeated export while preserving the original file bytes. A separate case test includes A/B source assertions without adding a cross-subject world claim and refuses export after a source supersession.

## Contract restoration

The abandoned artifact_ref field and its special packet handling are removed. kinds.py, actions.json, checks.sql, assertion actions.py and queries.py again match accepted `48fabae` exactly. The only addition inside the assertion package is a trusted read-only status lookup. s2-amendments.json retains the chronological proposal/acknowledgment and records the owner's withdrawal/restoration; there is no active M7 vocabulary or check extension.

M4/M5 references stored as JSON text remain on the 9a list, as the owner requested. This slice does not move them.

## Verification and handoff

The opening full run on accepted main `48fabae` passed 6,150 tests with nine unchanged conditional skips. That is baseline evidence, not the final M7 run.

Focused current-case integration passed 275 tests, including immutable generation/rollback, exact versions and transformed content, actual cached Word/Excel refusal after a judgment withdrawal, required issue placement and legacy reads. The census scanner is unchanged; its reviewed historical fallback binding is explicit, and the six migrated families have no legacy writes. Existing storage-facing tests now read case records; digest-only scenarios map to exact-reference/immutable-payload behavior tests.

M7 implementation 5230b92cc34c609f84236d6830e11f77a84de14d has complete reconciled offline coverage: 6,160 passed and nine unchanged skips, all affected M0 floors met and zero new type diagnostics. The [final record](../verification/stage1-m7/README.md) preserves original test failures, corrected-case and cleanup-module reruns, independent review and source equality. The review tag is for owner review. Main remains accepted M6 until the owner accepts M7. The original G5 case, all financial records/holds and source originals remain untouched; no model calls are authorized or needed for this migration.

The 11 criteria and HP02 page 115 still await a named engineering lead. That does not block this offline storage change.
