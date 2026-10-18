# Agent decisions and independent text tools — 2026-10-14

DeepAgents owns action choice and outcome delegation. Agents choose goals,
materials, strategy, structure, assignments and adoption. Bounded tools perform
substantive extraction, comparison, drafting and rewriting. This is a control and
persisted-output boundary, not a claim that model reasoning contains no prose.
The same configured provider/model may serve separate agent and tool calls.

| Responsibility | Current native capability |
| --- | --- |
| Writer chooses desired work | `process_report_content` produces typed ContentNode/Evidence payloads in one bounded call. |
| Writer adopts or revises its content | `save_text_node` / `commit_objects` adopt an exact actor/task-bound receipt; body, cells, caption and qualifiers cannot be overridden. `previous_ref` preserves identity, ownership, CAS and existing revision limits. |
| Coordinator defines goals, criteria and relations | Decision objects remain agent choices; Coordinator cannot author ContentNodes. |
| Reviewer selects checks and observations | `perform_assigned_review` compares content; `perform_assigned_artifact_review` compares exact saved artifact observations. Assignment, version, actual page/reference coverage and receipt ownership guards remain. |
| Layout chooses presentation | Existing layout/export operations remain, without report authorship or invented visual observations. |
| Learner formulates guidance | Optional `analyze_learning_material` synthesizes selected feedback/source/report evidence; project_fact candidates adopt exact factual fields. Preference/general-method strategy formulation stays with Learner; these tools cannot release candidates. |

Text jobs have no search, delegation, business-object writes or further model
calls. Inputs and authority are bound before invocation and checked at adoption.
For long sources, pass captured SourceArtifact refs plus located source_selections;
only version metadata and selected text enter the job. `output_count` permits
1–32 related payloads in caller-selected order in one call. Adopt each using its
zero-based `text_work_index` and original previous_ref. No mandatory per-node call
or merging of original identities is introduced.

Literal Evidence must quote actual text in every declared source and cannot carry
derived fields. Calculation Evidence must match an owned
`observe_evidence(kind="calculation")` receipt (`method="sum_products"`, exact
result). Neither requires a text model. Single-line report/chapter headings with
empty qualifiers are structure decisions; tables, figures and substantive blocks
are not heading exceptions.

Completed receipts establish receipt of valid tool output, not factual correctness.
Known truncated, filtered, refused or invalid tool-call responses cannot become
success receipts; raw rejected outputs and observed usage remain in generation
records. Failed/unknown attempts do not silently retry. Agent inference and context
summary costs still exist. Existing provider limits and accounting remain; these
interfaces grant no spending, report-revision, publication or sign-off authority.

ContentNode's final tool schema exposes kind-specific rendered-body requirements:
text nodes require `body.text`, tables require columns and rows, and figures require
source identity and caption. Backend content, ownership and reference guards still
apply. A received response rejected during JSON/output-contract validation is
recorded as `known_failed`, with its raw response, usage and actionable diagnostic;
it is not reported as an unexecuted call. Unknown transport outcomes remain
reserved. Shared analyzer length/refusal checks still precede this classification.

A completed text receipt at a pending native tool checkpoint can be reused after
a schema-only repair when archived inputs prove the same actor, objective,
authority, evidence, output count, model and prompt, and current validation accepts
the unchanged original output. This does not issue another provider call or alter
the original receipt. Changed intent, missing evidence or unknown results reject.

Layout exposes independent optional `table_alignment`, `table_cell_alignment`
and `table_cell_first_line_indent_mm` globally or per table. A value of zero
explicitly cancels inherited first-line indentation. Omitted values retain existing
behavior; per-node table controls reject non-table targets. These parameters affect
presentation only and do not establish artifact or semantic acceptance.

## Decision-only observation

`report-agent report-run --project ISOLATED_CASE --decision-only`, or
`run_report(..., decision_only=True)`, allows agent decisions and deterministic
observations, then interrupts through LangGraph before the selected substantive
text/vision tool handler. `decision_observation` saves actual role, tool and args,
`executed=false`, and no output/correctness claim. It is a terminal measurement:
execution entrypoints and the handler reject resume, including an already-built
graph. Read-only trace inspection remains possible. Use a fresh isolated case for
another comparison. One observation proves the selected action only. Feedback
effects require comparable baseline/feedback decisions; no real-model behavioral
comparison was run for this implementation, and decision evidence cannot prove
generated prose, scoring, engineering acceptance or learning generalization.

## Historical data and exports

Fresh CLI init defaults to hierarchical-review-v1 with delegated bounded review.
Non-hierarchical DeepAgents, native-rubric-v1 and ADK materials/report execution
entrypoints are inactive. Saved history, source/version records and exports remain
readable; opening them does not migrate or replay jobs. Trusted host ContentStore
APIs remain available for controlled offline fixtures/imports and are not exposed
as unguarded agent authorship tools.

`python scripts/run_deepagents_trial.py --project SAVED_CASE --inspect` reads
checkpoint metadata with the native saver using read-only SQLite. It needs no
credentials and constructs no model or executable graph. Missing/incompatible
historical databases are reported rather than recovered or initialized in place.

Compatibility export_docx customer copies omit automatic model status, runtime
diagnostics and internal identifiers. Actual report body, source index and genuine
missing/conflicting-source uncertainty remain. `include_execution_record=True`,
or CLI `export --execution-record`, explicitly produces a diagnostic copy.
Stored reports and previous exports are not rewritten; omission of execution
commentary does not establish engineering approval.

Maintained context-summary tests use report_agent.working_summary rather than
ignored .analysis helpers. Verification uses offline scripted services and actual
export bytes; it is not fresh report semantics or Word/Excel visual acceptance.

Pre-snapshot identity discovery is available through `read_object_index`: bounded
whole records, exact versions and ownership, a stable pagination digest, and no
bulk report body. It does not select the report scope or grant artifact ownership.
The existing recovery path also retains already-returned identity-only commit
receipt ranges. Retention verifies the same actor, original observation digest,
actual successful database operation and matching native tool-call range. Exact
duplicate ranges keep one literal copy while preserving all message/call IDs.
Source prose and analysis retain their ordinary bounded-preview policy; neither
identity availability nor a saved object proves reading, adoption or correctness.
`read_summary_observations` exposes its 1..20-record page bound in the native tool
schema; its handles must be used exactly, without abbreviation or reconstruction.
