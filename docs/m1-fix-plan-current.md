# M1 Fix Plan: Before the Rerun

Nov 2, 2026 · @Sandra GonzalezKo

**Goal:** fix what pilot M1 showed, verify the fixes offline, then rerun the same folder. The rerun must pass the list in step 6.

**Principle:** each fix is a record or a check the system owns, not prompt wording. M1 showed the agents already had most of these instructions and did not follow them. Agents keep the judgment: what to read, how to score, what to write. The system enforces the agreed scope, the calculation, the format and what may appear in the export.

**Order:** one stream, steps 1 to 6 in sequence. Each review gate in the last section ends with a tag for code review. The Reviewer's Steps 4 and 5 come after the rerun. File paths are starting points from the current code; the team confirms them when implementing.

## Agreed decisions

1. **Template report.** The 成果报告 PDF is the 模版报告 in scope §4. Fixed sections are copied from it, changing only project names, mileages and numbers. Facts and scores come only from the design and survey materials.
2. **Section plan.** The outline Word file is the section plan. Each section is fixed, extracted from a named document, or derived from another section.
3. **Scoring.** All 11 indicators of guideline Table 3-2 for every slope, as in the template. An indicator without direct evidence still gets a value, under the Rules for G3. The system takes the weights from Table A.3-1, computes X, F and the level, and the table is rendered in Table 3-2's form.
4. **Deliverables.** Word, plus an Excel clarification list for the end user. No PDF.
5. **Material issues.** Conflicts, unclear items, missing items and assumptions become records. They appear as Word comments and as rows in the Excel list, not in the report body. Chapter 6 keeps the template text.
6. **No internal content.** No internal IDs or agent working notes in the report.
7. **Checkpoint.** Before writing starts, the person who submitted the folder confirms the object list and the section plan. In the pilot that is the owner, not the end user.
8. **Storage.** File content moves out of the database into a hashed file store, with only metadata and a relative path in the database.
9. **Scope.** Only the first contract section's five deep-cut slopes. The supplied first-contract-section documents replace the outline's whole-project documents, citing scope §4.
10. **Report-specific rules live in the scope file.** 《报告编写范围说明》 §5 now states six numbered conventions (design priority, Table 3-2 format, Table A.3-1 weights, comments and Excel list, Word and Excel only, assumptions from indirect evidence). Two more are suggested to the owner: 7, all 11 indicators; 8, which file the template is and what may be copied from it. The suggested wording is in `scope-conventions-review.xlsx`. Until the owner adds them, decisions 1 and 3 here still apply. For other report types, the customer states their rules there too.

## Step 1: Reliability and storage

M1 ended with `SQLITE_BUSY` on a commit, with `state.db` at 1.04 GB in DELETE journal mode.

**1.1 Measure first.** Break down the M1 database by table, key prefix, row count and bytes. Known so far: `state` 452 MB, `source_versions` 407 MB, `events` 177 MB. `catalog.py` stores each source file in `source_versions.original` as a BLOB. Check how many versions and copies of each input exist.

**1.2 File store.** Add a module (suggested `blob_store.py`) that saves content under `blobs/<first 2 hex>/<sha256>`:

- Write to a temporary name, rename, then commit the database row.
- Stored files are never changed. Reads check the hash.
- The database row keeps the hash, size, media type and a path relative to the case folder.
- Add a cleanup for files no row points to.

Move `source_versions.original` to it first. Then move the other large values the measurement finds, starting with the largest. Keep audit and recovery records in the database.

**1.3 Database settings** (`store.py`, `connect`). Turn on WAL mode with `synchronous=FULL`. Keep the 15-second timeout. Check WAL is active on the actual run database at start, and stop with a clear error if it is not.

**1.4 Local lock errors** (`content_store.operation` and the reservation write in the vision path). When a local transaction hits `SQLITE_BUSY`, retry it a bounded number of times with a short backoff. Use the operation ledger, keyed by operation id, to decide what committed. If it still fails, return a retryable tool error to the agent. Never re-send a model call, and keep uncertain outcomes marked as uncertain.

**1.5 Monitoring.** Collect metrics from emitted logs. If a database view is needed, use the SQLite online backup API on a copy. Never read the live file directly.

**Done when:**

- A test that holds a read lock during a write ends with a retryable tool result, and the run continues.
- A test confirms no model call is repeated after a local failure.
- Re-importing the M1 inputs gives a database that is a small fraction of 1.04 GB, with every file readable and hash-checked.

## Step 2: Requirements into records

**2.1 Host goal** (`scripts/report_host.py`, `prepare()`).

