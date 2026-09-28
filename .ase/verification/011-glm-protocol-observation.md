# GLM Protocol Observation

Date: 2026-09-28 (Asia/Shanghai)

Status at initial review: confirmed adapter gap; Task009 causation unproven. This is an observation
record, not an implementation, deployment, model-call authorization, or stop order.
Author: Codex, acting as an independent protocol reviewer of the current adapter.

## Scope and Runtime Disposition

The review inspected application source, installed dependency source and package
metadata, official public documentation/source, and a synthetic in-memory probe.
It did not read credentials, inspect historical reasoning text, call a model,
install dependencies, change production code/configuration, or touch Task009 state.
This record adds no new experiment; it records the preceding review's evidence.

Main subsequently relayed tool-observed progress: inspection of `state.db` events
543/547 showed Task009 updating its todos toward drafting and rechecking the
outline. This was Main's tool-observed progress relayed to the reviewer, not a
user-reported observation or an independent runtime verification by this reviewer.
The disposition at that time was to leave Task009 running without stopping or
hot-patching it because of this finding.

This document preserves the initial review snapshot, not the current repair or
runtime status. Subsequent Task012 adaptation, cancellation, and recovery records
are tracked in [012-glm-protocol.md](012-glm-protocol.md). The historical gap and
disposition below must not be read as a claim that the adapter remains unfixed or
that the original no-intervention disposition still describes the current run.

## Confirmed Gap: GLM-PROTOCOL-01

Severity at initial review: **P2**, a provider-protocol compatibility/reliability gap. The then-current
adapter cannot preserve an incoming `reasoning_content` field across tool turns.
That is confirmed mechanically, but its actual impact on Task009 is unknown.
It is not classified as P1 because failure of the overall task due to this gap
has not been established.

Scope: GLM Chat Completions calls using the reviewed `configured_model` path.
No claim is made that every endpoint returns this field on every response.

At review time, `src/report_agent/deep_models.py:100-104` constructed `ChatOpenAI`
with `use_responses_api=False`, `reasoning_effort="high"`, and no explicit
`thinking.clear_thinking=false`. This is source-code evidence, not inspection of
live secrets or a captured wire request.

Installed versions verified from package metadata:

- `langchain-openai==1.6.6`
- `openai==2.54.0`
- `langchain-core==1.6.5`
- `langgraph==1.2.12`
- `langgraph-checkpoint==4.2.0`
- `langgraph-checkpoint-sqlite==3.1.1`
- `deepagents==0.7.19`

Installed source root:
`/home/dysun/.venvs/report-agent-system/lib/python3.12/site-packages/`

In `langchain_openai/chat_models/base.py`, the reviewed
`_convert_dict_to_message` at line 218 and `_convert_message_to_dict` at line 472
do not transfer `reasoning_content`. `_create_chat_result` at line 2049 and
`_get_request_payload` at line 2018 use these conversions. Saving the field only
on receipt therefore would not fix outbound history serialization.

These line references describe the inspected snapshot, not a guarantee against
future dependency or application edits.

## Official Protocol Evidence

Official URL, accessed during this review:
<https://docs.z.ai/guides/capabilities/thinking-mode>

The documentation distinguishes:

- Interleaved thinking: thinking between tool calls; thinking blocks should be
  retained and returned with tool results.
- Preserved thinking: retaining earlier assistant-turn reasoning. The page says
  this defaults on for the Coding Plan endpoint and off for the standard API.
  Explicit enablement uses `thinking.clear_thinking=false`, with historical
  `reasoning_content` returned unmodified and in its original sequence.

The documented request example uses
`extra_body={"thinking": {"type": "enabled", "clear_thinking": false}}`.
`reasoning_effort` is not a substitute for transmitting the historical field.
This review did not establish the live endpoint's defaults or actual wire behavior.

## No-Network Probe

Executed with the project's existing WSL Python interpreter. The probe used a
synthetic `ChatCompletion` containing an opaque test marker and one tool call,
an explicitly supplied dummy API key, and a loopback placeholder URL. It called
only local conversion and serialization methods, never `invoke`, `generate`, or
an HTTP/model request. Only boolean outcomes were printed; no reasoning text,
credentials, engineering content, or live configuration was printed.

The probe exercised:

