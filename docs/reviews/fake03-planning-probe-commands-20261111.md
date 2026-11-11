# Fake03 planning probe — commands for owner review

**Not a launch authorization.** Run only under the owning Linux user/Python. No command below initializes or resets a grant. No live authority file has been generated.

## Before launch

1. Review/accept the safety candidate and its verification. Run the separately owner-authorized full offline regression first.
2. Owner selects **3,700,000 or 5,500,000** as the probe hard cap and explicitly authorizes one Fake03 Coordinator planning launch with text-only `glm-5.3`, A/B and C proposed for exclusion, stopping at the page-sheet checkpoint, all holds preserved. This is not plan approval or engineering sign-off.
3. Copy [the invalid template](../verification/fake03-probe-safety/authority.template.json) into private operator storage. Replace every placeholder using the actual launch revision, existing grant and private held-request/retry receipt. Record the direct owner launch authority. Do not import an old plan or fake a new grant.
4. Pin the existing external GLM service configuration and full-model proof. The file's GLM Writer bundle supplies the approved GLM service for the probe; the process maps constructible roles to that same service, while the request hook admits only Coordinator calls. Never print keys. The template/answer key stays outside case inputs.

## Commands

`PYTHON` is the owning Linux interpreter, `AUTH` is the private completed authority file, `AUTH_SHA` its separately verified SHA-256, `ENV` the pinned external service config. `PREPARED_SHA` comes from prepare. Placeholders are not executable approvals.

```bash
# From the accepted checkout root; no package install is required.
export PYTHONPATH="$PWD/src"
"$PYTHON" -B -m report_agent.fake_planning_probe identify

# Offline import only; output includes case_path and prepared_sha256.
"$PYTHON" -B -m report_agent.fake_planning_probe prepare \
  --authority "$AUTH" --authority-sha256 "$AUTH_SHA"

"$PYTHON" -B -m report_agent.fake_planning_probe check \
  --authority "$AUTH" --authority-sha256 "$AUTH_SHA" \
  --prepared-sha256 "$PREPARED_SHA"

# Paid launch: only after the separate owner authorization.
export REPORT_SDK_RETRIES=0 REPORT_CONNECT_RETRIES=2
"$PYTHON" -B -m report_agent.fake_planning_probe run \
  --authority "$AUTH" --authority-sha256 "$AUTH_SHA" \
  --prepared-sha256 "$PREPARED_SHA" --env "$ENV"
```

SDK retries are zero. The retained two connection retries are the existing pre-HTTP connection policy, not permission to replay an unknown request. The command records its actual PID/UID/start ticks and claims result.json once. A failed or unknown result is inspected, never automatically restarted.

## Limits and checkpoint

| Owner cap option | Settled headroom for admitting another full request, with no new-run hold |
| --- | ---: |
| 3,700,000 | 2,520,352 |
| 5,500,000 | 4,320,352 |

The last admitted request may settle above that headroom, up to the hard cap. The full reservation is temporary and is not multiplied by all calls. Every request also counts existing campaign settled/held exposure. The read-only preparation snapshot showed 6,829,292 available; 5.5M fits but is **not** the mathematical maximum, and it does not guarantee planning completes. Recheck the ledger before actual authorization/launch. No campaign amendment is part of this probe.

At `page_sheet_checkpoint`, spending ends with the proposed bindings and the original native planning wait saved. `other_human_checkpoint` means a different decision is required. `budget_stop` and `unknown_outcome_held` are distinct outcomes. There is no automatic approval, follow-on Writer or retry. A later reply/continuation decision needs a separately authorized stage under the same preserved accounting; no continuation command is exposed here.

## Report to review

Read private `GRANT/runs/RUN_ID/result.json`, `tool-trace.jsonl`, and the case's existing `runtime-metrics.jsonl` (native Linux; database reads only `mode=ro/query_only`). Return per-call actual usage/growth, observed logical/HTTP attempt distinctions, held exposure, reason/role refusals, exact native checkpoint and pending bindings. Compare A/B page proposals, A-only survey, document-role restrictions and proposed C exclusion with frozen key v2. Review Chinese text field by field; do not claim engineering correctness from quote matches or zero refusals. No paid result is available yet.

Callbacks use existing [LangChain BaseCallbackHandler](https://reference.langchain.com/python/langchain-core/callbacks/base/BaseCallbackHandler) and [inherited configure hooks](https://reference.langchain.com/python/langchain-core/tracers/context/register_configure_hook); no Langfuse SDK, upload or additional model is introduced.
