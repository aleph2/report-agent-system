# Task011: feedback and native recovery

2026-09-28. Main implements/tests; independent boundary reviewer Anscombe
(`01a0e33c-c20e-7493-b090-1912cc5cf60f`) reviewed design and implementation.
User explicitly requested continuing work until a complete report is generated.

## Implemented scope

Removed BusinessBoundary's counter/signature hard failure before the third tool
execution. Added a temporary model-request system observation when the last three
complete single-tool AI/ToolMessage pairs have identical tool names, arguments and
successful content, with matching call IDs. Native messages are not modified.
No result normalization, semantic progress judgment, tool-result mutation, suppressed
execution, custom state persistence or business-call quota. Changing observations,
errors, missing/mismatched receipts and intervening actions do not match.

Tools, server permissions, committed-result ownership, receipt recovery, original
error handling and human interrupts remain unchanged. Detecting identical content
does not prove lack of progress. The agent chooses what to do with the observation.

## Local verification

Focused tests: 74 passed in62.15s, command:
`python -m pytest tests/test_deep_runtime.py tests/test_deep_models.py tests/test_calculations.py -q`

New cases include six nonmatching-history counterexamples, actual native recovery
from a simulated old third-call failure, temporary notice observed by a scripted
agent followed by draft creation, and three same submit requests returning one
durable result. These scripted tests prove protocol, not autonomous convergence.

Full regression completed: `python -m pytest -q`: 548 passed, 9 skipped,
one Google ADK experimental-feature warning, 162.00s. Skipped cases are not
claimed as passed or as live-model validation.

Authorized GLM5.3/high synthetic probe:
`.runs/task011/repetition-probe`. Historical fixtures contain four calculations:
one A and three identical B calculations. The initial trial_intent mistakenly
recorded2; a later trial_metadata_correction preserves and corrects this to4.
The shared test harness now derives this count from the seeded ToolMessages.

Actual result: first live request contains the repetition notice; three live
responses choose calculate, calculate, submit_result, producing a correct A=14/B=34
draft. Thus the agent did two extra calculations before progressing, not immediate
reuse. No new todo/scratch update in this probe. All historical/replayed calls are
distinguished from these live actions. Checkpoint projected state survives reopening.

Only one notice occurred: fixture JSON field ordering differs from actual tool JSON,
so subsequent mixed fixture/live tails do not match byte-for-byte. This is the
intended exact-comparison limit, not proof equivalently repeated work was absent.

Anscombe found no blocking issue for a single original-checkpoint resume. Residual
P2: a soft notice does not guarantee convergence. No automatic repeated restart;
inspect actual ongoing work. Semantic convergence, long-context improvement and
engineering quality remain unproven by this short probe.

## Native resume evidence

Original Task009 inspect: checkpoint `1f1bae15-80c0-6187-8174-a8dcbdc7543b`,
next tools,248 messages,0human interrupts, pending third calculate.
Closed original process verified before copying state.db/checkpoints.db to
`.runs/task011/pre-resume-evidence`. Original/copy SHA256 matched:
- state.db: f53dfb385d134f65eaa5e34a96a3ab891f8177c4ae378c027ef3802545e47832
- checkpoints.db: bd667bdd96fa1a9cf5ca89d97db13dd36c253e0767658d7d1a974c3c5da49d8f

Appended task011_resume_intent at original event507, including user authority,
checkpoint, runtime hash and no OCR reprocessing. Started one `--resume` against
`.runs/task009/autonomous-report`, not a new full report. No source edits/imports,
legacy changes, GUI restart, email, human answers or original evidence deletion.

Events509-513 at02:59:29-30UTC show native resume, completion of the pending calculate,
actual repetition observation, and the next coordinator request. This confirms
the old failure point is passed; it is not report-completion evidence.

Report outcome, exact final review and export/content inspection are pending.

Further observation: event543 at03:04:24UTC updates native todos, marks scoring
complete and report drafting in progress; event547 reads the outline. Calculations
also continue after this. There are still no committed results at this observation;
a todo claim is not independent verification of the scores or report completeness.
The held-out content reviewer is checking whether provisional scoring remains
properly distinguished from the owner's still-pending scoring-system confirmation.
