Save the exact Snapshot and Word export selected for delivery, optionally with its
bound XLSX companion. This is a draft selection, not an approval or a review trigger.
For reviewed-evidence accounting, review_basis_assignment_ref names a saved task's
complete immutable commission basis. review_assignment_refs explicitly lists the
compatible reviewer tasks adopted for this selected Snapshot and artifacts; their
saved refs/basis digest are available from read_decision_state at
['review_tasks','tasks',index,'review_commission_basis'] and the adjacent task_ref.
The basis may come from an earlier Snapshot; adopted tasks must match the current
Snapshot and basis. An empty task list adopts no positive conclusions. Omit the
basis and leave the list empty to retain an unassessed draft; missing standards
remain unknown. A nonempty adoption list requires a basis. Old defects and stronger
unfinished work remain separately visible. Selection never establishes full
semantic coverage or engineering acceptance. ending_reason is metadata only.
