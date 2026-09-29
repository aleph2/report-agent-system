# Task047: DeepSeek on the unchanged Aliyun connection

2026-09-30 user explicitly requested deepseek-v4.1-flash using the same current
API connection. Main retains Aliyun URL/key source, unchanged045/046 messages,
schema, six criteria, high reasoning, output limit65536, required tool choice,
nonstreaming and zero retries. No email. No legacy/production changes or043 run.

Use existing validated023 Aliyun DeepSeek adapter settings: enable_thinking=true
instead of GLM thinking object, max_tokens instead of max_completion_tokens.
Official2026-09-30 verification: https://help.aliyun.com/zh/model-studio/deepseek-api
documents deepseek-v4.1-flash, enable_thinking and high reasoning. These necessary
model parameter differences are explicit, not hidden as an exact one-field test.
Do not substitute api.deepseek.com, change key, shrink input or modify rubric.

Risk-validation/G1 open. One isolated call, no repair or automatic replay; preserve
errors and public response. Reuse unchanged paragraph alignment review and042
oracle. Independent LLM/RL specialist evaluates O1/O2/O3, criterion decisions,
false rejection and repair scope separately from protocol validity. Compare046
same-providerGLM and045 officialDeepSeek with appropriate backend/tool-choice
limits; one sample cannot establish model superiority or stable prompt effects.
Main owns runner/verification and Git. No private reasoning inspected/exported.
