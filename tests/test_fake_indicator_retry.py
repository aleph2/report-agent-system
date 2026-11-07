"""A resumed indicator may use exactly one response and cannot advance another row."""
import json
from types import SimpleNamespace
from pathlib import Path

import pytest

from report_agent.mini_commission import prepare_mini_commission
from report_agent.workspace import Workspace
from report_agent.store import Store
from report_agent.content_store import ContentStore
from report_agent.writer_assessment import read_indicator_step
from report_agent.writer_runtime import writer_session
from test_writer_context_replay import glm_model, reply
from test_transport_observation import close


@pytest.mark.asyncio
@pytest.mark.parametrize('mode',['valid','refused','twice'])
async def test_one_request_only_even_for_a_refused_save(tmp_path, monkeypatch, mode):
    case=tmp_path/'case'
    prepare_mini_commission(Path(__file__).parent/'fake_data/mini_commission/inputs',case)
    ws=Workspace(Store(case))
    def decide(turn, body):
        assert turn==1
        assert 'read_assigned_page' not in {t['function']['name'] for t in body['tools']}
        assert 'ORIGINAL PAGE TEXT' in json.dumps(body['messages'])
        calls=[('one','save_gap',{'missing':'Missing comparison.','question':'Which angle?'} if mode=='valid' else {'typo':1})]
        if mode=='twice':
            calls.append(('two','save_gap',{'extra':'bad'}))
        return reply(calls)
    model, wires=glm_model(SimpleNamespace(ws=ws),monkeypatch,decide)
    try:
        with writer_session(ws,'坡段 A',model,assessment_only=True,indicator_steps=True,section_id='3') as session:
            step=read_indicator_step(ContentStore(ws.store),session.actor)
            reads=[{'location':{'source_handle':'source-4','page':1},'content':'ORIGINAL PAGE TEXT'}]*3
            await session.run(continuation=(step,reads))
            assert session.progress['progress']['recorded']==int(mode=='valid')
            assert bool(session.progress['interrupted_indicators'])==(mode=='twice')
            assert len(wires)==1
    finally:
        await close(model)
