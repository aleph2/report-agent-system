# Task006 integration evidence (in progress)

2026-09-27. Main implements native runtime/model integration and observes paid trials.
Rawls implements shared knowledge, Gauss removes semantic gates and updates desktop UI,
Ptolemy tests native execution, Chandrasekhar verifies and imports source/OCR inputs.
Anscombe is the independent alignment reviewer. This is not a completion certificate.

## Early review disposition

- P2 semantic outcome gates: confirmed, Gauss removed required purpose/plan/materials
  chain while retaining producer permissions and exact-version final review.
- P2 observations as dependencies: confirmed, Gauss separates observation audit from
  adopted references. Producer impact assessments preserve unchanged content with a
  version snapshot. Gauss reports 141 tests passed before runtime replacement.
- General-purpose delegation, native checkpoint recovery, serial task execution and
  authorized model use require actual trace evidence, not design statements.

## Installed runtime

DeepAgents 0.7.19, LangGraph 1.2.12, langgraph-checkpoint-sqlite 3.1.1,
langchain-openai 1.6.6, Neo4j driver 6.3.1. Independent virtual environment;
old ADK modules remain historical test evidence, not the default report entrypoint.
Separate Neo4j container report-agent-knowledge006, localhost 17474/17687,
separate named volume. No legacy service/config/data writes.

## Live synthetic trial A

Evidence: `.runs/task006/synthetic-reuse`, GLM5.3/high, existing synthetic access note.
No engineering source or new OCR. Credential values read only into process memory
from three authorized legacy service metadata fields; no credential file copied.

- 12 completed model requests before interruption, 70,308 provider-reported total
  tokens (not a cost claim); all responses included usage. No total quota imposed.
- Model attempted direct composition, then delegated writer after a rejected submit.
- P2 API contract bug: submit_result accepted a free string kind without exposing
  enum/role values; model supplied `report` instead of `draft`. Fixed by explicit
  outcome enum and capability-specific tool description. No validation relaxed.
- P1 runtime integration candidate: child ask_human writes an interrupt checkpoint
  but invocation does not return. No model request remains in flight. Blocked action:
  accept native human-pause recovery or deploy the new report runner as verified.
  Containment: isolated synthetic project; keep checkpoints and inspect stacks.
  Main/Ptolemy investigate; no blind repeated paid request and no legacy impact.

