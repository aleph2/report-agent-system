# Task029: actual claim-evidence verdict contract in the native loop

2026-09-29. Continue the approved final-verifier direction, paid trials and email
reporting. Main owns implementation and integration; resume_assessment performed
read-only architecture assessment; alignment_review reviews the material boundary;
postrun_review independently evaluates public native findings and saved revisions.
Stage: critical-risk validation. Reliable automatic report acceptance is still open.

## Why this factor now

Task025–027 show failures in discovery, source interpretation and the transition
from observed facts to acceptance. Task028's four fixed-evidence observations are
mixed: original/broad passed, corrected/broad found scope/activity defects; both
localized quantity judgments were correct, but the original/local repair gap also
expanded the commissioned scope. No universal broad-task incapacity or reliable
local-review pipeline follows. The real decision gap is worth making observable.

The existing native schema permits pass criteria as name/true and describes the
whole explanation as1–2 sentences. H2 changed prose, not this contract. Prototype
an actual output contract requiring located grounds and commission impact for each
criterion. Grader chooses which consequential claims/conditions matter and how to
investigate; no per-page scan, exhaustive claim list, mandated tool sequence,
minimum defect count or added runtime reviewer is introduced.

## Minimal contract and native reuse

Keep native result enum, five rubric categories, model/parameters, tools, prompt,
input organization, compact source representation and iteration cap. Extend native
GraderResponse with grounded criterion variants; use the same class/tool name so
the native payload remains accurate. Each pass/fail criterion retains name/passed
and native gap requirements, adding a nonempty list of selected public grounds:

- report_claim and report_locator: assertion or deliverable condition being judged;
- report_locator may honestly state absent, not locatable or not applicable with a
  reason; no invented citation is required for a missing chapter or unknown fact;
- evidence: located observations from the report, sources or authoritative commission;
  an empty list may honestly represent absent evidence;
- relationship: supported, contradicted, unresolved or not_checked;
- commission_impact: why this matters for this criterion and commissioned use;
- needed_outcome: a justified correction/limitation/handling, or no change needed;
  this stays within the commission and responsible party's authority, with source
  disputes/human decisions preserved rather than assigned to the author to decide;
- blocks_criterion: the model's explicit judgment whether this ground prevents pass.

These are deliverable fields, not thinking steps. No private reasoning is requested.
Code rejects an explicit blocks_criterion=true together with passed=true; it does
not decide engineering materiality, turn every unknown into failure, require source
citations for report-internal facts, validate semantic truth from field presence,
or force an issue count. Nonempty selected grounds do not claim exhaustive coverage.
Native result/criterion consistency validation stays inherited.

DeepAgents0.7.19 has no public response_format option on RubricMiddleware. Its
_ensure_grader builds LangChain create_agent with a fixed native GraderResponse.
Use one opt-in thin override in existing FeedbackRubric, preserving resolution,
state/context schemas, middleware, tools and lazy cache, changing only the schema.
Do not replace native grade invocation, coverage retry, evaluation finalization or
revision loop. Installed framework model extraction preserves subclass instances;
criteria dict serialization retains extra grounds. This private construction hook
is a version-maintenance cost, explicitly tested against the pinned dependency.

Override only the existing _revision_prompt hook as needed to append serialized
public criterion grounds to the native author feedback. Retain the native message,
unverified warning and handoff behavior; do not create another author/reviewer turn.
Grounds are claims to check, not privileged instructions or already verified facts.
The responsible author still owns saved corrections; grader remains read-only.

The alternative of merely exposing existing analyze_text is deferred: it supplies
one source page/purpose to GLM without the selected report/commission/compact table,
so it changes model/context and does not directly test final acceptance synthesis.
The optional bounded-analysis capability can be a later informed experiment.

## Isolation, identity and verification

Add an optional claim_evidence_contract flag requiring the existing compact/
artifact/grounded/calibrated selection for this comparison. Absent flag preserves
old schema and behavior. Fresh-fork configuration is immutable; bind schema hash
and version before runtime/old-approval return. Put contract hash on review targets
and require it for matching acceptance. Reject schema changes on recovery; never
relabel old pass results. Same system prompt does not mean same output contract.

Before calls test actual registered response schema, required grounds/native gap,
explicit block/pass conflict, honest unresolved/nonblocking representation, default
compatibility, full grounds persistence through native finalization/reconciliation,
author feedback, unverified/terminal handoff and fresh-fork/recovery identity. Reuse
relevant rubric/source/context regressions. Independent alignment review remains a
development check, not an additional report-runtime gate.

Then freeze code/schema/system, prepare one fresh original Task016 pre-review fork
and run the complete native grader→author→re-review path. Task027 is the existing
same-prompt/compact/native control; autonomous observations may differ. This tests
the contract plus the necessary feedback projection, not a pure prompt change.
Keep all results and inspect actual requests/tool schemas, selected claims, grounds,
scope-consistent feedback, saved repairs, original F arithmetic, new defects and
exact final target binding. A filled schema or satisfied alone is not gain.

If useful native repair appears, independently test unseen supported/defective/
legitimate-uncertainty content and repeat the useful native observation once under
unchanged conditions before a reproducibility claim. If not, retain failure and
choose the next discriminating factor; do not replay until acceptance. Protocol
errors get evidence-first diagnosis; no blind business retries or cumulative token
quota. No graph, legacy mutation, engineering sign-off or automatic promotion.

Official references opened2026-09-29: LangChain
[structured output](https://docs.langchain.com/oss/python/langchain/structured-output)
and DeepAgents [rubrics](https://docs.langchain.com/oss/python/deepagents/rubric).
They support framework mechanics, not semantic reliability or current model quality.
