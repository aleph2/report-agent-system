# Task030 verification: shared standards and native acceptance

2026-09-29. Stage: critical-risk validation. Main implemented/integrated the runtime,
prompts and tests; criteria_storage implemented acceptance.py and its focused tests.
resume_assessment provided read-only architecture advice. alignment_review independently
reviewed the design and actual control/permission boundaries. review_fork independently
ran four synthetic native probes and reviewed recovery. No paid model calls occurred.

## Delivered behavior and evidence

New-project creation marks the requirement-derived mode; binding preserves historical
projects/runs. Coordinator alone publishes immutable criteria using existing Workspace
receipts and version history. Requirement references and real operator inputs are
preserved. Writers receive the pure shared standards in actual system context before
generation, explicitly adopt their criteria_id, and cannot save against an old version.
Read-only graders use the same standard and exact saved/exported target.

Dynamic rubric preparation merges the native reset bookkeeping before evaluation,
including same-invocation standard changes. Native execution, feedback, structural
retry and durable checkpoints remain. New-mode responses add domain three-state
outcomes; unknown-only ends without a forced author rewrite. Mixed feedback separates
established defects from unknowns. Wrong/missing/duplicate IDs use the native correction
attempt; repeated bad coverage ends unverified/undetermined rather than asking the
author to repair a protocol failure. Artifact availability and all-standard satisfaction
are distinct. Optional analysis, image, arithmetic and todo capabilities do not force
a sequence, page count or defect count.

The effective new acceptance system prompt intentionally does not append the native
binary instruction that unconfirmed items should be marked failed. It uses a compatible
GraderResponse subclass and pinned0.7.19 construction/extraction hooks; this private-hook
maintenance cost remains. IDs/required fields do not validate semantic truth, criterion
completeness or whether a revision improperly weakens requirements.

## Findings and Main disposition

| Finding | Severity / impact | Containment and disposition |
| --- | --- | --- |
| Empty checkpoint inspection classified a new marked project as legacy | P2; normal inspect-before-run could bypass the new default acceptance chain; blocked that behavior claim | Fixed: inspect actual persisted checkpoint/write rows read-only; unmarked old projects remain legacy, corruption is explicit. Owner Main/criteria_storage; focused regression passed. |
| Author received grader-specific instructions inside shared criterion text | P3; mixed role guidance in author system prompt, not an observed wrong report | Fixed: pure identity/criteria payload to author/coordinator; only grader receives assessment instructions. Owner Main; actual model-input regression added. |
| Missing selected draft ended with a reason available only in audit events | P2; next invocation could not directly observe the unmet precondition; blocked actionable recovery-feedback claim, not isolated testing | Fixed: persist public acceptance_limitation and expose it in project_state/project_view, clear when a valid target is available. Owner Main; recovery regression added. |
| Native repeated structural undercoverage could send an unverified response to author revision | Review concern about protocol feedback, not a confirmed substantive report defect | Hardened: native correction attempt retained; repeated failure terminates undetermined/unverified without author repair. Focused test passed. |

## Checks

- acceptance storage focused:23 passed (5.73s), including read-only empty-inspection,
  real history/WAL preservation and malformed database rejection.
- Initial integration/legacy subset:93 passed,3 failed. The3 were Task016 fixtures
  entering the intentionally new default without standards; explicitly bound those
  historical source-tool fixtures to legacy, retaining their original assertions.
- Subsequent focused native/source-tool tests:18 passed (35.80s), including delegated
  author inputs, mixed/unknown-only outcomes, exact-ID retry and repeated failure,
  changed-standard new run IDs and recovery without duplicated criteria.
- Independent review_fork probes:4 passed (15.13s), covering same-run changes, operator
  basis changes, post-standard interruption and incomplete completion without pass.
- Expanded regression:120 passed,8 setup errors (167.44s). All8 share the Task017
  historical baseline fixture, which also needed its explicit legacy mode. This is
  the same intended default-change fixture adjustment, not weakening an assertion.
  Only that fixture was changed; focused import rerun recorded below.
- Task017 import rerun:9 passed (32.37s). Together with the unchanged120 passes
  above, all128 distinct selected regression cases pass; one case overlaps. No
  production code changed after the expanded run. `git diff --check` also passed.

## Final independent disposition

alignment_review inspected the focused corrections after the early review. It found
the previous findings addressed in code and no new blocking finding: empty inspection
versus historical state, pure author standards, unverified structural termination and
public recovery limitation. It checked the new tests but did not rerun them. Main
accepts that bounded disposition, subject to the final executed regressions below.
review_fork's four independently executed probes are separate evidence; its recovery
visibility P2 was corrected after the probes and is covered by Main's final suite.

Main's final disposition: the selected regressions now pass, and no independent
blocking finding remains for this mechanism increment. Implementation/offline
verification is complete. Do not promote a report-quality baseline or resume paid
trials on this basis; those remain distinct from this completed scope.

All test counts overlap and must not be summed as unique evidence. Tests use the actual
native graph with synthetic scripted models; they validate mechanics, not autonomous
strategy quality, standard adequacy, improved defect detection or engineering acceptance.
G1 remains open. Task029 trials remain paused and unpromoted; no legacy application or
data was changed, no knowledge graph was migrated, and no source/OCR run was initiated.
