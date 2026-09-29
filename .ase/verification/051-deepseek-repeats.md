# Task051 repeat verification

2026-09-30. User requested additional tests. Main implements the isolated batch
harness; LLM/RL specialist independently reviews design and public outputs in
`051-independent-results.md`. Risk-validation/G1 remains open. Production/legacy
services, prompts, acceptance schema and pending043 work are unchanged.

Four offline checks passed (repeat schedule and unchanged050 hashes, raw result
preservation and rejection of missing/duplicate/reordered IDs,050 schema adaptation
and local validation regression). Reused050 alignment evidence for unchanged
prompt/schema boundary; no new runtime agent/semantic strategy was introduced.
Specialist reviewed design: fixed6 identities/order, independent contexts, no
repair/replacement, separate protocol/relationships/verdict/false rejection/repair
assessment. Main accepts the design findings and limited inference boundary.

All six request files were frozen before dispatch at
`.runs/task051/deepseek-repeats/`. high requests match050 high SHA256
`63bfb57026825423795495b11fd6baf25fb8ef27690836cb6e5b196c1a57093f`;
max requests match050 max SHA256
`d3854f920039a23b04400fccdee15e44f8854c627362e873548e55e3c67a5e8d`.
Manifest fixes high01,max01,high02,max02,high03,max03 dispatch order, concurrency3,
retries0 and timeout15/1800/60/60. Each result remains tied to its own identity
regardless of completion order. Pending requests halt on API/transport failure or
protected-file mutation; in-flight results remain collected. Protocol/semantic
failure is retained as an observation, never repaired or replaced automatically.

Primary table will report051's three new observations per setting;050 is separate.
Same-fixture repeats do not test generalization. Concurrency/cache/provider effects
preclude causal latency conclusions or assertions of statistical independence.
Both effort and capacity differ between settings, as before.

## Interim high observations (all three finished)

- high01: response JSON and six IDs present, but the not_satisfied C6 item lacks
  required gap. The saved request has strict=true and gap required in the false
  branch; finish_reason is tool_calls, not truncation. Local validation rejects it
  and no output.json is written. Public overall needs_revision is based on a
  soil-state allegation while C2 remains satisfied; it is not successful O1
  rejection. Specialist additionally checked the supplied rainfall page: the
  response's claim that '>1000mm' is absent from the source is incorrect, although
  its100 score remains correct. Scope and severity detailed in independent review.
- high02: valid protocol, all six satisfied. O1 correctly stated as70 outside
  adopted75–100, then waived as disclosed judgment and unchanged grade. False
  acceptance recurs. O2 value correct; actual height remains unknown.
- high03: finish_reason length; completion65536 equals configured max_tokens65536,
  public content empty and no tool calls. Reasoning metadata65536 is a completion
  subset, not extra usage. No substantive answer: unscorable rather than semantic
  false acceptance. This establishes capacity truncation in this observation,
  without rewriting050's earlier non-truncated outcomes. It reinforces that
  effort and capacity effects cannot be isolated in this comparison.

Each outcome is preserved; no replacement or repair request. Strict mode is not
treated as a substitute for local validation. Three max requests are now in flight.
## First two max observations

- max01: valid six-ID output, C2 not_satisfied and overall needs_revision. Correct
  O1 relation and criterion consequence, explicitly no pending-confirmation or
  unchanged-grade waiver. O2 conditional100 preserved. O3 not resolved. Specialist
  notes a separate C6 overclaim: the response admits soil-description source
  support is unverified yet passes C6 because verification is included in C2.
  Sharing a repair task does not establish that criterion's factual consistency.
- max02: raw public arguments contain unescaped quotes; JSON parsing fails,
  finish_reason tool_calls and completion109703 below131072. No output.json,
  no repair/replacement. Public text correctly identifies O1 and requests C2 N
  with sourced correction, but this is qualitative text evidence only, not a
  valid six-criterion machine result. Protocol failure remains despite strict.

## Completed batch (six requests, six responses, zero retries)

max03 produced valid output, overall undetermined (C2 satisfied, C6 undetermined).
It claims values are within their declared bands, does not establish the known
70 vs75–100 relationship, and assigns the source uncertainty to C6. It therefore
does not correctly reject the established C2 violation. Overall is withheld,
not all-pass: do not misreport this as whole-report acceptance.

