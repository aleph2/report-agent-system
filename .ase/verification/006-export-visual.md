# Task006 Export Visual Verification

Date: 2026-09-27, Asia/Shanghai. Actual performer: ASE Tester (this task),
independent of Main's application implementation. This record follows the ASE
verification template. It concerns rendering infrastructure and visible export
layout, not model ability, engineering correctness or engineering sign-off.

## Scope

Read-only inspection of the existing synthetic report:

- Input: `.runs/task006/synthetic-reuse-fixed/exports/12511f0b-0015-4068-be6c-96fa415273b1.docx`
- QA output: `.runs/task006/synthetic-reuse-fixed/exports/visual-qa/`
- Input SHA256 before and after rendering:
  `2c07b6760db749863da2e4d6aa68ee5305538677f78f76bbad3cdf0213f1e183`
- 29 nonempty paragraphs, no tables, one Letter-size section (8.5 x 11 inches).

Only this verification record and derived local QA files were created. No business
code, source DOCX, project results, legacy application/service/configuration or
dependencies were changed. No paid model/OCR calls or package installations occurred.

## Lifecycle Gate Decision

- Current stage: Task006 end-to-end integration, export usability verification.
  The useful outcome is a readable, traceable saved report, including its limits.
- Decision owner: Main. Actual visual reviewer: ASE Tester; this is independent
  testing of Main's export, not an additional independent review of the tester's
  own tooling. Main's final integration disposition remains Main's responsibility.
- G1: rendering feasibility validated within this Windows environment. Existing
  LibreOffice plus the bundled renderer produces usable PDF and page images.
- G2: this exact synthetic DOCX passes the export-layout check. This is a local
  subcheck and does not independently accept the complete application or quality
  of a real engineering report. Main's model-run evidence is recorded separately
  in `006-deepagents-integration.md`.
- Baseline: input hash above; LibreOffice 26.2.1.2 (X86_64); Codex document skill
  and workspace dependency bundle 26.905.11957; bundled Poppler/Python libraries.
- G3 gain: replaced an unverified export with a reproducible render and inspection
  of every page. Non-regression: original DOCX hash unchanged and all 29 paragraphs
  recovered from PDF after whitespace normalization.
- Held-out/variability limits: one English synthetic document. CJK, long tables,
  equations and future real-report pagination have not been validated by this input.
- Missing checks: actual future engineering DOCX and Microsoft Word rendering.
- Integration recommendation: accept the local render method and this synthetic
  layout result; continue real-report testing. No baseline promotion or engineering
  sign-off is implied.
- Next action and owner: Main supplies/generated real DOCX; Tester or Main renders
  that exact saved version and inspects every page using the method below.

## Commands Run

All project-relative commands use
`C:/Users/dongy/Documents/ChatGPT/report-agent-system` as the working directory.

| Command/check | Result | Notes |
| --- | --- | --- |
| WSL `command -v libreoffice soffice pdftoppm pdftotext fc-list` | Only `fc-list` found | WSL had no usable DOCX/PDF renderer on PATH. |
| WSL inspect `/var/cache/apt/archives` | Approximately 161 MB total cache | No matching LibreOffice, Poppler or font archives found. |
| WSL root `apt-get -s --no-install-recommends install libreoffice-writer fonts-noto-cjk poppler-utils` | Simulation only: 63 new packages, 0 upgrades/removals | Existing official Ubuntu archive/security sources; installation avoided after discovering Windows tools. |
| Resolve Codex workspace dependencies | Passed | Bundled Python, renderer, `pdfinfo.exe`, `pdftoppm.exe` available. |
| Check `C:/Program Files/LibreOffice/program/soffice.exe` | Found, version 26.2.1.2 | Original failure was executable discovery on PATH, not absence of LibreOffice. |
| Bundled `render_docx.py INPUT --output_dir OUTPUT --emit_pdf --verbose` with process-local LibreOffice PATH | Exit 0 | Independent temporary LibreOffice profile; 2 PNGs and nonempty PDF. |
| Bundled `pdfinfo.exe OUTPUT/12511f0b-0015-4068-be6c-96fa415273b1.pdf` | 2 pages, 612 x 792 points, PDF 1.7 | No encryption, forms or JavaScript reported. |
| `python-docx` paragraphs versus bundled `pypdf` extracted PDF text | 29/29 present | Whitespace ignored; original punctuation otherwise retained. |
| `pypdfium2` glyph bounds and Pillow image bounds | 0 out-of-page glyphs on both pages | Supplements, not replaces, visual inspection. |
| Input SHA256 after rendering | Unchanged | Source DOCX was not rewritten. |

