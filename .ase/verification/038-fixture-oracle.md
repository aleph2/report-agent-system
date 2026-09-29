# Task038 independent fixture oracle — frozen before model results

2026-09-29. Independent tester/context-curator: `review_fork`. Main owns the
runner, paid execution and integration. This file is evaluator-only; neither it
nor the preparation receipt may be serialized into model input. No model calls,
credentials, production writes or business-report revisions were performed here.

## Frozen inputs and predicate scope

Final revision2 model-visible file: `.analysis/task038/frozen/model-inputs.json`,
SHA256 `a196efb76a37c3201ca54e3ead7f0fb265041d881e6ed7d13de29860845544f5`.
Final receipt: `.analysis/task038/frozen/input-receipt.json`.
Root keys are exactly `version/cases`; each case has exactly
`id/commission/source/rubric/candidate`. The four cases share byte-identical
commission, source and rubric strings. Random IDs carry no condition names.
The rubric has two shared IDs:

- `criterion_d1ae7cfb116f6bfe`: §4.2(1) adopted rainfall/temporary construction
  conditions, claimed band and R31 value comply with the supplied guideline.
- `criterion_d12bd88289dfa050`: §4.2(5) adopted facility positions, claimed band
  and R42 group values belong to the supplied guideline's applicable interval.

The earlier `.analysis/task038/model-inputs.json` (SHA256
`13f36a8e3380f1658d79d5a755f40f797d5c475f1d1ef89a50f8da3f29ee7af3`)
and its `input-receipt.json` are preserved unchanged as an **unrun draft**.
They were never supplied to a model or used for scoring. Before paid calls,
alignment review identified that merely relabeling the original >1000mm phrase
as a75–100 class left the counterfactual's class description imprecise: the class
condition is >800mm, while >1000mm triggers the fixed100 note. Main accepted
revision2, which states both separately. The neutral commission, source, rubric,
criterion IDs and case IDs are byte-identical to the unrun draft. All labels
below refer only to the final revision2 file; no model results informed this edit.

These are **known-claim conditional rule predicates**, not the original six
acceptance criteria. They do not judge field truth, best in-band score,
construction scheduling, other indicators, arithmetic, F/levels, full-report
acceptance or engineering approval. The report's pending-confirmation language
remains present in every condition. It need not be resolved to decide whether
the present adopted mapping fits the provided rule. Other full-report defects
must not be imported into these two outcomes.

## Independently defensible labels

`N=not_satisfied`, `S=satisfied`. No cell requires `undetermined` for these given
premises and available rules. The second predicate is universal over both groups
named in §4.2(5); the original's valid value for site① does not rescue the others.

| Case ID | Report version | Context | R31 | R42 |
|---|---|---|---|---|
| `3654137d48c3` | Original | §4.2 + chapter6 | N | N |
| `62a14e5d301b` | Original | Full report | N | N |
| `0624bbf3556b` | Target counterfactual | §4.2 + chapter6 | S | S |
| `a0f3f6154bef` | Target counterfactual | Full report | S | S |

The original §4.2(1) uses annual rainfall1304.4–1582.5mm, claims a50–74 band,
and adopts R31=70. Guideline physical p20/printed p13 specifies75–100 for the
class containing annual rainfall >800mm and explicitly sets100 when rainfall exceeds1000mm;
it allows local annual data when five-year data are absent. Thus the adopted
premise does not require new rainfall retrieval for this conditional predicate.

Original §4.2(5) adopts facilities within roughly1.0H below the roadbed,
R42=80 for site① and70 for the rest. Physical pp21–22/printed pp14–15 give
75–100 for this near-facility class and preserve the neighboring50–74,
25–49 and0–24 classes plus interpretive notes.80 belongs to75–100;70 does not.
The diagnostic75 is an interval member, **not a recommended engineering score**.
Notes about preferring higher/lower values are retained in source, while the
criterion expressly does not test that preference or an optimal point choice.

The tester independently rendered and inspected all three original PDF pages
using pdfplumber's page renderer. Their decisive cells and full notes agree with
the existing public text blocks. The original flattened parse is preserved in
model input, including its spacing/OCR-like transcription artifacts; no cleaned
answer-bearing replacement or model-authored table was supplied.

## Exact origin and transformation

