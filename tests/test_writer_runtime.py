import json
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from report_agent.writer_runtime import writer_session
from report_agent.errors import ActionRejected
from test_m1_g3_integration import method_commission, section_plan, persistence_input
from test_m1_commission_plan import save, approve
from test_deep_runtime import Driver, invoke

@pytest.fixture
def ready(method_commission):
    f=method_commission
    if 'Owner rank order:' in f.ws.store.manifest['goal']:
        from test_writer_indicator_outcomes import attach_ranks
        attach_ranks(f)
    saved=save(f,section_plan(f));approve(f,saved)
    f.ws.store.set('manifest',{**f.ws.store.manifest,'assembly_contract':'system-assembler-v1'})
    return f

def test_fresh_assignment_is_host_scoped_and_public_tools_have_no_ids(ready):
    f=ready;driver=Driver(writer=[])
    with writer_session(f.ws,'Slope 1',driver('writer'), assessment_only=True, indicator_steps=True) as session:
        task=f.cs.read({'type':'DelegatedTask','id':session.actor.task_id,'version':1})['payload']
        assert task['assessment_object_id']=='S1' and task['section_ids']==['4']
        names=set(session.tool_names)
        assert {'read_assigned_page','save_evidence','save_assumption','save_gap','propose_material_issue'}==names
        assert not names&{'calculate_assessment','task','write_file','grep','commit_objects','freeze_snapshot'}
        for tool in session.tools:
            schema=tool.tool_call_schema.model_json_schema()
            assert not {'operation_id','method_id','method_version','object_id','indicator_id','source_ref','node_ref','locator'}&schema.get('properties',{}).keys()

@pytest.mark.asyncio
@pytest.mark.parametrize('method_commission',['with-owner-ranks'],indirect=True)
async def test_native_context_is_fresh_small_and_pins_exact_new_prompt(ready):
    f=ready
    for marker in ['FIRST_PRIVATE_HISTORY','SECOND_FRESH_HISTORY']:
        driver=Driver(writer=[AIMessage(content=marker)])
        with writer_session(f.ws,'Slope 1',driver('writer'),assessment_only=True,indicator_steps=True) as session:
            with pytest.raises(ActionRejected,match='PROBE_INDICATOR_STEP_INTERRUPTED'):
                await session.run()
            first=driver.calls[0][2]
            assert not any(isinstance(m,(AIMessage,ToolMessage)) for m in first)
            assert not any('FIRST_PRIVATE_HISTORY' in str(m.content) for m in first)
            assert sum(len(str(m.content).encode()) for m in first)<60000
            assert any('indicator_id' in str(m.content) for m in first)
        with f.ws.store.connect() as db:
            captured=[json.loads(r[0]) for r in db.execute("SELECT data FROM events WHERE kind='prompt_model_input'")]
        assert captured and all(v['status']=='exact' for v in captured)


def test_assigned_writer_cannot_save_another_slope(ready):
    from report_agent.risk_scoring import save_assessment
    f=ready
    with writer_session(f.ws,'Slope 1',Driver(writer=[])('writer'), assessment_only=True, indicator_steps=True) as session:
        payload=persistence_input(f);payload['object_id']='S2'
        with pytest.raises(ActionRejected):save_assessment(f.cs,session.actor,'foreign-object',payload)
    assert not f.cs.list_objects('Assessment')

def test_session_has_no_checkpoint_resume_surface(ready):
    from inspect import signature
    assert not {'resume','checkpoint','thread_id','task_id'}&signature(writer_session).parameters.keys()


from test_writer_assignments import assigned


@pytest.mark.asyncio
@pytest.mark.parametrize('method_commission',['with-owner-ranks'],indirect=True)
async def test_original_page_pixels_reach_the_next_native_request(assigned):
    from report_agent.writer_assignments import resolve_visual_pages
    f = assigned
    f.ws.store.set('manifest', {**f.ws.store.manifest, 'assembly_contract': 'system-assembler-v1'})
    def choose_page(messages):
        sources = json.loads(next(m.content for m in messages if isinstance(m, HumanMessage)))['sources']
        source = next(s for s in sources if s['title'] == 'design')
        return invoke('read_assigned_page', source_handle=source['source_handle'], page=2)
    driver = Driver(writer=[choose_page, AIMessage(content='read image')])
    with writer_session(f.ws, f.plan['objects'][0]['label'], driver('writer'), assessment_only=True, indicator_steps=True) as session:
        with pytest.raises(ActionRejected,match='PROBE_INDICATOR_STEP_INTERRUPTED'):
            await session.run()
        page = next(m for m in driver.calls[-1][2] if isinstance(m, ToolMessage) and m.name == 'read_assigned_page')
        assert isinstance(page.content, list)
        pixels = next(b for b in page.content if b['type'] == 'image_url')
        assert pixels['image_url']['url'].startswith('data:image/png;base64,')
        info = json.loads(next(b['text'] for b in page.content if b['type'] == 'text'))
        assert not {'image_ref', 'source_id', 'sha256', 'image_sha256', 'source_ref'} & info.keys()
        with f.ws.store.connect() as db:
            citations = resolve_visual_pages(f.cs, db, session.actor, [info['page_handle']])
        assert citations == [{'source_ref': f.pdf_ref, 'locator': 'page 2', 'quote': ''}]


@pytest.mark.asyncio
@pytest.mark.parametrize('method_commission',['with-owner-ranks'],indirect=True)
async def test_text_only_model_receives_page_text_without_visual_read_credit(assigned):
    f = assigned
    f.ws.store.set('manifest', {**f.ws.store.manifest, 'assembly_contract': 'system-assembler-v1'})
    def choose_page(messages):
        source = next(s for s in json.loads(next(m.content for m in messages if isinstance(m, HumanMessage)))['sources'] if s['title'] == 'design')
        return invoke('read_assigned_page', source_handle=source['source_handle'], page=3, view='native_text')
    driver = Driver(writer=[choose_page, AIMessage(content='Text only; no visual verification.')])
    model = driver('writer'); model.profile = {'image_inputs': False, 'image_tool_message': False}
    with writer_session(f.ws, f.plan['objects'][0]['label'], model,assessment_only=True,indicator_steps=True) as session:
        with pytest.raises(ActionRejected,match='PROBE_INDICATOR_STEP_INTERRUPTED'):
            await session.run()
    page = next(m for m in driver.calls[-1][2] if isinstance(m, ToolMessage) and m.name == 'read_assigned_page')
    assert [block['type'] for block in page.content] == ['text']
    view = json.loads(page.content[0]['text'])
    assert view['native_text'] == 'Drawing K1p250'
    assert view['visual_evidence'] == 'SYSTEM_VISUAL_CAPABILITY_UNAVAILABLE'
    assert 'page_handle' not in view
    from report_agent.writer_judgments import delivered_pages
    with f.ws.store.connect() as db:
        deliveries = [r for _,r in delivered_pages(db) if r['actor']['id']==session.actor.id]
    assert [(r['page'],r['modality']) for r in deliveries] == [(3,'text')]
    assert not any(r.get('image_delivered') for r in deliveries)


def test_indicator_session_requires_assessment_scope_before_opening_case():
    with pytest.raises(ActionRejected, match='ASSESSMENT_ONLY_WORKFLOW_REQUIRED'):
        with writer_session(None, 'Slope 1', None, indicator_steps=True):
            pytest.fail('unscoped writer was launched')
