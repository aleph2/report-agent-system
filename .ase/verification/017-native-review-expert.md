# Task017 native reviewer verification

2026-09-28. Main implemented the reviewer prompt and runtime wiring and performs
testing/integration. resume_assessment is an independent read-only recovery mapper;
review_fork implements only the isolated preparation script/tests. alignment_review
is the independent development alignment reviewer, not an application runtime role.

Git baseline 4229e51 preserves the existing independent application through Task016.
Branch codex/native-review-expert. Local author menglinsun <menglinsun@hotmail.com>
as requested. .runs, .analysis, databases, credentials and private key files are
ignored. No remote push or legacy repository write.

## Initial implementation and verification

- Native reviewer system prompt = versioned report-reviewer.md + the installed
  DeepAgents 0.7.19 GRADER_SYSTEM_PROMPT, unmodified. Native rubric remains unchanged.
- Active rubric harness excludes delegated reviewer; old no-rubric harness tests
  retain compatibility. No new workflow engine or runtime approval gate.
- Per-target reviewer_prompt_hash and active hash distinguish historical generic
  reviews from the new reviewer; old evidence is retained rather than relabeled.
- OpenAI official prompting docs consulted at the user's request; design/source
  mapping and transfer limitations are in ../knowledge/prompt-design-017.md.
- Focused tests: 20 passed in 44.52s (test_reviewer_prompt017.py,
  test_review_feedback.py, test_evidence_tools016.py). Actual native graph tests
  observe effective SystemMessage, evidence tool schemas, absent duplicate entry,
  version-bound review state and feedback/revision/terminal behavior. No network.
- Independent initial alignment review: no identified P0-P3 deviation. Source
  ownership and read-only evidence tool filtering retained. Recovery patch and
  real-run outcome still need evidence; offline results prove mechanics only.

## Review-start feasibility

Read-only baseline inspection found Task016 root checkpoint
1f1bb22a-e92f-64bd-8073-7505502d17b7 at step115, pending
FeedbackRubric.after_agent, before the generic grader. A SQLite in-memory fork and
public LangGraph aupdate_state preserved all 76 messages and produced only the
pending native review node with a new grading_run_id, zero iterations/evaluations,
no cached task result, and zero model calls. Task016's existing graph contains
9 facts, 12 receipts and 3 relationships. Initial namespace-clone proposal was
withdrawn after the user's graph question: all four saved results have fact_ids=[],
and the report adopts the three purpose results by result ID. This continuation
disables graph tools and connections; the original namespace stays untouched.
Confirmed C09 permits Graph or an equivalent sharing mechanism, not mandatory
graph use. No graph cloning or source/result dependency deletion is needed.

This is a continuation experiment, not a clean end-to-end run or a held-out prompt
evaluation. The exact old report and autonomous upstream products may be reused;
development findings and human answer-bearing feedback are not runtime inputs.

Full suite before graph-disable change: 596 passed, 9 skipped, 2 warnings in
219.90s. Skips are not passes; warnings concern historical ADK experimental schema
and native RubricMiddleware beta. Graph-disable targeted regression: 20 passed in
18.49s (reviewer prompt, knowledge state and fact runtime). An initial P2 helper
compatibility regression treated the lightweight test workspace without a Store as
a graph error; Main preserved the pre-existing injected-knowledge helper interface
with the same store-presence check used by delivery_state. The two failures were
reproduced then passed; no real-run data was affected. It blocked that regression
check only, and is fixed in this iteration.

Isolated fork validation: 9 passed in 32.45s, including native grader-first revision
and committed-WAL preservation. Independent final code alignment review complete;
see 017-alignment.md. Python compileall and git diff --check passed.
Configuration preflight confirms glm-5.3, deepseek-v4.1-flash, tracing disabled;
credentials never printed.

## Isolated real continuation

