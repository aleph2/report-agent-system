"""Whole-review material delivery is exact data, never a completed review."""
import json
from copy import deepcopy

import pytest

from report_agent.content_tasks import delegated_task
from report_agent.errors import ActionRejected
from report_agent.task_context import TaskContext
from report_agent.workspace import Workspace
from test_deliverable_declaration_v4 import case
from test_review_binding_v4 import prepared, review_call
from test_progress_retention import presented


def configure(cs, profile='review-materials-v1'):
    cs.store.set('manifest', {**cs.store.manifest,
        'context_policy': 'stateful-tools-v2', 'context_projection': profile})
    return Workspace(cs.store)


async def test_full_bound_materials_survive_repeated_calls_without_inventing_review(case):
    cs, declared, criteria, originals = prepared(case)
    workspace = configure(cs)
    with delegated_task(workspace, 'coordinator', review_call(criteria)) as (_, actor):
        before = deepcopy(cs.list_objects())  # Delegation legitimately creates its Snapshot.
        middleware = TaskContext(workspace, 'reviewer')
        with cs.store.connect() as db:
            observations = db.execute('SELECT count(*) FROM content_observations').fetchone()[0]
        first = await presented(middleware, [])
        again = await presented(middleware, [])  # History can be compacted away entirely.
        packet = first['review_materials']
        assert packet == again['review_materials']
        assert packet['semantic_acceptance'] is False
        assert packet['objects_complete'] is True
        records = {json.dumps(r['ref'], sort_keys=True): r for r in packet['objects']}
        assert len(records) == len(packet['objects'])
        task = cs.read({'type': 'DelegatedTask', 'id': actor.task_id, 'version': 1})['payload']
        snap = cs.read(task['review_snapshot_ref'])
        for ref in snap['payload']['refs'] + criteria + originals:
            assert records[json.dumps(ref, sort_keys=True)] == cs.read(ref)
        assert len(packet['requirements']) == 7
        assert packet['basis']['criterion_refs'] == task['review_commission_basis']['criterion_refs']
        assert 'digest' not in packet['basis']  # The normalized view is not the original hash body.
        assert packet['basis']['saved_basis_digest'] == task['review_commission_basis']['digest']
        assert 'criteria' not in packet['basis']  # One entity payload, scope links retained.
        assert any(r['ref']['type'] == 'SourceArtifact' and r['payload']['content']
                   for r in packet['objects'])
        assert any(r['ref']['type'] == 'Relation' and r['payload']['predicate'] == 'supported_by'
                   for r in packet['objects'])
        assert not first.get('assignment', {}).get('review_commission_basis', {}).get('criteria')
        assert 'materials_path' not in first['assignment']  # This is not a read_decision_state path.
        from report_agent.task_context import exact_task_context
        exact = exact_task_context(workspace, 'reviewer')
        assert first['assigned_targets'] == exact['assigned_targets']
        assert 'assigned_structure' in first
        for key, value in task.items():
            if key not in {'review_requirements', 'review_commission_basis'}:
                assert first['assignment'][key] == value
        with cs.store.connect() as db:
            assert db.execute('SELECT count(*) FROM content_observations').fetchone()[0] == observations
        assert cs.list_objects('ReviewRecord') == []
    # Material presentation adds no business objects after the genuine delegation.
    assert [r for r in cs.list_objects() if r['ref']['type'] != 'DelegatedTask'] == [
        r for r in before if r['ref']['type'] != 'DelegatedTask']
    assert 'review_materials' not in await presented(TaskContext(workspace, 'coordinator'), [])


async def test_old_projection_and_other_roles_do_not_receive_review_materials(case):
    cs, _, criteria, _ = prepared(case)
    workspace = configure(cs, 'focused-v1')
    with delegated_task(workspace, 'coordinator', review_call(criteria)):
        old = TaskContext(workspace, 'reviewer')
        assert 'review_materials' not in await presented(old, [])
    # Separate fresh store binding is covered by the profile immutability test below.
    assert 'review_materials' not in await presented(TaskContext(workspace, 'coordinator'), [])


