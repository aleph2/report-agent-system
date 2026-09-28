# Task006 Independent Alignment Review

2026-09-27. Reviewer: Anscombe, read-only independent agent. Main records the
findings and disposition here because that reviewer is prohibited from editing.
This record is not a claim that the reviewer implemented fixes or ran Main's tests.

## Verified boundaries

The reviewer inspected registration and the actual synthetic-reuse-fixed trace:

- Native DeepAgents default general-purpose delegation is disabled. Children do
  not receive nested task delegation or host shell. Files use virtual StateBackend.
- Tool closures bind capabilities: root can compose a draft, cannot mutate upstream
  facts or submit reviews. Knowledge may publish graph facts and optional purpose/plan
  artifacts; it cannot author or review the report. No mandatory artifact chain.
- The actual reviewer request began with its own system/human context, not parent
  AI/tool history. It read both sources and the exact saved draft, and submitted
  the matching review. This supports independent context, not engineering accuracy.

## Findings and Main disposition

| Finding | Impact and severity | Containment / disposition |
| --- | --- | --- |
| Graph lookup preceded SQL receipt recovery | P2: graph outage could block recovering an already committed result | Added immutable submission_id, atomically stored with result; lookup precedes graph and freshness checks. Main cross-layer lost-response test passes even with graph unavailable and changed human context. |
| CLI and read_result used SQL-only currentness | P2: disagreement with GUI/export on changed facts | CLI, read tool, delivery and export now use shared graph-state projection. Main tests verify unavailable means unknown/system failure, not missing input. |
| Adopted graph provenance absent from source impact chain | P2: source replacement could leave a fact-only consumer apparently current | New submit retains immutable source references from adopted graph facts; no fact-body duplication. Main source-replacement cross-layer test passes. |
| Producer assessment of graph revisions not yet supported | P2: changed facts stay pending, no reassessment without revision | Deferred. Status says needs_attention; no automatic rewrite or fresh-approval claim. Freeze real-trial input versions. Blocks dynamic graph-version reassessment acceptance, not isolated real-source testing. |

Main verification after fixes: tests/test_fact_runtime.py plus native runtime tests,
17 passed. The independent reviewer inspected fixes but did not independently execute
these tests. Exact-version history stays available; successful review is not sign-off.

## Remaining evidence boundaries

The live real-source run started before the receipt/source-impact patches above;
its in-flight process is not restarted or described as running those later patches.
The next run/resume must inspect saved receipts before dispatch. Historical artifacts
without submission_id remain immutable. Actual report quality, live graph adoption,
real-material human-decision recovery and final document layout need their own evidence.
Neither source completeness nor correctness follows from test counts or graph size.

## Actual-source follow-up

Chandrasekhar independently inspected the unsaved candidate in state.db events156/161
(14,676 characters, hash347c5a5164cd68d24bab217771c097cb091a78f02ab87b868210815afd0f0795).
P1 content finding: scope section5 leaves the scoring method to project-lead
confirmation, but candidate chapters3-6 present selected weights and risk grades as
confirmed and suitable for engineering use. Main accepts this severity for affected
content: blocks acceptance and engineering use, not isolated model revision/testing.
No candidate was saved or selected as delivery. Main did not calculate or rewrite it.
The finding was returned as development review feedback, not a human scoring decision.

The resumed reviewer eventually requested human assistance for a system_failure:
three internal draft task IDs were incorrectly used as result IDs, while results=0.
P2 identity/interface issue blocks review submission, not recovery. Agent projection
now omits internal submission tasks and task IDs from result views/receipts; durable
records and GUI audit are retained. Review tool explicitly names saved results[].id.
Anscombe approved this scope and cautioned that old checkpoint history remains.
Main recorded a clearly attributed technical-only response to this system issue,
then resumed the same checkpoint. No business issue or scoring assumption was approved.
19 native/cross-layer tests pass after projection/receipt changes. Full suite before
this final projection patch:232 passed,9 skipped,1 historical ADK warning.

