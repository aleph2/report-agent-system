# Task019: monitoring-quantity judgment diagnostic

2026-09-28. Main implemented and ran the four user-approved isolated conditions;
`postrun_review` independently checked the PDF transcription/reference, and
`alignment_review` reviewed the design and concrete harness. This is focused risk
diagnosis supporting the existing report trunk, not report acceptance or sign-off.

## Result and immediate decision

All four cases made the correct explicit target judgment. Both erroneous variants
were `needs_revision`; both quantity-corrected variants were `satisfied`. The actual
explanations locate physical PDF p97, table S3-2-10, total row: settlement plates
are 6; 40 is the count of inclinometer pipes. They also correctly identify the
other quoted totals: 96 displacement piles, 800m pipe length, 96 load cells.

| Context | Candidate quantity | Case ID | Top-level result | Explicit target judgment |
| --- | --- | --- | --- | --- |
| §5.2.3, 451 characters | Original 40 plates | 11b043c4fb44 | needs_revision | Correct mismatch: 6 plates; 40 belongs to pipe count |
| §5.2.3, 450 characters | Corrected 6 plates | 76c88e3b61f1 | satisfied | Correct source-supported match |
| Full report, 26,256 characters | Original 40 plates | bfbe28da747f | needs_revision | Correct mismatch: 6 plates; 40 belongs to pipe count |
| Full report, 26,255 characters | Corrected 6 plates | 5da4302a0107 | satisfied | Correct source-supported match |

The focused goal plus column-preserving source representation are sufficient for
this model to distinguish this particular error in either report length on these
four observations. There is no observed short/full discrimination difference here.
This does not establish that long contexts generally have no effect. The full
report condition contains the report, not the production agent's accumulated tool
history or all source materials. Historical Task018 still missed the error after
receiving flat source text; the present result does not identify which intervention
caused the difference.

Main's next diagnostic decision: preserve the autonomous responsibility prompt.
Do not yet rewrite it to mandate full scanning or a fixed tool sequence. The next
useful comparison should separate source presentation from target localization:
retain the full report and broad autonomous review commission, vary only flat
source text versus faithful table layout, and assess known errors independently.
That comparison has not been run in Task019. A supported improvement must then
return to the real reviewer -> responsible author -> saved revision -> re-review
path before claiming a correction-loop gain. No production baseline is promoted.

## Controlled inputs and execution

Prepared from the unchanged Task018 report ID
`cf1be9a3-756b-44a6-983c-0d85520906cc`, body SHA256
`7e86b61aa246f5f6b08ecd60c546a95c67cf88f9929f41462285c5c5eddea28d`.
Each corrected copy changes exactly one occurrence of `40 块沉降板` to `6 块沉降板`.
The complete §5.2.3 section is an exact substring of the matching full candidate.
References/expected labels are outside the runner's fixture directory and never
loaded by it. Fresh sessions use opaque IDs; actual order was short wrong,
full corrected, short corrected, full wrong. Corrected copies remain isolated;
they have not repaired the real report and still contain its other known defects.

The same commissioned target in every case is source fidelity of the parenthetical
aggregate quantities in §5.2.3(1), with locatable numeric support. Other chapters,
unquoted source items, equivalent counting-unit wording, export layout and engineering
sign-off are outside this narrow commission. This explicitly localizes attention
and therefore reduces production-task difficulty. Expected labels are never shown.

The full verified p97 table transcription, including all six nonempty data rows,
the total row, column identities, units and blanks, is supplied inline in all cases.
It is source evidence, not an injected verdict. Independent visual reference check:
[019-reference-check.md](019-reference-check.md). Original PDF SHA256
`74ab4e22761aea5d4130677ff50ffe0505676d27daa1fa48ca20eecdf0d96df6`;
transcription SHA256 `1fe051b550fa0faf7cbf4194447147f20f27fd41bf3829c3cb5b03cd54984c74`.
No new OCR, graph, image-model or evidence-tool calls were made.

The runner uses `create_agent` with the unchanged effective `reviewer_prompt()` and
native `GraderResponse` schema. It bypasses native transcript excerpting so the
full candidate is not silently truncated; it does not instantiate the outer author
revision loop. Production application code and prompts are unchanged. Every actual
first model message pair contains exactly system + complete HumanMessage, with the
candidate and source hashes verified against frozen inputs.

