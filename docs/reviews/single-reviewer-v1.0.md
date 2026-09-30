# Single reviewer implementation v1.0

2026-09-30. Task060. Replaces the duplicated hierarchical final grading entrypoint
for new runs; historical traces are not migrated or relabeled.

The coordinator owns standards, selects work and delivery versions, and chooses
continuation/wait/handoff/termination. A decision is durable metadata, not a routing
switch. Reviewer is delegated through native DeepAgents task with server-bound
ownership. It explicitly submits local or final review using one tool. Final
submission binds snapshot and export and atomically writes the record and pointer;
replay returns the same receipt. Only reviewer may register final review.

Version, source, receipt, coverage and negative-finding projection remain unchanged.
Incomplete or absent final review cannot become a positive final assessment. An
export/render mistakenly used as an item target now receives its exact field path
and an artifact_refs hint. Metadata context exposes complete criteria obligations
and object inventory, without the old transcript truncation or GraderResponse
contract. Reading metadata is not independent observation.

Runtime defaults to delegated-reviewer-v1; native-rubric-v1 is explicit historical
compatibility, never concurrently active with the new final-review path. Old rubric
checkpoints cannot silently enter the new graph. Model role identities are bound
without secrets and checked on recovery. Ordinary transient delegated API failure
returns execution feedback to the coordinator; cancellations/programming failures
remain execution failures. No automatic semantic stop or mandatory retry loop.

Configuration reads HIGHWAY_MODEL_DEEPSEEK_* for official DeepSeek and
HIGHWAY_MODEL_* for GLM-5.3. Writer uses GLM; coordinator/reviewer/text tool use
DeepSeek. Each role gets a complete endpoint/model/credential bundle. The trial CLI
uses --mixed-models for this combination; role switching requires a fresh project.

Independent design/diff review: /root/single_reviewer_alignment. Two P2 findings
(stale role overrides and silent recovery switching) were addressed in code and
regression tests. Final review follow-up and runtime evidence are tracked in the
verification record; this design document does not establish model quality.
