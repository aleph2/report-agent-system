# Fake03 Coordinator probe — failed before page sheet

Production **+0 / −0**, tests **+0 / −0**, checks/guards changed **0**, new legacy fallbacks **0**. One owner-authorized paid launch; no retry, fix or test rerun.

GitHub main and working branch were verified at accepted **2289ce1** before launch. Run **mini-planning-20261111-01** used text-only **GLM-5.3**, a **5.5M hard cap** and full **1,179,648** request reservations. Owner-local run: **2026-11-11 22:41:21–22:42:24 America/Tijuana** (**63.321s**); UTC **2026-11-12 06:41:21–06:42:24**.

## Result and cost

**FAILED before checkpoint. No plan or page bindings were saved.** Writer, Reviewer and export did not run. This is not budget exhaustion, an unknown outcome or a page-sheet quality verdict.

| Coordinator observation | Result |
| --- | ---: |
| Paid GLM requests / decision turns | 12 / 12 |
| Settled / new held tokens | 528,712 / 0 |
| Input / output tokens | 527,472 / 1,240 |
| Provider-reported cached input, already included above | 381,952 |
| First / last / largest input | 34,010 / 54,234 / 54,234 |
| Tool calls / refusals | 12 / 1 |
| Completed native model-call seconds | 58.292 |

Runtime records count **13 logical invocations**, including the locally blocked nested vision attempt; that is not 13 paid requests. Their summed time is **58.092s**, a different instrument from callback time and wall time. Tools: one todo update, ten page reads, one refused image analysis. Cached counts demonstrate provider-reported cache use, not a price estimate or reduced ledger charge. [Machine record](../verification/fake03-planning-probe-20261111/result-summary.json), [per-call growth](../verification/fake03-planning-probe-20261111/per-call.tsv).

## Confirmed cause and next work

**P1, blocks repeating this probe unchanged:** on turn 12 the Coordinator selected `analyze_source_image` for the drawing. That offered tool uses a separately configured vision client rather than the probe's GLM-only factory. Its attempted model was `deepseek-v4.1-flash-1017`. The scoped GLM request guard raised **SCOPED_REQUEST_WIRE_MISMATCH before dispatch**; the saved admission proof shows **zero HTTP attempts admitted, one local refusal**. No unauthorized vision request was paid. Evidence path: deep_runtime.py:642–656/899 → vision.py:89–161 → token_budget.py:79–87.

**P2, diagnosis labels:** deep_models.py:69–77 rewrites the scoped refusal as `MODEL_REQUEST_BUDGET_REACHED`. The launcher keeps top-level `planning_stopped`, although its native planning result is `failed` and the process exits 1. These original records stay unchanged; this report states their actual outcome.

Before another paid run: align this probe's offered model-backed tools with its text-only GLM authority; preserve the wire guard; add an offline real-tool-path case selecting the unavailable image tool; retain the exact local refusal in diagnostics/result classification. No fix has been implemented. Parallel-read and source-result redesign remain deferred.

## Preservation and review

All **316 prior attempt rows and authorization are unchanged**, including the **1,179,648 hold**. Campaign: **2,519,772 settled / 1,179,648 held / 6,300,580 available**. The separate historical **2M hold** was not accessed or changed. All **308 pinned files** are unchanged; exact process and probe-module processes are absent. Originals, responses, case/checkpoint, diagnostics and traces remain private at `.private/mini-planning-20261111-01/` and the existing campaign run directory.

Neo independently checked accounting, process absence and the diagnostic/admission path. The frozen answer key is unchanged; page-sheet applicability and Chinese-text checks are **unmeasured**, since no sheet exists. The one-launch authority is consumed; no continuation or automatic restart is authorized.
