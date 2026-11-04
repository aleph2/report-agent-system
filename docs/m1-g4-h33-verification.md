# G4 H3.3: planning waits and bounded draft reads

2026-11-03 (America/Tijuana). Baseline: approved H3.2 `d93f7e0`.

## Scope and behavior

This patch addresses only review points 1 and 2. It does not start a paid run,
change token limits, approve a plan, merge slope candidates, or enable email.

- In the existing Coordinator-only `PlanningGuard`, a terminal model response
  without valid or invalid tool calls cannot end an unconfirmed commission.
  The shared `_confirmed` check must accept the exact current plan, requirements
  and owner decision; a missing or stale confirmation produces a real native
  interrupt with the current gaps. Existing explicit human waits and malformed
  tool feedback retain their paths. There is no automatic extra model request.
- The wait reuses the existing trusted `Workspace.decide_issue` route. A raw
  LangGraph resume value cannot authorize continuation. A recorded owner note
  returns control to the model, never to the stale terminal answer. The existing
  model-command marker keeps that note from replacing the original report goal.
  A later terminal attempt creates a new wait; the five-rejection counter is not reset.
- `read_planning_draft()` now returns compact gaps first, gap counts, collection
  counts and a version digest. It does not return fixed text, full methods or
  table data by default. `collection` plus `page`/`page_size`, or `item_id`, selects
  details. Each page is exact JSON text in at most 3,000 Unicode-character chunks;
  follow `next_offset` before decoding the concatenated JSON. Nested citations
  remain exact. `view_ref` is required on continuations and rejects changed drafts
  or requirement versions. Large gap lists have explicit `next_gap_page` and
  `detail_id` links to their full diagnostics, rather than silent truncation.
- The internal `read_draft` and canonical saved records remain unchanged.
  New public selector errors reuse the existing field-specific diagnostic helper.

The public read-tool return shape changes intentionally: consumers use the summary
and advertised detail selectors instead of assuming a complete `plan` or requirement
payload is inline. Existing internal submission/validation callers are unaffected.

## Reproduction and verification

Run from the native Linux checkout with its existing owning interpreter:

```bash
PYTHONPATH=src:tests /home/dysun/.venvs/report-agent-system-native/bin/python -m pytest \
  tests/test_m1_g4_h33_guard.py tests/test_m1_g4_h33_pages.py -q
```

The native scripted models use the real DeepAgents graph and checkpoints, without
provider calls. The terminal reproduction records a non-pausing question and then
returns a final answer before approval, as the stopped paid run did. Before this
repair it ended `incomplete` with no resumable interrupt; after repair it waits for
an operator. Tests cover restart of the test host, unchanged waiting without a reply,
trusted note delivery, rejection of raw resume, repeated finals, original-goal
retention, approved and stale plans/requirements, and Coordinator-only registration.

The paging reproduction saves over 80,000 characters of fixed section text before
the old trailing gap list. Tests inspect the actual next model input, recover full
text and citations through bounded reads, retrieve requirement IDs and quotations,
reject stale continuations, and enumerate 1,000 synthetic gaps with explicit pages.

Preserved evidence under `/home/dysun/report-agent-m1/g4-restart-20261103/h33/`:

- `pages-red.log`: 5 failures before pagination; `pages-green01.log`: 5 passes.
- `guard-red.log`: 5 failures and 4 unaffected passes before terminal protection.
- `green01.log`: 15 preliminary passes across both changes.
- `root-task-red.log`: one failing independent-review regression demonstrating that
  an untagged operator continuation replaced the original root task. Fixed using
  the existing model-command marker; final regression includes this assertion.
- Root-level `focused-command.json`, `focused-input-pins.json`, `focused.log`,
  `focused.xml`, `focused-result.json`: preserved first affected batch, 464 passed
  and the two old terminal-expectation failures described below.
- `final/focused-command.json`, `final/focused-input-pins.json`, `final/focused.log`,
  `final/focused.xml`, `final/focused-result.json`: final frozen affected-module
  regression, 466 passed, with before/after input hashes. This is not a new full-suite
  run; prior H3.2 multibatch totals are not relabelled as H3.3 results.
- `neo-design-review.md`, `neo-source-review.json`, `neo-final-review.json`:
  independent design, source and final evidence review; offline completion accepted.

Final affected regression: **466 passed, 0 failed, 0 skipped**, in one invocation
(374.8 seconds including process overhead), across 17 modules. This includes
20 new H3.3 cases. All Python source/test input pins were unchanged during the run.
The complete repository suite was not rerun for this small patch.
After testing, one trailing CR byte in the new guard test was normalized to LF;
AST equality and before/after hashes are recorded in `post-test-whitespace.json`.
No behavior changed after the final batch.

The first affected batch had 464 passes and two expected-behavior failures in the
existing requirement-resume test: it deliberately returned a final answer with no
approved plan and previously required no new issue. The narrowly updated test now
requires exactly one real completion wait while retaining the original issue,
operator decision, requirements checkpoint, current requirement version and absence
of plan approval. The product guard was not weakened. Both original failures and
the separate final all-green affected batch are retained.

## Review and boundaries

Main implemented and executed the checks. Neo independently designed/reviewed the
boundary and authored the terminal tests; Neo did not execute the test suite.
Ponytail kept this in the existing planning reader and middleware, with no new
agent loop, scheduler, dependencies or runtime workflow. The Coordinator still
chooses its evidence-gathering and planning actions. The guard owns only the legal
terminal state and operator authority.

The API workflow was applied to the bounded selector contract and field errors;
TDD retained red/green evidence. No reusable graph was present in this native
checkout, so source/caller inspection was used. Langfuse guidance was consulted;
analysis used local saved evidence, with no Langfuse integration or data upload.
Native hook behavior was checked against installed code and the official
[LangChain hook configuration reference](https://reference.langchain.com/python/langchain/agents/middleware/types/hook_config).

The original findings are P2 defects blocking the next paid iteration's reliable
owner checkpoint and planning observations; offline repair/tests remain allowed.
The additional root-task replacement found in review was also P2 and was fixed
before completion. Duplicate/overlapping slope candidates remain a separate P3
follow-up; no engineering heights or inclusion decisions were inferred here.

The suggested 120M per-run ceiling is an unadopted budget proposal. The last saved
restart receipt measured 41,072,673 tokens including protocol checks, leaving
158,927,327 of its fresh 200M allowance; 21.8M was the earlier pre-continuation
figure. Historical holds and the ledger are unchanged. Development-agent token,
call and time statistics are unavailable.

Offline tests do not establish live-model behavior, engineering correctness, or
report delivery. The stopped case is not hot-patched or restarted; its recorded
chapter 2.1-2.5 source-substitution decision is retained without plan approval.
