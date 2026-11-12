# Fake03 vision-inclusive verification

Prior vision candidate vs main 2289ce1: production +370 / −77. That completed verification follow-up vs 7b76dbe: production +0 / −0; tests +25 / −7; runtime guards +0 / −0; test assertions +3 / −0. No fallback or test retirement.

The completed full verification below used runtime code byte-identical to 7b76dbe. The subsequent 6M cap follow-up is recorded separately below; corrected AGENTS.md is unchanged from aca3e81.

## Verification

**Clean replacement full run on 80f1875: 6,274 passed, 0 failed, 9 unchanged skips; 2,248.3 seconds.** Every collected test accounted for; nine coverage floors passed; all 1,334 frozen files unchanged. Automatic cleanup removed the passing source copy and all nine temporary directories, leaving zero test databases.

The initial focused run was interrupted by a WSL restart after 615 passing calls, without a terminal result. The original full run stays **failed: 6,264 passed, 10 failed, 9 skipped**. Neo traced all ten to stale test expectations: six image-description/catalog cases, three image-reader mocks, one page-facts placement case. Their replacements retain exact schemas, historical fixtures, complete geometry, and no-dispatch/recovery checks. Focused follow-ups passed 5, 22 and 28 cases; all ten originally failing cases passed in the replacement full run.

Main ran tests. Neo independently inspected code, captured requests, manifests, drawing pixels and records; the terminal recheck passed. Neo did not rerun tests. [Detailed results and failure map](../verification/fake03-probe-safety/vision-inclusive-full-20261112.json). Original failed/interrupted evidence is retained privately.

## Bound and frozen drawing

One DeepSeek-1017 call sends a PNG with maximum edge 1,024 and completion limit 8,192, including reasoning. Conservative reservation: **1,000,000 + 8,192 + 10 = 1,008,202 tokens**. Proposed one-check cap: **1,009,226**, including 1,024 margin. This is an upper allowance, not expected usage; no tighter Ali image-token bound is verified. [Provider limits](https://help.aliyun.com/zh/model-studio/deepseek-v4-1-flash) and [completion allowance](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions).

The [frozen v3 manifest](../verification/fake03-post-9a/manifest-v3-vision.json) pins key SHA-256 eb7fb10ab8237e2cd2656e2c3768252474aa1e666ca3689ed7c90d875a1106b4; all 14 fixture hashes match. Only **06_drawing.pdf page 1** is expected to need vision: zero native-text characters, one image; B-labelled cross-section, schematic without dimensions, stepped profile. It supplies no A facts, dimensions, geology, support/drainage or scores. Writer expectations are unchanged.

## Next gate

The owner authorized staged launch on the original candidate with a 1,009,226-token vision check and a 6,000,000-token shared Coordinator/vision probe, but the original candidate refused 6M at preflight. This follow-up changes only that probe cap; a new candidate tag needs fresh owner launch authorization. Continue after the check only with a complete non-truncated observation, settled usage, no new unknown hold, Neo review and at least 6,000,000 campaign tokens remaining. Stop at the page sheet without approval; preserve every hold. No paid call or main move occurred.

Next development item before another model change: consolidate model identifiers/limits/bounds using existing profile infrastructure; preserve current GLM request bytes. Parallel reads and source-result redesign stay deferred. [Operator commands](../verification/fake03-probe-safety/vision-inclusive-commands.md).

## 6M cap follow-up

Production +2 / -2; tests +15 / -15; guards +0 / -0; no legacy fallback or new test/case. Replace the selected 5.5M cap with 6M in the probe and shared budget whitelist, existing fixture/expectation arithmetic, active template and remaining-campaign condition. Historical run/frozen records retain their original values. Model-profile/configuration consolidation remains deferred.

Main ran the three existing probe-focused modules with the existing offline network guard: 42 passed, 1 failed (282.7s). The extra admitted call exposed an old mock returning Coordinator tool calls to the summary request. Neo classified it P2 fixture-only; edit the existing response lines to return a plain summary without advancing the Coordinator script. Only that existing budget case was rerun: 1 passed (16.0s), preserving full charge/reservation, five-call exhaustion, budget-stop and hold assertions. Original failed evidence remains private at `.private/fake03-cap6m-20261112/`; no full regression was run for this follow-up. Draft preflight and final Neo disposition follow before tagging.
