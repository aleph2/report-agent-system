# Task042 first-arm connection failure and suffix continuation

2026-09-29, Main. Preparation commit `2240e1a`; frozen semantics and inputs remain
unchanged. This is an execution incident, not an observed grader judgment error.

A (`cf0e383fe2c1`) started13:14:35 UTC and ended13:15:23 with an
OpenAITimeoutError, caused by APITimeoutError / ConnectTimeout. Its audit contains
one logical model request, zero responses and no returned usage. There is no
structured verdict to score. The configured SDK transport retry count remains2;
callback counts do not establish the number of low-level HTTP attempts or an
invoice amount. Batch stopped beforeB; postflight hashes all matched.

[HTTPX documents ConnectTimeout](https://www.python-httpx.org/exceptions/) as a
timeout establishing a host connection, distinct from reading a model response.
The [OpenAI Python SDK documents timeout and retry behavior](https://github.com/openai/openai-python#timeouts).
Local cause types support a connection-stage failure; they do not identify a
provider outage, DNS defect, WSL fault or model/context-length problem.

Main then made one zero-model transport probe in the same WSL Python environment
to the configured endpoint's host root, without credentials or project content.
At13:17:07 UTC, DNS resolved four addresses in0.029s and unauthenticated HEAD
returned HTTP404 in0.335s. No proxy environment variables were present. This
establishes host reachability at that moment, not authenticated inference health.
Evidence is preserved in `.analysis/task042/connectivity-01.json`; no environment
values, API keys, response bodies or private model reasoning were logged.

## Disposition before another model call

P2-042-I01: the connection incident prevents the originally planned valid A/B
pair and any paired semantic comparison. Its scope is the A attempt in this
diagnostic, not a confirmed production-code defect. Retain A as failed and
unscored; do not repair, replay or relabel it. No production promotion depends on
this probe. The now-reachable host and isolated still-unattemptedB allow useful
single-arm evidence under existing authorization, containing the failure without
stopping that remaining observation. A successfulB alone will not show an
improvement overA or support a causal treatment effect.

Main authorizes the runner's existing `--resume` solely for unattemptedB using
the unchanged frozen input, model/schema/parameters and a recorded diagnosis.
No network, proxy, timeout or model-setting changes are made. The original batch
is retained as `batch.before-continuation.json`; A artifacts are separately hashed
before continuation. IfB also fails, its attempt will likewise be preserved,
and this batch will not be replayed automatically.

An evaluator-only preflight command was inadvertently launched a second time
after its initial session had not been retained in the caller's displayed output.
The initial preflight completed; the duplicate refused its existing output with
REFUSE_PREFLIGHT_OVERWRITE. Both are zero-model checks. The successful preflight
and frozen oracle remain unchanged; this was not a repeated experimental cell.

## User URL question and already-completed continuation

Before the user's stop instruction, Main read only the allowlisted configured
base URL: `https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`.
It has no URL userinfo, query or fragment. The configured non-Responses adapter
uses the chat/completions route with model `glm-5.3`; this is a configuration
observation, not a capture of wire traffic.

A further bounded zero-model probe at13:23:52 UTC checked each of four currently
resolved addresses. Both IPv4 addresses completed TCP and verified TLS1.3 in
0.125/0.126s; both IPv6 addresses failed immediately at TCP. One additional IPv6
check recorded errno101, Network is unreachable. These observations are saved
in `connectivity-02.json` and `connectivity-ipv6-detail.json` under the Task042
analysis directory. Inspection of the installed httpcore AnyIOBackend and AnyIO
connect_tcp documentation confirmed fallback across resolved addresses. IPv6
unreachability therefore does not establish the cause of A's earlier timeout.
No URL, networking, timeout or model configuration was changed.

B completed13:25:34 UTC with a valid structured response; the batch finished
13:25:48 as completed_with_errors. This is direct evidence that a later actual
inference succeeded, not proof of the earlier failure's root cause. The original
A artifacts and saved pre-continuation batch all match their pre-resume hashes.
An attempted read-only socket snapshot occurred after the process had ended and
returned no matching active process; it does not diagnose the earlier timeout.

The user then instructed: “先不试了，估计是服务出问题了”. Main stopped all new model
and connectivity tests. Only existing-output audit, independent read-only scoring
and Git preservation continue as closeout. Service failure remains a hypothesis;
there is no confirmed infrastructure fix, no scheduled retry and no email.

The user subsequently resumed work: “说明服务恢复了，你继续”. Main acknowledged
that successfulB demonstrates later inference availability, while A's exact root
cause remains unknown. Work resumes from the preserved result; this does not
authorize relabeling/replaying the failedA within the frozen pair. The next work
is existing-result integration and a separately scoped native source-observation
design assessment, not another connectivity probe or automatic failed-cell retry.
