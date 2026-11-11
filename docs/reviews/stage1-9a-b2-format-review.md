# 9a-b2 — spec-driven tables and Word comments

Production Python **+135 / −202, net −67**; spec data **+18 / −2**; tests **+306 / −123**. Total excluding documentation: **+459 / −327, net +132**. Explicit raise/assert sites +1 / −2 (duplicate title checks consolidated, shared check retained); two requested test guards added. Two table-layout fallback paths removed; no new legacy fallback.

**Full offline verification passed; owner code/page acceptance pending.** Main stays at accepted c (`2133225`). No model calls, dispatcher/S2 changes, score/judgment changes, installs or original-case/ledger changes.

## Result and scope

- Scored and unscored data use the same saved TableSpec. No hard-coded draft columns, scored fallback or inline-citation/de-duplication path remains. Missing assessment specs refuse. Column proportions live in the spec and feed the existing renderer controls.
- Word comments use 来源/来源： and 待核/待核：. Commission instructions are filtered only from display; immutable issues and required-issue validation are preserved. Excel retains page-level sources.
- Skeleton numbering produces 3.1/3.2 and matching table captions; conditional grades retain Chinese method descriptions without doubled punctuation.
- The fresh synthetic pair contains 19 unscored indicators, three unchanged trial values (37, 27, 62), no adopted score/risk, eight source comments and 23 open comments matching 23 Excel issue rows. Twenty indicator comments anchor on 取值; three planning comments anchor on their own text.

## Verification

Main inspected all 13 LibreOffice-rendered PDF pages. Earlier equal/narrow-column previews remain as failed layout evidence; the final spec keeps decimal weights and 未评分 readable. Word bytes were unchanged by PDF conversion. Native Word rendering has not been checked; Excel print layout is out of scope.

The one authorized full run on exact `41826ec` passed **6,187 tests, nine unchanged skips, zero failures**, all 6,196 nodes once, in **50m28s**. All nine M0 coverage floors passed; overall coverage **90.62%**. All 1,270 frozen files were unchanged; the source copy was automatically removed, no temporary test databases remain, and the exact run processes are absent. [Full record](../verification/stage1-9a-b2/clean-full.json). Post-run reporting corrected an inherited floor-key lookup; no source/test edit or test rerun.

Focused results and exact file hashes are in [candidate.json](../verification/stage1-9a-b2/candidate.json). The two guards check format ownership and real Word/Excel output. Test-only mutations restoring instruction-source citation and old numbering both fail the intended tests; repository source stays unchanged. [Two renamed width cases and four explicit historical cases](../verification/stage1-9a-b2/retired-tests.tsv) retain explicit replacements; no test is silently dropped.

Earlier fixture/layout failures and the interrupted focused run remain as failed/interrupted evidence. The attached affected run passed 1,008 tests; final fixture-dependent checks passed 37. Counts overlap. Private evidence: `.private/stage1-9a-b2-20261110/`.

Next: owner code/page acceptance, then main fast-forward. Paid Fake03 remains a separate gate with a frozen Chinese-text answer key and owner scope/cap. Actual paid-trace refusal measurement precedes removal decisions; the qualitative frozen-digest check stays in e.
