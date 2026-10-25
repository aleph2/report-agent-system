"""Native graph and final SDK input for runtime-owned producer identity."""
import json
from collections import Counter

import httpx

from report_agent import deep_runtime
from report_agent.deep_models import GLMChatOpenAI, model_async_client
from test_hierarchical_content import ws, seed
from test_bounded_review import Model
from test_text_work import content
from test_prompt_native_sdk_inputs import completion


async def test_final_sdk_has_no_technical_id_and_success_is_queryable(ws):
    seed(ws)
    ws.store.set('manifest', {**ws.store.manifest,
        'review_entrypoint': 'delegated-reviewer-v1',
        'content_input_profile': 'relation-endpoints-v2',
        'operation_identity_profile': 'native-tool-runtime-v1'})
    producer = Model(json.dumps(content()))
    models, wires, counts = {}, [], Counter()

    def factory(role):
        if role == 'text_tool':
            return producer
        if role in models:
            return models[role]
        client = model_async_client(ws.store, role)
        async def transport(request):
            body = json.loads(request.content)
            wires.append((role, body))
            step = counts[role]
            counts[role] += 1
            if role == 'coordinator':
                if step == 0:
                    return completion(request, '', ('task', {
                        'subagent_type': 'writer', 'description': 'Describe supplied material.'}))
                return completion(request, 'Draft returned; independent review remains.')
            assert role == 'writer'
            if step == 0:
                return completion(request, '', ('process_report_content', {
                    'objective': 'Describe supplied material', 'object_type': 'ContentNode',
                    'source_selections': [{'source_id': 's'}]}))
            last = json.loads(next(m['content'] for m in reversed(body['messages']) if m['role'] == 'tool'))
            if step == 1:
                assert last['operation_id'] == 'native:process_report_content:fixture-process_report_content'
                return completion(request, '', ('get_operation_receipt', {'operation_id': last['operation_id']}))
            assert last['state'] == 'known_text_attempt' and last['text_work']['state'] == 'completed'
            return completion(request, 'Candidate produced and receipt inspected.')
        client._transport = httpx.MockTransport(transport)
        client._mounts.clear()
        models[role] = GLMChatOpenAI(model='glm-5.3', api_key='offline-only',
            base_url='https://fixture.invalid/v1', use_responses_api=False,
            http_async_client=client, max_retries=0, disable_streaming=True)
        return models[role]

    try:
        result = await deep_runtime.run_report(ws, factory)
        assert result['last_error'] is None, result
        wire = next(body for role, body in wires if role == 'writer')
        function = next(t['function'] for t in wire['tools'] if t['function']['name'] == 'process_report_content')
        assert not {'operation_id', 'runtime'} & function['parameters']['properties'].keys()
        assert 'supported_by and contradicted_by require a ContentNode subject_ref and an Evidence object_ref' in json.dumps(wire['tools'])
        assert len(producer.calls) == 1
        assert len([e for e in ws.store.events() if e['kind'] == 'prompt_final_http_input']) == len(wires)
    finally:
        for model in models.values():
            await model.root_async_client.close()
            model.root_client.close()
