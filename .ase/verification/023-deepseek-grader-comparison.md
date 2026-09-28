# Task023 DeepSeek grader comparison verification

2026-09-28. Main implementation/tests/integration; independent alignment_review
design/code review and postrun_review content assessment. User-requested model
comparison under existing paid/mail authorization. No legacy service changes.

Provider model listing confirmed deepseek-v4.1-flash on the existing endpoint.
Added explicit grader-only model override; coordinator/writer/knowledge/reviewer
roles retain GLM. Native DeepSeek selection is restricted to a fresh isolated review
fork and recovery binding, preventing reuse/relabel of previous GLM approval.
Exact targets also record grader_model. No prompt/rubric/tool/agent-loop changes.

Protocol differences: DeepSeek uses enable_thinking=true rather than GLM's
thinking.enabled/clear_thinking=false, and max_tokens instead of LangChain's
max_completion_tokens mapping. Both use high,65536output,nonstreaming,
parallel_tool_calls=false, unset temperature/top_p/seed, existing timeouts/retries.
These are provider-compatible settings, not identical reasoning compute.

76 relevant tests passed24.19s; one existing Rubric beta warning. Offline tests
cover explicit role routing, invalid models/no fallback, exact wire keys, opaque
reasoning tool-turn roundtrip, safe audits, old approval preservation and recovery
model mismatch, alongside existing native feedback/import regressions.

Real synthetic smoke14:08:25.310–14:08:30.298 UTC: deepseek-v4.1-flash,
2responses/2230tokens. lookup_checksum executed once; native typed GraderResponse
satisfied supported by returned42. No report/source data. This confirms transport,
tool continuation and schema on this endpoint, not report-quality capability.
Private protocol reasoning is preserved for transport and excluded from public audit.

Controlled and native report results pending. Both must retain Task022 failures as
the reference; do not imply a better model merely from passing this protocol smoke.