def test_new_material_profile_cannot_be_enabled_on_executed_case(case):
    cs = case[0]
    workspace = configure(cs)
    cs.store.event('deep_model_request', {'role': 'coordinator'})
    with pytest.raises(ActionRejected, match='FRESH'):
        TaskContext(workspace, 'coordinator')


def test_material_profile_binding_is_immutable(case):
    cs = case[0]
    workspace = configure(cs)
    middleware = TaskContext(workspace, 'coordinator')
    assert cs.store.get('context_projection_binding') == 'review-materials-v1'
    cs.store.set('manifest', {**cs.store.manifest, 'context_projection': 'focused-v1'})
    with pytest.raises(ActionRejected, match='BINDING_CHANGED'):
        TaskContext(workspace, 'coordinator')
    assert middleware.review_materials is True


@pytest.mark.parametrize('profile', ['review-interfaces-v2', 'review-interfaces-v3', None])
def test_material_projection_requires_v4_before_model_construction(case, profile):
    from report_agent.deep_runtime import build_agent
    cs = case[0]
    workspace = configure(cs)
    cs.store.set('manifest', {**cs.store.manifest, 'review_interface_profile': profile})
    def forbidden(role):
        pytest.fail('Incompatible material projection reached a model factory')
    with pytest.raises(ActionRejected):
        build_agent(workspace, forbidden, None)


async def test_materials_on_final_sdk_after_history_cleanup_and_store_reopen(case, monkeypatch):
    import httpx
    from types import SimpleNamespace
    from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage
    from report_agent.deep_models import GLMChatOpenAI, model_async_client
    from report_agent.store import Store
    from test_prompt_native_sdk_inputs import completion
    import test_deliverable_recovery_v4 as fixture

    old_work = fixture.work
    text = 'Start: compare A to B.\n' + '中文完整限定🙂\n' * 1600 + 'End: unresolved condition.'
    def long_work(source):
        objects = old_work(source)
        objects[1]['payload']['body']['text'] = text
        objects[1]['payload']['qualifiers'] = {'limitations': 'Missing proof remains missing.'}
        return objects
    monkeypatch.setattr(fixture, 'work', long_work)
    cs, _, criteria, _ = prepared(case)
    workspace = configure(cs)
    wires = []
    with delegated_task(workspace, 'coordinator', review_call(criteria)):
        middleware = TaskContext(workspace, 'reviewer')
        client = model_async_client(cs.store, 'reviewer')
        async def transport(request):
            wires.append(json.loads(request.content))
            return completion(request, 'Fixture material supplied; no review claim.')
        client._transport = httpx.MockTransport(transport)
        client._mounts.clear()
        model = GLMChatOpenAI(model='glm-5.3', api_key='offline-only',
            base_url='https://fixture.invalid/v1', use_responses_api=False,
            http_async_client=client, max_retries=0, disable_streaming=True)
        try:
            for current in [middleware, TaskContext(Workspace(Store(cs.store.root)), 'reviewer')]:
                request = SimpleNamespace(messages=[HumanMessage('Historical notes may be summarized.'),
                    ToolMessage('Old body', name='read_file', tool_call_id='old')],
                    system_message=SystemMessage('Role authority.'))
                request.override = lambda **kw: SimpleNamespace(**{**request.__dict__, **kw})
                async def late_cleanup(projected):
                    # Later history offloading cannot alter the freshly rebuilt task materials.
                    return await model.ainvoke([projected.system_message,
                        HumanMessage('History compacted; preserve the real task.')])
                await current.awrap_model_call(request, late_cleanup)
        finally:
            await model.root_async_client.close()
            model.root_client.close()
        assert len(wires) == 2
        for wire in wires:
            system = next(m['content'] for m in wire['messages'] if m['role'] == 'system')
            blocks = system if isinstance(system, list) else [system]
            frame = next(json.loads(b['text'].split('\n', 1)[1]) for b in blocks
                         if isinstance(b, dict) and b.get('text', '').startswith('Current task bindings'))
            records = frame['review_materials']['objects']
            body = next(r for r in records if r['ref']['type'] == 'ContentNode'
                        and r['payload']['body'].get('text') == text)
            assert body['payload']['qualifiers']['limitations'] == 'Missing proof remains missing.'
            assert len(frame['review_materials']['requirements']) == 7
        assert cs.list_objects('ReviewRecord') == []


