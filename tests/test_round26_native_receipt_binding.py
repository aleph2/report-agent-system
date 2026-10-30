"""Regression: native bound handoff release must not hide owned receipt metadata.

Scripted SDK responses exercise production registration/middleware only, not autonomy.
"""
import json
from collections import Counter

import httpx
import pytest
from langchain_core.messages import HumanMessage

from report_agent.content_store import Actor
from report_agent.deep_models import GLMChatOpenAI, model_async_client
from report_agent.deep_runtime import build_agent
from report_agent.store import digest
from test_deliverable_declaration_v4 import case
from test_prompt_native_sdk_inputs import completion
from test_review_binding_v4 import prepared, review_call
from test_reviewer_complete_materials import configure


def state_packet(body):
    marker = ('Current task bindings and navigation previews. Incomplete fields expose '
              'read_decision_state paths; previews do not establish complete instruction '
              'or evidence coverage:\n')
    for message in body['messages']:
        if message['role'] != 'system':
            continue
        content = message['content']
        parts = [content] if isinstance(content, str) else [p.get('text', '') for p in content]
        for text in parts:
            if marker in text:
                return json.JSONDecoder().raw_decode(text.split(marker, 1)[1])[0]
    raise AssertionError('Actual SDK request lacks native state packet')


@pytest.mark.parametrize('change_mutable_manifest', [False, True])
async def test_registered_native_handoff_sdk_keeps_owned_receipt_index(case, change_mutable_manifest):
    cs, declared, criteria, _ = prepared(case)
    workspace = configure(cs)
    foreign = cs.observe(Actor('foreign-reviewer', 'reviewer', 'foreign-task'),
                         {'secret': 'foreign payload'})['receipt_id']
    models, wires, counts = {}, [], Counter()

    def factory(role):
        if role in models:
            return models[role]
        client = model_async_client(cs.store, role)

        async def transport(request):
            body = json.loads(request.content)
            wires.append((role, body))
            step = counts[role]
            counts[role] += 1
            if role == 'coordinator':
                if step == 0:
                    return completion(request, '', ('task', review_call(criteria)['args']))
                return completion(request, 'Fixture observation only; review was not performed.')
            assert role == 'reviewer'
            if step == 0:
                if change_mutable_manifest:
                    cs.store.set('manifest', {**cs.store.manifest, 'context_projection': 'focused-v1'})
                return completion(request, '', ('read_context', {'target_ref': declared['refs']['a']}))
            return completion(request, 'Fixture only; no verdict or review save.')

        client._transport = httpx.MockTransport(transport)
        client._mounts.clear()
        models[role] = GLMChatOpenAI(model='glm-5.3', api_key='fixture-only',
            base_url='https://fixture.invalid/v1', use_responses_api=False,
            http_async_client=client, max_retries=0, disable_streaming=True)
        return models[role]

    try:
        agent = build_agent(workspace, factory, None)
        await agent.ainvoke({'messages': [HumanMessage('Observe the synthetic receipt boundary only.')]})
        reviewer = [body for role, body in wires if role == 'reviewer']
        assert len(reviewer) == 2
        packet = state_packet(reviewer[-1])
        assert packet['review_materials']['objects_complete'] is True
        assert len(packet['review_materials']['basis']['criterion_refs']) == 7
        assert 'observation_receipts' in packet, 'Native release omitted the selected receipt index'
        inventory = packet['observation_receipts']
        assert inventory['semantic_acceptance'] is False
        assert inventory['actor_id'] == packet['actor_id']
        assert foreign not in json.dumps(inventory)
        own = inventory['items']
        assert len(own) == 1
        assert own[0]['observed_material_refs'] == [declared['refs']['a']]
        with cs.store.connect() as db:
            saved = json.loads(db.execute('SELECT data FROM content_observations WHERE id=?',
                                         (own[0]['receipt_id'],)).fetchone()[0])
        assert own[0]['result_digest'] == digest(saved)
        assert cs.store.get('context_projection_binding') == 'review-materials-v1'
        assert not cs.list_objects('ReviewRecord')
    finally:
        for model in models.values():
            await model.root_async_client.close()
            model.root_client.close()
