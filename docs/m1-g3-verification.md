# M1 G3 verification

Status: G3 implementation, independent code review and offline artifact inspection
accepted as a review candidate. Publication tag: `m1-fixes-20261102-g3`.
This is not acceptance of a formal engineering report.

The current owner-approved development plan is [m1-fix-plan-current.md](m1-fix-plan-current.md).
The customer scope document selects the weight strategy. Prepared guideline data
does not select itself or override a customer's convention. No paid/provider
call or report rerun is authorized before G4 approval. Email polling is stopped;
the owner separately authorized one completion email after publication.

## Implemented behavior

- Reviewed source-bound method data covers all eleven indicators, forty-four
  grade rows, source notes, risk bands and twelve rank-weight lookup rows.
  Exact source hashes and reviewed data are checked before use. Generic method
  data requires an explicit host-side review record, unavailable to runtime agents.
- The confirmed commission records exact customer quotations, separate agent
  interpretations, selected method links and labelled defaults. Missing method
  or format capabilities remain checkpoint questions. Sourced contract bounds
  retain uncertain/in-range objects; only proven outside objects leave scope.
- One saved assessment validates every grade, value, basis and rank, then
  calculates products, totals, levels and joint sensitivity using Decimal.
  A no-evidence assumption cannot narrow its uncertainty to the adverse grade.
  Template scores and customer instructions cannot masquerade as factual evidence.
- System-generated ranking/evaluation tables and result nodes have immutable
  receipts. Derived summaries use those same saved results and qualifications,
  with counts taken from the exact commissioned assessment set. Missing objects
  remain incomplete; documented assumptions do not require pretending to have
  engineering sign-off.
- Source-derived fixed text permits only declared literal substitutions.
  Approved, page-bound source views preserve original PDF method tables while
  retaining the exact canonical text. Crop identities and completeness were
  checked for this fixture; the system does not infer semantic crop coverage.
  Generated assessment tables remain editable Word tables.
  The explicitly selected, reviewed format supplies margins, typography,
  headings, cover/title pages, headers, footer and a three-level TOC.
- Material issues anchor exact adopted values in Word and produce matching,
  filterable Excel rows, with no-evidence assumptions first. The linked Word
  asset must exist and pass its hash check. Working notes stay out of exports;
  internal fields, wrong sources, altered fixed text and unchecked Excel
  selections are refused.

## Verification evidence

Evidence remains under `.analysis/m1-g3-20261102/`; raw project source materials
and validation artifacts are not committed to Git.

| Focused batch | Result | Evidence |
| --- | --- | --- |
| Scoring, method data, commission, persistence, scope and source views | 141 passed | `neo-source-view-green-18.log/xml` |
| Existing commission, shared-store, saved-reference and calculation regressions, repeated after source-view changes | 116 passed | `main-regression-final.log/xml` |
| Native export adapter and existing layout regression | 15 passed | `neo-tool-adapter-green-11.log/xml` |
| Typography, layout and saved-layout reuse, including finalized duplicate bookmarks | 63 passed | `neo-anchor-green-13.log/xml` |
| Source-selected presentation, source-view receipts and table widths | 35 passed | `source-presentation-view-source-green.txt` |
| Export comments, workbook, merges and source-view rendering | 35 passed; four exact-image cases checked separately | `export-source-view-green.txt`, `export-source-view-exact-green.txt` |

These are separate focused batches; some checks overlap. They are not a full-suite
result. Independent reviews and issue dispositions are in `neo-review-ledger.md`
and `source-export-review.md`. Source transcription was checked independently
against physical PDF pages 18–24 and 91.

The final offline Word has 44 pages and a refreshed 20-entry table of contents.
Five evaluation tables contain 44 grade rows each. All 55 adopted values and every
evaluation-table cell match the frozen records; all 55 Word comments and their
exact value anchors match the Excel clarification rows. The four embedded source
regions retain the regenerated pinned crops' RGB pixels after TOC finalization.
Main reviewed all page contact sheets and enlarged representative pages; Neo
independently reviewed the method-table, evaluation and concluding pages.
Evidence: `export-real-qa.json`, `export-real-conversion-receipt.json` and the
internal page images. Only Word and Excel are deliverables; the PDF is internal QA.

## Acceptance boundary

The saved M1 report contains four slopes with eight indicators each. Its content
cannot establish a genuine complete five-slope, eleven-indicator reassessment.
The G3 offline conversion uses preserved content plus explicitly labelled
validation judgments to exercise the new calculation and export paths. It must
not be used as an engineering report or as evidence that the real inventory or
assumptions have been verified.

