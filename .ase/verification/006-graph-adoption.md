# Task006 Real GLM Graph Adoption Trial

Current status, 2026-09-28 Asia/Shanghai: COMPLETE for this bounded synthetic
graph-adoption trunk. One authorized run finished `reviewed_draft`, with real
Neo4j writes/retrieval/traversal, adopted fact versions, exact-target review and
four-page rendered export. No in-flight model or pending checkpoint task remains.
See the execution addendum below. The preparation sections retain the prior hold
and predeclared acceptance criteria as historical evidence, not the current status.

## Scope

Prepared by ASE Tester, 2026-09-27, for Main's serial execution coordination.
Status: PREPARED, NOT LAUNCHED. The user's specific instruction requires waiting
until Main explicitly confirms that the real engineering run has settled before
starting this paid synthetic run. Elapsed time or an idle process is not that signal.

Owned inputs/artifacts: `.runs/task006/graph-adoption/` and this record only.
Launcher: existing `scripts/run_deepagents_trial.py`, unchanged.
Runtime, workspace, dependencies, engineering data and other runs are not modified.

Manifest: `.runs/task006/graph-adoption/manifest.json`. Four small fictional notices
describe a shared gate, its pedestrian and vehicle openings, an east-ramp approach
and a delivery bay. No preseeded facts, material artifacts or task state. The two
audience questions use different wording and require different answers about a
shared restriction. The goal requests reusable indexed evidence, relationships,
actual adoption and exact-version review; it does not prescribe a tool sequence,
fixed agent count or mandatory intermediate documents.

Prepared manifest SHA256:
`8a44a205bad56108df2e6bc3dc6d32e6b9ced3cde2fc27a55dc6bb8cacb9ba7e`.

## Lifecycle Gate Decision

- Stage: Task006 end-to-end integration of real model decisions and graph adoption.
- Top-level outcome: a usable source-grounded report whose adopted reusable graph
  facts can be inspected, rather than a graph component test disconnected from output.
- Decision owner: Main. Test preparation/execution and evidence inspection: Tester.
- G1: reuse applicable native runtime and graph/local-embedding verification in
  `006-deepagents-integration.md` and `006-knowledge-evidence.md`. Those component
  passes do not establish this model-driven adoption trunk.
- G2: NOT RUN. Requires the actual GLM5.3 run, saved graph facts, retrieval evidence,
  adopted fact versions, an independent review of the exact saved draft and export.
- Baseline: existing code at launch; record hashes/versions immediately before the
  authorized attempt because Main is still iterating. No model request yet.
- G3 expected gain: fill the real graph-adoption evidence gap left by a successful
  synthetic report that used only source/material records.
- Non-regression invariants: project isolation; knowledge producer ownership;
  writer/reviewer upstream read-only boundaries; source provenance; no fabricated
  engineering approval; committed receipts retained across any recovery.
- Held-out/uncertainty: this small synthetic example can establish exercised paths
  and assess its two explicit answers, not general retrieval recall or report quality.
- Integration decision: pending run and evidence review. No baseline promoted.
- Next action: await Main's explicit settled signal, then one attempt through the
  existing launcher. Inspect before any recovery; no blind whole-run retries.

## Acceptance And Evidence

These are development assertions, not extra runtime steps or model prompt stages.

1. Paid-provider identity remains authorized GLM5.3. Use the launcher's existing
   credential-container lookup; never print or persist credential environment data.
   Record model requests, responses/errors and usage with unknown usage kept unknown.
2. A fresh isolated project namespace is bound by the application. Native event
   traces show successful `knowledge_put` calls by the knowledge producer. Confirm
   corresponding persisted Neo4j facts, provenance and write receipts in that namespace;
   tool-call intent alone is insufficient.
3. Observe at least two different substantive search queries against the reusable
   collection, serving the visitor and courier questions. At least one successful
   vector/hybrid result must contain vector-score evidence from the real pinned local
   embedding model. Empty search attempts alone do not count as semantic retrieval.
4. Relationships are apt for this scenario: gate restrictions apply to two approaches.
   Verify useful persisted relationships and a successful native traversal returning
   relevant paths. If the agent declines to create/use them, record that evidence gap
   honestly instead of manually adding graph data and calling the trunk passed.
5. Final saved draft has nonempty `fact_ids`. Read those exact versions from the
   bound real Neo4j project, confirm active/current status and provenance belonging
   only to the four supplied source IDs. Correlate adopted IDs with facts actually
   returned to the agent, not merely all search candidates or tester-created facts.
6. Final review belongs to reviewer, has `target_id` equal to the delivered draft ID,
   and the target is observed in that review context. Delivery and exported DOCX
   identify that exact reviewed version; inspect graph freshness projection as well.
