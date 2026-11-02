# M1 fixes and review gates

The owner authorized G1 (reliability/storage) followed by G2 (requirements,
inventory and customer checkpoint). Each gate ends with a pushed review tag.
Pause after G2 for owner review before G3. Provider checks and the real rerun
remain prohibited until G4 is approved. Original M1 data and unknown financial
reservations must remain intact.

## G1 behavior

- Runtime project stores require WAL and use FULL synchronization. The initial
  SQLite busy timeout remains 15 seconds; at most two short additional waits
  retry only the same SQL statement or commit. A stale WAL snapshot rolls back
  rather than retrying an invalid transaction.
- Local lock failures are explicit tool results. Existing operation IDs and
  receipts remain authoritative. After external work, persistence failure leaves
  an unresolved outcome and is not permission to repeat the external call.
- New source originals are immutable files at `blobs/<prefix>/<sha256>`.
  Database metadata contains a relative path, size, media type and hash. Readers
  verify bytes; historical BLOB rows remain readable without migration.
- Large public prompt captures use the same file store, retaining their logical
  capture keys and verified read API. Small response facts stay queryable in
  SQLite. Private reasoning and image bodies retain their existing redaction.
- Explicit `Catalog.collect_unreferenced_blobs()` refuses while a run/import
  holds the project lock. It also synchronizes with capture publication. There
  is no automatic deletion or original-case migration.
- The host no longer duplicates full prompt histories into the events table;
  immutable public prompt captures and native checkpoints retain the evidence.
- Preparation and both fresh-launch paths verify referenced blobs before provider
  setup. The launcher uses the pinned staged verifier in an isolated interpreter.
  Nonempty WAL is refused without checkpointing: the main database hash alone
  cannot pin changes that remain in WAL.
- `scripts/report_metrics.py CASE` reads `CASE/runtime-metrics.jsonl`, not the
  live database. Counters distinguish logical invocations, agent turns, physical
  usage attempts and tool rejections. Missing usage is unavailable. Summed
  invocation time is not elapsed wall time when calls overlap. Metrics do not
  replace the financial ledger or establish replay authority.

## Verification scope

New tests exercise real SQLite contention, WAL startup refusal, stale snapshots,
same-transaction commit recovery, rollback without cached transient failures,
native tool continuation, and prevention of external-call replay. Storage tests
cover exact bytes, hashes, paths, legacy reads, corruption, capture identities
and cleanup boundaries. Metrics tests prohibit SQLite reads and check privacy,
deduplication, missing data and truncated logs.

Local evidence is retained under `.analysis/m1-fixes-20261103/` (the directory
name is an identifier, not the execution date). The initial G1 batch failed
14 tests and passed the legacy-read test before implementation; its first repair
passed all 15. Extended capture tests separately reproduced three failures on
frozen baseline 760b035. The expanded G1 candidate passed 323 focused tests.
Additional tests were authored during implementation; they are not claimed as
all preceding the production changes. The complete suite and scripted whole
report acceptance remain G4 work.

After independent review, 22 storage/durability tests passed. Launch-gap RED
reproduced 13 failures, and a separate committed-WAL RED reproduced two failures.
The final launch/preparation/restore batch passed 43 tests with no failures,
errors or skips, including all three WAL scenarios. These batches overlap and
must not be summed as unique tests.

The same ten real M1 files were imported into separate fresh cases using baseline
760b035 and G1. All original bytes were read back and hash-checked. The database
fell from 409,800,704 to 5,586,944 bytes (98.64%); total case storage was
409,800,704 versus 409,417,694 bytes. This moves file bytes out of SQLite; it does
not claim to eliminate them. The new case used WAL and passed integrity_check.
The original stopped M1 case was not migrated or changed. These are import-only
measurements, not a prediction of a complete report run's database size.

Offline storage measurements distinguish database bytes from total case bytes.
Font-decoding warnings from the existing PDF parser are retained; matching
original hashes is not evidence of correct text extraction or engineering
interpretation. No real-model acceptance or sudden-power-loss test is claimed.

## G2 boundary

Source-linked requirements, section plans and assessment-object inventory must
precede writing and bind to the owner's confirmed version. Delivery checks
extend existing coverage accounting: an omitted object or unaccepted scope
reduction remains incomplete. Reviewer acceptance of a limitation cannot cancel
a customer requirement. G2 does not implement the G3 scoring or export redesign.

## G2 implementation and review candidate