Further actual recovery: the parent also needed explicit technical clarification;
it was still citing the pre-repair errors without attempting the repaired submit.
Main's second response is attributed development feedback, not scoring approval.
First actual result82d9f1bc-3e02-484f-aec1-4f0855fd0d3c (14,968 characters) committed
at15:36:37 UTC; reviewer read that saved body in events367/371. Chandra independently
confirmed three new qualifications at body lines5,280,286: method/weights/scores/grades
await project-lead confirmation. P1 is contained for a pending draft, not closed for
engineering use. Residual P2 lines308-310 reliability/use-as-basis wording needs alignment.

Anscombe final architecture disposition: conditionally accepted for isolated real
draft testing. Native framework/restricted tools/separate fact authority align with
confirmed decisions; no fixed semantic stage engine. Dynamic graph change reassessment,
new-fact relevance and general business-decision checkpoint adaptation remain unproven.
Main's full regression after projection:233 passed,9 skipped,1 historical warning;
17 static UI checks passed. These counts are not semantic acceptance.

Actual model review7947a78b-56f9-489b-99a6-bd5133781aa7 returned changes_required,
not acceptance. It requests chapter2 template alignment and flags source/OCR
ambiguities. Main also observed a P2 numerical inconsistency in its explanation:
it asserts50*0.03=1.20 (the arithmetic product is1.50) while claiming all products
are correct. This observation does not establish which underlying draft input or
score is correct. The model review is not reliable numerical validation. It blocks
claiming checked engineering scores, not saving a visibly pending draft. Preserve
the original review; a subsequent increment should expose a bounded deterministic
calculation tool for agent use rather than add mandatory per-cell LLM stages.
Main owns follow-up; no automatic formal approval, no silent correction of source
or report values. The current application can continue its own requested revision.

## 2026-09-28 Post-Delivery Control Review

Request: independently assess application controls, DeepAgents reuse and agent
design patterns. Review-only continuation of Task006; no new deployment, model
calls or runtime edits. Prior trunk evidence is reused, not rerun or promoted to
engineering acceptance. Main acknowledges that finishing the tested increment
did not exhaust the user's broader continued-development authorization; there
was no demonstrated technical blocker requiring development to stop.

Actual participants: Anscombe independently reviewed alignment and control
boundaries; Rawls checked framework reuse and reproduced the repeated-action
guard; Main read the current code, pinned framework source, official references
and compact real-run audit, and records the disposition here.

### Findings And Disposition

| Finding | Evidence | Severity, scope and blocked action | Main disposition |
| --- | --- | --- | --- |
| Source conflicts still lack business human adjudication | Earlier content findings above; actual run has two technical clarifications, not approval of scoring or adverse-value selection | P1 for affected engineering conclusions; blocks formal engineering use and claims of human approval, not a clearly pending local draft | Retain limitations; next business-quality work must present conflicts and receive a real decision, not infer approval from recovery or model review. Main owns follow-up. |
| Revision silently inherits dependencies | workspace.py:228 maps previous result references to current IDs; :332 unions task inputs into explicitly submitted inputs | P2; program can retain or advance evidence the revising agent did not select; blocks claiming all adoption is explicit | Separate predecessor history from adopted evidence. Let the producer select current dependencies; preserve ownership and history. Prioritize next scoped correction. |
| Repeated-call guard can stop actual progress and receipt retrieval | deep_runtime.py:58-64 hashes name/args/result IDs/context, not returned observations, graph versions or scratch changes; raises before handler | P2; false runtime stop, no demonstrated data loss or proof this caused the previous live failure | Correct or remove this heuristic hard stop. Rawls reproduced changing observations on the first two calls, then third-call rejection; actual receipt lookup similarly blocked on third call in one middleware instance. Recreating middleware permits replay; full checkpoint failure was not reproduced. |
| Observed target does not establish complete review | deep_runtime.py:141 records an ID after any nonempty result slice; workspace.py:384 checks only that ID was observed | P2 assurance limitation, not evidence that current reviewer skipped the draft; blocks claims of guaranteed full or correct review | Keep identity linkage as a narrow provenance check. Do not add per-word semantic gates; evaluate actual review quality separately. This run has full draft pagination evidence. |
| Graph revision reassessment remains incomplete | knowledge_state.py:23 detects noncurrent adopted facts; no completed producer impact-reassessment loop | P2; blocks dynamic knowledge-change acceptance, not frozen-input draft testing | Preserve needs_attention and unknown distinctions; do not automatically rewrite downstream work or call it current. Follow existing deferred disposition. |

