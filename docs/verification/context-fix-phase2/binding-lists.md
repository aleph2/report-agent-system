# Phase2 item 2 — atomic page-binding lists

Source +123/−36; checks/guards added: nonempty typed lists, all-index diagnostics, duplicate object/indicator detection and whole-request replay identity; removed: singular model-facing binding form; new legacy fallback paths: 0.

Owner-delegated requirement: one binding item may name several indicators for one page set, and one model call may contain several items. All binding assertions succeed or fail together without changing the S2 schema. Existing trusted single-item callers use the retained helper; the model sees only the list form.

`page_bindings.propose_many` validates every item against the saved plan, Coordinator subject authority, actual indicator IDs, source versions and physical pages before writing. Every child authorization includes the complete ordered normalized request and exact plan reference; appending or changing another item cannot reuse a completed prefix. The private assertion action holds every authorization while one existing S2 write transaction saves all children and operation receipts. Late C4 failures roll back the whole assertion batch.

Atomicity covers binding assertions. Source snapshots are captured first and authorization records may remain after a refused assertion transaction; this follows the existing separate-store boundary. There is no cross-store rollback promise or new action catalog entry. Existing diagnostics retain domain reasons and actual indexed input fields.

Main ran two behavioral RED cases, then **5 backend cases passed**, and **32 existing/native focused cases passed in 25.15s**. Coverage includes late rollback, cross-store refusal, exact replay, changed whole-request refusal, indexed errors and the native 22-binding owner checkpoint. Current callers and schemas were updated in place. Neo reviewed source and logs, found no P0–P3 issue and approved this separate commit; Neo did not independently run tests.

Evidence: `.private/context-fix-phase2-20261112/implementation/slice2-red.log`, `slice2-backend-green.log`, `slice2-assertion-atomic-green.log` and `slice2-native-focused.log`. Full-candidate regression, actual-candidate replay, final tag and preflight remain pending. No model call or ledger/hold mutation occurred in this slice.
