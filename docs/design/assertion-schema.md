# S2 assertion contract for owner review

**O3 approval, 2026-11-08.** The owner approved the vocabulary, C1–C12 and action catalog on condition that there was no new S2 finding. Independent replay verified the corrections and 19 offline contract tests passed. No S2 finding remained open at acceptance. The approved executable contract files are the versions introduced in `63dbb0f`. Runtime implementation is S3.

The owner confirmed that Stage 1 preserves the current dispatcher. The assertion contract governs actions on records. Task selection, dispatch order, retry scheduling and Coordinator wake-up belong to the later task-store phase.

## Review files

- [Pydantic vocabulary](../../src/report_agent/assertions/schema/kinds.py)
- [SQLite refusal queries](../../src/report_agent/assertions/schema/checks.sql)
- [Action and authority catalog](../../src/report_agent/assertions/schema/actions.json)
- [Proposed guideline representation](../../src/report_agent/methods/high_slope_guideline.assertions.proposal.json)
- [Offline contract examples](../../tests/test_s2_assertion_contract.py)

## What survives a task

Each assertion has an immutable ID, subject, typed claim, grounds, attributed actor, generating task, operation ID, observation time, recording time and both contract versions. A ground cites an assertion ID and names the particular proposition it supports in classification, assumption, adjustment, context or calculation. A source version, physical page, exact quote and delivery receipt can be traced without exposing the Writer conversation. Task/attempt state, admission/holds, packet delivery and page/image receipts belong to runtime. They are referenced by stable ID. The receipt proving an image was delivered stays mandatory on the visual path.

| Kind | What gets recorded |
|---|---|
| Source | Predicate, value/no-value/unknown, unit where applicable, coverage, period, versioned citation and applicable receipts |
| Conflict | Distinct competing observations; the applicable precedence convention when settled |
| Convention | Rule, scope and versioned criterion where applicable |
| Judgment | Evidence, assumption, conditional or gap; rationale and criterion version; supported classification/value or unscored question; alternatives and defeaters |
| Derived result | Versioned calculation, exact inputs, strength and resulting value when determined or provisional |
| Recommendation | Statement and basis IDs |
| Finding | Reviewer's conclusion on a record in the frozen snapshot |
| Presentation check | Pass/fail, check, snapshot and file digest |
| Question | Text and effect on classification, value, presentation or other work |
| Decision | Answer, dismissed challenge, draft delivery or formal release with bound target |
| Act | Endorse, challenge, confirm, supersede, retract or personally sign off; exact target, reason and replacement for supersession |

“Unknown” means the available material does not establish the value. A source explicitly stating zero within a named population and period can support zero in that scope. A page describing three boreholes on A supports neither a pit count on A nor a count of zero on B. A recorded rainfall period supplies no observation period for rockfalls. Open outcomes identify a question and carry no assigned score. The Fake03 owner deferred A/X51 as a **gap** with low and moderate recorded as conditional possibilities. A conditional judgment elsewhere can explicitly preserve alternative interpretations until a decision.

## Checks and refusal boundaries

| ID | Check | Decisive example |
|---|---|---|
| C1 | Discriminated kind-specific shape and matching producing action | A recommendation cannot enter through a Reviewer finding action. Extra claim fields are rejected. |
| C2 | Explicit absence needs a cited statement with named coverage | Missing groundwater material permits “unknown”. A null measurement alone cannot establish absence. |
| C3 | Evidence grounds must be confirmed, current, relevant and carry a value or explicitly established no-value | A valid quotation about rainfall does not support an event-frequency claim. |
| C4 | Every cited record must be in the calling task's issued packet | An otherwise valid assessment on an unoffered slope cannot be used. Receipt and source-version references are bounded too. |
| C5 | Same subject or a current confirmed convention explicitly authorizing the transfer | A region-level observation only transfers under a convention covering the source, target and proposition. |
| C6 | Confirmed versioned criterion and a permitted classification, alternatives and numeric interval | An unsupported adjustment is declined separately, so a supported grade can survive at the applicable midpoint, with the proposal visible to review. |
| C7 | Direct evidence requires agreement across the complete set of admissible readings | Divergent criterion interpretations also block a scored assumption. Empirical uncertainty under one interpretation can still support an assumption. An incomplete enumeration cannot establish a direct grade. |
| C8 | Assumptions identify alternatives and specific defeaters | A missing observation has to matter to the chosen interpretation. |
| C9 | Evidence cannot rely upon a conflict without a current confirmed precedence decision covering those grounds | Retain the survey quote alongside the preferred design quote. |
| C10 | A derived result cannot claim stronger support than its weakest input | An undetermined result remains unscored. Confidence and staleness are separate from arithmetic. |
| C11 | Match authenticated actor, specific action, current target, packet and applicable authority | A Coordinator's general decision authority cannot supply a release or an engineer's signature. |
| C12 | Formal release requires complete confirmed scope, matching frozen records, a same-snapshot review for each output, current status, no open grade question, and the exact Word/Excel pair | A snapshot with 21 distinct judgments fails even if all 22 output slots have labels and one judgment ID is reused. |

The midpoint rule operates only where a confirmed convention selects it. An accepted departure must carry a review flag, authorized direction and value, and the exact entitled ground IDs. The host derives allowed adjustments from typed method data. A refused proposal may be kept on the judgment for the Reviewer together with its effective midpoint and audit flag. Calculation inputs, recommendation bases and competing observations with another subject require a grounded, scoped transfer even if the caller omits envelope grounds.

