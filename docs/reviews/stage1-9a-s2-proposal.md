# Section 9a — S2 amendment proposal for review

Source: **0 lines added / 0 removed**. Active checks/guards added/removed: **0 / 0**. New legacy fallback paths: **0**. This proposal is not an active contract, permission to launch a model or an implemented release path.

Baseline: [one clean main run at cac8ca6](../verification/stage1-clean-main-20261110/results.json). The active S2 files and dispatcher remain unchanged.

## Decision requested

Acknowledge the following single 9a contract amendment before implementation. Proposed check/catalog version: stage1-9a-1. System code supplies that version on new operations; historical envelopes retain their stored versions and remain unchanged. Optional reference additions do not create a new envelope version. It covers the approved role split and the later owner-required case-target review/release work. No assembly-provenance assertions, C5 exemption, dispatcher change, new task store, new identity scheme or automatic engineering sign-off.

### 1. Move value extraction to Writer; confirm bindings rather than values

Coordinator proposes source-page applicability for an object/indicator; the owner confirms it at the planning checkpoint. Writer extracts values and exact quotes from those pages. Reviewer checks the values, qualifications and resulting judgments independently. Existing carried-over facts keep their provenance; they are not silently re-confirmed.

Use the existing convention kind for the binding, because it is a reviewable/withdrawable applicability decision. Add an optional typed page_binding with indicator_id and pages (source_version and physical page), and a typed case_ref to the immutable CommissionPlan version. The envelope subject identifies the object. The model selects offered page/indicator handles; system code fills source/version IDs, plan references and operation IDs. Empty bindings mean missing supplied support, never evidence of absence.

Owner confirmation is an act targeting that exact convention assertion. Superseding or withdrawing the binding invalidates its eligibility and the dependent results. Source assertions link to applicable bindings through existing context grounds; no separate binding ID field or reverse link is needed.

Catalog roles:
- assert_source: Writer and owner; remove Coordinator value extraction from the new route.
- record_conflict: add Writer, retaining Coordinator/owner authority where already applicable.
- record_convention: Coordinator, unchanged.
- All subject, packet and native-call authority comes from the authenticated assignment.

C2 still checks exact quote/source/page and actual image delivery. C3 changes from “the owner confirmed this value” to “this quoted value is on an applicable owner-confirmed page binding for this subject and indicator”. Unknowns remain unscored; an unknown or supplied-material gap cannot prove absence.

Do not alter a Source record's displayed status from proposed to confirmed. Trusted projection exposes quotation/binding eligibility separately. The same source-eligibility predicate must be consumed by the existing Python evidence projection and the source-ground parts of C6/C9; changing only C3 SQL would leave the old confirmed-value dependency in place. Method criteria, precedence conventions, cross-subject transfer and adjustment entitlement retain their independent confirmation requirements. A bound quote establishes location and permitted use, not that the extracted value is a correct interpretation; the Reviewer still checks that.

### 2. Typed references for claims about case versions

Use a minimal CaseRef: type, id and version. It is a one-way reference to existing immutable case content, not a new store or proof object. No content digest, backlink or joint transaction.

Proposed vocabulary:
- Convention.case_ref, Question.case_ref, Act.case_ref and Decision.case_ref: optional CaseRef for the already recorded plan, requirements, checkpoint and answer/choice content currently embedded as JSON text.
- Finding.target: existing assertion ID or CaseRef; Finding.snapshot: existing ID or CaseRef.
- Pair.snapshot and each Pair.records member: existing ID or CaseRef. PresentationCheck.snapshot uses the same snapshot reference form.
- Finding.reason: optional readable basis; the new Reviewer adapter supplies it with an explicit passed/failed/undetermined conclusion. Existing conclusion semantics remain explicit rather than inferring a pass from free text.

The trusted host resolves references and the canonical producer identity from existing case records and authenticated assignments. Agent tools receive offered handles; they do not submit actor identity, producer identity, digests or arbitrary file paths. Packet checks compare canonical type/ID/version keys; case references do not become assertion dependency IDs. Assertion grounds still name assertion IDs. A case-target finding refers to the immutable case content and its native review evidence; it does not introduce a cross-subject world claim or a C5 exception. That content's input lineage remains checked at export/release.

Consumers: plan_authority, commission_assertions and issue_authority replace their JSON-in-text interpretation with typed references. Reviewer/release adapters resolve the exact paragraph/table or DocumentSnapshot version. The assertion package continues to own its database; no outside attachment or access to private store internals.

