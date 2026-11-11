# Fake03 full draft flow — offline review candidate

Production source +193 / −35 (net +158); refusal guards +3 / −0; tools +1 / −0; fallback +1 (physical PDF lookup for empty-text pages). No tests retired or dependencies added. Dispatcher and S2 are byte-identical to accepted b2; main stays `14484f8`. No paid request, ledger change or historical-case edit.

## Scope and changes

The owner selected the full live draft flow. New preparation imports originals, raw requirements and reviewed method metadata, without a saved plan, owner approval, extracted values or verifier answers. The Coordinator uses the current native incremental tools. Its unanswered checkpoint makes no further model call; the owner’s one reply confirms the saved page sheet before any Writer request.

| Files | Requirement and reader |
| --- | --- |
| `mini_commission.py`, `fake_draft_flow.py` | Import-only preparation and shared reviewed metadata; native Coordinator, Writer, Reviewer and exporter consume them. |
| `commission_planning.py` | Explicit `publish_planning_draft` saves a plan before bindings. Submission reuses unchanged content without discarding caller operation identity. Verified Word quotations supply fixed text; the assembler receives the report title. |
| `operation_identity.py`, `planning_guard.py` | Host supplies the publication tool’s native ID; existing planning containment counts its refusals. |
| `page_bindings.py` | Blank-text drawing pages are checked against the original PDF. Binding proposals never publish plans. |
| `live_messages.py` | Authenticated row-review tasks retain their frozen-row interface rather than entering whole-report message checks. |
| New flow tests and verifier v2 | Current preparation and real tool path through owner reply, fresh extraction, independent review and paired draft export. |

The trusted operator hands off after the saved reply; it does not resume or change the dispatcher. Existing per-indicator Writers and the Writer text service choose their own tool calls. Missing Reviewer findings or interrupted Writer work block export. The old Writer-only paid CLI remains unchanged and is not the full-flow launcher.

## Evidence

Main ran **148 focused tests: all passed in 235.7 seconds**, on the final source/test files. Only model answers are scripted; business writes are real. [Measurements and file hashes](../verification/fake03-post-9a/offline-flow-results.json) record:

- 61 scripted Coordinator calls; 39 Writer calls plus 3 supporting text calls; 48 Reviewer calls. **0 provider requests / 0 provider tokens.**
- 22 saved rows, 22 independent findings, 2 fresh extracted facts still marked proposed.
- One frozen snapshot; 23 Word 待核 comments matched to 23 Excel issue rows, plus 5 来源 comments.
- Eleven LibreOffice pages inspected; final page pixels match those inspected. Native Word and Excel print layout were not checked.

The test also proves its script-data builder writes no case objects. Failed attempts, negative tests and self-review corrections remain in `.private/stage1-9a-paid-preparation-20261111/full-flow/`. Passing temporary cases are cleaned automatically. Generic scripted gap reasons establish plumbing, not paid judgment quality. Accepted-b2 cosmetic/instruction-text notes are unchanged.

## Remaining launch gates

1. Review frozen [key v2](../verification/fake03-post-9a/answer-key-v2.json) and its [manifest](../verification/fake03-post-9a/manifest-v2.json): 22 Coordinator bindings, 16 qualitative expectations, six unscored numeric positions, Chinese text and real-trace refusal measurement. V1 is unchanged. Real-model quality remains unmeasured.
2. One separately authorized full offline regression; none is inferred from this flow choice.
3. A trusted multi-role launch envelope with exact models, command, scope and cap. Read-only reconciliation found separate DeepSeek-only and GLM-only ledgers, not a shared full-flow guard. Both budgets and all holds remain unchanged. The old 16-row pilot scope cannot silently become 22 paid steps; no numeric-rule certification or formal release is claimed.
