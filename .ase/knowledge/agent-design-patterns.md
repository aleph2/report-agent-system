# Agent Design Knowledge

Checked 2026-09-27. For development architects, not a runtime system prompt.
Read relevant sections on demand. Official pages below are mutable: verify the
installed or proposed pinned version before relying on an API or default.
This note does not install a framework, authorize a migration, or certify behavior.

## Project decision and observed implementation

The user selects DeepAgents as the framework and Google agent design patterns as
design references. Inspection of `pyproject.toml` and `report_runtime.py` found
Google ADK 2.10.0 and its Runner/LlmAgent, not a DeepAgents implementation. Record
that mismatch rather than rewriting history. A DeepAgents version and working
integration are not yet established by this knowledge update.

Business planning, document intent, applicability, semantic identity and deciding
whether a source change matters belong primarily to agents. Code executes explicit
operations and enforces permissions, identity, storage and reliable effects. Not
every conditional requires an LLM: numerical checks and authorization remain code.

## Patterns are choices, not stages

The following compact selection guide is informed by Google's
[pattern guide](https://docs.cloud.google.com/architecture/choose-design-pattern-agentic-ai-system).
The project applications and cautions are our design judgments, not vendor guarantees.

| Pattern | Useful when | Avoid in this project |
| --- | --- | --- |
| Single agent with tools / ReAct | Next action depends on observed results | A hidden fixed pipeline behind nominal tool choice |
| Planning and replanning | Work needs decomposition as information arrives | Freezing every chapter, subtask and route before reading evidence |
| Coordinator with delegated workers | Context isolation or a distinct responsibility helps | One expert per small text operation or a mandatory five-role roster |
| Routing | Different capabilities fit different observed needs | Treating model-proposed routing as authority to expand permissions |
| Review and refinement | A concrete quality question can be checked against evidence | Repeated reviews with no new evidence, correction or progress |
| Sequential / parallel workflows | Real dependencies or independent work justify them | Imposing a fixed business chain; enabling concurrency without authorization |
| Human intervention | Source conflict, missing facts or reserved decisions need a person | Asking humans to compensate for unperformed retrieval or broken tools |

Final report review is a confirmed project requirement; avoiding repetitive review
does not remove it. A larger roster is not inherently more intelligent. Prefer the
smallest arrangement that can achieve and verify the outcome.

## DeepAgents reuse map

These are documented capabilities, not proof they are enabled in this application.

| Need | First capability to inspect | Configuration or remaining responsibility |
| --- | --- | --- |
| Model/tool execution | [DeepAgents harness](https://docs.langchain.com/oss/python/deepagents/overview) | Configure a compatible model and tools; do not build a second decision loop |
| Task planning | Harness planning middleware | Defaults change by version; current overview says planning is opt-in from 0.7, not universally enabled |
| Delegation and context isolation | [Subagents](https://docs.langchain.com/oss/python/deepagents/subagents) | Configure goals/tools and permissions; delegate useful outcomes, not every extraction |
| Context growth, skills and memory | Harness context facilities | Check provider/version and backend; summaries are not original evidence |
| File access and persistence | [Backends](https://docs.langchain.com/oss/python/deepagents/backends) | Select state/filesystem/store/composite backend and isolation namespace; memory-only storage is not restart durability |
| Resume and state persistence | [LangGraph checkpointers and stores](https://docs.langchain.com/oss/python/langgraph/persistence) | Configure durable storage and stable thread identity; distinguish thread checkpoints from cross-thread business data |
| Human approval | [Interrupts / human-in-the-loop](https://docs.langchain.com/oss/python/deepagents/human-in-the-loop) | Requires a checkpointer; connect the UI to the documented resume protocol, not a competing pause engine |
| File permissions | [Permissions](https://docs.langchain.com/oss/python/deepagents/permissions) | Verify scope and subagent inheritance; file rules do not automatically secure custom database tools or arbitrary shell execution |
| Retry and tool feedback | [Middleware](https://docs.langchain.com/oss/python/langchain/middleware/built-in) and provider integration | Verify available policies before wrapping; avoid stacked retries and unsafe replay of uncertain side effects |
| Progress and diagnostics | Harness streaming and existing runtime events | Project UI presents status and actionable errors; do not invent total work or ETA |

Framework state recovery alone is not an exactly-once guarantee for external writes.
Connect project operation receipts/transactions where needed; avoid parallel sources
of truth for the same runtime state. Assess each custom component before removing it.
Source ownership, report versions and project-specific data isolation remain product
requirements even when framework primitives implement part of their enforcement.

## Shared knowledge and tools

Graph, vector index and original-file storage are infrastructure behind tools, not
extra agents. LangGraph's execution graph is not the project's factual knowledge graph.
A filesystem backend is not by itself semantic retrieval or relationship traversal.
Do not label literal substring search as vector search or claim unused graph services.

Expose fact/entity/relation retrieval, vector search and scoped traversal as meaningful
capabilities when implemented. Give agents descriptions of purpose, inputs, results,
coverage/pagination, errors and permissions so they can choose appropriate actions.
CRUD rights follow producer ownership. Writers/reviewers read upstream knowledge and
request corrections; revisions preserve cited history. Separate sources, interpretations
and adopted evidence. Let agents judge semantic identity and business impact; programs
store the resulting relationships without re-deciding those judgments by type rules.

Observation logs record what was returned. They must not silently become adopted
dependencies. A changed search hit may warrant an impact question, not automatic
invalidation of every result that once observed it.

## Framework-first design practice

For a material choice, attach a small reuse comparison to the existing design note:
needed capability, native API and version, required configuration, observed evidence,
actual gap, and smallest extension. Mark evidence as documented, installed, exercised
or unverified. Do not demand a separate form or approval for each tool or minor edit.

Before adding a restriction ask: does it enforce an explicit safety/ownership boundary,
or substitute a procedural rule for an agent's business judgment? For example, require
evidence appropriate to the report, not a standalone `materials` artifact solely to
pass a schema. Preserve useful combined outcomes and alternative valid paths.

Prefer framework configuration, then an existing integration, then a thin domain tool.
Custom runtime infrastructure needs an evidenced gap, not familiarity with traditional
workflow design. Conversely, do not remove permissions or safe-write mechanisms merely
because a framework advertises persistence. Agent autonomy and safe execution coexist.

Evaluate both deterministic mechanics and agent capability. Scripted tests can verify
tool protocols; actual-model scenarios test decisions and content. Accept different
valid trajectories, including reuse and skipped unnecessary work. Record no-progress
repetition, source changes and recovery without using a total-call quota as a proxy.
Paid trials still require applicable permission; this document grants none.

## Further framework comparisons

ADK, Hermes and other harnesses are comparison candidates, not interchangeable layers
or an instruction to combine frameworks. Resolve an ambiguous name such as "DeepSeek
harness" to an exact official repository/product/version before attributing features.
This note does not claim a completed comparison of those systems. Extend the evidence
only for an actual design decision; do not turn reading patterns into a research phase
that indefinitely postpones the useful end-to-end test.