async def test_binding_keeps_original_versions_when_writer_revises_current_head(case):
    cs, declared, criteria, _ = prepared(case)
    workspace = configure(cs)
    with delegated_task(workspace, 'coordinator', review_call(criteria)):
        middleware = TaskContext(workspace, 'reviewer')
        before = (await presented(middleware, []))['review_materials']
        old = declared['refs']['a-body']
        cs.commit(case[2], 'later-body', [{'client_key': 'revision', 'type': 'ContentNode',
            'previous_ref': old, 'payload': {**cs.read(old)['payload'],
                'body': {'text': 'Later unselected writer revision.'}}}])
        after = (await presented(middleware, []))['review_materials']
        assert before == after
        assert 'Later unselected writer revision.' not in json.dumps(after)


def test_missing_bound_object_cannot_be_reported_complete(case, monkeypatch):
    from report_agent.content_store import ContentStore
    from report_agent.task_context import complete_review_materials
    cs, _, criteria, _ = prepared(case)
    workspace = configure(cs)
    with delegated_task(workspace, 'coordinator', review_call(criteria)) as (_, actor):
        task = cs.read({'type': 'DelegatedTask', 'id': actor.task_id, 'version': 1})['payload']
        original = ContentStore._read
        def unavailable(db, ref):
            if ref['type'] == 'SourceArtifact':
                raise ActionRejected('NOT_FOUND: missing original version')
            return original(db, ref)
        monkeypatch.setattr(ContentStore, '_read', staticmethod(unavailable))
        with pytest.raises(ActionRejected, match='NOT_FOUND'):
            complete_review_materials(workspace, task)


def test_actual03_full_payload_and_scope_links_without_task_json_paging(tmp_path):
    from pathlib import Path
    from report_agent.store import Store, encode
    from report_agent.content_store import ContentStore
    from report_agent.task_context import complete_review_materials
    fixture = json.loads((Path(__file__).parent / 'fixtures' / 'reviewer_materials_actual03.json').read_text())
    store = Store(tmp_path)
    sources = {o['payload']['source_id']: {'id': o['payload']['source_id'],
        'content': o['payload']['content'], 'coverage': o['payload']['coverage']}
        for o in fixture['objects'] if o['ref']['type'] == 'SourceArtifact'}
    store.initialize({'goal': 'Offline actual03 object fixture', 'sources': list(sources.values())})
    cs = ContentStore(store)
    with store.connect() as db:
        for record in fixture['objects']:
            ref = record['ref']
            db.execute('INSERT INTO content_versions VALUES (?,?,?,?)',
                (ref['type'], ref['id'], ref['version'], encode(record)))
    packet = complete_review_materials(Workspace(store), fixture['task'])
    objects = packet['objects']
    assert len(packet['requirements']) == 7
    assert len([o for o in objects if o['ref']['type'] == 'Criterion']) == 7
    assert len([o for o in objects if o['ref']['type'] == 'ContentNode']) == 9
    assert len([o for o in objects if o['ref']['type'] == 'SourceArtifact']) == 3
    assert len([o for o in objects if o['ref']['type'] == 'Relation']) == 19
    assert packet['requirements'] == fixture['task']['review_requirements']
    original = {encode(o['ref']): o for o in fixture['objects']}
    assert all(o == original[encode(o['ref'])] for o in objects)
    assert cs.list_objects('ReviewRecord') == []
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM content_observations').fetchone()[0] == 0


