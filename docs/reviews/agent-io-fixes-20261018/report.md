# Two I/O lifecycle repairs and the responsibility coverage plan

This batch implements the two repairs authorized after the sibling regression exercise. Codex implements; Neo reviews source, execution evidence and scope. The broader C1/task-context refactor remains paused. The 44-responsibility matrix is a coverage plan, not evidence that all responsibilities have passed.

## Boundaries explained before implementation

| File | Change | Preserved boundary |
|---|---|---|
| `src/report_agent/artifact_review.py` | Link the artifact operation reservation to its raw analysis reservation; expose a proven local refusal on replay. | Existing snapshot/owner/material checks, immutable successful review reuse and historical unresolved placeholders. |
| `src/report_agent/evidence_analysis.py` | Separate parent state propagation from permission to readmit an operation. Artifact calls disable readmission; existing Writer callers retain their default. | A different artifact operation ID cannot silently cause another model request. Original raw proof and previous parent remain unchanged. |
| `src/report_agent/working_summary.py` | Capture the real logical-request admission proof and distinguish zero-dispatch refusal from unknown outcome; preserve the original reason when replay is blocked. | Original history, policy scope, all existing replay blocks, model parameters and summary prompt. No new recovery entry point. |
| `tests/test_artifact_io_lifecycle.py` | Retain the original red case and add legacy, unproven-budget, new-ID and outer-cancellation counterexamples. | Real configured SDK hooks with offline HTTP transport; no provider contact. |
| `tests/test_summary_io_lifecycle.py` | Retain the original red case and add unproven-budget and already-sent-before-refusal counterexamples. | Fake model or offline SDK transport; actual stored failure and unchanged history are checked. |

No production prompt changes, model/provider changes, paid report execution, OCR, learner job, publication, email or historical-data migration are included. This repair does not release unknown token reservations.

## Root causes and dispositions

**NFR-05, P2 — inconsistent nested operation state.** The raw analysis knew a request was refused before dispatch, but the artifact parent retained only a request hash. Parent replay interpreted the missing result as an unknown provider outcome. Sharing parent propagation without separating readmission would also have exposed a retry capability this artifact caller did not previously have. The fix propagates the actual admission proof while keeping readmission disabled. A new ID referencing an existing refusal records `proof_origin=prior_raw_receipt` and `new_provider_attempt=false`; it does not claim a fresh admission event.

**NFR-10, P2 — summary failure classification discarded known evidence.** The exception boundary labelled every exception `SUMMARY_OUTCOME_UNKNOWN`. It now uses the actual admission hook to establish `SUMMARY_NOT_DISPATCHED`. A budget-like exception without that proof, a failure after an admitted request, timeout, and outer cancellation remain protected as unknown. Both known refusal and unknown failure still block replay in the same summary-policy scope. This batch fixes classification and visibility, not the entire recovery policy.

## Exactly what the 43 focused tests mean

All 43 are offline. They combine scripted fake models, real SDK admission hooks with `httpx.MockTransport`, and deterministic store/identity checks. None uses fake data to call a live LLM. They do not cover all 44 responsibilities.

| Retained test file | Cases | What is checked |
|---|---:|---|
| `test_artifact_io_lifecycle.py` | 5 | Zero dispatch versus dispatched timeout; current/legacy unresolved state; unproven budget exception; host cancellation; same/new-ID replay. |
| `test_summary_io_lifecycle.py` | 4 | Zero dispatch, timeout, unproven budget exception and refusal after an earlier HTTP send; original history and replay blocks. |
| `test_bounded_artifact_text_work.py` | 4 | Exact owned judgment, cache reuse, invented/foreign receipts, missing pages and partial completion. |
| `test_not_dispatched_recovery.py` | 8 | Atomic linked state updates, existing Writer readmission, vision refusal, diagnostic failure, exact bindings and post-admission budget errors. |
| `test_bounded_deadline.py` | 6 | SDK deadline reaches native tool observation; same/new-ID replay; held budget; outer cancellation and unrelated exceptions. |
| `test_summary_context_provenance.py` | 5 | Current feedback/task context, historical-note provenance, unchanged history and trigger, no clearing unknown state with new feedback. |
| `test_summary_recovery.py` | 5 | Exact recovery after compaction, incomplete preview limits, ownership and unknown outcome across restart. |
| `test_case_context_policy.py` | 6 | Empty/valid summaries, retry ownership, isolated model configuration and preservation of old failed policies. |

The separate preceding experiment made four real-model calls (Writer first decision, Reviewer first decision, and two independent text-tool outputs), recording 46,603 tokens. That evidence is reused, not rerun here. Neither its four calls nor these 43 tests establish complete agent-duty coverage or report quality.

## First-run failures retained

`focused-first` contains 41 passes and two failures in added tests. The summary test omitted the explicit token counter required by its `RunnableLambda` fixture; the existing fixture pattern corrected that setup. The artifact test raised `CancelledError` inside the mock transport, which exercised a different LangChain branch from host cancellation. The intended host-cancellation test now cancels the outer task after observing an actual offline dispatch.

The internal-cancellation finding is preserved in `internal-cancellation-candidate.json`, including installed versions, relevant `BaseChatModel.agenerate` source and the original failed trace. In langchain-core 1.6.5 the injected internal cancellation was surfaced as `AttributeError`. Its reachability and effect in real provider operation are not established. It is not silently counted as a passed cancellation path, and this batch does not alter framework code.

`focused-final` records 43 passes. The broader retained suite then passed **149 unique cases**, including all 123 previous cases and 26 additional cases. A final nine-case repeat verified the narrowed, read-only lifecycle trace capture; those nine are not added to the unique count. Product source was identical across the broad run and the final trace run. Both runs attempted no external network connections, and the production authorization plus all 1,032 budget-attempt rows remained exactly unchanged.

The exact case list, source/test hashes and budget comparison are in [verification.json](verification.json). The actual saved states and lifecycle events extracted from the final JUnit properties are in `../../../.analysis/agent-io-fixes-20261018/lifecycle-state-trace.json`; native fake-model inputs/outputs remain in the run directories. Neo's final independent disposition is in [neo-review.md](neo-review.md). Preserve all prior failed and passing runs.

## Coverage and agent-centric testing

See [Neo's 44-responsibility matrix](responsibility-coverage.md) for each duty's existing evidence and remaining gaps. Its organizing unit is the responsibility: goal and input, available evidence, allowed decisions, tool handoff, saved output and truthful return. Interface, protocol-path and independent-condition coverage measure those responsibilities. Valid alternative action sequences remain acceptable.

Use fake models to test the program's treatment of actual inputs/outputs, selected real-model synthetic cases to test decisions and structures, and real saved objects/files to test effects. New failures become retained regression examples. A passing script cannot prove model semantics, and a structurally valid response cannot prove a correct report.

This follows the official discussion of [Deep Agent single-step, full-turn and state/artifact evaluations](https://www.langchain.com/blog/evaluating-deep-agents-our-learnings). The official [agent evaluation guidance](https://docs.langchain.com/langsmith/evaluation-approaches) also notes that multiple valid trajectories can make exact sequence matching too restrictive. Existing pytest, native graph, scripted models and offline HTTP fixtures are sufficient for this batch; no additional evaluation service is introduced.
