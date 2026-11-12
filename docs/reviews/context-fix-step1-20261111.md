# Context fix — Step 1 review packet

Source code added/removed: **0/0**. Product checks/guards added/removed: **0/0**. New fallback paths: **0**.
**Status: proposed; Step 1 prepared, owner selected classifier removal, implementation/review still pending.** Baseline: ead8bf5096f000d677df288ae253c9a2a29e1df8.
Main remains 7da4f9483a08a3a975ce05f7b559a56d9f626511.

This packet implements the documentation step of the owner's **Context Fix Plan (2)**, supplied 11 November 2026.
It does not authorize a full regression, a paid probe, a cap change or a main move.
Steps 2–4 follow the separate reviews in that plan; Step 5 and Step 6 require separate owner authorizations.
The 5.0M Coordinator input estimate is a local proxy, not provider spending.

## 1. Findings and proposed boundary

The reproduced request-growth finding is **P2**, blocking acceptance of the current context/cost design for the planning probe, not unrelated offline work.
At the baseline, TaskContext renders effective state, constructs a full/delta2 frame, and after a successful model response saves its receipt and prepends the frame to the returned model result.
The next model call therefore resends earlier state. See [TaskContext](../../src/report_agent/task_context.py#L509) and [prepare_delivery](../../src/report_agent/task_state_delivery.py#L243).

**C1 replacement:** keep the existing projection and additions; render their effective value at the request boundary, once, in a call-local tail.
Use the existing observation finalizer rather than adding another state store or middleware framework.
The tail carries current state, dynamic declared contributions and budget observations in distinct fields.
No tail is returned in ModelResponse, ExtendedModelResponse or Command updates. No frame/receipt is written.
Read committed state after preceding tools finish; do not join case, task, assertion and budget databases in one transaction.
Keep the original user task independently of program-authored notes.

The existing trust boundary is required, even though saved frames are not: user/tool lookalikes must not acquire host authority; counters must not become permissions; a summary must not override current instructions.
Keep call-local actor binding, marker escaping, exact-wire composition and recovery checks. A history marker is ordinary message content, never host authority. No stored frame receipt can promote it. Do not add an assertion or digest for the new tail.

## 2. C1/C4 file change list — proposed, no source edits yet

Paths below are under src/report_agent unless a different root is shown. “Reader” names the concrete consumer, not a possible future use.

| File | Add/change, requirement and reader | Remove |
| --- | --- | --- |
| [task_state_delivery.py](../../src/report_agent/task_state_delivery.py) | Extend the existing call-local observation scope/finalizer to carry the effective state supplied by TaskContext. C1 reader: final outgoing model request and existing prompt/recovery comparisons. Retain spoofing protection and business-message classification. | New full/delta/delta2 frame construction, delta comparison, occurrence IDs and receipt writes; history-chain reconstruction. The owner-selected classifier removal is detailed below. |
| [task_context.py](../../src/report_agent/task_context.py) | Supply exactly the current compact projection, current user task, scoped instructions, complete review materials when required, received returns and separate resources to that finalizer. C1 reader: same actor's current request. Preserve existing tool-result projection and page/image delivery behavior. | prepare_delivery/persist_frame calls and response-result frame insertion. No replacement history snapshots. |
| [prompt_provenance.py](../../src/report_agent/prompt_provenance.py) | Finalize the same shared tail after all declared contributions; preserve it across nested same-actor scopes. C1 reader: AgentPromptBoundary capture, final HTTP offer checks and prompt-context delivery. Keep prompt captures and source manifests. | Wording telling the agent to reconstruct a saved full/delta chain; duplicate state rendering. No new capture-body store. |
| [fake_draft_flow.py](../../src/report_agent/fake_draft_flow.py) | Wire the existing AgentPromptBoundary for the standalone Reviewer and prose Writer, using the same role/profile that built their prompt. C4 reader: final request capture and shared observation finalizer. Test exact prompt/tool equivalence; do not inject TaskContext into either path. | No agent, role, scheduling step or approval is removed or added. |
| [working_summary.py](../../src/report_agent/working_summary.py) | Summarize ordinary C1 business history; call-local host state is never part of that saved history. C1 reader: existing summary input. | Delete verified_frame filtering/import. Do not change summary trigger, model, output limits or recovery policy. |
| [tool_trace.py](../../src/report_agent/tool_trace.py) | Add the existing prompt call ID to model-start/outcome and inherited tool rows. Step 1 trace reader: operator joins the model turn to existing offered/final captures. Null remains a capture gap, never guessed. | No new transcript, receipt, digest, counter or clearing event is needed. |
| [deep_runtime.py](../../src/report_agent/deep_runtime.py#L1029), admission and builder metadata only; [native_trace.py](../../src/report_agent/native_trace.py#L155), read-only checkpoint inspection | Owner-required boundary: refuse pre-C1 history before live startup opens a writable saver or changes status. Reuse native checkpoint metadata, with a C1 context-delivery discriminator supplied by the builder; admission is its reader. Empty/new history is allowed, C1 history keeps normal owner waits. | Remove the obsolete rubric-upgrade attribute/branch and its comment; no frame migration, history rewrite, fresh-thread workaround or automatic redo. Graph routing/scheduling stay unchanged. |
| Existing task-state, prompt, recovery, summary, handoff and repetition tests; tests/support/task_state_contract.py | Replace frame-history assertions with current-tail assertions; retain the business/trust/recovery requirements. V2 reader: old effective-state oracle compared with actual outgoing state at every scripted call. | Retire only full/delta serialization expectations, with a named replacement per removed test. Do not retire source, image, operation-identity or unknown-outcome protections. |
| Proposed tests/test_context_call_delivery.py and tests/test_context_wiring.py | V1/V2/V6 and four-path wiring checks through native entry points, including response/Command variants and failure before/after model response. Reader: focused C1 acceptance record. Share the current fake-flow fixture instead of copying it. | No new test infrastructure, dependency or fixture data family. |
| docs/reviews and tasks/plan.md, tasks/todo.md | Short review/result pointers required by the owner's staged review. | No historical verification record is rewritten. |

The native [middleware factory](../../src/report_agent/deep_runtime.py#L1083) already installs TaskContext and AgentPromptBoundary; its middleware wiring does not need an edit. The owner-directed old-history removal adds only admission and builder-metadata work in that file, plus deletion of the unreachable legacy rubric-upgrade branch. This is a narrow history-lifecycle exception, not a dispatcher redesign.
**Dispatcher protected:** no changes to delegation/dispatch routing, graph topology, scheduling, task storage or operator launch safety. The only proposed run_report change is deleting the obsolete rubric-upgrade branch at baseline lines 1261–1266. Do not claim the entire dispatcher file/function is byte-identical after that deletion. Normal C1 owner checkpoint handling remains intact.
No S2, scoring, export, budget, role prompt or ledger changes belong to C1.
C3's indicator reading-allowance placement is a later edit, not smuggled into this C1 list.

## 3. C4 wiring matrix

One shared implementation in task_state_delivery.py; do not install full global state in bounded tasks merely to make the rows look uniform.

| Actual path at baseline | Frames today | C1 / call-local state | C2 decision for later Step 3 | Toolset changes |
| --- | --- | --- | --- | --- |
| Native Coordinator: deep_runtime.build_agent → middleware(coordinator) | Yes when TaskContext is enabled | Replace history frames with same effective current-state tail. Keep both current resources and moved dynamic blocks. | Long-session candidate; only tools proven immutable/refetchable and still offered can be cleared. Inventory first. | May change through native tool selection; compare prefix only within identical offered-toolset phases. |
| Indicator Writer: IndicatorRun.run → create_agent | No TaskContext/frame chain | Keep bounded assignment, current page results and existing prompt boundary. No global state injection. Shared finalizer handles only declared local changes/resources when applicable. | **None:** keep all active-indicator evidence until save; three-read limit unchanged. | read_assigned_page disappears after three attempts; issue/save availability also changes. |
| Qualitative Reviewer: fake_draft_flow.complete → create_agent | None | Keep frozen row tools and assigned task. Add existing final prompt boundary, not TaskContext. No invented current-state fields. | Bounded review task: no clearing in this plan; preserve evidence for its findings. | Fixed tool catalog today. |
| Prose Writer: fake_draft_flow.complete → create_agent | None | Keep delegated scope and current BusinessBoundary contributions; add final prompt boundary using the same shared tail helper. No global projection. | Bounded section task: no clearing in this plan. Any later long-session treatment needs the Step 3 inventory and recovery proof. | Fixed catalog today; compare the actually offered schema, not an assumed role catalog. |
| Native delegated Writer / Reviewer / Layout | Same shared native factory as Coordinator, when context enabled | Inherit C1 through TaskContext; preserve each actor's scoped projection, review materials and resources. | Decide by actual session shape at Step 3; role name alone never enables clearing. | Native selection/review tools can change. |
| Supporting summary / vision / text services | No independent host-frame chain | Keep their current bounded contract; no TaskContext added. Owner-role accounting is unchanged. | No clearing of bounded supporting calls. | Their existing contract decides catalog. |

Bounded means the current task's evidence stays visible, not that its prompt is free of all dynamic observations.
No paid Writer/Reviewer request becomes permitted merely because its wiring is tested.

## 4. Saved-frame receipt reader census and disposition

The baseline has **one receipt writer**, persist_frame, called from TaskContext after the model returns.
The persisted receipt contains actor_id and content_digest; no scoring or report computation reads it.
All production modules importing task_state_delivery are accounted for below.

| Reader / caller | What actually depends on it | Proposed disposition |
| --- | --- | --- |
| prepare_delivery → verified_frame/store.get(task_state_frame:…) | Classifies history, validates actor, reconstructs full/delta chain and decides next frame. | Remove chain reconstruction and new writer entirely. Delete verified_frame, frame_delivery and their receipt-based trust path as well; fresh C1 calls do not need them. |
| business_messages → verified_frame | Separates host frames from business dialogue. Called by BusinessBoundary in deep_runtime and KnownWriteRepetition.scope. Protects original task/repetition interpretation. | Delete the saved-frame filtering dependency. Use only call-local identity for a newly injected tail; ordinary saved history never gains authority from a receipt. |
| WorkingSummary._acreate_summary → verified_frame | Excludes authenticated host frames from historical summary text. | Delete verified_frame filtering/import: C1 saves no host tail. No summary-trigger change. |
| current_user_task → FRAME/MODEL_COMMAND markers | Distinguishes direct user goal from host frames, program-authored notes and summaries. No receipt read itself. | Delete the obsolete FRAME skip/import; keep program-authored-note/summary separation. A call-local tail must not replace the user task. |
| prompt_provenance → observation_delivery, finalize_observations, STATE_EXPLANATION, DYNAMIC_SOURCES | Final request/capture composition and current scoped-instruction delivery. **Not a stored-frame receipt consumer.** | Keep and adapt the shared current-tail boundary; replace only frame-chain wording. |
| model_recovery → normalize_observations, delivery_layout | Compares exact business requests while treating volatile budget counters as observations. Prevents wrong request reuse/redispatch. **Not a frame receipt consumer.** | Keep; include all effective business state in request identity. Retain existing unknown/hold protections and the tests that prevent a changed layout from replaying an unknown request; no extra request or replay. |
| live_messages → observation_semantics | Offered-message comparison ignores only permitted volatile counters. **Not a frame receipt consumer.** | Keep exact business data comparison with the new tail. |
| planning_guard → MODEL_COMMAND | Marks operator guidance so it does not replace the original goal. **Not a receipt consumer.** | Keep unchanged. |
| tool_selection → model_response | Unwraps native model/Command results. **Not a receipt consumer.** | Keep unchanged, including Command updates. |

**Owner decision (11 November 2026): remove the classifier as well.** No current requirement found in this trace needs receipt-authorized historical frames inside a new live agent. Historical transcripts stay readable on their writing tag/commit; originals remain unchanged. The earlier recommendation to retain a read-only classifier is superseded, not implemented.

### 4a. The requested pre-C1 live-history check

**Result: a live checkpoint-reopen path exists.** This is confirmed by source/caller tracing, not by reopening a real case or making a model call.

| Location at baseline ead8bf5 | Evidence / consequence |
| --- | --- |
| deep_runtime.require_native_runtime, 1029–1041 | Rejects retired runtime/review profiles, but does not check a history's C1 delivery generation. Pre-C1 native delegated cases are not the retired ADK/rubric case rejected here. |
| project_agent, 1187–1188 | Opens that case's checkpoints.db with AsyncSqliteSaver and passes it to the newly built current agent. |
| run_report, 1242 and 1257 | Uses the fixed thread ID report and reads its existing snapshot. No code-version/layout barrier is tested at this point. |
| run_report, 1269–1301 and 1326 | With interrupts, sends Command(resume=answers); with pending nodes, sends an update/None; otherwise supplies a new user message to the same checkpointer/thread. A new message does not itself select a fresh thread. |
| CLI report-run (cli.py:119–121), web run_guarded (webapp.py:160–162), Fake03 plan (fake_draft_flow.py:43–46) | All reach that same run_report entry. Fake03's prepared fresh case avoids old history, but the generic entry does not. |
| Legacy upgrade comment (1162), attribute (1163), and branch (1261–1266) | Refer to the old rubric middleware. Admission and build_agent reject native-rubric/non-native execution before it can be active on the supported production path. Remove these obsolete production remnants; do not mistake their deletion alone for closing the general reopen path. |
| native_trace.inspect_checkpoint / recent_tool_events / read_trace | Inspect or display native messages; none consumes verified_frame or grants host authority from a frame receipt. They supply no exception requiring the classifier. No change to raw transcript display is needed for classifier removal. |

**Minimal proposed boundary for Step 2:** reuse the read-only native checkpoint inspection at require_native_runtime, which already runs before locks/status/writable checkpoint setup. Tag C1-created checkpoint metadata through build_agent's existing runtime metadata as a context-delivery contract (one discriminator, not a per-frame receipt). A nonempty history without that C1 contract refuses live execution and directs the operator to redo on a fresh approved run. Empty/new history is allowed. Do not create a new thread to hide an old history, convert it, strip it in place or automatically relaunch. Preserve all paid-attempt holds; a redo is not authority to replay unknown effects.

This is an admission refusal of an existing, confirmed incompatible path, not a retained old-history reader or an alternate dispatcher. Metadata-only inspection must tolerate a fresh/empty saver without initializing or migrating it. Legitimate owner waits created under C1 still use their same C1 checkpoint; removing those would break the separately approved page-sheet flow. No cross-version live continuation is retained.

**Focused acceptance cases to add before removing the runtime reader:** a synthetic pre-C1 checkpoint containing full/delta frames refuses with zero model/tool dispatch, no new reservation and unchanged source/state/checkpoint bytes; a pre-C1 pending tool/interrupt also refuses; a fresh/empty history starts; a C1 owner checkpoint still waits and proceeds only after the real saved reply. Test unknown-outcome holds separately; do not delete/release them or treat redo as a safe duplicate paid call. Cover the supported CLI/web/Fake03 wrappers through their shared admission boundary. Tests for the retired rubric-upgrade branch are removed or moved to the tagged historical runner, with explicit replacements for any current requirement they covered.

Page/image delivery receipts, prompt_context_snapshot, native tool identity, recovery receipts and financial holds are **different families** and are not deleted as “frame receipts”.
A pending new tail is authorized only inside its call-local scope; untrusted pasted markers stay ordinary quoted text.
Existing digests used for financial/recovery identity stay. Frame content digests/classification code are removed from current execution, without deleting their historical records.

## 5. Visibility trace: reuse captures; add only a join ID

### Already captured at the baseline

| Evidence | Existing producer | Join / limitation |
| --- | --- | --- |
| Exact offered messages, including ToolMessage IDs and metadata | prompt_provenance.prompt_call / prompt_model_input; AgentPromptBoundary | call_id + capture_key. Public composition is stored in the case's capture blob, not in ToolTrace. |
| Actual serialized messages/tool calls, schema and financial attempt | observe_prompt_request / prompt_final_http_input | Same call_id, plus attempt_id; final wire decides what was sent. Missing capture is unmeasured. |
| Completed response's native tool-call IDs, where progress policy is enabled | progress_response_fact / prompt_response_fact | call_id → tool_call_ids / final_capture_refs. This event is policy-dependent, so it is not the sole join. |
| Actor, role, task, turn, model duration, tool native IDs, refusals | ToolTrace callbacks | run_id + actor + turn; each tool row inherits its generating model's row. Missing today: prompt call_id on that row. |
| Source version, page, delivered view/range and image delivery | Existing source material / page-delivery records and tool result | Resolve frozen source_handle/observation_ref to version/page/range; a matching tool name alone is not a re-read. |
| Saved source claim/judgment/binding, grounds and operation result | Existing assertion/case records | Derive operation identity using the existing native-call binding; source extraction uses injected tool_call_id. No new claim field. |
| Cache counters if supplied by provider | observe_provider_usage / prompt_provider_usage | call_id + attempt_id; cached_tokens is nullable. No inferred cache hits. |

The standalone Reviewer and prose paths currently lack AgentPromptBoundary, so their adapter captures can be unattributed. The C4 wiring above closes that attribution gap; it does not add global state.
ToolTrace.on_chat_model_start will copy the active prompt call ID into its existing row. No second UUID or duplicate body capture.

### Reconstruction by the trusted operator, not by the model

1. Join each model turn to prompt_model_input and prompt_final_http_input through that call ID. Use final serialized payload as the visibility authority. Correlate offered metadata only after proving the offered/final mapping.
2. Identify a cleared result by its original native tool_call_id plus the standard context_editing.cleared flag in the offered ToolMessage, and verify the fixed placeholder on the wire. Preserve the original call arguments.
3. Resolve the original result to immutable source version/page/view or exact observation range using the existing records. Track actor/task boundaries; visibility in another agent's call is not this agent's evidence.
4. A later successful read counts as a re-read only for that same frozen content and relevant range/view, and only if its returned content appears in a subsequent request. A merely requested, rejected or cleared-again read is not visible evidence.
5. Join the save tool call to its generating model turn and existing persisted operation result through the public case/assertion readers, without opening the assertion database outside its module. This works even when there is no subsequent model call after a successful save. Report committed, refused and unknown outcomes separately.
6. For each claim ground/source, list cleared-before-save results, any later visible re-read, and any still-visible equivalent evidence (retained fact, current task, quote or other result). Flag “cleared, no visible re-read” for human inspection; do not equate it automatically with a wrong claim.
7. Report incomplete joins/captures as unmeasured, with the missing identifier named. Never infer visibility from a delivery receipt alone, timestamp proximity or the existence of an exact quote in storage.

Private review rows: run/actor/task; prompt call and attempt; original tool_call_id; frozen page/range/view; first request with cleared result; visible re-read request if any; save native ID and saved record; still-visible support; manual verdict.
These are derived review output, **not** new runtime schema, stored receipts or model-supplied fields.

**Two existing clearing mechanisms must not be confused:** TaskContext.abefore_model already marks report_preview_cleared navigation ranges; metadata_observations can clear identity previews.
The replay/probe report distinguishes these from the new request-local C2 edit. Do not count those old flags as evidence that C2 ran.
All active indicator-Writer pages remain visible. The Coordinator proposes page bindings, not extracted values, so the planning-only probe checks binding decisions without requiring extraction quotes.
Actual Writer extraction/judgment effects can only be measured in a separately authorized continuation/full flow; a Coordinator-only probe cannot prove them.

## 6. Implementation and review checks, not results

- **Step 1 now:** check source anchors, complete the nine-import consumer census and four primary wiring paths, and record the owner-selected classifier removal plus the live-checkpoint path check. No runtime test result is claimed.
- **Step 2 C1:** first make focused tests fail for history insertion/receipt writes and pre-C1 live admission, then replace the path. At each scripted model boundary, compare independently reconstructed old effective state with the new current tail, including nested removals, JSON types, user task, review material, received returns and current resources. Compare business state exactly; label counters separately without discarding them from V2.
- Capture committed state once at the boundary for both the baseline oracle and the new renderer; do not have the expected side call the new renderer. No transaction across databases or atomic-snapshot promise across independent stores.
- Exercise all matrix paths; failed model calls leave no saved tail; ExtendedModelResponse/Command output preserves all program-authored messages. Native factory and dispatcher behavior remain unchanged.
- Map every retired delta/history test to a specific replacement test before deleting it. The existing tests named in section 2 are discovery scope, not permission to weaken them.
- Run focused V1/V2/V6 for C1 alone. Report per-call/max/total component sizes; do not report reduced requests until measured.
- **Step 3/4 later:** clearable/excluded business-tool inventory and independent review before C2. Use installed ContextEditingMiddleware + ClearToolUsesEdit with a static placeholder, keep arguments/IDs, and verify actual full-stack clearing. Retain the six known semantic-defect cases and ten controls. Do not raise the reading allowance or add re-read prompt instructions.
- **V5:** compare prefix bytes only while offered tools are unchanged, without persisting another digest. Stable prefix is not a provider cache-hit measurement. Existing nullable provider counters are enough; do not install a caching/telemetry service.
- **V7:** cross the actual WorkingSummary threshold and report its firing/request size. Summarization changes require a separate proposal.
- **Step 5:** one separately authorized full offline regression on the final candidate with verified private fixtures and automatic cleanup; current full-suite authority is absent.
- **Step 6/7:** size the planning-only probe from V1, obtain scope/cap/one-launch authority, then judge correctness before cost. Keep every prior usage row, unknown outcome and historical 2M hold.

## 7. Review handoff

- Main: source/caller inventory and Step 1 documentation prepared; no implementation.
- Neo and owner's advisor: **review pending**, no approval attributed to them.
- Owner: **remove classifier**, confirmed in the current chat; no full-run or probe authority requested by this packet.
- No application/test/config/S2/dispatcher files changed in this documentation step. No model calls, service installs, financial reads/writes, main move or historical-case mutation.

Skills applied: planning/task breakdown and documentation for this packet; Ponytail for deletion-first scope; direct code inspection because Graphify is unavailable in the owning environment; existing local capture design informed the trace review.
Langfuse is not connected for this task; no service dependency or upload is introduced.

Documentation verification: eleven local links resolved; baseline production/test/config/script trees unchanged; git whitespace check passed. No focused or full runtime suite was run for this documentation-only step.

Owner disposition follow-up: classifier retention rejected; the live old-history path and proposed admission-only retirement are now recorded. Source-level check only; no historical database was opened and no runtime regression was run.