The query consumes a validated record as `:row`, the versioned catalog as `:catalog` and a trusted host projection as `:ctx`. The caller may submit claim content. It cannot submit the projection, authority, support facts, checks, hashes or eligibility results. S3 must build that projection within the same transaction as the write and reject missing, stale or mismatched bindings. In particular:

- `packet` is the exact immutable authorized set. `records` resolves current assertions, their source/version, per-proposition entitlement, scopes, statuses, resolutions, typed quantities and dependency-derived strength.
- `applicable_readings`, their exhaustiveness, and each permitted range come from the bound criterion and confirmed scoped conventions. S3 must evaluate the actual expressions on exact observations, including subject, units, coverage, observation periods and visual receipts. The SQL examples consume the resulting attestations. They do not establish engineering interpretation.
- `decimal_between` is an exact decimal predicate with inclusive limits. The test registers it with SQLite on an in-memory connection. S3 must bind exact arithmetic and reject malformed operands. Binary floating-point conversion would erase the boundary demonstrated in the tests.
- `satisfied_authority_conditions` consists of checks evaluated by the host on independently issued grants, actor identity and live targets. Every condition listed for that action must hold. The catalog and query cover independent packet/producer gates, personal identity, named release delegation and exclusive owner powers. S3 must validate target identity and that each grant names the action, actor, subject and binding, and that it is current.
- `snapshot`, `required_slots`, the owner-confirmed scope proof, reviews, active challenges and open questions resolve from frozen or current authoritative records as appropriate. Calculate digests over the actual file bytes. Keys identify required outputs independently of their observed records. Reviews must name the same frozen snapshot and precise record. Fail closed if the required list, snapshot, review set or dependency/status projections cannot be resolved completely.

C1–C12 define rejection boundaries. A supported grade plus an invalid adjustment is two claims to evaluate. The record exposes the proposed adjustment, effective value, reason and review flag; the operation receipt and Reviewer view retain them. Historical Fake03 A/X32 retains its provisional grade, value 27 and question while flagging the suggested grade change. The historical A/X51 replay retains 37 after refusing 49. The later owner deferral supersedes that example for the current pilot. [Recorded cases](../reviews/fake03-claim-validation-offline.md) and [owner deferral](../reviews/fake03-x51-review-follow-up.md).

## Who may act

| Action | Authority and output |
|---|---|
| assert_source / record_conflict | Coordinator or owner creates a source assertion or conflict |
| record_convention | Coordinator proposes a convention. An owner confirmation is a separate act. |
| save_judgment | Writer, or calculator for a determined indicator. Each Writer save checks the claimed producer binding even with a valid packet. A second Writer with a valid packet can be refused by that binding. |
| derive_result / save_recommendation | Calculator derives; Writer recommends |
| record_finding / record_presentation_check | Reviewer records findings. Layout or the text tool records presentation checks. |
| ask / decide | Any authenticated agent can ask. Owner decides; Coordinator can answer within delegated scope. Only the owner can dismiss a challenge. |
| endorse / challenge / confirm | Reviewer or Coordinator endorses or challenges. Confirmation requires an authorized person. Convention confirmation requires the owner. |
| supersede / retract | Author or owner acts on the specific eligible target. An unresolved challenge can be withdrawn by its raising Reviewer, or resolved by owner decision. An owner retracting a formal release targets its precise decision ID. |
| deliver_draft | Coordinator delivers frozen files with gaps disclosed; the record describes a draft |
| release | Delegated Coordinator releases one specific reviewed Word/Excel pair. Only the owner can retract that release. |
| sign_off | A named engineer personally signs a specific active release decision |

Status precedence is retracted, superseded, contested, confirmed, endorsed, proposed. Preserve the history of confirmation while displaying contested as the effective status. A Reviewer can withdraw their own challenge; otherwise the owner can dismiss it or supersede/retract the target. A superseded or retracted input marks transitive dependents stale, including findings. Judgments and findings may qualify by endorsement. Source and convention confirmation require the appropriate person. A frozen release retains the original records and pair of digests after later changes; a new release requires its own decision.

## Atomicity and recovery for S3

An action either commits all its records and receipt or writes no assertion. A refusal is an operational event. No model call runs within the transaction. Look up the operation ID first, check permission to retrieve its receipt, then compare actor, canonical request digest and task/attempt/packet bindings. An exact repeat returns the old result even if current eligibility changed. A mismatch is a conflict. Only a fresh operation checks current eligibility, action authority, packet and C1–C12. Two operations from one task may have different outcomes. S3 must demonstrate concurrent duplicates, a lost reply after commit, a two-action partial task and an exact retry after status changes.

## Method review

The proposal binds the active transcription and original PDF by SHA-256, identifies all eleven printed criteria and their four bands, and preserves the page and JSON pointer for each printed description and note. It includes the qualitative purpose sets, facility side/distance and absence envelope, investigation points per section, and event-period/season adjustment rules. The risk/weight/presentation tables remain version-pinned by reference. The pilot midpoint rule and deferred interpretation carry separate, scoped provenance. The active method loader continues using its existing version. Confirming S2 approves the representation; unresolved engineering interpretations stay open.

## Offline verification

Run `python -B tests/support/run_offline_tests.py -q tests/test_s2_assertion_contract.py` in the native environment. The suite uses local Pydantic, stdlib SQLite and the published fake/pinned method data. It exercises sample shapes and SQL outcomes. Storage concurrency, building the host projection from real packets/receipts, live Coordinator extraction, and byte-level Word/Excel production belong to their later implementation gates.
