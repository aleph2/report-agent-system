# Development rules

Use the smallest complete change and existing DeepAgents mechanisms. Do not add a
second agent loop, hidden fixed business workflow, memory engine or broad permissions.
Agents choose semantic work; the program owns identities, version binding, permissions,
immutable storage and deterministic validation. Tools do not expand caller ownership.

Before work, select relevant installed skills and read their instructions. Use Ponytail
for scoped implementation/review; Graphify's existing graph for navigation with current
source verification; Agent Skills for the actual requirements/debugging/TDD/review phase;
Langfuse methods for AI traces/evaluation, stating whether platform integration is real.
Use agent-prompt-design and octocode-prompt-optimizer for role/tool/handoff prompt changes.
A skill name alone is not execution evidence: record actions, artifacts and limitations.

Codex implements; Neo independently reviews actual scope, source, model inputs and results.
Prompt changes also receive DeepSeek review when that development setup is available.
Distinguish independent review performed from a proposed or unavailable review.

Preserve first failures, autonomous corrections and unknown outcomes. Diagnose before retry;
never reset financial history, replay unknown requests or weaken tests to obtain green.
Write a reproducing test, repair the root cause, verify affected paths, then run the
appropriate complete regression against frozen sources. Real-model autonomous/semantic
behavior requires separately authorized fake-data validation, not scripted business dispatch.
Provided/read/planned/saved/completed are different from correctness or engineering approval.

Keep credentials, customer sources, operational history and private reasoning archives local.
Read RELEASE_VALIDATION.md before claiming historical tests reproduce from a fresh clone.
Publication uses a reviewed, sanitized snapshot; it must not add private local history.

## Independent execution storage

Each fresh execution owns its input snapshot, state, checkpoints and outputs.
Do not depend on another execution's temporary or writable directory. Keep
managed fixtures and explicitly shared durable libraries/financial records
outside run containers. Reuse verified snapshots with provenance and hashes,
not live links to old runs. Verify dependencies before dispatch; fail on missing
inputs instead of recreating an empty ledger or retired run. Regression uses
fresh directories and records forbidden old-input accesses. Python guard
coverage must not be described as an operating-system-wide sandbox.