## Reusable Render Command

Use a process-local PATH addition. Do not change system PATH, a running LibreOffice
profile, the DOCX or project application code. The packaged renderer creates its
own temporary profile and cleans it up. This uses the pre-existing native Windows
LibreOffice under the user's instruction to check/reuse existing tools before
installing packages; the Windows dependency bundle has no bundled LibreOffice.

```powershell
$env:PATH = 'C:\Program Files\LibreOffice\program;' + $env:PATH
$renderPython = 'C:\Users\dongy\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$renderScript = 'C:\Users\dongy\.codex\plugins\cache\openai-primary-runtime\documents\26.905.11957\skills\documents\render_docx.py'
$exportDir = '.runs\task006\synthetic-reuse-fixed\exports'
Get-ChildItem -LiteralPath $exportDir -Filter '*.docx' -File | ForEach-Object {
    $renderOutput = Join-Path $_.DirectoryName ('visual-qa-' + $_.BaseName)
    & $renderPython $renderScript $_.FullName --output_dir $renderOutput --emit_pdf --verbose
    if ($LASTEXITCODE -ne 0) { throw ('DOCX rendering failed: ' + $_.FullName) }
}
```

The verified run used `visual-qa` as its output directory because there was one
DOCX. The reusable loop uses one directory per document to prevent PNG collisions.
For later real reports, change only `$exportDir` to the authorized new export
directory. Record the input hash, confirm every output page, compare text, and open
every `page-N.png`; command success alone is not visual acceptance. Re-resolve
bundled paths when the installed runtime version changes.

## Manual Checks

Opened both generated PNGs and checked the complete pages, including page edges and
the page transition. Original image dimensions are 1547 x 2002 pixels each.

| Page | Observations | Result |
| --- | --- | --- |
| 1 | Two-line title fits. Status, scope, report title and sections 1-5 are readable. No clipped text, overlaps or missing glyphs observed. Section 5 has its first source item on this page. | Pass |
| 2 | Continues the remaining two source items, then Source index and Version record. Draft/review/input IDs are complete. Remaining white space is ordinary end-of-document space, not an empty extra page. | Pass |

Page 1 ink bounds: `(164, 164, 1384, 1852)` pixels.
Page 2 ink bounds: `(164, 152, 1321, 733)` pixels.
No heading was left alone without following content at the page break. No table
assessment is claimed because this input contains no tables. Existing title rule,
metadata and report wording were preserved; no style redesign was performed.

Evidence hashes:

| Artifact in `exports/visual-qa/` | SHA256 |
| --- | --- |
| `12511f0b-0015-4068-be6c-96fa415273b1.pdf` | `4f25256c18187ba92203d546bebbd9665065679f2ebc82a1d8e21b094cb8cb87` |
| `page-1.png` | `05875e85306d4e3105e07e45b82ce870fedf4bf97b553083514f277a2c8880d3` |
| `page-2.png` | `ec71c796d9d6be59a83589f921a0ffab46f71009eb45debbdd557c0cad64976e` |

## Skipped Checks