- Replace the hard-coded goal with a generic frame: write the report the requirements describe, using the design and survey materials as the factual basis.
- Remove "成果报告PDF仅供结构和格式参考" and the fixed 设计与地勘 rule from the goal and `scope_instruction`; the customer's conventions come from the scope file (2.4).
- Keep `COMMISSION_OR_REFERENCE_AMBIGUOUS` only for the scope file: exactly one `报告编写范围说明.md`. The template PDF under `成果报告` is registered with the purpose `template`.

**2.2 Configuration** (`config/current.json`, `scripts/stage_report.py`).

- Set `synthetic` to `false`.
- Replace the exact `input_file_count` with a maximum, since the approved hash list already pins the files.
- Set `round_token_limit` to about 100M per run. The 200M budget is the M1 total, tracked across runs.
- Remove the stale `tool_discovery_profile`.

**2.3 Section plan** (new, suggested `section_plan.py`). Read the outline Word file once into a record with one row per section:

- **Fixed:** the matching section of the template PDF (pages and text), plus the list of values to replace (project name, contract section, mileages, counts).
- **Extracted:** the named source document, such as 施工图总说明 for 2.1–2.5, or the deep-cut slope design volume for 4.1. The outline's 4.1 images are kept as examples of the drawing set to read per slope: plan, geology sheet, elevation and typical section. They are not used as content or facts.
- **Derived:** the source sections and the rule, such as chapter 5 = template text with chapter 4's results inserted.

The plan is built by an agent and saved through a tool, then confirmed at the checkpoint (step 3). Writing tasks are assigned per section from the saved plan, not from prose.

**2.4 Customer conventions and the method pack.** Save each numbered item in scope §5 as a convention record with its exact quotation. Every agent interpretation is saved separately and labelled as an interpretation, never as a customer requirement.

Rules that need prepared data are carried out from a reviewed **method pack** for the guideline: the transcribed Tables 3-2, 3-3 and A.3-1 (step 4.1), the Word template from the format standard (step 5.1), and the template report for fixed text. The Coordinator links each convention to a method-pack entry, and the checkpoint brief lists the links, for example "约定3：权重系数 → 指南表A.3-1，11项一行". Two cases need care:

- **No matching method-pack entry:** the brief shows it as an open question, and writing does not start. Agents never improvise the rule.
- **The scope file says nothing on a point:** the guideline default applies, labelled "默认，未约定" in the brief so the owner can override it.

Order of precedence: scope file, outline, guideline defaults, template report.

**Done when:** offline, the M1 outline and scope file produce a section plan with 1.1, 1.2, 1.4, 3.1, 3.2 and chapter 6 as fixed, chapter 5 as derived, and 1.3, chapter 2 and chapter 4 as extracted, each with its source.

## Step 3: Object inventory, checkpoint and delivery check

**3.1 Object inventory** (new, suggested `scope_inventory.py`). An agent saves each assessment object through a tool. Each object records:

- mileage, side, length, height, type (deep-cut or retaining), soil or rock;
- the source document and page for each value;
- whether the inclusion comes from the customer's text or is the agent's interpretation.

**Scope boundary first.** 施工图总说明 and 平面总体布置图 cover the whole project, but this report covers only the first contract section: the five deep-cut slopes in it (confirmed by the owner, 2026-11-02). The inventory first records the contract section's start and end mileage, with its source page. Objects outside that range are out of scope. They are not listed as missing and do not create material issues.

**Cross-check within the boundary.** The outline's 1.3 cross-check applies only inside the contract section: objects from 施工图总说明 and the design volumes are reconciled with 平面总体布置图. A difference inside the range becomes a material issue (step 5). Conflicting values are kept side by side with their sources; a single unknown value never removes an object. The checkpoint brief must show exactly the five slopes; any other count is a question for the owner before writing starts.

**3.2 Checkpoint brief.** After the section plan and inventory are saved, the system writes a short brief to the output folder:

- **Object list:** one row per object, with the included/excluded state and reason.
- **Section plan:** each section, its type and its source.
- **Deliverables and conventions.**
- **Open questions:** only those the materials cannot settle.

The run pauses through the existing human-question path (`ask_human` in `deep_runtime.py`) until the reply: approved, or a list of corrections. For the pilot the reply comes through the command line or a reply file. With no reply, the run keeps waiting. The confirmed inventory version is what the delivery check uses.

**3.3 Per-object outcome.** Each confirmed object must end in one of:

- **Complete:** the agreed score, risk level and section exist, with every indicator value cited or labelled as an assumption.
- **Reduced by the customer:** a reduced scope recorded at the checkpoint or by a later question.

Anything else is **incomplete**. Extend `review_coverage.py` so the confirmed inventory objects are expected objects, alongside the existing snapshot ones, instead of adding a second coverage system.

**3.4 Delivery check** (`deliverables.py` / `content_delivery.py`). At delivery the system lists every object without a complete or customer-reduced outcome. If any exist, the report is delivered labelled **incomplete**, naming those objects, and the run is not reported as successful. The Reviewer can accept that a limitation is honestly stated; it cannot cancel a commissioned object.

