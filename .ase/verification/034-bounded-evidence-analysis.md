# Task034 implementation and local verification

Main implemented optional selected-evidence analysis in a new module and thin native
tool wrapper. Grader outcome prompts/criteria contract and existing analyze_text are
unchanged. Only reviewer role exposes the new tool; native requirement acceptance
includes it in its read-only tool set. No mandatory call, source search or fixed
semantic steps were introduced. Existing DeepAgents remains the control loop.

alignment_review independently checked design and implementation. Main accepts its
P2-034-A01: the initial wrapper did not record read result IDs in the legacy review
observation ledger, so an analysis-only read followed by review submission would be
rejected. It blocked that legacy submission path, not native acceptance or isolated
analysis. Fixed before paid calls: success/cache reuse records only validated result
IDs from actual returned evidence in the current ToolRuntime namespace. No caller-
invented identity is recorded. Main owns correction and validation; no historical
run was affected. Full input audit/cache records remain derived observations.

The requested StructuredTool JSON-selector check now executes the actual tool wrapper
with an offline model and proves analysis -> saved review submission without a redundant
read. Source/result access is checked before cache, source blocks and report character
ranges are explicit, model parameters/contract/full observations enter cache identity,
and whole-page supplements retain their limitations. Historical result selection is
identified separately from current selected delivery. No private reasoning is exported.

Eight focused tests pass, covering exact selected content and stable business
artifacts, cache invalidation, project/selector rejection, historical identity,
non-execution of unexpected tool calls, table limits, native JSON schemas and actual
review submission. During test development, a fixture used the wrong Workspace.submit
signature and a schema test converted a raw function instead of the native StructuredTool;
both were corrected. These were test setup errors, not paid execution failures.
Existing acceptance/claim tests27 passed before the ledger fix; acceptance15 passed
after it. Existing context/feedback tests20 passed. No semantic-quality claim follows.

## Bounded diagnostic declaration

Use Task032's four synthetic cases as known controls, one call per entrypoint per
case (eight calls). This is not a new holdout or a statistical improvement estimate.
Each pair has the same saved source/report content, commission and question. The old
analyze_text receives the primary source normally and the remaining selected material
inside purpose; the new tool resolves the same selection IDs itself. Actual system
prompts and serialization differ because these are the real interfaces; do not
attribute semantic differences solely to version binding. Alternate arm order.

No oracle file enters the runner; strict model-visible input validation is reused.
All reports/sources fit the declared selections without truncation. Both tools use
the existing GLM-5.3/high text model and settings. Preserve actual public inputs,
outputs, usage and errors. No author, final grader or autonomous tool choice occurs
in this local comparison. After evidence review, decide whether a native selection
probe adds information; do not automatically run a whole highway report.

## Local result and next diagnostic decision

All eight local calls completed05:12:25UTC, one GLM-5.3 response each,38126 provider
tokens, no missing usage. Main verified complete source texts and candidate bodies
in every actual request, one common callback parameter set, and all37 frozen files
unchanged. Independent postrun_review finds the main factual relations correct in
both interfaces; this is not evidence of a semantic improvement over the old tool.

Known material limitations remain: selected/packet03 finds the available registrar
but permits labelling it unprocessed as an alternative repair; selected/packet02
misstates whether the business threshold belongs to the commission even while
preserving its correct unknown conclusion. Preserve these independent findings
and exact outputs. They block treating tool prose as authoritative repair/acceptance
requirements, not running a read-only isolated observation. Main retains ownership
of disposition; complete independent detail is034-independent-results.md.

Main chooses one autonomous native-grader-only probe of Task033's report. The action
tests whether the grader voluntarily uses selected evidence analysis, chooses relevant
material and integrates observations appropriately. It has no author or outer repair
loop, so unsupported repair suggestions cannot alter the report. Known local faults
remain in the frozen candidate; no prompt retuning or evaluator answers are injected.
This containment makes the information value exceed waiting for a perfect tool.
There is no reliability promotion or engineering sign-off. Inspect valid content and
false findings as carefully as new detections. An unused tool or another unsupported
all-pass is evidence against the proposed next-step gain, not a reason for blind retry.

Import only original source/OCR inputs plus unchanged Task033 criterion definitions
and report bytes into a fresh project. Normal APIs assign new criterion/result IDs;
record their mapping and exact body hash. Prior verdicts, independent findings,
checkpoints and author history are excluded. A neutral initial history and new IDs
differ from the original full run, so do not claim a single-factor causal comparison.
Existing source-only tools and the new optional tool remain available. The framework
grader graph runs normally, with the previously disclosed direct-graph coverage/
outer-loop limitations. The public-import/no-history/replay-protection test passes
(1test,6.26s); input-copy mechanics reuse previously tested prepare_clean_trial009.

Task034 start email1a0eb90c51b23c93 reports completed Task032 limits and the bounded
new-tool experiment. Source/code/runtime outcomes will be reported separately from
availability and test counts.