| Check | Reason |
| --- | --- |
| APT installation and WSL rendering | Existing Windows renderer worked; avoided 63 unnecessary packages. |
| New paid model/OCR runs | Outside this verification task; inspected already exported file only. |
| Real engineering report, CJK, long tables, equations | Not represented by this synthetic input. Windows SimSun, Microsoft YaHei and Calibri font files are present, but presence is not rendering proof. |
| Microsoft Word parity | LibreOffice rendering is verified; Word may paginate differently. |
| Agent-quality, provenance semantics and engineering acceptance | Separate review responsibilities; this check proves visible export usability only. |

## Failures And Fixes

- EX-VIS-01, P2 tooling/environment limitation: the earlier renderer could not find
  `soffice` on PATH. This blocked visual verification, not report execution or
  saving a draft. Existing executable discovery and a process-local PATH addition
  contained and resolved it without installation or business changes. Owner:
  Tester; disposition: resolved for this environment, verified by two rendered pages.
- A supplementary PDFium text comparison initially flagged the scope paragraph:
  its extractor returned U+FFFE at the wrapped `sign-off` hyphen. Visual inspection
  showed the hyphen and following word intact; independent `pypdf` extraction
  recovered all 29 original paragraphs. This is an extractor-specific observation,
  not evidence of DOCX content loss; no product bug or automatic text-repair was claimed.
- Optional `pdftotext.exe` was not present in the bundled Poppler subset. The
  bundled `pypdf` comparison provided the needed check; no package was installed.
- Renderer emitted `Could not find platform independent libraries <prefix>` but
  exited successfully. PDF and both PNGs were independently checked as above;
  no output defect was observed. The warning's underlying cause was not investigated.

No unresolved P0/P1 rendering issue or confirmed clipping/pagination defect was
found in this document. Continue the authorized real-input trunk; apply this same
visual check to its actual final export before claiming that export passed.

## Residual Risk

This is evidence for one exact DOCX and one renderer/font environment. Future
report size, Chinese text, tables and renderer/font changes can alter page breaks.
Do not treat local render readiness, model-reviewed labeling or successful DOCX
export as engineering sign-off or proof of substantive report quality.

## Real Draft Preview Addendum

Date: 2026-09-27. Performer: ASE Tester. Status: PREVIEW ONLY, NOT ACCEPTED.
This addendum preserves the earlier synthetic evidence. It extends rendering
coverage to actual CJK text and long table-like content, not engineering content
or model quality. Main owns disposition of the findings below.

### Exact Snapshot And Authority

- User authorized GET of saved draft `82d9f1bc-3e02-484f-aec1-4f0855fd0d3c`
  from `http://localhost:18140/api/export/82d9f1bc-3e02-484f-aec1-4f0855fd0d3c`.
- Saved to `.runs/task006/highway-report/exports/preview-unreviewed-82d9f1bc-3e02-484f-aec1-4f0855fd0d3c.docx`.
- Derived PDF and all 19 PNGs are in the adjacent directory
  `preview-unreviewed-82d9f1bc-3e02-484f-aec1-4f0855fd0d3c-visual-qa/`.
- Export timestamp in document: `2026-09-27T15:39:03.316805+00:00`.
  Status text: `Unreviewed draft; not approved.` Version record: exact draft ID,
  `Review: none`, empty input-results and knowledge-versions fields,
  `Knowledge validity at export: not_used`.
- This is a historical snapshot. User subsequently reported review
  `7947a78b-56f9-489b-99a6-bd5133781aa7` as `changes_required` and parent revision
  in progress. That review and any later draft are NOT covered by this snapshot.
- Tester used GET, local rendering and read-only SQLite queries only. No model
  call, delivery selection, result submission or business-code edit was performed.
  The separate graph-adoption paid run remains on hold pending explicit Main go.

### Checks And Results