**Done when:** offline tests cover:

- five objects, four assessed: delivered as incomplete, naming the fifth;
- one parameter unknown: assessed, with the unknown stated;
- a reduced scope accepted by the customer: delivered, with the reduction recorded;
- a reduced scope not accepted: incomplete;
- an object the agent excluded with only its own interpretation: incomplete.

## Step 4: Scoring

**4.1 Table definition as data** (suggested `templates/guideline-table-3-2.json`). Transcribe guideline Table 3-2 once:

- the 5 categories and 11 indicators (X11, X12, X21, X22, X23, X31, X32, X41, X42, X51, X52);
- each indicator's four grade rows with their text and score bands (0–24, 25–49, 50–74, 75–100);
- the notes column, including the interpolation and take-the-larger-value rules;
- the Table 3-3 level bands for F.

The team checks the transcription against the guideline pages. A different guideline later means a new data file, not new code.

**4.2 Scoring records** (new, suggested `risk_scoring.py`). For each slope the agent saves, through one tool per call:

- the importance ranking of the 11 indicators, with a short reason;
- for each indicator: the grade row, the value within its band, the evidence (design or survey document and page), and the explanation for the notes column. An indicator without data still gets a value and a stated reason.

**4.3 System calculation** (reuse `calculations.py`). The system:

- checks every value is inside its chosen band, and every indicator is ranked once;
- takes the weights from guideline **表A.3-1 重要性排序法权重系数表** by the number of indicators and each indicator's rank, with no calculation. This is the customer's convention, to be stated in 《报告编写范围说明》 (owner, 2026-11-02). Table A.3-1 is transcribed into the 4.1 data file with Table 3-2, rows for 1 to 12 indicators, and checked against the guideline page image, because the extracted text of that page is garbled. For 11 indicators the row is 0.17, 0.16, 0.14, 0.12, 0.11, 0.09, 0.07, 0.06, 0.04, 0.03, 0.01, the same as the template report. This replaces the earlier rounding rule;
- computes X = R × γ with those weights, F = ΣX, and the level from Table 3-3.

Agents never write the arithmetic. Section 3.2 keeps the template's method text, so no formula working appears in the report.

**4.4 Two tables per slope.** The exporter renders the weight ranking table and the evaluation table from the 4.1 definition: Table 3-2's columns, all four grade rows per indicator with merged cells, and the adopted value, weight, score and notes.

**4.5 Reviewer check.** Every indicator value cites the design or survey material. A value that matches the template report's score for the same slope without its own citation is flagged.

**Done when:** offline, the five slopes' indicator choices produce tables whose arithmetic matches a hand calculation, and an out-of-band value, a missing indicator or a duplicate rank is refused with one message listing every problem.

## Step 5: Output

**5.1 Word template from the format standard** (suggested `templates/report-format.dotx`, used by `content_export.py`). Build it once and check it against the standard:

- A4; margins 2.5 / 2.5 / 2.5 / 1.5 cm;
- 宋体 for Chinese text, Times New Roman for numbers and Latin text;
- headings "第一章 / 1.1 / 1.1.1 / （1）" with the sizes, spacing and alignment in the standard; body 小四, 1.5 line spacing, 2-character first-line indent;
- table titles above in "X.X.X-X" form, figure titles below; tables with a 0.5 pt double outer border;
- header with project name (left) and report name (right), footer page number;
- cover and title page per sections 5 and 6 of the standard;
- a Word-generated table of contents with at least three levels.

The exporter applies it to every report. The agents do no formatting; the Layout agent checks rendered pages and reports problems.

**5.2 Report text separate from working notes** (`content_models.py`). Content nodes get separate fields for report text, citations and working notes. Only report text, and citations rendered as readable references such as "（设计文件第96页）", reach the export. IDs, locators, calculation chains and notes stay in the audit record.

**5.3 Material issue records** (new, suggested `material_issues.py`). Each issue records:

- type: conflict, unclear or missing;
- the slope or section, and the documents and pages;
- what the conflict or gap is, and the value the report adopted;
- the question for the end user;
- the passage in the report it attaches to.

The exporter writes each issue as a Word comment on its passage. The body states only the adopted value.

**5.4 Excel clarification list** (`content_workbook.py`). Built from the same records, one row per issue: number, type, slope or section, documents and pages, issue, adopted value, question, and an empty answer column. The Word comments and the list always match.

**5.5 No PDF.** Remove PDF from the deliverables. Rendering for the Layout agent's page checks stays internal.

**5.6 Checks before export.** Export is refused, with the locations listed, when:

