# Post-M10 clean verification and planning-conflict trace

Source: **0 lines added / 0 removed**. Production checks/guards added/removed: **0 / 0**. New legacy fallback paths: **0**.

Accepted M10 is e86284a. Main was fast-forwarded to that exact commit and the milestone branch was deleted. The owner explicitly authorized one clean offline full regression before 9a. It runs on a frozen archive of accepted main with 51 hash-verified private fixture inputs imported explicitly, the existing offline network guard and failed-only/count-one pytest retention. Its result is pending; no paid launch is authorized.

## Three planning conflicts: fixture omission, not an M6 regression

Planning is not absent: prepare_mini_commission saves and confirms the scripted plan. commission_plan.required_material_issues creates obligations from two reconciliation differences (design versus survey, initial date versus revision) and slope A's competing ratio inventory. reply stores those obligations in CommissionDecision. It does not invent the full comment's adopted wording or choose arbitrary output locations.

The omitted work is later in the scripted replay: it never calls Writer propose_material_issue for these obligations or the trusted routing command for the two general reconciliations. The Writer proposal creates the full IssueRecord and IssueBinding. record_issue_routes supplies explicit destinations for reconciliations; inventory routes are system-derived when an assessment is admitted.

Main ran the **same test** on accepted M10 and pre-M6 7e19856. Both passed with the same progression: 3 missing records/bindings/routes initially; 0 missing records/bindings after three normal Writer proposals; only one missing route after two trusted reconciliation routes. That last route is slope A's inventory route, dependent on assessment admission. The missing-assessment gate is intentionally left intact, and no report is exported. No M6 storage fix is indicated.

The new test records the omitted fixture stage using only choices already in the confirmed synthetic plan. It preserves the original M10 negative replay; no fake scoring, direct database injection or export-check weakening. The fixture omission is P2 and does not block 9a once the full run passes. Completing inventory routing for unscored results belongs to the mandatory 9a draft support.

[Trace and exact producer map](../verification/stage1-post-m10/conflict-trace.json). Detailed comparison logs and frozen cases are private under .private/stage1-conflict-trace-20261109/. Main executed the comparisons; independent review remains pending.

## 9a entry/exit

Do not start 9a implementation until the clean full run is reconciled. Start with the required agent-field/check inventory and concrete S2 amendment proposal. Dispatcher remains unchanged. Rendered-page QA of the paired Word/Excel drafts is a required 9a exit criterion **before any paid run**, alongside unscored rows/reasons, not-determined risk level, assertion-only corrections, and formal-release refusal for unscored/unwaived indicators. Paid Fake03 and the real report each still need separate scoped launch authority.
