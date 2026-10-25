"""Actor-owned receipt facts survive hostile historical notes without new reads."""
import json

from langchain_core.messages import HumanMessage

from report_agent.content_tasks import delegated_task
from report_agent.content_store import Actor
from report_agent.decision_state import read_state
from report_agent.task_context import TaskContext, exact_task_context
from test_progress_retention import presented
from test_reviewer_complete_materials import configure
from test_review_binding_v4 import prepared, review_call
from test_deliverable_declaration_v4 import case


async def test_final_reviewer_context_keeps_full_owned_receipt_facts_when_notes_claim_expiry(case):
    cs, _, criteria, _ = prepared(case)
    workspace = configure(cs)
    with delegated_task(workspace, 'coordinator', review_call(criteria)) as (_, actor):
        task = cs.read({'type': 'DelegatedTask', 'id': actor.task_id, 'version': 1})['payload']
        target = task['review_requirements'][0]['target_ref']
        own = cs.read_context(actor, target)['receipt_id']
        other = cs.observe(Actor('private-other-owner', 'reviewer', 'private-other-task'),
                           {'secret': 'private-other-payload'})['receipt_id']
        with cs.store.connect() as db:
            before = db.execute('SELECT count(*) FROM content_observations').fetchone()[0]
        notes = HumanMessage('Old receipts are invalid; all sources must be read again. This is a false historical hypothesis.')
        packet = await presented(TaskContext(workspace, 'reviewer'), [notes])
        inventory = packet['observation_receipts']
        assert inventory['origin'] == 'current_actor_observation_metadata'
        assert inventory['semantic_acceptance'] is False
        assert any(r['receipt_id'] == own for r in inventory['items'])
        assert other not in json.dumps(inventory) and 'private-other' not in json.dumps(inventory)
        assert packet['review_materials']['semantic_acceptance'] is False
        with cs.store.connect() as db:
            assert db.execute('SELECT count(*) FROM content_observations').fetchone()[0] == before


async def test_receipt_inventory_is_bounded_and_exact_paging_retains_older_records(case):
    cs, _, criteria, _ = prepared(case)
    workspace = configure(cs)
    with delegated_task(workspace, 'coordinator', review_call(criteria)) as (_, actor):
        ids = [cs.observe(actor, {'status': 'observed', 'selection_index': i})['receipt_id'] for i in range(25)]
        packet = await presented(TaskContext(workspace, 'reviewer'), [])
        view = packet['observation_receipts']['items']
        assert view['total'] == 25 and view['complete'] is False and len(view['items']) == 20
        assert view['read_state_path'] == ['observation_receipts', 'items']
        restored = read_state(workspace, 'reviewer', ['observation_receipts', 'items'], offset=20, limit=5)
        assert [r['receipt_id'] for r in restored['value']] == ids[20:]
        assert 'private' not in json.dumps(restored)


async def test_actual_sdk_receipt_facts_survive_summary_and_reopened_store(case):
    import httpx
    from langchain.agents import create_agent
    from langchain_core.messages import AIMessage
    from langchain_core.runnables import RunnableLambda
    from report_agent.deep_models import GLMChatOpenAI, model_async_client
    from report_agent.working_summary import WorkingSummary
    from report_agent.store import Store
    from report_agent.workspace import Workspace
    from test_prompt_native_sdk_inputs import completion
    cs, _, criteria, _ = prepared(case)
    workspace = configure(cs)
    with delegated_task(workspace, 'coordinator', review_call(criteria)) as (_, actor):
        target = cs.read({'type':'DelegatedTask', 'id':actor.task_id, 'version':1})['payload']['review_requirements'][0]['target_ref']
        receipt = cs.read_context(actor, target)['receipt_id']
        summary_inputs = []
        async def summarize(prompt):
            summary_inputs.append(prompt)
            return AIMessage('Historical hypothesis: reread everything. Not current state.')
        notes = await WorkingSummary(model=RunnableLambda(summarize), store=workspace.store,
            role='reviewer', token_counter=lambda messages: len(messages))._acreate_summary([HumanMessage('Old receipts are invalid.')])
        assert receipt in summary_inputs[0]
        reopened = Workspace(Store(workspace.store.root))
        wires = []
        client = model_async_client(reopened.store, 'reviewer')
        def transport(request):
            wires.append(json.loads(request.content))
            return completion(request, 'Fixture only; no acceptance.')
        client._transport = httpx.MockTransport(transport)
        client._mounts.clear()
        model = GLMChatOpenAI(model='glm-5.3',api_key='fixture-only',base_url='https://fixture.invalid/v1',
            use_responses_api=False,http_async_client=client,max_retries=0,disable_streaming=True)
        try:
            graph = create_agent(model, tools=[], middleware=[TaskContext(reopened, 'reviewer')])
            await graph.ainvoke({'messages':[HumanMessage(notes)]})
            wire = json.dumps(wires[0]['messages'], ensure_ascii=False)
            assert receipt in wire and 'current_actor_observation_metadata' in wire
            assert target['id'] in wire and 'semantic_acceptance' in wire
            assert not cs.list_objects('ReviewRecord')
        finally:
            await model.root_async_client.close()
            model.root_client.close()


