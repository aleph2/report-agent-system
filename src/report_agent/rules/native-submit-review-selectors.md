Save your actual scoped findings and check results against the exact assigned
Snapshot. For each item choose assigned_scope_index from the current task's shown scope map.
The program binds target_ref, criterion_ref, scope_id and assessment_kind from that
immutable assignment; do not supply those four per-item fields. Free scope prose
cannot replace the selected identity.
assigned_scope_index is the zero-based position in this task's full saved
review_requirements, not a preview-page, review-item or required_checks position.
Check indexes belong to required_checks of the selected scope; observation_indexes
belong to that item's observations. Observation.receipt_id is the saved receipt ID,
not an observation index.
 criteria_refs names only standards actually
assigned to this task, not every standard in the full commission basis. Use the
local required_checks indexes, your own saved observation receipt IDs and item-local observation indexes.
For a mechanically projected Criterion outcome the whole verbatim outcome is check0.
Preserve completed defects, uncertainty, unperformed/blocked work and its reasons.
An item not started has a null verdict; reading or saving alone does not prove correctness.
Content targets are the exact assigned Snapshot/member. Each export/render item
repeats its matched requirement's complete artifact_refs set; artifact_check_scopes
defines individual check extent. outside_assignment_notes belongs to review.items[],
not the batch. Excel export fidelity can be checked; Excel layout/render is outside the existing capability. Optional
delivery_export_ref binds provenance only. The tool saves a ReviewRecord and returns
its ref; it neither edits report content, triggers author work nor approves delivery.

Only the four per-item identity fields are program-bound. Batch review.target_ref,
review.snapshot_ref, review.criteria_refs, review.scope and review.dependency_refs
remain required. Batch target and snapshot use exact assigned refs; scope describes
what was actually assessed, and dependency_refs may be empty when appropriate.
delivery_export_ref is a top-level tool argument, not a field inside review.

Use the current actor's saved receipt_id values in observations; CheckResult uses
local observation_indexes, execution_state, result and remaining, not a verdict field.
assigned_scope_index applies only to submit_review. confirm_review_reuse still uses
new_scope_id from the saved assignment; its ID-based interface is unchanged.
