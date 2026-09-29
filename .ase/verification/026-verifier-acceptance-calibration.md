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

## Frozen candidate and first paired execution

Implementation commit95d6781, author menglinsun <menglinsun@hotmail.com>. Runtime/
rules/launchers are frozen across29 files for the upcoming native candidate.
Strict case validation and all three input/label/note raw hashes match the earlier
independent freeze; Main has not read their content/labels. Control system raw
SHA2569fc8bbdf0d34697901c5a0dc1253a0acbd974581e3d2c2419b2734b9c661bbd0
is byte-identical to Task025 H2; candidate system raw SHA256
85caa16ad32d6ba3a8c772564ffc36a2e73e3e711594e9e0018ec37c71979476.
Complete prompts/settings are saved under.analysis/task026/frozen-settings.json.

The declared six-call batch started at.runs/task026/holdout-paired. Frozen case
order638e15809d18,c1e4086f172b,2cdb1e2cc69b; first/third control→candidate,
second candidate→control. Each is one independent native nested-grader invocation,
serially, with no outer author revision loop. Outcome remains pending here. Native
real-trunk execution will follow from the prepared original baseline, not from a
synthetic case or a Task025 revised report.

Milestone email sent in the established thread, message1a0ea6dc7e158dd3, containing
the exact candidate paragraph, unchanged model/settings, completed Task025 result
limits, implementation/test evidence and paired/native next steps. It does not
claim either the new prompt or small controls establish real report reliability.

## First paired case: independent interim finding

For638e15809d18, both arms returnneeds_revision and correctly identify the
source-to-report hall/quantity mapping swap and its packing-use consequence.
The candidate's actual first system is3343characters, matching frozen SHA85caa16a;
the human message is4550characters. Independent review confirms both arms' actual
system/human equal their saved inputs, actual model parameters/tool schemas are
equal, and all four source contents arrived verbatim. Initial human messages differ
in run identities/nonce/context metadata and the recorded experiment flag; do not
claim literal byte equality of the full requests. Candidate export coverage60/66
includes the relevant report through conclusion/source index; control read66/66.

Main accepts P2-026-H01 as a bounded feedback defect: candidate Evidence offers
mere disclosure of a known derived mismatch while Correctness requires correction.
It blocks treating that alternative as sufficient repair guidance, not the valid
revision verdict or continuing the declared trials. Main also accepts P3-026-H02:
the challenge to the correctly scoped statement that the original inputs have no
conflicting versions is unsupported; a report transcription error does not make
its consistent original sources conflicting. This blocks deleting or falsifying
that correct source-status statement without cause. Neither defect has propagated
through an author because these calls contain no author loop. Main retains both
outcomes and producer-facing implications; no runtime feedback or label is changed.

There is no main-classification gain on this first pair; the control already found
the material error. The candidate's additional wording defects are observed facts,
not proof of their unique cause or global inferiority. The remaining acceptable
cases and actual native report/revision trial are still required by this iteration.

## Paired execution terminal; native candidate started

All six declared calls exited0,61observed responses/559699tokens, no missing usage.
The three report-level classifications are the same in both arms:638e requires
revision; c1e4 and2cdb are accepted. All six actual public request systems match the
frozen control/candidate hash. Independent review of the two acceptable cases is
still underway; six labels alone do not establish clean feedback or generalization.

Native preflight confirms all29 runtime/rule/launcher hashes, baseline file hashes
and source hashes match; four original results unchanged, no new result, no prior
model response in this fresh fork. The candidate then started serially, using
artifact+grounding+calibrated_acceptance=true and the original Task016 report.
Its first actual public system is3343characters/hash85caa16a; human5821characters.
The exact public initial messages are saved at
.analysis/task026/native-calibrated/effective-prompt.md. It remains in progress;
no report improvement or runtime acceptance is claimed here.

Parameter evidence has layers: diagnostic_invocation logs LangChain callback
parameters (max_completion_tokens=65536); the frozen DeepSeek adapter translates
that to max_tokens=65536 when constructing the HTTP payload. Diagnostic settings
record that constructed payload's non-message fields. Both arms use the same
adapter/value and tool schema. Native LocalAudit logs public messages and response
model metadata, not a complete HTTP parameter capture; its parameter evidence is
the frozen configured_model and launcher selection. No claim of hidden-reasoning
inspection or complete transport packet logging is made.

## Completed independent three-case comparison

Independent postrun_review has now checked all six outcomes and their actual
observations. Both arms' principal classifications are supported on all three
reports. The limited planning case preserves3interested/1undecided/1declined and
unresolved electricity/rain/stall conditions without claiming an event occurred;
the minor-imperfection case preserves9identities,4/3/2categories and3key points,
recognizing the duplicated heading as non-blocking. No new false rejection or
fabricated completion claim was confirmed in these four accepted calls. Their
full source contents and export blocks actually arrived. H01/H02 remain bounded
candidate-feedback defects in the first case, with no author propagation tested.

Main accepts this scoped evidence: no main-classification improvement on these
three new reports, and no observed over-rejection of their legitimate limitations
or minor imperfection. Six calls are not six independent reports and do not measure
general accuracy. Frozen files remain unchanged. The native trial is in progress;
do not substitute the paired labels for content, repair or final-acceptance evidence.
