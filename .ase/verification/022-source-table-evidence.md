# Task022 source-table evidence and trunk verification

2026-09-28. Main implemented and tested; alignment_review independently reviewed
design and actual code; postrun_review independently compared rendered original
pages with automatic extraction. No engineering sign-off.

## Implementation and pre-run evidence

Additive source_table_views now accompany native read/search tools, and table_view
accompanies inspect_source_page. All original text, literal matches, source filters,
pagination and immutable originals remain. Search adds the actual locator list for
all blocks in a spanning match. Strict physical locators drive lazy page selection;
there is no ordinal/page substitution. Source access reuses original membership,
path confinement and SHA256 validation. No persistent cache, OCR, knowledge-graph
copy, write capability or business-specific extraction rule was introduced.

Existing pypdf6.19 layout mode returned empty on design p96–98; p97 native text
was908chars. Installed pdfplumber0.11.10/pdfminer.six20260107 in the independent
WSL environment, pinning pdfplumber in pyproject. Existing Pillow/PDFium pins were
retained. The fixed generic lines/lines settings produced automatic columns on
p97, including 40 pipes and6plates, without manual reference-table input.

Independent page review: see 022-source-observation-review.md. p96 and p98's true
monitoring-frequency table retained inspected values; narrative p15 had no table.
P3-022-O01: p98 drawing frame/emptygrid are extra geometric candidates. Scope:
line-based PDF detection, source-output noise. Blocks claims of semantic table
counts/complete parsing, not isolated integration. Containment: explicit candidate
status/limitations, original text and exact page/cell provenance. Main retains this
known limitation this iteration; reconsider generic filtering only if real trace
shows consequential confusion. Do not delete nested tables to hide this sample.

165 relevant tests passed in40.37s (source_tables, document_tools, catalog,
evidence_tools016, agent_boundaries, native_rubric013, review_feedback,
review_import017). One existing native Rubric beta warning. Checked merges,
empty cells, locator types, spanning matches, pagination, parser failures, source
boundaries/hash freshness, no writes, existing native feedback/revision contracts.
git diff --check passed. These are mechanics/protocol, not model-quality proof.

alignment_review found no blocking design/implementation finding. It checked
C25 observations vs decisions, D08 isolated dependencies/storage, source/producer
read-only boundaries, unchanged native loop and effective tool descriptions.
Main accepts that disposition. It does not claim production correction has occurred.

Prepared .runs/task022/review-continuation using unchanged Task017 importer and
Task016 pre-review checkpoint1f1bb22a-e92f-64bd-8073-7505502d17b7. Fresh grading
run9865e8fb-8ea9-4c20-9bd0-6e3b3566152b. Native next is FeedbackRubric.after_agent;
76messages,4results,1617frozen source blocks retained. No old approval, manual
findings, graph dependencies, newOCR or paid calls during preparation. Original
candidate hash7e86b61aa246f5f6b08ecd60c546a95c67cf88f9929f41462285c5c5eddea28d;
reviewer role hash07d7d853ae3e317e640b5adb8524a16d3ab9e2e8296145cef1e38ad2086c7a29.
New tool wrapper exercised read-only on the copied p97: unedited automatic row
bindings present; original source hash matches. Runtime test result is pending.

User explicitly authorized paid calls and email during this task. Kickoff and
implementation milestone sent via existing Gmail to the verified correspondent;
private exact bodies/receipts are in ignored .analysis/task022.
