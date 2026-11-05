# G5 stopped rescue: W-plan review baseline

**Review baseline only. Execution remains stopped. No W implementation or new model call is authorized by this tag.**

The tag includes every committed G5 rescue change after launch baseline5509f749: export fixes, deterministic assembler, source-binding fix, bounded rescue and unknown-summary guards, and the latest checkpoint-validation work. Existing history is retained; no squashing or rewriting. Original G5 classification remains **stopped during export; content assembled**. Draft scoring content is not a canonical assessment.

## Stopped state

At 2026-11-05T21:15:05.342291+00:00: no matching original G5 or assessment-rescue process, including all four saved PID/UID/start-tick identities. The exact unresolved2M ledger row and old unknown-summary recovery record are unchanged. The full ledger equals the pre-continuation snapshot. Current rescue: **8,733,638 settled +2,000,000 held**, existing20M cap,9,266,362 available after that hold. No local-preflight-repair launch occurred. Original G5 final settled usage89,936,039; its records and historical holds remain preserved.

## Included code and validation status

| Component | Included work | Status / limit |
|---|---|---|
| Export | Own-node rendered comment anchoring, MI-3-2-01 regression; automatic paired Word/Excel from one frozen snapshot and issue set; existing content/citation/fixed-text checks | Implemented/tested; no final G5 delivery produced |
| Assembler | System-owned structure/fixed sections/assessment-derived tables/chapter5; audited prose projection and required-issue bindings; reject agent-authored score tables in prose | Implemented/tested; final current-case assembly awaits five canonical assessments |
| Source binding b63db58 | Recognize identical frozen guideline captures by source_id/file digest/exact content; retain quote, source-use and factual-source guards | Local regressions passed; no successful canonical assessment yet |
| Rescue b66e689 /51cd411 /f2e4622 | Writer-only task, original cumulative10M then20M baseline, exact unknown2M hold preservation, old key/payload/wire replay fences, genuine owner authority in native summary and declared Writer system contribution |147 affected tests passed at f2e4622; actual next launch stopped before model invocation |
| Checkpoint387553b | Accept only exact pinned failed-model task with files-only native partial-result digest; fixed derivative known-pre-send repair path preserves the consumed receipt and requires identical whole finance snapshot/no model events | **Work in progress for integration:86 local tests + actual offline-copy guard proof passed; live continuation NOT exercised; repair launch NOT run** |

The checkpoint failure was our validator assuming next=(model,). Native LangGraph omits a task with pending file writes from next even though its sole errored model task remains. No model request or extra ledger row was produced by that local failure. No manual checkpoint mutation is used by the repair.

## Step0: exactly where the first8.1M went

First rescue phase:15:13:51–16:18:26 UTC, **8,097,818 settled tokens**, zero held;75 invocations,74 returned usage records and one known-not-sent budget refusal. Prompt7,892,687; completion205,131; prompt share97.47%. Median prompt101,153 tokens, maximum187,435. No cache credit was recorded. Input share alone is not a measurement of waste.

Each group below is the provider usage of the returned model response that selected that action. Native reads themselves are not separately charged model calls. All74 response usages reconcile one-to-one to financial attempts.

| Selected action / model purpose | Returned calls | Prompt | Completion | Total |
|---|---:|---:|---:|---:|
| project_status | 2 | 141,379 | 4,242 | 145,621 |
| search_sources | 20 | 2,423,590 | 39,943 | 2,463,533 |
| inspect_source_page | 7 | 809,675 | 30,308 | 839,983 |
| read_commission_plan | 2 | 122,812 | 2,118 | 124,930 |
| read_file | 2 | 154,385 | 483 | 154,868 |
| grep | 4 | 360,586 | 2,818 | 363,404 |
| read_tool_observation | 13 | 1,404,907 | 51,765 | 1,456,672 |
| read_object_index | 7 | 495,299 | 4,770 | 500,069 |
| read_context | 8 | 754,781 | 4,307 | 759,088 |
| calculate_assessment | 5 | 700,008 | 32,503 | 732,511 |
| get_operation_receipt | 1 | 146,453 | 220 | 146,673 |
| native_context_summary | 3 | 378,812 | 31,654 | 410,466 |
| **Total** | **74** | **7,892,687** | **205,131** | **8,097,818** |

