# Fake03 full-flow launch proposal — no spending authority

Production source +0 / −0; tests +0 / −0; runtime checks/guards +0 / −0; fallback changes 0. This is a proposal, not an executable paid launcher or an authorization.

## Accepted baseline

The owner accepted the integration and supplied its code/key review in chat. Main was fast-forwarded from `14484f8` to **`7da4f94`**, with no rewrite. Source/tests equal clean-tested `f35ea76`: 6,196 passed, nine unchanged skips, zero failures. No duplicate independent review is required by this proposal. The old failed full run stays failed and preserved.

Frozen verifier: [answer key v2](../verification/fake03-post-9a/answer-key-v2.json), [manifest](../verification/fake03-post-9a/manifest-v2.json). It stays outside model inputs and cannot be widened after a paid result. Scope is the live Coordinator → saved owner page-sheet reply → fresh per-indicator Writers → independent Reviewer → draft Word/Excel, A and B only. C is a proposed exclusion until the saved owner reply confirms it. Six numeric positions stay unscored; formal release is out of scope.

## Measured cost and proposed cap

Main replayed the existing complete scripted-flow test with a local request-size counter. Both focused runs passed; provider calls/tokens were **zero**. `cl100k_base` counted compact JSON messages and tool schemas. This is a **proxy**, not GLM's serving tokenizer, hidden reasoning, provider framing or a certified request bound. Two passes estimated 6,775,180 and 6,785,599 input tokens (0.15% apart; dynamic IDs differ). Repetition checks consistency, not calibration to GLM.

| Role/service | Offline calls | Input-token proxy | Median / largest input |
| --- | ---: | ---: | ---: |
| Coordinator | 61 | 5,028,850 | 82,381 / 119,902 |
| Writer | 39 | 659,958 | 6,432 / 63,729 |
| Writer support (`text_tool`) | 3 | 16,864 | 5,763 / 5,817 |
| Reviewer | 48 | 1,069,508 | 22,424.5 / 41,398 |
| **Total** | **151** | **6,775,180** | |

The scripted replies total only 17,542 proxy tokens and are **not** a realistic allowance for live reasoning. Assuming 1K–4K output/reasoning tokens per live call and 0–10% more input gives a planning range of **6.9M–8.1M tokens**, conditional on similar call counts and tokenizer behavior. Live loops or different tokenization can exceed it. No dollar figure is claimed without a pinned service tariff. [Measurements](../verification/fake03-post-9a/launch-cost-estimate.json).

The Coordinator is the cost driver. In the diagnostic repeat, its request grew from 33,688 to 120,081 proxy tokens and from four to 184 messages; the tool schemas contribute 18,702 each time. At the final call, human-message content contributes about 45.5K, retained source-page results 17.2K and retained planning-draft results 11.8K. This proves large repeated inputs, not an engineering-judgment failure. Merely deleting old history does not prove that 3.7M will suffice: static payloads and call count also matter.

Read-only campaign snapshot, **2026-11-11 21:11:49 UTC**: maximum 10,000,000; settled **1,991,060**; held **1,179,648**; available **6,829,292**. The held Run 04 request remains held. The separate historical 2M hold remains untouched. The 100M verification aggregate is a ceiling, not a fresh balance or launch permission.

**Recommendation:** keep spending stopped and first reduce/re-measure the repeated Coordinator context offline, without changing the key, judgments or evidence access. Then recompute the cap; retaining 3.7M is not promised. If the owner instead chooses to test the unchanged flow, the concrete alternative is **10M per run and an explicit campaign amendment from 10M to 14M**, within the 100M aggregate after reconciling its remaining balance. Preserve all previous usage and holds. This is a proposal only: 3.7M/10M remain the actual limits until separately authorized and implemented.

| Opportunity | Explanation and why it works | Estimated savings at 151 calls | Implementation effort | Risk to output quality |
| --- | --- | ---: | --- | --- |
| Reduce repeated Coordinator context using existing framework facilities | Remove superseded operational state and duplicate payloads while retaining usable evidence, current plan and qualifiers | Unmeasured; Coordinator's 5.03M proxy input is the measured target, not guaranteed savings | Separate bounded offline change and replay | Lost evidence/comparisons; unchanged key and saved-row checks must hold |
| Keep full-model reservation | Avoid claiming an uncertified tokenizer estimate is a hard bound | **0** token savings; reservation headroom is disclosed below | Existing hook reuse | Budget may stop before completion; explicitly reported |

