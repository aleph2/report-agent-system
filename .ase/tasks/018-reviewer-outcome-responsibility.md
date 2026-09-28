# Task018: grader owns the assessment, chooses its strategy

2026-09-28. User reviewed the effective prompts and explicitly requested less
prescription of how to review: clarify the grader's responsibility for the result
and let it choose its own strategy. This applies to acceptance and revision
judgments, not an incentive to pass or reject more reports.

Outcome: a concise responsibility prompt and outcome-based rubric reach the actual
native grader, without another input message reintroducing a review recipe.
Stage: incremental integration of the end-to-end trunk. Task017 proves effective
prompt wiring, tool access and native loop mechanics; report-quality G2 remains
open because its real run missed consequential defects and made no revision.
Expected gain this task is alignment of the effective instructions with the user's
chosen autonomy, not an unmeasured improvement in GLM assessment quality.

Main owns design, context, implementation, focused verification and integration.
The existing independent alignment_review agent reviews the material design and
final diff under .ase/roles/alignment-reviewer.md. No runtime review stage is added.

Scope:
- Rewrite src/report_agent/rules/report-reviewer.md around reliable assessment,
  useful correction feedback, autonomous strategy and read-only/human boundaries.
- Retain the five existing outcome categories in report-review.md; remove method
  prescriptions, tool-selection instructions and repeated procedural guidance.
  Keep evidence quality, correct applicability, internal consistency, honest scope
  and actual saved/exported deliverables as acceptance requirements.
- Make review.py's application observation identify the target and available
  context, without directing which tools to call. Keep its identity/hash binding.
- Preserve the installed native grading contract, response schema, permissions,
  tool implementation, model/parameters, history preparation and feedback loop.
- Reuse existing focused native prompt/feedback tests. Do not add tests that score
  prompt wording or claim a simulated verdict proves professional judgment.

Implementation is authorized. This turn does not request another paid run or a
model change; no provider call, live continuation, checkpoint rewrite or source/
report mutation is needed for the prompt change. Existing Task016/017 results and
evidence remain historical. No legacy application or knowledge-graph writes.

Relevant known defect: P2-017-R01, missed material contradictions in a completed
native assessment. It blocks quality-promotion claims and engineering reliance,
not this prompt integration. Containment remains the recorded content findings;
Main retains it as unresolved until actual outcome evidence establishes a fix.

Checks: effective SystemMessage and native contract; review-only tools and one
review entry; prompt/rubric identity invalidates mismatched prior acceptance;
existing native feedback/revision/terminal paths. Record exact checks and the
independent review disposition in verification/018-reviewer-outcome-responsibility.md.
Finish by committing the scoped change with the configured Git author and showing
the resulting prompt to the user. Distinguish changed instructions from verified
model behavior.

## Continuation after the user's correction

The user asked why work stopped after implementation. Main acknowledges that the
intended outcome includes real verification of the revised grader, and continues
with one isolated native review/revision invocation using the unchanged GLM-5.3
configuration. This supersedes the earlier implementation-only scope interpretation;
it is not a new restriction inferred from that historical paragraph.

Reuse the proven Task017 preparation path on the same pristine Task016 pre-review
checkpoint. New destination: .runs/task018/review-continuation. Preserve Task016
and Task017, sources/OCR and original results. No manual finding list or repairs
enter runtime. Grader and author choose their actions under the native loop.
Record this task's authorization accurately in launcher metadata, freeze code and
prompt identities before launch, verify actual sent prompts, then independently
assess any native feedback and revisions. Reuse valid Task017 content evidence;
do not equate a native satisfied verdict with corrected report content.

Read-only resume_assessment checks isolation/readiness. Independent postrun_review
checks actual content after completion. These are development verification roles,
not added runtime agents. Preserve meaningful failed outcomes without blind paid
retries or an automatic sequence of prompt changes and more calls.
