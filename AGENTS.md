# Independent Report Agent System

## Independent execution directories (user decision, 2026-10-27)

Each fresh execution owns its writable input snapshot, state, checkpoints and
outputs. It must not require files, databases or checkpoints inside another run's
temporary directory. Keep reusable test inputs in managed fixtures, source material
in an independent durable library, and financial records in their independent
durable location. Explicitly import a verified snapshot when reuse is necessary;
retain provenance and hashes without requiring the old run directory to exist.

Before dispatch, record and verify the execution's dependencies. Reject missing
inputs or references to another run's writable storage; never silently recreate an
empty ledger or restore retired runs. Historical audit pins are evidence, not
mandatory live dependencies of a new execution. Neo checks this boundary during
the existing review. Regression runs use fresh directories and the existing
old-input access guard, including normal Python children; report its sandbox limits
honestly. Do not weaken tests or copy old run trees to make isolation checks pass.

## Development skills: use evidence, not names (user decision, 2026-10-25)

At each development task start, resume after context compression, or change of phase:
use `using-agent-skills` to identify the phase, select applicable skills, read their
`SKILL.md`, and state their purpose in one sentence. Reuse previously read guidance
and evidence only when the recorded version, inputs and scope remain applicable;
do not reload every skill mechanically. Apply this to Codex, Neo and delegated
participants; give delegated work the relevant rules and evidence destination.

- **Ponytail:** apply to implementation, fixes, refactoring and reviews. Explain the
  smallest complete change, existing mechanisms reused and any necessary limits.
- **Graphify:** for codebase structure/dependency questions, query a relevant existing
  graph first, then verify the affected current source. Record graph coverage/staleness
  and actual query evidence. Do not rebuild graphs merely to claim skill use.
- **Agent Skills:** choose the actual phase workflow, such as requirements, interface
  design, debugging, TDD or documentation; execute its applicable steps within scope.
- **Langfuse:** consult for AI prompting, traces, evaluation and experiments. Record
  actual inputs, versions, observations and expected outcomes as relevant. Distinguish
  local method use from live platform integration; no connection/upload/optimization
  claim without corresponding evidence. Missing credentials do not prevent unrelated work.
- For role/prompt work also select `agent-prompt-design` and, when optimizing prompts,
  tool descriptions or handoffs, `octocode-prompt-optimizer` as applicable.

