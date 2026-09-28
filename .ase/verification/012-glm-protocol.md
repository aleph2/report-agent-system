# Task012 protocol verification

2026-09-28. Main implements/tests; Rawls investigates installed framework;
Anscombe independently reviews implementation and scope. Outcome remains report
delivery, not a claim that provider adaptation alone fixes autonomous reasoning.

## Evidence and change

Task011 resume reached291 native messages but no committed report, again returning
identical calculate calls after the repeat observation. Main sent SIGINT to exact
PID779846. Cancellation completed and checkpoint remains at model node, no human
interrupt: `1f1bae9d-cf1f-65ce-81b4-4e1c59e1cdaf`.
The outstanding provider response may have been billed; no local result was adopted.

P2 confirmed protocol gap: ChatOpenAI1.6.6 drops GLM reasoning_content bidirectionally.
Historical raw responses are unavailable; the last8 normalized report responses show
0 reasoning tokens. Therefore lost nonempty reasoning is NOT proven as the historical
cause. Explicit thinking settings also change along with field preservation, so this
is not a single-variable causal comparison.

Added a thin GLMChatOpenAI subclass to receive/return the exact opaque string on its
corresponding AIMessage. Native checkpoint stores it; no new persistence mechanism.
Absent historical fields stay absent. Streaming/ResponsesAPI are explicitly outside
the adapter contract; disable_streaming makes normal public streaming use nonstreaming.
Configured model now sets thinking enabled, clear_thinking false. SDK retries, tools,
permissions, prompts, native harness and report sources remain unchanged.

LocalAudit strips reasoning from serialized copies and records presence/length only.
Native messages are untouched. Existing GUI event whitelist remains. Anscombe raised
a conditional P1 exposure if SDK DEBUG/external tracing is enabled. Before real resume,
Main checked openai, openai._base_client, httpx, httpcore: all DEBUG disabled; OPENAI_LOG,
LANGSMITH_TRACING, LANGCHAIN_TRACING_V2, LANGCHAIN_TRACING unset. The trial launcher
explicitly sets both modern tracing flags false. This is a verified local execution
condition, not a claim that arbitrary future DEBUG/tracing configurations are safe.

## Validation

- First focused test run:45 passed in5.05s (new protocol plus deep_models).
- Integrated focused run:71 passed in62.19s (protocol/models/native runtime).
- Exact string/empty/missing preservation through mocked SDK, native checkpoint
  close/reopen and outbound payload; old missing-field assistant; tool IDs/order;
  multiple distinct messages; audit omission without mutation; unsupported path errors.
- The manual summary placeholder case only tests retained-field mapping, not native
  summarization. Rawls is adding a focused real-middleware offline test separately.
- Full regression completed:554 passed,9 skipped, one historical ADK experimental
  warning in153.08s. Separately added native-summary test is not included in this count.

Six authorized synthetic requests total, serialized, no engineering materials:

| Probe | Observed result |
| --- | --- |
| `.runs/task012/protocol-probe` raw default first turn | Two rounds returned empty reasoning strings and0 reasoning tokens. Tool call then final answer. The first script's strict whole-content equals42 flag was false; no answer-correctness claim rests on it. |
| `.runs/task012/protocol-complex` raw explicit settings | Includes old assistant without field. First reasoning571 chars/229 tokens, second42 chars/9 tokens. One add call, then final answer containing16. |
| `.runs/task012/adapter-probe` actual configured adapter | First409 chars/166 tokens, second38 chars/9 tokens; one add call then final answer containing16. Native serializer round-trip and exact outbound equality asserted. |

These probes confirm local wire compatibility, not complete schedule correctness or
autonomous convergence. The synthetic prompt explicitly asks not to repeat checksum;
do not treat it as proof that the report's repetition is solved. Raw reasoning never
printed or persisted by raw probes; adapter checkpoint field audited by metadata only.

Anscombe accepts thin-adapter design with the verified local logging condition.
Native summary intentionally replaces a prefix; preserved suffix messages retain
fields per installed-source review. Full-history continuity and actual provider use
of clear_thinking are not established merely by200 responses. No historical blocks
can be reconstructed. A single original-checkpoint continuation will test trunk gain.

## References

- https://docs.z.ai/guides/capabilities/thinking-mode (checked2026-09-28)
- https://docs.z.ai/api-reference/llm/chat-completion
- Installed langchain-openai1.6.6 base.py and DeepAgents0.7.19 summarization source.
- `.ase/verification/011-glm-protocol-observation.md`

Final report generation, content review and export QA remain pending.

Original task resumed once after adapter validation. Events606/611 still returned
empty reasoning fields and calculate. Event616 returned a nonempty field (16875
characters, metadata only in event audit) followed by eight calculate actions in
total through645. This confirms actual-report protocol use, not resolution of the
repetition or correctness of selected inputs. No committed result yet at647.

Further trunk gain: first report draft `000dde5e-c3c7-4079-93f9-5bffced10335`
saved after647,21424 characters. The coordinator delegates to reviewer at661;
reviewer reads project_status then previews that report at668. Independent held-out
content review and first-draft visual QA were dispatched after the actual saved draft.
No held-out defect list was fed to runtime. This demonstrates progression beyond the
loop after the combined changes, not attribution to any single change.

Rawls added `tests/test_glm_native_summary.py`:2 passed in5.75s. Tests execute the
native middleware with a fake summary model, serialize/reconstruct its actual event,
exercise tool-pair boundaries and retained fields. Anscombe confirmed the scope:
not a full build_agent/SQLite summary restart test or live summary-quality claim.
