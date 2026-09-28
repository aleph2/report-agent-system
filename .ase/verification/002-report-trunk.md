# Task002 verification and disposition

2026-09-27. First full-path implementation increment under confirmed v0.4.
Stage: end-to-end trunk construction. G2 and production/engineering acceptance remain open.
No provider requests, new OCR, engineering source uploads or legacy service changes occurred.

## Delivered scope

- `workspace.py`: immutable outcome tasks/results with server-bound ownership, actual
  input observation records, receipts, source issues and operator decisions.
- `report_runtime.py`: reusable ADK agent loop; coordinator chooses outcome tasks, not
  a fixed five-agent sequence. Text analysis is an optional bounded tool. A worker
  cannot delegate, escalate its role or write another owner's result.
- `models.py`: shared transient HTTP retries before any response, explicit attempts
  and failure audit; no hidden cumulative token/call quota.
- `webapp.py`, static UI and CLI: local desktop status, arranged-task progress, errors,
  human decisions, recovery entry and deterministic saved-draft DOCX export.
- Purpose/materials provided by the operator can be reused. Plans require observed
  purpose evidence, drafts require observed plan/materials, reviews observe the exact
  draft. These are result prerequisites, not mandatory agent invocation stages.

Main implemented backend, CLI, tests, integration and independent browser verification.
Averroes (UI worker, `01a0e261-f43f-77d1-b146-a601216956ca`) implemented the initial three
static files; Main reviewed and integrated them, adding explicit operator resolution,
real arranged-task progress and confirmed feedback receipt display.
Heisenberg (`01a0e055-b5c5-7802-953d-03afafcfac58`) independently reviewed alignment and
concrete code risks. This was a development review, not a report runtime expert stage.

## Evidence

Main ran the full suite using WSL Ubuntu-24.04, Python 3.12 in the independent venv:

`python -m pytest -q --junitxml=.runs/offline002/tests.xml`

Result: **48 passed, 2 warnings, 9.06 seconds**. Warnings concern ADK experimental tool
schema and Starlette's test-client httpx deprecation; no failing tests. JS syntax check
`node --check src/report_agent/static/app.js` also passed.

Tests cover project/owner isolation, observed inputs, immutable receipt replay, exact
review versions, purpose/materials reuse, failed-task recovery preserving the plan,
configuration errors, identical-action stagnation, shared transient retries, no retry
after partial response/auth/unknown error, atomic human-decision rollback via SQLite
trigger fault injection, both directions of review-status changes, system-versus-source
issue classification, local HTTP action protection, explicit HTTP execution, busy-lock
rejection, safe event tail, and DOCX text/source/version labels.

`scripts/run_offline_report.py --project .runs/offline002` traversed the actual ADK tool
dispatch with a scripted model: supplied purpose/materials, three arranged outcome
tasks (plan, draft, review), five saved results and a DOCX. This action sequence and
content are scripted fixture data; they do not demonstrate real-model planning or
semantic quality. The UI labels this mode and cannot launch provider calls for it.
`.runs/offline002-errors` is a separate synthetic error/human-input scenario.

Main browser verification used the real local UI and API, at 1440x1000 and 1100x900:
progress and error visible; logs collapsed; human input/focus survived polling;
submission was acknowledged and remained unresolved without explicit confirmation;
an HTML-shaped source string stayed literal (`#issues img` count 0); console warnings
and errors were empty on the checked page. Desktop document widths fit each viewport.
Screenshots: `.runs/offline002/ui-evidence.png` and
`.runs/offline002-errors/ui-evidence.png`. Temporary viewport overrides were reset.

Download button caused `/api/export/<saved-draft-id>` HTTP 200 and the UI displayed
download initiation. API tests parsed the returned DOCX successfully. Browser download
event/path capture timed out, so final browser-saved-file receipt is **not verified**.
No blind repeat download was used as evidence of success.

The packaged DOCX renderer was attempted with the bundled runtime. It failed because
`soffice.exe` is unavailable. Content/version tests pass, but visual Word layout is
**not verified**; no production formatting or engineering report acceptance is claimed.

Local preview retained at `http://localhost:18140/`, synthetic and provider-disabled.
Temporary error-test server on 18141 was stopped. Legacy 18082 was not restarted.

## Independent findings and Main disposition

All confirmed findings below are P2: they affected this prototype's reliable delivery
claims, not authorization of a signed engineering report. They blocked the named
verification claim while permitting contained offline construction and draft export.

1. Non-atomic human decision/revision: blocked crash-consistent invalidation. Fixed by
   one SQLite transaction covering issue, context revision, ready state and receipt.
   Fault-injection regression proves rollback. Reviewer confirmed the code correction.
2. Unread basis/target IDs accepted at submit: blocked the claim that necessary inputs
   were supplied. Fixed by checking server-recorded provided/read references. No extra
   model stage; no claim that observation proves semantic correctness. Reviewer confirmed.
3. Page/Word differing review choice and stale delivery: blocked consistent status.
   Both now use the latest committed review of the exact draft. Reviewer confirmed the
   central rule, then identified the reverse direction (rejected to accepted). Main
   corrected all delivery-state derivations and added a no-new-call reverse regression.
   Final reverse fix was verified by Main, not independently rerun by the reviewer.
4. System failure grouped as source shortage: blocked responsibility classification.
   Fixed distinct `system_error` versus `needs_human`, with matching export labels.
   Reviewer confirmed. Errors are not silently treated as missing user materials.
5. Receipt changed after additional reads: blocked idempotent replay of saved output.
   Fixed by comparing submitted content/provenance separately from later observations.
   Reviewer confirmed the code-level fix; Main tested persisted replay.

The reviewer did not execute tests or call models. Do not describe that review as full
production acceptance. Main retained the boundaries and did not add a compliance agent
to the application runtime.

## Remaining scope and risks

- New full-report real-model quality/autonomy has not been tested. Prior two-scenario
  live permission was consumed; this implementation approval did not expand it.
- Source inputs are immutable parsed-text manifests. Raw-file ingestion, large-document
  indexing/Graph retrieval and source replacement/affected-consumer workflow remain
  unimplemented. Correction requests are recorded and invalidate old review context,
  but a complete producer-correction closure interface remains future work.
- Recovery reconstructs useful saved state, not the exact old SDK/model conversation.
  Arbitrary in-flight network outcomes are not replayed automatically. Current retry
  scope is HTTP 408/429/500/502/503/504 before any yielded response, at most 3 attempts.
- Stagnation guard covers only repeated identical actions against unchanged state.
  It does not prove detection of semantically repetitive but differently worded work.
- P2 export verification gap: basic headings/paragraphs only; tables/templates/layout
  and the browser's final saved-file receipt are not accepted. Containment: synthetic
  draft labels and no engineering delivery; not a blocker for protocol prototype use.
- Local desktop prototype only. No remote exposure, multi-user authentication, mobile
  UI, user skill editing, self-evolution, concurrency or engineering sign-off.
- Default source-issue wait/continue policy remains undecided. Recording an issue or
  decision does not silently grant acceptance or change another producer's result.

Next decisive evidence is a newly authorized synthetic real-model full-report run,
followed by source/indexing and production export increments. Do not expand calls or
upload engineering originals without the applicable authorization.
