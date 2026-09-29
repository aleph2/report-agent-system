# Task027 verification: compact geometry and explicit structure

2026-09-29. Stage: critical-risk validation through the native report/review trunk.
Main implements and integrates; independent alignment_review reviews design/code;
postrun_review authored independent fixtures and will assess runtime content. No
new runtime agent, mandatory review sequence or engineering approval is introduced.

## Design and implementation scope

Task026 completed without content improvement despite actual prompt loading and
designp97 arrival. Public tool-context size motivates this separate representation
factor; it does not prove attention failure, truncation or a sole root cause.
The task packet predeclares unchanged calibrated prompt/model/rubric/native loop,
with all authorized callers' normal source reads/searches using compact geometry.
Actual autonomous selected pages may differ; source bytes and selection rules do
not. Empty-cell geometry and explicit spans add visible structure beyond the old
sparse nonempty bounds, so this is not a pure text-length intervention.

Main builds each raw table first. Compatible complete cell rectangles become exact
shared x/y edges and1-based geometric [row,column,row_span,column_span]; all extracted
rows/strings/empty/null values remain. Dimensions, anchors, null correspondence,
overlaps and old nonempty bboxes are checked. Conversion failure falls back per
table, preserving original text and sibling candidates. Coordinates are not rounded,
drawing-frame candidates are not filtered, and no meaning/header/value is filled.
inspect_source_page remains the original raw view with source membership/hash checks.
The optional fresh-fork flag binds into the existing target/configuration identity;
defaults, previous configurations, prompt, schemas and tool catalog remain unchanged.

Independent design/implementation review found no material blocking deviation.
Main incorporated its scope clarifications and per-table fallback requirements.
The reviewer did not run tests, inspect private model reasoning or claim report
quality. Main accepts this scoped alignment result and retains quality verification
as the actual native experiment, not another runtime gate.

## Offline evidence and independent fixture

Independent three-page PDF is tests/fixtures/table_geometry027.pdf, raw SHA256
6df478e92dde6ac964b6777314bc3c619802f367ba7f9b75f4220328a68fadf0.
Authored expected JSON SHA256
5497fbb68cc9121df8f3b753aa098bab71e34165c4fbf2f8929baa2471b210f3.
Expectations derive from original hand-authored cell definitions, not converter
output; the independent reviewer checked native extraction and rendered all pages.
The fixture covers ordinary blanks, horizontal/vertical/empty spans and a new
irregular quarter-point grid. Main read the expected structure after the generic
converter was implemented; its first use is independent, later use is regression.

15 new tests passed in4.68s. Relevant source/document tools, context, calibration,
native reviewer and feedback regressions then passed154tests in28.76s. These checks
include complete authored-rectangle reconstruction, unchanged rows and raw-access
locator, hash/membership boundaries, immutable experiment selection and invalidating
old acceptance even though the prompt itself is unchanged. No model calls occur.

P3-027-T01 (test setup only, fixed): two initial tests updated source_blocks before
constructing Catalog, so the table did not yet exist. Main corrected test setup;
the15-test run then passed. No production defect or paid replay resulted.
P3-027-T02 (independent validation finding, fixed): the first ambiguous-geometry
tests used empty native rows, allowing an unrelated anchor failure to hide absence
of the overlap check. Main supplied native rows matching the cell anchors; the
four focused cases passed in1.93s. This local test-confidence weakness did not block
the contained experiment; its planned correction is complete. No new broad test
loop or quality claim follows from these offline checks.

On identical real selected pages,11pages/15table candidates were retained:
12exact_grid_v1 and3raw_fallback. Knownp97 rows and original bboxes reconstruct;
p98 retains all three drawing/frame candidates including its fallback. The largest
same8-page search observation goes from184137 to108373 serialized characters
(about41% smaller), with frozen text/other fields unchanged. Re-extracted raw views
also exactly match the previously recorded Task026 observations after JSON type
normalization. Some small/fallback views grow, including geologyp174; no universal
size reduction or model-quality gain is claimed. Full per-page results are saved
under.analysis/task027/table-comparison.json. These are characters, not tokens.

## Fresh native baseline and execution boundary

Prepared.runs/task027/native-compact without model calls. Import attempt
d8dd051b-6c4a-423d-821a-32653b967457; grading run
3192aeda-40d3-4ab9-ac3a-d807fc348265. Original Task016 pre-review checkpoint
1f1bb22a-e92f-64bd-8073-7505502d17b7, draftcf1be9a3 body SHA256
7e86b61aa246f5f6b08ecd60c546a95c67cf88f9929f41462285c5c5eddea28d,
four original results and1617 source blocks; no graph copy/use, new OCR or manual
review findings injected. Baseline hashes stayed unchanged during preparation.
No Task027 paid invocation has occurred at this record's initial creation.