| Check | Evidence/result |
| --- | --- |
| Existing render method | Same bundled renderer and process-local LibreOffice PATH as above; exit 0, no install. |
| PDF/PNG output | 19 Letter pages, 612 x 792 points; each PNG 1547 x 2002 pixels. PDF 1.7, 664557 bytes. |
| Manual page coverage | Opened every page, 1 through 19. CJK readable; no visible missing glyphs, edge clipping or overlapping text. |
| Glyph bounds | PDFium reports zero out-of-page character boxes on all 19 pages. This does not prove absence of internal layout defects. |
| DOCX content | 246 nonempty paragraphs, zero native Word tables. All 211 nonempty saved-body lines occur in DOCX paragraphs after removing Markdown heading prefixes and whitespace only. |
| Immutable body | Read-only SQLite SHA256 before GET and after rendering are equal; see hashes below. |
| Source index | All six draft source IDs, titles and partial-coverage labels match the local source snapshot. All associated warnings/limitations and four non-null PDF parse IDs are retained. Other catalog sources are not claimed as draft references. |
| Version consistency | Draft ID matches; `fact_ids=[]` and `input_ids=[]` agree with the export's empty fields and `not_used` status. This does not prove knowledge-graph adoption. |
| Fonts | PDF resources include Calibri, Microsoft YaHei, MS Gothic and OpenSymbol. Existing CJK fallback rendered; no font installation was needed. |

Source IDs checked:
`07fe4d16-e482-4ee5-83ac-5dd2cdc1bdb6`,
`2918682c-0804-426f-be09-47e6d802e9dd`,
`6bd3cacb-f733-47f5-89ff-5f2ec9114940`,
`91f00b59-1f64-48d1-9354-d8ac71aae539`,
`932dc8f9-ef16-40b6-9975-c5a449a4b6f7`,
`e3100d4e-9489-426b-81b8-378689a817d9`.

Supplementary full PDF paragraph equality did NOT pass: ordinary pypdf extraction
matched 211/246 paragraphs; PDFium and pypdf layout mode matched 217/246. Extracted
font runs reorder some CJK heading characters and angle symbols, although the
visually inspected positions are readable. Do not report 246/246 PDF text equality
or silently normalize these differences away. Exact body-to-DOCX preservation and
visual inspection are separate positive evidence; PDF extraction fidelity remains
a limitation of this check, not a proven source-body mutation.

### Findings And Disposition

- EX-VIS-02, P2 export formatting: Markdown tables remain pipe-delimited paragraphs,
  with literal separator rows and `**` markers, rather than native tables. Columns
  wrap inconsistently and table context separates across pages. Examples: table
  4-2 total alone at the top of page 9; table 4-7 caption/header at the bottom of
  page 12 with data beginning on page 13; table 4-8 continues on page 14 without a
  repeated header. Scope: this exact long CJK export. It impairs comparison and
  polished report use, but does not block saving or inspecting this explicitly
  unreviewed preview or continuing runtime testing. Containment: preserve the
  snapshot, keep preview labeling, and require human review of tabular content.
  Planned disposition: Main to prioritize Markdown-to-Word table/emphasis handling
  and pagination regression coverage before claiming final export-layout acceptance.
  No tester implementation change; Main disposition pending.
- EX-VIS-03, P3 pagination polish: version metadata is split after page 18, leaving
  only Draft/Review/Input results on page 19. No text is lost. This blocks no
  current action. Containment: retain the complete 19-page preview. Suggested
  disposition: keep the short version block together when export polish is scheduled;
  Main owner, deferred pending disposition.
- Format limitation, not a new engineering finding: actual page size is Letter
  with Calibri/CJK fallback, while the draft's own formatting note discusses later
  A4/Song-style formatting. No template-compliance or final-format acceptance is
  claimed. Scope/issue appendices are visible and add pagination; their substantive
  content was not adjudicated in this layout check.

### Evidence Hashes