| Run | Protocol | Public key judgment | Overall | Valid correct O1/C2 delivery |
| --- | --- | --- | --- | --- |
| high01 | missing required gap | C2 S; rejection based on different soil claim | needs_revision text only | no |
| high02 | valid | recognizes O1 then waives it, C2 S | satisfied | no |
| high03 | length, no public answer | unscorable | none | no |
| max01 | valid | O1 recognized, C2 N | needs_revision | yes, limited to this oracle |
| max02 | invalid JSON | O1 recognized, C2 N in public text | needs_revision text only | no |
| max03 | valid | O1 not correctly established, C2 S | undetermined | no |

Primary051 counts: high protocol1/3, max2/3. Correct public O1 relationship plus
C2 rejection: high0/3 (one has no answer and is semantically unscorable), max2/3.
Valid delivery with that correct key rejection: high0/3, max1/3. These are trial
outcomes on one fixed fixture, not general accuracy or independent Bernoulli-rate
estimates. Correct key rejection does not establish every criterion's correctness.

Historical050 separately: high valid/allS (wrong C2), max valid/C2N (correct O1).
If explicitly pooled, valid correct key deliveries are high0/4 and max2/4;
protocol validity high2/4, max3/4. Do not select050's favorable max outcome or
invalid max02's favorable wording as substitutes for this batch's outcomes.

All six saved requests remain byte-identical to their respective050 settings;
postflight checks match, no API/transport error or undispatched request, no
repair/replacement. Returned models are deepseek-flash with the same backend
fingerprint aeb56401ca74e127821c4f9126dcb669 in all six responses. No private
reasoning text inspected. Summary metadata saved in the run directory.

| Run | Seconds (observational) | Prompt | Completion | Total |
| --- | ---: | ---: | ---: | ---: |
| high01 |201.4|136351|53104|189455|
| high02 |201.0|136351|54759|191110|
| high03 |249.4|136351|65536|201887|
| max01 |522.4|136351|116858|253209|
| max02 |472.0|136351|109703|246054|
| max03 |492.1|136351|115288|251639|

Total usage1333354 = prompt818106 + completion515248. Reasoning496564 is already
included in completion, never added again. Token accounting is not invoice cost;
cache/concurrency differences preclude a causal latency claim.

Main's conclusion: max shows more correct key judgments in these observations,
but does not reliably deliver them. Both protocol and substantive review defects
remain. Keep this as diagnostic evidence, not a production promotion or G1/G2
acceptance. A later comparison should equalize output capacity to isolate effort
more closely; high03 establishes why that distinction matters. No further calls
are started by this recommendation.

## Independent review and Main disposition

LLM/RL specialist `/root/llm_rl_expert` completed independent review of all six
public responses, exact requests, oracle, freezes, usage and counts. Main accepts
the scoped findings in `051-independent-results.md`:

- P2-051-R01: high01 missing gap and max02 malformed JSON block accepting those
  outputs or passing them directly into an author loop. Retain the local validator,
  quarantine originals; investigate protocol reliability in a future increment.
- P2-051-R02: high01/high02 and max03 do not correctly reject the established C2
  violation. max03 withheld the overall result, so the defect is criterion-level
  false acceptance/missed known violation, not whole-report all-pass. No quality
  promotion or signing from these observations. Retain calibrated oracle evidence.
- P2-051-R03: high01 incorrectly says the >1000mm source text is absent. Preserve
  correct source excerpt; do not change the correct rainfall explanation based on
  this claim. Future review-quality work must include source-reading controls.
- P2-051-R04: high03 output-capacity truncation prevents using this trial as a
  grading result. Retain as capacity failure, not a semantic judgment; a subsequent
  effort comparison should use equal adequate capacity. No silent continuation,
  replacement sample or rewriting of this outcome occurred.
- P2-051-R05: max01/max02 overstate C6 source consistency despite acknowledged
  unresolved support. This blocks treating their C6 S as全面核验通过, while the
  valid max01 O1 feedback remains useful for later source-grounded repair. No
  complete C6 gold or claim that original source data are false is manufactured.
- P3-051-R06: max03 writes F>=45 for the special-assessment threshold; the actual
  applicable boundary is >45. None of the six current values equals45, so its
  current five-object list is unchanged. Record for correction before reusing that
  statement as a general rule; it does not block this diagnostic outcome.

Main owns these follow-ups. Scope is the frozen fixture/candidate integration,
contained by explicit failure records and absence of production promotion or
engineering signing. They do not block completing the requested repeat study.
No real author revision or native end-to-end report acceptance was demonstrated.
All authorized051 tests, four offline checks and scoped reviews are complete;
no in-flight request or new experiment remains. Pending043 work is preserved.
