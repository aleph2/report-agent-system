# Task025 verification record

2026-09-29. Main implements and runs experiments. Independent alignment_review
reviews design/implementation; postrun_review independently prepared four new
synthetic hold-out inputs and labels and will assess public outputs. This is the
project's development team, not a new runtime agent roster.

Authorization: direct chat agreed to the two separately tested factors, then the
whole Task024 approach. Existing paid-model/email authorization persists. A verified
reply also requested continuation. Initial experiment email was sent in the existing
thread (receipt saved under `.analysis/task025/`). No legacy mutation/graph migration.

## Frozen plan before paid results

- H1 initial screen: four new synthetic cases, each once in transcript and artifact
  modes; alternate arm order by case index. Same deepseek-v4.1-flash/high parameters,
  original system/rubric/schema and identical read-only evidence/context tools.
  Eight planned grading sessions; repeat a discriminating gain before attributing
  reliability. If both arms easily pass, say these cases do not discriminate rather
  than multiplying identical easy runs. No global accuracy claim from this screen.
- Inputs supplied to the model contain no labels. Frozen inputs SHA256
  c398b88af2b174c82c62c6fd7b0d481176c7d492f06483c2b627176fe633605a;
  independent labels SHA256
  e4978cc177cdd26771964c407cd4e08c7b69841d44ed6980a18161585b102be0.
  Cases b3e72a91c640,4f86c2a09db1,a9c17d5e8034,6d02fb83a157 cover valid compilation,
  material unit error, contradictory activity completion and properly disclosed
  source conflict. All are explicitly synthetic, with identical author assertions
  and no actual human-feedback entries. Labels/notes are not tool-accessible.
- Real development regression: fresh copies of the same Task016 pre-review boundary
  1f1bb22a-e92f-64bd-8073-7505502d17b7, report body SHA256
  7e86b61aa246f5f6b08ecd60c546a95c67cf88f9929f41462285c5c5eddea28d.
  Run current controlled transcript arm, then artifact arm with ordinary native
  feedback/author/re-review enabled. This known report is not a held-out case.
- H2 separately adds concise public verdict-grounding requirements. It keeps the
  native GraderResponse and status meanings unchanged. Compare against the same H1
  mode; do not claim pure schema effects. Additional runtime/state changes or H3
  presentation work require their own recorded factor and verification.

A declared number of cases is experimental design, not a cumulative usage cap.
All observed response usage is recorded. Execution errors require diagnosis before
replay. General quality acceptance needs real corrected saved reports and preserved
valid content, not synthetic success, tool activity, or a top-level verdict.

## Design review and implementation checks

Independent alignment_review found no inherent design blocker. It specifically
required frozen per-attempt context, full paginated access beyond native 4000/30
excerpt limits, distinction between framework HumanMessages and operator decisions,
allowlisted public history, server-bound access and immutable experimental identity.
Main implemented those as context snapshots/target hashes, explicit section paging,
source metadata, no additional_kwargs serialization, fixed workspace closure and
fresh-fork/resume guards. Detailed implementation review completed; dispositions
and final scoped checks are recorded below.

Current changes are opt-in and do not replace the production default. Two controlled
arms both add the same context tool, so H1 cannot be attributed directly to the
historical Task023 runtime, which did not have that tool. H1 changes default input
organization/wording/length together, not a proven isolated internal anchoring cause.

The first focused round passed27 tests (21.35s) after correcting an incomplete test
fixture's missing resolved field. No model calls occurred. Broader relevant runtime,
import, feedback, model and diagnostic regressions are in progress. Passing these
tests establishes mechanics only. P2-023-R01 remains open.

Broader regressions:66 passed in57.15s. Independent implementation review found two
contained issues, both accepted and corrected by Main before paid execution:

- P2-025-A01: configuring a fresh fork outside its project lock could race startup
  before target creation. This blocked the runtime-immutability claim, not serial
  isolated diagnosis. Configuration now locks its whole validation/write operation;
  PROJECT_ALREADY_RUNNING leaves both configuration and binding unchanged. Resolved.
- P3-025-A02: public history omitted legal string entries inside content lists. This
  limited the completeness claim for that representation, with no demonstrated
  effect on current plain-string trials. Strings are now retained in order while
  nonpublic reasoning blocks remain excluded. Resolved.