- a fixed section differs from the template text apart from its listed values;
- an extracted section does not cite its named document;
- the text contains UUIDs, field-name patterns (`source_id`, `locator`, `calculation`, `current_limits`), list literals, English keys or remarks about drafting;
- a material issue record has no passage to attach to.

**Done when:** re-exporting the M1 content through the new path gives a Word file with the template formatting, no internal fields, the issues as comments, and a matching Excel list.

## Step 6: Offline verification, then the rerun

**6.1 Offline.** Using the M1 inputs and saved content as fixtures, with scripted models and no paid calls:

- run the tests listed under each step's "Done when";
- run the full suite;
- run one complete scripted pass through checkpoint, writing, review and export, and confirm it produces both deliverables.

**6.2 Before the rerun.**

- Stage the rerun again from the current inputs: the updated 《报告编写范围说明》 (its hash has changed), the template with `--template`, and the guideline file renamed to match §3 if the owner does so.
- Put the case folder and the token ledger on Linux storage, with the start-up guard against 9p, DrvFS and network drives.
- Report the remaining M1 budget.
- Run the two-turn check on each model.
- Agree a time with the owner, who answers the checkpoint within a few minutes.

**6.3 Rerun** on the same folder with a fresh case, the per-run limit from 2.2, and monitoring from logs only.

**Pass list for the rerun:**

1. All five slopes assessed, or a reduction the owner explicitly accepted.
2. A weight ranking table and a Table 3-2-form evaluation table for each slope, with the arithmetic done by the system.
3. Fixed sections match the template; chapter 5 is the template text with chapter 4's results; chapter 6 is the template text.
4. Chapters 2 and 4 cite the documents the outline names.
5. Every material issue appears as a Word comment and as a row in the Excel list, and not in the body.
6. No internal IDs or agent working notes in the report.
7. The format standard is applied: margins, fonts, headings, table numbers, header and footer, cover, title page, table of contents.
8. Deliverables are Word and Excel only.
9. The run completes without a local database failure.

## Rules for G3 (confirmed by the owner, 2026-11-02)

The owner's direction: make reasonable assumptions from indirect evidence, and leave pointers so the engineers find them quickly in manual review, where people decide. These rules replace the matching parts of 3.3, 4.2 and 4.5.

**Rule 1: every indicator gets a value, with its basis recorded.** The basis is one of:

1. **Direct evidence:** the design or survey document and page.
2. **A guideline rule applied to stated facts:** for example "地层分布复杂者取大值", or regional rainfall data for X31.
3. **An assumption from indirect evidence:** for example a nearby borehole, the adjacent slope, the drawing's geology sheet, or the general notes. The value is the one the indirect evidence best supports; when it supports several grades equally, take the less favourable one.
4. **An assumption with no evidence:** only when nothing indirect exists. Take the less favourable grade and say so plainly.

The agent never leaves an indicator empty. The system checks that each value has one of these bases, and that no value cites the template report.

**Pointers for manual review.** Every assumption (bases 3 and 4) becomes a material issue record. It appears as a Word comment on the value in the evaluation table, and as a row in the Excel list with the basis, the pages used and the question. Comments from bases 3 and 4 are labelled so a reviewer can filter them, with "no evidence" first.

**Rule 2: when an assumption could change the risk level.** The system recomputes F with all assumed indicators together at the lowest and highest values their plausible grades allow, holding the weights fixed.

- **The level stays the same:** the comment and Excel row are enough.
- **The level could change:** add one short sentence in the body wherever that slope's level is stated, in chapter 4 and in the chapter 5 summary, for example "X23按不利情况取值，补充地下水位资料后需复核风险等级。" The comment is marked as affecting the level.

**Completeness.** A slope with assumptions counts as assessed: it has a score and a level, and every assumption is pointed to. Delivery completeness is not engineering sign-off; the engineers' manual review is.

## Review gates

| Gate | After | What the review checks |
| --- | --- | --- |
| G1 | Step 1 | Lock-failure test, no repeated model calls, database size after re-import, files hash-checked |
| G2 | Steps 2 and 3 | Generic host goal, section plan from the M1 outline, inventory and checkpoint brief, the five delivery-check cases |
| G3 | Steps 4 and 5 | Table 3-2 transcription, calculation tests, re-exported M1 Word file and Excel list, export checks |
| G4 | Step 6.1 | Full suite and the scripted end-to-end pass, before any paid call |

Each gate ends with a tag pushed for review, as with rc3 and rc4. No paid or provider calls before G4 is approved.

## Out of scope for this plan

- **Reviewer Steps 4 and 5:** after the rerun, with the commission coverage check (3.3) as their first target.
- **Reading the end user's answers** from the Excel list back in for the next revision.
- **Embedding design drawings** (plans and cross-sections) in the report. The feedback did not ask for it; the template has them.
- **Prompt-only changes:** each fix here is a record or a check.
