# Public v4 Writer assignment repair — 2026-11-13

Source: +9/-6 lines in four files; tests: +79/-3 in two existing files. One public role/new-assignment validation added; no backend eligibility, evidence, assembly or money guard changed. No new fallback path. The accepted historical G3 calculator interface is retained; the unusable bulk calculator is removed from all system-assembler-v1 Writer catalogues, bound and unbound.

## Requirement and change

The actual Coordinator task schema forbade the object binding that the backend already accepted, and the public adapter discarded it. The failed production case therefore could not offer its Writer the canonical assessment action. The owner-delegated bounded repair and additional forwarding-file exception are preserved privately.

- `co_review_message.py`: optional assessment_object_id describes one included confirmed-plan object and is restricted to new Writer assignments. Existing writer_assignment remains the only object/section eligibility validator.
- `live_messages.py`: forward that non-null field in the actual _assemble_task path; no new check there.
- `hierarchical_tools.py` / `deep_runtime.py`: remove the bulk calculator through the existing system-owned filter; hide the canonical action only for an unbound task. Keep section prose tools.
- Backend content_tasks already persists and validates the binding; no backend edit was needed. No prompt, parser, cap, model, ledger, failed-case or retry change.

## Verification and remaining gates

Main ran the two authorized new production-path tests on old source 8ac1d1a before editing: both failed for the reproduced missing-public-field and unbound-legacy-tool defects. Qualification builds the exact public task schema, traverses _assemble_task, persists the Writer binding, checks the actual Writer BusinessBoundary offer, refuses excluded C, and checks the unbound offer. Existing role/continuation cases and the existing section-tool expectation were updated in place.

Main focused result: **61 passed in 14.58 seconds**, offline network guard enabled. Neo independently reviewed the actual source and RED/focused evidence, found no blocking defect, and approved source freeze plus the one required full regression; Neo did not independently rerun tests. Line endings were preserved without whole-file reformatting.

Full regression, source/fixture hashes, coverage floors, cleanup, final Neo review and immutable c tag are pending at this source freeze. Private qualification evidence: `.private/v4-assignment-repair-20261113/`. Do not launch before the requested commit/tag/review/count package is sent. A fresh planning case and a fresh sheet review are required; the failed case and every hold remain unchanged.
