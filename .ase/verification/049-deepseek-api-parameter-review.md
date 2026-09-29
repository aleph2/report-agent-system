# Task 049 — DeepSeek API documentation and effective request review

Date: 2026-09-30. Role: Main, documentation and local evidence review. User asked
for official API parameter improvement advice. No new paid request, prompt/code
change, environment change, or production promotion performed. Lifecycle stage:
review-only; prior G1 uncertainty remains. Existing Task 043 work is untouched.

## Evidence

- Official https://api-docs.deepseek.com/guides/thinking_mode/
- Official https://api-docs.deepseek.com/guides/tool_calls/
- Official https://api-docs.deepseek.com/api/create-chat-completion/
- Effective request: `.analysis/task045/frozen-request.json`, reused byte-for-byte
  by Task 048 (SHA256 `3b5d647981279f8b9e7b4a7ec40ec40184bc6f7c495b835577facba031ad9d54`).
- Local schema inheritance: `src/report_agent/acceptance_review.py`.
- Task 045/048 public results and receipts; no private reasoning inspected.

Current request: deepseek-flash, thinking enabled, reasoning_effort high,
max_tokens 65536, tool_choice auto, parallel_tool_calls false, stream false,
strict unset. Temperature/top_p unset.

## Confirmed defect P2-049-R01

System instruction requires exact criterion IDs in `criterion.name`. Both
effective tool schema branches instead describe `name` as a descriptive,
functional statement of what the criterion checks. They provide no ID enum.
Inherited framework wording conflicts with the application instruction.

Severity P2: local integration reliability defect; emitted descriptive names
cannot be matched safely to the acceptance contract. It may contribute to the
Task 045/048 ID errors, but sole causality is unproven. Scope: these effective
schemas and any caller reusing this inherited field without overriding it.
Containment: retain exact-ID/coverage validation; invalid results remain rejected.
Blocks consuming mismatched output as a valid rubric assessment, not isolated
research or this documentation outcome. Owner Main; proposed next increment:
align field description with exact ID semantics and derive allowed IDs from the
actual rubric. Do not weaken validation or relabel historical invalid results.

## Recommended sequence (not implemented)

1. Correct the conflicting description and bind IDs to the supplied rubric.
2. Adapt the wire schema to official strict-mode support. It requires the beta
   base URL, strict=true on every function, all object properties required and
   additionalProperties=false. Enum and anyOf are documented. Current oneOf,
   discriminator and minLength need adaptation to the documented subset rather
   than simply adding strict=true. Actual server compatibility is untested.
   Retain local uniqueness, completeness, ordering and status consistency checks:
   an enum alone does not ensure every ID appears exactly once.
3. Establish the corrected-protocol high baseline, then compare max separately
   with frozen materials. More reasoning is an experiment, not a proven cure.
   Official mappings: xhigh -> high; ultra -> max.
4. Keep tool_choice auto in thinking Chat Completions; required/named choice is
   documented to return 400. Temperature and presence/frequency penalties are
   ignored in thinking mode. top_p has an effective range of 0.95–1.0; there is
   no local evidence that tuning it improves grading.
5. Do not attribute current failures to output truncation: Task 045/048 used
   46786/40192 completion tokens and ended with tool_calls, below 65536.
   Reassess capacity for a max trial (official default for max is 128K), while
   separately recording latency/usage and preserving adequate output capacity.
6. Streaming may improve progress visibility; it does not establish better
   judgment. Assemble complete tool arguments and validate before consuming.

Strict output can address protocol reliability, not the semantic false acceptance
in Task 048: its public answer expressed the out-of-band score relationship but
waived the consequence. Judge protocol validity and substantive acceptance
correctness separately. No claim of stable model superiority or learned behavior.

No implementation or compliance change was made; independent alignment review
was not run for this documentation-only note. Any subsequent contract change
requires the existing relevant review step.
