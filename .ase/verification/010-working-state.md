# Task010 verification: local working-state transition

2026-09-28. Main implemented and ran tests. Anscombe
(`01a0e33c-c20e-7493-b090-1912cc5cf60f`) independently reviewed the design,
actual changes and all final probe artifacts, read-only, with no paid calls.

## Change and framework reuse

Only production change: six lines of coordinator guidance in deep_runtime.py.
Keep adopted inputs/rules/results and remaining work in native todos or scratch
notes; choose useful granularity and reuse still-applicable results. No fixed ledger
schema, next-tool rule, automatic semantic state transition or additional agent.
All existing tool, ownership, checkpoint and final-review behavior is unchanged.
The repeat guard is unchanged. No GUI restart, deployment or Task009 recovery.

Official references checked against installed DeepAgents 0.7.19/LangChain 1.4.2:
- https://github.com/langchain-ai/docs/blob/main/src/oss/deepagents/overview.mdx
- https://github.com/langchain-ai/docs/blob/main/src/oss/langchain/middleware/built-in.mdx

Native TodoListMiddleware supplies planning guidance/tools and explicitly advises
direct completion of simple tasks rather than unnecessary todos. StateBackend and
AsyncSqliteSaver already persist working files/state. No equivalent infrastructure
was added. Provider adapter hash stayed
98c0b0057b4a98158d508b0bb9bd4dfac8a8808f2a3148d3adc0eb05357c6c41.

## Offline evidence

Command (WSL, project venv):
`python -m pytest tests/test_deep_runtime.py tests/test_deep_models.py tests/test_calculations.py -q`

Final result: **66 passed**, 54.74 seconds. New test uses a scripted model through
the native runtime to calculate, write a scratch note, update todos, reopen the
checkpoint and verify the original observation, note and todos. It also checks the
guidance is in the effective system prompt. This is protocol, not autonomy evidence.
Two earlier executions had 65 passes/one test failure due to new test assertions:
joining a string as lines and stringifying content blocks instead of reading their
text. Assertions were corrected; no production behavior was changed to pass them.

## Real-model local comparison

Existing authorized GLM5.3 service, `reasoning_effort=high`, unchanged adapter and
tools, serial execution, no real engineering inputs. Synthetic historical tool
messages contain actual deterministic calculator outputs, not paid agent calls.
Both prompt variants use the production build_agent and full tool registration.
Only the candidate adds WORK_STATE_GUIDANCE. No test grader is supplied to agents.

Task: save an interim synthetic cost comparison, not final report delivery. A is
10*0.6+20*0.4=14; B originally 30*0.6+40*0.4=34. The changed-input case contains an
explicit human correction of B's second value to45, making B=36. Nothing prescribes
the next tool. Native tool-boundary interrupts allow external observation only;
the experiment stops at first saved draft, not after final todo cleanup/review.

Final evidence: `.runs/task010/native-state-comparison/<case>/`
(`state.db`, `checkpoints.db`, `probe-result.json`, `checkpoint-observation.json`).

| Case | New calculate calls | Model responses | Observed result |
| --- | ---: | ---: | --- |
| Baseline reuse | 0 | 2 | Marks totals complete, saves A=14/B=34 draft |
| Candidate reuse | 0 | 2 | Marks totals complete, saves A=14/B=34 draft |
| Baseline corrected input | 1 | 5 | Recalculates B=36, updates todos, saves correct draft |
| Candidate corrected input | 1 | 3 | Recalculates B=36, records corrected B=36 in todo, saves correct draft |

All four drafts contain the adopted inputs, formula, totals and source reference.
All projected message/todo/file states match after closing/reopening the checkpoint.
No scratch files were written in these live cases. Candidate changed-input sequence:
calculate -> write_todos -> submit_result. It did not recalculate unaffected A.
Baseline changed-input submission initially missed a required argument; normal
tool-error feedback let it correct and save the draft. This is an observed contained
P2 tool-use error, not evidence of systematic efficiency improvement by the prompt.

High reasoning was requested throughout, not guaranteed per response. Final candidate
changed case has one positive reasoning-usage response (37 tokens); the other final
responses report zero. No internal reasoning text is needed for these observations.

## Preserved preliminary attempts

`local-state-comparison` contains four earlier live cases (9 total model responses).
All reached drafts; candidate changed case wrote todos and recovered from a nonexistent
result-ID error (`RESULT_NOT_IN_PROJECT`, P2, contained by tool feedback). However the
initial todo was supplied via ainvoke input and ignored because PlanningState.todos
is OmitFromInput. These cases do not prove continuation from an existing coarse todo.

`seeded-state-comparison` contains a failed fixture initialization and zero model
responses. Default aupdate_state also did not establish the intended state; a
pre-call assertion detected this. No provider retry or old task recovery occurred.

The final harness uses aupdate_state(..., as_node="tools"), asserts todo persistence
before any model call, and supplies matching synthetic historical todo messages.
This fixes the test fixture only. Preliminary evidence was preserved, not relabeled
as successful validation of the final fixture. Total live responses across attempts:21.

## Independent review and disposition

Anscombe: minimal guidance is acceptable under C25; no mandatory micro-workflow or
hidden acceptance criteria. Both matched cases pass the local reuse/invalidation and
draft-progress check. Main accepts these findings and keeps the concise guidance.

Limits retained:
- Baseline also passed; no causal improvement or reliability rate established.
- Todos contain only part of the adopted result ledger. Inputs/rules/totals are also
  in the saved draft and messages; the test does not establish a complete independent
  working ledger or reliance on todos rather than message history.
- Reopening proves persistence, not autonomous continuation after recovery.
- Stopping at first draft leaves draft-saving todo in progress; cleanup was not tested.
- Short synthetic context does not reproduce Task009's approximately132k-token tail.
- The P2 custom repeat-guard defect remains open. It blocks claims that repetition
  recovery is fixed, not this isolated local test. Main must address it separately;
  no guard, quota or additional controller was added or removed here.

Disposition: this local change and verification are complete. Do not claim the real
report is repaired/completed, do not automatically rerun Task009, and do not impose
a fixed ledger or mandatory bookkeeping gate based on these samples.
