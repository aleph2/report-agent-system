# Task031: real pre-production criteria and acceptance trial

2026-09-29. User's "开始吧" resumes authorized paid application testing after
Task030's implementation and explicit pause. Existing authorization permits paid
models and email communication. Run one fresh isolated end-to-end observation;
do not resume Task029 or silently repeat a completed unfavorable observation.

## Outcome and controlled boundary

Use the same original commission, files and frozen OCR as the earlier full report
run Task016, imported cleanly from `.runs/task006/highway-report` into
`.runs/task031/requirement-acceptance`. No old reports, standards, known-defect
answers, reviews, human-reference report, graph state or checkpoints are inputs.
No paid OCR ingestion. Optional image observation remains an agent choice.

Freeze code, prompts, response schema, source/OCR hashes and configured parameters.
Use the unchanged full-run default GLM5.3/high for coordinator, author, text tools
and native grader; optional image observations use DeepSeek v4.1 flash. This is
the Task016 full-run model selection, not Task029's grader-only DeepSeek override
(which is bound to a historical review-fork protocol). Record that difference;
Task029 is diagnostic context, not a controlled single-factor comparator.

The new mode makes the coordinator define standards before production, share them
with the author and grader, and autonomously select execution/revision actions.
Main does not author acceptance criteria, repair the report or inject known answers.
Keep runtime files frozen during execution. Genuine human decisions remain human;
do not invent operator responses or auto-resume such an interrupt.

## What counts as evidence

- Criteria exist before first draft/delegated production; requirement provenance,
  coverage and allowed limitations are substantively appropriate, not merely valid JSON.
- Author/grader actually receive and adopt the same version; model-call public I/O,
  tools/observations, schema and configuration are inspectable. Audit is not private
  reasoning or a full HTTP capture. Count all model and vision usage without duplication.
- Compare saved report defects, correct observations, acceptance judgments, effective
  repairs and regressions. Do not count more rejections, more calls or a satisfied
  flag as improvement by themselves. Original-source uncertainty stays distinct.
- Inspect full saved report and exact selected export, and distinguish source access,
  checks actually observed, general capability and coverage claims.
- Recheck original/source/OCR and frozen-code hashes; preserve baseline outcomes.

Main runs and audits. postrun_review independently assesses actual criteria and
report/verdict evidence without influencing runtime. Reuse Task030 independent
alignment and128 offline regressions; no changed application code is planned.
Stage remains critical-risk validation. A single run can expose mechanisms and
failures; it cannot establish general reliability, causality or engineering approval.

For execution failure, diagnose local/public evidence before any recovery; no blind
paid replay. No cumulative token/call quota is introduced. Report meaningful progress
and final result by email, including honest incompletion/unknown usage if interrupted.