The reviewer also noted the original tests covered same-instance retries only.
Main added new Workspace/middleware reconstruction against the same run/iteration,
plus changed-feedback rejection preserving old target/snapshot. All7 context tests
pass in2.62s after these final scoped edits. This is offline identity/reconstruction
evidence, not a completed real in-flight process interruption and recovery trial.
Actual prior native feedback is retained separately in assignment with its framework
provenance, rather than mislabeled as an operator decision. Default production
behavior, ownership and original role/rubric/schema remain unchanged.

Two real continuations are prepared at `.runs/task025/native-transcript` and
`native-artifact`, with1617source blocks and4original results, graph disabled, no
new OCR, no prior review projection, same pre-review parent and unchanged baseline
hashes. Public import receipts identify different isolated run IDs; no models were
invoked by preparation. Both use the same added context tool in the actual contrast.

## H1 completed synthetic comparison

All eight planned sessions completed, with68 observed model responses and548943
tokens (transcript33/269980; artifact35/278963), with no execution errors or missing
response usage. Independent full-content scoring is in025-holdout-review.md. Both
arms correctly accepted the two eligible cases and rejected the two material-error
cases. Actual requests, source returns and verdict grounds were checked, not only
labels. All eight system hashes match the frozen settings. Input/label hashes did
not change. These four small synthetic cases do not discriminate the main verdict
ability of the two arms; they do not establish general or engineering accuracy.

Main accepts the independent findings and keeps them open:

- P2-025-H1-01: transcript's packaging feedback permits leaving a determinate,
  correctable error unresolved. Correct core detection remains valid. No writer
  acted on this nested diagnostic; it blocks a reliable-correction claim, not
  continuing the isolated experiments. Disposition: assess feedback and actual
  saved revisions separately; do not feed the independent answer into the model.
- P3-025-H1-02: transcript's scan feedback infers an unsupported approval status.
  The unexecuted-work contradiction is valid. Disposition: track this unsupported
  addition and ensure future saved changes are not accepted merely because the
  core verdict was correct. It does not justify stopping this iteration.

The two feedback differences are single observations, not a causal or stable
advantage for artifact mode. The labels remain independent of model context.

## H1 real native comparison in progress

Code was frozen at9b2b73e in both prepared forks. Transcript control completed:
22 grader responses,1710522 tokens, no missing response usage, iteration0 satisfied
on all5 criteria. Four original saved results remain unchanged; no author revision
occurred. Public postflight checks preserve baseline files, sources and29 frozen
code files. Its broad positive explanation is not accepted as proof of report
correctness. Independent content/evidence review is underway. Artifact continuation
started only after the control finished, with the same model/rules/tools and fresh
original checkpoint. Its result is still pending; no quality gain is claimed.

## Predeclared H2 follow-up

Before the H1 artifact verdict is available, Main declares one fresh real native
artifact+grounded continuation as the next diagnostic, compared with artifact's
unchanged-role result. Use the GROUNDING_INSTRUCTION already frozen at9b2b73e,
same sources/checkpoint/model/tools/rubric/schema and ordinary author feedback loop.
No H1 output, independent finding or label enters this new workspace. This tests
the incremental public-grounding requirement, not a new model or output schema.

Run serially after H1 finishes. If a valid gain appears, repeat the discriminating
condition and replay the four frozen synthetic cases under artifact_grounded for
non-regression and false-rejection checks. If it again produces only unsupported
global acceptance, retain that failure and revise the next hypothesis rather than
multiply nondiscriminating small-case calls. This is a declared information-value
branch, not a new spending cap or a quality pass. Native runtime errors are diagnosed
before any replay; existing authorization remains in force.

## Interim public observations, not final candidate acceptance

Independent review025-native-review.md confirms P2-025-N01: transcript's full
acceptance leaves F01/F02/F03/N01/X21 unchanged despite complete body access.
Main accepts the finding and its scope: blocks quality promotion and treating
disputed inputs as established, does not block this isolated paired continuation.
Containment remains explicit failure records and no automatic engineering sign-off;
Main owns the next diagnosis and the report producer owns any actual revision.

While artifact is still running, its first public GraderResponse requests revision
for omitted candidate slopes and contradictory inclusion rules (related to F02).
Author/coordinator responses have begun. This is a change in observed feedback,
not yet a verified correction or a causal quality claim. Complete native execution
and independent content checking remain necessary. No in-flight intervention or
developer findings have been supplied to the author or grader.
