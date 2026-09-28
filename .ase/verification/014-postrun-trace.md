# Task014 Post-run Trace Verification

Date: 2026-09-28. Independent reviewer, read-only examination of
`.runs/task014/autonomous-report/state.db` and checkpoint metadata using SQLite
`mode=ro`. No production edits, project writes, model calls, credential reads,
checkpoint message-blob deserialization, hidden-reasoning inspection, or engineering
answer assessment. Event numbers below identify rows in this project's `events`.

## Outcome and Status Layers

One saved draft: `a0e13187-24d2-42f6-80b0-782b9e1c39da`, 21,419 characters.
Native grading run `80343feb-18d9-47fc-9b8b-04228effa36e`, iteration **0**,
`satisfied`, `unverified=false`, origin `native_rubric_checkpoint` (event 231).
The saved review's draft-body hash and rubric hash match the saved draft and
active rubric. There is one result version, not an unrecorded revision series.

The state layers must not be conflated:

- Raw `report_status`, raw `delivery.status`, and `deep_run_finished` event 232
  are **needs_human**. One unresolved source issue remains registered.
- Native `satisfied` is projected by `review.py:157` (`review_delivery`) and
  `knowledge_state.py:47` (`project_state`) to **reviewed_draft**. This is the
  return status Main reported, not a raw database status update. This projection
  does not mean that the human decision was supplied or the issue disappeared.
- `checkpoint_resume=false`, `native_interrupts=[]`, `report_error=null`; all
  56 model requests have matching response IDs. No pending model request or
  human interrupt is recorded. Raw `needs_human` does not establish an unfinished run.
- Main reported process exit 0. This audit independently verifies the finish
  event and settled state; it did not recover an OS exit-status record.

## Assistance, Restart and Code Evidence

Event 2 is the only `trial_attempt_intent` (`resume=false`); event 3 is the only
`deep_run_started` (`resume=false`, `native_checkpoint=false`). There is exactly
one finish and no cancel/error/restart event. Checkpoint metadata contains one
root `input` checkpoint and 129 root `loop` checkpoints, plus one native grader
input and 26 grader loop checkpoints. No checkpoint blobs were opened.

No operator-feedback, human-decision, correction, source-change or external
review events/keys were found. The single issue has no `decision` or
`decision_origin`. Model-audit HumanMessage variants are the initial project view,
the native context-extraction request (event 97), and native summarization
continuation (`lc_source=summarization`, first observed at event 99), not three
operator interventions. Native summary generation is included in model usage.
No task/delegation tool was called; the coordinator produced the draft itself.

All production files in the original import receipt still match their hashes.
The current rules SHA256 is still
`cff789a67297516f4b92c46bb7cb03ece799ab17a850514340bc50130f527106`, matching
Main's launch record. None of those code/config files or the rules file has a
modification timestamp at or after launch. Together with the single-run trace,
this supports **no observed runtime code/rule change or external assistance**.
It is not tamper-proof monitoring: pre/post hashes cannot exclude an unlogged
change-and-revert, and this audit did not inspect credentials or all environment
values. Main's separate effective-configuration record remains the reference.

## Actual Grader Evidence

Grader activity occupies events 180-231; it made 13 model requests and 12 tools:

| Tool | Events / observations | Coverage actually recorded |
| --- | --- | --- |
| `project_status` | 183, observation in 185 | Current draft/source/issue metadata; projected status was then `unreviewed_draft` |
| `read_result` | 187, 191 | Same draft; offsets 0 and 16000 returned 16000 + 5419 characters, then `next_offset=null` |
| `read_review_export` | 195, 199, 203 | Block ranges [0,30), [30,130), [842,902): 190 of 902 blocks, not the whole export |
| `search_sources` | 207, 211, 215, 219, 223, 227 | Returned 10/28, 10/14, 5/5, 2/2, 3/3, 10/30 matches respectively; three searches remained paginated |

Search observations cover five distinct source IDs, including the design-source
PDF, geology-source PDF, high-slope guide, and bridge/tunnel guides. This lists
observed retrieval, not correctness of source selection. All export reads bind to
the same preview and DOCX SHA256
`43527a63bf83ced06a9c4d55c00efc6939840896233dededec71ea3cbbb4440a`.
The grader also receives the native bounded transcript and prior preview metadata.
It did not directly call `read_source_page`, `inspect_source_page`, vision,
`calculate` or graph tools. Export text/structure sampling is not rendered-page
visual inspection or proof that every export block was checked.

### P2: Six-case recomputation claim exceeds demonstrated tool evidence

The persisted grade explicitly says **"all six F-value calculations recompute
correctly"**. The coordinator called `calculate` nine times (events 101, 105,
109, 113, 117, 121, 142, 146, 150). The grader called it **zero** times.

The actual first grader request (181) includes exactly four complete prior
`[tool:calculate]` observations, matching coordinator calls at 121, 142, 146 and
150. The five earlier calculation observations are absent from that bounded
transcript. This is consistent with installed DeepAgents 0.7.19
`middleware/rubric.py:1362`, which selects the transcript tail and bounds messages.
The grader did obtain the complete report text separately.

