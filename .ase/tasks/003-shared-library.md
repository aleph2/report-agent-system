# Task003: shared library and producer correction

User asked to continue implementation, 2026-09-27. Work only in the independent
repository. No new provider calls, OCR, legacy imports or engineering data uploads.
Stage: end-to-end trunk construction; semantic model acceptance remains open.

Main owns source catalog/version receipts, paginated literal retrieval, runtime tools,
HTTP/CLI integration and integrated verification. Halley owns file text parsing and
parser tests. Feynman owns producer-bound revision/impact and its tests. Sagan provides
independent read-only alignment review. UI work is separately bounded to static files.

Import TXT/MD/DOCX/PDF as immutable original bytes plus located extracted text, with
explicit parser limitations. No claim of complete OCR/image/layout extraction. A new
version preserves previous source IDs and bytes. Explicit replacement has optimistic
current-version checking and repeatable receipts. Source updates occur under the project
lock, not while agents are running. Retrieval is a local literal-search baseline with
pagination, not semantic identity resolution or a completed graph platform.

Agent tools expose observations and choices, not a forced intake/analysis/write chain.
Only the bound producer may commit a replacement result. Corrections and dependencies
are durable; descendants are marked outdated without automatic reruns. Original changes
are visible to the coordinator, including additions that have no existing consumers.
Unassessed changes and outdated inputs cannot silently remain a reviewed delivery.

Verify import/read/reuse/correction/affected draft/review/export using real ADK with
scripted model responses, plus receipt replay, version conflict, permissions, rollback,
HTTP limits, browser desktop flows and existing regressions. Synthetic protocol tests
are not real-model semantic validation. Deploy only the new synthetic workbench.

Implementation/verification increment completed: 120 tests pass, scoped independent
review findings corrected, local synthetic 18140 redeployed and desktop paths checked.
See `.ase/verification/003-shared-library.md` for evidence and remaining acceptance
boundaries. Overall G2/real-model report acceptance is still open.
