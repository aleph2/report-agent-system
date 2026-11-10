# Part b2 — report format comes only from the spec

Production source +0 / −0 in this plan; implemented checks/guards +0 / −0; new legacy fallbacks 0. The two b2 guards below are planned, not implemented or measured.

## Timing and gates

Part b remains accepted at `fdf8f93`. Finish and accept c first; then start b2 from main after main advances to c. Reuse the current branch; do not edit c and b2 files concurrently. Paid Fake03 requires accepted a, b, c and b2, the measured inventory, the frozen answer key, and separate owner-approved launch scope/cap. C lists b2's two guards as planned and updates them when b2 lands.

## Principle and change list

Everything prescribed by the guideline or template is defined once in the method pack's spec: table layouts, captions, numbering and source placement. Content code supplies data; the renderer alone creates layout. Before coding, list additions/removals by file, with the requirement and reader for each addition. This part should remove more code than it adds. Report source, tests and spec data separately and report the total honestly.

## Tables: one layout from Table 3-2

Assessment code supplies data only: category, indicator, grade description, range, value, weight, score and explanation. It supplies no headers or captions. Unscored value/score are 未评分; explanation retains the reason and remaining candidate grades. Grade rows and ranges still appear.

One exporter renderer handles scored and draft tables from the spec: 分类 / 评估指标 / 分级 / 基本分值（分值范围、取值） / 权重系数（γᵢⱼ） / 评估分值（Xᵢⱼ） / 说明. Ranking uses 序号 / 评估指标 / 权重系数, caption 表x … 权重系数排序. Missing spec refuses export. Delete draft column lists in `draft_assessment.py` and the scored fallback in `risk_scoring.py`.

## Sources and open items as Word comments

Delete inline body citations and b's adjacent-citation de-duplication workaround. Source comments: author 来源, prefix 来源：, sources formatted as 《document title》第N页. One comment per supported statement or table, anchored on its sentence or table caption rather than paragraph fragments.

Open-item comments: author 待核, prefix 待核：, anchored on the indicator's 取值 cell. Keep one to one with Excel issue rows (23 in Fake03). Never cite commission-instruction imports (scope and requirements), in comments or anywhere else. Use the existing import roles; add no new role data. Excel issue sources remain page-level.

Authors make the comment kinds filterable; Word/LibreOffice choose their colors. Do not prescribe exact colors. Comments do not print and may be removed before release; formal-release source placement remains in e.

## Numbering and cosmetics

Use skeleton/spec numbering: 3 边坡评估 → 3.1 坡段A and 3.2 坡段B, with matching table numbers. Remove doubled 。； punctuation. Source titles use 《title》 with correct spacing.

## Two planned guards

1. Fail if code outside the renderer defines an assessment-table header list or caption pattern. Spec data remains the single format definition.
2. Inspect Word: assessment headers/captions match spec; no inline body citations; every comment author is 来源 or 待核; 待核 comments match Excel rows one to one; no commission-instruction document appears as a source.

## Verification and acceptance

Before tagging, search tests for old-column and inline-citation expectations. First reproduce header, inline-citation, instruction-source and numbering findings with failing tests; then run focused checks. Regenerate Word, Excel and PDF with file hashes for owner page review. Also supply a short Word-comment list with author, anchor and text, since PDF does not show comments. Run one full offline regression, then owner acceptance and main fast-forward.

Out of scope: Excel print layout, real Word footnotes, formal-release source placement (e), and changing scores or judgments. Chinese reader-facing reasons/questions remain a requirement in the new frozen paid-Fake03 answer key, preserving exact quotations and system identifiers. Historical frozen keys stay intact.
