# Task029 verification: claim-evidence verdict contract

2026-09-29. Stage: critical-risk validation, not accepted report automation.
User approved the complete verifier direction, paid calls and email communication.
Main implemented and ran checks; resume_assessment provided read-only architecture
advice; alignment_review independently reviewed design and implementation. Neither
reviewer called a paid model or repaired the report. postrun_review will assess the
actual public findings and saved revisions independently after native execution.

## Before real execution

The optional `claim_evidence_contract` extends the actual native response schema,
not only prose. Each selected criterion ground states the report claim/location,
observations/location, relationship, commissioned impact, needed outcome and the
grader's own blocking judgment. Honest absent locations, empty observations and
nonblocking uncertainty are allowed. Only explicit block/pass inconsistency is
additionally rejected; semantic truth, completeness and materiality are not inferred
by code. The agent still selects evidence, tools, strategy and stopping depth.

Main retained native grade invocation, coverage retry, result consistency,
finalization and revision loop. An opt-in lazy construction hook substitutes the
schema, and the existing feedback hook conveys grounds with an explicit statement
that they are unverified public judgments. Terminal handoff carries the same status
note. This introduces a pinned DeepAgents0.7.19 private-hook maintenance dependency,
not a custom runtime review sequence or another agent. Default behavior is retained.

The contract version, schema and feedback note are hashed into the fresh-fork
binding and review target. Checks precede old-approval early return; a changed
contract cannot adopt an old approval. No-flag historical bindings remain valid.
The actual system and rubric remain those of Task027; this experiment changes the
output contract plus its necessary author-feedback projection.

Architecture reviewer resume_assessment checked installed native types/extraction
and finalization behavior, including in-memory subclass preservation. It recommended
this factor over exposing the existing source-only GLM analysis tool, which would
change model/context without directly testing verdict synthesis. Main adopted this
limited design; no extra tool or mandatory analysis stage was added.

Alignment reviewer alignment_review found no material blocker or deviation from
C25/ownership/recovery boundaries in design and code. Main incorporated honest
absent/not-applicable report locators, authority-bounded needed outcomes, and the
nonblocking suggestion to attach FEEDBACK_NOTE to terminal handoff. The reviewer
read code/test logic but did not execute tests. This is development review, not a
runtime approval or report-quality endorsement.

## Deterministic evidence and disposition

- 65 related regressions passed in19.17s, covering contract tests (then10), native
  review feedback/context/calibration/rubric/prompt and compact tables. One expected
  beta RubricMiddleware warning. No model calls.
- Added terminal-handoff and approval-early-return regression coverage:12 contract
  tests passed in3.27s. After the terminal feedback-status note, the same12 passed
  in2.67s. These overlap the65 and must not be summed to77 distinct tests.
- Scripted native grading/revision/regrading tests exercise the registered tool
  schema, persistence/reconciliation, actual author feedback and lazy construction;
  they do not prove autonomous content quality.
- **P3-029-T01**, fixed: the first schema test incorrectly assumed bind_tools items
  were dictionaries; actual LangChain values were StructuredTool instances. The
  inspection now uses convert_to_openai_tool. No production behavior or paid result
  was affected. It blocked that test's verification until corrected, not execution
  under the already-valid runtime contract. Main owned and fixed it before calls.

## Prepared native observation

One fresh original Task016 pre-review fork in `.runs/task029/native-contract`:
import attempt `ac8579b6-569f-4bbd-831a-d93364154232`, grading run
`5479d48c-299c-4346-85d5-eba659e79641`, original draft
`cf1be9a3-756b-44a6-983c-0d85520906cc`, normalized body SHA256
`7e86b61aa246f5f6b08ecd60c546a95c67cf88f9929f41462285c5c5eddea28d`.
Preparation copied verified input/OCR and own results with provenance;1617 blocks,
4 results, zero model calls/new OCR/graph dependencies/manual feedback. Baseline
hashes were preserved. Opaque checkpoint handling was mechanical preparation;
development audit uses only public events/messages and saved results.

Next freeze code/system/schema/model configuration, then run the full native path
once. Grader deepseek-v4.1-flash and author glm-5.3 retain prior parameters. Use
artifact/grounded/calibrated/compact inputs and opt-in claim-evidence contract.
Task027 is the existing same-system/compact native control, not a paired identical
tool trace. Preserve all findings and failed calls. Inspect actual grounds,
commission scope, saved repairs, residual/new errors and exact final version binding.

No paid Task029 result is claimed by this preparation record. If useful native
repair appears, apply the predeclared unseen-case and unchanged-repeat checks before
claiming reproducibility. Otherwise retain the failed observation and select an
informative next factor. No automatic promotion or engineering sign-off.

Task028's complete mixed result and this next design were emailed to the verified
user in the existing thread; Gmail receipt `1a0eabd16078a36c`, thread
`1a0e8337bc8d5abd`. Ignored audit folders retain full inputs, outputs and receipts;
versioned records avoid committing private source/report material.

## Frozen start and actual first request

Committed implementation `ac4ad42e51765d69f537e4c72d687e8911f8fc5f`;
30 runtime/rule/launcher files frozen before the paid call. Preflight verified
all baseline/source/code hashes, unchanged four original results and no new result.
Selected configuration was durably bound before launch. Contract identity:
`claim-evidence-v1`, SHA256
`18656e4068f26338a426cd9a2810aaca10358539b43cbe6ebe6f285251749b8e`.
Schema and converted GraderResponse tool definition are retained in
`.analysis/task029/frozen-settings.json`; no HTTP capture is claimed.