7. Manually verify source-grounded answers: at 13:00 the guest may take the east ramp
   and G4 pedestrian wicket; west steps remain closed. At lunchtime the van may not
   enter; its next stated opportunity is 14:00, through G4 vehicle lane to Bay B2,
   within the 14:00-17:00 window. Pedestrian permission is not vehicle permission.
   Preserve the synthetic scope and no engineering sign-off.
8. Render the saved DOCX with the already verified local method from
   `006-export-visual.md`; inspect every page. Saving/exporting alone is not a pass.

Use `deep_tool_start/end/rejected`, model-request ToolMessages, model responses,
`result_committed`, selected delivery, checkpoint state and read-only graph queries
as complementary evidence. An end event can still accompany a rejected tool, so it
must not by itself be counted as a successful write/search. Deduplicate repeated
ToolMessages by native call/context identity when histories repeat across requests.

## Prepared Launch Command

DO NOT EXECUTE until Main explicitly says the real run has settled. This is a
prepared command, not evidence of a launched or successful run.

```bash
cd /mnt/c/Users/dongy/Documents/ChatGPT/report-agent-system
env PYTHONPATH=src REPORT_GRAPH_URI=bolt://127.0.0.1:17687 HF_HUB_OFFLINE=1 \
  /home/dysun/.venvs/report-agent-system/bin/python \
  scripts/run_deepagents_trial.py \
  --project .runs/task006/graph-adoption \
  --manifest .runs/task006/graph-adoption/manifest.json
```

No `--resume` on the first attempt. Later recovery requires inspecting checkpoint,
receipts, tool outcomes and model activity before deciding whether/how to resume.
Do not change the manifest after Store initialization. Do not repurpose the real
engineering project's storage or namespace. Graph URI is the independent system's
dedicated service, not the legacy graph.

## Commands Run

| Command/check | Result | Notes |
| --- | --- | --- |
| Read project instructions, Task006, launcher, runtime graph tools and ownership | Complete | Read-only preparation. |
| JSON/Store contract validation in temporary storage under owned directory | Passed | Four source IDs resolve; zero seeded results/tasks, no call intent or graph namespace. Temporary preflight storage cleaned up. Actual trial `state.db` does not exist. |
| Check goal for prescribed tool names | Passed | No `knowledge_put`, `knowledge_search`, `knowledge_traverse` or `submit_result` instructions; deliverable and capability requirements only. |
| Read cached pinned ONNX model and verify SHA256 | Passed | Revision `faf4aa4225822f3bc6376869cb1164e8e3feedd0`, SHA256 `634d0f66c29dc934c8fa72b8a4fe91dd4d420a22f1d82a241058d4316e659a99`; no download or inference. |
| Count fixture source title/content tokens using cached tokenizer | Passed | scope 128, gate 117, walking 98, delivery 125; below 512. Agent-created fact lengths still need inspection. |
| Neo4j read-only `CALL dbms.components()` and `SHOW INDEXES` | Passed | Dedicated service at port 17687: Neo4j 2026.08.1; `ra_fact_text` and `ra_fact_vector_v1` ONLINE. Zero graph mutations or fact seeding. |
| Installed package metadata | Read | DeepAgents 0.7.19, LangGraph 1.2.12, Neo4j Python driver 6.3.1, fastembed 0.8.1. Reconfirm at launch if environment changes. |
| Paid GLM launcher | NOT RUN | Waiting for Main's explicit settled signal. |

## Manual Checks

The source notices are consistent and sufficient for the two questions. Scope
explicitly excludes outside-hours/weekend/emergency/design work. No source content
contains real engineering inputs, credentials, tool instructions or permission grants.

## Skipped Checks

| Check | Reason |
| --- | --- |
| Model execution, adoption, exact review, export and visual QA | Serial launch hold; no run yet. |
| General model-quality/engineering acceptance | Not established by this bounded synthetic trial. |
| Independent alignment review of new architecture | No runtime/architecture change in this task; no new review pass claimed. |

## Failures And Fixes

One preflight diagnostic query failed because its `$names` Cypher parameter was
expanded while crossing the shell invocation. Reissued a static read-only index
listing and filtered its returned rows locally; both expected indexes were ONLINE.
This was a diagnostic-command construction error, not an application or graph defect.
No runtime code or service setting was changed.

No run-related defect assessed yet. After launch, classify confirmed findings P0-P3
with rationale, affected action, containment, owner and disposition. A missing graph
adoption path blocks claiming this graph-adoption test passed, not unrelated source-only
draft testing. Keep historical failures and do not repair runtime within this task.

## Residual Risk

The model chooses its actions. It may produce a correct source-only report while
leaving graph adoption unproven. A final `reviewed_draft` status does not by itself
satisfy the graph-specific acceptance criteria above. The expected substantive
answers are not a prescribed execution trace.

## Authorized Execution Addendum