Implementation commit a88f304. Preparation exited 0 into
.runs/task017/review-continuation with import-receipt.json and code-freeze.json.
New checkpoint 1f1bb2b9-c5b5-6005-8074-5e3d5c4a5f3f; new grading run
2b44e9e7-05e0-4a00-b493-a3bd4cd3b7fc. Only pending node
FeedbackRubric.after_agent; 76 original messages, 4 original results and 1617
frozen OCR/source blocks. Original draft hash 7e86b61aa246f5f6b08ecd60c546a95c67cf88f9929f41462285c5c5eddea28d.
No graph clone, no active graph namespace, knowledge_enabled=false, no added human
feedback, no model/OCR call during preparation. Fresh preview is bound by grader.
All original files in preparation receipt remained byte-identical. Historical
events through sequence518 are excluded from this run's usage counts.

One launcher invocation started 2026-09-28 11:00:19 UTC. First new model request
is rubric_grader; no coordinator generation precedes review. Initial ordinary
trace shows report/export reads and source-scoped retrieval. No in-flight edits,
developer hints, manual source decisions, report repair or duplicate startup.
Post-run outcome and independent content assessment: pending.

Independent readiness observation by resume_assessment at 11:02:04 UTC:
all 22 Task016 files listed in receipt still match; both manifests match; ten
original files (including scope) match; all 1617 OCR rows and four saved results
match exactly. All result fact_ids are empty. JSON receipt equals persisted receipt.
No graph binding, operator decision or feedback/human_decision/development_feedback
event. Event521 records native resume, event522 binds new grading identity to the
original report and new prompt, event523 at 11:00:32 is the first new model request
(rubric_grader). Exactly one new run start/attempt. Reviewer accessed no checkpoint
messages, models, credentials or graph; baseline SQLite only via temporary copy.

## Completed run and actual effect

11:00:19-11:03:18 UTC, 179 seconds. Launcher exited0 with projected
reviewed_draft; raw report_status=needs_attention is legacy bookkeeping, not the
native verdict. Native iteration0 satisfied, five criteria passed, unverified=false.
No native needs_revision, coordinator response, delegated expert or revised result.
The original report body and all four results remain unchanged; historical known
content defects therefore remain. No quality gain or autonomous correction is
demonstrated by this run. This is a negative quality result, not a wiring failure.

- 19 new GLM grader responses, 1,086,273 prompt + 7,789 completion = 1,094,062
  tokens. All usage returned; no vision/OCR/graph requests or run failure. There
  was one recoverable read_review_export PREVIEW_INVALID_RANGE response (limit120,
  then corrected to30); the compact deep_tool_rejected event count alone missed
  this ordinary tool response. Do not interpret zero events as zero tool feedback.
- 18 evidence tool calls: project_status1, read_result2, read_review_export5,
  source-scoped search8, read_source_page2. Original arithmetic can be reused;
  no new calculate call occurred. Text/structure checks are not visual inspection.
- First actual model SystemMessage exactly matches reviewer_prompt() and receipt
  hash 266a6907c57d6586a071994ea695f483c37e3e2de284c4661ddfc0458f962e2e.
  The specialist role's actual delivery is confirmed, not merely inferred from code.
- Grader rationale treats recorded scope/source/scoring limitations as nonblocking
  and states all criteria passed. Independent content assessment must judge that
  conclusion; prior acceptance or successful execution does not settle correctness.
- Postflight: all22 original Task016 receipt files and all49 frozen implementation
  files unchanged. OCR1617 hash remains 6c094821f9b06a323fb44f9d0b0da82df0fade051a5a660403af349a1d305a00.
- New export hash4409a19229030b37c1d14819d092106592be276977e9660ffa9113d84d005f95.
  Its DOCX package differs from Task016 only in the export-time string in
  word/document.xml (knowledge validity not_used at11:03:30 instead of09:58:36).
  All other package members and document content match. Reuse Task016's37-page
  visual QA with its existing limitations; do not claim a fresh rendering or repaired
  TOC/front matter/attachments. Native pinned preview is a distinct export hash.

