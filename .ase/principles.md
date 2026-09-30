# Confirmed Development Principles

2026-09-27. Carried into this independent project from the user's confirmed discussion,
especially C25 (agent/tool separation) and D08 (greenfield implementation).

The user approved implementing the v0.4 consensus revision on 2026-09-27. Role
responsibilities are not a fixed agent roster or mandatory semantic pipeline.
Coordination is a task responsibility, not necessarily a permanent planning agent.
Purpose understanding remains a prerequisite for a grounded report plan, not a
mandatory separate agent invocation. Final report review and upstream read-only
boundaries remain. Agent count and storage choice are not predetermined by this
approval. The completed synthetic-trial permission does not cover new paid trials.

- Deliver useful, traceable compilations of existing materials with bounded checking.
  Do not turn compilation into new engineering design, calculation or sign-off.
- Understand the user's scope and document purposes before report planning. This is
  an outcome prerequisite, not a hard-coded sequence of five agents.
- Agents observe, plan, choose LLM or code tools and adapt to real feedback. Text
  analysis tools handle supplied input and return results, provenance and limitations.
  They neither grant authority nor recursively manage other agents.
- Keep one responsible producer for each shared result. Downstream writing/review
  reads upstream results and requests corrections; it cannot overwrite them.
- Source contradictions and actual missing material go to humans. Parsing, retrieval
  and execution failures are system problems, not user missing-data problems.
  The default continue/wait policy for source issues is still undecided.
- Graph is a retrieval mechanism, not an end in itself. Preserve source evidence,
  derived summaries and versions separately. Do not require IDs for every word.
- Code handles IDs, committed relationships, versions, permissions, storage and
  reliable execution. Semantic identity, applicability and evidence support remain
  model/expert judgments. Do not duplicate calculable mappings in model outputs.
- Reuse valid source/OCR inputs and own committed results. Mark actual use separately
  from new requests. Changes can affect newly relevant tasks, not only old consumers.
- Persist useful work and operation receipts. Unknown write outcomes require checking
  receipts before replay. Safe receipt recovery is not an unproductive reasoning loop.
- Share transport handling and distinguish transient failures from permissions/invalid
  input. No blind paid retries. Record usage; no hidden cumulative token/call quota.
  Keep justified technical limits and explicit uncertainty; no silent truncation.
- Make progress, failures and recovery visible. Logs are secondary; no fabricated ETA.
  A saved draft is not a reviewed report, accepted POC or engineering sign-off.
- Serial execution first. No mobile UI, user Skill editor, plugin marketplace,
  self-evolution or distributed orchestration in the initial scope.
- Use an independent repository, dependency environment, entry points and writable
  data. Do not migrate/copy/import legacy business code or task/graph state. Legacy
  application and data stay unchanged. Deployment/replacement requires its own scope.
- Review effective prompts, code, tool internals and real traces, not role names.
  Design consistency, offline tests and real model acceptance are different evidence.

Original discussion records remain in the neighboring legacy project's `.ase/` as
historical evidence only. Its old task-specific paid/deployment authorizations do not
automatically authorize this application's trials.

## Requirement-derived acceptance responsibility (2026-09-29)

User confirmed that the coordinator owns acceptance-standard creation/maintenance
as part of requirement and document-purpose understanding. Define outcomes before
report production; author and acceptance agent share the exact version. The author
owns the report; the acceptance agent chooses and adapts the verification strategy
and tools and owns the evidence-backed assessment. Both may request standard
corrections; neither may overwrite upstream standards or weaken them to fit a draft.
Source conflicts and real requirement choices retain human authority. Ordinary
requirement clarification is not a new approval ceremony. Every standard needs an
outcome with evidence/limits; coverage does not prescribe page scans or tool order.
Distinguish satisfied, not_satisfied and undetermined, and usable staged delivery
from all-standard satisfaction. See [design and implementation limits](030-acceptance-design.md).

## Quality feedback as the delivery design core (2026-09-30)

User requests full adoption of the document-quality discussion and identifies
automatic review feedback as the core mechanism for improving delivery without
requiring humans to label every correction. See the
[updated design](054-evidence-centered-quality-design.md) and
[discussion coverage](054-discussion-coverage.md). These are design requirements,
not claims that the new capabilities or quality gains have been implemented.

Generate feedback from requirements, original evidence, computations, rendering,
cross-document relationships and actual correction outcomes. Keep it located,
versioned, actionable and verifiable; model agreement is not ground truth.
Inspect both stated claims and required-but-missing content. Authors maintain
their supporting records; reviewers verify them and may find unlisted issues.
Separate actual adopted sources from later supporting evidence, semantic claims
from Word positions, and assessment outcomes from execution/coverage states.

Preserve agent strategy choice, upstream ownership, native framework execution,
human-reserved decisions and independent project storage. No mandatory reviewer
roster, majority-vote acceptance, private-reasoning capture or new knowledge graph
is required. Recheck affected content after corrections, protect correct content,
and distinguish completed acceptance from unresolved or interrupted work.
Assess final defects, false findings, correction damage, coverage and human
calibration cost. Stored feedback is not parameter learning; training remains
a later option requiring trustworthy labels and held-out evaluation. Do not
reintroduce cumulative token/call quotas through stopping or cost comparisons.

Selective decisions are central: automatic definitive assessments require evidence
for the current case and an empirically supported capability scope. Record unresolved
causes, target versions, evidence and impact. Creating a handoff does not require
an assignee, next action or resumption condition; these may be added later.
Handoff state is useful feedback for relevant authorized agents, without changing
the existing assessment or automatically triggering their actions.
Retrieval, computation, better observation or another validated capability may resolve
them before human involvement. Out-of-scope exploratory answers do not establish
reliable acceptance. Measure both residual defect risk and automatic coverage;
neither universal abstention nor unsupported passes count as successful delivery.

## Versioned content and hierarchical review (2026-09-30, later discussion)

The [current architecture](../ARCHITECTURE.md) organizes versioned content objects
as a tree with separate cross-node evidence, dependency and location relations.
Documents are exported from immutable content snapshots. Reviews bind exact
content, criteria and dependency versions; changed relations can invalidate
an assessment even when its text is unchanged. Node/subtree passes do not
establish parent or global acceptance. Upper levels check composition and
coverage against requirements and sources independent of generated content.
Coverage responsibilities are given; agents choose methods and depth and may
review multiple nodes in one call. Exported content fidelity and rendered-page
quality both need evidence. These are architecture changes, not completed code
or a mandatory per-node agent pipeline.