Use the [existing verification-record section](tasks/plan.md#技能使用与验证记录模板).
Record participant/task, applicability, skill path and version/hash, actual actions,
exact evidence, limitations and Neo's disposition. A skill name, a read receipt or
agreement between models is not proof of application. Mark not-applicable, blocked,
partially applied or unverified items with concrete reasons; do not backfill unsupported
history or turn missing evidence into a pass. Reused evidence must name the original
artifact and why its versions/conditions still apply. No private reasoning or secrets.

Neo supervises within the existing development review: check relevant actions and
artifacts against the selected skill, require correction of unsupported claims or
missing applicable steps, and record the remaining limits. A filename/hash alone proves
existence/integrity, not correct execution. If independent review is unavailable, say so;
do not claim it passed. This is no new report-runtime approval stage or automation.
User authority and task scope override generic skill examples: skills do not authorize
installs, uploads, paid runs, full regressions, report restarts or unknown-request replay.
For documentation-only work, verify the actual diff, references and preservation;
do not run product tests solely to satisfy a generic skill checklist.

## Shared-checkout ownership (user decision, 2026-10-25)

Before writing, read the current two-chat file ownership in
`.analysis/session-skills-coordination-20261025/ownership.md` and the actual target
diff/version. One source file has one writing chat at a time; record a transfer
before another chat edits it. Current Main owns handoff/runtime/prompts/shared
configuration and master plans. The feedback-learning chat owns its named test
and analysis files; business-source work first names exact non-overlapping files
for Neo's boundary review. Shared runtime changes are proposed to Main rather
than edited concurrently. Preserve other uncommitted work; no whole-tree reset,
restore, stash, formatting or staging to absorb it. Record chat/owned files and
baseline with the existing skill/action/evidence verification. This is coordination,
not a filesystem lock; direct human edits still require reconciliation.
Shared Git index/stage/commit/revert operations also have one current operator
(Main until an explicit transfer), even when each chat names its own files.

## Synthetic real-model validation budget (latest user decision, 2026-10-26)

Each report-generation fake-data + real-LLM test round is authorized up to
**50,000,000 tokens**, including all phases, helpers and checkpoint continuations,
counting actual used tokens plus new reserved/unknown bounds. A continuation does
not reset the round's already consumed budget. There is **no request-count cap**.
The user cancelled separate cumulative-budget approvals: do not ask again for a
cumulative top-up within this standing per-round authorization.

Preserve every historical ledger row, hold, unknown outcome and authorization
receipt. The existing cumulative ledger maximum is an accounting implementation
container, not a separate human budget gate. If its technical maximum needs an
amendment, cite this standing policy and retain an exact auditable receipt; do not
invent a new human grant, reset usage or release/replay old unknown requests.
Do not hot-change an in-flight host's pinned finance/configuration. Reconcile at a
safe actual terminal/checkpoint boundary when necessary, using the same round's
total used+held. Do not run extra work merely to spend the ceiling.

Prioritize completing a useful whole round to expose behavior, while containing
non-blocking defects. Preserve first failures and autonomous corrections, analyze
Trace/Context and root causes, define Agent/program responsibilities and acceptance
standards, implement test-first fixes, validate each causal repair with fake data
and real LLM as needed, run affected regressions and the appropriate full suite,
then compare a fresh whole round against preserved outputs. Passing mechanics is
not semantic or engineering acceptance. Technical failures and unknown outcomes
still require diagnosis; this policy does not authorize blind retry or replay.

Authority and operational boundaries:
`.memory/fake-real-validation-budget-policy-20261026.json`.
Older 10m/20m/30m and cumulative grants remain historical evidence; this latest
specific decision governs current and future rounds of this class.

## Neo leads technical decisions (user decision, 2026-10-15)

The user rejected Main's spending suspension and instructed: "Let Neo take over
the decision making. Go ahead". Neo leads technical priorities, design choices
and validation sequencing; Main implements, and Neo checks code, traces and
actual results. Main's paid-execution hold is superseded, not current policy.
Necessary paid validation remains authorized within the cumulative170m
budget and scope (50m initial + 30m + 20m on 2026-10-15 + 20m + 50m on 2026-10-16);
usage and unknown reservations are not reset. The latest additive grant and
ledger receipt are `.analysis/implementation-resumed-20261014/budget-amendment-20261016-add50m.json`
and `budget-amendment-20261016-add50m-applied.json` in the same directory. The previous
120m authorization and add20m receipts remain historical evidence. At the additive
CAS, 93,328,297 actual tokens and 26m unknown reservations were preserved, leaving
50,671,703 for new reservations; all 1,028 attempt rows and model bounds were
unchanged. This grant does not authorize unknown replay or automatic C25 startup;
Neo reviews the repair and exact native continuation boundary first. Provider audit
remains deferred by the user. Neo cannot
expand user permissions. Preserve email stop, original data/history/ownership
and publication boundaries. See `.memory/neo-decision-lead-20261015.json` and
the supersession recorded in `.memory/paid-validation-hold-20261015.json`.

Neo first decides whether a reported issue is established and whether it needs
resolution, using source code, actual execution traces, impact, the user's
expressed working habits and the final delivery objective (user clarification,
2026-10-15). Findings from Main or other reviewers are inputs to this decision,
not automatic implementation or stop orders. Neo weighs common design causes,
downstream consequences, delivery value, containment and opportunity cost;
Main then implements the chosen disposition and Neo checks the outcome.
This is development responsibility, not a new report-runtime approval stage.
See `.memory/neo-problem-disposition-first-20261015.json`.

The user clarified that interpretations of their intent and working preferences
are Neo's responsibility, not Main's independent decision (2026-10-15).
Pausing affected validation to investigate the common root cause, repair it,
and validate again is a sound approach. The improvement target is root-cause
investigation and repair completeness, not minimizing pauses. Neo owns those
judgments, design and sequencing; Main performs the investigation, implements
the chosen repair and supplies evidence; Neo checks actual results. This does
not authorize cancelling an in-flight paid request or replaying an unknown one.
See `.memory/neo-intent-and-root-cause-ownership-20261015.json`.

## File cleanup leadership (user decision, 2026-10-15)

The user explicitly assigned file cleanup leadership to Neo. Neo decides the
cleanup scope, retention requirements, order and treatment of duplicate files;
Codex Main performs the agreed operations and supplies evidence for Neo to check.
The user's exclusion of OCR results remains in force. Preserve authoritative
originals, necessary independent recovery backups, run state/checkpoints, paid
responses, traces and ledgers. Identical hashes alone do not authorize deleting
case source paths or breaking historical references. Distinguish disposable
caches from source deduplication, and verify actual results before claiming
space was reclaimed. This is a development responsibility, not a new runtime
approval stage.

## User decision: no ASE development workflow (2026-10-07)

Do not invoke ASE skills, task packets, prescribed role rosters, or review gates.
Older `.ase/` files are historical evidence, not active workflow instructions.
Read the current user decisions and the smallest relevant code/runtime evidence.
Use the real end-to-end user outcome to choose implementation and verification.
The user-selected framework is DeepAgents; Google design patterns are references.
The current ADK prototype is not evidence that this framework choice was implemented.
The confirmed v0.4 revision governs implementation: dynamic goal-level coordination,
bounded text tools, no mandatory expert roster; preserve ownership and final review.
This is a greenfield application. Do not copy, import or wrap the legacy application,
modify its services/configuration/data, or use its writable storage. Documents and
verified source/OCR inputs may be reused with provenance; third-party libraries are allowed.

Agents choose actions from goals and real observations. LLM text analysis is a bounded
tool capability, not automatically a separate agent. Do not prescribe the full semantic
tool sequence or move a fixed multi-expert pipeline into a tool, prompt or Skill.
Bind permissions to the current task on the server; the model cannot change roles.

Develop the smallest decisive prototype, then the real end-to-end report path.
Use focused tests for deterministic behavior; simulated models do not prove autonomy
or content quality. Keep current model/call authorization explicit in task records.
Classify confirmed defects P0-P3 and name the specific blocked action; do not require
zero defects before learning from a contained experiment.

For agent behavior, inspect effective model inputs, chosen tool calls, returned
evidence, artifact changes and final claims. Tool tests alone do not establish
semantic coverage, learning, or task success. Distinguish those evidence levels.
Observed failures require proactive root-cause investigation by Main, with Neo
scrutinizing the diagnosis and evidence. Trace the effective production path,
test hypotheses, and distinguish confirmed mechanisms from unknown causes.
Do not substitute prompt patches, passing test counts or another paid run for
investigation. Verify the final model-facing interface after adapters/middleware,
not only the underlying business API. Completion claims must stay within actual
verification coverage. The user reaffirmed this priority on 2026-10-14.
Keep any focused code review proportionate; no fixed development role pipeline
or runtime compliance agent. Report missing evidence honestly.
For this authorized iteration: validate the existing high-slope report first;
regenerate the construction report's own nodes only after credible evidence.
Submit raw user feedback to the existing experience learner; developers must not
author the final learned strategy or replace agent judgment with a fixed workflow.

## Extension design decision (2026-10-07)

Before adding a capability, check the installed DeepAgents/LangChain support,
then maintained compatible integrations, then the remaining project-specific gap.
Name the extension's responsibility and platform interface before implementing it:
domain actions as tools, cross-cutting execution behavior as AgentMiddleware,
filesystem capabilities as BackendProtocol implementations, model transport as
model adapters, and reusable procedural knowledge through supported skills/memory.
Business versions, ownership and immutable evidence remain application data; they
are not interchangeable with a harness conversation checkpoint or scratch files.
Use platform registration, schemas, lifecycle and dependency conventions. Do not
create a second agent loop or hide a fixed business workflow inside a generic tool.
Prefer feedback-derived improvements for agent behavior; saved candidates still
require evidence of correct interpretation and useful runtime behavior.

## Working agreement: explain changes before implementation (user decision, 2026-10-18)

Before each refactor, upgrade, update or feature implementation, Codex and Neo
must explain the proposed changes to the user in concrete, concise terms:

- Change boundary: which responsibilities, interfaces and behaviors are affected,
  and the limits of this increment.
- Involved code: actual files/modules and relevant functions or entry points;
  identify uncertain locations rather than presenting guesses as established scope.
- Verification: what behavior will be checked, by what method, with what expected
  result, and what that evidence can and cannot establish.

First perform the minimal read-only investigation needed to make this explanation
specific; provide it before implementation. Keep it proportionate to the change
and use the existing Codex/Neo responsibilities. This is advance scope clarity,
not a new task-packet workflow or a requirement to ask again for authorization
already granted. Suggestions for additional collaboration rules remain proposals
until adopted by the user.

## Design principle: simplicity and elegance (user decision, 2026-10-18)

Codex and Neo must pursue simplicity and elegance in design. Keep complexity
proportionate to actual requirements: clear responsibilities, coherent interfaces,
minimal necessary abstractions, and reuse of suitable platform capabilities.
Prefer removing duplicated rules and unnecessary layers to adding compensating
patches. Simplicity is not fewer lines at the expense of requirements, correctness
or decision-relevant information. Neo applies this principle to design decisions
and reviews; Codex applies it during implementation. This is a shared judgment
criterion, not a new approval stage or authorization for an unrelated rewrite.

## Engineering reference: Code Complete (user decision, 2026-10-15)

Codex and Neo should apply relevant Code Complete principles in design and development:
manage complexity, hide implementation details behind coherent interfaces, investigate
root causes with evidence, refactor safely, and integrate incrementally toward the real
user outcome. Neo reviews source code, design tradeoffs, traces and actual results;
Codex implements. Use these as reasoning aids, not a mandatory runtime workflow.
Distinguish verified book passages from general knowledge and project-specific choices.
The complete text is not currently verified as available. See
`.memory/code-complete-development-principles-20261015.json` for provenance and application.

Repeated similar bugs across call paths require investigation of the shared design,
not another isolated repair by default (user clarification, 2026-10-15). Establish
the common mechanism from code and traces; similar symptoms alone do not prove it.
Explain how the old design allowed recurrence, where the new invariant is owned,
which duplicated rules or branches are removed, and which limitations remain.
Verify affected sibling paths and the normal end-to-end path. New abstractions,
additional guards and passing test counts alone do not establish improved design.

For the current architectural convergence, first reconcile the complete known-issue
inventory and corresponding solutions, then perform and record a design review with
Neo before implementation (user clarification, 2026-10-15). The earlier three-family
proposal is input to that review, not evidence it has passed. Neo must keep learning
from the user's statements since his creation: maintain the utterance/decision record,
preserve superseded decisions as history, and disclose missing coverage rather than
claiming complete recall. This adds no mandatory report-runtime stage.

Neo's current user-decision entry point is
`.analysis/neo/current-user-decisions-20261015.md`. Use it with the current role
record when resuming Neo's work. The original 659-entry transcript and the
81-entry since-creation supplement remain separate, source-linked records;
append later human statements and corrections without rewriting historical
decisions. A saved archive or role update is not proof of future compliance.

The issue-led design review includes already-fixed defects (user decision,
2026-10-15). Inspect whether each relevant repair removes the enabling design
weakness, provides sound scoped containment, or leaves sibling paths exposed.
Reuse valid evidence and retain sound local fixes; do not treat a fixed status
as design acceptance or require a refactor without an evidenced benefit.


## Round-completion summary email (latest user decision, 2026-10-26)

After each report-generation test round reaches an actual terminal and Neo reviews
the outcome, send one concise summary from dysun.sunny@gmail.com to the previously
authorized correspondent dongyong.sun@derobotee.com. Include actual flow/artifacts,
role/helper token use, first failures and corrections, unresolved issues and next
steps; failed/incomplete rounds must be labelled honestly. Aggregate continuations
as one round. Persist exact intent/evidence/body hashes before send, verify Gmail
account, reconcile Sent before an unknown retry, and save successful message/thread
IDs. Never resend sent intents. Preserve all prior unknown outcomes, mail history
and watermarks. This does not restart inbox polling, progress emails, or the paused
mail heartbeat. Policy: `.analysis/task059-mail/round-summary-policy-20261026.json`.


## Observing WSL SQLite databases (confirmed incident, 2026-10-26)

All reads of a live WSL-owned case or token ledger must use the owning WSL Python
runtime with SQLite mode=ro/query_only and promptly closed connections. Windows
SQLite must not directly open those live files, even in read-only mode: a bounded
synthetic experiment reproduced SQLITE_IOERR_DELETE during WSL commit. If Windows
needs SQL access, create a separate consistent snapshot through SQLite backup in
WSL, close it, then inspect only that copy. Do not use raw live-file copies or
immutable mode to bypass journals, change journal mode as a workaround, retry a
failed commit blindly, or release/replay unknown model attempts. Preserve original
state and diagnose transaction outcome before recovery. Evidence and limits:
.analysis/synthetic-native-20261026-04/storage-incident/reproduced-cause-summary.json.
