"""Author instruction reaches the SDK; fake output does not prove semantic quality."""
import json
from hashlib import sha256
import httpx

from report_agent.content_models import ContentNode
from report_agent.content_tasks import delegated_task
from report_agent.deep_models import GLMChatOpenAI,model_async_client
from report_agent.evidence_analysis import analyze_evidence_packet
from report_agent.prompt_sources import describe_content_schema,load_prompt
from test_hierarchical_content import ws,seed
from test_native_operation_identity import activate
from test_prompt_native_sdk_inputs import completion
from test_text_work import writer_call


async def test_pricing_inclusion_instruction_reaches_actual_author_sdk_and_source_capture(ws):
    seed(ws);activate(ws)
    ws.store.set('manifest',{**ws.store.manifest,'review_interface_profile':'review-interfaces-v4',
        'review_entrypoint':'delegated-reviewer-v1',
        'review_execution_mode':'native-reviewer-v2','delegation_prompt_profile':'separate-description-v1',
        'report_expression_profile':'reader-expression-v2','report_prompt_profile':'concise-v1'})
    prompt=load_prompt('text-work-v2')
    assert 'distinguish charges already included from charges not to be added' in prompt
    schema,_=describe_content_schema(ContentNode.model_json_schema())
    client=model_async_client(ws.store,'text_tool');wires=[]
    def respond(request):
        wires.append(json.loads(request.content))
        return completion(request,json.dumps({'body':{'text':'含税合计2160元，不另加税费。'},
            'qualifiers':{'范围':'缺少实测厚度，不作工程验收。'},'claim_kind':'inference'},ensure_ascii=False))
    client._transport=httpx.MockTransport(respond);client._mounts.clear()
    model=GLMChatOpenAI(model='glm-5.3',api_key='fixture-only',base_url='https://fixture.invalid/v1',
        use_responses_api=False,http_async_client=client,max_retries=0,disable_streaming=True)
    try:
        with delegated_task(ws,'coordinator',writer_call()):
            await analyze_evidence_packet(ws,model,{'output_schema':schema,'evidence':[
                {'source':'Synthetic pricing sheet','content':'含税合计2160元，不另加税费；缺少实测厚度。'}]},
                prompt,'independent-text-tools-v1')
        assert len(wires)==1
        assert any(prompt in message['content'] for message in wires[0]['messages'] if isinstance(message['content'],str))
        capture=next(ws.store.get(e['data']['capture_key']) for e in ws.store.events() if e['kind']=='prompt_final_http_input')
        assert capture['public_input']==wires[0]
        sources=capture['source_manifest']['files']
        source=next(f for f in sources if f['name']=='text-work-v2')
        assert source['text_sha256']==sha256(prompt.encode()).hexdigest()
    finally:
        await model.root_async_client.close();model.root_client.close()
