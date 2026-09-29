# Task039 independent input and evaluation baseline

2026-09-29. Independent tester/context-curator: `review_fork`. Frozen before
Task039 model calls. Main owns the runner and execution; independent review
owns interpretation of actual public outputs. This document and the preparation
receipt are evaluator-only and must not be serialized into the model request.

## Exact model-visible material

`.analysis/task039/frozen/model-inputs.json`, SHA256
`091ebccb990297a9a3e8d123c4b419c0f0adbdd064afe46d134c58e9125b62f3`.
Root keys: `version/cases`; version `broad-criteria-controls-v1`.
One anonymous case, `9c8c1f6128dc`, has only
`id/commission/source/rubric/candidate`. The existing Task037 user-message
format serializes the latter four fields, without the case ID or receipt.

| Field | Exact source | Characters | SHA256 |
|---|---|---:|---|
| commission | Task034 acceptance JSON body's `requirement_basis.goal` | 507 | `a0637c7c3e3b2d377cda50d7e29ee424f14753884996c2d12b0ffff258f5cd87` |
| source | Task038 frozen original-full case's `source` | 3714 | `d6a8958de2f95b3f85b247ceef7bd935470905bd773625d7a3c1ba19750e35eb` |
| rubric | `{"criteria": [...]}` containing all six original Task034 criterion objects | 2272 | `867ab0caed8d1aba1c47c20e746f872bc7e0dace53628c8ffe9302821d481330` |
| candidate | Task038 frozen original-full case's `candidate`, equal to the Task034 saved draft body | 17979 | `07c5933c882cadf8b3099785501726bdc54cd0d3a4f83272ce80e99fb64af7b7` |

Historical result source is `.analysis/task034/probe-results.json`:
acceptance ID `77303599-fad3-4468-8e0a-a442436c5e03`, draft ID
`b3452830-1325-47a5-92d5-8580f3800eb3`. Acceptance body hash is
`7a197764a53ec3768b4aa939445aea655641a3f4066595a0522d974acfa5a225`.
Every original criterion retains `id`, `condition`, `evidence_expectation`,
`allowed_limitations`, `requirement_refs` and `scope`; definitions and IDs
were checked against the actual Task034 initial `input.json` rubric. No field
is tightened, renamed, replaced by Task038's narrow checks or silently dropped.

The source comprises complete existing guide text blocks for physical pages
20–22/printed pages13–15, exactly as in Task038. Original PDF SHA256 is
`f063d3f281232a2c7057a8ab832e1e5d0f2262222df72fdf4edbe941b6ac8e98`.
The receipt carries original ToolMessage identity, locators and page-text hashes.
Original PDF pages were independently inspected during Task038 preparation;
that source-verification evidence remains valid. No new cleaned transcript,
retrospective answer, corrected report, error-location hint, old verdict,
development feedback or expected outcome is added to these four input fields.

## Predeclared C2 baseline

C2 is `criterion_427df1b2580e4b25b53d196be8aee4b8`.
Its expected state is **not_satisfied**. One valid material counterexample
within its scope is sufficient; discovering both known examples is not required.
With a supported C2 failure, the overall result should be **needs_revision**,
regardless of unresolved other criteria. This is not a complete gold verdict
for the rest of the report.

Coverage was checked against the original wording. C2 requires the guide's
indicator-system method, basic scores for each workpoint, reproducible weighted
calculation and guide-consistent level mapping; its requirement reference is
the guide's chapter3 and its scope is report chapter3 and chapter4 scoring.
Its evidence expectation asks for per-workpoint Rij values with explained
bases. The report itself states in §3.2(2) that Rij values follow guide table3-2
bands. Therefore a demonstrably incompatible application of table3-2 to a
premise the report already adopts defeats this method/scoring criterion.
Merely giving a reason or making the later arithmetic reproducible does not
establish that the adopted basic score follows the cited rule. C3's separate
stage/pending-confirmation requirement does not remove C2's existing obligation.

Two independently established sufficient counterexamples, for evaluators only:

- **Rainfall mapping:** §4.2(1) adopts annual rainfall1304.4–1582.5mm,
  misstates the applicable class as50–74 and sets R31=70, repeated in all six
  workpoint tables. Guide physical p20 says the upper rainfall class is75–100
  for rainfall above800mm and expressly sets100 above1000mm; its note permits
  local annual data when five-year data are unavailable. The current report
  premise conflicts with its adopted basic score without requiring new field
  measurements or a different preferred subjective score.
- **Facility-position mapping:** §4.2(5) adopts facilities within about1.0H
  below the roadbed, gives site① R42=80 and the other five70. Guide physical
  pp21–22 gives75–100 for that near-facility class, then the neighboring classes
  and explanatory notes.80 belongs to the interval;70 does not. The grounded
  counterexample is the latter group, not a claim that all six R42 values fail.
  No engineering-optimal point score is required for this interval contradiction.

Evaluate C2's reported state and substantive grounding separately. A response
that merely says N without a valid report/source-based reason does not show the
intended detection. At least one locatable valid material C2 counterexample
is enough; do not require both examples, a particular wording, or a proposed
repair. Another genuinely supported material C2 counterexample may also count
after manual verification against the supplied material. Additional erroneous
claims or repair advice remain separately reportable even when one valid
counterexample has been found. S or U does not meet this C2 baseline; record the
actual explanation and avoid inventing an internal cause.

## Other five criteria and limits

There are **no complete gold labels** for C1, C3, C4, C5 or C6 in this diagnostic.
Record actual states and evaluate concrete reasons against the evidence actually
provided. In particular, the original design/geology/format documents are not
supplied here. A report assertion about them is not independent source verification.
Do not turn an omitted discussion into an explicit endorsement of that claim;
likewise an overall N does not prove every other claim or repair suggestion valid.
Distinguish unknown/not-assessed judgments, unsupported certainty, genuine
counterevidence and protocol failures in the post-run record.

This is one original report with two fresh repetitions. Guide pages were selected
by developers and directly supplied, so it cannot demonstrate autonomous
retrieval or an unchanged Task034 trajectory. Both original commission and broad
criteria replace Task038's narrow commission/criteria; that contrast cannot
isolate a single causal variable. This has **no full-report positive control**,
cannot estimate a false-positive/false-rejection rate, and does not test a native
author/review loop, engineering approval or general reliability. A failure or
success is preserved; it does not authorize a replay or additional calls.

## Offline preparation evidence

`scripts/prepare_broad_criteria_diagnostic.py` uses only the standard library.
It successfully generated the one-case input and separate receipt, checks five
frozen input hashes before/after, checks the exact Task034 rubric definitions,
and requires unchanged Task038 source/report strings. It refuses different
existing outputs. No model, credentials, database/checkpoint, source rewrite,
production code or service access occurred. Task038's frozen inputs and running
experiment are unaffected. Main performs runner preflight before any invocation.
