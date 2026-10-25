# Architecture

DeepAgents supplies the native agent loop, delegation, middleware and checkpoint interfaces.
Application modules extend these interfaces rather than implementing a second agent loop.

## Responsibilities

- Co chooses task goals, deliverables, applicable standards, scope and continuation from
  real observations. It coordinates rather than repeating authorship or substantive review.
- Writer creates and revises owned content, preserves qualifications and provenance, and
  returns the selected saved output. Authorship does not grant self-acceptance.
- Reviewer plans useful acceptance work, checks exact deliverables against their standards
  and evidence, and saves genuine findings, uncertainty and remaining work. It does not
  rewrite upstream content or turn access receipts into correctness.
- Optional Layout improves presentation of an authorized immutable snapshot. Changed
  artifact presentation has no automatically inherited artifact review.
- The program binds versions and ownership at delegation, validates deterministic contracts,
  calculates with tools, stores immutable records/receipts and provides precise feedback.

## Data and context

SQLite-backed application records distinguish original requirements, source/evidence objects,
content, snapshots, tasks, review records and exported/rendered artifacts. Conversation
checkpoints and scratch files are not substitutes for these business versions.

Static role prompts, tool/parameter descriptions and their final model-facing assembly have
source provenance. Task descriptions carry dynamic goals and scope; a subagent's system role
is separate. Context middleware retains exact recoverable application facts. The selected
complete Reviewer-materials profile presents each bound business object version once, while
actor-owned receipt metadata retains exact identities with bounded, explicit recovery paths.
Providing materials or a plan is not evidence of completed review.

## Failures and validation

Rejected calls retain their first diagnostic and known outcome. Unknown requests are not
blindly replayed. Repetition feedback is an observation, not proof of semantic non-progress
or a universal termination mechanism. Correct authorization/evidence refusals stay enforced.

Deterministic contracts are checked offline. Autonomous handoff and semantic behavior require
separate fake-data/real-model observations. Runtime completion, saved judgments, artifact
quality and engineering acceptance remain different claims. See the release validation notes.
