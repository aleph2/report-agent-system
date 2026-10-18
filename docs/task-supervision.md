# Delegated review supervision

This capability uses the existing native DeepAgents `task`, `DelegatedTask`,
`ReviewRecord` and observation receipts. It adds no agent, backlog, daemon or
second execution loop. The coordinator assigns outcomes; the reviewer decides
how to investigate and retains professional judgments.

For a new reviewer delegation supply `review_snapshot_ref` and
`review_requirements`. Each requirement names an exact target and criterion,
a stable `scope_id`, and `required_checks` labels. The reviewer uses that scope
ID and accounts for actually performed checks in `coverage.checked`. Multiple
requirements may be assessed in one invocation; there is no one-call-per-node rule.

Optional `required_read_refs` require actual whole-body observation of exact
ContentNode or SourceArtifact versions. Historical bodies may be requested for
a comparison without adding them to the current author's snapshot. A snapshot
inventory, unreturned source reference or partial body selection does not count
as that read. A read is still not proof of comparison or understanding. Export
and render requirements also bind their exact `artifact_refs`.

On return the native tool middleware reconciles applicable saved review items,
versions, scope IDs, check declarations and actual read receipts. Explicit
review corrections/reuse and changed sources are respected. It requests only
remaining requirements once through the same native reviewer task and owner.
The reservation is saved before that invocation. Failure, cancellation or an
unknown return cannot cause an automatic replay of that completion request.
Still-incomplete work and reasons stay visible in `read_task_supervision`, the
coordinator's subsequent context and saved execution decisions, independently
of its todos. Existing completed work can be reused. A resumed assignment cannot
silently narrow its saved requirements.

Execution completion is separate from correctness. `not_satisfied` remains a
defect; completed investigation with `undetermined` may retain a human decision.
Unperformed/blocked checking remains incomplete. The supervisor cannot discover
every omitted requirement, verify semantic coverage from labels, or prove an
agent's private reasoning. It does not override criteria or reviewer verdicts.

Dependent layout is rejected when prequeued in the same model response as a
review of its snapshot. The coordinator must receive the return and decide its
next action in another model turn. Required execution gaps on that snapshot
also prevent a new layout delegation. Independent snapshots are unaffected.
This does not itself prove content stability: substantive findings and authorized
revision limits still require coordinator judgment.

Report body creation/revision, including structure nodes, belongs to writer in
the current delegated-review runtime. The coordinator can maintain criteria and
relations and freeze producer-owned saved content for delivery without acquiring
content ownership. Original writer tasks resume with their existing identity.
Historical `native-rubric-v1` fixtures retain their compatibility behavior;
saved old objects/checkpoints are not migrated or restarted by this change.
Existing coordinator-owned content is not transferred to writer. Any later
authorized continuation must respect that ownership and the logical node's
existing revision count; creating a new version is not a count reset.

The local calibration cases in `docs/reviews/task-supervision-calibration.json`
preserve both successful and misleading outcomes with their evidence and limits.
Offline scripted-model tests verify the interface and native execution path.
They do not calibrate a real model's review depth or demonstrate learning,
cross-case reliability, full report coverage or production acceptance.
# 2026-10-09 scoped comparison extension

Task reconciliation now matches the existing target, criterion, scope ID and
assessment kind. `checked_requirement_indexes` identifies performed positions in
the immutable assignment; descriptive wording is not an identity. Old single-action
scopes retain their scoped completed declarations. Old multi-action records need
explicit matching labels or new indexed evidence; a broad sentence does not close
several obligations. Reusing a scope ID with changed checks does not reuse completion.

Access accounting uses the originating task's actual body-read observations available
when its ReviewRecord was submitted. Later reads, other actors, failed reads, partial
selections and wrong versions do not establish that earlier access. Old records have
no temporal boundary and conservatively use the union of their batch's cited receipts.
Per-item support citations remain separate; access is never semantic verification.

`review_execution_mode: bounded-tool-v1` is an opt-in experiment. It reuses the
one-shot evidence-analysis runner and native tool registration. The reviewer agent
organizes exploration and calls `perform_assigned_review`; the tool loads original
assignment/criteria and exact target bodies, adds selected supporting material, and
persists the model's scoped judgments under the caller's existing task authority.
The organizer cannot replace those judgments through submit/correction tools.
Missing/partial work remains explicit. No additional agent, backlog, learning,
whole-report restart, per-node call limit or hidden retry loop is introduced.

The same saved task may contain several related scopes in one call. No new user
prompt replaces the original assignment. Material selection and model judgment can
still be wrong; deterministic protocol tests and invocation counts do not demonstrate
review quality. The isolated comparison and original model outputs are retained in
`.runs/task-supervision-tool-comparison-20261009`.

