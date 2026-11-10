# Section 9a — S2 amendment proposal for review

Source: **0 lines added / 0 removed**. Active checks/guards added/removed: **0 / 0**. New legacy fallback paths: **0**. This proposal is not an active contract, permission to launch a model or an implemented release path.

Baseline: [one clean main run at cac8ca6](../verification/stage1-clean-main-20261110/results.json). The active S2 files and dispatcher remain unchanged.

## Owner acknowledgment and separate implementation reviews

The owner acknowledged this amendment in substance on 2026-11-10, with the four corrections and a–f delivery split recorded below. This revision applies those terms before implementation. Keep one umbrella amendment, applied and reviewed in separate parts; log only the vocabulary/check deltas actually implemented in each part, not a claim that all of 9a is active. Proposed first check/catalog version: stage1-9a-1. System code supplies versions; historical envelopes stay unchanged. Optional reference additions alone do not require another envelope version. No assembly-provenance assertions, C5 exemption, dispatcher change, new task store, new identity scheme or automatic engineering sign-off.

## Delivery split and launch boundary

| Part | Scope and review | Gate |
| --- | --- | --- |
| 9a-a | Page bindings, Writer extraction/new C3, one confirmation-sheet reply, retirement of file-level source-use approval | Before paid Fake03 |
| 9a-b | Unscored draft rendering, required issue records/routes, one-to-one comments/rows and rendered-page QA | Before paid Fake03 |
| 9a-c | Remove receipt/digest dependencies where 9a-a touches them; finish the active field/check inventory with measured refusal counts | Before paid Fake03 |
| 9a-d | General typed references replacing the existing JSON-in-text references | May follow paid Fake03 |
| 9a-e | Case-target review, formal release/C12 and plan-scoped owner waivers | May follow paid Fake03; required for formal release |
| 9a-f | New numeric guideline grading/interpolation and larger-of height rules, with separate small acceptance tests | May follow paid Fake03 unless its frozen scoring expectations require them |

Review and tag each part separately in a–f order, except that f comes forward when the paid test requires its numeric rules. Reuse the current 9a branch rather than making a branch per letter. Each verification record starts with source additions/removals and net change, checks/guards added/removed and legacy fallback paths. Main advances only to an accepted part; delete the working branch when its work is closed.

The paid Fake03 gate is accepted 9a-a/b/c, the measured check inventory, required offline verification and a **separate owner-approved launch scope/cap**. It tests extraction, judgment quality and the draft trunk; it does not require formal release. Until 9a-e is accepted, keep the existing formal-release refusal. Parts d/e are not hidden paid-run prerequisites. Numeric part f is brought forward only if the answer key/run scope requires its scoring. Freeze that choice before launch: unimplemented numeric rules must be reported as a capability limitation, not missing source evidence or a successful numeric-grade test. No launch is authorized by this revision.

The detailed sections below define the whole amendment; their gates are governed by this table. Defer general reference cleanup; 9a-a may use the existing accepted reference-in-text representation. If a narrowly needed typed binding reference is necessary for a itself, document its actual consumer, without pulling all of d onto the critical path.

### 1. Move value extraction to Writer; confirm bindings rather than values (9a-a)

Coordinator proposes source-page applicability for an object/indicator; the owner confirms it at the planning checkpoint. Writer extracts values and exact quotes from those pages. Reviewer checks the values, qualifications and resulting judgments independently. Existing carried-over facts keep their provenance; they are not silently re-confirmed.

Use the existing convention kind for the binding, because it is a reviewable/withdrawable applicability decision. Add an optional typed page_binding with indicator_id and pages (source_version and physical page). Part a links to the immutable CommissionPlan using the existing accepted representation; part d replaces general JSON-in-text references with typed case_ref. Do not make general reference cleanup a dependency of a. The envelope subject identifies the object. The model selects offered page/indicator handles; system code fills source/version IDs, plan references and operation IDs. Empty bindings mean missing supplied support, never evidence of absence.

Confirmation is **one checkpoint and one owner reply** to the versioned confirmation sheet, not one click per binding or slope. System code applies that reply to the exact listed conventions, producing the individual confirm acts. Unresolved/excepted bindings stay unconfirmed. Repeating the same reply completes only its missing acts with the original operation identities; it neither duplicates acts nor approves a binding added after that sheet. An interruption can be retried from the saved reply without asking the owner to answer again.

Superseding or withdrawing a binding invalidates its eligibility and dependent results. Source assertions link to applicable bindings through existing context grounds; no separate binding ID field or reverse link is needed.

