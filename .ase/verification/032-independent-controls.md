# Task032 independent synthetic judgment controls

2026-09-29. Designer and independent tester: `review_fork`. Main owns runtime
implementation, paid execution and integration. This record defines the oracle
before observing any Task032 model output. The tester made no paid calls, read no
credentials or private checkpoints, and changed no production code.

## Design and isolation

Read Task031's declared input/standard/verdict findings, current acceptance
storage/schema, actual grader prompt, Task032 declaration, and the
agent-prompt-design skill and its research note. Task031 supplies the diagnostic
questions, not answers for these controls. All names, records and reports here are
invented library-office material, with no highway source, score, site or report
language reused.

Fixture: `.analysis/task032/heldout_controls.json`, schema
`task032-independent-controls-v1`; SHA256 at completion:
`c682a82ff1258be8aed552d0cf516e579638a5b0e7c71285cc142a0635b9727d`.

The `model_visible` object contains the commission, scope, sources, paired criteria
and candidate reports. The sibling `evaluator_only` object contains labels,
rationales, mutation descriptions and oracle arithmetic. The harness must extract
only `model_visible` into its separate input file; do not supply the complete
fixture, this verification record, expected labels or later evaluation feedback to
the grader. Native storage assigns criterion IDs; the evaluator joins them to the
four ordinal positions outside the model context.

The first three candidates have the same commission and exactly the same three
sources: registry, personnel/review roster and applicable scheduling rules. The
fourth has those identical sources plus one explicit addendum completing one
genuinely absent duration. It is a genuine full-pass control, not an assumption
that the missing value happened to be favorable. Comparisons across arms within a
case hold the source set and report fixed; case04's source addition is deliberately
not a single-factor report-edit comparison with case01.

## Criterion identities and independently checkable labels

The criterion order is scope coverage, numerical fidelity, source/internal
consistency, then the all-items duration threshold. Both criterion sets use only
the existing input fields. Their `condition`, `scope` and `requirement_refs` are
identical for each ordinal. Expanded evidence/limitation wording spells out the
same commissioned outcomes and three-state boundaries; it adds neither a business
requirement nor a required tool sequence.

| Case | Scope | Numeric | Consistency | All-items threshold | Overall |
| --- | --- | --- | --- | --- | --- |
| packet_01 | satisfied | satisfied | satisfied | undetermined | undetermined |
| packet_02 | not_satisfied | not_satisfied | not_satisfied | undetermined | needs_revision |
| packet_03 | satisfied | satisfied | not_satisfied | undetermined | needs_revision |
| packet_04 | satisfied | satisfied | satisfied | satisfied | satisfied |

There are nine positive, four negative and three genuinely unresolved item labels
across sixteen decisions, not sixteen independent cases.

- **packet_01:** faithful bounded compilation. Eligible IDs are P-17/P-28/P-39/P-44.
  P-52 is at another location, P-63 belongs to an archived earlier batch. The two
  known pending review statuses are honestly retained. P-44's registry duration is
  truly absent; its missing duration is not a report defect when accurately shown.
  It prevents confirming the separate all-items scheduling threshold.
- **packet_02:** the main table omits P-44 because of missing duration and includes
  P-52 merely because it shares batch/status, violating the commissioned scope.
  It assigns P-17's raw14.96 to the15.00–<30.00 band based on its rounded display.
  It also says every listed packet completed review despite P-39 being pending
  both in its table and the source. These are three located failures, not guesses
  about incomplete investigation. Its separate threshold statement remains honestly
  unresolved; the other defects do not prove an actual duration breach.
- **packet_03:** scope/numeric data are accurate, but P-28's owner is called absent
  while the report admits not searching the roster. The roster supplies the owner
  as许宁. This is a correctable compilation error, distinct from the genuinely
  absent P-44 duration. Asking the user to supply an already available owner does
  not make that field unknown in the source package.
- **packet_04:** the addendum supplies P-44's raw duration22.48, displayed22.5 and
  correctly assigned to the standard band. All four raw durations are individually
  below30.00, so the separate threshold is now established. The same two pending
  personnel checks remain disclosed and do not violate the commission.

Rounding is a deliberate false-positive control: raw14.96 is light although
displayed15.0, raw15.00 is standard, and raw29.96 is standard although displayed30.0.
The source explicitly requires unrounded classification and decimal half-up display
rounding. Criticizing the raw29.96/standard combination solely because display30.0
reaches an endpoint is an erroneous rejection. Conversely, a plausible rounding
explanation does not excuse packet02's14.96/standard assignment.

The fourth criterion assesses the commissioned business threshold itself, not
whether the document correctly says that it remains unknown. This distinction is
explicit in the shared commission and in both criterion sets. Missing one genuine
measurement with no contrary measurement yields `undetermined`; an accurately
limited draft may still satisfy the other three standards. The full-source case
demonstrates that a complete positive verdict can also be correct.

## Smallest credible comparison and interpretation

The declared matrix is four cases × three arms × two repetitions =24 direct native
grader assessments. Arms are baseline criteria/original grader, clear-boundary
criteria/original grader, and clear-boundary criteria/clarified grader. One fresh
state per cell prevents previous decisions contaminating another assessment. Hold
model, parameters and evidence tools constant, freeze both prompts before calls,
and preserve the actual scheduled order. Reverse each case's original arm order
on the second repetition rather than accidentally keeping the same arm first.

This yields96 per-criterion observations, but only four independently designed
synthetic cases. Report paired counts by case/repetition and each error type:
missed established defect, false rejection, unjustified uncertainty, unsupported
positive certainty and unsupported negative certainty. Check public explanations
and source relationships, not only labels. A correct overall `needs_revision`
does not excuse a false numeric accusation or a missed separate contradiction.
If all arms already solve these small cases, report the ceiling and no demonstrated
gain; do not modify cases or labels to manufacture an improvement signal.

The separately declared fresh full trunk must use actual coordinator-produced
standards and author output. These fixed diagnostic criteria/reports are not proof
of autonomous standards creation, report generation, repair or highway reliability.

## Offline checks and harness inspection

Checked with the installed runtime's `AcceptanceCriterionInput` and Python Decimal:
all eight criteria validate; the shared condition/scope/reference fields match;
the completed source set is the common set plus only its addendum; every source
has exactly id/title/coverage/content; all four raw/display/band oracle triples
match decimal half-up arithmetic; expected aggregate outcomes and label counts
are consistent. Model-visible serialization contains no oracle keys or expected
aggregate labels. This is deterministic fixture validation, not model-quality
evidence.

Read `scripts/run_acceptance_boundary_diagnostic.py`. Its `load_inputs` rejects
unexpected top-level/source/case fields, and its grader construction reads only
the preprocessed model-visible file. It saves criterion IDs, the actual selected
report, export/context bindings and the arm's effective prompt. No evaluator-label
load path was present in the inspected harness. Main must retain the separate-file
preprocessing boundary; passing the full fixture is intentionally rejected.

The direct harness invokes the native grader graph rather than `_agrade` or the
outer `FeedbackRubric` revision loop. Consequently it does not exercise native
coverage-correction retries or author revision. Exact-ID coverage failures must be
reported as contract failures and excluded from ordinary semantic scoring, not
silently mapped to pass/fail. Its purpose is judgment diagnosis; full-loop evidence
comes from the separately declared trunk.

No new production bug is established by this fixture work. The initially inspected
schedule kept the same arm first across a case's two repetitions; Main was notified
before calls so it could improve counterbalancing. The chosen final order must be
recorded and not changed in response to scores. This is experimental-design scope,
not a reason to stop unrelated development or to claim a model failure.
