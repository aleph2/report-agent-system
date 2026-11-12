# Fake03 vision-inclusive verification

Vision candidate vs main 2289ce1: production +370 / −77. This verification follow-up vs 7b76dbe: production +0 / −0; tests +25 / −7; runtime guards +0 / −0; test assertions +3 / −0. No fallback or test retirement.

Runtime code remains byte-identical to 7b76dbe; corrected AGENTS.md remains as approved at aca3e81.

## Verification

**Clean replacement full run on 80f1875: 6,274 passed, 0 failed, 9 unchanged skips; 2,248.3 seconds.** Every collected test accounted for; nine coverage floors passed; all 1,334 frozen files unchanged. Automatic cleanup removed the passing source copy and all nine temporary directories, leaving zero test databases.

The initial focused run was interrupted by a WSL restart after 615 passing calls, without a terminal result. The original full run stays **failed: 6,264 passed, 10 failed, 9 skipped**. Neo traced all ten to stale test expectations: six image-description/catalog cases, three image-reader mocks, one page-facts placement case. Their replacements retain exact schemas, historical fixtures, complete geometry, and no-dispatch/recovery checks. Focused follow-ups passed 5, 22 and 28 cases; all ten originally failing cases passed in the replacement full run.

Main ran tests. Neo independently inspected code, captured requests, manifests, drawing pixels and records; the terminal recheck passed. Neo did not rerun tests. [Detailed results and failure map](../verification/fake03-probe-safety/vision-inclusive-full-20261112.json). Original failed/interrupted evidence is retained privately.

## Bound and frozen drawing

One DeepSeek-1017 call sends a PNG with maximum edge 1,024 and completion limit 8,192, including reasoning. Conservative reservation: **1,000,000 + 8,192 + 10 = 1,008,202 tokens**. Proposed one-check cap: **1,009,226**, including 1,024 margin. This is an upper allowance, not expected usage; no tighter Ali image-token bound is verified. [Provider limits](https://help.aliyun.com/zh/model-studio/deepseek-v4-1-flash) and [completion allowance](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions).

The [frozen v3 manifest](../verification/fake03-post-9a/manifest-v3-vision.json) pins key SHA-256 eb7fb10ab8237e2cd2656e2c3768252474aa1e666ca3689ed7c90d875a1106b4; all 14 fixture hashes match. Only **06_drawing.pdf page 1** is expected to need vision: zero native-text characters, one image; B-labelled cross-section, schematic without dimensions, stepped profile. It supplies no A facts, dimensions, geology, support/drainage or scores. Writer expectations are unchanged.

## Next gate

New staged owner authorization is pending. First: one direct image-tool check, no Coordinator model call. A complete, settled result, no new unknown hold and Neo review are required before the separate Coordinator-only GLM-5.3 plus vision probe, capped at shared 5.5M and stopping at the page sheet. Recheck campaign availability after the check; stop if the full 5.5M is unavailable. Preserve every existing hold. **No paid call or main move occurred.**

Next development item before another model change: consolidate model identifiers/limits/bounds using existing profile infrastructure; preserve current GLM request bytes. Parallel reads and source-result redesign stay deferred. [Operator commands](../verification/fake03-probe-safety/vision-inclusive-commands.md).