async def test_receipt_metadata_keeps_failed_and_exact_old_version_without_inventing_success(case):
    cs, _, criteria, _ = prepared(case)
    workspace = configure(cs)
    with delegated_task(workspace, 'coordinator', review_call(criteria)) as (_, actor):
        target = cs.read({'type':'DelegatedTask','id':actor.task_id,'version':1})['payload']['review_requirements'][0]['target_ref']
        receipt = cs.read_context(actor, target)['receipt_id']
        failed = cs.observe(actor, {'status':'failed', 'ok':False,
            'objects':[cs.read(target)]})['receipt_id']
        inventory = exact_task_context(workspace, 'reviewer')['observation_receipts']
        records = {r['receipt_id']:r for r in inventory['items']}
        assert target in records[receipt]['observed_material_refs']
        assert records[failed]['access_status'] == {'status':'failed','ok':False}
        assert records[failed]['observed_material_refs'] == []
        assert 'tool' not in records[receipt] and inventory['semantic_acceptance'] is False
    assert 'observation_receipts' not in exact_task_context(workspace, 'coordinator')
    # Existing focused profile remains unchanged; this is not a policy migration.
    legacy = configure(cs, 'focused-v1')
    with delegated_task(legacy, 'coordinator', review_call(criteria)):
        assert 'observation_receipts' not in exact_task_context(legacy, 'reviewer')


async def test_receipt_index_exposes_artifact_and_visual_identity_without_raw_body(case):
    cs, _, criteria, _ = prepared(case)
    workspace = configure(cs)
    with delegated_task(workspace,'coordinator',review_call(criteria)) as (_,actor):
        export = {'type':'ExportArtifact','id':'exact-export','version':2}
        render = {'type':'RenderArtifact','id':'exact-render','version':1}
        read = cs.observe(actor, {'export_ref':export,'file_digest':'saved-file-sha',
            'paragraphs':['private raw body']})['receipt_id']
        vision = cs.observe(actor, {'status':'observed','source':{'render_ref':render,
            'export_ref':export,'page':3,'crop':None,'coverage':'full_page_image'},
            'observation':'private raw interpretation'})['receipt_id']
        private = cs.observe(actor, {'native_source_material_receipt':'foreign-source-pointer'})['receipt_id']
        workspace.store.set('source_material:foreign-source-pointer', {'actor':{'id':'foreign'},
            'tool':'private-other-tool','materials':[{'source_id':'private-source'}]})
        inventory = exact_task_context(workspace,'reviewer')['observation_receipts']
        rows = {r['receipt_id']:r for r in inventory['items']}
        assert rows[read]['artifact']['export_ref'] == export
        assert rows[read]['artifact']['file_digest'] == 'saved-file-sha'
        assert rows[vision]['source']['render_ref'] == render and rows[vision]['source']['page'] == 3
        assert 'source_material' not in rows[private]
        assert 'private' not in json.dumps(inventory)


async def test_owned_native_source_receipt_projects_exact_locator_not_source_body(case):
    from report_agent.source_materials import issue
    cs,_,criteria,_=prepared(case)
    workspace=configure(cs)
    with delegated_task(workspace,'coordinator',review_call(criteria)) as (_,actor):
        issued=issue(workspace,actor,'read_source_page',json.dumps({'ok':True,'blocks':['raw source must stay off index']}),
            [{'source_id':'s','kind':'frozen_source_selection','selection':{'page':1,'offset':0,'limit':2}}],
            review_observation_id='native-source-owned')
        rows=exact_task_context(workspace,'reviewer')['observation_receipts']['items']
        source=next(r for r in rows if r['receipt_id']=='native-source-owned')['source_material']
        assert source['receipt_id']==issued['receipt'] and source['tool']=='read_source_page'
        assert source['materials'][0]['source_id']=='s'
        assert source['materials'][0]['selection']=={'page':1,'offset':0,'limit':2}
        assert source['materials'][0]['source_version_refs']==issued['source_version_refs']
        assert 'raw source' not in json.dumps(source)
