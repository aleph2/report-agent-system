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
