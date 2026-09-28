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

Independent completed-iteration review now confirms the two missing-candidate
findings have support, while P2-025-N02 identifies a wrong implication in the same
feedback: the26m candidate cannot satisfy the cited below20m clause merely by
being potentially unstable. Main accepts this local feedback defect; it blocks
accepting that implication as established, not the isolated revision continuation.
Final saved text must be checked for propagation. In this artifact iteration,
all907 export blocks and design p97's complete automatic table actually arrived,
yet F01 and other known defects were not reported. This narrows the diagnosis:
more retrieval alone does not explain or cure these remaining misses. It does not
prove a unique attention/prompt/model cause. The producer has now saved a new
draft; its correctness and final native re-review remain pending.

## H1 native execution completed; H2 started

Artifact finished with92 observed responses (79grader,13coordinator),6766415
tokens, no missing response usage/errors. Iteration0 requested revision; two new
drafts were saved; iteration1 accepted final857eb650-96c3-4ef7-a156-f6fdeb5f9341,
raw body SHA2564b85eade0a7a1babd42a71b6f3863da721fe9e4e0807424877642bd7c7deb9b9.
The selected target/preview identify that final version. All baseline/source/code
postflight hashes match and all4 original results are unchanged. Independent final
content/revision/non-regression review is underway; native acceptance is not ours.

Both H1 native arms actually sent system SHA256
f48d315c8246f9310a0cf27cd7308d14df099715531590958a5a1901f7f861b5.
Their initial human inputs were31013 and5791characters respectively. Grader
responses reportdeepseek-v4.1-flash; artifact's author responses reportglm-5.3.
Differences in evidence chosen, reading depth and length are outcomes of this input
organization experiment, not independently held variables or proof of a unique cause.

H2 started serially after H1 exited0, using preparednative-artifact-grounded from
the same original boundary. Actual first system equals reviewer_prompt with the
frozen grounding switch true, SHA256
9fc8bbdf0d34697901c5a0dc1253a0acbd974581e3d2c2419b2734b9c661bbd0,
2741characters; human5790characters. H2 received no H1 revisions/developer findings.
It remains running; do not claim a result or improvement yet.

## Conditional H3 design advice

Independentalignment_review reviewed a possible later compact source-table view,
read-only and without inspecting in-flight author work. It supports a separate
representation experiment after H2, not a diagnosis that formatting is the root
cause. Reuse extractor, selected pages, original membership/hash checks and full
text. Preserve raw cell text/order/empty-vs-null and locators. Geometric spans must
come from complete extractor cell rectangles/grid boundaries; existing nonempty
bounds alone cannot recover empty cells, and null must not be guessed as a merge.
Do not semantically fill headers/units/values, filter drawing-frame candidates or
hardcodep97. Full raw view/source remains reachable. Prefer unchanged tool catalog;
any added parameter/tool is a separate choice-space factor. Test horizontal/vertical
and empty merges, condition/value relationships, ambiguous geometry, and an
independent unseen table. H3 has not been implemented or run in this record.

## H1 final content disposition and H2 first outcome

Independent H1 final review confirms a real F02 scope/coverage revision and
preserved six original arithmetic totals. P2-025-N02's wrong26m implication was
not adopted: the author explicitly distinguishes literal criteria from a pending
conservative extension. Main records this containment without erasing the feedback
defect. P2-025-N03 is accepted and open: newly added groundwater/design-completeness/
investigation-point scores lack the stated mapping or contradict the report's own
bands. F01/F03/N01/X21 also remain. This blocks full-quality/new-score acceptance,
not continued isolated diagnosis. Main owns follow-up; the producer owns repairs.
No global H1 superiority or quality promotion is claimed from this one pair.

H2 completed28 grader responses/2770731tokens, no missing response usage/errors,
iteration0 satisfied and no author revision. It explicitly identifies40 as the
inclinometer count and6 as settlement plates, but describes the mislabel as
non-consequential and accepts the staged report. This is new public recognition
evidence, not corrected content or reliable acceptance. The separate independent
H2 review is underway, including its additional58.05 arithmetic assertion.

