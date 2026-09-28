# Task021: broad review, flat versus column-preserving source evidence

2026-09-28. Main prepared and executed the user-authorized four-case experiment.
The independent `alignment_review` checked design and actual paired inputs before
calls; `postrun_review` independently assessed public outputs and existing defects.
Current stage is focused risk diagnosis supporting the existing report trunk.

## Result and engineering decision

The original wrong report was accepted with flat evidence and its specific quantity
error was detected with the column-preserving representation, without a target
section/quantity hint in the commission. Corrected controls did not receive a target
false allegation, but neither explicitly discussed/check-confirmed that quantity.

| Source presentation | Report variant | Verdict | Predeclared target outcome |
| --- | --- | --- | --- |
| Original flat text | Original40, c24f82ae1090 | satisfied | Not reported; wrong report broadly accepted |
| Preserved column bindings | Corrected6, 5efcba78bffc | satisfied | Not mentioned; no target false allegation observed |
| Original flat text | Corrected6, 94930c7f4c47 | satisfied | Not mentioned; no target false allegation observed |
| Preserved column bindings | Original40, 09a71435a457 | needs_revision | Detected: source6settlement plates versus40inclinometer pipes |

The final case explicitly locates Section5.2.3(1), design tableS3-2-10 page3, and
the source rowK1319+910–K1320+160. Its first response already identifies the error;
the second only repairs a missing structured gap field, so target detection is not
an effect of human factual feedback or an additional independent inspection.

This comparison supports source representation/cell binding as a concrete candidate
contributor to the historical failure, and shows targeted section instructions were
not necessary to detect this error under the structured supplied-context condition.
It does not establish reliable autonomous detection, quantify an improvement, or
prove a sole cause: one observation per cell, human semantic cleanup, preselected
evidence and different random generations remain limitations. Full report correctness
is not established in any cell. Existing non-target defects still constrain approval.

Main's next engineering priority is to preserve recoverable table structure and
source provenance in the evidence supplied by ordinary source tools, rather than
hard-code this sentence/value or prescribe the grader's investigative sequence.
This experiment used a manually verified table for diagnosis; that fixture must
not be deployed as if it were general automatic extraction. A general extraction/
presentation change must be checked on original pages and return to the real
reviewer -> responsible author -> saved revision -> re-review path. No such
production change, automated table-parser validation or correction-loop acceptance
is claimed here. Merely supplying flat numbers and a vague warning is not evidence
that the model can recover all lost cell associations or calibrate its final verdict.

## Controls and actual inputs

All four use the same English broad commission plus unchanged original Chinese
project scope, identical production system responsibility prompt/native grading
contract/rubric, full candidate report, model settings and response schema. Task
instructions do not name the target chapter, p97 importance,40/6 anomaly, or an
investigative plan. The supplied source bundle contains every distinct actual
block returned by Task018 search_sources/read_source_page:29blocks from5documents.
It omits historical query strings, author/model claims/plans/verdicts and export
data. It contains no added never-returned text from a source database or PDF.

Between source arms only index21 changes. The same design-p97 block occurs once;
the other28blocks and all source IDs/locations/order remain identical. Flat text is
the exact854-character historical return, including extraction noise. Structured
text uses the independently visually verified nonempty rows, column names/units,
group/title identity and totals. Every numeric row sequence is identical, but the
table restores cell/column bindings and omits empty-row/extraction noise. This is
semantic presentation cleanup, not purely cosmetic spacing. See independent
[021-alignment-review.md](021-alignment-review.md) and the reused
[019-reference-check.md](019-reference-check.md).

Both original candidates have SHA256
`7e86b61aa246f5f6b08ecd60c546a95c67cf88f9929f41462285c5c5eddea28d` (26,256chars).
Both quantity-corrected candidates have SHA256
`2c5b5309e412d25a156fe5f5b8d03fbd96f8d53c306bd6e9f2771dbb44b5f562` (26,255chars),
differing only by one `40 块沉降板` -> `6 块沉降板`. Their other defects remain.
Actual first HumanMessages are64,112–64,177characters and fully match the frozen
hashes, including the complete candidate and source bundle. First input contains
only system+human. No silent truncation, tools for evidence retrieval, author loop,
reference labels or old transcript are present. Model callbacks confirm unchanged
system text and invocation parameters in every request. Labels are development-only.

Fresh context with flat evidence still reproduced a miss: historical author/tool
history is therefore not a necessary condition for this observed failure. It may
still affect production behavior; this is not proof that history has no influence.
The source bundle itself was selected by a prior reviewer and carries relevance;
this experiment does not test full-project search, unreturned documents or actual
autonomous tool selection. Fixing source presentation alone has not been shown to
resolve the broader verdict-calibration/coverage problem.

