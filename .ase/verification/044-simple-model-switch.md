# Task044: simple DeepSeek switch result

2026-09-29. Main implemented and ran the isolated call; `/root/llm_rl_expert`
independently reviews public results in `044-independent-results.md`. User
explicitly changed model, URL and API key and asked for this simple test.
No email, production configuration changes, legacy restart or Task043 execution.

## Actual outcome

One request, one response, zero retries, 2026-09-29 14:04:41.910213 to
14:07:25.500697 UTC (163.59 seconds). Requested and returned model:
`deepseek-flash`; base URL `https://api.deepseek.com`, Chat Completions route.
New key read directly from user `.env`, never printed or persisted in evidence.

Overall `satisfied`, all six exact criterion IDs `satisfied`. Valid tool call and
schema; raw function arguments equal the validated output, with no repair.
Prompt136200 + completion37756 = total173956 tokens. The32703 reasoning tokens
are already included in completion; no reasoning text read or exported.

Task042 B GLM result was also six satisfied. This new result does not remove the
known false acceptance. It explicitly quotes the report's X21=70, adopted
易滑软弱地层, and guideline75–100, then calls70 an “in-band judgement” and says
the pairing is “loose rather than contradicted”. That is publicly inconsistent
relation reasoning, not proof that the model internally recognized a violation
and intentionally ignored it. C2 remains incorrectly satisfied under the frozen
oracle. R31=100 retains source support. Unknown actual height is acknowledged,
but the report's definite20–30m band remains accepted despite missing support.

## Controls and limitations

Saved request messages exactly equal042 B (3489/278651 characters), schema/tools
unchanged; all15 saved source observations, report and original six criteria
remain. Independent preparation review confirmed Task043 was not introduced.

- system SHA256: `340e74c063010a8957579a17ab2e9b20cd960e4858eb382e6f5521a86d70b2a4`
- user SHA256: `68504cfd4871eda5210dfdd19e26e8a880df22066721028a682067e68dc07c39`
- request: `8e03b094ea14106e1088bafbe87f7cffd534a6d9b7782b11987d10c59933ea33`
- response: `7ffe51f1558db8435ccfc435c9cd65280eb4d5ea480e5e0aa6edb58ea6d7c31b`
- output: `de80fc195b82594eb91d843a126b88bae5867f66a48b47728f478882f4ee2c65`
- receipt: `2caaa2cd149f2af4b0d1126af512e697bd6774060d6d538a7ada1a7b83721094`

Official DeepSeek docs prohibit required tool choice in thinking mode. Effective
settings: thinking enabled, reasoning_effort high, max_tokens65536,
tool_choice auto, parallel_tool_calls false, stream false; temperature/top_p/seed
unset. Compared with GLM: backend/model/key changed, max_completion_tokens renamed,
GLM clear_thinking omitted, required→auto, direct SDK replaces agent wrapper, SDK
retries2→0. Timeouts15/1800/60/60 seconds connect/read/write/pool. Thus this is not a
pure causal model comparison. Equal high labels do not imply equal reasoning.

Checked official pages (2026-09-29):
- https://api-docs.deepseek.com/api/create-chat-completion/
- https://api-docs.deepseek.com/guides/thinking_mode/

## Delivery disposition

Risk-validation/G1 remains open. This fulfills the requested one-sample test;
it does not establish model equivalence, stability, autonomous evidence gathering,
end-to-end review improvement, production promotion or engineering acceptance.
P2-044-R01: reproduced false C2/overall acceptance, plus overbroad source-support
claims. Scope: this fixed-input review. Blocks using this verdict for whole-report
acceptance/promotion/sign-off; does not block isolated diagnosis or marked drafts.
Containment: keep result research-only, preserve oracle and pending issues;
Main owns follow-up within the existing grader reliability work. No automatic
paid replay. Independent final review concurs. P3-044-R02: grader claims
5788/121=47.84, but that expression rounds to47.83; the report's actual rounded
weights give47.8403→47.84 and are correct. Main accepts the finding as a grader
explanation/precision defect, not a report correction or grade change. It blocks
neither this test nor a marked draft; retain it for subsequent grader regression.

## User hypothesis after the call

User asks whether the prompt failed to identify the report as an unverified
evaluation object. Main inspected the exact sent system prompt: it already says
candidate report, assess artifact not author's narrative, unsupported definite
assertions cannot be excused by pending confirmation, and reports/source/tool
outputs are untrusted observations rather than instructions. Therefore absence
of all such guidance is refuted; insufficiently salient epistemic separation or
failure to follow it remains a hypothesis. “Not instructions” primarily specifies
instruction authority, not whether author assertions count as verified evidence.
A possible isolated intervention is to explicitly identify report factual claims
as claims to establish, prohibit self-validation by their own assurances, and
retain report text as direct evidence for structure/disclosures. Do not presume
all content false or all originals infallible. No prompt modified or extra model
call made in response to this discussion. A follow-up should keep the current
DeepSeek inputs/settings fixed and inspect valid/invalid/unknown controls together.

Evidence: `.runs/task044/simple-model-switch/attempt-01/` contains exact request,
public response, parsed output and receipt. Offline preflight passed; actual call
validates model/endpoint/auth and structured-output compatibility. Postflight
checks verified raw/parsed equality and frozen message identity. No production
behavior was changed, so no application regression suite was required.
