# Stage 1 M9 — retained old-route boundary

Source: **0 lines added / 0 removed**. Checks/guard families added/removed: **0 / 0**. New legacy fallback paths: **0**.

The owner accepted the privacy follow-up at `3b49947` and directed M9 to proceed. The approved Stage 1 plan, section 3 O5 and section 9, keeps the old Coordinator/web routes behind accessors until after the first real report. M9 therefore records retention, **not migration or retirement**. No new architecture or S2 amendment is proposed.

| Family | Verified consumers and disposition |
| --- | --- |
| `corrections` | Workspace producer corrections, revision input and delivery/status. Retain `legacy_state` read/write accessors. Several other M0 text matches are public fields or typed review records, not this state key. |
| `source_changes` | Catalog import plus Workspace source-impact and delivery. These have shared live readers; retain the existing accessors. |
| `result_impact_assessments` | Workspace producer-scoped usability assessments and status. Retain; do not substitute `stale_derivations` across incompatible legacy result/assertion IDs. |
| `decision_observation` | Existing runtime, CLI and repetition snapshot. Retain; dispatcher behavior is unchanged. |

The unchanged M0 scanner found 868 static sites, of which 87 cover the 16 M9-classified families. There are 28 explicit calls to the four core getter/setter pairs; grouped SQL snapshots and broad readers are recorded separately. Static counts do not prove runtime use or inactivity. The 12 additional mixed census families remain separately listed; this audit does not claim their report meaning has been split or migrated.

**Verification by Main:** 137 focused tests passed on an isolated source copy: legacy storage guards, correction/revision ownership and rollback, source supersession and impact, catalog/library behavior, agent boundaries, M3 calculations, and the production Fake03/control replays including A/X32 and unscored A/X51. All 6,159 tests collect. All 962 tracked source, script, test and configuration files remain byte-identical to the accepted base; dispatcher, S2 and tests are unchanged. No tests were deleted, so no retirement mapping is needed. Coverage was not remeasured for unchanged code. Pytest's failed-only/count-one automatic retention remains enabled.

**M10 handoff:** keep these routes and their active readers/storage, plus the operational/task storage still used by today's dispatcher. Do not forbid or remove a deferred family merely to claim zero legacy state. Use the existing guardian for migrated families. No paid run, report restart, full regression, historical-case change or ledger/hold change occurred. The owner's one clean full run remains scheduled after M10, before 9a. Main stays at the accepted base until this review is accepted.

[Results](../verification/stage1-m9/results.json), [retained-family list](../verification/stage1-m9/retained-families.tsv), [explicit callers](../verification/stage1-m9/core-family-callers.tsv), [current census](../verification/stage1-m9/m9-state-sites.tsv). Detailed logs and the approved-plan copy are private under `.private/stage1-m9-20261109/`. Independent review remains for the owner.
