# Sourced station-point boundary repair — 2026-11-13

Source/config: +15/-7 lines in three files; tests: +51/-7 in one existing file. One exact single-point recognition branch added; approval, source, inventory, coverage and money guards retained. No new fallback or test harness/function.

## Scope and behavior

Authenticated owner-delegated direction permits OFFLINE preparation only after strike two; paid work remains stopped. The native approval refused the cached three-versus-two question even though C was excluded. Location recognition accepted only two-endpoint values under two source-literal attribute names.

- `commission_plan.py`: sourced full-match station points become zero-length ranges. Unknown, unsourced, ambiguous, reversed or conflicting locations remain conservative. Count only included objects not proven outside; retain full inventory and independent delivery-coverage checks.
- `methods/pilot_planning.json`: existing packaged planning config now supplies `location_attribute_names`; no source-literal alias fallback and no new settings framework. The high-slope catalog and its pinned hash are unchanged.
- Canonical ScopeBoundary describes an expected count only when the cited customer text explicitly states it, otherwise null. Actual Coordinator BoundaryInput reuses that description; no count inference parser or source override was added.

## Verification at source freeze

Main extended existing boundary/range tests and the existing save-plan/native-approval count test; no new test function. Before source edits: three expected RED failures (sourced point, configured alias, three listed/two included approval); thirteen passes. After repair: **315 focused tests passed in 109.02s**, with the offline network guard. The existing inventory/coverage test omits the separate expected-count gate while retaining all missing-object/no-silent-reduction assertions. Neo reviewed the actual intended diff and RED evidence, found no blocker, and approved freeze after focused green.

A read-only frozen-case copy recomputes A/B inside and C outside, with no fresh count question. The original cached question remains; no native approval retry or frozen-plan edit occurred. The actual Coordinator set_scope_boundary tool schema exposes the shared explicit-count/null description. Private evidence: `.private/boundary-point-repair-20261113/`.

One full regression and terminal Neo review remain pending at this freeze. No paid launch, new run authority or release/replay is authorized. Fresh03, its old approval refusal, every hold and the c tag remain preserved. Any future paid work needs a new explicit decision and a fresh planning case.