Track tokens and output quality together; do not optimize by weakening the fixed key. [Langfuse cost-analysis guidance](https://langfuse.com/academy/experiments/cost-optimization).

## Shared budget: required behavior before any paid launch

Use one persistent existing campaign ledger and **one run ID** for every Coordinator, Writer, Reviewer and support request. Charge `text_tool`, summary and any authorized vision support to its parent role. Do not give each model/role a separate grant. Proposed service scope is the existing verified text-only `glm-5.3` for all model calls, subject to the final owner's model/scope approval. No extra model comparison.

Keep the full verified reservation **B = 1,179,648** per request. No proxy estimate lowers it. Admission checks, in the existing atomic reservation transaction:

`run_settled + run_held + B <= approved_run_cap`

`campaign_settled + campaign_held + B <= approved_campaign_cap`

The request settles to trustworthy provider usage; the full bound remains held on an unknown outcome. The bound is not multiplied by 151: completed requests settle before the next one. Admit at most one new in-flight request; the specifically preserved historical hold is never released, reused or retried. A new unresolved request stops the run.

At 3.7M, a new request fits only while run settled usage is at most **2,520,352** with no current-run hold. The campaign independently leaves **5,649,644** new settled tokens before another full reservation cannot fit. Both are below this proxy estimate. With the proposed 10M run cap, its settled admission headroom becomes **8,820,352**; the proposed 14M campaign would cover existing exposure plus the new 10M run (13,170,708 total). These figures are admission arithmetic, not promises of completion.

After planning, persist the same run/counters and wait. No Writer request or other model spending occurs while the owner page sheet is unanswered. The trusted completion command consumes the saved reply under the same authority/counters; it creates no fresh grant and never replays a failed/unknown paid action. SDK and application replay of unknown calls remain disabled.

## Refusal capture and delivery

Record **every tool attempt and refusal from the real trace**, across roles, before aggregating: run, authenticated actor/role, task/decision-turn ordinal, native tool-call ID, tool, reason codes, field/site when available, and outcome. Deduplicate rejected calls by run + actor + native call ID; multiple reasons may overlap but count as one rejection. Keep missing-attribution rows for reconciliation, never guess. Keep model/provider failures, local budget denials and owner revisions separate from tool refusals.

Reuse LangChain callbacks and the existing inventory capture logic; cover exceptions **and** `ToolMessage(status="error")`. Persist private append-only evidence across the owner checkpoint and crashes. Rebuild c's static inventory for the exact launch revision; join observed reasons/sites to it and retain zero counts separately from unmeasured coverage. Classify each real refusal as catching a real error, interface/bookkeeping friction, or unresolved. No automatic check deletion.

Return per-role settled/held tokens, invocations, tool rejections, decision turns, completed logical-call seconds and in-flight age. Attribute support to its parent; `text_tool` is a service. Developer-agent usage is unavailable unless measured. Also return saved rows/quotes, gaps, fixed-key mismatches, Chinese text reviewed field by field, Reviewer findings, and draft Word/Excel from one snapshot with hashes/rendered preview. If a content check refuses, report its exact missing requirement without weakening it.

## Implementation gate and exact next work

No runtime change has been made in this proposal. Before launch:

1. Choose context reduction first (recommended), or the larger-cap unchanged-flow alternative. Any context change gets its own short file/change list and offline evidence; do not alter the dispatcher or key.
2. Bind the trusted full-flow route in `fake_verification.py` to `fake_draft_flow` and the shared budget. Reuse the existing launcher; the historical Writer-only scope remains explicit, not relabelled. Extend `fake_verification_budget.py` only as required for the **approved** per-run/campaign limits, preserving historical rows/caps and the one named hold. Reuse `TokenBudget.increase_authorization` for an authorized campaign amendment; never initialize a fresh ledger to obtain headroom.
3. Reuse/extract the existing inventory callback through the runtime metrics boundary for live capture; remove any duplicated observer logic made unnecessary. Readers are the private run summary and c's measured sweep. No Langfuse SDK/service, credentials or upload is needed/configured.
4. Focused tests through the real operator boundary: all roles/support share one cap; exact reservation boundary; concurrent requests cannot overspend; campaign usage/holds survive; unknown outcome stops without a replay; saved owner checkpoint blocks all model calls and continues on the same counters; refused exception/error-message recorded once with role/reason/native ID; restart of the observer does not duplicate counts; key stays out of model inputs; full scripted path still yields the draft pair. Tests use disposable synthetic ledgers, never the live campaign.
5. Publish code, focused evidence, exact operator commands, model/config pins and final estimate/cap for review. Any further full regression needs its own owner authorization. Only then request **one paid launch** naming Fake03 full flow, A/B, C exclusion through the saved checkpoint, model scope, run/campaign caps and preserved holds. No launch command is represented as ready now.

Private evidence: `.private/fake03-launch-preparation-20261111/`. Two local measurement setup failures (cache path and pytest parameter ID) were retained before the successful focused measurements; no provider request or application fix resulted. Passing pytest case data was automatically removed; zero temporary case databases remain.