The 55 validation values comprise 28 unverified legacy values treated as indirect
assumptions and 27 deliberate no-evidence scenarios. They do not establish actual
source absence or engineering correctness. The unchanged original inputs and the
unapproved real commission proposal were not used as authorization for a rerun.

Two contained limitations remain explicit:

- P2: template section 3.2 retains its ranking formula, as the owner required for
  fixed text, while the updated customer scope selects A.3-1 lookup, which the
  calculator executes. This does not block offline source-fidelity acceptance,
  but method narrative/calculation consistency needs customer/engineer resolution
  before claiming engineering readiness. No replacement wording was invented.
- P3: inherited PDF line breaks under justification stretch some short lines and
  punctuation; the fixture also repeats chapter 6's heading. No value loss or
  clipping was observed in the reviewed pages. These are retained formal-layout
  review items, not a claim of pristine issued-report formatting.

G4 retains the full suite and complete scripted pass. Current-input staging,
native Linux case/ledger checks, the actual owner checkpoint, any paid rerun and
manual engineering sign-off remain separate and are not claimed here.

## G3 follow-up — 2026-11-03 UTC

This section supersedes the original presentation results and open formula P2
above; the original evidence remains historical. The owner approved a small,
source-driven table specification pilot, alongside the existing method records.
The guideline explicitly permits A.3-1 simplified selection on physical PDF page
91. The earlier formula-versus-lookup concern is therefore closed; this does not
assert that every tabulated weight equals a rounded formula result.

### Behavior and decision boundary

Two prepared table specifications reproduce this report's ranking and evaluation
tables. Their generic renderer binds columns to immutable saved records; specs
contain headers, bindings, groups/merges, captions, sorting and level labels,
never numeric cell data, grade descriptions or formulas. Grade descriptions live
in source-bound method records; adopted values, weights and scores come from saved
calculations. The original method-record version remains readable.

The existing plan checkpoint now includes table versions, source pins and rendered
headers. Unsupported bindings and missing annotation anchors are rejected before
approval. Each known reconciliation difference and distinct multi-valued inventory
attribute becomes a frozen confirmation obligation. Word and Excel exports reject
omitted or altered obligations, including pointers outside the rendered root.

Approval also writes `outputs/confirmation-checklist-<digest>.md`, recording the
method, weight-selection convention, table types/versions and source references.
It is a readable projection of the immutable approval: editing it grants no
authority. Repeating the same confirmation can restore a missing checklist without
creating another approval. Users can reference confirmed rules in a future scope
document, but automatic cross-case import/matching is not implemented. New source
versions and applicability still require confirmation.

This pilot uses prepared source-copied specifications. Runtime method discovery,
agent-generated table specs and a dedicated versioned-spec confirmation UI remain
later work. A different-structure generic compiler test passes, but this is not a
claim that arbitrary report methods or layouts are already supported.

### Follow-up verification

Evidence is in `.analysis/m1-g3-followup-20261102/`. Main implemented integration;
the named method-data and export owners implemented their modules. Neo independently
reviewed tests and implementation, retaining first failures and subsequent fixes.
No outstanding P0/P1 was found within that reviewed scope.

| Separate focused batch | Result | Evidence |
| --- | --- | --- |
| New specification, confirmation and conflict contracts | 43 passed | `neo-followup-green-09.log/xml` |
| Existing scoring, method, integration and commission tests | 160 passed | `neo-regression-10.log/xml` |
| Export, workbook, footnote and native-layout regressions | 92 passed | `export-regression-green.txt` |
| Source/compiler checks | 21 passed | `source-table-spec-green-02.txt` |
| Presentation regressions | 37 passed | `source-presentation-green.txt` |
| Hierarchical content and saved-reference regressions | 51 passed | `main-regression.log/xml` |

Batches overlap and must not be added as unique tests or described as the full
suite. Main's 51-test batch used fresh native Linux writable storage and the
existing old-input/network Python guard, including normal Python children; no
guard events were recorded. This is not an operating-system sandbox and does not
cover interpreters started with options that bypass Python startup hooks.

