# Task007 autonomous revision experiment

2026-09-28. Main integrated optional tools and feedback, not a semantic stage engine.
Rawls implemented source-page access; Gauss implemented the opt-in reader export;
Ptolemy implemented exported-snapshot inspection. Anscombe independently reviewed
design and actual code. This development review is not another report-runtime gate.

## Scope and actual changes

- Native DeepAgents planning, delegation, checkpoint/interrupt and existing producer
  permissions remain. No new fixed order, mandatory graph pass or extra model reviewer.
- Decimal sum-products returns each product and the total, precision and rounding flag.
  No eval, formula selection or engineering decision. Source pages are project-bound,
  hash-verified physical PDF pages, with native text and matching frozen OCR.
- Source-page images may be embedded by explicit Markdown references; their IDs are
  automatically adopted through existing source/version checks. No semantic ID inference.
- Opt-in technical_zh DOCX template, reader/audit separation, actual OOXML structure/text
  inspection. A pinned preview version preserves the exact export across pagination.
- Short outcome prompt additions and task-specific defect feedback. Human comparison
  report stays held out; original sources, existing OCR and previous model draft reused.

## Evidence so far

- Initial full regression: 414 passed, 9 skipped (127.31 seconds), before final review fixes.
- Integration regression after fixes: 180 passed (70.66 seconds), including native tool
  schemas/observations, source isolation, immutable draft import, image-source adoption,
  exact preview snapshots and backward-compatible exports. These are software tests,
  not evidence of autonomous report correctness.
- Final full regression: 464 passed, 9 skipped, one pre-existing experimental ADK warning
  (115.51 seconds). Paid/infrastructure-dependent skipped checks are not claimed passed.
- Actual guideline physical page20: native text630 characters, one matched frozen block,
  PNG497118 bytes; no new OCR. Actual isolated imported-draft export smoke test succeeded.
- New project `.runs/task007/highway-revision`: 1617 source blocks copied verbatim;
  nine source originals plus commissioning scope copied after hash validation. Only
  previous draft imported, no old approvals/checkpoints/issues/task or graph state.
  Receipt `.runs/task007/highway-revision/import-receipt.json` records hashes and identities.
- GLM5.3 real run launched through existing runtime/credential loader; no secrets logged,
  no provider switch. Outcome and model behavior not yet assessed.

## Review findings and Main disposition

1. P2 preview pagination could change export hashes: fixed with explicit snapshot version.
   Blocked exact-file inspection claims, not content revision. Ptolemy tests and Main
   integration passed; independent reviewer confirmed code closure.
2. P2 task feedback could enter reader scope: fixed by separate public scope metadata.
   Blocked clean reader copy acceptance, not agent input. Scope remains unchanged for
   the business; feedback is only agent task context. Technical-template path verified.
3. P2 image references could be absent from adopted source IDs: fixed deterministic
   Markdown parsing at submission after receipt lookup. Tests verify source-change impact
   and foreign-source rejection; independent reviewer confirmed code closure.
4. P2 trial importer assumed scope_instruction was text, but real baseline stored a dict:
   first preparation failed before destination writes/model calls. Fixed reading text and
   copying scope original; dict-scope regression added and real import succeeded.

All owned by Main for integration and closed in code/test. No new P1 access blocker found
by independent review. Confirmed report defects C01-C07 remain open until actual revised
content is inspected; software changes alone do not close them.

## Boundaries

GLM5.3 is text-only per official model documentation. Image references, native text and
OOXML inspection do not establish visual understanding. Runtime preview deliberately
reports render_unavailable; development-side rendering/visual QA must be separate.
Arithmetic does not approve inputs, scoring method or engineering grades. Source conflicts
and real missing material remain human decisions. Never auto-answer a business interrupt.
Exact saved-version model review is not POC acceptance or engineering sign-off.

## Real-run intermediate findings

The model saved f3980169-c8f7-4c2b-bf5d-4b5abd5ca09c, then independently revised it to
aac838f6-8806-42f6-bbf2-346d52431cb0. Three submissions referenced a superseded draft
as a live input and were rejected; the model eventually corrected input_ids itself.
No validation was disabled and no operator answer was injected. Native context
summarization was observed, not a locally reimplemented memory engine.

Independent development content review is in `007-content-review.md`, limited to f398.
Six detailed scoring tables were arithmetically corrected but a summary value and
some explanations remained wrong. Later aac838 corrected increment explanations;
not all intermediate findings automatically close. The native runtime reviewer also
returned changes_required for aac838, including the stale summary score and front matter.

