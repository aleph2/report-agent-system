# Step 6 — Fake03 Coordinator planning probe proposal

Production **+0 / −0**, tests **+0 / −0**, checks/guards changed **0**, new legacy fallbacks **0**. Proposal only; no spending or cap change.

## Accepted code and scope

C2/C3 accepted at **6cf4193**, source/tests identical to clean-tested **d0984f9** (6,230 passed, nine unchanged skips, zero failures). Use the accepted main revision after this documentation-only handoff; pin its exact ID with the existing `identify` command. [Acceptance](context-fix-c2-c3-acceptance-20261111.md), [operator commands](fake03-planning-probe-commands-20261111.md), [safety implementation](fake03-planning-probe-safety-20261111.md).

Proposed one launch: fresh Fake03 import; live **Coordinator planning only**, text-only **glm-5.3**; A/B; C remains a proposed exclusion until the owner's saved reply. Stop at the real owner page-sheet checkpoint or earlier budget stop, other human wait or unknown outcome. No Writer, Reviewer, export, automatic approval, retry or continuation. Frozen answer key v2 stays outside model inputs and is not widened.

## Cost and recommendation

The matched scripted Coordinator replay has **61 calls / 3,357,595 input proxy tokens / 66,851 largest request**. C2/C3 provides no material Coordinator saving. This local estimator is not GLM billing. At the same call count, adding a planning allowance of 1K–4K output/reasoning tokens per call and 0–10% more input gives roughly **3.42M–3.94M**. This is a scenario, not a bound: live steps and tokenization may differ.

**Recommend a 5,500,000-token hard run cap.** Keep the full **1,179,648** reservation per request, one in flight, and count every request against both run and campaign. Another request fits only while settled run use is at most:

| Hard run cap | Settled admission headroom, no current-run hold |
| --- | ---: |
| 3,700,000 | 2,520,352 |
| 5,000,000 | 3,820,352 |
| **5,500,000 recommended** | **4,320,352** |

The final admitted request can settle above the headroom, within the hard cap. 5.5M leaves more room above the scenario than 5M; it is a limit, not a target or completion guarantee. This recommendation does not change the existing 3.7M default.

Owning Linux read-only ledger check at **2026-11-12 06:24:50 UTC**: campaign cap **10,000,000**, settled **1,991,060**, held **1,179,648**, available **6,829,292**, **316 attempts**. A new 5.5M run fits the campaign without amendment, leaving **1,329,292** if all of it settles. The separate historical **2M hold** remains untouched; its ledger is not opened by this probe. Preserve every usage/hold row. The 100M verification total is not new launch authority. Recheck before dispatch.

## Evidence returned and next gate

Return actual per-call input/output/cached tokens when reported (otherwise unmeasured), growth and largest request; per-role/support invocations, logical turns, tool refusals deduplicated by actor/native-call ID and reason, completed logical-call time/current in-flight age; settled versus held exposure. Retain prompt/tool trace joins for cleared → actually visible re-read → saved claim; a Coordinator-only probe cannot establish Writer extraction correctness.

Compare the proposed page sheet with the fixed Coordinator key, including A/B page applicability, A-only survey, instruction/template exclusions, C's proposed status and Chinese reader-facing text. Preserve the original checkpoint/brief. No Writer call goes out while the owner has not replied.

**Owner decision still required:** authorize one Fake03 Coordinator-only planning probe with the scope/model above and **5.5M hard cap**, or choose another cap. Page-sheet confirmation and paid continuation are later, separate decisions. Real probe counts guide any later parallel-read or source-reader redesign.
