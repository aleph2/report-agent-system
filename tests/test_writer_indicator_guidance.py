"""The confirmed method and commission supply the Writer's context for each judgment."""
from pathlib import Path

import pytest

from report_agent import writer_assessment as api
from report_agent.content_store import ContentStore
from report_agent.mini_commission import prepare_mini_commission
from report_agent.store import Store
from report_agent.workspace import Workspace
from report_agent.writer_runtime import writer_session
from test_m1_g3_integration import method_commission
from test_writer_indicator_outcomes import ranked


def test_real_method_marks_only_its_two_documentation_indicators_and_projects_scope_rule(tmp_path):
    inputs = Path(__file__).parent / 'fake_data' / 'mini_commission' / 'inputs'
    prepared = prepare_mini_commission(inputs, tmp_path/'case')
    ws = Workspace(Store(tmp_path/'case'))
    cs = ContentStore(ws.store)
    plan = cs.read(prepared['plan_ref'])['payload']
    req = cs.read(plan['requirements_ref'])['payload']
    priority_id, = [i['anchor_id'] for i in req['items'] if 'source_priority' in i['capabilities']]
    source = next(a['source'] for a in req['anchors'] if a['id'] == priority_id)
    object_label = next(o['label'] for o in plan['objects'] if o['object_id'] == 'A')
    marked = set()
    with writer_session(ws, object_label, None, assessment_only=True, indicator_steps=True,
                        section_id=prepared['assessment_section_id']) as session:
        for _ in range(11):
            step = api.read_indicator_step(cs, session.actor)
            assert step['source_priority'] == [{'scope_quote': source['quote'], 'location': source['locator'],
                                                'interpretation': source['quote']}]
            rule = next(r for r in plan['method_pack']['indicators'] if r['id'] == step['indicator_id'])
            assert step['category'] == rule['category']
            if step.get('documentation_note'):
                marked.add(step['indicator_id'])
                assert 'unavailable' in step['documentation_note'] and 'positive evidence' in step['documentation_note']
                assert 'absence only if a source states the absence for this object' in step['documentation_note']
            api.save_indicator_outcome(cs, session.actor, 'test-'+step['indicator_id'], step['indicator_id'],
                {'kind':'gap','missing':'Synthetic traversal of all approved method rules.','question':'Review fixture?'})
    assert marked == {'X51', 'X52'}


@pytest.mark.parametrize('method_commission', ['with-owner-ranks'], indirect=True)
def test_unclassified_legacy_plan_keeps_its_own_conventions(ranked):
    step = api.read_indicator_step(ranked.cs, ranked.actor)
    assert step['source_priority'] is None and step['owner_conventions']
    assert 'documentation_note' not in step


@pytest.mark.asyncio
@pytest.mark.parametrize('method_commission', ['with-owner-ranks'], indirect=True)
async def test_writer_sdk_request_carries_judgment_and_precedence_instructions(ranked, monkeypatch):
    from test_writer_context_replay import glm_model, reply
    from test_transport_observation import close
    f = ranked
    def respond(turn, body):
        return reply([('test-save-'+str(turn), 'save_gap',
                       {'missing':'Synthetic prompt test.', 'question':'Supply the missing fact?'})])
    model, wires = glm_model(f, monkeypatch, respond)
    try:
        with writer_session(f.ws, 'Slope 1', model, assessment_only=True, indicator_steps=True) as session:
            await session.run()
    finally:
        await close(model)
    import json
    instructions = json.dumps([m['content'] for m in wires[0]['messages'] if m['role']=='system'], ensure_ascii=False)
    assert 'every supported interpretation gives the same grade' in instructions
    assert 'two or three plausible grades' in instructions and 'choose a provisional grade' in instructions
    assert 'Reserve review questions for unresolved inputs' in instructions
    assert 'cite the relationship that justifies transfer' in instructions
    assert 'source_priority' in instructions and 'quoted owner_conventions' in instructions
