"""Compatibility: exact legacy defaults plus explicit concise summary source/provenance."""
import hashlib
from pathlib import Path
from langchain_core.messages import HumanMessage
from report_agent.working_summary import working_summary
from report_agent.prompt_sources import load_prompt
from report_agent.store import Store
from test_hierarchical_content import ws
from test_bounded_deadline import offline_model,close_model

async def test_bare_store_legacy_and_explicit_concise_summary_remain_separate(ws,monkeypatch,tmp_path):
    normal=offline_model(ws,monkeypatch)
    try:
        bare=Store(tmp_path/'uninitialized')
        legacy=working_summary(normal,bare)
        concise=working_summary(normal,bare,prompt_profile='concise-v1')
        assert hashlib.sha256(legacy.summary_prompt.encode()).hexdigest()=='f07d90b4a03aa720187ca2232802cb3fdae5c3e24f42228ab4f4ba35b1b94e8c'
        assert concise.summary_prompt==load_prompt('working-summary-concise')
        assert concise.prompt_source=='working-summary-concise' and legacy.prompt_source=='working-summary'
        bare.set('manifest',{'report_prompt_profile':'legacy-v1'})
        assert concise.summary_prompt==load_prompt('working-summary-concise')
    finally:await close_model(normal)

async def test_explicit_concise_summary_final_sdk_matches_the_new_template_source(ws,monkeypatch):
    import httpx,json
    from test_prompt_native_sdk_inputs import completion
    from report_agent.deep_models import GLMChatOpenAI,model_async_client
    client=model_async_client(ws.store,'coordinator')
    normal=GLMChatOpenAI(model='glm-5.3',api_key='fixture-only',base_url='https://fixture.invalid/v1',
        use_responses_api=False,http_async_client=client,max_retries=0,disable_streaming=True)
    requests=[]
    def transport(request):
        requests.append(json.loads(request.content))
        return completion(request,'Synthetic unresolved working notes, not source evidence.')
    normal.http_async_client._transport=httpx.MockTransport(transport)
    normal.http_async_client._mounts.clear()
    try:
        summary=working_summary(normal,ws.store,'coordinator',prompt_profile='concise-v1')
        await summary._acreate_summary([HumanMessage('Preserve the nested error path; one failed receipt does not invalidate others.')])
        capture=next(ws.store.get(e['data']['capture_key']) for e in ws.store.events() if e['kind']=='prompt_final_http_input')
        assert capture['public_input']==requests[0]
        file,=capture['source_manifest']['files']
        assert file['name']=='working-summary-concise' and file['offered_match']=='summary_template_envelope'
        assert capture['source_manifest']['unresolved_sources']==[]
    finally:await close_model(normal)
