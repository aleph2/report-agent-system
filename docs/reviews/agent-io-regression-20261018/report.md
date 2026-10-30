# Agent I/O regression verification — 2026-10-18

Codex implemented the test probes. Neo reviewed test design, source, traces and dispositions. The user paused the proposed product refactor and authorized retained tests of current behavior: fake models for program boundaries, followed by synthetic data with real models. **No application implementation, production prompt, dependency or original report was changed.**

## Result

**123 distinct offline cases: 121 passed, 2 failed.** The failures reproduce the same outcome-classification weakness at two sibling entry points. They are retained as ordinary failing regressions, not skipped or marked xfail. Four bounded real-model probes also completed: **4 HTTP attempts, 4 responses, 46,603 recorded tokens**, no retries or new unknown outcomes.

This is a scoped verification result, not proof that every historical defect is fixed or that every interface/path/condition is covered. It does not establish whole-report quality or engineering acceptance.

## Bugs reproduced in sibling paths

| Finding | Actual execution evidence | Root cause in current implementation | Disposition |
|---|---|---|---|
| NFR-05, P2: artifact-review local refusal becomes unresolved | Real SDK admission rejects a synthetic insufficient budget before send. MockTransport count is 0; shared raw reservation records `not_dispatched`. Replaying the same artifact operation returns `ARTIFACT_TEXT_WORK_OUTCOME_UNRESOLVED`. No ReviewRecord is created. | `artifact_review.py` stores an outer placeholder containing only `request_hash`; it does not pass a parent reservation to the shared evidence executor. The outer replay branch interprets every missing result as unresolved. | Blocks acceptance of artifact local-refusal classification/recovery. Retain the red case; no product fix in this test-only increment. |
| NFR-10, P2: summary local refusal becomes unknown | Real SDK admission rejects before send, count 0, no summary or usage. Original history is retained, but the saved reason is `SUMMARY_OUTCOME_UNKNOWN`; same-input replay is policy-blocked without dispatch. | `WorkingSummary._acreate_summary` catches every exception and saves the same unknown classification, including a proven local budget refusal. | Blocks acceptance of summary local-refusal classification/recovery. Retain the red case; do not automatically clear the failure or retry. |

Both have a passing **actually-dispatched timeout** counterpart: one admitted send, original history/state preserved, full token reservation retained, and no second send on replay. The correction must preserve this distinction. Shared weakness: individual callers interpret incomplete operations independently instead of consistently carrying the execution outcome from the transport/evidence boundary. A common symptom is not evidence that both require identical APIs.

Sources: `src/report_agent/artifact_review.py`, `evidence_analysis.py`, `working_summary.py`, `bounded_operations.py`, `request_budget.py`; exact failing tests are `tests/test_artifact_io_lifecycle.py` and `tests/test_summary_io_lifecycle.py`. Neo's independent assessment is in [neo-review.md](neo-review.md).

## What was exercised

| Historical mechanism / obligation | Roles and entry points | Evidence and present result |
|---|---|---|
| Semantic/control text clipped, qualifiers lost | Coordinator, Writer, Reviewer, Layout: source reading, `read_context`, `read_content_selection`, `search_sources`; managed context on/off where parameterized | Next actual fake-model request and adapter wire retain fixed long tails/qualifications. Existing native offload tests verify exact recovery instead of automatic bulk reinjection. Passed selected cases. |
| Tool lacks material agent intended to pass | Coordinator, Writer, Layout: `analyze_text` / `analyze_evidence`; Writer producer and candidate revision; Reviewer bounded check | Exact selected text, question, candidate input, count and references checked at independent tool boundary; final model schemas recorded. Passed selected cases. Reviewer intentionally does not expose the two general analysis tools. |
| Error becomes apparent success / observation identity changes | Four report roles: rejected reads; final result delivery; received-invalid producer result | Exact error code reaches next model; original content versions remain unchanged. Independently changed tool name/status is rejected. Received-invalid output is not reported as unexecuted input. Passed. |
| Learning receives shortened material | Optimizer: feedback reading and learning-material analysis | Existing native optimizer tests rerun; actual input/output tails and qualifications retained. No candidate publication or real learner run. Passed. |
| Old completion reused after scope changes; unknown work replayed | Native task resume/follow-up, Writer SDK lifecycle, summary provenance | Changed requirements cannot reuse old completion; unknown follow-up is not reexecuted; SDK refusal and timeout controls remain distinct in covered Writer paths. Passed selected cases. Artifact and summary sibling refusal cases fail as above. |
| Historical comparison accepted to read but rejected when saving; ambiguous scopes | Reviewer bounded review, assignment, historical comparison | Existing authorized comparison save/reconcile and authority-negative cases passed. Does not grant broader historical write authority. |
| Duplicate contents pages and formatting loss | Existing DOCX byte/structure tests | Nested report nodes yield one directory; selected Markdown/paragraph structure regressions passed. No new Word/Excel visual acceptance. |
| Final schema, real model I/O | Writer, Reviewer, independent text tool | Four synthetic probes described below. No generated model action was executed. |

The main group produced archived calls for Coordinator, Writer, Reviewer, Layout and optimizer, plus independent text-tool inputs/outputs. Socket guards denied external TCP/UDP for the offline pytest process; no connection attempts were observed. MockTransport calls are local synthetic interactions, not provider calls. The guard is not a claim about arbitrary subprocess networking.

