# Task022: located table evidence in the real review/revision trunk

2026-09-28. User asked to continue after Task021 and then explicitly authorized
paid model calls and email communication. Main performs architecture, implementation,
verification and integration; independent alignment_review checks relevant confirmed
boundaries and postrun_review assesses actual evidence/output. Git author remains
menglinsun@hotmail.com. No legacy writes or engineering sign-off.

Stage: continuous integration on the existing executable trunk, with report-quality
acceptance still unresolved. Task018's broad false acceptance and Task019–021's
source-presentation evidence remain valid. One broad controlled observation per
cell is not general quality proof. Expected trunk gain: an autonomous reviewer can
obtain column-preserving source observations through its ordinary chosen tools and
return actionable feedback to the responsible author; resulting saved revisions and
re-review, if any, must be inspected rather than inferred from top-level status.

## Scope and design

- Keep outcome-responsible reviewer role, commission, rubric, model and native
  DeepAgents review/refinement loop. No prescribed scan sequence or target hints.
- Preserve original source bytes, frozen extraction/OCR, source IDs, locators,
  literal search selection and pagination. Add derived geometry only for physical
  pages represented by returned blocks, deduplicated per tool response.
- Existing pypdf 6.19.0 layout mode was exercised on design physical pages 96–98;
  it returned empty text despite native content on page97. Probe pdfplumber 0.11.10
  table geometry before implementation. Prefer maintained third-party extraction
  over custom semantic column binding. No manual reference-table injection.
- Extend read_source_page/search_sources/inspect_source_page observations with
  table rows/cell geometry, original hash, physical page and extractor configuration.
  Do not guess column meanings, propagate merged headings, or turn blanks into zero.
  These are unverified mechanical renditions, not complete semantic/visual coverage.
- Resolve project membership/path/hash using existing original access boundaries.
  Batch selected pages per source. Initially no persistent cache and no source DB
  writes. Explicit failures preserve the frozen text and identify system limitations.
  Scans, unruled tables and DOCX remain bounded by existing tools and limitations.

Framework reuse: DeepAgents 0.7.19 already supplies tool choice and native
FeedbackRubric revision control. No new agent/stage/decision loop. The gap is a
mechanical source representation. pdfplumber API/version will be pinned if the
offline probe supports use. No new OCR or interpretation model calls in this tool.

## Verification and decision

1. Check extraction against original rendered page97 (prior independent visual
   evidence reusable) plus held-out nearby/table/text pages. Preserve unedited
   automatic outputs separately from the old manual reference.
2. Test table alignment/merged and empty cells, unsupported/blank/broken originals,
   strict physical locators, cross-block/page pagination, no source mutation,
   membership/path/hash boundaries. Reuse existing relevant regression checks.
3. Review changed tool internals/descriptions and permissions independently.
4. Fork Task016's preserved pre-review native checkpoint into a new isolated
   Task022 run with original candidate and frozen source inputs. Use authorized
   current GLM-5.3 settings. Record effective prompts, tools, safe parameters,
   public outputs, observed usage, source views actually returned and artifact IDs.
   Do not add known findings to runtime input. No blind paid rerun on failure.
5. Inspect feedback, author changes, next review and persisted/exported result.
   Known F01/F02/F03/N01 and P2-021-R02 are development-side assessment anchors,
   never runtime answer hints. Record new defects and false allegations separately.
   Quality improvement requires actual evidence; local tests alone do not establish it.

Existing P2 report/reviewer issues block quality promotion/engineering reliance,
not this isolated integration run or explicitly limited human-review drafts.
Classify new confirmed issues with severity, scope, containment, exact blocked
action and disposition. Main owns corrections/disposition; do not hide failed runs.

Email: use verified existing correspondent dongyong.sun@derobotee.com from the
authenticated Gmail account. New Task022 thread ID 1a0e8337bc8d5abd; kickoff sent.
Send meaningful milestones/results and inspect relevant replies during this work.
Private mail receipts and source/model data stay in ignored .analysis/.runs.

Official extraction references consulted (2026-09-28):
- https://pypdf.readthedocs.io/en/6.19.0/user/extract-text.html
- https://github.com/jsvine/pdfplumber (table geometry, cells and extraction limits)

## Post-run bounded diagnostic (declared before calls)

Native run completed satisfied with no revision; its20actual page supplements did
not include designp97. Do not blindly repeat this same invocation. Separately test
whether the *automatic* representation is understandable when actually supplied.
Reuse Task021 flat arm's29blocks/5documents, unchanged broad commission, complete
original40 and quantity-corrected6 reports, role/rubric and GLM settings. Add the
exact unedited runtime source_table_views for p97 as a separate derived supplement;
all original flat blocks remain. No manual table, target instruction, old verdict,
or reference label enters input. This necessarily makes that page more salient;
record this limit rather than treating it as proof of one unique cause.

Two fresh sessions, one initial call per report, native schema continuation allowed,
stop on error. Original40 success requires explicit source-supported column/count
mismatch; top-level status alone is not success. Corrected6: supported match,
not-mentioned and false allegation are separate outcomes. Both retain other defects.
Freeze full input and code before paid calls; inspect actual complete messages and
safe usage. Existing Task021 flat/manual arms are historical references, not new
replications or a causal estimate. No evidence tools/outer revision loop here:
this tests automatic-source interpretation, never autonomous coverage or production
quality acceptance. This diagnostic is within current paid authorization; production
code/state and failed native result remain unchanged.