1. OpenAI SDK `ChatCompletion.model_validate` and `model_dump`.
2. Installed `ChatOpenAI._create_chat_result`.
3. Installed `ChatOpenAI._get_request_payload` using an `AIMessage` already
   containing the field plus its matching `ToolMessage`.
4. `JsonPlusSerializer.dumps_typed` / `loads_typed` with both an old-style message
   lacking the field and a new-style message containing it.

Observed output:

```json
{
  "sdk_preserves": true,
  "response_conversion_preserves": false,
  "request_conversion_preserves": false,
  "checkpoint_new_preserves": true,
  "checkpoint_old_loads_without_field": true,
  "tools_survive": true
}
```

This verifies the conversion loss and serializer capability. It is not a live
provider test, a full SQLite saver/recovery test, or evidence of model quality.

## Existing Integration Assessment

The installed package inventory contained no ZAI/Zhipu integration,
`langchain-community`, or `langchain-deepseek` package.

- **ChatZAI:** no installed implementation or verifiable official Python
  implementation was identified in the bounded review. This is not a claim that
  no such implementation exists anywhere.
- **ChatZhipuAI:** the official community source inspected has no
  `reasoning_content` handling in its receive, send, or streaming conversions.
  It is not an evidenced drop-in solution for this requirement.
- **ChatDeepSeek:** the official source inspected preserves the incoming field
  for SDK responses and streaming chunks, but its request override does not
  reinsert it into outgoing assistant messages. It is a reference pattern, not
  proof of complete GLM tool-turn compatibility with the installed base adapter.

Official source URLs inspected (moving branches, not installed-version evidence):

- <https://github.com/langchain-ai/langchain-community/blob/main/libs/community/langchain_community/chat_models/zhipuai.py#L138>
- <https://github.com/langchain-ai/langchain/blob/master/libs/partners/deepseek/langchain_deepseek/chat_models.py#L323>

No candidate integration was installed or called against a provider.

## Minimal Future Adaptation and Compatibility Risks

The smallest identified candidate is a thin GLM-specific `ChatOpenAI` subclass
that preserves the response field in `AIMessage.additional_kwargs` and returns
that exact field on the corresponding outgoing assistant history message, plus
the explicit documented `thinking` request setting. Keep native tool binding,
SDK retries, DeepAgents orchestration and LangGraph persistence. Do not add a
second execution loop or recovery engine. This is a proposal, not implemented work.

Compatibility requirements for a later authorized validation:

- New messages can use the existing serializer; no new message class or database
  table is indicated by this probe.
- Old messages without the field must remain readable. Missing historical data
  cannot be reconstructed by a new adapter. Do not manufacture an empty value
  or synthesized reasoning and label it preserved history.
- Local loading compatibility does not establish that the real endpoint accepts
  mixed old/new history or preserves equivalent behavior. That remains unknown.
- Preserve assistant/tool ordering and IDs. Do not edit historical checkpoints
  or reset business receipts merely to satisfy the new transport representation.
- Cover SDK-object and dictionary responses. If streaming is later used, it
  needs its own lossless chunk handling; the non-streaming probe does not prove it.
- Native summary/context compaction compatibility with preserved reasoning is
  unverified. Do not promise indefinitely complete history after compaction.
- `LocalAudit` currently serializes full messages; adding this field would also
  add it to local audit data. Review storage/display boundaries before deployment;
  diagnostics should expose presence/length/check results, not reasoning text.

## Causality, Containment and Planned Disposition

**Not established:** whether historical Task009 raw responses contained the
field, whether an intermediary removed it, or whether preserving it would reduce
repeated calculations or improve drafting. Historical raw evidence is missing.
Missing fields in converted messages cannot distinguish those possibilities.

The confirmed statement is conditional: if the reviewed path receives
`reasoning_content`, these installed conversions discard it, and manually storing
it on an `AIMessage` alone still does not return it to the provider.

Blocked action: claiming complete GLM preserved-thinking compatibility is not
supported. This finding does **not** independently block Task009 continuation,
draft generation, or human review, and does not establish a root cause for its
earlier repeated calculations.

Containment: retain this limitation explicitly, preserve available historical
evidence, and make no in-flight changes based on the causal hypothesis.
Main owns prioritization and any future adaptation/deployment decision. A later
authorized compatibility test should distinguish mechanical field round-trip,
old-checkpoint acceptance, and actual task behavior. No paid call, rollout, or
automatic retry is authorized by this record.