Retire the file-level source-use approval in **the same 9a-a amendment**. Planning can read the explicitly supplied case files to propose bindings; Writer/report use follows confirmed page bindings and its issued packet. Case access and C4 remain security boundaries, not extra material-approval prompts. Remove the new-route file-level approval wait, UI/action requirement and report/export dependency, rather than manufacturing an always-approved grant. Preserve historical decisions/source originals; do not delete authorization receipts, copy old grants or build grant-reuse logic. Tests must show that a fresh case reaches the single confirmation sheet without a file-approval checkpoint.

Catalog roles:
- assert_source: Writer and owner; remove Coordinator value extraction from the new route.
- record_conflict: add Writer, retaining Coordinator/owner authority where already applicable.
- record_convention: Coordinator, unchanged.
- All subject, packet and native-call authority comes from the authenticated assignment.

C2 still checks exact quote/source/page and actual image delivery. C3 changes from “the owner confirmed this value” to “this quoted value is on an applicable owner-confirmed page binding for this subject and indicator”. Unknowns remain unscored; an unknown or supplied-material gap cannot prove absence.

Do not alter a Source record's displayed status from proposed to confirmed. Trusted projection exposes quotation/binding eligibility separately. The same source-eligibility predicate must be consumed by the existing Python evidence projection and the source-ground parts of C6/C9; changing only C3 SQL would leave the old confirmed-value dependency in place. Method criteria, precedence conventions, cross-subject transfer and adjustment entitlement retain their independent confirmation requirements. A bound quote establishes location and permitted use, not that the extracted value is a correct interpretation; the Reviewer still checks that.

### 2. Typed references for claims about case versions (9a-d/e, after the draft gate)

Use a minimal CaseRef: type, id and version. It is a one-way reference to existing immutable case content, not a new store or proof object. No content digest, backlink or joint transaction.

Proposed vocabulary:
- Convention.case_ref, Question.case_ref, Act.case_ref and Decision.case_ref: optional CaseRef for the already recorded plan, requirements, checkpoint and answer/choice content currently embedded as JSON text.
- Finding.target: existing assertion ID or CaseRef; Finding.snapshot: existing ID or CaseRef.
- Pair.snapshot and each Pair.records member: existing ID or CaseRef. PresentationCheck.snapshot uses the same snapshot reference form.
- Finding.reason: optional readable basis; the new Reviewer adapter supplies it with an explicit passed/failed/undetermined conclusion. Existing conclusion semantics remain explicit rather than inferring a pass from free text.

The trusted host resolves references and the canonical producer identity from existing case records and authenticated assignments. Agent tools receive offered handles; they do not submit actor identity, producer identity, digests or arbitrary file paths. Packet checks compare canonical type/ID/version keys; case references do not become assertion dependency IDs. Assertion grounds still name assertion IDs. A case-target finding refers to the immutable case content and its native review evidence; it does not introduce a cross-subject world claim or a C5 exception. That content's input lineage remains checked at export/release.

Consumers: plan_authority, commission_assertions and issue_authority replace their JSON-in-text interpretation with typed references. Reviewer/release adapters resolve the exact paragraph/table or DocumentSnapshot version. The assertion package continues to own its database; no outside attachment or access to private store internals.

### 3. Complete C12 for case content and plan-scoped owner waivers (9a-e)

Keep the existing independent Reviewer requirement: review on the exact frozen output, by a canonical actor distinct from both producer and releaser. Coordinator endorsement alone never qualifies.

The host builds the required-output slots from the owner-confirmed plan and the complete frozen report. Snapshot members cover the required indicator outcomes and case content; missing required outputs cannot disappear because no judgment was saved. Reviews target those exact members. Release binds the snapshot plus both Word and Excel digests, keeping the O7 digests. Authority points to the confirmed plan/convention by reference instead of encoding a hash of the output list inside rule text.

Indicator slots name the actual saved judgment or the explicit owner-waiver decision for that indicator. Prose/table/snapshot slots name immutable case versions. Do not reuse one whole-table reference to pretend that 22 indicator outcomes exist. An unsaved outcome can appear as an open draft row, but formal release needs its saved scored outcome or explicit owner waiver. Case content is not labeled “confirmed” to fit the old assertion-only check: eligibility is exact version membership, live input lineage and an independent passing case-target review. Assertion members keep their applicable confirmation/endorsement rules.

Add the owner-only action waive_indicator producing a decision with effect waive_indicator. Its subject is the object, target is the required indicator ID and case_ref is the exact CommissionPlan version. It records the explicit reason. These are host-bound fields; an ordinary plan approval, silence or Coordinator action is never a waiver.