Report: `.analysis/task034/probe-results.json`, select `id=
b3452830-1325-47a5-92d5-8580f3800eb3`, `kind=draft`, read `body`.
Original body has17979 characters and SHA256
`07c5933c882cadf8b3099785501726bdc54cd0d3a4f83272ce80e99fb64af7b7`.
The same file contains the historical acceptance body under
`77303599-fad3-4468-8e0a-a442436c5e03`, SHA256
`7a197764a53ec3768b4aa939445aea655641a3f4066595a0522d974acfa5a225`.
Those original criteria are retained as provenance, not silently repurposed as
the two new diagnostic criteria.

Source PDF: `.runs/task034/native-probe/sources/路堑高边坡施工安全评价指南.pdf`,
SHA256 `f063d3f281232a2c7057a8ab832e1e5d0f2262222df72fdf4edbe941b6ac8e98`.
Source ID `932dc8f9-ef16-40b6-9975-c5a449a4b6f7`.
Exact received text comes from `.runs/task034/native-probe/model-io.json`:
event `sequence=123`, `kind=deep_model_request`, `data.messages[0]`, select
the `type=tool` message with `tool_call_id=call_d62566be88794d1b98dc8fe4`;
decode `content`, retain complete `blocks` with ordinals19,20,21. The decoded
objects contain `ordinal/locator/text`, corresponding to physical pages20–22.
The whole ToolMessage content SHA256 is
`96ab20f2db433708538c6d4b16fdf8c9851ca54767fd7631349f3499cc60076b`.
The three page text hashes and original locator strings are in the receipt.
Their mechanical `source_table_views` have empty `tables`; they are not used
or described as a verified structured table.

Local candidates are exact whole-section slices joined with two newlines:
original zero-based Python character ranges `[7199:8232]` and `[16874:17979]`.
The first preserves **all** §4.2 paragraphs, including unrelated indicators;
the second preserves **all** chapter6, including limitations. Source is identical
in local/full conditions. Full candidates preserve the complete original body
or its controlled target transformation.

The preparation script asserts five exact replacement families and reverses
them to verify byte-identical recovery of the original body:

| Target replacement | Count in full report |
|---|---:|
| Replace the quoted>1000mm/50–74 class with the exact>800mm/75–100 class, then explicitly apply the>1000mm fixed100 note | 1 |
| `R31=70` → `R31=100` in §4.2 and §6.2 | 2 |
| Six X31 table cells70 →100 | 6 |
| §4.2's other-sites `R42=70` → `R42=75` | 1 |
| Five X42 table cells70 →75 | 5 |

The exact first replacement's new text is
`"施工地区过去5年内年均降雨超过800mm"档（75～100）；已采用年均降雨量超过1000mm，依该表说明应取100`.
The existing preceding rainfall premise and following adopted R31 statement and
pending-confirmation sentences remain, with the declared R31 value replacement.

Site①'s R42=80 and all non-target reasons/limitations stay unchanged. Full
counterfactual body SHA256 is
`8f594fbee1eb7589b65a61b74b929d3478fda8eca697ef5d1f858e0ed19f18e2`.
Original local/full lengths are2140/17979 characters; final target-counterfactual
local/full lengths are2171/18016. The receipt records every exact slice and hash.
Its existing F calculations and levels are intentionally unchanged, so this
counterfactual is **not a corrected business report**. Only the scoped target
assertions are made consistent; no score is adopted into saved results.

## Verification and inference limits

`scripts/prepare_real_context_diagnostic.py` uses only the Python standard
library, verifies five original file hashes before and after construction,
checks report/acceptance identities, selects only the public source observation,
and refuses different existing outputs. It opens no database/checkpoint, accesses
no service configuration and makes no model calls. It successfully produced the
four cases and receipt. Main owns runner compatibility and offline tests.

Task034's final request demonstrably contained these rules and the complete
report text; receipt does not establish attention, comprehension or an internal
reason for its false pass. No geology counterevidence was received in that
probe, and none is added here. Task035 retrospective answers are excluded.

This 8-call matrix (four frozen cases × two repetitions) measures scoped response
differences for a known failed real report. Local/full varies total length,
available surrounding information, placement and possible distractors together;
it cannot isolate a unique long-context mechanism. Original/counterfactual
changes both target predicates together, so it is not an interaction test.
Both succeeding would leave autonomous discovery, trajectory, production
criteria, repair-loop quality and generalization unverified. No result here
alone closes G1 or authorizes the original all-pass.
