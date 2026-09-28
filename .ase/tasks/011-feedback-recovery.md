# Task011: Observational feedback and report recovery

2026-09-28. User authorized continuing, then explicitly continuing work until a
complete report is generated. Main implements/tests/runs; Anscombe independently
reviews boundaries. Use existing GLM5.3/high and authorized vision as needed.

Goal: resume Task009 from its native failure checkpoint and produce a complete
reviewed, exported report, preserving source/OCR reuse and uncertainty. Do not
restart all source processing or manufacture human decisions to finish.

Known P2: BusinessBoundary treats repeated signatures as proof of no progress and
raises a whole-run failure before executing the third call, blocking even receipt
recovery. Prior Task009 failure and Task010 local tests are the baseline evidence.
Keep original failure records; explicitly distinguish resumed work from prior work.

Smallest repair: remove signature counter/hard failure; detect only the last three
matching successful single-tool exchanges from native messages. Add a factual
observation to the next model request. Agent chooses the action. Do not rewrite
ToolMessage results, suppress tool execution, create a semantic classifier, enforce
ledger fields, allocate business-call quotas or prescribe a report workflow.
Changing inputs/observations, errors or intervening actions do not match. Existing
permissions, receipts, role ownership, errors, interrupts and checkpoints remain.

Verify native checkpoint recovery and feedback with scripted offline agents, with
counterexamples for changing observations and repeated receipt retrieval. Run an
isolated GLM probe seeded with three actual deterministic synthetic observations;
it must receive the diagnostic and make useful progress, not just end silently.
Then preserve a pre-resume evidence snapshot and resume Task009 once. Observe actual
results; continued looping is a diagnostic issue, not grounds for blind replay.

No legacy application edits, bulk OCR, automatic approvals, email or concurrent
report jobs. Source contradictions/missing materials remain human decisions. Any
human interrupt must be reported honestly; continue independent work only within
the application's supported capabilities and the user's existing scope.

G2 remains incomplete until a useful full report, exact-version independent review
and inspected export exist. Generation is not engineering sign-off. Test-only stop
boundaries do not become production limits. Independent review is a development
activity, not a new runtime stage.
