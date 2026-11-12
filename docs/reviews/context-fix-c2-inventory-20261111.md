# Context fix C2 — Step 3 reviewed inventory

Production **+0 / −0**; runtime checks/guards **+0 / −0**; new legacy fallbacks **0**. Inventory only; no C2 middleware, catalog filter or summary change. Main remains **7da4f94**.

**Matched baseline:** identical V1 observer, estimator and 151-call scripted flow passed on **ead8bf5** and C1 **346f1ba**. Coordinator: **3,799,615 → 3,357,633 proxy input tokens, −11.6%**, 61 calls each. Catalog unchanged at **23,767/call**. System component **1,235 → 1,173** reflects C1's shortened state explanation; role prompt files are unchanged. These are local estimates, not provider usage. [Measurement](../verification/context-fix-c2/same-estimator.json).

**Proposed shared stock policy:**

- ContextEditingMiddleware/ClearToolUsesEdit runs **before TaskContext tail injection**, or before standalone boundaries. Neo reproduced two tails with the opposite order. Preserve call arguments/IDs; use the generic placeholder.
- Only successful immutable results with an unchanged recovery reader **still offered** qualify. Frozen Reviewer rows and path-qualified page/index reads are candidates. Stock exclusion is by name: any error/unproved variant excludes that whole name for that request. Optional model selection must prove final availability or clear nothing. [87-tool inventory](../verification/context-fix-c2/tool-inventory.tsv).
- Preserve writes, paid/model results, receipts, mutable heads and all indicator-Writer evidence. Delete both bespoke preview/identity clearers by excluding **all read_tool_observation and commit returns**. Keep summary_recovery.capture, exact recovery, delivery/image/ownership/range checks.
- Reviewer has one growing session per slope; prose Writer one across all sections. Prose growth is dominated by the mutable current-plan read, so this replay proves **no prose C2 saving**. Native delegated context/filesystem tools exist, but their sessions are unmeasured. [Per-path policy](../verification/context-fix-c2/session-policy.tsv).
- Eligible-result upper bounds: source pages **563,692**, frozen Reviewer rows **452,058** proxy tokens. Mutable planning drafts **326,142** and prose current-plan reads **174,909** stay excluded. These are contributions, not savings. [Breakdown](../verification/context-fix-c2/result-contributions.json).

**Catalog proposal, separately scoped:** eleven actual-absence predicates yield a hypothetical **23,767 → 20,852** schema estimate. **Keep task offered:** Neo reproduced legal generic-Writer admission without plan/snapshot/task; a Reviewer can also resolve saved_work into its first snapshot. Keep planning edits after publication. Default-off NativeToolSelection is a paid model selector, not deterministic filtering. [Predicates/readers](../verification/context-fix-c2/catalog-eligibility.tsv). Trimming is beyond original Step 4; this inventory does not authorize its implementation.

| Step 4 files | Addition/removal; requirement and reader |
| --- | --- |
| Existing context/middleware extension | One stock-edit policy for Context Fix C2; read at request assembly |
| task_context.py / metadata_observations.py | Delete old clearing/restoration and dead identity helpers; keep recovery/capture checks |
| deep_runtime.py / fake_draft_flow.py | Wire before native tail/standalone boundaries; no dispatcher routing/scheduling changes |
| Focused context tests and replacement map | V3 actual clearing/one tail/pairing/history/exact re-read/exclusions; V4 wrong and correct quotes plus six defects/ten controls; V5 stable prefix; V7 actual summary-threshold crossing |

Stock's nearest-preceding-AI matching can skip a result after an intervening note; V3 must prove real-stack clearing. Context thresholds are measured during TDD, not spending caps. Summary trigger, S2, scoring, exports, originals and financial records stay unchanged.

**Evidence/review:** Main's paired replays passed (45.36/43.56 s); separate contribution replay passed (163.90 s), network blocked and source trees unchanged. Neo ran four in-memory placement/pairing assertions and one disposable generic-Writer counterexample, then accepted this corrected technical inventory. Both disposable passing copies were cleaned; captures/logs remain private. No runtime replacement coverage is claimed.

**Authorized full run:** frozen C1 **346f1ba** finished **6,206 passed / 3 failed / 9 unchanged skips**, 36m30s. Failures were retired frame assertions/census rows; corrections **a412688 / 3eeb5e6** pass six focused checks, reviewed by Neo. The full run remains failed; it was not restarted. [Result and diagnosis](context-fix-c1-full-20261111.md).

**Unmeasured:** provider/cache behavior, C2 or catalog-filter savings, delegated-session sizes. No paid probe or main move; Step 6 sizing follows the final measured candidate.