C12 permits an open indicator only when an active explicit owner waiver applies to its plan version, object, indicator and effective inputs. A waiver changes neither the saved judgment nor the calculator's adopted score; the row remains unscored and the level remains not determined where no adopted result exists. It waives only the missing score, not missing required rows, evidence errors, stale inputs, missing review, broken citations, fixed text or file checks. A cosmetic prose/layout/typo change or new snapshot alone does **not** require re-waiving. The waiver stays applicable until withdrawal or a change to the indicator's effective inputs; another plan version is outside its scope. System code binds the existing input references (facts, page bindings, method/rank/precedence references as applicable), and compares effective reference sets directly. Do not add an input digest or use a snapshot ID as input identity. New or superseded effective evidence, a changed applicable binding or changed calculation convention invalidates applicability; a missing-input state becoming supplied is an input change too.

Each release records the exact waiver assertion IDs it relied on and its own exact snapshot/file pair. Used waivers remain assertion dependencies of release, so retraction cannot leave a silently eligible release. Input changes make an old waiver inapplicable without rewriting or deleting it.

Draft delivery, formal release and named engineering sign-off remain separate. Keep FORMAL_RELEASE_DEFERRED_TO_9A until the new application path and refusal tests are accepted. Do not add placeholder assertions for paragraphs or move assembly provenance out of case data.

### 4. Remove redundant transport links without losing business facts (9a-c, targeted first)

Before paid Fake03, remove submission_receipt/projection_digest and related receipt dependencies **where 9a-a touches them**. Do not turn unrelated cleanup into a blocker for the draft trunk. Carry untapped consumers into the later part that changes them. Keep exact request/binding comparison for redo, source version pins and O7 file digests. No paid request, hold or authorization row is reset/released.

Page/image delivery is checked during the action; used source/version/page and qualifications remain in the completed fact/judgment grounds. Before deleting any receipt-backed field, inventory its consumers, including the current typed-fact qualifier projection. Retain or explicitly project real business facts, not the transport receipt as a substitute. Existing accepted historical data stays physically unchanged; O4/O5 readers are not retired by this amendment. Any additional business field required by this audit is brought back with its actual consumer before it is added.

## Configuration-only claim: confirmed limits

The original plan expected mostly prompts, catalog, C3 and tool/access configuration. Source inspection shows real dependencies outside those files:
- planning_assertions._issuer is explicitly Coordinator-only;
- writer_fact_packet.assigned_facts requires confirmed values and unpacks receipt qualifiers;
- evidence.py and checks.sql use confirmed-value status in several ground checks;
- authority.py and queries.py currently assume frozen members are assertions;
- current unscored results are refused by assembly and lack open-row rendering.

These are requirement-backed adapter/projection changes, not permission to rebuild storage, IDs, recovery or dispatch. Record this as a boundary finding before the paid run. Keep one store per write and the current dispatcher byte-identical.

## Separately reviewed acceptance

- Exact quote on an applicable confirmed binding accepted; wrong/unconfirmed/withdrawn binding refused; source status not falsely elevated. Unknown material never proves absence.
- C4/C5 scope, qualifiers, conflicts, midpoint/adjustment rules, producer binding and native identity replays remain covered. Six known defects remain blocked/flagged; ten controls and fake04 wording remain valid.
- 9a-f, independent numeric acceptance: reuse pure weighted/sensitivity arithmetic; add only specified guideline threshold/interpolation and larger-of total/bench-height rules. Use a small table-driven test for threshold endpoints, total versus bench scores and missing required inputs. This is new calculator functionality, not role-split acceptance. Bring it forward only when the paid Fake03 scoring scope requires it; otherwise keep numeric limitations explicit.
- Fake03 drafts contain each open indicator and its reason, including the A/X51 deferral; the two reconciliation issues and inventory issue reach comments/Excel rows with correct routes. No invented score.
- 9a-e: case-target reviews, exact versions/pair, missing 22nd output, pre-freeze reviews, producer/releaser self-review and owner waivers have passing/refusing pairs. Include typo-only re-export retaining the waiver, changed inputs invalidating it, a newly supplied missing input invalidating it, and withdrawal blocking releases that rely on it.
- Source correction/replacement makes affected calculations and prose stale; prior files and records remain intact.
- Word/Excel share one frozen snapshot; required issue comments match rows one-to-one; fixed text, citations, internal-content checks and rendered pages/tables/TOC pass.
- Field/check sweep includes every active agent-facing field/check and actual refusal measurements, including measured zeroes. Missing instrumentation is marked unmeasured, not zero.
- 9a-a/c: business copies carry completed facts, not another run's grants/receipts. Image-delivery checks survive. Applicable offline verification and acceptance of a/b/c precede a separately authorized paid launch; this is not a requirement to finish d/e/f first. Full regressions still require explicit authorization.

