"""Diagnostic failures versus authoritative local refusal; no external I/O."""
import json

import httpx
import pytest
from langchain_core.messages import HumanMessage

import report_agent.prompt_provenance as provenance
from report_agent.deep_models import GLMChatOpenAI, model_async_client
from report_agent.evidence_analysis import analyze_evidence_packet
from report_agent.request_budget import logical_request_admission, account_request_sync
from report_agent.working_summary import working_summary
from test_hierarchical_content import ws
from test_prompt_composition_boundary import response


def test_observation_projection_failure_does_not_change_caller_outcome(ws,monkeypatch):
    """P07: projection, decoding and sink all belong to the failsoft observer."""
    def broken(_):raise RuntimeError('Synthetic diagnostic failure')
    monkeypatch.setattr(provenance,'public_projection',broken)
    with provenance.prompt_call(ws.store,'fixture-observation',offered={'messages':[]}):
        provenance.observe_prompt_request(httpx.Request('POST','https://fixture.invalid',json={}),ws.store,'reviewer')
    # Malformed/custom bodies are also a diagnostic gap, not a transport veto.
    provenance.observe_prompt_request(httpx.Request('POST','https://fixture.invalid',content=b'not-json'),ws.store,'vision')
    gaps=[e for e in ws.store.events() if e['kind']=='prompt_capture_unavailable']
    assert len(gaps)==3 and all(e['data']['status']=='unexplained' for e in gaps)


@pytest.mark.parametrize('previously_admitted',[False,True])
def test_only_this_exception_with_zero_admissions_has_not_dispatched_proof(ws,previously_admitted):
    with logical_request_admission() as trace, provenance.prompt_call(ws.store,'fixture'):
        if previously_admitted:
            account_request_sync(httpx.Request('POST','https://fixture.invalid',json={'messages':[]}))
        provenance.bind_wire_payload({'messages':[{'role':'system','content':'original'}]})
        with pytest.raises(provenance.PromptCompositionError) as caught:
            provenance.admit_prompt_request(httpx.Request('POST','https://fixture.invalid',
                json={'messages':[{'role':'system','content':'changed'}]}))
        proof=trace.not_dispatched_proof(caught.value)
        if previously_admitted:assert proof is None
        else:
            assert proof and proof['admitted_http_attempts']==0
            assert proof['admission_boundary']=='http_request_hook_before_financial_accounting'
            assert trace.not_dispatched_proof(provenance.PromptCompositionError(str(caught.value))) is None


@pytest.mark.parametrize('purpose',['summary','analysis'])
async def test_pre_financial_composition_refusal_is_not_unknown_model_outcome(ws,purpose):
    sent=[]
    async def mutate(request):
        body=json.loads(request.content);body['messages'][0]['content']+=' synthetic undeclared mutation'
        request._content=json.dumps(body).encode();request.headers['content-length']=str(len(request._content))
    client=model_async_client(ws.store,'text_tool',extra_hooks=[mutate])
    async def transport(request):sent.append(request);return response(request)
    client._transport=httpx.MockTransport(transport);client._mounts.clear()
    model=GLMChatOpenAI(model='glm-5.3',api_key='fixture-only',base_url='https://fixture.invalid/v1',
        use_responses_api=False,http_async_client=client,max_retries=0,disable_streaming=True)
    summary=working_summary(model,ws.store,role='coordinator')
    try:
        with pytest.raises(provenance.PromptCompositionError):
            if purpose=='summary':await summary._acreate_summary([HumanMessage(content='Fixture current task.')])
            else:await analyze_evidence_packet(ws,model,{'objective':'fixture'},'Fixture known role.',
                'custom-fixture-v1',reserve_attempt=True)
        assert sent==[]
        if purpose=='summary':
            record=ws.store.get(summary._failure_key())
        else:
            event=next(e for e in ws.store.events() if e['kind']=='evidence_analysis_input')
            record=ws.store.get('bounded_review_attempt:'+event['data']['operation'])
        assert record['provider_outcome']=='not_dispatched',record
        assert record['admission_proof']['admitted_http_attempts']==0
    finally:await client.aclose()


async def test_visual_pre_financial_composition_refusal_preserves_known_no_send(tmp_path):
    """Same sibling rule for the existing real vision SDK entry."""
    from openai import AsyncOpenAI
    from report_agent.vision import observe_source_image
    from test_document_tools import workspace
    visual=workspace(tmp_path/'visual');sent=[]
    async def mutate(request):
        value=json.loads(request.content);value['messages'][0]['content']+=' undeclared mutation'
        request._content=json.dumps(value).encode();request.headers['content-length']=str(len(request._content))
    client=model_async_client(visual.store,'vision',extra_hooks=[mutate])
    async def transport(request):sent.append(request);return response(request)
    client._transport=httpx.MockTransport(transport);client._mounts.clear()
    sdk=AsyncOpenAI(api_key='fixture-only',base_url='https://fixture.invalid/v1',max_retries=0,http_client=client)
    try:
        result=await observe_source_image(visual,'original','Inspect synthetic page.',client=sdk)
        assert result['provider_outcome']=='not_dispatched',result
        assert result['admission_proof']['admitted_http_attempts']==0 and sent==[]
    finally:await sdk.close()