Actual first public grader request:system3343 characters, human6030 characters;
raw system SHA256
`85caa16ad32d6ba3a8c772564ffc36a2e73e3e711594e9e0018ec37c71979476`,
matching the freeze and Task027 exactly. Rubric raw SHA256 remains
`b63e7620378e6648fa9882db5c69e978a9744e0a5c095c1db0642792abc70ca5`.
This proves system delivery, not instruction compliance or complete source coverage.
Native execution is underway; no preliminary verdict is counted as completion.

User email `1a0eaa3540d84f2a` asked for the next-step reasoning. Main replied in the
same verified thread with rationale, actual scope and gain/regression criteria;
sent receipt `1a0eac6ad38c127d`. No source attachments or credentials were emailed.

## First public verdict and saved revision (final regrade pending)

The first actual GraderResponse (public event681) is needs_revision: Human authority
fails, four other criteria pass, and all five contain grounds (counts1/2/3/2/1).
The real coordinator receives the16,625-character native feedback message with all
ground fields and FEEDBACK_NOTE intact. This establishes actual schema/feedback
use, beyond a recorded feature flag. No schema repair was needed for this response.

The author saved/selected `e1616261-f23b-44d0-8550-0857ca25f0b9`, body SHA256
`134f69ea2d156cb70bea238be08095fd50826b6c7c632978300e26a3d902fda7`.
Independent postrun_review checked the actual body/diff/source observations in
`029-native-review.md`. The N01 fieldwork contradiction is substantially corrected;
X21 moved into its stated band and exact recomputation yields52.6 consistently.
The other five original totals remain correct. Original F01/F03/F02 remain.

Main adopts the independent disposition: P2-N01 wrong40-plate source confirmation,
P2-N02 inadequate materiality/overbroad positive criteria; P3-N03 weak team-status
inference, P3-N04 incorrect52.7 illustration (not propagated), P3-N09 overstated
claim that a particular original cell explicitly cites3.1.2(2), which it does not.
The corrected review wording and its history are preserved. Saved new P2-N05/06/07
cover unsupported team formation, stronger negative-design/exclusion assertions,
and unsupported equivalence of source stability terms; P3-N08 limits the claim
that choosing the lower end of a risk band is inherently conservative. None is
injected into the application. They block claiming a reliable accepted report,
not completion of this isolated regrade or accurately marked draft review.

This is useful local saved gain with regressions, not Task029 acceptance. It meets
the predeclared condition for the three new scoped controls and one unchanged fresh
native repeat; the repeat is not a retry to discard an unfavorable first result.
Paid calls remain serial. The existing frozen runtime stays unchanged while live.
Progress/limitations were emailed, receipt `1a0eada7c1c9c8a7`.

## Subsequent observation preparation

resume_assessment prepared three new synthetic compilation controls with correct,
incorrect and honest-uncertain content; postrun_review independently read all
assignments, nine sources, full candidates and labels. See029-heldout-review.md.
Input SHA256 `8ee0a6b3e2f9253ea7632884a4c038f93b155167f8137651993246f806ccca17`;
reference SHA256 `caed5d5b410605ae1aca14edc3dfd2312528f3ba617224e1e6a2aed6e19632fb`.
The expected judgments are separate and unavailable to the runtime. No model call
or quality pass is implied. Before execution, expose/check the intended actual
schema in the existing diagnostic; its current older arm is not Task029 evidence.

Repeat preparation in `.runs/task029/native-contract-repeat` has zero model calls,
no graph/new OCR/manual feedback. Import `294b0df3-a4d2-4dc1-b49e-a2a9013b8bc6`,
grading run `b81b3d90-db7b-449b-8507-087046714da8`, identical original body. System,
schema, rubric, configuration and all30 runtime files match the first frozen run.
Source/baseline hashes and original results pass preflight. Config/contract are bound.

**P3-029-T02**, fixed before repeat calls: the ignored repeat freeze helper used a
Windows-relative path literally under WSL and failed to find the code file. Main
normalized only the recorded path separators, then every original code hash passed.
The failure occurred before configuration/model invocation and did not modify the
live first run or invalidate its frozen code. It blocked that repeat precheck until
corrected, not the isolated running experiment. No paid retry resulted.

## Completed first run and explicit user pause

First native run subsequently completed (exit0) with final event885 satisfied and
one saved revision. Total usage including the separate vision tool is91 responses /
8,509,127 tokens. Postrun independent review records partial valid repairs plus
remaining/new defects, not reliable whole-report acceptance. In particular the
grader autonomously observed the original image, correctly recognized6 plates
versus the unchanged40 in the report, and still waived the error because it did
not change F/grade. This is recognition followed by unjustified acceptance.
Main adopts P2-N10/N11 and the independent arithmetic correction P3-N12; see
029-native-review.md. Keep positive repairs and adverse findings together.

The stored report_status field remained unreviewed_draft, while the application's
project_state/delivery_state projection uses the native satisfied verdict and
reports reviewed_draft. These are distinct fields, not a missing native verdict.
Neither projected status nor the recorded all-pass establishes engineering quality.

The repeat began but was stopped on the user's explicit responsibility-design
pause. It has26 recorded responses /1,118,221 reported tokens, no saved revision,
no final verdict, and possible unobserved in-flight usage. Process termination was
checked; do not treat its stale running field as an active process or completed
assessment. All model work remains paused. The unused held-out runner/tests are
preserved in `.analysis/task029/suspended/`; no paid held-out execution occurred.
Task030 follows the newly confirmed requirement-derived acceptance responsibility.
Emails: quality assessment1a0eaf02612ae2ba; criteria-owner proposal1a0eafaed53dab71.