Actual performer: ASE Tester, independently inspecting Main/Rawls runtime and
graph implementation. Main explicitly announced real CLI 76140 settled and said
GO. Paid execution: 2026-09-27 16:02:03 through 16:09:00 UTC (2026-09-28
00:02:03 through 00:09:00 Asia/Shanghai). No second model run or resume was started.
Manifest SHA256 remains the prepared value above; only four fictional sources.

### Baseline And Artifacts

All paths below are under `.runs/task006/graph-adoption/` unless stated otherwise.

- `launch-intent.md`: exact user authorization, serial preflight, launch command
  and source-file SHA256 baseline. The repository was uncommitted; no Git revision
  is fabricated. The source-only real engineering run is not this graph test.
- `state.db`: native audit and business receipts; `checkpoints.db`: LangGraph
  persistence. `events.jsonl`: derived copy of all 330 audit events.
- `audit_trial.py`: read-only local inspection helper; `audit-evidence.json`:
  deduplicated calls/ToolMessages, results/tasks and read-only Neo4j snapshot.
  `acceptance-checks.json`: assertion results, exact queries, scores and versions.
- Actual model `glm-5.3`, DeepAgents 0.7.19, LangGraph 1.2.12,
  langgraph-checkpoint-sqlite 3.1.1, langchain-openai 1.6.6, Neo4j driver 6.3.1,
  fastembed 0.8.1, markdown-it-py 4.0.0. Neo4j service is the dedicated port 17687.
- Graph namespace: `87fd26c7-3b84-4c87-9d4d-7a8c33057813`.
- Saved draft: `2ea9d129-45b8-456b-8025-7a0b115a528b`.
  Body SHA256 `311a4511c8bc9b8bda884f71e4a0ddad7b13ea3d361268c0aa80a5c0bbd79ef4`.
- Exact review: `5857049a-ab05-49a4-b463-d66d00422a34`, owner `reviewer`,
  outcome `accepted`, target and `observed_result_ids` both identify that draft.
- Export: `exports/2ea9d129-45b8-456b-8025-7a0b115a528b.docx`, SHA256
  `d29c4f4028a709dfdd9601f60ec33257d77d8dfbe30c5c648d0c432da6b1428e`.
  PDF and four PNGs: `exports/visual-qa/`. PDF SHA256
  `0623ca8708f660a863c9f38dc671fc02d5833d4a342bce8695d190ae55bfd902`.
  `export-qa.json` records text, bounds and version checks.

### Behavioral Evidence

| Predeclared check | Observed result |
| --- | --- |
| Native model-driven graph creation | 13 successful `knowledge_put`, 25 `knowledge_link`; read-only Neo4j confirms 13 active revision-1 facts, 25 edges and 38 unique receipts (13 put, 25 link). All writes by knowledge role. |
| Project/source boundaries | Every saved fact and relationship is in the new namespace; all source references are drawn from the four synthetic IDs. No engineering inputs or tester-seeded facts. |
| Real embeddings | All facts have pinned model ID and 384 dimensions. Cached ONNX SHA matches the preflight. Full title/body token counts range 151-338, below 512; no fixture fact exceeds the indexing window. |
| Different semantic questions | Two successful native hybrid searches, each returning three scored matches with real vector scores, not empty calls or tester queries. Exact details below. |
| Useful graph traversal | Knowledge call `call_f820a1d8e9cf4dc48b81a0c9` and reviewer call `call_60fe2b84f75448fd9e4f41f4` each return six paths from midday restriction fact `e659887d-322d-473d-8ae2-bd62e776e9fd`. Relations include `applies_to_part_of`, `defines`, `not_closed_by`, `unaffected_by`, `consequence_of`, `derived_from`. |
| Actual draft adoption | Draft `fact_ids` contains all 13 persisted active versions. All IDs were returned to the coordinator through native knowledge-task output, not fabricated by Tester. Report explicitly cites F1-F13 with exact IDs and uses them for both answers. |
| Exact-version independent role review | Native reviewer first read the saved draft, read all four sources and all 13 facts, and traversed the graph. Committed review records exact observed target and accepted outcome. Root selected this draft/review pair. No standalone writer child was required: root authored through the permitted draft path, persisted owner `writer`. |
| No fixed artifact chain | Only draft and review results were committed; native tasks were knowledge then reviewer as chosen by the model. No mandatory purpose/plan/materials result chain was inserted. |
| Export/freshness | DOCX lists the exact draft/review and 13 knowledge versions with `current` at 16:09:00.955967 UTC. No changed fact IDs. |
| Settlement | Launcher exit 0, no model errors, no issues; `--inspect` shows `next=[]`, `tasks=[]`, zero interrupts, checkpoint `1f1ba8dc-0228-6253-802a-5274b37fedee`. Inspection made no model request. |

Actual semantic queries, issued by the knowledge agent:

