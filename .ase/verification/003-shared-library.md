# Task003 verification and disposition

2026-09-27. Independent application only. Stage: end-to-end trunk construction;
G2 real-model/engineering acceptance is not claimed. No provider calls, OCR, original
engineering uploads, legacy application/configuration/data changes or concurrent
report execution occurred.

## Delivered increment

- Original bytes, extracted text, located blocks and import receipt commit together
  in the project's SQLite store. Exact upload replay returns the same source version.
  Explicit replacement requires the current version; old source IDs remain readable.
- TXT/MD UTF-8, DOCX body/table and PDF page text intake. DOCX/PDF are always marked
  partial, with limitations. Empty/encrypted/corrupt/over-limit input is rejected, not
  silently truncated. No OCR or remote resource fetching.
- Literal source retrieval uses full extracted text and maps matches to located
  windows, including matches crossing artificial 4,000-character boundaries. Paging
  exposes remaining data. Result search returns metadata; selected results have paged
  reads. The coordinator initially receives metadata rather than every result body.
- Corrections route to server-bound original producers. New immutable result,
  replacement relation, correction receipt and task completion are atomic. Late
  correction requests remain visible on the current replacement; no automatic reruns.
- Known source/result consumers become outdated transitively. Historical comparison
  reads are distinguished from active references. Newly relevant sources can mark
  selected existing outcomes affected; unrelated additions do not force re-planning.
  Human source decisions remain separate from coordinator relevance assessments.
- Domain action rejections return as tool observations, allowing the agent to correct
  its request. Unknown exceptions still propagate. No relaxation of role permissions,
  hidden retry loop, mandatory semantic stages or cumulative model-call quota.
- Desktop UI exposes library intake, source versions, parser limitations, full-text
  paging, paged search, correction requests and outdated/replaced results. Uploads,
  queries, correction recording and status polling do not launch model work.

## Roles

Main: catalog, runtime, API/CLI/export integration, end-to-end fixtures, tests,
deployment and independent browser verification.
Halley (`01a0e2a9-b34b-7513-af1a-5f4757db91bd`): parser and 32 parser tests.
Feynman (`01a0e2a9-b636-7850-96a2-bd0394ecdaa9`): workspace correction/impact and tests.
Sartre (`01a0e2ac-7a4c-7082-b6f1-60153efb70e9`): desktop UI design and implementation.
Sagan (`01a0e2a9-b8c6-7192-9289-9e1a80b890d8`): independent read-only alignment review,
early design and concrete final fixes. This is development review, not a runtime stage.

## Evidence

Main ran the independent WSL Python environment:

`python -m pytest -q --junitxml=.runs/task003-tests.xml`

Final result: **120 passed, 2 warnings, 35.35 seconds**. Warnings are the existing ADK
experimental schema and Starlette test-client deprecation. Node syntax check passed.
Reviewer confirmed final code fixes; Main ran final tests. The reviewer's last XML
read preceded the final 120-test run; do not claim the reviewer independently ran it.

Tests include raw parser formats/order/limits, exact source receipts, replacement
conflict, original-byte preservation, pagination, historical/current search, cross-block
matching, observed versus metadata-only reads, fault-injected transaction rollback,
role/target immutability, concurrent receipt replay, producer old/new comparison,
late feedback, selected impact from new sources, unrelated source reuse, known-domain
feedback recovery, unknown exception propagation, and analysis success/cache/failure
observation distinctions. Existing model retry, report, API and export tests remain.

`scripts/run_offline_library.py --project .runs/offline003-verified` persisted the actual
ADK tool dispatch with a **scripted** model: source intake -> initial plan/material/
draft/review -> source replacement -> producer material and draft replacement -> exact
new review/export -> unrelated addition assessed without re-generating anything.
Result: 7 arranged tasks, 8 saved results, 4 source versions, reviewed synthetic draft.
The plan was reused; old source/report text stayed unchanged. The current Word contains
the new hours, not the old hours. Final full-suite tests repeat this path on final code.
The protocol sequence and text are scripted, not model autonomy/semantic-quality proof.

An earlier `.runs/offline003` attempt hit an integration TypeError while the source
assessment signature was still being changed. It is preserved as failed evidence.
It was not a provider failure, engineering task or successful trial. No blind replay
into that state was used; the verified trial has its own isolated directory.