Related upstream evidence (not yet proven to be this failure's cause):
https://github.com/langchain-ai/langgraph/issues/7857 documents synchronous writes
on AsyncSqliteSaver's own event loop causing a deadlock. Installed source confirms
get_tuple has a guard while put/put_writes use a synchronous future bridge.
Framework reference: https://reference.langchain.com/python/deepagents/graph/create_deep_agent

## Source reuse

Chandrasekhar independently matched nine original-file hashes and frozen extracted
text hashes, plus the scope statement. 1,530 PDF pages: 977 native and 553 previously
OCRed pages. Reuse does not prove OCR numeric/diagram fidelity. The outline DOCX
contains four media files and one header/footer part not represented in its 470-character frozen plain text;
mark this as unparsed input, not user missing data. Do not import old derived plans.

## Confirmed native runtime repair

The interrupt hang was Main's `max_concurrency=1` configuration, not the candidate
upstream synchronous SQLite bug. The native background executor used that limit
for dependent checkpoint writes. Removing only this setting let the same offline
child-interrupt test return. Business tool/delegation serialization stays in the
boundary middleware. P1 resolved: native interrupted/resumed child tests pass,
including restart and no duplicate result commit. Preserve trial A as failed evidence.

## Live synthetic trial B

`.runs/task006/synthetic-reuse-fixed`: 13 GLM5.3/high requests/responses, 85,617
provider-reported total tokens, all with usage. About 46 seconds, reviewed_draft.
Actual path: read existing materials and sources, root writes draft, native reviewer
reads exact draft and both sources, review saved, root selects delivery. No forced
purpose/plan/knowledge/writer chain. Independent reviewer confirmed isolated reviewer
context and exact-version target from actual trace, not merely the declared topology.
Draft 12511f0b-0015-4068-be6c-96fa415273b1; review 3c74c341-3dd0-4b34-9475-d7b60af47ad0.
DOCX exported locally. Visual rendering not yet verified: local renderer could not
find LibreOffice. This is a model-reviewed synthetic draft, not engineering sign-off.

Follow-up: Ptolemy located existing Windows LibreOffice (PATH discovery was the
problem), rendered and inspected both pages. All 29 paragraphs retained, no visible
truncation/overlap, input hash unchanged. See 006-export-visual.md; this is not CJK
or real-report layout acceptance.

Focused regression after entrypoint repair: 43 passed; one historical ADK warning.
Shared graph worker reports 22/22 actual integration checks including local 384-D
embeddings, Chinese semantic retrieval, traversal, ownership and project isolation.
Import worker: 6 tests, 9 originals plus scope, 1,617 located blocks; zero new OCR calls.

## Real source trunk (in progress)

Started 2026-09-27 15:02 UTC in `.runs/task006/highway-report`, isolated GLM5.3/high.
Scope statement is the operator goal, nine frozen parsed sources with originals and
locators. No legacy derived plans/reports imported, no new OCR. Independent Neo4j.
Desktop server on localhost:18140 now serves this project; the previous offline
fixture server was idle and stopped. Original highway service 18082 is untouched.
Current process started before the later receipt/fact-provenance patches; do not
claim those later changes were hot-applied. No in-flight model cancellation.

Baseline regression after explicit graph adoption: 209 passed, 9 graph tests skipped
in the no-service suite. Separate real Neo4j/local embedding suite: 30 passed.
Desktop synthetic page verified in browser: actual activity, exact delivery IDs,
read-only literal source search; no console errors or artificial progress percentage.
Additional worker-loss GUI projection tests: 9 passed; native/cross-layer receipt,
source-impact and unknown-graph tests: 17 passed. Final full suite remains pending.

Full regression before role-specific submit refinement: 231 passed, 9 skipped,
one historical ADK warning. No new graph behavior in the skipped group; separate
30-test actual graph/embedding run remains applicable.

### Real-trial tool contract failure and native resume

P2: a unified submit_result exposed review-only outcome/target fields to authors.
The actual coordinator generated a ~14,700-character draft but put a prose result
summary in outcome. SQL correctly rejected review fields for a draft, with a
misleading ONLY_REVIEWER_CAN_SUBMIT_REVIEW error. Three rejected repeats followed.
The first attempt also shortened source UUIDs; its SOURCE_NOT_IN_PROJECT rejection
was valid. The framework's native error recovery fixed those IDs, not the outcome.

Main contained the known repeated submission defect with SIGINT to the isolated
trial process only; it exited 1. No successful result was present, no source/OCR
was rerun. Incomplete cancelled model output is not reported as provider failure;
its final usage is unknown. Parent native checkpoint
1f1ba863-bdb0-668e-807e-92c4525e9e26 retained 84 messages, next=tools, no human interrupt.

Fix: each role sees only its submit parameters. Draft kind remains a draft Literal;
review outcome is required accepted/changes_required and exact target is required.
Internal ownership/actor/exact-review checks remain. Schema migration ignores a
legacy draft's irrelevant prose outcome, never converts kind=review into draft or
authorizes self-review. A real ToolNode checkpoint test stores old arguments,
fails before execution, rebuilds and resumes to exactly one draft with empty
outcome/target. 18 focused native/cross-layer tests pass, including foreign-kind
rejection before side effects. Independent reviewer approved this narrow direction.

At 15:20 UTC Main resumed the original project/thread after inspecting receipts
and durable state. The child reviewer continued; original sources and root reading
history were retained. This is native resume evidence, not final-report acceptance.
Business tool rejections now receive a sanitized explicit GUI event instead of
being visually indistinguishable from successful tool returns.

### Recovery and desktop follow-up

Two technical-only issue answers were required: child reviewer confused task IDs
with result IDs, then parent cited stale pre-repair errors. Main did not approve
scoring or author report content. Role-specific tool contracts plus removal of
internal task IDs from agent observations/receipts preserve all durable evidence.
The same project/checkpoint then saved the first actual 14,968-character draft
82d9f1bc-3e02-484f-aec1-4f0855fd0d3c. Independent reviewer read this exact result.
Full report review is still in progress at this entry; see final outcome below.

233 full tests passed,9 service-dependent graph tests skipped,1 historical ADK
warning; separate30 actual graph checks remain valid.19 focused native/cross-layer
tests pass. pip check and compileall pass. UI worker reports17 static checks pass.
Main verified1440x1000 desktop in real browser: native run status/reviewer activity
and disabled duplicate-run button visible above source list; full scope retained
in initially collapsed details. No console errors. No invented percentage or ETA.
Windows launcher40220 serves actual project on18140 with latest runtime, separate
from CLI model worker. Temporary18141 synthetic server stopped. Legacy untouched.

## Actual-source outcome

2026-09-27 15:59 UTC: native run finished reviewed_draft and exported DOCX.
Selected draft166fe644-d837-4b13-965e-b428bf069b92 and exact review
e41e8b4a-8585-4097-8e5c-a6e451a855a9. Four results total: two drafts, one
changes_required review and one accepted model review. The selected draft has an
input link to the first draft, not a replaces_id edge; the model's final narrative
claim of replacement does not establish that edge. No historical result was rewritten.

A provider OpenAIConnectionError occurred after the accepted review was committed,
before delivery selection. Main inspected exact target, receipts and native checkpoint
1f1ba8ac-4fe0-6743-80cc-624ae73a00e1 (136 messages, pending tools, no human interrupt).
Authorized native resume completed delivery without duplicate committed results.
This is real transport-failure recovery evidence, not proof every provider error can
be safely retried or that partial model reasoning was recovered.

Trace totals:143 model-start callbacks,141 successful responses,1 model-error callback,
and1 earlier cancelled request with unknown final usage. Known successful-response
usage:11,650,004 prompt +187,508 completion =11,837,512 total tokens. SDK internal
attempts are not separate model-start callbacks; these counts are not billing totals.
No cumulative token/call limit was applied. No worker remains active for this real run.

The actual run chose source-only compilation; fact_ids=[] and knowledge.status=not_used.
It does NOT establish model adoption of shared graph. A separate synthetic graph-use
test follows. Source intake reused977 native-text pages and553 OCR pages, no new OCR.

Independent Chandra verified final qualifiers retained (body hash
e47e7d528efe8a2202c4a35e6f36365723496658eaf5b9607321592679cbbfe1): method, weights,
F values and grades await project-lead confirmation. Known residuals: unqualified
reliability/use-as-basis language, numerical-review inconsistency, source value/height
ambiguities, and non-final Word layout. The model accepted tag does not close these
findings. Only a pending, locally reviewable draft is delivered; no engineering sign-off.

## Final code verification

297 tests passed,9 service-dependent graph checks skipped,1 historical ADK warning
(53.68s);17 static UI tests passed. Separate30 live graph/embedding tests remain
applicable. pip check clean. Installed markdown-it-py4.0.0 is explicitly pinned;
no new model provider or OCR service added.

Final narrow adapter changes normalize only explicit identity relationships:
replaces_id is not duplicated as a live dependency; review target_id automatically
contributes its exact dependency. Original-request receipts remain first, and
ownership, observation and current-version checks remain enforced. Independent
Anscombe approved these deterministic normalizations; actual earlier candidates
are not retroactively assigned replacement edges. Tests cover original hash replay,
foreign/superseded predecessor and unobserved/non-draft review rejection.

Safe error classification now distinguishes model connection, timeout, access and
rate-limit failures without serializing provider bodies, URLs or credentials. No
new retry wrapper or changed retry policy. Export uses a proven Markdown parser to
create Word tables with repeated header rows; it does not change saved report text.

Desktop redeployed with latest code, Windows launcher28224. Actual API export was
downloaded to `.runs/task006/gui-export-final.docx`:9 Word tables, correct selected
draft/review IDs and engineering disclaimer. Browser confirms reviewed-draft label,
enabled download and no console errors. This is display/download verification,
not substantive engineering or full report-format-standard acceptance.
