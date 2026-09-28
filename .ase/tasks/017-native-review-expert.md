# Task017: effective native report reviewer and isolated review continuation

2026-09-28. User authorizes implementation and one real verification, preferably
starting at review; only if technically infeasible, run from the beginning while
reusing verified OCR. User also requests Git management. Email and mail monitoring
remain paused; report only in chat. No legacy application writes or deployment.

Outcome: the existing DeepAgents native grader uses our report-review expertise,
evidence tools and judgment boundaries, and native feedback can cause autonomous
revision. Stage: end-to-end trunk gap closure / incremental integration. Task016
proves execution and retrieval mechanics, not report-quality acceptance (G2 open).
Expected gain is consequential evidence-grounded review with native revision;
do not claim quality improvement from unit counts or a prompt change alone.

Confirmed P2-017-01: the runtime grader used the generic framework prompt because
native_review omitted system_prompt; the specialist reviewer was a different,
optional delegated entry point. This blocks claims that specialist review was
effective, not this isolated test. Main owns the fix and verification this task.
Task016 findings stay in historical verification and are not runtime hints.

Plan and boundaries:
1. Preserve baseline in Git and inspect review-start isolation with no paid calls.
2. Supply one role prompt to native RubricMiddleware, retaining its structured
   response and conservative evidence contract. Remove duplicate reviewer choice
   from the active native-review harness; retain historical compatibility only
   where required for old harness/checkpoint tests. Do not add a review engine,
   mandatory second reviewer, fixed tool sequence or source-specific answers.
3. Bind prompt configuration to review provenance so old acceptance is not silently
   interpreted as assessment by the new reviewer. Keep read-only evidence tools.
4. Prove actual native prompt/tool exposure and feedback/revision behavior offline;
   independently review material design and final patch before the paid invocation.
5. Isolate a continuation using existing source/OCR and saved report, retaining
   provenance, upstream ownership and original Task016 bytes. No developer defect
   lists, human reference report or hand-authored repairs enter the agent context.
   Following the user's graph question, do not clone or enable a graph for this
   trial. All four Task016 results have empty fact_ids; the draft adopts three
   saved purpose results. Disable graph tools/connections with trusted project
   configuration; reject a fork with graph dependencies instead of dropping them.
6. Run once with existing GLM5.3/high and configured optional vision, then assess
   evidence, feedback, revisions, persisted/exported outcome and usage. No blind
   retries, manual answers or in-flight runtime edits. Pause evidence is a result.

Main handles architecture, implementation, tests and integration. Read-only
resume_assessment maps recovery; independent alignment-reviewer checks actual
prompts, tools and controls (development review only). Separate independent
post-run content review from the runtime review, without injecting its findings.

Local .ase has no README/team/workflow files; use existing principles/roles and
the neighboring project's read-only delivery/development-lifecycle/bugfix/feature
instructions rather than overwrite or bootstrap an entire framework this task.

Acceptance: effective specialist prompt and one active native review entry;
native decision/feedback/revision mechanics intact; no upstream permission or
historical data regression; one inspectable real run. Content gain and remaining
limits are assessed separately; no engineering sign-off or automatic promotion.
