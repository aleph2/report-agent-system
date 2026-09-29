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
