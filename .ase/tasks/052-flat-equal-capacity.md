# Task052 — separate protocol diagnosis and equal-capacity effort comparison

2026-09-30 user approved next steps after051. Main owns runner/tests and delivery;
alignment reviewer checks changed wire projection and transport boundaries, LLM/RL
specialist independently assesses public outcomes using frozen042 oracle. Stage:
risk-validation, G1 open; no production/native report promotion, author revision,
legacy write, email or private reasoning inspection. Pending043 remains untouched.

Facts:051 strict requests produced missing gap and invalid JSON, plus one high
capacity truncation. Cause of server constraint failure is unknown. Rechecked
official Tool Calls documentation2026-09-30: beta+strict is documented for thinking
mode, anyOf is supported, all object properties required/additionalProperties false.
https://api-docs.deepseek.com/guides/tool_calls/
Do not claim a documented guarantee was empirically established. First use an
offline MockTransport test to check SDK serialization/routing and preservation of
raw malformed arguments. Live request hook records only safe URL/hash/JSON equality
and strict flags, no headers, credentials, query, userinfo or private reasoning.

Candidate flat wire removes the pass/fail anyOf branches, keeps all original fields,
uses boolean passed and requires gap for every item. A passed item must have empty
gap, enforced locally; nonempty gaps are rejected, never discarded silently.
Only after full wire validation, an explicit canonical projection removes empty
passed-item gap. Raw response and wire-output remain preserved. No ID/status/text/
evidence repair; original GraderResponse consistency checks and exact IDs remain.

Predeclare maximum4 independent requests with unchanged050 messages/materials:
- A union-high131072 and flat-high131072, one each. Only tools differ. Compare
  protocol outcomes separately from semantic outputs. Flat success does not prove
  union complexity was the cause. No new semantic prompt paragraph or oracle.
- B flat-high131072 and flat-max131072, one each, ONLY if A flat passes complete
  wire and original canonical/ID validation and neither A call has API failure or
  postflight mutation. B differs only reasoning_effort. Do not gate on favorable
  semantic outcome or pool the A high with B high as an unqualified rate estimate.

All4 request files frozen before A, each own attempt path, retries0, same timeouts,
max2 in flight within each phase. No replacement samples or repair; B skipped if
the predeclared protocol gate fails. Preserve all A and B outcomes. Concurrency
and small same-fixture samples do not support latency causality, statistical
independence, generalized reliability or training claims. Report protocol validity,
O1 relation/C2 verdict, O2 control, O3 unknown/band support, C6 coverage and repair
separately. Follow-ups are Main-owned and do not start extra calls automatically.