### Framework Reuse And Remaining Complexity

Anscombe groups the reviewed controls into 17 purposes, not an exhaustive count
of predicates, tools, tests or mandatory workflow stages:

| Group | Control purpose | Category |
| --- | --- | --- |
| 1 | Role tools, result kinds and server-bound producer ownership | Permission/consistency/reliability |
| 2 | Project isolation and virtual filesystem capability boundary | Permission/consistency/reliability |
| 3 | Authorized model and service configuration | Permission/consistency/reliability |
| 4 | Project run mutex and role-local serial tools | Permission/consistency/reliability |
| 5 | Submission identity, immutable receipts and transaction idempotency | Permission/consistency/reliability |
| 6 | Explicit predecessor and exact review-target normalization | Permission/consistency/reliability |
| 7 | Adopted-version impact propagation and graph freshness projection | Permission/consistency/reliability |
| 8 | Pagination, ranges and tool argument validity | Permission/consistency/reliability |
| 9 | Native checkpoint resume and saved human-answer mapping | Permission/consistency/reliability |
| 10 | SDK transport retries and timeouts | Permission/consistency/reliability |
| 11 | Optional bounded text-analysis cache/reuse | Permission/consistency/reliability |
| 12 | Exact-version independent review and delivery status | Semantic/process boundary |
| 13 | Source conflicts/missing material referred to humans | Semantic/process boundary |
| 14 | Automatic inheritance and forced union of revision dependencies | Semantic/process control to narrow |
| 15 | Three consecutive identical calls cause hard stop | Semantic/process control to narrow |
| 16 | Custom runtime status/checkpoint flag mirrors | Framework-overlapping projection |
| 17 | Custom model/tool audit events and GUI polling | Framework-overlapping observation |

The first category contains framework configuration as well as application checks;
17 does not mean 17 custom reimplementations. A control's legitimate purpose does
not prove its implementation correct or its complexity minimal.

- Native create_deep_agent owns model/tool iteration; SubAgentMiddleware owns
  delegation/context isolation. Application configuration defines available
  knowledge/writer/reviewer capabilities, not an obligatory sequence. Root can
  write without delegating to a writer; graph use is not mandatory.
- TodoListMiddleware, StateBackend/file middleware and native context management
  are configured. Configured summarization is not proof it triggered in every run.
- AsyncSqliteSaver owns checkpoints; interrupt/Command own pause/resume. Saved
  operator answers and GUI projection adapt these primitives to the application;
  they are not an independently implemented reasoning scheduler.
- Provider integration supplies retry handling (max_retries=2) and explicit
  technical timeouts. There is no aggregate model-call/token quota.
- Project isolation, producer permissions, immutable artifacts and transactional
  receipts remain application responsibilities. Native checkpoint persistence is
  not an exactly-once guarantee for SQL/Neo4j side effects.
- Custom report status mirrors and custom audit events overlap framework state
  and events. They are maintenance risks to simplify, not confirmed evidence of
  a second scheduler. Business result status is distinct from execution state.
- Tools remain too granular for some work: the synthetic graph run issued 13
  fact writes and 25 relation writes and took 82 model requests. Consider a
  meaningful batch write/read capability; this is not evidence that all 82 calls
  were caused by program controls, nor authorization for concurrent execution.
- Skills editors, unrestricted shell, dynamic role creation, concurrency and
  self-evolution are not required merely to use every framework feature.

Anscombe's conclusion: direction accepted with semantic-boundary and reliability
reservations. Main agrees: core framework reuse is established; complete business
conformance, minimal complexity and improved efficiency are not established.
The latest 297-test result is prior program evidence, not fresh tests in this
review or proof of autonomous quality. Real audit remains 143 model starts,
141 responses, 12 rejected-tool events, four committed results and two technical
human clarifications; historical rejected calls include subsequently fixed issues.

Official references checked for capability/pattern interpretation (installed
DeepAgents 0.7.19 source governs actual available behavior):
- https://docs.langchain.com/oss/python/deepagents/overview
- https://docs.cloud.google.com/architecture/choose-design-pattern-agentic-ai-system

Next recommended changes are narrowing the repeat guard and removing automatic
dependency adoption, then improving tool granularity and business human-decision
handling. They are recommendations in this review, not implemented repairs.