- **Before first assessment submission:**54 returned requests,5,391,997 tokens. This includes evidence searches/page inspection and navigation of plans, objects, context and offloaded observations.
- **First through last submission:**7 requests,1,018,493 tokens; five submission attempts plus an observation read and operation-receipt lookup. The five responses selecting submissions account for732,511 tokens.
- **After the last submission:**13 returned requests,1,687,328 tokens; further searches/context/observation reads and one native summary, with no further assessment submission.
- **Result:**five rejected submissions, all for HP01; zero canonical assessments,55 indicator judgments still not canonically saved. Other four slopes had no assessment submission.
- **Stop:**the next2M reservation would exceed the10M cap;1,902,182 remained. This was budget admission, not10M actual spend or evidence that the full grant was exhausted.

Three supporting requests (410,466 tokens) were recorded historically as unattributed:writer/unexplained. Their full formatted native summary-prompt prefix/suffix, single user message and zero tools establish that they were native context summaries charged to Writer. This derived diagnosis does not rewrite those historical captures. Developer-agent tokens/calls/time are unavailable.

## Every assessment refusal, including upstream refusals

The public tool is calculate_assessment. Of its five refusals, three entered save_assessment; two stopped earlier. All five are included so no failure is hidden by that naming distinction. Each occurred once, deduplicated by actor/native tool-call ID.

| Code | Boundary | Diagnosis |
|---|---|---|
| `NATIVE_TOOL_VALIDATION_ERROR` | Native typed-argument validation, before save_assessment | Unexpected top-level assessment.question field; no canonical save was attempted. |
| `ASSESSMENT_INVALID` | risk_scoring.save_assessment identity validation | The reported message says method identity/version mismatch; actual submitted version2 matched, but method_id was wrong. |
| `OPERATION_CONFLICT` | ContentStore.operation idempotency guard, before a new save_assessment | Reused the prior failed operation_id with a changed method_id/payload. This is a legitimate changed-request conflict; no duplicate save. |
| `COMMISSION_QUOTE_NOT_AT_SOURCE_LOCATION` | Source/locator validation inside save_assessment | An indicator source quote did not match its supplied locator. Preserve the exact quote/location guard; no inference that the whole source was absent. |
| `ASSESSMENT_GUIDELINE_RULE_SOURCE_REQUIRED` | Guideline-rule source validation inside save_assessment | X11 cited an equivalent frozen capture of the same guideline, with equal source_id/file digest/exact text but a different ContentStore Ref. This was a system identity bug, not missing guideline evidence. Fixed in b63db58; strict content/source/permission checks remain. |

There were nine recorded tool rejections overall; the other four were non-assessment tool errors. The operation conflict was a changed request using the same ID, not proof of an identical cached-failure replay. The earlier description of X11 as missing guideline evidence is superseded by the verified source-identity diagnosis.

## Inputs for W review, not implementation decisions

The evidence supports reviewing system-bound method identity/source identity/operation IDs, precise schema and locator feedback, useful compact retrieval, and visibility of long read/repair sequences before building Writer tools. It does not justify lowering source checks, promoting draft tables, inventing judgments, or claiming all97.47% input tokens were wasted. The assembler must be reviewed against canonical assessment inputs; software tests are not engineering acceptance.

Final Word/Excel export, rendered pages/TOC,25 required issues and nine-item acceptance verification remain **not completed**. The later unknown-summary transport failure has no verified response or usage; its2M hold remains intact. The checkpoint repair's live behavior remains unverified.

## Audit files and boundaries

- [Machine-readable diagnosis](g5-step0-diagnosis-20261105.json) includes every refusal/native-call ID, exact spending groups, timeline, code commits, stopped-state proof and limitations.
- [All74 paid calls](g5-step0-calls-20261105.csv) contains timestamps, financial attempt IDs, action names and provider counters, with no prompts, source quotes, reasoning or assessment values.
- Private original evidence stays in the existing G5 monitor/rescue evidence directories; no raw case/ledger/sources are copied into Git. No remote push, restart, release of holds, new case or paid test is part of this baseline.
- Unrelated pre-existing G4 backlog changes in tasks/todo.md and tests/fixtures/g4_h34_bookkeeping.json remain untouched and excluded.
