# Task047: same-connection Aliyun DeepSeek observation

2026-09-30 local. User requested deepseek-v4.1-flash without changing the current
API connection. Main used existing .env Aliyun URL/key, overriding only the selected
model name plus its established provider parameter mapping. No .env writes,
production changes, service restarts, emails or043 execution. Risk-validation/G1
remains open. Independent reviewer is `/root/llm_rl_expert`; unchanged paragraph
alignment findings from045 remain applicable. No private reasoning read/exported.

## Actual comparison settings

Endpoint https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1,
requested modeldeepseek-v4.1-flash. Messages/schema identical to045/046. Model
parameter mapping from existing023 adapter: enable_thinking=true (replacesGLM
thinking object), max_tokens65536 (replacesmax_completion_tokens). Reasoninghigh,
tool_choicerequired, parallel_tool_callsfalse, streamfalse; temperature/top_p/seed
unset. Direct SDK, retries0, timeout15/1800/60/60 seconds as046.

Official docs checked2026-09-30:
https://help.aliyun.com/zh/model-studio/deepseek-api documents this exact model,
enable_thinking and high reasoning. Different provider routes/defaults are not
assumed equivalent;045 officialDeepSeek usedauto instead ofrequired. No claim
of a literal single-field payload change or equal internal reasoning budget.

- RequestSHA256 `e74acca7566078d81af8b1b739a5eeb8664493bc3afaeb575eaea02fa648ffe9`
- SystemSHA256 `d167b3c571860b9501f1b0d95bb6bc05476c9267bc880c826b11aba2f8356293`
- UserSHA256 `68504cfd4871eda5210dfdd19e26e8a880df22066721028a682067e68dc07c39`
- Oracle042 unchanged `f09f6e5acaf08a3db2e96784e8f7dabf522397d2ef3c9a653f54b35215f4a3c7`

One exclusive attempt, started2026-09-29T21:17:18.660096UTC. Artifacts at
`.runs/task047/aliyun-deepseek-claims/attempt-01/`. No repair or paid replay.
Outcome pending; positive/unknown controls and protocol assessed separately.

## User cancellation

User cancelled waiting and selected their restored officialDeepSeek endpoint.
Main sentSIGTERM only to the exact047 Python processPID2275244 after matching
argv and workspace; local exec returnedexit1. No response.json was present.
Original attemptedreceipt retained unchanged; cancellation.json records local
termination, no returnedusage and unknown remote completion/billing. This is an
uncompleted/unscored trial, not a model-quality failure or confirmed provider
outage. No automatic replay. New048 is separately user-authorized on official
DeepSeek with the prior045 request. No email.
