"""Synthetic wire probe. Keep private reasoning in memory; persist metadata only."""
import asyncio
import argparse
import hashlib
import json
import os
from pathlib import Path

from openai import AsyncOpenAI
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from report_agent.deep_models import configured_model
from report_agent.store import Store

from run_deepagents_trial import load_service_environment


async def main(complex_case=False, adapter=False):
    root = Path('.runs/task012/adapter-probe' if adapter else
                '.runs/task012/protocol-complex' if complex_case else '.runs/task012/protocol-probe')
    root.mkdir(parents=True, exist_ok=True)
    intent = root / 'intent.json'
    with intent.open('x', encoding='utf-8') as output:
        json.dump({'scope': 'synthetic protocol validation only',
                   'authorization': 'user continue implementation until report delivery',
                   'engineering_data': False, 'requests_planned': 2}, output)
    load_service_environment('hunan-highway-trial067-api-1')
    tools = [{'type': 'function', 'function': {
        'name': 'add', 'description': 'Return the sum of two integers.',
        'parameters': {'type': 'object', 'properties': {
            'a': {'type': 'integer'}, 'b': {'type': 'integer'}},
            'required': ['a', 'b'], 'additionalProperties': False}}}]
    messages = [{'role': 'user', 'content': 'Use add to compute 17+25, then give the sum.'}]
    if complex_case:
        messages = [
            {'role': 'user', 'content': 'Remember the earlier completed job: the sum was 9.'},
            {'role': 'assistant', 'content': 'The earlier job is complete: 9.'},
            {'role': 'user', 'content': (
                'A synthetic scheduling problem: job A takes 4h; B takes 7h after A; '
                'C takes 3h after A; D takes 5h after both B and C; E takes 2h after C. '
                'There are two workers. Determine the earliest time both D and E are '
                'finished, and give a feasible schedule explaining the lower bound. '
                'First use add to verify 17+25 as an independent checksum. Once its '
                'successful result arrives, do not repeat that checksum; finish the '
                'scheduling answer. Do not reveal private reasoning, only schedule and conclusion.')},
        ]
    if adapter:
        model = configured_model(Store(root), 'protocol_probe')
        bound = model.bind_tools(tools)
        history = [AIMessage(item['content']) if item['role'] == 'assistant' else HumanMessage(item['content'])
                   for item in messages]
        for index in range(2):
            answer = await bound.ainvoke(history)
            reasoning = answer.additional_kwargs.get('reasoning_content')
            metadata = {'round': index + 1, 'reasoning_present': isinstance(reasoning, str),
                        'reasoning_length': len(reasoning) if isinstance(reasoning, str) else None,
                        'tool_names': [call['name'] for call in answer.tool_calls],
                        'answer_mentions_expected': '16' in answer.content,
                        'usage': answer.usage_metadata}
            (root / f'round-{index + 1}.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
            print(json.dumps(metadata), flush=True)
            if index == 0:
                if len(answer.tool_calls) != 1 or answer.tool_calls[0]['name'] != 'add':
                    raise RuntimeError('PROBE_EXPECTED_ADD_TOOL_CALL')
                call = answer.tool_calls[0]
                if call['args'] != {'a': 17, 'b': 25}:
                    raise RuntimeError('PROBE_UNEXPECTED_ARGUMENTS')
                serde = JsonPlusSerializer()
                restored = serde.loads_typed(serde.dumps_typed(answer))
                history += [restored, ToolMessage('42', tool_call_id=call['id'])]
                payload = model._get_request_payload(history)
                assert payload['messages'][-2].get('reasoning_content') == reasoning
        return
    async with AsyncOpenAI(base_url=os.environ['REPORT_BASE_URL'],
                          api_key=os.environ['REPORT_API_KEY'], max_retries=0,
                          timeout=180) as client:
        for index in range(2):
            options = {} if index == 0 and not complex_case else {'extra_body': {
                'thinking': {'type': 'enabled', 'clear_thinking': False}}}
            response = await client.chat.completions.create(
                model=os.environ['REPORT_MODEL'], messages=messages, tools=tools,
                parallel_tool_calls=False, reasoning_effort='high',
                max_tokens=65536, **options)
            message = response.choices[0].message.model_dump(exclude_none=True)
            reasoning = message.get('reasoning_content')
            metadata = {'round': index + 1, 'finish_reason': response.choices[0].finish_reason,
                        'response_model': response.model,
                        'reasoning_present': isinstance(reasoning, str),
                        'reasoning_length': len(reasoning) if isinstance(reasoning, str) else None,
                        'reasoning_sha256': hashlib.sha256(reasoning.encode()).hexdigest()
                            if isinstance(reasoning, str) else None,
                        'tool_names': [c['function']['name'] for c in message.get('tool_calls', [])],
                        'answer_present': bool(message.get('content')),
                        'answer_mentions_expected': ('16' if complex_case else '42') in (message.get('content') or ''),
                        'usage': response.usage.model_dump() if response.usage else None}
            (root / f'round-{index + 1}.json').write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps(metadata), flush=True)
            if index == 0:
                calls = message.get('tool_calls', [])
                if len(calls) != 1 or calls[0]['function']['name'] != 'add':
                    raise RuntimeError('PROBE_EXPECTED_ADD_TOOL_CALL')
                args = json.loads(calls[0]['function']['arguments'])
                if args != {'a': 17, 'b': 25}:
                    raise RuntimeError('PROBE_UNEXPECTED_ARGUMENTS')
                messages.append({k: v for k, v in message.items()
                                 if k in {'role', 'content', 'tool_calls', 'reasoning_content'}})
                messages.append({'role': 'tool', 'tool_call_id': calls[0]['id'], 'content': '42'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--complex', action='store_true')
    parser.add_argument('--adapter', action='store_true')
    args = parser.parse_args()
    asyncio.run(main(args.complex or args.adapter, args.adapter))