## Initial inventory status

The initial source survey records 12 SQL check families (13 clauses), model-visible Writer schemas and candidate native guard sites. It is not a finished removal decision or a measured refusal census. The proposal changes no active schema/catalog/check/prompt. The owner has acknowledged the substance subject to this revised split. No application changes are claimed here. Each implementation part receives its own size/verification record, tag and review.

## Illustrative stored claims (identifiers filled by the host)

A binding is a convention, not an extracted value. This illustration shows the eventual typed reference after d; a may retain the existing plan-reference representation:

~~~json
{"kind":"convention","scope":"source_page_binding","rule":"Pages applicable to this indicator",
 "case_ref":{"type":"CommissionPlan","id":"plan-id","version":2},
 "page_binding":{"indicator_id":"X31","pages":[{"source_version":"source-version","page":1}]}}
~~~

An explicit waiver does not change a saved score or constitute engineering sign-off:

~~~json
{"kind":"decision","effect":"waive_indicator","target":"X51",
 "case_ref":{"type":"CommissionPlan","id":"plan-id","version":2},
 "reason":"Owner explicitly waives this object/indicator for these effective inputs."}
~~~

The envelope supplies the authenticated owner and object subject. Existing grounds carry the host-bound input assertion references; the illustration omits those envelope grounds for brevity. These examples are specifications for review, not records written to a live case.

## Implementation surface tied to requirements

| Files | Addition/removal and consumer |
| --- | --- |
| assertions/schema/kinds.py, actions.json, checks.sql | 9a-a: binding/role/source-use and C3 eligibility deltas; 9a-d/e: general reference and waiver/release deltas. Native adapters and C3/C12 consume only their reviewed part. Log exact contract deltas in s2-amendments.json after acknowledgment. |
| assertions/evidence.py, authority.py, queries.py, actions.py | Project binding eligibility without faking value confirmation; resolve authorized case targets; compare complete frozen output membership and owner waivers. Preserve request/binding replay and C4/C5. No new assertion tables. |
| planning_assertions.py, commission_plan.py, commission_assertions.py, plan_authority.py, issue_authority.py | Coordinator binding/checkpoint adapter and typed reference readers replacing JSON in text. 9a-a adds the one-reply confirmation fan-out and retires file-approval dependencies; general reference-reader cleanup waits for d. Content first, assertion second, no joint transaction. |
| source_use.py, source access/export callers | 9a-a retires file-level approval for the new route; confirmed page bindings and case access remain. Preserve historical source-use records and keep O4/O5 behavior. |
| writer_fact_packet.py, writer_assignments.py, writer_assessment.py, writer_judgments.py, writer_runtime.py | Build reference-scoped Writer access, quote extraction and atomic completed outcomes; retire receipt/progress dependence only after preserving actual consumed facts/qualifiers. |
| risk_scoring.py, assessment_results.py, assessment_projection.py, existing tools | Reuse pure weighting/bounds, add specified numeric rules, remove projection digest dependence and render actual unscored reasons without an adopted score. |
| qualitative_review.py and native review adapters | Read-only review over exact source/value/judgment/case versions; store disputable findings as assertions, with explicit verdict and reason. |
| system_assembler.py, content_export.py, content_workbook.py, material_issues.py | Admit disclosed drafts; preserve required issue routes/comments/rows, case-version lineage and all existing export checks. |
| Workspace correction UI/action entry and corresponding current-case procedure | Notice/disable only for assertion-backed reports, pointing to assertion correction/source replacement; keep O4/O5 old routes intact. |
| Effective Coordinator, Writer and Reviewer prompts and tool descriptions | Remove conflicting confirmed-value/role instructions together with tool changes. No extra model or scheduler. |
| Existing replay, authority, copy, numeric, rendering and release tests | Add/refine failing/passing cases for the actual requirement gaps; preserve the six defect and ten control outcomes and map any retired tests individually. |

This table is scope clarity, not approval of a larger refactor. The exact field/check inventory determines unnecessary code removed within these boundaries. Paid-launch authorization and engineering interpretation of the unresolved criteria remain separate.

[Initial field inventory](../verification/stage1-9a-inventory/agent-fields-initial.tsv), [current S2 check clauses](../verification/stage1-9a-inventory/s2-checks-initial.tsv), [scope and unfinished measurements](../verification/stage1-9a-inventory/status.json).
