# Task001 verification: independent materials-agent prototype

Date: 2026-09-27. Main performed implementation, tests and live-trace/content inspection.
Independent alignment/code reviewer: Heisenberg, agent
`01a0e055-b5c5-7802-953d-03afafcfac58`. Review is development-time, not a runtime agent.

## Outcome and boundary

The independent CLI runs a real ADK model/tool loop against configured GLM5.3, reads
synthetic sources, reuses or commits immutable materials, and accepts operator feedback.
There is no fixed semantic stage list or legacy application import. Code tools do not
invoke a hidden multi-expert pipeline. The optional LLM analysis tool is one bounded
request, not another agent. Sources remain immutable; ownership is bound by code.

This supports narrow feasibility of autonomous materials work. It does NOT accept the
full report-system G1/G2: report planning, larger-data indexing, writing, final review,
Word export, desktop UI and representative engineering end-to-end quality remain open.
These examples fit easily into context and do not establish large-document performance.

## Reproducible environment

- Independent Git root: `C:/Users/dongy/Documents/ChatGPT/report-agent-system`.
- Branch: `codex/initial-prototype`; first implementation remains uncommitted.
- New venv: `/home/dysun/.venvs/report-agent-system`, Python 3.12.14.
- google-adk 2.10.0, litellm 1.102.1, pytest 9.1.1, pytest-asyncio 1.4.0.
- `python -m pip check`: no broken requirements.
- `python -m compileall -q src scripts tests`: passed.
- `python -m pytest -q`: 23 passed. One ADK experimental function-schema warning.
- Actual provider model configured as `openai/glm-5.3`, reasoning_effort=high.
  This is the adapter configuration, not a packet-level verification claim.
- Request timeout 180s; task timeout 1800s; num_retries=0; no cumulative call/token quota.
- Credentials loaded only into the trial subprocess environment from read-only existing
  service metadata. New application code does not read legacy config or call its APIs.
  No key copied to source files. No engineering material or OCR was transmitted.

## Live evidence

Private raw evidence remains in each `.runs/.../state.db`, ignored by Git. Responses
may contain model reasoning or input text; do not publish raw event dumps. The table
reports actions and committed outputs only. Timestamps below are SQLite UTC.

| Case | Evidence | Outcome | Decision / text-tool requests | Observed actions |
| --- | --- | --- | --- | --- |
| Existing-result reuse | `.runs/live001/materials-reuse/state.db`, 09:43:26-09:43:39 | draft_ready, original fixture selected | 3 / 0 | read_sources, select_result |
| Fresh materials (off-plan) | `.runs/live001/materials-new/state.db`, 09:43:39-09:43:52 | draft_ready, one new result | 4 / 0 | read_sources, save_material, select_result |
| Feedback supplement | `.runs/live002/materials-feedback/state.db`, 09:50:17-09:51:51 | draft_ready, old result unchanged, new result selected | 4 / 0 | read_sources, save_material, select_result |

The original approval named reuse and feedback supplementation. Main initially supplied
a fresh-material case instead of feedback. This was an execution-scope mistake, disclosed
in chat and retained here; it is not retroactively treated as approved feedback evidence.
The originally approved feedback case was then run once in live002. No attempted cases
were blindly replayed. No additional paid variants are authorized by this record.

The feedback case started with a saved note omitting timing. Explicit feedback requested
supported timing, maintenance-week applicability and night-time limitations. The selected
new note adds 08:00-17:00 and the maintenance week, preserves the east/west arrangement,
and says no night-time route can be inferred. The original artifact remained byte-for-byte
unchanged. No prescribed tool sequence or mandatory text-tool call was supplied.

All three runs used direct interpretation by the controller. Thus the optional text tool
is covered by protocol tests only; its real invocation/semantic quality is not established.
Request counts are observations, not a quota or proof of billed tokens/cost.
Provider-reported total tokens sum to 5,200 (reuse), 7,151 (fresh materials) and
7,689 (feedback). These total fields already include provider output accounting;
thought-token fields are NOT added again. No price or charge is inferred.

After the last configuration-error fix, the installed CLI `run` was invoked against
the completed live002 project without provider credentials. It returned the same
selected artifact; the durable count remained 4 model requests and 21 events. This
was receipt retrieval, not an additional paid trial. live001 preceded the R1-R3 fixes;
live002 followed the main R1-R3 fixes but preceded moving config construction inside
runtime. No claim is made that the final code was paid-retested from empty input.

## Review findings and Main disposition

| ID | Severity / rationale / scope | Blocked action and containment | Disposition |
| --- | --- | --- | --- |
| R1 | P2: trailing failure overwrote an already committed draft status, risking unnecessary model replay | Blocks completed-result recovery claim; persisted artifact remained intact and live trials could continue | Main fixed: preserve draft_ready, record trailing error separately; error and actual Task.cancel regressions pass |
| R2 | P2: runtime failure could still exit CLI with code 0 | Blocks using process exit as execution acceptance; inspect persisted status meanwhile | Main fixed CLI exit codes; five result/error combinations tested |
| R3 | P2: initialization outside try could leave false running | Blocks startup-failure visibility claim; did not affect already started live runs | Main moved initialization/config construction inside guarded runtime, tested startup and missing-config errors |
| R4 | P2: trial script checks and records live_attempt_registered separately before taking the run lock; simultaneous script launches could both register | Blocks claiming concurrency-safe paid-trial deduplication, not this observed serial run; do not launch the same trial concurrently or blindly rerun it | Open. Main will make registration atomic before automated/concurrent trial dispatch; application project lock and transactional artifact receipts do not by themselves close this script gap |
| C1 | P2: feedback output equates all time outside 08:00-17:00 with night-time, and wording about west-path closure beyond the week is ambiguous | Blocks calling this note semantically fully verified, not the isolated mechanism experiment; label not_reviewed and do not use as engineering output | Main retains raw result, no manual rewrite or silent pass. Resolve through producer feedback during a later authorized content-quality iteration |

All confirmed findings are local, containable and do not justify halting unrelated
development. Independent final increment review confirmed R1-R3 closed within this
prototype scope, R4 remains open, and C1 still blocks content acceptance. Heisenberg
read code, test definitions and evidence; 23 test execution is Main's evidence, not
a claimed independent rerun. Main accepts these dispositions; no full-system pass.
The scope deviation is a development-process failure: keep the exact approved scenario
in the task packet and trial inputs before dispatch; do not expand paid tests by analogy.

## Focused offline coverage

Tests cover immutable receipts across reopen/reordered source IDs, foreign-project
denial, upstream write refusal, immutable input snapshot, exclusive worker lock,
bounded analysis/cache and incomplete-response rejection, actual ADK tool protocol,
save-before-failure recovery, completed-result replay avoidance, actual cancellation,
startup errors, error events, CLI exit codes, explicit feedback preserving old artifacts,
feedback rejection while running, and completion without provider credentials.
Scripted models demonstrate protocol behavior only, not autonomous semantic quality.

## Remaining limits

SQLite and in-memory SDK sessions are prototype choices. Recovery reconstructs from
durable artifacts/receipts/feedback, not an exact continuation of lost SDK conversation.
HTTP retry, no-progress detection, source-version updates, semantic retrieval, role
delegation, robust multi-user security, GUI and complete report acceptance are not done.
Only a small synthetic sample was exercised; no broad success-rate claim is justified.
The next trunk work should produce a reviewed document from a scoped project, preserve
upstream ownership, and expose progress/errors without adding mandatory micro-stages.
