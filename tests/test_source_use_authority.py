"""Exact source-use admission and unchanged write ownership; fake model only."""
import json
from copy import deepcopy

import pytest

from report_agent.bounded_review import perform_review
from report_agent import commission_imports, plan_authority
from report_agent.catalog import Catalog
from report_agent.content_store import ContentStore
from report_agent.content_tasks import delegated_task
from report_agent.errors import ActionForbidden, ActionRejected
from report_agent.evidence_analysis import selected_evidence, analyze_selected_evidence
from report_agent.hierarchical_tools import actor_for
from report_agent.source_use import configure_source_use, report_binding, resolve_source_use_binding, validate_source_versions
from report_agent.store import Store, digest
from report_agent.text_work import prepare_material
from test_bounded_review import Model, review_call
from test_hierarchical_content import seed
from test_task_supervision import ws, offline


def approved_policy(store, ids):
    from report_agent.content_store import Actor
    from test_m5_source_use import approve

    ref = configure_source_use(store, list(ids), 'These exact supplied versions')
    if plan_authority.native_plan_ref(store) is None:
        approve(ContentStore(store), actor_for('coordinator'), Actor('operator', 'operator', 'scope-confirmation'),
                ref, 'source-use', scope=True)
    assert report_binding(store) == ref
    return ref


def grant(ws, ids=('s',)):
    return approved_policy(ws.store, ids)


def historical_policy(store, ids=('s',)):
    # Pre-M5 fixtures retain the original, digest-bound grant and never acquire a new approval.
    from report_agent.source_use import _commission, immutable_version_digest
    versions = []
    for source in store.sources(list(ids)):
        payload = ContentStore.source_payload(source)
        versions.append({'source_id': source['id'], 'source_payload_digest': digest(payload),
                         'immutable_version_digest': immutable_version_digest(payload)})
    record = {'contract': 'source-use-v1', 'commission_binding': _commission(store),
              'declaration': {'source_ids': sorted(ids), 'authorization_origin': 'Archived operator decision'},
              'versions': versions}
    key = digest(record)
    store.set('source_use_authority:' + key, record)
    store.set('source_use_authority_binding', key)
    return key


def test_host_manifest_binding_invalid_declaration_and_reopen(tmp_path):
    store = Store(tmp_path)
    manifest = {'goal': 'Same commission', 'sources': [{'id': 's', 'title': 'Rule', 'content': 'ABC', 'coverage': 'complete'}],
                'source_use': {'source_ids': ['s', 's'], 'authorization_origin': 'User authorizes s'}}
    invalid = deepcopy(manifest)
    invalid['source_use']['source_ids'] = ['absent']
    with pytest.raises(ActionRejected, match='SOURCE_NOT_IN_PROJECT'):
        store.initialize(invalid)
    assert store.get('manifest') is None
    store.initialize(manifest)
    ref = commission_imports.source_policy_ref(store)
    assert ref['type'] == 'CommissionSourceUsePolicy'
    assert store.get('source_use_authority_binding') is None
    with pytest.raises(ActionRejected, match='SOURCE_USE_OWNER_APPROVAL_REQUIRED'):
        report_binding(store)
    store.initialize(manifest)
    assert commission_imports.source_policy_ref(store) == ref


