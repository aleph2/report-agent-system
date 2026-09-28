# Task019: controlled monitoring-quantity judgment diagnostic

2026-09-28. User approved the proposed next step: wrong/correct monitoring-quantity
variants in short and full report contexts, with model, parameters, goal and rubric
held fixed. Reference labels remain development-side; original reports stay intact.

Stage: focused risk diagnosis for the existing end-to-end trunk. Task018 proves
new autonomous instructions reached GLM-5.3, but its satisfied verdict missed known
material defects. P2-018-R01 remains open; this diagnostic does not itself validate
report quality or the author/reviewer correction loop.

Main owns fixture preparation, harness, execution and integration. Independent
alignment_review checks design/final boundaries; postrun_review independently
checks original table and reference labels. No runtime reviewer is added.

Design:
- Visually verify original roadbed-design PDF physical p97, S3-2-10 page3/3.
  Provide the same faithful column-preserving transcription of all nonempty table
  rows in every condition. This is source evidence, not a reference verdict.
- Four cells: short/full context crossed with original/corrected quantity. The
  corrected test copy changes only one literal, 40 块沉降板 -> 6 块沉降板.
  The short context is the complete section5.2.3; the full context is the original
  saved report body. No production report or source is corrected by this fixture.
- Use the same focused assignment in all four: assess fidelity of the design
  monitoring aggregate quantities quoted in section5.2.3(1). Other report text is
  context, not another commissioned judgment in this diagnostic. Missing unrelated
  chapters in an excerpt and unquoted source-table items are not defects here.
- Keep actual reviewer_prompt(), five-category load_rules(), GLM-5.3/high settings
  and native GraderResponse schema. Fresh independent sessions; all evidence inline,
  no tools, author history or revision loop in any condition. This removes retrieval
  as a variable while testing judgment, not the production agent end to end.
- Use opaque case IDs/order. Store the mapping and expected factual outcomes outside
  the runner's fixture directory. The runner neither opens reference labels nor
  injects prior development findings. Freeze exact input/code hashes before calls.
- Initially run each of the four cells once, serially, using the existing authorized
  service. No blind whole-case retries; preserve attempts and provider usage/errors.

Interpretation: the full corrected copy still contains other known report defects;
do not use full-report satisfied as a general positive truth. Assess the stated
quantity target and citations. A short-vs-full difference suggests a context effect
only within this focused clean-evidence setup; four observations do not establish
reliability or a universal cause. Clean transcription and target focus differ from
historical production conditions. If all cells discriminate correctly, capability
under these conditions is supported, but autonomous detection remains unproved.

Predeclared target scoring: an explicit source-supported 40-versus-6 mismatch in
an original case, or an explicit source-supported six-plate match in a corrected
case, counts as correct target judgment. An explicit contrary judgment is incorrect.
No explicit target judgment is inconclusive, regardless of top-level result or
other rubric failures. Independent reference review verified all four quoted
aggregate numbers. Equivalent counting-unit wording is outside this numeric target.

Checks: source/transcription verification; one-edit invariant; equal assignment,
source, prompt/rubric and parameters across conditions; complete untruncated
candidate in actual model messages; no label access; original bytes unchanged;
meaningful offline harness tests for payload/isolation/failure receipts. Exact
outcomes and next discriminating decision recorded in verification019. Commit code
with configured author menglinsun@hotmail.com; keep private fixtures and run data
in ignored .analysis/.runs.
