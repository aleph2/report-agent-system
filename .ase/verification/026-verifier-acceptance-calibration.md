# Task026 verification: acceptance-boundary emphasis

2026-09-29. Stage: critical-risk validation of final verification on the native
review/revision trunk. Main implements/integrates; alignment_review independently
reviews design/implementation; postrun_review owns independent runtime-content
assessment and frozen cases. This is development work, not an additional runtime
reviewer or engineering sign-off.

## Current evidence and limits

The design and predeclared comparisons are in
../tasks/026-verifier-acceptance-calibration.md. The candidate states outcome and
materiality responsibilities while preserving autonomous investigation. Existing
role/rubric language already addresses correctness; this is a stronger explicit
emphasis experiment, not proof that the prior prompt lacked responsibility.

Official OpenAI guidance consulted for the design:
- https://developers.openai.com/api/docs/guides/reasoning-best-practices
- https://developers.openai.com/api/docs/guides/evaluation-best-practices

Direct goals, room for autonomous strategies, task-specific comparisons and human
calibration inform the design. These documents do not establish the performance of
DeepSeek or GLM, or prove that this paragraph will improve the report. Task025's
mixed real outcomes remain the local evidence motivating the separate factor.

## Isolated real baseline preparation

Prepared while the unchanged Task025 repeat was running, with zero model calls:
.runs/task026/native-calibrated, import attempt
fcfa6887-e5ba-4bc2-8f49-2c97431b31e0, new grading run
08015bc0-9d70-47d2-be5c-1897f8ebe129. Same Task016 pre-review boundary
1f1bb22a-e92f-64bd-8073-7505502d17b7, original cf1be9a3 report with SHA256
7e86b61aa246f5f6b08ecd60c546a95c67cf88f9929f41462285c5c5eddea28d.
Four original results and1617 source blocks preserved; no graph copy, new OCR or
manual feedback. Baseline hashes verified unchanged by preparation. The pending
native node is FeedbackRubric.after_agent; prior approval projection is cleared.

No candidate configuration has been bound and no Task026 runtime change or paid
invocation has occurred at this point. Code/prompt/labels will be frozen and actual
wire input checked before interpreting candidate outcomes. Preparation is not a
successful review, recovery experiment or report improvement.

## Implementation and independent development review

After Task025's repeat and four-case H2 batch both exited0, Main implemented the
optional calibrated_acceptance flag. Its true value is valid only with artifact
input and grounded_verdict=true. Existing two-key configurations remain untouched;
the launcher adds the key only when explicitly selected. The single frozen English
paragraph is appended to the effective system prompt. Existing locked fresh-fork
binding, resume identity, target configuration and prompt hash provide isolation;
old approvals cannot become candidate approvals. No tool, schema, author permission,
loop, model parameter or source-table change is bundled with it. The diagnostic
adds one arm and an explicitly named raw-file input hash beside its existing
newline-normalized text hash; it never reads label files.

Main ran focused offline verification:38 tests passed in24.39s across acceptance
calibration, context, effective reviewer entry, native feedback/revision behavior
and diagnostic isolation. These check implementation behavior, including invalid
configuration no-write, immutable reopen binding, exact native prompt/target,
unchanged tool schemas and old-approval invalidation. They are not quality evidence
or an actual in-flight interruption recovery experiment.

Independent alignment_review then examined the diff, task packet and test logic
read-only. It found no material alignment deviation or blocking implementation
finding: paragraph matches predeclaration, defaults/old configuration stay intact,
configuration and effective prompt bind the target, tools/schema/author loop are
unchanged, and the runner preserves alternating serial order and label separation.
It did not run tests, inspect frozen case text/labels or assess report quality.
Main accepts that scoped finding; no extra runtime gate is introduced. Its minor
documentation observation is addressed by labeling the task packet's initial
not-yet-implemented statement as historical predeclaration.