async def test_native_summary_and_checkpoint_reopen_restore_full_materials(case, tmp_path):
    import httpx
    from deepagents import create_deep_agent
    from langchain_core.messages import AIMessage, HumanMessage
    from langchain_core.runnables import RunnableLambda
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from report_agent.deep_models import GLMChatOpenAI, model_async_client
    from report_agent.store import Store
    from report_agent.working_summary import WorkingSummary
    from test_prompt_native_sdk_inputs import completion
    cs, _, criteria, _ = prepared(case)
    workspace = configure(cs)
    wires, summaries = [], []
    async def summarize(prompt):
        summaries.append(str(prompt))
        return AIMessage('Fixture history summary. Review remains unperformed.')
    client = model_async_client(cs.store, 'reviewer')
    async def transport(request):
        wires.append(json.loads(request.content))
        return completion(request, 'Material observed; independent verification still pending.')
    client._transport = httpx.MockTransport(transport)
    client._mounts.clear()
    model = GLMChatOpenAI(model='glm-5.3', api_key='offline-only',
        base_url='https://fixture.invalid/v1', use_responses_api=False,
        http_async_client=client, max_retries=0, disable_streaming=True)
    config = {'configurable': {'thread_id': 'material-summary-reopen'}}
    path = str(tmp_path / 'isolated-review-checkpoint.db')
    try:
        with delegated_task(workspace, 'coordinator', review_call(criteria)):
            for index, current in enumerate([workspace, Workspace(Store(cs.store.root))]):
                async with AsyncSqliteSaver.from_conn_string(path) as checkpointer:
                    summary = WorkingSummary(model=RunnableLambda(summarize), store=current.store,
                        role='reviewer', trigger=('messages', 5), keep=('messages', 1),
                        token_counter=lambda messages: len(messages), trim_tokens_to_summarize=None)
                    agent = create_deep_agent(model=model,
                        middleware=[TaskContext(current, 'reviewer'), summary], checkpointer=checkpointer)
                    history = [HumanMessage('Prior question '+str(i)) if i % 2 == 0
                               else AIMessage('Prior working note '+str(i)) for i in range(8)]
                    if index:
                        restored = await agent.aget_state(config)
                        assert restored.values['messages']
                    await agent.ainvoke({'messages': history if not index else [HumanMessage('Continue exact task.')]}, config)
            assert summaries and len(wires) == 2
            for wire in wires:
                system = next(m['content'] for m in wire['messages'] if m['role'] == 'system')
                blocks = system if isinstance(system, list) else [system]
                frame = next(json.loads(b['text'].split('\n', 1)[1]) for b in blocks
                    if isinstance(b, dict) and b.get('text', '').startswith('Current task bindings'))
                records = {json.dumps(o['ref'], sort_keys=True): o for o in frame['review_materials']['objects']}
                assert frame['review_materials']['contract'] == 'review-materials-v1'
                for criterion in criteria:
                    assert records[json.dumps(criterion, sort_keys=True)] == cs.read(criterion)
            assert cs.list_objects('ReviewRecord') == []
    finally:
        await model.root_async_client.close()
        model.root_client.close()


def test_wrong_evidence_uuid_fails_without_aliasing_then_explicit_correction_reads(case):
    from report_agent.store import encode
    cs, output, criteria, _ = prepared(case)
    workspace = configure(cs)
    with delegated_task(workspace, 'coordinator', review_call(criteria)) as (_, actor):
        evidence = output['refs']['e']
        wrong = {**evidence, 'id': '4513c388-3acf-4a75-8f3a-9dd11870f47a'}
        with cs.store.connect() as db:
            before = db.execute('SELECT count(*) FROM content_observations').fetchone()[0]
        with pytest.raises(ActionRejected, match='NOT_FOUND'):
            cs.read_context(actor, wrong)
        with cs.store.connect() as db:
            assert db.execute('SELECT count(*) FROM content_observations').fetchone()[0] == before
        corrected = cs.read_context(actor, evidence)
        assert corrected['receipt_id']
        assert encode(evidence) in encode(corrected)
        assert cs.list_objects('ReviewRecord') == []
