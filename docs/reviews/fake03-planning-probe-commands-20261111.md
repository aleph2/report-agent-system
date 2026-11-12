# Fake03 planning probe — current operator commands

**Not a launch authorization.** Use the owning Linux user/Python and a reviewed immutable candidate. Historical proposals/results keep their original limits and observations.

## Authority configuration

The existing separately pinned private authority file configures both limits:

- `aggregate_tokens` must equal the current authorized maximum in the existing campaign ledger. Preflight reads it without creating or changing the ledger, and runtime checks the same value again. Extend an existing grant only through the authorized additive amendment API; preserve every attempt, hold and amendment receipt.
- `per_run_tokens` is the explicitly authorized cap for this run, bounded by that campaign. The probe does not maintain a separate list of allowed amounts. A one-image check must cover its verified full request reservation.

Fill every placeholder in the [planning template](../verification/fake03-probe-safety/authority.template.json) or [one-image template](../verification/fake03-probe-safety/vision-check-authority.template.json), including both limits. Templates deliberately have no chosen amounts. Pin candidate/fixtures, answer key v3, the authorized scope/models, existing grant, preserved hold and comparison receipt, and both GLM/vision service proofs as applicable. Keep keys local and authority/answer-key records out of case inputs. Preparation and a successful dry-run preflight do not authorize dispatch.

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

## Admission and checkpoint

Before any separately authorized launch, reconcile settled usage plus all holds against both the campaign and applicable verification/real-report aggregate allowances. A delegation ceiling does not reset usage or replace a category ceiling. Confirm the remaining campaign allowance can cover the authorized run and each full provider reservation; no token estimate substitutes for a hard bound.

At `page_sheet_checkpoint`, spending ends with the proposed bindings and original native planning wait saved. No approval, follow-on Writer, continuation or retry follows automatically. `budget_stop`, another human checkpoint and an unknown held outcome remain distinct terminal results. Preserve the actual result, traces, usage and all holds; compare actual proposals with the frozen answer key and report missing or unverified work honestly.
