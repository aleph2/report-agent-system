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
credentials never printed. One paid invocation and post-run outcome: pending.