def test_new_tasks_pin_grant_legacy_replay_and_resume_do_not_inherit(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    old_call = review_call(snapshot, refs, id='legacy')
    with delegated_task(ws, 'coordinator', old_call) as (_, old_actor):
        assert resolve_source_use_binding(ws, old_actor) is None
    policy = historical_policy(ws.store)
    with delegated_task(ws, 'coordinator', old_call) as (_, replayed):
        assert replayed == old_actor and resolve_source_use_binding(ws, replayed) is None
    resume = review_call(snapshot, refs, id='resume-old')
    resume['args']['resume_content_task_id'] = old_actor.task_id
    with delegated_task(ws, 'coordinator', resume) as (_, resumed):
        assert resumed == old_actor and resolve_source_use_binding(ws, resumed) is None
    with delegated_task(ws, 'coordinator', review_call(snapshot, refs, id='new')) as (_, new):
        assert resolve_source_use_binding(ws, new) == policy
    assert len(cs.list_objects('DelegatedTask')) == 2


def test_same_declaration_after_replacement_never_reenrolls_new_version(ws):
    policy = grant(ws)
    replacement = Catalog(ws.store).import_file('replacement.txt', b'New unapproved rule', replaces_id='s')
    assert grant(ws) == policy
    assert commission_imports.source_policy_ref(ws.store) == policy
    owner = actor_for('coordinator')
    with pytest.raises(ActionRejected, match='SOURCE_USE_VERSION_NOT_AUTHORIZED'):
        validate_source_versions(ws, owner, [replacement['source']['id']])
    assert validate_source_versions(ws, owner, ['s']) == policy
    actual = selected_evidence(ws, [{'source_id': 's', 'offset': 0, 'limit': 1}], [], actor=owner)
    assert actual[0]['observation']['blocks'][0]['text'] == 'Class B permits 75 to 100.'
    with pytest.raises(ActionRejected, match='SOURCE_USE_AUTHORITY_IMMUTABLE'):
        configure_source_use(ws.store, [replacement['source']['id']], 'different grant')


async def test_explicit_alias_is_only_dependency_and_changed_choice_conflicts(ws):
    grant(ws)
    cs, owner, refs, snapshot, _ = seed(ws)
    first = cs.capture_sources(owner, 'alias-one', ['s'])['result']['source_refs'][0]
    chosen = cs.capture_sources(owner, 'alias-two', ['s'])['result']['source_refs'][0]
    assert first != chosen
    model = Model()
    with delegated_task(ws, 'coordinator', review_call(snapshot, refs)) as (_, reviewer):
        original = cs.list_objects('SourceArtifact')
        args = ([{'source_id': 's', 'offset': 0, 'limit': 1}], [])
        result = await perform_review(ws, reviewer, model, 'exact-alias', ['rule-comparison'], *args, source_version_refs=[chosen])
        packet = json.loads(model.calls[0][-1][1])
        assert packet['selected_source_version_refs'] == [chosen]
        entry = next(e for e in packet['evidence'] if e['kind'] == 'source_blocks')
        assert entry['source_version_refs'] == [chosen] and entry['source_material_receipt']
        saved = cs.read(result['review_ref'])['payload']
        sources = [r for r in saved['dependency_refs'] if r['type'] == 'SourceArtifact']
        assert chosen in sources and first not in sources
        assert cs.list_objects('SourceArtifact') == original
        repeat = await perform_review(ws, reviewer, model, 'exact-alias', ['rule-comparison'], *args, source_version_refs=[chosen])
        assert repeat['reused'] and len(model.calls) == 1
        with pytest.raises(ActionRejected, match='OPERATION_CONFLICT'):
            await perform_review(ws, reviewer, model, 'exact-alias', ['rule-comparison'], *args, source_version_refs=[first])
        assert len(model.calls) == 1


async def test_read_and_capture_do_not_grant_supplemental_use(ws):
    cs, owner, refs, snapshot, _ = seed(ws)
    source = cs.capture_sources(owner, 'capture-only', ['s'])['result']['source_refs'][0]
    model = Model()
    with delegated_task(ws, 'coordinator', review_call(snapshot, refs)) as (_, reviewer):
        with pytest.raises(ActionRejected, match='REVIEW_SUPPLEMENT_REQUIRES_BOUND'):
            await perform_review(ws, reviewer, model, 'no-grant', ['rule-comparison'],
                [{'source_id': 's', 'offset': 0, 'limit': 1}], source_version_refs=[source])
    assert not model.calls and not cs.list_objects('ReviewRecord')


@pytest.mark.parametrize('role', ['coordinator', 'writer', 'reviewer', 'layout'])
async def test_shared_actual_source_consumers_deny_unenrolled_before_model(ws, role):
    grant(ws)
    cs, owner, refs, snapshot, _ = seed(ws)
    extra = Catalog(ws.store).import_file('later.txt', b'Unapproved later version')['source']['id']
    source = cs.capture_sources(owner, 'later-capture', [extra])['result']['source_refs'][0]
    async def check(actor):
        selection = [{'source_id': extra, 'offset': 0, 'limit': 1}]
        model = Model()
        with pytest.raises(ActionRejected, match='SOURCE_USE_VERSION_NOT_AUTHORIZED'):
            await analyze_selected_evidence(ws, model, 'compare', selection, [], actor=actor)
        with pytest.raises(ActionRejected, match='SOURCE_USE_VERSION_NOT_AUTHORIZED'):
            prepare_material(ws, [source], [], actor=actor)
        with pytest.raises(ActionRejected, match='SOURCE_USE_VERSION_NOT_AUTHORIZED'):
            selected_evidence(ws, selection, [], actor=actor)
        assert not model.calls
        allowed = selected_evidence(ws, [{'source_id': 's', 'offset': 0, 'limit': 1}], [], actor=actor)
        assert allowed[0]['observation']['blocks'][0]['text'] == 'Class B permits 75 to 100.'
    if role == 'coordinator':
        await check(owner)
    else:
        call = {'id': 'use-' + role, 'args': {'subagent_type': role, 'description': 'Same task'}}
        if role == 'layout':
            call['args']['layout_snapshot_ref'] = snapshot
        with delegated_task(ws, 'coordinator', call) as (_, actor):
            await check(actor)


def test_source_use_never_grants_writer_foreign_node_or_upstream_write(ws):
    grant(ws)
    cs, _, refs, snapshot, _ = seed(ws)
    original = deepcopy(cs.read(refs['claim']))
    with delegated_task(ws, 'coordinator', {'id': 'writer-own', 'args': {'subagent_type': 'writer', 'description': 'Draft own section'}}) as (_, writer):
        assert resolve_source_use_binding(ws, writer)
        payload = original['payload']
        with pytest.raises(ActionForbidden, match='object owner'):
            cs.commit(writer, 'foreign-edit', [{'client_key': 'x', 'type': 'ContentNode', 'previous_ref': refs['claim'], 'payload': payload}])
        with pytest.raises(ActionForbidden, match='object type'):
            cs.commit(writer, 'upstream-edit', [{'client_key': 'x', 'type': 'Criterion', 'payload': cs.read(refs['k'])['payload']}])
        own = cs.commit(writer, 'own-node', [{'client_key': 'own', 'type': 'ContentNode', 'payload': payload}])['result']['refs']['own']
        revised = cs.commit(writer, 'own-revision', [{'client_key': 'own', 'type': 'ContentNode', 'previous_ref': own,
            'payload': {**payload, 'body': {'text': 'Revised own section'}}}])['result']['refs']['own']
        assert revised['id'] == own['id'] and revised['version'] == own['version'] + 1
    assert cs.read(refs['claim']) == original


async def test_unselected_optional_source_is_not_treated_as_consumed(ws):
    grant(ws)
    cs, owner, refs, snapshot, _ = seed(ws)
    extra = Catalog(ws.store).import_file('optional.txt', b'Unapproved optional source')['source']['id']
    optional = cs.capture_sources(owner, 'optional', [extra])['result']['source_refs'][0]
    call = review_call(snapshot, refs)
    call['args']['review_requirements'][0]['material_refs'] = [optional]
    model = Model()
    with delegated_task(ws, 'coordinator', call) as (_, reviewer):
        result = await perform_review(ws, reviewer, model, 'no-optional-used', ['rule-comparison'])
    assert result['review_ref']['type'] == 'ReviewRecord' and len(model.calls) == 1
    assert extra not in json.dumps(json.loads(model.calls[0][-1][1])['evidence'])


def test_bound_legacy_source_observation_unknown_origin_cannot_bypass(ws):
    import hashlib
    # Actual pre-grant original-source return, owned by Coordinator.
    owner = actor_for('coordinator')
    page = selected_evidence(ws, [{'source_id': 's', 'offset': 0, 'limit': 1}], [], actor=owner)[0]['observation']
    text = json.dumps(page, ensure_ascii=False)
    sha = hashlib.sha256(text.encode()).hexdigest()
    ref = digest({'owner': owner.id, 'tool': 'read_source_page', 'sha256': sha})
    ws.store.set('tool_observation:' + ref, {'owner': owner.id, 'tool': 'read_source_page', 'text': text, 'sha256': sha})
    extra = Catalog(ws.store).import_file('only-authorized.txt', b'Only this new original is authorized')['source']['id']
    grant(ws, [extra])
    with pytest.raises(ActionRejected, match='TEXT_WORK_SOURCE_OBSERVATION_ORIGIN_REQUIRED'):
        prepare_material(ws, [], [], [ref], actor=owner)


@pytest.mark.parametrize('role', ['coordinator', 'writer', 'layout'])
@pytest.mark.parametrize('tool', ['analyze_text', 'analyze_evidence'])
async def test_native_analysis_issues_owned_version_receipt_and_foreign_task_cannot_borrow(ws, role, tool):
    from langchain_core.messages import AIMessage
    from test_agent_result_delivery import run_role, expected_owner
    from test_decision_data import activate
    from test_deep_runtime import invoke
    from report_agent.source_materials import owned_materials
    grant(ws)
    cs, _, refs, snapshot, _ = seed(ws)
    activate(ws)
    args = ({'source_id': 's', 'purpose': 'Observe selected synthetic rule', 'offset': 0, 'limit': 1}
            if tool == 'analyze_text' else {'question': 'Observe selected synthetic rule',
                'source_selections': [{'source_id': 's', 'offset': 0, 'limit': 1}], 'result_selections': []})
    model = Model()
    await run_role(ws, role, [invoke(tool, **args), AIMessage(content='Observed, no engineering claim.')], refs, snapshot, model)
    with ws.store.connect() as db:
        values = [json.loads(row[0]) for row in db.execute("SELECT value FROM state WHERE key LIKE 'source_material:%'")]
    records = [r for r in values if r['tool'] == tool and r['actor']['id'] == expected_owner(ws, role)]
    assert len(records) == 1 and len(model.calls) == 1
    record = records[0]
    assert record['materials'][0]['kind'] == 'model_text_interpretation'
    assert record['materials'][0]['source_payload_digest'] == digest(cs.source_payload(ws.store.sources(['s'])[0]))
    original = ws.store.get('tool_observation:' + record['body_ref'])
    from report_agent.content_store import Actor
    actor = Actor(**record['actor'])
    parts = owned_materials(ws, actor, record['body_ref'], original['text'], tool)
    assert parts == record['materials']
    with pytest.raises(ActionForbidden, match='another task'):
        owned_materials(ws, Actor('foreign', 'writer', 'foreign'), record['body_ref'], original['text'], tool)


def test_verified_pregrant_source_material_cannot_be_consumed_under_different_grant(ws):
    from report_agent.source_materials import issue, block_material
    owner = actor_for('coordinator')
    page = selected_evidence(ws, [{'source_id': 's', 'offset': 0, 'limit': 1}], [], actor=owner)[0]['observation']
    text = json.dumps(page, ensure_ascii=False)
    issued = issue(ws, owner, 'read_source_page', text, block_material(page))
    extra = Catalog(ws.store).import_file('different.txt', b'Only this version is authorized')['source']['id']
    grant(ws, [extra])
    with pytest.raises(ActionRejected, match='SOURCE_USE_VERSION_NOT_AUTHORIZED'):
        prepare_material(ws, [], [], [issued['body_ref']], actor=owner)


@pytest.mark.parametrize('role', ['coordinator', 'writer', 'reviewer', 'layout'])
@pytest.mark.parametrize('authorized', [True, False], ids=['enrolled', 'not-enrolled'])
async def test_native_image_consumer_checks_before_image_client_and_cache(ws, monkeypatch, role, authorized):
    from langchain_core.messages import AIMessage
    from test_agent_result_delivery import run_role
    from test_decision_data import activate
    from test_deep_runtime import invoke
    from test_ingestion import pdf_bytes
    from test_vision import VisionModel
    from report_agent import document_tools, vision
    image_id = Catalog(ws.store).import_file('original.pdf', pdf_bytes(('Synthetic page',)))['source']['id']
    policy = grant(ws, ['s', image_id] if authorized else ['s'])
    cs, _, refs, snapshot, _ = seed(ws)
    activate(ws)
    model, resolutions, clients = VisionModel(), [], []
    real = document_tools.vision_source_image
    def resolve(*args, **kwargs):
        resolutions.append(args[1])
        return real(*args, **kwargs)
    def client():
        clients.append('created')
        return model
    monkeypatch.setattr(document_tools, 'vision_source_image', resolve)
    monkeypatch.setattr(vision, 'configured_vision_client', client)
    await run_role(ws, role, [invoke('analyze_source_image', source_id=image_id, question='Observe exact page'),
        AIMessage(content='Observation ended, no engineering acceptance.')], refs, snapshot, Model())
    assert len(model.calls) == len(resolutions) == len(clients) == int(authorized)
    requests = [e for e in ws.store.events() if e['kind'] == 'vision_request']
    assert len(requests) == int(authorized)
    if authorized:
        assert requests[0]['data']['source_use_policy_ref'] == policy
    else:
        assert not ws.store.get('vision_request')


async def test_unknown_supplemental_model_outcome_cannot_be_replayed(ws):
    import httpx
    grant(ws)
    cs, owner, refs, snapshot, _ = seed(ws)
    chosen = cs.capture_sources(owner, 'known-version', ['s'])['result']['source_refs'][0]
    model = Model(httpx.ReadTimeout('Unknown fake outcome'))
    with delegated_task(ws, 'coordinator', review_call(snapshot, refs)) as (_, reviewer):
        with pytest.raises(httpx.ReadTimeout):
            await perform_review(ws, reviewer, model, 'first-attempt', ['rule-comparison'],
                [{'source_id': 's', 'offset': 0, 'limit': 1}], source_version_refs=[chosen])
        with pytest.raises(ActionRejected, match='PREVIOUS_ATTEMPT_UNRESOLVED'):
            await perform_review(ws, reviewer, model, 'different-id', ['rule-comparison'],
                [{'source_id': 's', 'offset': 0, 'limit': 1}], source_version_refs=[chosen])
    assert len(model.calls) == 1 and not cs.list_objects('ReviewRecord')


@pytest.mark.parametrize('changed', ['content', 'file_digest', 'coverage', 'other_metadata'])
def test_full_version_checks_all_fields_except_dynamic_current(ws, changed):
    grant(ws)
    cs, owner, _, _, _ = seed(ws)
    payload = deepcopy(cs.source_payload(ws.store.sources(['s'])[0]))
    if changed == 'other_metadata':
        payload['source_metadata']['title'] = 'Changed title'
    else:
        payload[changed] = 'Changed immutable value'
    with ws.store.connect() as db:
        forged = cs._insert(db, owner, 'SourceArtifact', payload)
    with pytest.raises(ActionRejected, match='SOURCE_USE_VERSION_NOT_AUTHORIZED'):
        validate_source_versions(ws, owner, source_refs=[forged])


async def test_generic_authorized_history_does_not_relax_reviewer_currentness(ws):
    grant(ws)
    cs, owner, refs, snapshot, _ = seed(ws)
    original = next(r for r in cs.read(snapshot)['payload']['refs'] if r['type'] == 'SourceArtifact')
    Catalog(ws.store).import_file('replacement.txt', b'New rule', replaces_id='s')
    assert validate_source_versions(ws, owner, source_refs=[original])
    model = Model()
    with delegated_task(ws, 'coordinator', review_call(snapshot, refs, reads=[original])) as (_, reviewer):
        with pytest.raises(ActionRejected, match='REVIEW_SOURCE_VERSION_CHANGED'):
            await perform_review(ws, reviewer, model, 'stale-original', ['rule-comparison'])
    assert not model.calls


async def test_mandatory_source_cannot_be_waived_by_authorized_supplement(ws):
    extra = Catalog(ws.store).import_file('supplement.txt', b'Authorized supplement')['source']['id']
    grant(ws, [extra])
    cs, owner, refs, snapshot, _ = seed(ws)
    original = next(r for r in cs.read(snapshot)['payload']['refs'] if r['type'] == 'SourceArtifact')
    supplement = cs.capture_sources(owner, 'supplement', [extra])['result']['source_refs'][0]
    model = Model()
    call = review_call(snapshot, refs, reads=[original])
    with delegated_task(ws, 'coordinator', call) as (_, reviewer):
        with pytest.raises(ActionRejected, match='SOURCE_USE_VERSION_NOT_AUTHORIZED'):
            await perform_review(ws, reviewer, model, 'mandatory', ['rule-comparison'],
                [{'source_id': extra, 'offset': 0, 'limit': 1}], source_version_refs=[supplement])
    assert not model.calls and not cs.list_objects('ReviewRecord')


async def test_native_source_free_analysis_empty_receipt_is_not_a_source_grant(ws):
    from langchain_core.messages import AIMessage
    from test_agent_result_delivery import run_role
    from test_decision_data import activate
    from test_deep_runtime import invoke
    grant(ws)
    cs, owner, refs, snapshot, _ = seed(ws)
    activate(ws)
    await run_role(ws, 'coordinator', [invoke('analyze_evidence', question='Inspect this saved node only',
        source_selections=[], result_selections=[], snapshot_ref=snapshot,
        content_selections=[{'ref': refs['claim'], 'unit': 'text', 'offset': 0, 'limit': 30}]),
        AIMessage(content='Observed node, no source completeness claim.')], refs, snapshot, Model())
    with ws.store.connect() as db:
        records = [json.loads(r[0]) for r in db.execute("SELECT value FROM state WHERE key LIKE 'source_material:%'")]
    record, = [r for r in records if r['tool'] == 'analyze_evidence']
    assert record['materials'] == []
    prepared = prepare_material(ws, [], [], [record['body_ref']], actor=owner)
    assert prepared.evidence[0]['tool'] == 'analyze_evidence'
    extra = Catalog(ws.store).import_file('later.txt', b'Not authorized')['source']['id']
    with pytest.raises(ActionRejected, match='SOURCE_USE_VERSION_NOT_AUTHORIZED'):
        prepare_material(ws, [], [{'source_id': extra, 'offset': 0, 'limit': 1}], [record['body_ref']], actor=owner)


@pytest.mark.parametrize('authorized', [True, False])
async def test_paired_render_original_reference_use_gate(ws, monkeypatch, authorized):
    import hashlib
    from io import BytesIO
    from PIL import Image
    from report_agent.content_export import inspect_render
    from test_ingestion import pdf_bytes
    from test_vision import VisionModel
    from report_agent import document_tools
    source_id = Catalog(ws.store).import_file('reference.pdf', pdf_bytes(('Reference page',)))['source']['id']
    policy = grant(ws, ['s', source_id] if authorized else ['s'])
    cs, owner, refs, snapshot, _ = seed(ws)
    buffer = BytesIO()
    with Image.new('RGB', (100, 100), 'white') as image:
        image.save(buffer, format='PNG')
    data = buffer.getvalue()
    (ws.store.root / 'content-assets').mkdir(exist_ok=True)
    asset = ws.store.root / 'content-assets/page.png'
    asset.write_bytes(data)
    with ws.store.connect() as db:
        export = cs._insert(db, owner, 'ExportArtifact', {'snapshot_ref': snapshot, 'file_ref': 'synthetic.docx'})
        render = cs._insert(db, owner, 'RenderArtifact', {'snapshot_ref': snapshot, 'export_ref': export,
            'page_assets': [{'asset_ref': 'content-assets/page.png', 'sha256': hashlib.sha256(data).hexdigest()}]})
    model, resolutions = VisionModel(), []
    real = document_tools.vision_source_image
    def resolve(*args, **kwargs):
        resolutions.append(args[1])
        return real(*args, **kwargs)
    monkeypatch.setattr(document_tools, 'vision_source_image', resolve)
    if authorized:
        result = await inspect_render(cs, owner, render, 1, 'Compare', client=model, reference_source_id=source_id)
        assert result['result']['source_use_policy_ref'] == policy
    else:
        with pytest.raises(ActionRejected, match='SOURCE_USE_VERSION_NOT_AUTHORIZED'):
            await inspect_render(cs, owner, render, 1, 'Compare', client=model, reference_source_id=source_id)
    assert len(model.calls) == len(resolutions) == int(authorized)


async def test_artifact_checker_rejects_unenrolled_structured_reference_receipt(ws):
    from test_artifact_review import setup, visual
    from report_agent.artifact_review import bounded_artifact_review_tool
    extra = Catalog(ws.store).import_file('only-granted.txt', b'Only authorized source')['source']['id']
    grant(ws, [extra])
    cs, refs, snapshot, export, render, source, call = setup(ws, pages=1)
    model = Model()
    with delegated_task(ws, 'coordinator', call) as (_, reviewer):
        receipt = visual(cs, reviewer, render, export, source, 1)
        with pytest.raises(ActionRejected, match='SOURCE_USE_VERSION_NOT_AUTHORIZED'):
            await bounded_artifact_review_tool(ws, model)('not-granted', ['rule-comparison'], [receipt])
    assert not model.calls


@pytest.mark.parametrize('authorized,historical', [(True, False), (False, False), (False, True)])
async def test_artifact_checker_checks_actual_character_source_receipt_before_reservation(ws, authorized, historical):
    from report_agent.hierarchical_tools import content_tools
    from report_agent.artifact_review import bounded_artifact_review_tool
    from test_artifact_review import setup, payload, visual
    extra = Catalog(ws.store).import_file('other.txt', b'Other source')['source']['id']
    if historical:
        historical_policy(ws.store, [extra])
    else:
        grant(ws, ['s'] if authorized else [extra])
    cs, refs, snapshot, export, render, source, call = setup(ws, pages=1)
    with delegated_task(ws, 'coordinator', call) as (_, reviewer):
        tool = next(t for t in content_tools(ws, 'reviewer') if t.__name__ == 'observe_evidence')
        if not authorized and not historical:
            with pytest.raises(ActionRejected, match='SOURCE_USE_VERSION_NOT_AUTHORIZED'):
                tool(kind='source', source_id='s', offset=0, limit=20)
            assert ws.store.get('artifact_text_work:' + reviewer.id + ':actual-character-receipt') is None
            return
        selected = tool(kind='source', source_id='s', offset=0, limit=20)
        real_image = visual(cs, reviewer, render, export, source, 1)
        expected = payload(snapshot, refs, render, [real_image])
        model = Model(expected.model_dump_json())
        operation = 'actual-character-receipt'
        if authorized:
            saved = await bounded_artifact_review_tool(ws, model)(operation, ['rule-comparison'],
                [selected['receipt_id'], real_image])
            assert saved['result']['review_ref']['type'] == 'ReviewRecord' and len(model.calls) == 1
        else:
            with pytest.raises(ActionRejected, match='SOURCE_USE_VERSION_NOT_AUTHORIZED'):
                await bounded_artifact_review_tool(ws, model)(operation, ['rule-comparison'], [selected['receipt_id']])
            assert not model.calls
            assert ws.store.get('artifact_text_work:' + reviewer.id + ':' + operation) is None


async def test_native_writer_calculation_observation_reaches_producer_without_false_source_requirement(ws):
    from langchain_core.messages import AIMessage
    from test_agent_result_delivery import run_role, expected_owner
    from test_decision_data import activate
    from test_deep_runtime import invoke
    from test_text_work import content
    grant(ws)
    cs, _, refs, snapshot, _ = seed(ws)
    activate(ws)
    held = {}
    def use_actual_calculation(messages):
        owner = expected_owner(ws, 'writer')
        with ws.store.connect() as db:
            observations = [(key.split(':', 1)[1], json.loads(raw)) for key, raw in db.execute(
                "SELECT key,value FROM state WHERE key LIKE 'tool_observation:%'")]
        ref, record = next((ref, r) for ref, r in observations
            if r['tool'] == 'observe_evidence' and r['owner'] == owner)
        actual = json.loads(record['text'])
        assert actual['result']['tool'] == 'sum_products' and actual['result']['result']['total'] == '6'
        held['ref'] = ref
        return invoke('process_report_content', operation_id='calculation-draft',
            objective='Describe this actual calculation with its limits', object_type='ContentNode',
            input_refs=[], source_selections=[], observation_refs=[ref])
    model = Model(json.dumps(content()))
    await run_role(ws, 'writer', [invoke('observe_evidence', kind='calculation', terms=[['2', '3']]),
        use_actual_calculation, AIMessage(content='Draft receipt generated, not acceptance.')], refs, snapshot, model)
    assert len(model.calls) == 1
    packet = json.loads(model.calls[0][-1][1])
    assert any(e.get('observation_ref') == held['ref'] for e in packet['evidence'])