To follow the predeclared discriminating-observation branch, Main will repeat H2
once from the same fresh original boundary and run the four frozen synthetic
cases once under artifact_grounded, without changing code, prompt, labels or
sources. The first outcome is retained in full; the repeat cannot replace it.
This checks whether the recognition/acceptance behavior recurs and whether the
new instruction preserves appropriate acceptance on the small controls. It does
not claim a quality gain or require acceptance of every typo. If the repeat differs,
record variability rather than selecting the better result. H3 remains conditional;
the newly exposed judgment/calibration issue may be the higher-value next factor.

Independent025-grounding-review.md now confirms H2's real F01 recognition and
accepts neither the unsupported materiality waiver nor blanket acceptance. Main
accepts P2-025-G01/G02, open: source correctness/recognition and commissioned-use
judgment must be scored separately; F02/F03/N01/X21 remain. Scope is this frozen
report/trial; no unique global cause is claimed. They block quality promotion,
not the declared repeat or controlled draft review. No repair occurred.

Main also accepts P3-025-G03: the public phrase exact58.05 is inaccurate. Exact
7024/121=58.049586... rounds directly to the original correct58.0 at one decimal.
58.05 is a possible intermediate rounded value; public evidence cannot establish
the model's calculation route. Do not turn this into a false arithmetic allegation
against the report. No writer received this as a correction in H2.

First H2's postflight/export is retained; repeat started from fresh unchanged
originals with import6c33bc52-8d59-493d-b1b1-9773b7ad59ee and grading run
9ab60931-90db-4643-aeaa-1031085d7096. Its code freeze still covers the same29files.
The completed-run usage so far is210observed responses/11796611tokens including
13author responses; the in-flight repeat is not included. No hidden reasoning was
needed for these judgments; public findings/observations and saved reports suffice.

Focused independent design advice prioritizes a later acceptance-boundary emphasis
over H3 at this point: H2 already recognized the quantity error. Task026 records the
candidate outcome paragraph, no mandatory investigation steps, and fresh independent
positive/minor-imperfection controls. This does not alter Task025's in-flight prompt
or predeclared repeat/regressions. Main has not accepted any candidate quality gain.

## H2 repeat first-iteration disposition and audit conventions

Independent review confirms a real K1318 right-side omission in the repeat's first
needs_revision verdict. Main accepts P2-025-G04: the feedback merges different
chainages/sides into one left12/right14 assertion. It blocks adopting that combined
claim as verified, not addressing the actual omission or continuing the isolated
trial. Main also accepts P3-025-G05: the proposed replacement of supported4.1.2
with4.1.5 lacks evidence. It blocks that unverified citation edit, not the trial.
Both remain open pending producer output; no developer correction is injected into
the running author. Final review will distinguish propagation from containment.
The repeat did not mention40/6 and did not receive designp97; the first H2's correct
recognition is not attributed to this repeat. Differing outcomes remain side by side.

The frozen Task025 synthetic input has raw-file SHA256
c398b88af2b174c82c62c6fd7b0d481176c7d492f06483c2b627176fe633605a.
The runner's read_text hashes universal-newline-normalized text, SHA256
0b3b952febb9eddce87cd5cfd0931001e0787b194fe0278420cfc18d807bb85f.
This CRLF normalization does not change JSON case content or labels. Keep both
hash definitions explicit; do not compare them as if they were the same encoding.

The audit helper's status field reads the stored report_status marker. The launcher
returns project_state's derived delivery status after rubric reconciliation; these
are different fields. For completed runs, a raw needs_attention/unreviewed_draft
marker alone does not establish a stale-target or failed-run bug. Terminal output,
public review events, selected draft/target identity and saved content determine
what completed and what was actually accepted. No production status change is
made on the strength of this audit-display difference.

P3-025-A03 (local audit helper, fixed): Windows export failed while cleaning its
temporary baseline copy because SQLite's transaction context manager did not close
the connection. Main changed the ignored read-only audit helper to use explicit
contextlib.closing for both connections. Re-running the same export succeeded;
no model replay or frozen runtime change was needed. Scope is diagnostic export
cleanup, not grader behavior or source integrity. It blocked completion of that
audit export only; the live isolated trial continued. No production defect or
quality gain is inferred from this helper repair.

## H2 repeat completed; frozen four-case regression started

