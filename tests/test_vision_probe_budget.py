"""One campaign/run budget for text and vision; original ledger rows stay intact."""
from hashlib import sha256
from io import BytesIO
import base64
import json

from PIL import Image
import httpx
import pytest

from report_agent.fake_verification_budget import FakeFlowBudget
from report_agent.token_budget import RequestBound, request_token_bound, token_budget, account_response_sync
from report_agent.request_budget import RequestBudgetExceeded, account_request_sync
from test_fake_fresh_comparison import pair
from test_fake_verification_launcher import packet
from test_probe_budget import finance

VISION='deepseek-v4.1-flash-1017'
TEXT='glm-5.3'
TEXT_URL='https://synthetic.invalid/text/chat/completions'
VISION_URL='https://synthetic.invalid/vision/chat/completions'
TEXT_BOUND=RequestBound(TEXT,sha256(TEXT_URL.encode()).hexdigest(),1048576,131072,'a'*64)


def visual_bound():
    return RequestBound(VISION,sha256(VISION_URL.encode()).hexdigest(),1000000,8202,'b'*64,
                        image_max_edge=1024,wire_output_limit=8192)


def budget(pair,cap=5500000):
    _,_,grant,c=pair
    return FakeFlowBudget(grant,'mixed',{**c,'run_ids':['mixed']},'c'*64,
                          maximum_tokens=cap,model_bounds={VISION:visual_bound().total})


def image_url(edge=1):
    out=BytesIO();im=Image.new('RGB',(edge,edge),'white');im.save(out,format='PNG');im.close()
    return 'data:image/png;base64,'+base64.b64encode(out.getvalue()).decode()


def body(model):
    return {'model':model,'stream':False,'max_completion_tokens':8192 if model==VISION else 65536,
        'messages':[{'role':'user','content':[{'type':'text','text':'Locate the drawing subject'},
                    {'type':'image_url','image_url':{'url':image_url()}}]}] if model==VISION else [{'role':'user','content':'Plan'}]}


def send(account,model,used=10,change=None,provider=None):
    payload=body(model);payload.update(change or {})
    handler=provider or (lambda _:httpx.Response(200,json={'usage':{'total_tokens':used}}))
    with token_budget(account),request_token_bound((TEXT_BOUND,visual_bound())):
        with httpx.Client(transport=httpx.MockTransport(handler),event_hooks={
                'request':[account_request_sync],'response':[account_response_sync]}) as client:
            return client.post(VISION_URL if model==VISION else TEXT_URL,json=payload)


def test_mixed_models_charge_same_run_without_changing_original_authorization_or_hold(pair):
    account=budget(pair);before=finance(account)
    send(account,TEXT,11);send(account,VISION,20)
    assert account.run_snapshot()=={'maximum_tokens':5500000,'settled':31,'held':0}
    after=finance(account)
    assert before['auth']==after['auth']
    assert all(row in after['rows'] for row in before['rows'])
    assert account.snapshot()['reserved_or_unknown_upper_bounds']==1179648


def test_mixed_models_exact_cap_and_one_more_request(pair):
    account=budget(pair)
    for _ in range(3):send(account,TEXT,TEXT_BOUND.total)
    send(account,VISION,5500000-3*TEXT_BOUND.total-visual_bound().total)
    send(account,VISION,visual_bound().total)
    assert account.run_snapshot()['settled']==5500000
    for model in [TEXT,VISION]:
        with pytest.raises(RequestBudgetExceeded):send(account,model,provider=lambda _:pytest.fail('cap dispatched'))


def test_unknown_visual_request_blocks_every_model_without_releasing_holds(pair):
    account=budget(pair);send(account,VISION,provider=lambda _:httpx.Response(200,json={}))
    before=finance(account)
    assert account.run_snapshot()['held']==visual_bound().total
    for model in [TEXT,VISION]:
        with pytest.raises(RequestBudgetExceeded):send(account,model,provider=lambda _:pytest.fail('unknown replay'))
    assert finance(account)==before
    assert account.snapshot()['reserved_or_unknown_upper_bounds']==1179648+visual_bound().total


@pytest.mark.parametrize('kind',['output','oversize','remote','glm_image'])
def test_vision_policy_does_not_weaken_text_or_dispatch_invalid_wire(pair,kind):
    account=budget(pair);before=finance(account);payload=body(VISION)
    if kind=='output':payload['max_completion_tokens']=8193
    if kind=='oversize':payload['messages'][0]['content'][1]['image_url']['url']=image_url(1025)
    if kind=='remote':payload['messages'][0]['content'][1]['image_url']['url']='https://external.invalid/image.png'
    if kind=='glm_image':payload['model']=TEXT
    with pytest.raises(RequestBudgetExceeded):
        send(account,payload['model'],change=payload,provider=lambda _:pytest.fail('invalid wire dispatched'))
    assert finance(account)==before
