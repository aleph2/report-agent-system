# Task044: one direct DeepSeek model-switch observation

User requested a simple model change before Task043 and updated model, endpoint
and key in the legacy project's `.env`. Read only those authorized settings;
never modify or restart legacy services. No email. Main implements and executes;
the existing LLM/RL specialist independently judges public output afterward.

Stage: risk-validation; G1 report-review reliability remains open. Reuse Task042
B's exact saved system/user text, tool schema and six criteria. One fresh SDK
request, no retrieval, author loop, schema repair or paid replay. This is a fixed
input judgment, not native autonomous grading or end-to-end acceptance.

Model `deepseek-flash`, endpoint `https://api.deepseek.com`, current key read only
in memory. Preserve high reasoning, 65536 maximum output tokens and nonstreaming.
Per official Chat Completions docs, thinking mode rejects required tool choice:
use auto, omit GLM clear_thinking, use max_tokens. SDK retries zero makes the one
request boundary explicit (previous GLM allowed two transport retries).
Preserve prompts and schema even if auto produces a protocol failure. Record
that adapter/backend changes confound pure model causality.

Plan: verify frozen inputs; save credential-free request and immutable attempt;
invoke once; validate response/criterion coverage; judge using unchanged042
oracle. Observe O1 (70 vs adopted75–100), O2 (rainfall100) and O3 (height unknown)
separately from overall verdict and repair advice. No complete six-item gold,
no stability estimate or production promotion from one sample. Task043 stays pending.

Official references checked 2026-09-29:
- https://api-docs.deepseek.com/api/create-chat-completion/
- https://api-docs.deepseek.com/guides/thinking_mode/

Outcome and exact paths/hashes: `.ase/verification/044-simple-model-switch.md`.