The final Word artifact renders to 38 pages in the verified PDF. It contains five
evaluation tables with 47 body rows and two header rows each, and 115 comments:
55 ranking reasons, 55 assumptions and five
known-conflict pointers. Excel contains 60 clarification rows (55 assumptions and
five conflicts). Exact saved-value and annotation comparisons passed; four source
regions retain their crop pixels. All 11 source copies and durable-library blobs
were hash-checked after export. Main reviewed both final contact sheets covering
all pages and enlarged page 18; Neo independently reviewed representative table
pages. Final image lineage is in `export-final-image-lineage.json`, with artifact
hashes and checks in `export-final-handoff.json` and `export-real-qa.json`.
The raw UNO TOC-finalization receipt reports a different intermediate page count;
it is preserved but is not used as evidence of final pagination.

These are actual generated files driven by deterministic scripted inputs and
tool/adapter tests. They establish calculation, persistence, validation and output
behavior for those inputs. They do not establish that an LLM can independently
interpret new material, select correct arguments or finish an entire report.

### Remaining limits

The offline fixture still uses unverified drawing-title object labels and the
previously disclosed validation assumptions; it is not an engineering assessment.
Inherited P3 spacing and the duplicate chapter-6 heading remain formal-layout
items. Joint assumption sensitivity remains the implemented check; individual
assumption refinement is deferred. Fixed source prose was preserved.

G4 step 6.1's full suite and complete scripted pass remain mandatory outstanding
work, as do native case/ledger readiness and current-scope staging with `--template`
before the actual checkpoint/rerun. No paid/provider calls, real report rerun,
ledger migration or G4 approval occurred in this follow-up. Email remains stopped.

## Customer comment policy — owner decision, 2026-11-02

The owner approved G3.1, then reversed the earlier suggestion to put ranking
reasons in the customer Word file. Customer comments are reserved for material
issues: conflicts, unclear or missing information, and assumptions. Ranking
reasons remain in saved audit records. The Excel clarification list is unchanged;
each customer Word comment must correspond to one clarification row.

This supersedes the historical 115-comment output above. That artifact and its
verification evidence remain preserved. The customer-comment follow-up uses
`.analysis/m1-g3-customer-comments-20261102/`; it does not authorize an internal
review-copy mode, G4 execution, paid calls or a real report rerun.

The customer exporter now emits only material-issue comments, including when a
previously saved G3.1 snapshot contains ranking-comment metadata. New assessments
keep reasons in the immutable assessment input/results and saved ranking records,
without creating customer comment metadata. Audit-only text is no longer scanned
as visible customer content; validation of historical metadata and material-issue
anchors remains in place. Excel behavior is unchanged.

The legacy v1 generator also omits its visible reason column while retaining the
audit data and existing order. A historical generated four-column ranking table
is refused with an instruction to regenerate from the saved assessment, rather
than silently editing frozen data or stripping arbitrary table columns.

Independent tests first reproduced seven failures with two checks passing
(`red.log/xml`). After the three-file repair, eight affected test files passed:
269 tests in 59.13 seconds (`green.log/xml`). Neo authored the tests; Main reviewed
them before RED, and Neo independently reviewed the repair.
Tests include actual DOCX/XLSX correspondence for all five issue types, exact
anchors, saved-audit preservation, historical snapshot re-export, and retained
malformed-input guards. This is a focused regression batch, not the full suite.

The existing Python input fence recorded one denied operation during RED and 65
during GREEN. An isolated probe reproduced a limitation: relative `open` calls
using a directory descriptor are incorrectly resolved against the working
directory by this fence. LibreOffice profile-like paths dominate the GREEN log;
the log does not establish each caller's cause. All recorded operations were
denied. The guard was not weakened, and zero guard events or full OS isolation
are not claimed. Fresh writable test storage was native Linux. The probe and raw
events are preserved with the follow-up evidence.

The newly generated offline customer Word contains 60 material-issue comments
matching all 60 Excel clarification rows and exact value anchors. All 55 ranking
reasons remain matched across the three saved Assessment audit locations; no new
ranking-comment metadata is produced. Table cells, Excel cells and four source
crops match the G3.1 fixture. `export-real-qa.json` records the checks.

The first XML comparison normalized empty runs too broadly. A narrower check
found 55 extra empty formatted runs in the old artifact, so that comparison was
not accepted as sole layout proof. Both results are preserved. A fresh offline
PDF was then rendered: all 38 pages match the prior verified PDF in text, page
dimensions and RGB pixels at scale 1.4 (`export-pdf-comparison.json`). Prior visual
review is reused on actual rendered-page equality. Excel differs only in package
metadata. Engineering and inherited P3 limits remain unchanged; comment-balloon
pagination is not claimed.