`commission_plan.py` stores immutable source-linked section plans, exact customer
quotations separately from interpretations, declared inventory attributes, and
every known object as an existing Requirement record. Unknown values and
conflicting alternatives remain visible. Required attributes are commission data,
not a product-specific slope schema; the M1 fixture declares mileage, side,
length, height, type and soil/rock. New plans cannot silently remove known objects.

The coordinator saves a proposal and requests the existing native human interrupt.
The generated brief and adjacent JSON show the exact plan reference and reply
shape. The trusted operator responds using:

```text
report-agent commission-reply --project CASE --issue-id ISSUE_ID --file DECISION.json
```

Only that structured operator reply can approve the exact version or explicitly
reduce named objects with reasons. Generic human-answer prose cannot authorize
writing. Missing named section sources remain `pending_sources`; approval is
refused until those sources are supplied or an explicit substitution is recorded
in a revised plan. Corrections require a new proposal and confirmation.

Writer assignments bind selected section rows. Delegation, generation before its
helper call, and ContentNode saving all enforce the current confirmation. The
host waits inside its original token-budget/observer scope and resumes the same
workspace through native checkpoints; waiting does not restart the host, reset
the ledger or replay unknown reservations.

Snapshots automatically include confirmed inventory Requirements and source
closure. Each writer records its own saved section/score/level/basis references.
Matching outcome references are frozen into the snapshot and digest; another
writer's draft cannot alter the selected snapshot's completeness. Ambiguous
matching outcomes are refused. Reopening an outcome affects a newly frozen
snapshot, while the old snapshot retains its original evidence. Missing or
unresolved objects propagate `incomplete` through delivery, project state,
runtime, CLI exit status and the host receipt. This is structural coverage, not
an eleven-indicator calculation or engineering approval.

The host uses a neutral commission frame and records optional supplied templates
with purpose `template`; conventions come from the scope document. The obsolete
tool-discovery profile is removed. Existing real-input/hash checks and the
100M-per-run/200M-total M1 limits remain in place.

### Real-source evidence and remaining acceptance gap

The private offline fixture reuses the fresh G1 source cache in an isolated case
and separately imports the authorized template PDF. All ten input hashes and
the template hash are recorded. It saves six fixed sections (1.1, 1.2, 1.4, 3.1,
3.2, 6), extracted sections 1.3/2/4, and chapter 5 derived from chapter 4. Fixed
text is linked to actual template pages, and the design-priority convention is
quoted from the actual scope file. Five design-drawing candidates retain all six
attributes; untranscribed values are explicitly unknown, not fabricated or
declared absent from the originals.

The named `第一册第一分册 施工图总说明` and `平面总体布置图设计说明` were not
located in the inspected material. Roadbed design notes, geological general
notes and local slope plans are not silently renamed to fill that gap. The
fixture preserves these pending sources and verifies approval refusal. Thus it
proves record behavior and honest missing-source handling; the original plan's
real-data criterion that every section has its named source remains incomplete.
This blocks approval/writing of that real commission, not publication of this
offline code-review candidate. Owner source clarification is pending.

Private evidence is under `.analysis/m1-fixes-20261103/`: preserved RED tests,
focused JUnit/logs, independent Neo and alignment reviews, the real-source
mapping, `g2-real-plan.json` and `g2-real-acceptance.json`. Original M1 state,
financial unknowns and source files remain untouched. Full-suite, scripted whole
report, provider acceptance, visual fidelity and report quality remain G4 work.

Final focused regression: **249 passed, 0 failed, 0 errors, 0 skipped**, in
220.72 seconds. The 24 reviewed source/test/config file hashes remained unchanged.
The earlier 247-pass/one-failure run is preserved: its subprocess could not import
a test helper because `tests` was missing from PYTHONPATH. The final environment
uses `PYTHONPATH=src:tests`. Independent Neo and alignment reviews found no
remaining critical code issue in the inspected scope. These overlapping batches
are not a new full-suite count.

## G3 rules discussed, implementation deferred

Indicator bases are evidence, a stated guideline rule applied to facts, or a
labelled and justified assumption with a material-issue record. Unjustifiable
values remain unresolved. Sensitivity considers joint feasible extremes of all
assumptions with adopted weights fixed, not merely one-at-a-time changes.
Every slope must be checked under the agreed eleven-indicator method; the old
eight-indicator S1 score cannot establish which new results need qualification.
Qualified delivery completeness is distinct from engineering sign-off.
