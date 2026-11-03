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
