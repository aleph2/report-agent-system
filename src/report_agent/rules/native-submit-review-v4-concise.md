Save genuine scoped findings against the assigned Snapshot. Copy each item's scope_id
from saved review_requirements; use only that task's assigned criteria_refs, local
required_checks indexes and observation indexes into your own recorded observations. A projected Criterion's
whole verbatim outcome is check0. outside_assignment_notes belongs to review.items[],
not the batch; keep genuinely out-of-scope limits there. Preserve defects, uncertainty and unperformed/blocked
checks with reasons; unexecuted work has a null verdict. Reading or saving is not correctness.

review.snapshot_ref anchors the assigned Snapshot; review.target_ref and each item's
target_ref select the assigned Snapshot/member. scope describes the actual assessed
extent at batch and item level; scope_id is its saved task identity, not that description.
criteria_refs contains assigned criteria; dependency_refs records exact batch dependencies,
with optional item dependency_refs overriding that batch set for the item's reuse.
artifact_refs contains only exact ExportArtifact/RenderArtifact type/id/version refs.
For each export/render item use its matched requirement's complete artifact_refs set;
artifact_check_scopes defines check extent, not a smaller item declaration.
Required artifact extent stays in the saved assignment's artifact_check_scopes; observations
must support what you actually checked. Do not add extent fields to artifact_refs.
Excel export fidelity is supported; Excel layout/render is outside its current capability.
delivery_export_ref is a top-level tool argument, not a field inside review; it binds
provenance, not acceptance. coverage_accounting targets only the exact ContentNode and
Requirement entries in the supplied coverage inventory; other materials belong in their
applicable dependency/observation fields. Use your own observation receipt IDs for
observations, not write-operation IDs or public-return recovery references.
review.scope and review.dependency_refs are required; dependency_refs may be empty when
there are no exact batch dependencies. Batch/item scope is a string.
Do not add any fields absent from the current schema, including extent/body_extent or
extra item, coverage or artifact-ref fields;
required extents come from saved content_check_scopes/artifact_check_scopes.
Only successful observations support a non-null verdict or completed check; failed/blocked
reads may be recorded. Completed content checks need every body ref in saved content_check_scopes; when a
missing_body_refs diagnostic is returned, obtain those observations before resubmitting.
A finding uses an item's local required_checks index, an existing CheckResult and a
nonempty subset of that check's observation indexes. delivery_checks[].artifact_refs use only assigned refs of the same
item kind; a new RenderArtifact cannot substitute for an assigned artifact.
Earlier own actor/task receipts remain recoverable; applicability still depends on their
actual version/extent. Foreign receipts are rejected. coverage_accounting applies only
when assigned an inventory; a Requirement cannot be not_applicable.
Returns the saved ReviewRecord ref; does not edit content, start authorship or approve delivery.