| Artifact | SHA256 |
| --- | --- |
| Immutable draft body UTF-8, before/after | `31b5eb0e88a7bc4df6c6f65001c66f59fcb8f6d2e602d389ac427979e90850a8` |
| Preview DOCX, before/after rendering | `e2d9eaad7024a00c3ef0e127bd906d2b0939302058532267dc53a38143b20355` |
| Derived preview PDF | `c1e542c79b6924be05dc6e32d144ccb110ff79b0351cf9176520c20b7c46fd80` |

Gate disposition: G1 rendering feasibility and CJK preview usability are supported.
G3 gain is inspection of the real saved export without changing its body or
interrupting the model run. Full export-layout acceptance is NOT granted because
of EX-VIS-02. Engineering acceptance, source correctness, calculation correctness,
the later review/revision and Microsoft Word parity remain outside this check.
Next action: Main continues the current revision; render its exact saved export
again when authorized. The preview issues do not justify stopping that iteration.

## Final Candidate Table Verification

2026-09-28 Asia/Shanghai. Actual performer: ASE Tester. Main announced Gauss's
narrow Markdown-table formatter ready and explicitly authorized a fresh Python
process calling `export_docx` for final candidate
`166fe644-d837-4b13-965e-b428bf069b92`. No GET to the old loaded server was used;
the server was later restarted by Main. No model call, content edit or delivery
selection was performed by this local export/render check.

### Baseline Correction

The existing final DOCX already contained NINE native Word tables. It was not an
old-parser output. Its 55048-byte size matches the separately re-exported file,
but byte size alone was not used as evidence: table counts, all cells and paragraph
content were compared. Only the export-validity timestamp paragraph differed.

Tester initially copied it using the misleading `-old-format-baseline.docx` suffix
under the prior assumption supplied at handoff. After Main questioned that label,
Tester checked the actual tables and renamed only that tester-created copy to
`166fe644-d837-4b13-965e-b428bf069b92-pre-reexport-baseline.docx`. The standard final
file remains unchanged. The corrected copy is byte-identical to it. This is a
pre-reexport baseline, NOT evidence of the old formatter. The earlier `82d9...`
preview has zero tables but different saved body content, so the two draft versions
are not an exact same-content before/after comparison. Historical results above
remain valid for their respective versions.

### Artifacts And Commands

Directory: `.runs/task006/highway-report/exports/`.

- Existing standard DOCX: `166fe644-d837-4b13-965e-b428bf069b92.docx`, preserved.
- Baseline copy: `166fe644-d837-4b13-965e-b428bf069b92-pre-reexport-baseline.docx`.
- Fresh export: `166fe644-d837-4b13-965e-b428bf069b92-table-layout.docx`.
- PDF and all 20 PNGs:
  `166fe644-d837-4b13-965e-b428bf069b92-table-layout-visual-qa/`.
- Derived assertions:
  `166fe644-d837-4b13-965e-b428bf069b92-table-layout-structural-qa.json`
  and `bounds-qa.json` inside the QA directory.

Fresh WSL Python imported `Store`, `Workspace`, `export_docx`, read the exact saved
draft, and wrote `export_docx(ws, id)` bytes to the distinct table-layout path. No
launcher or model factory was invoked. The existing bundled Windows renderer and
process-local LibreOffice PATH command above then rendered that path, exit 0.
Input body and baseline hashes were checked before/after. Source exporter SHA256
at export: `18607ec6da6ae14e1f4e4bff83100a2185a5914887e40fa7c9d44f835dd770a9`.

### Results