Development visual QA of f398's exact snapshot hash
`6d45390d0ebc02ac0e20be8dcc851076a7aae6c9d5ed3a41580843a8ca069a91`:
37 rendered pages, 9 tables, 0 images; all pages examined, no observed clipping or
overlap in tables/Chinese text. P2 duplicate front matter and unpopulated TOC persist;
P2 missing figures persists. P3 excessive table whitespace/chainage wraps/long header.
Evidence: `.runs/task007/visual-qa/f398-model-preview-6d45390d/visual-qa.md`.
This is a historical artifact check, not final acceptance or model visual capability.

New P2 integration defect: successful preview text reads were not registered as draft
observations, so native reviewer submission wrongly required read_result as well
(events319/329 REVIEW_TARGET_NOT_OBSERVED). Model worked around it, then submitted
review8c8a30ad-d4de-4ceb-9414-fd06ecdf71eb. Main accepts Anscombe's focused disposition:
record exact-draft observation after successful nonempty preview read using injected
ToolRuntime; retain all target/version/ownership checks. Fixed after current run;
54 focused regression tests passed (58.82 seconds), including native reviewer preview-only
success and empty/invalid/other-draft negative cases. No audit rewrite or restart.
Only corresponding review
submission is affected; an observed version is not proof of full or visual review.

Observed coordinator
autonomously inspecting guideline physical pages and calling the calculator for all
six workpoints. Totals observed: 48.99, 42.33, 60.98, 59.04, 54.68, 56.41, conditional
on selected inputs, not approved engineering scores. Initial read-page and todo input
errors were surfaced and corrected by the model without Main changing runtime state.

## Trial outcome

Real GLM run: 2026-09-27 23:23:07Z to23:49:46Z, 26m39s. 88 locally recorded model
requests and88 responses (including native context summarization; not an assertion
about hidden SDK attempts or billable requests). No model/HTTP error events.86 tool
starts,14 rejected calls; ask_human interrupts so its tool_end is intentionally absent.
Calculator: six coordinator calls and six reviewer calls. Original-page inspection:
10 coordinator and11 reviewer calls. Preview:5 coordinator and13 reviewer calls.
One autonomous reviewer delegation, no knowledge producer/graph/text-analysis calls.
This revision workload is not comparable to the initial full report for speed claims.

Latest saved draft: `989e4c69-2fee-4fc8-a556-b13a057ee987` (21509 characters).
After native reviewer feedback the agent corrected summary value59.04 and removed
duplicate front matter. Development review confirmed all66 table products, six totals,
summary and conclusion totals agree. C01 numerical rule application and C02 arithmetic
substantially improved, but scoring inputs and applicability remain unapproved.

Residual P2 content: under the draft's rock-slope assumption,28.9m is still described
as25-49 while guideline physical page18 assigns0-24. No source-page images were adopted;
evidence appendix remains a locator list. Rule paraphrase/provenance gaps noted in
`007-content-review.md` remain. These block claims of all findings closed/full content
acceptance, not a clearly limited review draft. Main owns follow-up; don't silently
edit model text to turn this experiment into a pass.

Agent called ask_human for slope-height definitions/values, rainfall-rule applicability
and scoring-method confirmation. Issue `f68f6d83-f995-4215-9af1-b5433579831b` unresolved.
Native checkpoint `1f1bace1-c970-6bbe-8093-c65f25f3094d`: one interrupt, next=tools,
no task error. End state needs_human, not HTTP failure. No operator answer or resume.

Important P2 delivery-selection limitation: agent first paired latest989 with prior
review8c8, correctly rejected REVIEW_VERSION_MISMATCH. It then selected superseded
aac with that review (which said changes_required), so launcher exported selectedaac.
This was an explicit model selection, NOT automatic latest fallback. Latest989 is
unreviewed; old review must not be inherited. Keep historical export/audit unchanged,
provide an explicitly unreviewed989 QA copy, and distinguish selected vs latest in
follow-up tool/UI work. No approved or engineering-ready delivery is claimed.

Next changes should improve tool contracts/observations and artifact responsibility,
not add semantic stages: distinguish editing history from adopted current inputs,
expose template-owned front matter to the agent, make actual export limitations clear,
and keep explicit known rules connected to the corresponding report claims. Figure
selection and source applicability remain expert decisions. Human decisions remain
unresolved rather than being answered by the development team.
