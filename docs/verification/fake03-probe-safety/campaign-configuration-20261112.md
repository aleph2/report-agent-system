# Campaign and run amounts from pinned authorization

Source +40/−31; checks/guards +3/−3; legacy fallback paths added: 0. Existing budget test functions added/removed: 0.

Owner requirement: an authorized verification grant must be usable without editing a campaign amount in source. Preserve all existing attempts, holds, model bounds and authorization history; a grant increase authorizes no paid launch.

- `fake_verification_budget.py`: initialize from an explicit configured campaign maximum; read existing ledgers without a fixed-amount comparison; compare the pinned expected maximum on runtime construction. Flow caps come from the run authorization and remain bounded by that campaign.
- `fake_verification.py`: consume `aggregate_tokens` from the separately SHA-pinned authority, compare the existing ledger read-only, and forward the same pin into both runtime budget branches. The one-time initializer consumes that configured amount.
- `fake_planning_probe.py`: consume the separately pinned run cap and campaign ceiling; retain scope/models, one-image full-reservation minimum, holds, single launch and page-sheet stop.
- `fake_indicator_retry.py`: forward the original campaign pin through the retained continuation budget. This changes no retry authorization or unknown-outcome policy.
- Existing invalid templates leave both amounts unset; current operator instructions require the actual authorized values. Historical proposals and verification records retain their original values.

Added checks are positive aggregate/run consistency, exact read-only ledger matching at preflight, and matching again at runtime construction. Removed checks were the fixed campaign amount, fixed probe amount, and flow amount whitelist. Existing transport/request bounds and accounting remain in force. The retained mini-assessment workflow keeps its existing separate stop-loss; this change adds no model profile or global budget framework.

Main ran six existing focused budget/launcher modules: **50 passed**. After correcting aggregate forwarding, the affected existing cases were rerun: **6 passed**. The continuation follow-up passed **6 existing cases**. Neo reviewed source, caller coverage and these logs; Neo did not independently run tests. Details and source hashes: `.private/context-fix-phase2-20261112/implementation/`.

Financial amendment, category reconciliation and exact preserved rows are private. The existing additive CAS API is used on the original campaign, with no reset or hold release. Full regression, final Phase2 candidate/tag, replay comparison and draft preflight remain pending; this record is not a paid-launch or complete-Phase2 claim.