| Check | Result |
| --- | --- |
| Native tables | 9 tables. Row counts including headers: 7, 7, 13, 13, 13, 13, 13, 13, 7. Column counts: 7, 6, 5, 5, 5, 5, 5, 5, 8. |
| Body preservation | All 537 cells exactly match saved Markdown cell content after intentional bold-delimiter removal. All 106 non-table body paragraphs exactly match, allowing only existing heading-prefix conversion. Saved-body hash unchanged. |
| Row/header properties | Every header has `w:tblHeader`; every row has `w:cantSplit`. No fixed-height clipping observed. |
| Render coverage | All 20 Letter-size pages opened and inspected, including every table's last row. Chinese characters, numbers and source IDs readable; no observed glyph loss, text overlap or page-edge truncation. |
| Repeated headers | Visible on page 4 (table 1-1 continuation), page 9 (4-2), page 14 (4-7), page 15 (4-8). Headers remain attached to at least one data row when a table begins near a page bottom. |
| Final rows | Table 1-1 ends on page 4; 4-1 ends page 8; 4-2 page 9; 4-3 page 10; 4-4 page 11; 4-5 page 12; 4-6 page 13; 4-7 page 14; 4-8 page 15. All visible and structurally intact. |
| Glyph bounds | Zero out-of-page character boxes on all 20 pages. Supplements visual review; not a semantic correctness test. |
| Baseline comparison | Standard and copied baseline each already have 9 tables. All table cells and all paragraphs match fresh output except the validity timestamp paragraph. No formatter improvement is inferred from this same-version comparison. |
| Source/version metadata | Six source IDs, titles and all extraction limitations retained. Draft `166fe644-d837-4b13-965e-b428bf069b92`, review `e41e8b4a-8585-4097-8e5c-a6e451a855a9`, input `82d9f1bc-3e02-484f-aec1-4f0855fd0d3c` match. Knowledge `not_used`, checked 2026-09-27T16:03:54.944954+00:00. |
| Approval label | `Model-reviewed draft; not engineering-approved.` Scope's pending-confirmation text remains visible. Accepted runtime review does not resolve engineering acceptance. |

### Remaining Layout Findings

- EX-VIS-02 disposition update: native table rendering, repeat headers and complete
  final rows are validated on this final candidate. The old raw-pipe-table symptom
  is not present here. User accepted its P2 classification and Gauss supplied the
  narrow fix. Do not claim a controlled old/new formatter experiment for this ID.
- EX-VIS-04, P3 remaining caption/column polish: table 4-6 caption sits at the end
  of page 12 while its table begins on page 13. Equal-width columns also cause
  long chainage strings in the eight-column summary to wrap across several lines.
  Complete text and repeated headers remain readable, so neither issue blocks
  this model-reviewed draft's local layout check. Containment: retain the intact
  export and do not claim final template conformity. Owner Main/exporter;
  suggested deferred work: caption keep-with-next and content-aware column widths.
- EX-VIS-05, P3 existing non-table Markdown polish: `**` remains literal in body
  paragraphs, while bold table totals render correctly. Scope text also retains
  Markdown prefixes. Narrow table conversion did not promise a full Markdown
  renderer. No current action blocked; Main/exporter can schedule separately.
- EX-VIS-03's nearly empty metadata page was specific to the earlier preview;
  this candidate keeps the version block together on page 20. Different content
  and pagination mean this is not proof of an explicit metadata pagination fix.

### Hashes And Decision

| Exact artifact | SHA256 |
| --- | --- |
| Saved final draft body, unchanged | `e47e7d528efe8a2202c4a35e6f36365723496658eaf5b9607321592679cbbfe1` |
| Standard final DOCX and preserved baseline copy | `478b389c289606d3f1487bbf6c1c39842c0ad26431b6c40d78383777a4d25984` |
| Fresh table-layout DOCX | `4ef16f2bb0d58669576669990a3ec582eb7aa0a9c24ff260a58b5cb24ab9f34c` |
| Fresh table-layout PDF | `3e64394a67dd5911b815758b185dbe67ed4ec4d08fede5baf2eb3b1cb37c766d` |

Accept the narrow final-candidate table/CJK/content-preservation check, with P3
polish and original Letter/font/template limitations disclosed. This is not flawless
typesetting, full PDF extraction equivalence, content review or engineering sign-off.
Main's reported 43 focused tests and later 297 tests were not rerun by Tester here;
they are separate implementation-suite evidence. No application code was changed.
