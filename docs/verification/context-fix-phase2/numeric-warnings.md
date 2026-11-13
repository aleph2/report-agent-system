# Phase2 item 5 — soft numeric-literal warnings

Source +90/−9; checks added: advisory normalized decimal-literal comparison and record-local citation selection; blocking guards added/removed: 0/0; new legacy fallback paths: 0.

Owner-delegated requirement: flag numbers in planning free text when absent from that record's cited quotations. Saving remains allowed, original prose is unchanged, and the owner sees the warning at the page-sheet checkpoint. This does not implement the separate 9a-f calculator.

`planning_inputs.numeric_literal_warnings` compares exact Decimal values after fullwidth/thousands normalization, preserving percent and degree distinctions. Direct citations replace inherited evidence, including empty citations. Nested semantic records without their own evidence clear inherited support; sibling citations cannot justify one another. Requirement interpretations join only their exact anchor and continuations. Planning labels, reasons, interpretations, notes, results, differences and replacement text are scanned; reviewed method/table internals, source quotations/examples and human/historical owner/carried records are excluded. Candidate-disposition reasons without their own citations may therefore warn.

Existing edit receipts expose warnings. `commission_plan.request_checkpoint` recomputes them from the exact pinned plan and requirements; the existing checkpoint sidecar, full appendix and owner Markdown/HTML/audit receive that same projection. No warning store, assertion kind, plan field, authority change or refusal was added.

Main reproduced two missing behaviors, then the planning/H32/checkpoint/parity checks passed **173 cases in 108.19s**. Review identified record-boundary and replacement-field gaps; they were fixed, and the final strengthened behavioral/brief/skeleton/carryover checks passed **111 cases in 32.11s**. Existing brief assertions still verify original plan/requirements digests and appendices; warning visibility is checked in Markdown, HTML and audit. Counts overlap. Neo reviewed final source and logs and approved this commit and full-candidate offline freeze; Neo did not independently run tests.

Evidence: `.private/context-fix-phase2-20261112/implementation/slice5-red.log`, `slice5-behavior.log`, `slice5-focused.log` and `slice5-final.log`. Matching literals do not establish arithmetic, general unit conversion, semantics or numeric correctness; scientific notation and malformed grouping are not certified. Full regression, replay, final tag and preflight remain pending. No paid call or financial mutation occurred.
