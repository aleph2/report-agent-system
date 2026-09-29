# Task051 — repeatability of the Task050 settings

2026-09-30 user: "好，多测试几次". Main predeclares three additional observations
per setting (six total), no outcome-dependent replacement samples. Settings are
exact Task050 request bytes, including high/65536 vs max/131072. This is risk
validation, G1 still open; native end-to-end acceptance and production promotion
are outside this iteration. Prior050 is reported separately and cumulatively,
never substituted for an unfavorable new sample. Same fixture, not held-out data.

Main owns isolated runner/tests and integration. LLM/RL specialist independently
reviews public outputs using the unchanged042 oracle. Reuse050 alignment review
for the unchanged prompt/schema and local validation. No new semantic protocol,
agent responsibility, legacy implementation import, source edit or email.

Dispatch order high01,max01,high02,max02,high03,max03. At most3 in-flight isolated
SDK requests to reduce waiting, each with its own client, context and receipt.
No prior response enters another request. This is an experiment harness only;
the application's serial runtime is unchanged. Concurrency/server/cache effects
mean timing is observational and samples are not asserted statistically independent.
All six requests are frozen before execution. API/transport error or a protected
file mutation halts undispatched trials; existing in-flight requests are collected.
Semantic or protocol failures remain observations without automatic repair/retry.

Predeclared outcomes per run: valid JSON/schema and exact6 ordered IDs; O1 correct
conditional relationship AND C2 not_satisfied/overall needs_revision; preservation
of correct O2 rainfall100; O3 actual height unknown and current band unsupported;
repair supported by source evidence, without fabricating height/classification.
Other five criteria have no complete gold. A generic rejection is not success if
its reasons are wrong. Report errors, omissions and undetermined separately.

Three new successful max runs would support consistency on this fixture, not
general reliability. Any misacceptance refutes an unqualified stable-success claim.
Report exact counts with denominator3 new (and4 including050), preserve mixed
outcomes and don't select the best result. No training/learning claims or causal
attribution solely to reasoning effort: the two settings also differ in capacity.

Official deepseek-flash /beta, same timeout and retries0 as050. Read currently
authorized env credentials in memory only; no env/config/service changes. Save
public response/usage/fingerprint without reading private reasoning. Baseline
hash checks precede requests; output directories and launch checks forbid replay.
