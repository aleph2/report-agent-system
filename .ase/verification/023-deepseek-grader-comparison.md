# Task023 DeepSeek grader comparison verification

2026-09-28. Main implementation/tests/integration; independent alignment_review
design/code review and postrun_review content assessment. User-requested model
comparison under existing paid/mail authorization. No legacy service changes.

Provider model listing confirmed deepseek-v4.1-flash on the existing endpoint.
Added explicit grader-only model override; coordinator/writer/knowledge/reviewer
roles retain GLM. Native DeepSeek selection is restricted to a fresh isolated review
fork and recovery binding, preventing reuse/relabel of previous GLM approval.
Exact targets also record grader_model. No prompt/rubric/tool/agent-loop changes.

Protocol differences: DeepSeek uses enable_thinking=true rather than GLM's
thinking.enabled/clear_thinking=false, and max_tokens instead of LangChain's
max_completion_tokens mapping. Both use high,65536output,nonstreaming,
parallel_tool_calls=false, unset temperature/top_p/seed, existing timeouts/retries.
These are provider-compatible settings, not identical reasoning compute.

76 relevant tests passed24.19s; one existing Rubric beta warning. Offline tests
cover explicit role routing, invalid models/no fallback, exact wire keys, opaque
reasoning tool-turn roundtrip, safe audits, old approval preservation and recovery
model mismatch, alongside existing native feedback/import regressions.

Real synthetic smoke14:08:25.310–14:08:30.298 UTC: deepseek-v4.1-flash,
2responses/2230tokens. lookup_checksum executed once; native typed GraderResponse
satisfied supported by returned42. No report/source data. This confirms transport,
tool continuation and schema on this endpoint, not report-quality capability.
Private protocol reasoning is preserved for transport and excluded from public audit.

Independent alignment_review completed design and final-code review: no blocking
finding. Main accepted its model-identity concern and verified fresh-fork binding
before execution. This review is development evidence, not report acceptance.

## Frozen supplied-evidence comparison

Two cases completed14:10:38.035–14:20:28.694 UTC, one response each. Both returned
satisfied/all5passed. Original40 (50709d75596d) did not mention the quantity error;
corrected6 (f80d2c73e83c) broadly claimed monitoring quantities match but did not
explicitly establish6 or the40/6 column distinction. The corrected case retains
other known defects, so it is not a wholly correct report. Independent content
assessment is recorded in023-postrun-content.md; known P2s remain open.

Usage:99246input+63005output=162251tokens. Provider records private reasoning token
counts, but no hidden reasoning text is read/exported or used to reconstruct thought.
These are observed responses/tokens, not an exact cost or HTTP-attempt count.

Main's analyze_diagnostic.py verifies input file byte equality toTask022, actual
full system/human/candidate/source content, identical framework/output contract,
and only the intended model/protocol settings change. All51frozen code files stay
unchanged. Same effort names/numeric caps do not imply equal compute. Exact safe
I/O,parameters and receipts are indexed in .analysis/task023/README.md.

The model switch has not solved this supplied-evidence failure. It does not show
that prompts were unchanged accidentally or that all failures are missing-page
retrieval; relevant automatic evidence was already supplied in both models' calls.
One pair does not establish model-wide rates or a unique mechanism.

## Native tool-based continuation

One fresh Task016 fork ran after the pair completed, grading
run4d23cbf0-4384-44c2-8fbe-b20fdc99ad91.14:21:12–14:25:31 UTC,259seconds.
19actual grader responses, all reporting deepseek-v4.1-flash; no other-role response,
author revision or new result. Iteration0satisfied/all5passed,unverified=false.
Its explanation claims no material defect requires correction. This is another
false acceptance of the unchanged original report, not a successful corrective loop.

18tool calls:project_status1,read_result2,read_review_export10,read_source_page3,
search_sources2. Two read_result parts concatenate to the exact26256-character
original report hash7e86b61aa246f5f6b08ecd60c546a95c67cf88f9929f41462285c5c5eddea28d.
Eight successful export reads cover240distinct blocks of907; several repeatoffset0.
Two export calls fail PREVIEW_INVALID_RANGE withlimit120/107, then execution
continues with valid reads. These do not explain absence of the complete report
body, which was separately read. Every recorded tool return reached a model request.

New source reads cover the extraction outline, format standard and cut-slope Guide.
24distinct physical-page table views all belong to that Guide; no new design or
geological PDF reads, and no designp97 evidence in this native trial. Therefore this
native quantity miss includes evidence-selection limits. It does not show failure
after inspecting designp97; the separate fixed-evidence pair tests that condition.
There is no new OCR, visual-model request, knowledge-graph use or developer feedback.

Main verified actual system/rubric equal frozenTask018/022, the trial and target
bound to DeepSeek, all22baseline files and51code files unchanged, all original
source hashes/1617source blocks preserved,4old result records unchanged and no
new result. The original report still contains its known defects. Export byte
identity is not claimed: the launcher generates a new file with current validity
metadata, while the review itself is bound to the recorded pinned snapshot.

Native usage1014333input+17180output=1031513tokens. Task023 including diagnostic pair
and protocol smoke:23observed responses,1115621input+80373output=1195994tokens.
Exact HTTP retries/monetary charges are not inferred from response counts.

## Main disposition and useful outcome

Independent postrun_review owns023-postrun-content.md. Main accepts the demonstrated
P2-023-R01 reliability failure (continuation of known content defects): it blocks
using this satisfied result for quality promotion, confirmed engineering inputs or
engineering sign-off. It does not block publishing this contained experiment's
evidence or providing a precisely annotated draft for human review. NoP0/P1 evidence.
No automatic model promotion or provider-wide configuration change is made.

This iteration establishes a real grader-only model switch, working tool/schema
transport and a controlled negative comparison; it does not solve the review
quality problem. Strategy remains the agent's choice. Both models overlook the
quantity in identical supplied evidence, while their native source-selection traces
differ. Merely changing the model, English language or checking that the prompt was
loaded is not supported as a sufficient fix. Format/context salience, evaluation
scope calibration and model judgment remain competing explanations, not proven causes.

Further identical paid reruns have no justified information gain. The next research
increment should start offline with a generic, faithful compact representation of
automatic table observations plus independent held-out cases, before another
controlled comparison. Preserve numbers, blanks, provenance and uncertainty; do
not inject the known40/6 answer, mandatory page list or fixed semantic checklist.
This is a follow-up direction, not completed work or a new paid call inTask023.

Email update1a0e864bf263dcc4 sent to the authorized correspondent in the existing
thread, reporting both results, usage and the continuing native trial.
Final email1a0e86ad67c9f017 reports the completed native failure, preserved artifacts,
23responses/1195994tokens and the unresolved P2 limit, with the safe I/O index.