Browser evidence (Main, real page/API):

- 18140 showed 7/7 arranged tasks, current/historical sources, replaced results and
  closed producer correction. Search returned the current hours; historical read
  returned the old hours.
- A SQLite backup into `.runs/offline003-ui` was used on temporary 18141 for destructive-
  free UI testing, so the retained example's accepted state was not contaminated.
- Uploaded only `examples/library-browser-check.txt`, received a source ID and visible
  unassessed-change warning. No tasks/provider calls were automatically added.
- Read pages 1-10 then 11-13; search pages 1-10 then 11-12. HTML-shaped source content
  stayed literal; `#source-blocks img` count was zero.
- A correction request showed an acknowledged pending receipt and the planner owner,
  while the original result remained intact. Logs remained collapsed.
- Desktop checks: 1440x1000 and 1100x900, document widths within viewport; no captured
  console warning/error. Keyboard activation worked. CUA mouse activation/filechooser
  initially had no effect; keyboard chooser worked. This is not attributed to an app bug.
- `browser-upload.png` in the UI test directory records the changed UI. Final overview
  is `.runs/offline003-verified/browser-overview.png`.
- Download UI initiated the exact saved-draft export; server returned HTTP 200. Browser
  download-path event timed out, so a final browser-saved-file receipt is not verified.
  The separately persisted DOCX and API output were parsed by tests. No blind re-send.

Final deployment: `http://localhost:18140/`, `.runs/offline003-verified`, explicitly
scripted/provider-disabled. Restarted this service after the final fixes. Temporary
18141 stopped; test databases/evidence retained. Legacy 18082 untouched.

## Review findings and Main disposition

All confirmed issues below are P2: they blocked the named reliability claim, not
contained synthetic testing or marked draft export. No P0/P1 was identified in scope.

1. Related new source without old consumers could restore an old reviewed delivery
   after a description-only assessment. Fixed explicit affected-result roots and
   transitive invalidation; empty reassessment cannot erase established impact.
   Unrelated additions still preserve useful outcomes. Regression and reviewer check.
2. Domain feedback initially caught all ValueError/PermissionError, including internal
   failures. Fixed explicit ActionRejected/ActionForbidden types. Unknown failures
   propagate; synchronous/asynchronous regressions. Reviewer confirmed code.
3. Analysis failure could leave a successful read footprint. Fixed observation only
   after success or cache hit, with analysis-result extent and reuse flag. Failure,
   success and cache regressions; reviewer confirmed code.
4. Literal match could disappear across artificial chunk boundaries. Fixed full-text
   match mapped to windows with every returned ordinal. Count is distinct starting
   blocks, not occurrences. Cross-boundary regression; reviewer confirmed code.
5. Historical reads could poison producer replacement freshness. Fixed separate
   history observations; current adopted references still checked. Old/new comparison
   and immutable receipt recovery regressions; no permission expansion.

Main accepted the fixes within the current increment. Sagan's final scoped review
found no new material blocker. This does not certify semantic correctness of declared
evidence, expert choices, every future input or engineering sign-off.

## Remaining boundaries

- New real-model full-report validation still needs authorization; no additional paid
  trial permission was inferred from development continuation.
- Literal scan is a transparent baseline, not semantic Graph retrieval. Large-corpus
  scaling is not benchmarked. Source catalog/GUI status still load full records in
  parts of the backend; assigned result bodies are still supplied in full to workers.
- Observations prove which version/text was returned, not comprehension or semantic
  adoption. Source declarations are not independently proven factual evidence links.
  Source contradiction/missing information still goes to humans; the general policy
  for pausing versus continuing with caveats remains undecided.
- Parser limits are explicit but post-decompression PDF checks are not a hard memory
  sandbox. Containment: local trusted-input prototype, 20 MiB upload cap, no network,
  no multi-user exposure. A hostile-input public service needs stronger isolation.
- No OCR, image understanding or faithful Word/PDF layout extraction. No production
  Word template/layout acceptance; visual rendering remains unverified without
  LibreOffice. No engineering sign-off, mobile UI or user Skill editor.