### 3. Complete C12 for case content and explicit owner waivers

Keep the existing independent Reviewer requirement: review on the exact frozen output, by a canonical actor distinct from both producer and releaser. Coordinator endorsement alone never qualifies.

The host builds the required-output slots from the owner-confirmed plan and the complete frozen report. Snapshot members cover the required indicator outcomes and case content; missing required outputs cannot disappear because no judgment was saved. Reviews target those exact members. Release binds the snapshot plus both Word and Excel digests, keeping the O7 digests. Authority points to the confirmed plan/convention by reference instead of encoding a hash of the output list inside rule text.

Indicator slots name the actual saved judgment or the explicit owner-waiver decision for that indicator. Prose/table/snapshot slots name immutable case versions. Do not reuse one whole-table reference to pretend that 22 indicator outcomes exist. An unsaved outcome can appear as an open draft row, but formal release needs its saved scored outcome or explicit owner waiver. Case content is not labeled “confirmed” to fit the old assertion-only check: eligibility is exact version membership, live input lineage and an independent passing case-target review. Assertion members keep their applicable confirmation/endorsement rules.

Add the owner-only action waive_indicator producing a decision with effect waive_indicator. Its subject is the object, target is the required indicator ID and case_ref is the exact frozen DocumentSnapshot version. It records the explicit reason. These are host-bound fields; an ordinary plan approval, silence or Coordinator action is never a waiver.

C12 permits an open indicator only when that exact frozen output has an active explicit owner waiver. A waiver changes neither the saved judgment nor the calculator's adopted score; the row remains unscored and the level remains not determined where no adopted result exists. It waives only the missing score, not missing required rows, evidence errors, stale inputs, missing review, broken citations, fixed text or file checks. New snapshots require a new waiver. Used waiver assertions are dependencies of release, so retraction cannot leave a silently eligible release.

Draft delivery, formal release and named engineering sign-off remain separate. Keep FORMAL_RELEASE_DEFERRED_TO_9A until the new application path and refusal tests are accepted. Do not add placeholder assertions for paragraphs or move assembly provenance out of case data.

### 4. Remove redundant transport links without losing business facts

As already required in 9a, new judgments must not depend on submission_receipt and new calculations must not require projection_digest. Keep exact request/binding comparison for redo, source version pins and O7 file digests. No paid request, hold or authorization row is reset/released.

Page/image delivery is checked during the action; used source/version/page and qualifications remain in the completed fact/judgment grounds. Before deleting any receipt-backed field, inventory its consumers, including the current typed-fact qualifier projection. Retain or explicitly project real business facts, not the transport receipt as a substitute. Existing accepted historical data stays physically unchanged; O4/O5 readers are not retired by this amendment. Any additional business field required by this audit is brought back with its actual consumer before it is added.

## Configuration-only claim: confirmed limits

The original plan expected mostly prompts, catalog, C3 and tool/access configuration. Source inspection shows real dependencies outside those files:
- planning_assertions._issuer is explicitly Coordinator-only;
- writer_fact_packet.assigned_facts requires confirmed values and unpacks receipt qualifiers;
- evidence.py and checks.sql use confirmed-value status in several ground checks;
- authority.py and queries.py currently assume frozen members are assertions;
- current unscored results are refused by assembly and lack open-row rendering.

These are requirement-backed adapter/projection changes, not permission to rebuild storage, IDs, recovery or dispatch. Record this as a boundary finding before the paid run. Keep one store per write and the current dispatcher byte-identical.

## Offline acceptance before a paid run

- Exact quote on an applicable confirmed binding accepted; wrong/unconfirmed/withdrawn binding refused; source status not falsely elevated. Unknown material never proves absence.
- C4/C5 scope, qualifiers, conflicts, midpoint/adjustment rules, producer binding and native identity replays remain covered. Six known defects remain blocked/flagged; ten controls and fake04 wording remain valid.
- Reuse the existing pure weighted/sensitivity arithmetic. Numeric guideline grade/interpolation logic is still missing in the active calculator path: implement only specified guideline rules, including the larger-of total/bench-height rule; missing required inputs remain open. Do not treat qualitative midpoint choice as numeric interpolation.
- Fake03 drafts contain each open indicator and its reason, including the A/X51 deferral; the two reconciliation issues and inventory issue reach comments/Excel rows with correct routes. No invented score.
- Case-target reviews, exact versions/pair, missing 22nd output, pre-freeze reviews, producer/releaser self-review and owner waiver/retraction have passing/refusing pairs.
- Source correction/replacement makes affected calculations and prose stale; prior files and records remain intact.
- Word/Excel share one frozen snapshot; required issue comments match rows one-to-one; fixed text, citations, internal-content checks and rendered pages/tables/TOC pass.
- Field/check sweep includes every active agent-facing field/check and actual refusal measurements, including measured zeroes. Missing instrumentation is marked unmeasured, not zero.
- Business copies carry completed facts, not another run's grants/receipts. Image-delivery checks survive. Full offline verification and independent review precede a separately authorized paid launch.

