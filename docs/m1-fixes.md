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

## G3 rules discussed, implementation deferred

Indicator bases are evidence, a stated guideline rule applied to facts, or a
labelled and justified assumption with a material-issue record. Unjustifiable
values remain unresolved. Sensitivity considers joint feasible extremes of all
assumptions with adopted weights fixed, not merely one-at-a-time changes.
Every slope must be checked under the agreed eleven-indicator method; the old
eight-indicator S1 score cannot establish which new results need qualification.
Qualified delivery completeness is distinct from engineering sign-off.
