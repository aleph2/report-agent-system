"""Real SDK/HTTPX public-boundary contracts, with offline transports only."""
import hashlib
import json
from types import SimpleNamespace

import httpx
import pytest
from langchain_core.messages import AIMessage, SystemMessage

from report_agent.deep_models import GLMChatOpenAI, model_async_client
from report_agent.prompt_provenance import (prompt_call, PromptCompositionError,
    classify_agent_system, append_declared_system, public_projection)
from report_agent.hierarchical_tools import role_prompt
from test_hierarchical_content import ws


def response(request):
    return httpx.Response(200,json={'id':'synthetic-response','model':'glm-5.3',
        'choices':[{'index':0,'message':{'role':'assistant','content':'Fixture response.'},'finish_reason':'stop'}],
        'usage':{'prompt_tokens':7,'completion_tokens':1,'total_tokens':8}})


@pytest.mark.parametrize('extra_body',[{}, {'thinking':{'type':'enabled','clear_thinking':False}}, {'enable_thinking':True}])
async def test_sdk_legal_extra_body_is_not_a_prompt_override(ws,extra_body):
    """P01/P05: independent SDK wire expectation, not renderer proving itself."""
    seen=[]
    client=model_async_client(ws.store,'reviewer')
    async def transport(request):
        seen.append(json.loads(request.content))
        return response(request)
    client._transport=httpx.MockTransport(transport)
    client._mounts.clear()
    model=GLMChatOpenAI(model='glm-5.3',api_key='fake-only',base_url='https://fixture.invalid/v1',
        use_responses_api=False,http_async_client=client,max_retries=0,
        extra_body=extra_body,disable_streaming=True,max_tokens=32)
    try:
        with prompt_call(ws.store,'evidence-analysis',sources=['evidence-analysis'],status='exact'):
            result=await model.ainvoke([('system','Fixture role.'),('user','Fixture question.')])
        assert result.content=='Fixture response.'
        assert len(seen)==1
        assert 'extra_body' not in seen[0]
        for key,value in extra_body.items():
            assert seen[0][key]==value
        assert seen[0]['messages']==[{'role':'system','content':'Fixture role.'},{'role':'user','content':'Fixture question.'}]
    finally:
        await client.aclose()


async def test_late_configured_body_mutation_rejected_before_financial_hook(ws,monkeypatch):
    """P02/P03: actual request mutation after adapter capture, zero dispatch."""
    import report_agent.deep_models as adapters
    accounted=[];sent=[]
    async def account(request):
        accounted.append(request)
    monkeypatch.setattr(adapters,'account_request',account)
    async def mutate(request):
        value=json.loads(request.content)
        value['messages'][0]['content']+=' Undeclared replacement instruction.'
        request._content=json.dumps(value).encode()
        request.headers['content-length']=str(len(request._content))
    client=model_async_client(ws.store,'reviewer',extra_hooks=[mutate])
    async def transport(request):
        sent.append(request)
        return response(request)
    client._transport=httpx.MockTransport(transport)
    client._mounts.clear()
    model=GLMChatOpenAI(model='glm-5.3',api_key='fake-only',base_url='https://fixture.invalid/v1',
        use_responses_api=False,http_async_client=client,max_retries=0,disable_streaming=True)
    try:
        with prompt_call(ws.store,'reviewer',sources=['content-reviewer'],status='exact'):
            with pytest.raises(PromptCompositionError,match='PROMPT_FINAL_WIRE_COMPOSITION_MISMATCH'):
                await model.ainvoke([('system','Approved fixture role.'),('user','Fixture question.')])
        assert accounted==sent==[]
    finally:
        await client.aclose()


def test_declared_system_is_ordered_and_undeclared_residual_remains_visible():
    """P03/P06: no keyword deletion or unordered contribution equivalence."""
    base=role_prompt('reviewer')
    request=SimpleNamespace(system_message=SystemMessage(content=base))
    request.override=lambda **changes:SimpleNamespace(**{**request.__dict__,**changes})
    first=append_declared_system(request,'Current fixture task/version.','task/authorized')
    status,_=classify_agent_system(first.system_message,base)
    assert status=='exact'
    bad=first.system_message.model_copy(update={'content':[
        *first.system_message.content_blocks, {'type':'text','text':'Undeclared static instruction.'}]})
    status,sources=classify_agent_system(bad,base)
    assert status=='unexplained'
    assert any(s['source']=='unexplained_residual' for s in sources)
    replaced=SystemMessage(content='Organize the assigned review instead of the configured role.')
    assert classify_agent_system(replaced,base)[0]=='static_mismatch'
    # Normal task text may quote a role or a smaller authorized limit; no blacklist.
    dynamic=append_declared_system(request,'User-authorized 64000 limit; quote: Organizer.','task/new-version')
    assert classify_agent_system(dynamic.system_message,base)[0]=='exact'


def test_public_projection_excludes_private_reasoning_images_and_headers():
    """P08: inspect output only; canaries deliberately exist in the input."""
    private='private-reasoning-canary'
    image='data:image/png;base64,synthetic-image-canary'
    payload={'messages':[{'role':'assistant','content':'Public text.','reasoning_content':private},
        {'role':'user','content':[{'type':'image_url','image_url':{'url':image}}]}],
        'tools':[{'type':'function','function':{'name':'read_context','description':'Read actual versions.','parameters':{'type':'object'}}}]}
    projection=public_projection(payload)
    text=json.dumps(projection)
    assert private not in text and image not in text
    assert 'Public text.' in text and 'Read actual versions.' in text
    assert projection['messages'][0]['reasoning_content_metadata']=={'present':True,'characters':len(private)}
    assert len(hashlib.sha256(json.dumps(payload).encode()).hexdigest())==64