## Execution, usage and integrity

Task baseline commit `b9d555b`; unchanged diagnostic executor from `41ec4d0`.
The local wrapper alternates opaque source groups while reusing load_inputs,
real_factory and run_case. Exclusive destination directories prevent replay; all
inputs are validated before credentials are read; failures stop the batch.
Credentials remain in memory, with no new OCR/graph/image-model/legacy writes.

Actual model: GLM-5.3, reasoning_effort high, thinking enabled,
clear_thinking false, max_completion_tokens65536, parallel_tool_calls false,
non-streaming Chat Completions. Temperature/top_p/seed unset, SDK retries2,
timeouts connect/read/write/pool15/1800/60/60seconds; versions/settings identical
to Task020. The only tool schema is structured GraderResponse submission.

Run window13:10:48–13:19:55UTC, approximately547seconds. Four initial cases,
five observed requests/responses: first three one each, final case two. Final
first response had Correctness.passed=false but omitted its required gap field;
the native ToolMessage reported criteria.2.0.gap missing. The second response filled
the field while preserving the factual findings. This is a schema-validation repair,
unlike Task020's natural-language structured-output continuation. No manually
repeated paid case or human factual feedback. Callback counts do not independently
audit possible SDK-internal HTTP retries.

Provider-reported usage: **212,041input +40,419output =252,460tokens**. Output includes
reasoning-token counts; private reasoning content is neither inspected nor exported.
No currency cost estimate. Four earlier harness tests remain applicable; additional
input/provenance/invariant checks and real behavior verify this changed test data.
All157 frozen original run/analysis/code/input/reference files are byte-identical
after execution. Actual parameter objects equal Task020 and every input hash matches.

Private Git-ignored evidence:
- `.analysis/task021/actual-prompt.md`: exact broad instructions/system/rubric.
- `.analysis/task021/fixtures/`: opaque source-arm inputs and interleaved batch order.
- `.analysis/task021/source-comparison.json`: exactly the two p97 presentations.
- `.analysis/task021/reference.json`, `freeze.json`, `results.json`: labels/provenance,
  protection hashes and actual I/O/usage/integrity summary.
- `.runs/task021/judgment/<case-id>/`: complete input.json, output.json, model-io.json,
  settings.json and receipt.json. Public model content and safe invocation metadata
  are retained; no credentials/private reasoning exported.

## Defects and acceptance disposition

Existing F01/P2 and P2-018-R01 are reproduced in the flat original case, not newly
counted as separate bugs. Three satisfied outputs overstate overall consistency
while untouched report conflicts remain. All six previously verified weighted
totals remain arithmetically correct; this is not a new arithmetic failure and no
calculate tool call is required to substantiate correct arithmetic. Disclosure of
pending decisions still does not fix contradictory assertions or invalid inputs.

The narrow discrimination is useful diagnostic evidence, not quality promotion.
Existing P2 issues block relying on erroneous engineering inputs, asserting broad
content acceptance, and engineering sign-off. They do not block recording this
isolated comparison, which leaves original reports and sources unchanged. Main
owns the source-presentation follow-up; report producers retain correction ownership.
Independent content assessment and any additional supported findings are recorded
in [021-output-review.md](021-output-review.md), with Main's final disposition below.

Main accepts independent **P2-021-R01** as another observation of the existing broad
false-acceptance defect, not a new bug per case. It remains open and limits all
overall-quality claims, including the two quantity-corrected controls.

Main accepts new **P2-021-R02**: the report's own Table3.2-1 (L254) places residual
layers in the75–100 X21 band, while Table4.2-1 (L344) cites residual/soft-plastic clay
and assigns60 without connecting a different applicability basis to that choice.
This affects input qualification; the report producer must justify or revise it
before treating the input as verified. It does not establish a unique engineering
value or authorize Main to substitute one. Severity P2: a material, locatable and
containable report inconsistency. Keep open with the responsible producer; resolve
and re-review before content-quality promotion/engineering reliance. For this
diagnostic, preserve the original and explicitly record the uncorrected issue.

The statement that the risk grade is unaffected is supported only for changing
this one R while holding all other inputs fixed: weight19/121, original exact
F50.272727, R75–100 gives F52.628099–56.553719, stillIII. It is not a conclusion about
the result after fixing every other disputed input. No engineering value is chosen
and no original artifact is changed by that conditional check.

Main records **P3-021-R03**, the missing required gap in the first structured
response, as recovered within this invocation. Impact is one extra response and
its usage/latency, with no loss of the already present factual finding. The native
validator's correction is sufficient containment for this delivered diagnostic;
no extra retry or application change is justified from this one observation. Retain
the complete public error/correction trace for regression comparison. It does not
block diagnosis delivery or imply a new grading insight in the second response.
