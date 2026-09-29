# Task033 representative report verification

In progress, 2026-09-29. Main runs the actual native application in the new isolated
`.runs/task033/boundary-guidance` project. No source reconstruction, report writing,
criterion authoring or engineering decision is performed by development agents.

Candidate runtime is unchanged from Task032 implementation96f371c. Task declaration
commit51fc39f. Freeze is `.analysis/task033/freeze.json` and project's trial-freeze.json.
Preflight checked all34 runtime/configuration hashes, ten copied originals including
the commission, and source index against the baseline. Fresh state starts with zero
results/reviews and graph disabled. Verified index has1617 blocks. Trial input and
baseline source data are preserved. Source copy preparation finished before any
model invocation; it was not retried.

The one authorized launch uses GLM-5.3/high, max_tokens65536, non-streaming,
parallel_tool_callsfalse, provider thinking enabled, max_retries2 and existing
15/1800/60/60s connect/read/write/pool timeouts. Temperature/top_p/seed unset. Optional
vision tool remains agent-chosen; actual calls/usage will be audited. No new OCR.
No cumulative token quota or whole-task arbitrary timeout was added.

Authorized start email1a0eb705cac906e1 in thread1a0e8337bc8d5abd explains that the
synthetic experiment is incomplete and cannot prove highway-report quality. It
reports the independent small-trunk success and remaining P3 standard-language
ambiguity without treating either as a blanket model capability conclusion.

Main's audit script reads allowed public events, saved results and state.db via
read-only connections. It never opens private checkpoints/reasoning. Result mirrors
preserve LF; hashes and public model I/O are retained under
`.analysis/task033/boundary-guidance`. No independent findings enter runtime input.

First observation04:33:29UTC: coordinator reading commission/source material,6 model
responses, no saved criteria/draft or model error yet. G1 remains open. Do not infer
successful report delivery or acceptance from this progress record.

The user subsequently explicitly said continue without stopping and continue email
communication. Main answered the strategy question in chat and sent the same three
priorities (preserve acceptance object, distinguish evidence acquisition from
judgment, measure effective repairs/non-regression) in authorized email
1a0eb749385f25b9. Inspect only this relevant mail thread for any new reply; quoted
old messages are historical context, not fresh instructions. Latest check contained
only the recent sent updates, no new incoming decision.

## Terminal result and Main's disposition

The original launch completed normally (exit0), deep_run_finished seq283 at
04:49:44UTC. Canonical delivery is reviewed_draft with six satisfied criteria at
iteration0, no saved revision and no human issue. Raw report_status remains
unreviewed_draft; it is not the canonical delivery projection. Saved standard
95f221a2-b318-4158-b1f8-235aa71c6273 and draft
ad297419-5aa2-41fb-aa6f-c80f722fe352 (17979 chars) are the only two results.
Target draft SHA256 is07c5933c882cadf8b3099785501726bdc54cd0d3a4f83272ce80e99fb64af7b7;
DOCX SHA256 is4583aed0881a93ffa448717aa8ef921ebea1b55d04491a21405c388e0231f3e8.
The complete public requests/responses, selected evidence, model settings, results,
export and target are retained in the isolated project and public audit mirror.

69 responses/requests, allGLM-5.3:37 coordinator and32 grader,5923895 provider tokens;
zero model errors, missing usage or visual-model calls. Postflight all34 frozen
runtime hashes and all ten originals match, including baseline counterparts;
both1617-block indexes and original goal match the freeze. Graph remains disabled.
Sixteen arithmetic calls comprise ten author calculations and six grader recalculations.
Main's Decimal audit independently reproduces the six saved sums. Printed weights
sum1.0001 while exact ranks sum1; the displayed arithmetic convention does not
justify a false material-miscalculation finding.

Independent postrun_review read the whole report and compared actual source support
and terminal grader reasons; see033-independent-results.md. Main accepts:

- P2-033-C01: generated standards still narrow the commissioned universe to the
  six design rows. Available geology candidates lack complete disposition. This
  blocks a full commissioned-scope claim, not isolated diagnostics or a bounded draft.
- P2-033-D01: the adopted rainfall premise is attributed to the wrong guideline
  band. Holding every other report input fixed, applying the supplied >1000mm rule
  changes siteIII's printed sum44.7413 to47.4683, crossing theII/III boundary. This
  conditional check is not a new engineering assessment or validated replacement
  of the remaining uncertain inputs. The report's separate recommendation to give
  that site special assessment contains some consequence but does not cure the rule.
- P2-033-D02/D03/D04: class/value incompatibilities, insufficient threshold premises
  and undisclosed design/geology differences block unqualified scoring/source-fidelity
  acceptance. Preserve genuine uncertainty and provisional proposals; do not invent
  replacement measurements, choose a winning source or demand new engineering work.
- P2-033-R01: the six-item all-pass is substantively unsound. Grader read all604
  export blocks and correctly recalculated sums, but did not obtain key guideline
  scoring pages. Some geology height/lithology counterevidence did reach it. Therefore
  this is both incomplete verification and failed synthesis of available evidence,
  not solely a missing retrieval problem or an arithmetic-tool failure.
- P3-033-C02/D05/D06: source-reference precision, unsupported group attribution and
  numbering deviations are contained draft issues. They do not justify stopping
  the useful quality investigation or claim a severe engineering failure.

Main owns the next scoped increment and its disposition. Keep this complete draft
as diagnostic evidence, not as a promoted reliable verifier or signed engineering
report. G1 remains open and the primary-use-case acceptance is not achieved. The
useful draft and clearer standards/authority boundaries are real gains, but cannot
waive the available-source errors. Old defects absent already inTask031 are not
counted as new fixes. No native repair occurred in this trial.

Next priority is to improve actual evidence-to-claim assessment while preserving
autonomous investigation. Existing bounded analyze_text takes only one source slice;
evaluate the smallest useful extension for locally comparing chosen, identified
report/source evidence, rather than repeating the same full run or adding known
answers to prompts. Independent alignment review is requested before implementation.
Neither tool availability nor a future isolated success constitutes promotion.

Terminal email1a0eb82332bae597 sent in authorized thread1a0e8337bc8d5abd, with exact
intent/receipt retained. It reports the erroneous all-pass, conditional grade effect,
two distinct evidence failure modes, usage and continued work without requesting
repeated authorization.
