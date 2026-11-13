# Phase2 current-write numeric warning projection

Source +37/−6; projection selectors +3/−0; validation/authority guards +0/−0; legacy fallback paths: 0. New test functions: 0.

The owner-delegated follow-up requires each successful model write reply to contain only warnings for records submitted in that call, using actual record ID, relative field and uncited number. Complete warning lists remain in the operation store and owner page-sheet checkpoint. The model operation reader returns only an aggregate warning count after its existing authority checks, including the duplicated content-operation response.

`planning_inputs.compact_write_result` applies this projection after persistence, reusing saved IDs and backend warning paths. `hierarchical_tools.get_operation_receipt` uses the same helper in count-only mode. Other receipt kinds, errors, permission checks and model-attempt metadata retain their behavior. No new store, alias, dependency or owner-configured constant is added.

The strengthened existing write/checkpoint case reproduced a numeric-unit parsing defect: an ASCII sentence period after a percent or degree unit caused the unit to be dropped. Neo classified it P2 and approved the one-line matcher repair; the expectation was preserved.

Main updated existing assertions in place: **24 focused cases passed in 11.28s**, and **16 generic receipt cases passed in 15.50s**. Cases cover exact ID-prefix separation, batch index mapping, nested fields, count-only recovery at both response locations, immutable full audit, owner checkpoint retention and punctuation. AST comparison confirms unchanged test-function names. Neo reviewed final code and terminal logs and approved commit/freeze; Neo did not independently rerun tests. Evidence: `.private/context-fix-phase2-20261112/implementation/current-warning-*.log` and `current-warning-review.json`.

The preceding bb404cc full passed **6287 cases, 0 failures, 9 unchanged skips**, all 6296 nodes once, all nine coverage floors, in 2323.5s. Its 1343 source files were unchanged; passing copies and nine temporary directories were removed. That result is retained but does not qualify this new candidate: the follow-up explicitly requires its own same-60 comparison, clean full, new tag, draft preflight and Neo review. The original f7ad188 full remains failed. No provider calls or financial changes occurred.
