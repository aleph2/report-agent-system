# Optional supervision plugins

The coordinator chooses a server-registered `supervision_plugin` on a new reviewer task.
Omitting it saves `null`: the native reviewer runs once without automatic reconciliation,
completion follow-up or supervision notice. Basic permissions, versions, immutable evidence
and review standards still apply. `list_supervision_plugins` returns available choices.

Existing task selection is immutable. Resume its owner without specifying a new selection.
Historical tasks without a selection field retain their original `task-checks-v1` policy.
A new policy applies to a new task, not a running invocation or archived evidence.

`task-checks-v1` retains declaration/read reconciliation. `task-checks-evidence-v2` also
requires `check_results` for assigned checks. Each result identifies the check position,
actual execution state, what the investigation found, indexes of supporting observations,
and remaining work when incomplete. These observations must be real task-local successful
receipts. An evidence link establishes provenance; it does not establish understanding,
comparison quality, factual truth or full commissioned coverage.

Both implementations reserve at most one completion follow-up for the same task identity.
They retain residual work and reasons. Node revision limits remain separate.
`outside_assignment_notes` retain genuinely external work without counting it as an
assigned omission. They never waive an assigned check. Historical unchecked fields remain
conservative; this change does not rewrite or reclassify archived assessments.

`read_review_obligation_coverage` optionally exposes independent requirements/criteria
alongside actual assignments for a snapshot. A mapped criterion is not proof every fact
was checked. The coordinator must carry the full commission into assignments and preserve
unassigned work; a targeted revised-defect check does not close other factual omissions.

Implement another `SupervisionPlugin` and register it in `supervision_plugins.PLUGINS` to
offer a later policy. The plugin runs at the existing native middleware boundary with the
already-bound task and native invocation. It cannot grant roles or ownership, replace the
reviewer's engineering judgment, or silently create a second agent loop. New runtime policy
still requires appropriate validation and model-run authorization.
