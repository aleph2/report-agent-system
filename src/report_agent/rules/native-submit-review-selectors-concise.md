Save genuine scoped findings against the assigned Snapshot. For each item choose assigned_scope_index from the current task's shown scope map;
the program binds target_ref, criterion_ref, scope_id and assessment_kind from that
immutable assignment. Do not supply those four per-item fields. Use only the task's
assigned criteria_refs, local
required_checks indexes and observation indexes into your own recorded observations. A projected Criterion's
whole verbatim outcome is check0. outside_assignment_notes belongs to review.items[],
not the batch; keep genuinely out-of-scope limits there. Preserve defects, uncertainty and unperformed/blocked
checks with reasons; an item not started has a null verdict. Reading or saving is not correctness.

assigned_scope_index is the zero-based position in this task's full saved
review_requirements, not a preview-page, review-item or required_checks position.
Check indexes belong to required_checks of the selected scope; observation_indexes
belong to that item's observations. Observation.receipt_id is the saved receipt ID,
not an observation index.

review.snapshot_ref anchors the assigned Snapshot; review.target_ref selects the assigned Snapshot/member;
item targets are bound from the selected assigned scope. scope describes the actual assessed
extent at batch and item level; the assigned scope index selects its saved identity, not that description.
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

Use the current actor's saved receipt_id values in observations; CheckResult uses
local observation_indexes, execution_state, result and remaining, not a verdict field.
assigned_scope_index applies only to submit_review. confirm_review_reuse still uses
new_scope_id from the saved assignment; its ID-based interface is unchanged.