Evidence outside Git: .analysis/task017-postrun/trace-summary.json,
effective-prompt.json and postflight.json; immutable run data in .runs/task017.
No second trial, report repair, human feedback injection, email or monitoring restart.
Independent final content assessment and Main disposition recorded separately.

## Main disposition

The implementation and review-start experiment are complete. P2-017-01 (effective
reviewer wiring) is fixed and observed in the real SystemMessage. P2-017-02
(preparation sidecars) is fixed with offline committed-WAL/full-tree evidence and
unchanged real baseline hashes. Native controls and evidence permissions pass the
scoped development checks; none of these establish professional content quality.

P2-017-03 remains: this exact known-defect report still receives five native passes.
Impact: unsupported automatic acceptance of consequential scope/evidence/correctness
and delivery claims. The exact draft is unchanged, so Task016's P2 monitoring-column,
scope-screening, scoring-qualification and fieldwork-assertion findings and publishing
limitations persist. Independent postrun_review confirms the whole report reached
the grader and relevant source evidence was visible. This blocks claiming reliable
autonomous acceptance, full-scope engineering readiness or sign-off. It does not
invalidate the contained experiment or require deleting its evidence.

Containment: preserve original and continuation outcomes, disclose known errors,
do not promote the report as verified engineering work, and do not feed developer
answers into this completed trial. Main owns follow-up. A targeted, independently
labelled pass/fail evaluation of evidence-to-verdict judgments is the next useful
test, including unwarranted rejection; it is not executed or paid-authorized by this
record. The prompt delivery hypothesis is settled; why the model applies the rubric
too loosely remains a quality diagnosis, not a proven hidden reasoning cause.

G2 report-quality acceptance remains open; no baseline quality promotion. This one
known case differs in prompt, disabled graph capabilities and continuation context,
so neither general improvement nor a separate causal effect is established.

## User-requested actual prompt comparison

User asked whether the actual grader prompt had really changed. Main compared
the first real deep_model_request SystemMessage in both runs, using temporary
SQLite snapshots and reading only system instructions, not hidden reasoning.

| Actual request | UTC | Characters | SHA256 of encoded system prompt |
| --- | --- | --- | --- |
| Task016 event421 | 09:55:09 | 1107 | 9601cb499674cb66756a05c2b51faae30ae27f5983bf22ef366579480b0110b8 |
| Task017 event523 | 11:00:32 | 4369 | 266a6907c57d6586a071994ea695f483c37e3e2de284c4661ddfc0458f962e2e |

The new request adds3262 characters of role/judgment/tool guidance and headings.
The entire old native contract is preserved exactly inside the new system prompt.
The new actual hash equals the current assembled prompt and recorded review target.
The rubric itself is deliberately unchanged; tools retain source evidence capability
with graph disabled. Thus this test rules out unchanged/missing specialist system
instructions as the current explanation. It does not prove the model followed each
instruction or that longer prompts improve quality.

Evidence-supported diagnosis from independent 017-postrun-content.md:
the full26256-character report reached the grader in two reads. Scope/internal
fieldwork assertions and contrary limitations were visible, yet final explanation
uses the limitations as grounds for passing. That conflicts with the rubric's
disclaimer-cannot-cure-correctable-error rule. Separately, the monitoring source
table was not fetched in this run, so its miss includes an evidence-selection gap.
These are two observed failure modes, not a disclosed model thinking process or
proof of one underlying cause. Broad five-category pass output does not independently
prove each consequential claim was checked. No prompt patch or second paid run was
made while answering this diagnostic question.

Next hypothesis to test: whether explicit application of the existing limited-draft
versus correctable-contradiction distinction improves grounded verdicts on balanced
positive/negative cases. Evaluate misses and unjustified rejection, keep source facts
held out of instructions, and use the native loop. Merely increasing prompt length,
making every tool mandatory or adding another reviewer is not supported by this run.