Confirmed scope: the trace does not demonstrate an independent six-case tool
recalculation, nor does it establish full six-case calculator-evidence coverage
at grading time. The grade must not be presented as such verification. This audit
does **not** establish arithmetic error, absence of model-internal calculation,
or that the four retained observations map to four final cases; engineering
answers and hidden reasoning were intentionally not assessed.

Severity rationale: P2 evidence/claim-auditability gap, local to the review claim.
It does not block the already completed diagnostic draft trial. Containment:
retain the exact grade and tool evidence, qualify what was actually checked,
and leave engineering approval to the separately authorized assessment.
Disposition: record for Main's review; no silent regrade, new model call, forced
workflow, or production fix in this task.

## Errors, Human Issue and State Timeline

Times below are database UTC; add eight hours for Asia/Shanghai.

| UTC | Event | Observation |
| --- | --- | --- |
| 05:41:14 | 2 | One launch intent, no resume |
| 05:41:18 | 3 | Fresh native run starts; runtime sets raw status `running` |
| 05:49:38-39 | 94-96 | `ask_human(category=source_conflict, pause=false)` records issue `871c457f-39c1-411f-a95c-5fcb2c92b9e6`; no native interrupt |
| 05:50:26 | 98 | Native context-summary response completes, not an external answer/restart |
| 05:51:03 | 125-127 | Wrong source UUID rejected with `SOURCE_NOT_IN_PROJECT`; requested limit was also 60, but membership is the recorded error |
| 05:51:07-10 | 130-135 | Coordinator reads project status, then retries with the catalog UUID and limit 20 successfully in the same run |
| 05:56:32 | 160 | Only report result committed |
| 05:56:36 | 164-165 | Delivery selected; legacy delivery persists `needs_human` for the unresolved issue |
| 05:57:22 | 180 | Native review binds the immutable draft/preview/rules |
| 05:59:42 | 231-232 | Native satisfied, iteration 0; run finishes with raw `needs_human`, dynamically projected reviewed draft |

The human issue concerns a pending operator confirmation recorded by the agent;
it remains unresolved, with no operator response. Its engineering merits were
not evaluated. `pause=false` explicitly allowed continuing supported work.

There is one caught tool rejection, all 53 tool starts have corresponding ends,
and no model/vision/run error events. **SDK transport-attempt failures are not
fully observable here**: callbacks record the outer model call and its final
response/error, not every SDK HTTP attempt (`deep_models.py:112`, `:126`, `:135`). No Task014 persisted
launcher stdout/stderr was found under `.runs`; zero propagated errors does not
prove zero recovered SDK connection/timeouts/429s. SDK-internal retry count and
failed-attempt billing therefore remain unknown, rather than recorded as zero.

## Timing and Usage

Native start-to-finish: 05:41:18-05:59:42 UTC, **1104 seconds / 18m24s**
(13:41:18-13:59:42 Asia/Shanghai). Launch-intent-to-finish is 18m28s.
These intervals do not include a separately timed post-run export/OS shutdown.

Usage is summed once per unique successful model `run_id`; all 56 responses have
usage, no unmatched requests and no duplicate response IDs were found.

| Model/role | Responses | Input tokens | Output tokens | Total |
| --- | ---: | ---: | ---: | ---: |
| GLM coordinator, including native summary | 43 | 3,029,134 | 62,541 | 3,091,675 |
| GLM native rubric grader | 13 | 760,801 | 6,926 | 767,727 |
| GLM subtotal | 56 | 3,789,935 | 69,467 | 3,859,402 |
| Vision `deepseek-v4.1-flash` | 2 | 2,555 | 6,288 | 8,843 |
| Combined reported usage | 58 | 3,792,490 | 75,755 | 3,868,245 |

The native summary (event 98) accounts for 132,944 GLM tokens and is already in
the coordinator subtotal, not an extra call to add again. Token totals are
provider-reported usage, not a monetary bill or a failed-attempt usage estimate.

Vision requests/responses are events 47/48 and 73/74. Both returned the requested
model, `status=observed`, `finish_reason=stop`, `reused=false`, no mismatch/error.
They used source `07fe4d16-e482-4ee5-83ac-5dd2cdc1bdb6`, physical PDF pages 22
and 115, full-page images without crop (2382x1685 and 2382x1684). Reported
`image_tokens` are 990 each, 1980 total, **included in** vision input usage.
This is two bounded image observations, not whole-document OCR.

## Graph Use

A fresh graph project ID was allocated, but no `knowledge_*` tool was invoked;
the final result has `fact_ids=[]`. `knowledge_state.py:8` returns `not_used`
for empty adopted fact IDs. Thus this report did **not** demonstrate graph CRUD,
retrieval, vector search or graph-grounded adoption. Allocation of a project ID
alone is not graph use. No graph query was issued for this audit.