Repeat exited0 with92 observed responses (80grader,12coordinator),6695250tokens,
no missing response usage/errors. Iteration0 needs_revision led to two saved drafts;
iteration1 satisfied targets3055b721-161a-4311-aa6e-f55467fb5ba3, body SHA256
01908754ae726016a07b034449808dea050d1963e428448e65af3c82b13644b1,
pinned DOCX c51140e39f0bdb495b6872d9e73bb8d47203cd2e28eb2ecf2670bec6e287fe50.
Postflight has no failed baseline/source/code hashes; all original results remain
unchanged. Initial effective system is identical to the first H2. Final independent
saved-content/feedback-propagation review remains in progress; satisfied is the
runtime outcome, not Main's acceptance. Its explanation repeats the contested
left12/right14 assertion, which requires checking against the actual saved text.

The predeclared four-case H2 regression started serially after repeat terminal at
.runs/task025/holdout-h2, one artifact_grounded invocation per frozen case in file
order. The batch reads only the inputs file, not labels/notes; same code/prompt/
model/tool/schema settings remain frozen. No Task026 runtime implementation or
candidate paid call has started. Completed observed usage including the repeat is
302responses/18491861tokens; the in-flight four-case regression is excluded.

## Completed H2 follow-up: Main disposition

Independent final repeat review confirms real F02 scope/handling improvements,
preserved original six scoring rows/totals and correct4.1.2 citation. G05 did not
propagate. G04 is partially contained by accurate detailed left/right subsegments
and preservation of the12/14m source difference; do not erase that improvement
or claim the whole left-side range was incorrectly copied. Summary grouping still
does not validate all inputs of a shared assessment.

Main accepts new P2-025-G06/G07 as open: the draft wrongly calls a candidate's
available evidence only a general-summary entry despite existing detailedp142,
and assigns the added candidate a groundwater score without evidence establishing
the chosen band. Seven sums are arithmetically correct, but that does not validate
R. G06 blocks using that absence claim as established; G07 blocks treating the
new score/ranking as verified. The producer owns correction or accurate affected-
claim limitation; Main owns the next development increment and quality decision.
Neither blocks isolated trials or explicitly limited draft review. OldF01/F03/
X21/N01 and final overbroad acceptance (G02) remain; no quality promotion follows.

Independent target checking confirms full1027/1027 export blocks of the final body
and the pinnedc51140e3 DOCX. The launcher's later export has SHA256
eb70a036923d98e821643f36796a5ccd4a05ec00064df05fe3b3d754621816b7;
only its two status/time paragraphs differ. This is not a new report revision or
stale-target defect. Markdown raw CRLF bytes differ from normalized body hashing;
body identity01908754 remains. No new visual page acceptance is claimed.

The four H2 synthetic calls all exited0:33 responses/256901tokens, no missing
response usage, actual system hashes match frozen H2 and actual response models
aredeepseek-v4.1-flash. Main classifications match the earlier controls: two
appropriate accepts and two revision requests. Detailed independent reason/gap
assessment is pending separately. No author's corrective action occurs in these
nested-grader cases. Task025 completed-run usage totals335responses/18748762tokens,
including25author responses, and is not an exact billing statement.

Task026 implementation began only after both repeat and synthetic H2 were terminal
and the frozen Task025 postflight had been retained. No Task025 result was replaced
or silently re-run under the new prompt. The next candidate is independently
tracked; this report records a limited real revision gain and remaining failure,
not a solved verifier or a unique prompt-root-cause claim.

Independent four-case H2 review now confirms all four principal classifications
with source/full-export evidence and actual prompt/input matching. Main accepts
P2-025-H2-01: in the scan case, one failing criterion demands correcting a false
completion assertion while another permits merely disclosing the conflict and
leaving it to a human. It blocks treating that mixed repair advice as reliable;
no author acted, so no propagated report defect is claimed. Producer-facing advice
must distinguish known correctable facts from genuinely unresolved source limits.
The next isolated prompt experiment may continue; this regression remains open.

Main also accepts P3-025-H2-02: the library acceptance reason overstates an explicit
draft/unapproved label that the body does not contain. It does not invalidate the
otherwise supported acceptance or create a new approval requirement; preserve it
as a limited explanation defect. The packaging feedback now requires the correct
352 and does not repeat H1's inappropriate unresolved alternative. No false
rejection of honest source conflict or outstanding installation was observed.
These are four old regression cases, not fresh held-out generalization evidence.