## Initial inventory status

The initial source survey records 12 SQL check families (13 clauses), model-visible Writer schemas and candidate native guard sites. It is not a finished removal decision or a measured refusal census. The proposal changes no active schema/catalog/check/prompt. Application implementation waits for this amendment's acknowledgment.

## Illustrative stored claims (identifiers filled by the host)

A binding is a convention, not an extracted value:

~~~json
{"kind":"convention","scope":"source_page_binding","rule":"Pages applicable to this indicator",
 "case_ref":{"type":"CommissionPlan","id":"plan-id","version":2},
 "page_binding":{"indicator_id":"X31","pages":[{"source_version":"source-version","page":1}]}}
~~~

An explicit waiver does not change a saved score or constitute engineering sign-off:

~~~json
{"kind":"decision","effect":"waive_indicator","target":"X51",
 "case_ref":{"type":"DocumentSnapshot","id":"snapshot-id","version":1},
 "reason":"Owner explicitly accepts this unresolved indicator for this frozen output."}
~~~

The envelope supplies the authenticated owner and object subject. These examples are specifications for review, not records written to a live case.

## Implementation surface tied to requirements

| Files | Addition/removal and consumer |
| --- | --- |
| assertions/schema/kinds.py, actions.json, checks.sql | Only the proposed reference/binding/waiver vocabulary, role rules and eligibility/release checks; native adapters and C3/C12 consume them. Log exact contract deltas in s2-amendments.json after acknowledgment. |
| assertions/evidence.py, authority.py, queries.py, actions.py | Project binding eligibility without faking value confirmation; resolve authorized case targets; compare complete frozen output membership and owner waivers. Preserve request/binding replay and C4/C5. No new assertion tables. |
| planning_assertions.py, commission_plan.py, commission_assertions.py, plan_authority.py, issue_authority.py | Coordinator binding/checkpoint adapter and typed reference readers replacing JSON in text. Content first, assertion second, no joint transaction. |
| writer_fact_packet.py, writer_assignments.py, writer_assessment.py, writer_judgments.py, writer_runtime.py | Build reference-scoped Writer access, quote extraction and atomic completed outcomes; retire receipt/progress dependence only after preserving actual consumed facts/qualifiers. |
| risk_scoring.py, assessment_results.py, assessment_projection.py, existing tools | Reuse pure weighting/bounds, add specified numeric rules, remove projection digest dependence and render actual unscored reasons without an adopted score. |
| qualitative_review.py and native review adapters | Read-only review over exact source/value/judgment/case versions; store disputable findings as assertions, with explicit verdict and reason. |
| system_assembler.py, content_export.py, content_workbook.py, material_issues.py | Admit disclosed drafts; preserve required issue routes/comments/rows, case-version lineage and all existing export checks. |
| Workspace correction UI/action entry and corresponding current-case procedure | Notice/disable only for assertion-backed reports, pointing to assertion correction/source replacement; keep O4/O5 old routes intact. |
| Effective Coordinator, Writer and Reviewer prompts and tool descriptions | Remove conflicting confirmed-value/role instructions together with tool changes. No extra model or scheduler. |
| Existing replay, authority, copy, numeric, rendering and release tests | Add/refine failing/passing cases for the actual requirement gaps; preserve the six defect and ten control outcomes and map any retired tests individually. |

This table is scope clarity, not approval of a larger refactor. The exact field/check inventory determines unnecessary code removed within these boundaries. Paid-launch authorization and engineering interpretation of the unresolved criteria remain separate.

[Initial field inventory](../verification/stage1-9a-inventory/agent-fields-initial.tsv), [current S2 check clauses](../verification/stage1-9a-inventory/s2-checks-initial.tsv), [scope and unfinished measurements](../verification/stage1-9a-inventory/status.json).
