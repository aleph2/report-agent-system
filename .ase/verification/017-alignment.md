# Task017 independent development alignment review

Reviewer: alignment_review, independent alignment-reviewer subagent. Read-only;
Main records its returned findings and dispositions here. This is development
verification, never a runtime report-approval stage or engineering review.

Relevant confirmed decisions: C09 graph or equivalent sharing; C14/C15 effective
prompt and contract consistency; C25 autonomous goals/tools and no hidden fixed
micro-workflow; upstream producer ownership; D08 independent application and data.
The draft architecture 005 was not treated as confirmed approval.

Reviewed initial/final role and native adapter, active harness, prompt-hash
projection, graph-disable configuration, preparation script and new test design.
No identified P0-P3 principle deviation in those final paths. Specifically:

- report-reviewer.md is delivered in the actual grader SystemMessage alongside
  the exact installed DeepAgents 0.7.19 default grading contract. Rubric unchanged.
- Active report harness has one native reviewer; only the historical no-rubric
  harness retains delegated-review compatibility. Evidence choice remains with
  the grader; no mandatory visual call, exhaustive reread or source-specific answer.
- Evidence allowlist excludes report/upstream writes, delegation, human decisions
  and correction mutations. Async source vision remains available when justified.
- Old generic acceptance is retained historically but does not match new prompt
  identity. Existing native revision/terminal mechanisms remain in control.
- Per-trial graph-disable removes constructor/injected tools and prevents hidden
  freshness reads; adopted IDs remain unknown if disabled, never silently dropped.
- Native aupdate_state forks the pristine pending after_agent review boundary,
  resets grading identity/evaluation state and preserves messages/results/OCR.
  NoCallModel forbids inference during preparation. Existing graph IDs are not
  active in the isolated destination; facts are not cloned.
- New destination is required; existing baseline lock is opened read-only; source
  hashes, adopted fact-ID refusal and post-boundary read-only events are checked.

Offline isolation tests discovered P2-017-02: SQLite read-only access to a WAL
database could create baseline sidecars. Scope: preparation byte preservation,
not evidenced report/data loss. This blocked an untouched-baseline claim and real
preparation until corrected; Main accepts that disposition. Worker moved SQLite
reads/backup onto a locked temporary byte snapshot including committed WAL;
reviewer inspected the fix. Test full-tree hash comparison now verifies no added
sidecars or changed originals. Containment: only synthetic fixtures affected;
no real Task016 preparation had run. Owner review_fork/Main, fixed this iteration.

Audit helper now records knowledge_enabled as suggested by reviewer. Launcher
intent labels Task017's one authorized continuation rather than historical generic
authorization; this changes metadata only.

Evidence reported to reviewer: 596 passed/9 skipped full regression before the
graph-disable change; 20 passed targeted graph/native tests; 8 passed isolated fork
tests (30.35s), including recovered read rejection, grader-first revision, source,
feedback, fact dependency, invalid checkpoint, existing destination and live-lock
refusals. Final preparation rerun: 9 passed in 32.45s, adding committed WAL page
preservation with unchanged baseline full-tree hashes. No outstanding code
alignment defect; actual receipt and model outcome remain separate evidence.

Main disposition: accept the focused boundary review. Mechanics do not establish
GLM judgment quality, report correctness or engineering approval. Real outcome and
post-run content review remain separate evidence. No extra runtime approval gate.
