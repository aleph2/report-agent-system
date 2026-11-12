# Fake03 planning probe — safety candidate

Production source +384 / −7 (net +377); tests +327 / −8 (net +319). Explicit rejection sites +14 / −0; one fallback retains the accepted 3.7M limit for unregistered Writer-only run IDs. No dependency, prompt, dispatcher, S2, scoring or export change. No tests retired.

## Owner scope and implementation

The owner selected the **probe path**, superseding the earlier suggestion to optimize context before measuring live behavior. This package adds no spending authority. Main stays accepted `7da4f94`; this candidate is for review.

| File | Requirement and reader |
| --- | --- |
| `fake_verification_budget.py` | One existing campaign ledger and run ID for all roles. The existing atomic reservation transaction binds the selected cap and authority; the old hold and the campaign cap still count. Both current budget readers recognize the shared trigger. Existing Writer limits remain unchanged. |
| `fake_planning_probe.py` | Explicit `identify/prepare/check/run` operator entry. Fresh case without saved facts, plan or approval. Same text-only GLM, full 1,179,648 reservation; HTTP hooks admit only Coordinator requests. It stops for the actual page-sheet route or reports a different human wait, cap stop or unknown outcome. A claimed run cannot be replayed. |
| `tool_trace.py` | Native LangChain callbacks feed the private refusal/usage report: authenticated task identity, native IDs, reason codes and supplied diagnostics, validation fields, per-call provider usage/time and unfinished calls. Error messages without a BaseTool callback are included. Checkpoint interrupts, budget denials and model failures are separate. |
| `fake_verification.py`, test helpers | Reuse existing pinned authority/comparison validation. Old callers retain their default workflow/cap. Extract only the scripted planning helper used by the operator-boundary tests. |

The shared budget primitive accepts every role under one run; the **probe command** admits Coordinator HTTP requests only. Constructors for other roles may be needed by the existing graph, but their HTTP requests are refused before reservation/dispatch. There is no Writer, Reviewer, export or continuation action in this command.

## Verification

Main ran **105 focused tests, all passed**, no skips, in **4m12s** (4m17s including the wrapper) on the frozen source/test hashes. All 105 collected nodes ran once. The live campaign still has the same 316 rows and authorization.. [Detailed record](../verification/fake03-probe-safety/focused.json). All tests use synthetic ledgers and intercepted model transport. They prove accounting and plumbing, not live judgment quality or real token counts. Red/green evidence stays private.

- Exact 3.7M/5.5M admission boundaries, shared role accounting, one in-flight request, original hold, 10M campaign cap, changed authority refusal and reopen behavior.
- Real native Coordinator graph through the production SDK/HTTP hooks reaches 22 proposed page bindings, with no owner decision or delegated Writer. A deliberate incomplete-plan refusal is captured once. Unknown outcome retains the new full hold and stops; repeat launch refuses. A premature Writer request reaches no transport.
- Live callbacks cover raised errors, returned errors, validation and unavailable tools. Native IDs deduplicate; unattributed records and partial log lines stay visible. Normal `GraphInterrupt` is a checkpoint, not a refusal. Local admission denials do not count as provider failures.
- Removing the Coordinator-only request guard in a disposable mutation copy permits a forbidden request and fails the test. Canonical source is untouched by the mutation.
- The accepted Writer-only route still works after installing the shared trigger. No cap/hold protection was removed to achieve that.

Per-call `tool-trace.jsonl` supplies the usage-growth curve; `model_calls` is the logical invocation count, including denied/failed invocations. `provider_usage_calls` counts responses with measured usage, not unknown outcomes. Existing `runtime_metrics` supplies purpose-based decision turns and supporting-call accounting; absent usage remains unavailable. Refusal summaries count one run/actor/native ID with overlapping reasons. Chinese text and bindings are reviewed against frozen v2 after the real probe; no regex-only language pass or automatic widening of the key.

## Review and launch gates

[Exact commands and authority template](fake03-planning-probe-commands-20261111.md). The template's null cap is deliberately invalid. Neither 3.7M nor 5.5M has been selected or applied to a live run. The existing 10M campaign, its 1,179,648 hold and the separate historical 2M hold are unchanged; this command never opens the rescue ledger.

Historical safety-candidate status above is superseded by the [accepted C2/C3 handoff](context-fix-c2-c3-acceptance-20261111.md): the clean full regression passed, and context repairs are included in accepted code. The [Step 6 proposal](fake03-planning-probe-step6-20261111.md) still requires separate owner launch scope/cap authority. Later continuation needs separate authority; this package cannot continue from the checkpoint. No campaign amendment was implemented.

Private evidence: `.private/fake03-probe-safety-20261111/`. The old failed `cd48c0a` full run and the accepted clean `f35ea76` result remain separate and intact.
