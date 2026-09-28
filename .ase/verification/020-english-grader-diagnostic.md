# Task020: English commission comparison

2026-09-28. Main executed the four real cases requested by the user. The existing
independent alignment-reviewer `alignment_review` checked translation/input
equivalence and then independently scored the public outputs. Its read-only
findings are recorded here by Main. No runtime reviewer stage was added.

## Observed result

All four English-commission cases made correct explicit target judgments, the
same four outcomes as Task019's Chinese commission. Both original40 cases identify
the column error (6 settlement plates; 40 inclinometer pipes), and both corrected6
cases explicitly confirm the quoted quantities against the source total row.
The conclusions remain scoped to the stated quantity check.

| Case | Context/variant | Chinese commission | English commission | English model responses |
| --- | --- | --- | --- | ---: |
| 11b043c4fb44 | short/original40 | needs_revision, correct mismatch | needs_revision, correct mismatch | 1 |
| 5da4302a0107 | full/corrected6 | satisfied, correct match | satisfied, correct match | 1 |
| 76c88e3b61f1 | short/corrected6 | satisfied, correct match | satisfied, correct match | 2 |
| bfbe28da747f | full/original40 | needs_revision, correct mismatch | needs_revision, correct mismatch | 1 |

This controlled sample shows no target-judgment improvement from the translation.
It does not establish language equivalence or that language never affects grading:
both batches already score4/4, each cell ran once, and language order was not
randomized. Wording/tokenization also changes with translation. Source/report
content remains Chinese. There is no evidence here to promote an English prompt
as a remedy for the historical autonomous-review failure.

## What changed and what stayed fixed

Only the common Chinese commission was translated into English. The exact English
text is versioned in [020-english-grader-diagnostic.md](../tasks/020-english-grader-diagnostic.md).
The production responsibility prompt, native grading contract and rubric were
already English and remain byte-for-byte identical at the text level. Main and the
independent reviewer verified identical IDs/order, source text, candidate bodies
and candidate hashes. Every audited first HumanMessage equals its Task019
counterpart with exactly the commission substituted, with no truncation or new
answer hints. Source-table verification and reference labels are reused from019;
the runner does not access labels. Four fresh sessions, no evidence tools, no
author loop or original-report modifications.

Actual system SHA256: `f48d315c8246f9310a0cf27cd7308d14df099715531590958a5a1901f7f861b5`.
English commission SHA256: `f8f9d08d64c94c973edc4dc7301069b714bd55bbd99a56aa96c04e6061ff5982`.
Preparation task commit `7830db9`; unchanged runner baseline `41ec4d0`.
All102 frozen original Task018/019, production code and Task020 input/reference
files remained byte-identical after execution. The new task packet is the only
pre-run tracked change; no application code or persistent production prompt changed.
Existing four harness tests remain applicable; no redundant rerun was claimed.

## Invocation evidence

GLM-5.3, reasoning_effort high, thinking enabled, clear_thinking false,
max_completion_tokens65536, parallel_tool_calls false, non-streaming Chat Completions.
Temperature/top_p/seed are unset. SDK max_retries2 and timeouts15/1800/60/60 seconds
unchanged. All actual invocation parameter objects equal Task019's; the independent
reviewer additionally verified corresponding settings.json bytes identical.

Five observed model requests/responses for four initial cases, 12:54:03–12:55:51 UTC,
approximately108 seconds. Provider usage totals: **50,006 input +7,233 output =57,239
tokens** (output includes reported reasoning tokens). No price estimate or claim
that callback counts independently audit SDK HTTP retries.

Short corrected case first returned a public natural-language answer already
correctly identifying6 plates, without the GraderResponse tool call. The unchanged
native agent continued; its second request contained only original system/human
plus that AI reply. It then submitted the same factual conclusion as structured
GraderResponse. There was no ToolMessage, schema-validation error or human factual
feedback in between. This is structured-output continuation, not a factual revision
or a demonstrated schema-validation-error repair. It is recorded, not hidden as a
single model call. It did not trigger a new manually replayed case.

Private, Git-ignored evidence:
- `.analysis/task020/actual-prompt.md`: verbatim actual system/common commission/rubric.
- `.analysis/task020/fixtures/inputs.json`: frozen complete four inputs.
- `.analysis/task020/reference.json`, `freeze.json`, `results.json`: separate labels,
  preservation hashes and actual comparison summary.
- `.runs/task020/judgment/<case-id>/`: input.json, output.json, settings.json,
  receipt.json and redacted actual model-io.json. No credentials/private reasoning
  are exported. Preparation/analysis scripts are in `.analysis/task020/`.

## Independent finding and Main disposition

**P3-020-R01: feedback exceeds the numeric commission in the full-error case.**
In bfbe28da747f, the Correctness gap directs replacing the wrong quantity with
`沉降板6块、测斜管40个`, adding a previously unquoted item despite the explicit scope
exclusion. The Evidence gap also objects to absent citation at the point of
quotation, although this diagnostic asks for a supported review conclusion, not a
new inline-citation requirement. The source facts and core mismatch detection are
correct; the extra requirements exceed what was commissioned.

Severity P3 because the deviation is limited extra feedback in an isolated test;
there is no demonstrated false target rejection, altered real report or lost work.
Scope: full-error English feedback only; no claim that all feedback is exact or
that translation caused it. Containment: retain the actual output, score only the
predeclared target, do not apply extra requirements to production. Main accepts the
finding, keeps it open for feedback-scope evaluation before using such feedback in
the author correction loop, and does not rewrite prompts or rerun paid cases from
this single observation. It blocks treating every suggested edit as an authorized
requirement; it does not block completing this diagnostic. Delay would not improve
the already recorded comparison or protect any presently modified production work.

Existing F01/P2 and P2-018-R01 remain unresolved in the original report and broad
review path. This experiment neither repairs them nor permits content-quality
promotion, engineering reliance on the wrong value or engineering sign-off.

## Cause assessment and next discriminating decision

The established production failure is a wrong acceptance after relevant report
text and flattened source-page text reached the grader. Arrival does not establish
correct column binding or claim-by-claim verification. The focused experiments show
the model can make the specific judgment when relevance is explicit and table
columns are preserved, in either commission language. They do not expose the
model's private internal process or uniquely identify a cause.

Current candidate causes are source representation/column mapping, autonomous
selection of what to verify, and a stop/verdict decision that overstates what has
been established; accumulated tool context is another uncontrolled historical
difference. English versus Chinese is not supported as the remedy by these results.
The next useful experiment remains the Task019 decision: retain the broad autonomous
review goal and full report, vary only source presentation, and assess detection
independently without pointing out the target sentence. That has not been executed
in Task020. Evidence for autonomous detection must precede a claim that the real
author/reviewer correction loop has improved. No production baseline promotion.

Git author remains `menglinsun <menglinsun@hotmail.com>`; Main records the actual
work and independent findings rather than claiming general reviewer reliability.
