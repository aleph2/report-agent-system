# Phase2 item 1 — atomic planning lists

Source +240/−127; checks/guards added: nonempty lists, duplicate item IDs, all-index validation and whole-request replay; removed: singular model-facing edit forms; new legacy fallback paths: 0.

Owner-delegated requirement: requirement statuses, objects, sections, questions and reconciliations accept one atomic typed list. The model has one form per tool; trusted existing single-item helpers remain for real callers.

`commission_planning.py` reuses the existing item checks inside one `ContentStore.operation`. Per-item savepoints collect errors without committing a valid prefix; the outer refusal rolls back the complete batch. Successful items pass the same source, section, scope and role checks. The ordered whole list participates in the existing operation digest. Requirement-status checks reuse `_write_items` in rollback-only validation savepoints, then save one final requirements revision. Interpretation publication remains the existing separate phase; an immutable unpublished revision may remain if publication fails, and no cross-store rollback is promised.

The existing native planning tools consume list schemas; the section ingress retains outline identity, mutually exclusive source modes and fixed-text generation. Native diagnostics identify actual `items.index` fields and related fields. No dispatcher scheduling, parallel setting, source-result clearer, S2 schema, model configuration or financial row changes belong to this slice.

Main reproduced the missing batch behavior with three focused behavioral cases. After implementation, four backend/existing cases passed. The first native schema check correctly exposed the retired singular expectation; existing callers and expectations were updated in place. Five focused modules/native-flow checks then passed **175 cases**. Neo found one P2 diagnostic-wrapper regression; after fixing it and strengthening existing exact-path assertions, **10 affected cases passed**. Neo reviewed the code and logs and approved this slice; Neo did not independently run tests.

Evidence: `.private/context-fix-phase2-20261112/implementation/slice1-red.log`, `slice1-batches-green.log`, `slice1-native-focused.log` and `slice1-diagnostic-final.log`. These are offline/synthetic mechanics, not live-model quality, token savings or full-candidate acceptance.

Next slices remain binding batches, generalized full-collection reads using existing limits, Coordinator ID visibility and literal-number warnings. Full offline regression, actual-candidate replay comparison, final tag and preflight remain pending. No paid launch is authorized by this record.
