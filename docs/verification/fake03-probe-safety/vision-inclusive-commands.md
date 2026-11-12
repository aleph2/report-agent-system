# Vision check and Coordinator probe: trusted operator commands

These commands do not create a grant or release any hold. Use the existing private campaign and distinct owner-authorized run IDs. Templates are not authority; they deliberately contain unfilled paths/pins, and the check template has no cap.

## Private authority preparation

1. Commit/review the candidate and complete its offline verification. Use owning Ubuntu-24.04 Python for all commands and SQLite observations.
2. Run identify and pin its commit, fixture manifest and answer-key hash:

    /home/dysun/.venvs/report-agent-system-native/bin/python -B -m report_agent.fake_planning_probe identify

3. Prepare private authority from [check template](vision-check-authority.template.json) or [probe template](authority.template.json). Preserve the existing grant path and fresh-comparison hold/retry proof. Record the actual owner chat authority privately. Hash the authority file separately; never put credentials, real service URLs or raw case material in Git.
4. Bind service proof to the exact external configuration and exact request URL. GLM retains 1,048,576 input + 131,072 output = 1,179,648. Vision uses the conservative documented Ali ceiling: 1,000,000 input + 8,202 output = 1,008,202, with host PNG edge 1,024 and wire max_completion_tokens 8,192. The output reservation includes the documented possible 10-token overrun. Thinking is explicit; no automatic mode fallback or output-limit increase.
5. The staged single-check cap is 1,009,226 (reservation + 1,024 margin). The next candidate probe cap is 6,000,000 shared by GLM/vision/support calls, within the unchanged campaign. Both stages require owner launch authorization naming the new candidate tag. Cached input counts in full. Actual expected vision usage has not been measured.

Official bounds: [Ali model limits](https://help.aliyun.com/zh/model-studio/deepseek-v4-1-flash), [completion limit and overrun](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions). No provider-specific tight image token formula has been verified. A 40K hard bound must not be substituted.

## Prepare, inspect, launch once

Run from the accepted candidate checkout, with the external service configuration outside the repository/run directory. The same CLI handles either separately pinned authority:

    /home/dysun/.venvs/report-agent-system-native/bin/python -B -m report_agent.fake_planning_probe prepare --authority "$TASK_AUTHORITY" --authority-sha256 "$TASK_AUTHORITY_SHA"
    /home/dysun/.venvs/report-agent-system-native/bin/python -B -m report_agent.fake_planning_probe check --authority "$TASK_AUTHORITY" --authority-sha256 "$TASK_AUTHORITY_SHA" --prepared-sha256 "$TASK_PREPARED_SHA"
    /home/dysun/.venvs/report-agent-system-native/bin/python -B -m report_agent.fake_planning_probe run --authority "$TASK_AUTHORITY" --authority-sha256 "$TASK_AUTHORITY_SHA" --prepared-sha256 "$TASK_PREPARED_SHA" --env "$TASK_EXTERNAL_ENV"

Before run, inspect the prepared import and exact effective models, retries and proof pins. SDK retries must be zero; the existing two transport connect retries never replay a sent HTTP request. The check directly calls the image tool for 06_drawing.pdf page 1 and makes no Coordinator model call. The probe prepares a separate fresh import, runs only Coordinator planning/support, and stops at the real page-sheet checkpoint; it does not approve the sheet.

Proceed past the check only after a complete non-truncated observation from the declared backend, settled usage, no new unknown hold, and Neo’s review. After the small check settles, recheck the campaign’s actual available tokens using owning WSL Python. Proceed only if at least 6,000,000 remain, so the full proposed probe ceiling is available; otherwise stop for owner disposition without amending a grant, changing the cap or releasing holds. The 6M cap is not earmarked at preparation. Any failure stops further paid stages; investigate offline without replaying unknown calls. A received incomplete result remains incomplete. No automatic retry/continuation.

## Report back

Preserve result.json, actual process identity, ToolTrace, runtime metrics and ledger before/after privately. Reconcile the exact process exit and reservation IDs, not an assumed PID. Show per-role settled/held tokens, invocations, decision turns, deduplicated refusals and elapsed invocation time. Vision support belongs to Coordinator; it is not a sixth agent. Compare bindings and suitable vision use against the frozen v3 key before judging cost; report Chinese reader-facing text and cached token counters separately. These local counters supplement the authoritative ledger and never release holds.