Plain UTF-8 text SHA256 (different encoding convention from historical `store.digest`):
- Effective system: `f48d315c8246f9310a0cf27cd7308d14df099715531590958a5a1901f7f861b5`.
- Rubric: `b63e7620378e6648fa9882db5c69e978a9744e0a5c095c1db0642792abc70ca5`.
- Common commission: `f34a7e40905a487eafce41de09f88c7915ad74a6926d0de19f25ab28bc04dbce`.

## Actual model configuration, usage and evidence

GLM-5.3 through existing `GLMChatOpenAI`, Chat Completions, non-streaming:
`reasoning_effort=high`, `thinking.type=enabled`, `clear_thinking=false`,
`parallel_tool_calls=false`, `max_completion_tokens=65536`. Temperature, top_p and
seed are not explicitly sent; provider defaults are not inferred. SDK max_retries=2;
timeout seconds connect/read/write/pool = 15/1800/60/60. Invocation callback parameters
are identical across all four cases. There are no evidence tools; the only tool
schema is native structured result submission (`GraderResponse`).

Versions: DeepAgents0.7.19, LangChain1.4.2, langchain-openai1.6.6,
LangGraph1.2.12, OpenAI SDK2.54.0. Code baseline commit `41ec4d0`.
Run window 12:44:48–12:47:09 UTC, approximately142 seconds.
Observed four model starts and four successful responses, one per case, with no
schema repair or model error recorded. These callback counts do not independently
audit SDK-internal HTTP retries. Provider-reported total usage: 46,460 input +
10,489 output = **56,949 tokens**; output includes reported reasoning-token usage,
not exported private reasoning content. No currency cost was estimated.

Private local evidence (ignored by Git):
- `.analysis/task019/fixtures/inputs.json`: exact common prompt/rubric/commission/source and candidates.
- `.analysis/task019/reference.json`: development-only labels and preservation hashes.
- `.analysis/task019/freeze.json`: pre-call code/input/reference hashes.
- `.analysis/task019/results.json`: actual outputs, usage and integrity summary.
- `.analysis/task019/actual-prompt.md`: verbatim audited system, common commission
  and rubric, extracted for the user's prompt inspection; source/candidate omitted
  in this reading copy and retained in the complete per-case inputs.
- `.runs/task019/judgment/<case-id>/input.json`: complete actual intended input.
- The same case folder's `output.json`, `model-io.json`, `settings.json`, `receipt.json`:
  public structured output, redacted actual model messages/invocation options,
  configuration and attempt receipts. Credentials/private reasoning are not exported.

## Verification, disposition and limits

Four meaningful offline tests passed in2.69 seconds: complete long input and tamper
detection, label-field rejection, fresh input/public-result export/no replay, and
redacted failure receipts. `git diff --check` passed. The original26 Task018 files
and all30 frozen code/input/reference files remained byte-identical after the run.
No original DB/report/export/source was modified. Git author is
`menglinsun <menglinsun@hotmail.com>`; business fixtures and run data stay ignored.

Independent alignment review and Main disposition:
[019-alignment-review.md](019-alignment-review.md). Independent output assessment is
recorded in [019-output-review.md](019-output-review.md).

The existing F01/P2 and P2-018-R01 remain open: incorrect report quantity and broader
production false acceptance still affect monitoring inputs and verdict reliability.
They block content-quality promotion, reliance on the erroneous engineering input
and engineering sign-off. They do not block this isolated diagnosis or an accurately
qualified draft review; containment is unchanged source/report data, narrow labels,
explicit unresolved status and no production promotion. Main/author owns follow-up.
No new defect is established by this diagnostic. Requiring all report issues to be
resolved before this experiment would delay identification without improving its
isolation; conversely, focused success cannot justify accepting the whole report.

This is one observation per cell, one known error, clean manually verified table
representation and a localized commission. It is not a reliability estimate, a
causal proof about prompt changes, autonomous source discovery, full-report quality,
or demonstrated author correction. The exact root cause remains unresolved.
