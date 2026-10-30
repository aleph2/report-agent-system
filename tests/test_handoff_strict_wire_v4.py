"""Provider codec plus actual SDK MockTransport, without contacting a provider."""
import json
from pathlib import Path

import httpx
from langchain_core.messages import HumanMessage
from langchain_core.tools import StructuredTool
from langchain_core.utils.function_calling import convert_to_openai_tool

from report_agent.content_tasks import task_tool
from report_agent.deep_models import GLMChatOpenAI
from report_agent.deepseek_strict import StrictCodec
from test_deepseek_strict import schema_check
from test_deliverable_declaration_v4 import case
from test_review_binding_v4 import prepared, review_call
from test_prompt_native_sdk_inputs import completion


async def test_v4_deepseek_strict_sdk_wire_roundtrips_legal_business_choices(case):
    cs, _, criteria, _ = prepared(case)
    def task(description: str, subagent_type: str) -> str:
        """Native delegation capability."""
        return description
    tool = task_tool(StructuredTool.from_function(task), review_profile='native-reviewer-v2',
                     interface_profile='review-interfaces-v4')
    original = convert_to_openai_tool(tool)['function']
    codec = StrictCodec(original)
    schema_check(codec.function['parameters'])
    from support.flat_task_fixture import task_arguments
    arguments = task_arguments(cs, case[1], review_call(criteria)['args'])
    encoded = codec.encode(arguments)
    assert codec.decode(encoded) == arguments
    wires = []
    def transport(request):
        wires.append(json.loads(request.content))
        return completion(request, '', ('task', encoded))
    client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    model = GLMChatOpenAI(model='deepseek-v4-pro', api_key='fixture-only',
        base_url='https://fixture.invalid/beta', http_async_client=client,
        use_responses_api=False, max_retries=0, disable_streaming=True, deepseek_strict=True)
    try:
        result = await model.bind_tools([tool]).ainvoke([HumanMessage('Synthetic codec contract only.')])
        assert result.tool_calls[0]['args'] == arguments and not result.invalid_tool_calls
        assert wires[0]['tools'][0]['function']['strict'] is True
        destination = case[0].store.root / 'effective-deepseek-v4.json'
        destination.write_text(json.dumps({'synthetic_only':True, 'wire':wires[0],
            'decoded_arguments':result.tool_calls[0]['args'],
            'limitation':'SDK codec protocol only; no provider acceptance, production parameter or autonomy proof.'},
            ensure_ascii=False,indent=2), encoding='utf-8')
    finally:
        await client.aclose()
        model.root_client.close()
