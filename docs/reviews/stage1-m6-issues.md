# M6: issue storage and report locations

Owner request: continue the agreed M6 slice, keep the dispatcher unchanged, run the full offline regression, then tag and push for review. Baseline: accepted M5 `64c9b4e`. Work remains on `codex/stage1-m6`; promotion to main follows owner acceptance.

## Scope and design

M6 migrates `report_issues`, `g6_issue_record:*`, `g6_issue_binding:*` and `g6_issue_route:*`. Case-local immutable versions hold issue content, its report binding, operator placement and runtime wait projections. Existing content versions and heads are reused. Historical keys remain readable and are not rewritten. There is no joint transaction with the assertion database, backlink, new digest or vocabulary amendment.

Genuine human replies to generic questions and typed planning/export waits use S2 question/decision actions. The case answer is saved first; the question and answer are recorded separately, and the runtime projection follows. A lost projection reads the authenticated answer; repeating each step is safe. Generic replies can be revised or leave the issue unresolved. Plan and requirements checkpoints retain their M4/M5 authority paths. Placement records are content, not invented owner questions.

The host issue view includes report proposals and locations, human waits and current assertion questions, gaps, assumptions, conditionals, conflicts and findings. The wait-only query used by guards preserves the existing human-pause behavior. The host view is not an unrestricted agent query. Writer assignment, citation, proposal receipt and required-issue identity checks remain in their existing entry points.

The trusted operator reads the combined view with `report-agent issues --project CASE`. This is separate from the agent's project summary; the unrestricted host view is not placed in an agent prompt or packet. Material records retain exact node or section/object bindings; unplaced questions have an empty location list rather than an invented paragraph. Judgment entries identify their logical slope, with exact rendered placement left to assembly.

## Verification boundary

Verify immutable history, historical reads, rollback in an existing transaction, exact redo, changed human replies, a crash before the owner act, a crash after the act and before projection, typed resumes, Writer proposal integrity and operator placement priority. A later route version must leave an earlier frozen Word/Excel pair unchanged. Existing required-issue tests must still show one Word comment per Excel row. Run the offline Fake03 replay and the full repository suite, compare coverage/type diagnostics with M5, and record independent review and dispatcher/S2 diffs.

Test temporary directories use pytest's `failed` retention policy with count one. Concurrent shards receive stable separate temporary roots without `--basetemp`; logs and evidence remain outside those roots. G5 and historical operational cases are untouched. No report model call is part of this slice.

## Pending engineering work

The engineering lead is still a role without a named person. The 11 pilot scoring criteria and HP02 page 115 remain pending technical review; no request has been sent and no engineering judgment is supplied by this migration. The owner confirms resulting project conventions before the real report. This does not block the offline M6 storage migration.

The consolidated later work is recorded in [section 9a handoff](stage1-9a-consolidated.md).
