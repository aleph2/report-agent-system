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
bindings present; original source hash matches. Actual run result follows below.

User explicitly authorized paid calls and email during this task. Kickoff and
implementation milestone sent via existing Gmail to the verified correspondent;
private exact bodies/receipts are in ignored .analysis/task022.

## Real native outcome: observation gain, no demonstrated quality gain

Completed13:46:32–13:49:32 UTC (180s). iteration0 satisfied, all5criteria passed,
unverified=false. Launcher exited0 and projected reviewed_draft; underlying
report_status needs_attention is separate bookkeeping. No author/coordinator call,
new result, report edit or second review. Original P2 issues remain.

23grader responses,22tools: project_status1, read_review_export11, search_sources9,
read_source_page1. One export limit120 rejected with PREVIEW_INVALID_RANGE;
the grader recovered with limit100. Ten successful export pages cover907blocks
through next_offset=null. No vision/OCR/graph calls. Returned use is complete:
1,208,487 input +7,589 output =1,216,076 tokens (cumulative contexts, not one
context size or monetary cost). GLM-5.3 response identity confirmed. Configuration:
chat/completions, reasoning_effort high, max_completion_tokens65536,
thinking enabled/clear_thinking false, parallel_tool_calls false, nonstreaming,
temperature/top_p/seed unset, SDK max_retries2, timeouts15/1800/60/60seconds.
No new cumulative quota. These match existing model setup; safe instantiated-model
fields and actual public responses are saved separately from credentials.

Role/rubric exactly match frozen production text in the first actual request.
Tool descriptions are the intended change; do not call the entire effective input
identical to Task018. This run autonomously chose a different path and sources.
All22tool results appear in subsequent model requests. Twenty distinct source-page
views arrived, including table candidates on design22/96/99 and survey12/153.
Design97 was never selected, so its improved column observation was not received.
Do not describe this as failure to understand p97 after viewing it. No request
required a named page or check; source/role/tool observations remained autonomous.

Independent postrun_review: see022-postrun-content.md. P2-022-R01 carries existing
false acceptance: known target quantity missed; already-received scope, rule/input,
fieldwork and X21 contradictions also missed. Final reasons overstate appendix
completion despite text indicating later attachments. The six weighted sums remain
correct; no false arithmetic defect or new confirmed geometric-table misuse found.
Main accepts review disposition: block report-quality promotion/confirmed engineering
use, retain explicit human-review limitations; this does not block isolated diagnosis.
The runtime feedback loop did not receive needs_revision, so this run does not
demonstrate author revision or successful re-review. Do not manufacture that trace.

Postflight: all22protected baseline files and51frozen implementation/script files
unchanged; all copied original hashes,1617source blocks and4result objects match
import receipt. Final DOCX differs from original only in the knowledge-validity
timestamp in word/document.xml; report body is unchanged. No new visual render
claimed. Public input/output/settings/export are in .analysis/task022 and .runs/task022.

Main decision: retain generic read-only observation capability as an implementation
increment; do not promote it as a solved reviewer-quality baseline. Do not retry
the same native call. The predeclared two-case automatic-view diagnostic in the task
packet distinguishes supplied-evidence readability from autonomous evidence choice.
Source snapshot was generated by the actual tool implementation before the final
warning wording added frame/emptygrid false candidates; existing parser limitations
were already present. It is an unedited automatic observation, not manual semantic
transcription; it is not a tool result delivered in the failed native review.

## Bounded supplied-evidence diagnostic: both broad verdicts still satisfied

Ran exactly the predeclared2fresh cases13:54:08.795–13:57:45.113 UTC, corrected6
first, original40 second. Same unchanged29flat source blocks/5documents and broad
commission as021; added unedited mechanical p97 observation captured before the
native call. No target instruction, manual table semantics, old verdict or labels
entered model input. The programmer-selected page increases salience and context
length; do not interpret this as equivalent autonomous retrieval.

| Case | Candidate | Public result | Target-level assessment |
| --- | --- | --- | --- |
| f80d2c73e83c | Full report, only quantity40→6 | satisfied | Not mentioned; no target false allegation, not an explicit verified match |
| 50709d75596d | Original full report with40plates | satisfied | Known source mismatch not detected; blanket false acceptance |

Each used1request/1response, no schema continuation or execution error. Returned
usage102,804input+18,315output=121,119tokens. All55frozen files unchanged;
actual complete system/user messages, source bundle and report verified; settings
and invocation parameters exactly equal Task021 harness. All automatic geometry,
identity and settings match current code after JSON normalization; only a wording
addition to the generic false-candidate warning postdates the frozen observation.
No private reasoning content is exported. Both candidates retain other known
defects; neither is a wholly correct reference. Do not compute2/2success from
top-level statuses, and do not score silence on corrected6as an explicit match.

Main disposition: this provides a second failure condition with the p97 observation
actually supplied. Therefore missing retrieval alone cannot explain this task's
observed failures. Task021's manually normalized table success did not reproduce
with the automatic JSON supplement in these single observations. Format/readability,
salience, context composition and stochastic judgment remain confounded; no unique
cause or general rate is established. Existing P2 false-acceptance issue remains
open, not a separate new defect for each case. No new target false allegation.

Total observed paid use this task:25responses,1,311,291input+25,904output=
1,337,195tokens across1native invocation+2diagnostic sessions. These are returned
token totals, not25knownHTTPattempts or billing. SDK transport retries cannot be
counted from successful-response audit alone; no monetary cost inferred.

No further identical paid retry. The next useful investigation is a predeclared
held-out comparison of evidence representation and grader judgment reliability,
preserving autonomous strategy and evaluating erroneous acceptance and false
rejection separately. Existing tools and source fidelity are retained; this
iteration does not claim that changing to English, adding geometry, or taking
more samples by itself fixes the broad reviewer. Formal quality acceptance and
real corrective-loop success remain open. Original sources/report runs preserved.