## Real-model probes

Same configured provider bundle as the project: Writer `glm-5.3`; Reviewer and text tool `deepseek-v4.1-flash`. The current compatible endpoint uses its existing non-strict configuration. No strict downgrade, tool removal or provider substitution was made. The separate official-DeepSeek strict/allOf compatibility finding is **not resolved by these probes**.

| Probe | Actual result | Recorded tokens |
|---|---|---:|
| Writer one decision | Returned registered `search_sources(query='class B', source_id='s')`; arguments validate against full native tool schema. | 24,778 |
| Reviewer one decision | Returned registered `read_task_assignment({})`; arguments validate. | 12,976 |
| Independent text tool, supplied source statement | Real `process_report_content` grouping and parser accepted a block citing the supplied 75–100 range, with qualifications. | 4,488 |
| Independent text tool, missing table | Real parser accepted a block explicitly preserving missing-table/partial-coverage uncertainty without inventing a value range. | 4,361 |

The role requests were captured at the normal native model boundary with complete prompts and tools, then rebound to the configured real adapter for one response. Returned actions were inspected, not executed. The text tool used the real producer and output parser, without adoption. Output cap was explicitly **8192 for these probes**, not a production configuration change. Four small observations do not establish reliable multistep behavior or semantic quality; in particular, the normal text sample still includes material/table qualifications and is not a report-style acceptance test.

All four attempts used one `RequestBudget(4)`, including SDK retries, and the existing cumulative 170m ledger. Recorded usage moved from **93,328,297 to 93,374,900**. The previous **26m unknown/reserved upper bounds** and all **1,028 prior attempt rows** are unchanged. Remaining capacity for new reservations is **50,625,100**; this is a ledger observation, not new authorization. Cached input (15,360) is already included in the 46,603 total.

## Records and repeatability

Latest unique-node reconciliation: [verification.json](verification.json). Raw evidence remains in `.analysis/agent-io-regression-20261018/`:

- `siblings-first/`: original 38 cases, 30 pass/8 fail. Failed assertions incorrectly read the error envelope and measured state before legitimate task delegation. These are test errors, not eight product bugs.
- `siblings-v2/`: corrected fixture/oracle and wider regressions, 102 pass/1 fail. Full fake-model schemas/messages and independent tool messages archived.
- `state-and-identity/`: retained collection failure caused by a mistyped requested test name; no test executed.
- `state-and-identity-v2/`: correct selected nodes, 18 pass.
- `lifecycle-proof/`: strengthened artifact two-case proof, 1 pass/1 fail; same node IDs as the main group, not counted twice.
- `summary-lifecycle/`: summary two-case proof, 1 pass/1 fail.
- `probe-offline-v1/`: fake Writer response used an unregistered tool name; 3 pass/1 fail. Preserved as a harness error.
- `probe-offline-v2/`: corrected four-case MockTransport preflight, 4 pass. Its 80 synthetic usage units are in a separate fake ledger and are not paid tokens.
- `probe-live-v1/`: unique real probe registration, exact native/text inputs, wire requests/responses, parsed output, source/test hashes, original ledger snapshot and budget deltas. Never replay this directory.

Retained runners:

```powershell
wsl.exe -d Ubuntu-24.04 -- /home/dysun/.venvs/report-agent-system/bin/python scripts/verify_agent_io.py --out .analysis/agent-io-regression-NEW/run tests/test_agent_io_siblings.py tests/test_artifact_io_lifecycle.py tests/test_summary_io_lifecycle.py tests/test_agent_io_identity.py
```

`probe_agent_io.py` defaults to offline MockTransport. `--live` is explicit, requires the exact existing ledger and provider file, and creates a fresh directory rather than retrying an old result. Future paid runs still need a concrete scope and budget; do not use this command as an automatic retry loop.

## Remaining coverage boundaries

- This increment does not close the complete 173 role/tool-pair matrix, all configurations, all paths or MC/DC. The earlier whole-suite baseline remains valid historical evidence; this selected run does not replace it with a whole-suite green claim.
- Only Writer/Reviewer made real agent decisions. Coordinator, Layout, optimizer, summary semantics and visual tools were not real-model behavior-tested here.
- Host CLI/Web budget binding, frontend feedback retargeting, Office transaction duration, multipart header typography, stored Reviewer prompt identity and generic ledger presentation require their own applicable tests. No absence-of-bugs claim for these areas.
- The known official strict-schema incompatibility remains separate. No new provider configuration was tested.
- Source/data semantics, complete first-contract-section scope, real Word/Excel rendering and final customer acceptance were not tested by this synthetic I/O wave.

## Changed code

Six new files only: `scripts/verify_agent_io.py`, `scripts/probe_agent_io.py`, `tests/test_agent_io_siblings.py`, `tests/test_agent_io_identity.py`, `tests/test_artifact_io_lifecycle.py`, `tests/test_summary_io_lifecycle.py`. Existing `tests/test_agent_result_delivery.py` was already untracked before this task and was reused unchanged. The pre-existing output directories are not part of this change.

See [code-changes.diff](code-changes.diff) for the complete new code, and [source-baseline.json](source-baseline.json) for the starting file hashes and Git status. Application source, pre-existing tests and dependency declaration are checked against that baseline in `verification.json`.
