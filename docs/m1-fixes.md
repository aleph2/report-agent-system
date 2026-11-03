# M1 fixes and review gates

Current authority: [the owner's updated M1 fix plan](m1-fix-plan-current.md),
received 2026-11-02 America/Tijuana, supersedes the matching older requirements
below. G3 implementation is authorized; its current status is inspection/design,
not implemented or verified. G4 approval still precedes paid/provider calls.
Email polling and sending were stopped by a later direct owner instruction.
Earlier G1/G2 results and restrictions below remain historical evidence.

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

## G2 review followup: scoped source replacements and template staging

The owner's updated review resolves the prior source-policy question through the
existing scope document, section 4: this stage uses the supplied first-contract
materials. The original G2 source-gap evidence above is historical; it is not a
new demand to supply whole-project documents or repeat the same scope approval.

Each proposed source replacement retains the requested document name, actual
replacement citations, exact quotation from the trusted commission source, and
a separate agent explanation. Resolution is local to its section. Forged quotes,
non-customer authority, undeclared replacement pages and deleting prior source
obligations are refused. A replacement creates a new plan version; the ordinary
owner checkpoint still confirms that exact version before writing. Structural
provenance checks do not prove that a replacement is semantically sufficient.

Chapter 2 can cite the actual roadbed design notes and survey general notes.
Section 1.3 can cite the design tables and survey work-point/support records,
retaining their differences. Four detailed survey reports are not a four-object
inventory: support records exist separately. The offline proposal retains five
design candidates, unknown attributes and unresolved mapping differences; it is
not an approved or engineering-verified inventory.

The checkpoint headings are Chinese. Snapshot outcome lookup uses a bounded
indexed key range. Optional repeatable `stage_report.py --template PDF` accepts
explicit template PDFs without moving originals; normal hashes, PDF profiles,
resource checks and collision refusal apply. See `pilot-inputs.md` for staging.

Bounded limitation: this patch implements source replacement, not discovery of
an originally requested document. A later original-source resolution needs its
own explicit path; it must not be mislabelled as a replacement. Automated copying
and checking of fixed template text remains G3. The existing Windows-mounted
WSL case was identified as 9p; native Linux case/ledger placement still needs
verification before G4. No live case or financial ledger was migrated or reset.

Evidence is in `.analysis/m1-g2-followup-20261102/`: preserved failing tests,
focused checks, independent Neo/alignment reviews, and versioned real-source
proposal records. No paid calls, report rerun or G3 work is included.

## Earlier G3 discussion — superseded by the updated owner plan

Indicator bases are evidence, a stated guideline rule applied to facts, or a
labelled and justified assumption with a material-issue record. Unjustifiable
values remain unresolved. Sensitivity considers joint feasible extremes of all
assumptions with adopted weights fixed, not merely one-at-a-time changes.
Every slope must be checked under the agreed eleven-indicator method; the old
eight-indicator S1 score cannot establish which new results need qualification.
Qualified delivery completeness is distinct from engineering sign-off.

## Current G3 requirements — implemented and accepted for offline review

- Use reviewed method-pack data for guideline Tables 3-2, 3-3 and A.3-1,
  the format-standard Word layout and the fixed-text template. Link numbered
  scope conventions to entries in the checkpoint brief. A required missing
  entry blocks writing; a guideline default is labelled `默认，未约定` for
  owner review. Precedence is scope, outline, guideline defaults, template.
- Weight-strategy authority is the end user's current `报告编写范围说明`,
  not a hard-coded system policy or this development plan. The agent reads
  the supplied version, records the exact convention separately from its
  interpretation, and links the selected strategy to available method data or
  calculation capability. The system executes and validates that selection.
  The updated M1 plan describes Table A.3-1 lookup as this commission's selected
  strategy; verify it against the actual updated scope file before binding it.
  Verified table data may be prepared, but neither its selection nor the listed
  eleven weights becomes a universal rule. Do not silently recalculate or
  normalize table values when the scope selects direct lookup. A missing
  capability remains an explicit checkpoint question, not an improvised rule.
- Every indicator has a value and a direct-evidence, applied-guideline,
  indirect-assumption or no-evidence-assumption basis. No-evidence assumptions
  are the last resort and take the less favourable grade. When indirect evidence
  supports several grades equally, take the less favourable grade. Template scores are
  never factual evidence. Both assumption classes create anchored Word comments
  and matching filterable Excel rows, with no-evidence cases first.
- Joint low/high plausible values use the same adopted weights. If the level
  can change, qualify each statement of that slope's level in chapters 4 and 5
  and flag the comments; otherwise comments and Excel rows suffice. Properly
  recorded assumptions count as assessed, not engineering sign-off. Calculation,
  content and required export checks still have to succeed.
- The commissioned scope is five deep-cut slopes in the first contract section.
  Record its sourced mileage boundary; only proven outside-range objects are
  out of scope. Preserve in-range discrepancies and unknowns. A count other
  than five requires an owner question, not deletion or invented objects.
  This scope decision does not itself approve the existing real proposal.
- G3 retains all Steps 4–5: verified tables/calculations, fixed-text extraction
  and controlled replacements, the complete Word format, material issues,
  matched Word/Excel output and export refusals. Full-suite/scripted whole-run
  acceptance remains G4. Fresh staging of changed source bytes and native Linux
  case/ledger placement with a filesystem guard remain pre-rerun requirements.

The updated scope file has been read: §5 item 3 explicitly selects Table A.3-1.
Guideline physical pages 18–24 and 91 were visually checked and transcribed;
source hashes and format-source locators are preserved in the G3 evidence folder.
Suggested scope conventions 7 and 8 are not asserted
to exist in that file; the owner's plan decisions 1 and 3 apply meanwhile.

Owner clarification after supplying the updated plan: the end user changed the
scope document to define weight selection. This supersedes any interpretation
that the development team must predefine that selection in the system. Preserve
the customer-authored file and bind any saved interpretation to its exact version;
an updated source must not silently inherit an older checkpoint approval.

G3 code and offline artifacts passed independent review. See
[the verification record](m1-g3-verification.md) for focused batches, exact
Word/Excel pairing, source-view checks and contained P2/P3 limitations.
`m1-fixes-20261102-g3` is the offline review tag, not a formal report acceptance.
G4 approval is still required before paid/provider calls or a real report rerun.
