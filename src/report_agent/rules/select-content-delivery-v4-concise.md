Save the selected exact Snapshot, Word export and optional bound XLSX companion as a draft;
selection neither approves it nor triggers review. review_basis_assignment_ref names a
saved task's complete immutable commission basis. review_assignment_refs lists compatible
Reviewer tasks adopted for the current Snapshot/artifacts and basis. Find saved basis/refs
and task_ref using read_state_path supplied in your current packet with read_decision_state.

The basis may originate at an earlier Snapshot, but adopted tasks must match the current
Snapshot and basis. A nonempty adoption list requires a basis; an empty list adopts no
positive conclusions. Omit the basis and keep that list empty for an unassessed draft;
missing standards remain unknown. Old defects and stronger unfinished work stay visible.
ending_reason is metadata, not semantic coverage or engineering acceptance.