1. `guest walking without a vehicle at one in the afternoon how to get in`
   (`call_f1e624cc344a4592b86f169e`): first result is pedestrian-answer fact
   `7b37a761-1c62-47ff-aaf2-d13d24b20a18`, vector score `0.7166846990585327`;
   other returned vector scores `0.6947959661483765`, `0.6576550602912903`.
2. `courier with parcels in a van at lunchtime when can the truck get through and where does it unload`
   (`call_4259c2c55fe94e2cb6b4f961`): first result is van-answer fact
   `8e1938cf-2db0-48bd-9f45-3ab1e9949c1b`, vector score `0.7645134329795837`;
   other returned vector scores `0.7441156506538391`, `0.6382431387901306`.

These demonstrate two queries in one model run, not a separate later user session
or held-out retrieval benchmark. Locators are preserved as block/character text in
fact bodies; structured provenance locator fields are empty because the native
put calls supplied source IDs. Do not claim structured locator validation.

Tester manually checked the bounded answers against the frozen notices: pedestrian
at 13:00 uses east ramp and G4 wicket, west steps closed; lunchtime van has no entry
permission before 14:00, then uses G4 vehicle lane to Bay B2 within the afternoon
window. The shared midday vehicle restriction does not close pedestrian access.
The saved report explicitly excludes design/sign-off and out-of-scope arrangements.
This checks these answers only, not general agent or engineering quality.

### Execution And Usage

| Command/check | Result |
| --- | --- |
| Prepared GLM launcher without `--resume` | Exit 0, reviewed draft, one trial-attempt intent. |
| `audit_trial.py --save` | Read-only database/graph inspection; 13 facts, 25 edges, 38 receipts. |
| Local acceptance assertions | Passed: namespaces, source set, owner, receipt uniqueness, adoption, native-returned IDs, nonempty scored searches, paths and exact observed review target. |
| Launcher `--inspect` | Exit 0; no pending tasks/interrupts, no model call. |
| Bundled DOCX renderer with existing LibreOffice | Exit 0; all four PNGs opened and inspected. |
| PDF text/bounds check | 83/83 paragraph/cell text units recovered ignoring whitespace; zero out-of-page glyphs. |

82 requests and 82 responses, provider-reported prompt tokens 1,263,973,
completion tokens 20,979, total 1,284,952. No response lacks usage. By role:
coordinator 14 responses / 170,171 tokens; knowledge 47 / 869,051;
reviewer 21 / 245,730. These are reported usage counts, not a cost estimate or
proof of provider-internal attempt counts. No efficiency improvement is claimed.
82 calls for four short sources warrants later performance evaluation; it is not
by itself an architecture-validation failure or a reason to falsify this run's
successful graph adoption. No hidden call/token quota was introduced.

### Findings And Limits

- GA-01, P2 recovered model/tool argument misuse: event 220 rejected the first
  coordinator `submit_result` with `RESULT_NOT_IN_PROJECT`; fact UUIDs were placed
  in `input_ids`. The next submission moved them to `fact_ids`, left `input_ids`
  empty, and committed exactly one draft. No manual clarification, replay, resume
  or runtime edit was required. Scope: one submission in this trial. Containment:
  validation and model correction worked; no delivery/test action remains blocked.
  Owner Main; record for future contract-usability evaluation, not a demonstrated
  permission or storage defect. No Python exception stack escaped the middleware;
  exact rejected arguments and error ToolMessage remain in the saved audit.
- GA-02, P3 export polish: non-table `**` and hyphen-list markers remain literal;
  the introductory table label is on page 1 and table starts on page 2. The full
  14-row, three-column table fits page 2, including F13; readable, no clipping.
  No current trunk action blocked. Main/exporter owner; defer wider Markdown and
  caption polish. This shares the known narrow-parser limits in export verification.
- No crash/interrupt recovery was exercised here; reuse native offline recovery
  evidence separately, do not claim this run proves new recovery behavior.
- General retrieval recall, later independent query sessions, sustained performance,
  arbitrary source sizes and real engineering graph adoption remain unverified.
  Main reported the real engineering report as graph `not_used`; this synthetic
  evidence must not be transferred to that report.

### Gate Disposition

G1/G2: the model-driven graph-adoption path is validated within this synthetic
scope through native tools, persisted graph data, exact review and usable export.
G3 observed gain: real adoption evidence now exists, beyond prior component tests
and source-only runs. This is not a controlled performance comparison or a blanket
full-suite non-regression claim. Relevant observed ownership/provenance invariants
held; broader existing test evidence belongs to Main's integration record.
Tester recommends accepting this bounded infrastructure/trunk evidence with the
limitations above. Main owns integration and baseline promotion. No engineering
sign-off or general model-quality certification. No further paid run is planned
or in flight from this tester.
