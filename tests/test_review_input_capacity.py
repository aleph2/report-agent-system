"""Offline admission and exact transport controls; no engineering-quality claim."""
from copy import deepcopy
import json

import httpx
import pytest

from report_agent.bounded_review import perform_review
from report_agent.content_tasks import delegated_task, normalize_review_requirements
from report_agent.errors import ActionRejected
from report_agent.input_capacity import (bind_review_input_capacity, review_capacity,
    service_identity, admit_review_packet, mandatory_capacity_issue)
from report_agent.prepared_material import PreparedMaterial
from report_agent.store import Store, encode
from report_agent.workspace import Workspace
from report_agent.task_supervision import review_readiness
from test_bounded_review import review_call
from test_hierarchical_content import seed
from test_explicit_original_requirement_selection import partial_model
from test_task_supervision import offline


@pytest.fixture
def ws(tmp_path):
    store = Store(tmp_path)
    store.initialize({'report_id': 'capacity-fixture', 'goal': 'Bounded exact review.',
        'content_contract': 'hierarchical-review-v1', 'review_entrypoint': 'delegated-reviewer-v1',
        'review_execution_mode': 'bounded-tool-v1',
        'sources': [{'id': 's', 'title': 'Rule', 'content': 'Class B permits 75 to 100.', 'coverage': 'complete'}]})
    store.set('role_model_services', {'text_tool': {'model': 'offline-review', 'base_url': 'https://fixture.invalid/v1'}})
    return Workspace(store)


def policy(ws, maximum=800000):
    return dict(version=1, report_id='capacity-fixture', case_root=str(ws.store.root.resolve()),
        route='perform_assigned_review', service=service_identity('https://fixture.invalid/v1'),
        model_name='offline-review', max_input_utf8_bytes=maximum, output_tokens=65536,
        declared_context_tokens=1000000, host_headroom_tokens=134464,
        tokenizer_sha256='a' * 64, provider_evidence='Offline fixture declared service window',
        authorization_record='Offline test only; no real model authorized')


def model():
    result = partial_model()
    result.openai_api_base = 'https://fixture.invalid/v1'
    result.max_tokens = 65536
    return result


def test_policy_is_immutable_idempotent_host_bound_and_locked(ws):
    raw = policy(ws)
    ref = bind_review_input_capacity(ws.store, raw)
    assert bind_review_input_capacity(ws.store, raw) == ref
    with pytest.raises(ActionRejected, match='ALREADY_BOUND'):
        bind_review_input_capacity(ws.store, {**raw, 'version': 2})
    with ws.store.run_lock(), pytest.raises(RuntimeError, match='PROJECT_ALREADY_RUNNING'):
        bind_review_input_capacity(ws.store, raw)


@pytest.mark.parametrize('field,value', [('report_id', 'other'), ('case_root', '/other'),
    ('route', 'artifact_review'), ('model_name', 'other'), ('service', {'host': 'other'})])
def test_wrong_case_route_or_service_cannot_change_historical_binding(ws, field, value):
    with pytest.raises(ActionRejected):
        bind_review_input_capacity(ws.store, {**policy(ws), field: value})
    assert review_capacity(ws.store) is None


@pytest.mark.parametrize('variant', ['service', 'output', 'over_bytes'])
def test_legacy_adapter_audits_without_a_second_precall_gate(ws, variant):
    bind_review_input_capacity(ws.store, policy(ws, 100))
    fake = model()
    if variant == 'service':
        fake.openai_api_base = 'https://other.invalid/v1'
    elif variant == 'output':
        fake.max_tokens = 70000
    admit_review_packet(ws.store, review_capacity(ws.store), fake, {'body': '测' * 100}, 'System')
    audit = [e['data'] for e in ws.store.events() if e['kind'] == 'review_input_capacity_audit'][-1]
    assert audit['enforcement'] == 'historical_audit_only'
    assert audit['input_utf8_bytes'] == len('System'.encode()) + len(encode({'body': '测' * 100}).encode())
    assert audit['accepted'] is None and fake.calls == []



async def test_capacity_binding_does_not_invalidate_completed_semantic_cache(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    fake = model()
    with delegated_task(ws, 'coordinator', review_call(snapshot, refs)) as (_, reviewer):
        first = await perform_review(ws, reviewer, fake, 'first', ['rule-comparison'])
    bind_review_input_capacity(ws.store, policy(ws))
    with delegated_task(ws, 'coordinator', review_call(snapshot, refs)) as (_, reviewer):
        second = await perform_review(ws, reviewer, fake, 'same-input-new-id', ['rule-comparison'])
    assert second['reused'] and first['review_ref'] == second['review_ref']
    assert len(fake.calls) == 1


async def test_unknown_attempt_remains_unreplayed_after_capacity_binding(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    fake = model()
    fake.response = httpx.ReadTimeout('Unknown provider outcome')
    with delegated_task(ws, 'coordinator', review_call(snapshot, refs)) as (_, reviewer):
        with pytest.raises(httpx.ReadTimeout):
            await perform_review(ws, reviewer, fake, 'first', ['rule-comparison'])
    bind_review_input_capacity(ws.store, policy(ws))
    with delegated_task(ws, 'coordinator', review_call(snapshot, refs)) as (_, reviewer):
        with pytest.raises(ActionRejected, match='PREVIOUS_ATTEMPT_UNRESOLVED'):
            await perform_review(ws, reviewer, fake, 'second', ['rule-comparison'])
    assert len(fake.calls) == 1 and not cs.list_objects('ReviewRecord')


async def test_material_lower_bound_does_not_make_readiness_capacity_judgment(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    call = review_call(snapshot, refs)
    call['args']['review_requirements'].append({**deepcopy(call['args']['review_requirements'][0]),
        'scope_id': 'larger', 'required_checks': ['Large original source comparison'],
        'required_read_refs': [next(r for r in cs.read(snapshot)['payload']['refs'] if r['type'] == 'SourceArtifact')]})
    bind_review_input_capacity(ws.store, policy(ws, 1))
    ready = review_readiness(cs, snapshot, normalize_review_requirements(call['args']['review_requirements']))
    assert not any(i['kind'] == 'capacity' for i in ready['issues'])
    assert mandatory_capacity_issue(cs, normalize_review_requirements(call['args']['review_requirements'])[0], review_capacity(ws.store)) is None
    fake = model()
    with delegated_task(ws, 'coordinator', call) as (_, reviewer):
        await perform_review(ws, reviewer, fake, 'full-packet-model-double', ['rule-comparison'])
    assert len(fake.calls) == 1  # A model double proves material delivery, not HTTP admission.



async def test_large_material_does_not_block_fresh_or_selected_scope(ws):
    cs, actor, refs, snapshot, members = seed(ws)
    large = cs.commit(actor, 'large-fixture', [{'client_key': 'large', 'type': 'ContentNode',
        'payload': {**cs.read(refs['claim'])['payload'], 'body': {'text': 'x' * 100000}}}])['result']['refs']['large']
    newer = cs.freeze(actor, 'with-large-fixture', refs['root'], [*members, large])['result']['snapshot_ref']
    call = review_call(newer, refs)
    call['args']['review_requirements'].append({**deepcopy(call['args']['review_requirements'][0]),
        'scope_id': 'larger', 'required_checks': ['Whole large node comparison'], 'required_read_refs': [large]})
    bind_review_input_capacity(ws.store, policy(ws, 30000))
    ready = review_readiness(cs, newer, normalize_review_requirements(call['args']['review_requirements']))
    assert not any(i['kind'] in {'capacity', 'oversized_source'} for i in ready['issues'])
    fake = model()
    with delegated_task(ws, 'coordinator', call) as (_, reviewer):
        result = await perform_review(ws, reviewer, fake, 'selected', ['rule-comparison'])
    assert len(fake.calls) == 1 and result['items'][0]['execution_state'] == 'blocked'
    call['id'] = 'fresh-large-assignment'
    with delegated_task(ws, 'coordinator', call):
        pass



async def test_successful_source_free_large_packet_cache_survives_later_smaller_policy(ws):
    cs, actor, refs, snapshot, members = seed(ws)
    changed = cs.commit(actor, 'large-claim', [{'client_key': 'claim', 'type': 'ContentNode',
        'payload': {**cs.read(refs['claim'])['payload'],
        'body': {'text': 'x' * 90000}}}])['result']['refs']['claim']
    members = [*members, changed]
    refs['claim'] = changed
    snapshot = cs.freeze(actor, 'large-claim-snapshot', refs['root'], members)['result']['snapshot_ref']
    call = review_call(snapshot, refs)
    fake = model()
    with delegated_task(ws, 'coordinator', call) as (_, reviewer):
        first = await perform_review(ws, reviewer, fake, 'old-success', ['rule-comparison'])
    bind_review_input_capacity(ws.store, policy(ws, 30000))
    with delegated_task(ws, 'coordinator', call) as (_, reviewer):
        second = await perform_review(ws, reviewer, fake, 'reuse-old', ['rule-comparison'])
    assert second['reused'] and second['review_ref'] == first['review_ref'] and len(fake.calls) == 1


def test_full74_material_has_no_independent_character_limit():
    data = [{'kind': 'source_blocks', 'selection': {'source_id': str(i)},
        'observation': {'blocks': ['测' * 1000]}} for i in range(74)]
    material = PreparedMaterial(encode(data), frozenset())
    assert material.encoded_characters > 64000
    assert material.evidence == data and len(material.evidence) == 74
    assert not hasattr(material, 'require_bounded_size')



async def test_full_packet_audit_includes_schema_and_commission_without_fake_capacity_certificate(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    call = review_call(snapshot, refs)
    bind_review_input_capacity(ws.store, policy(ws, 3000))
    fake = model()
    with delegated_task(ws, 'coordinator', call) as (_, reviewer):
        await perform_review(ws, reviewer, fake, 'full', ['rule-comparison'])
    audit = [e['data'] for e in ws.store.events() if e['kind'] == 'review_input_capacity_audit'][-1]
    packet = json.loads(fake.calls[0][1][1])
    assert packet['commission'] and packet['output_schema']
    assert audit['input_utf8_bytes'] > 3000 and audit['accepted'] is None



@pytest.mark.parametrize('configured', [False, True])
async def test_large_explicit_original_requirement_preserved_with_or_without_legacy_policy(ws, configured):
    store = Store(ws.store.root / 'large-original-case')
    store.initialize({**ws.store.manifest, 'goal': 'x' * 90000})
    store.set('role_model_services', ws.store.get('role_model_services'))
    ws = Workspace(store)
    cs, actor, refs, snapshot, members = seed(ws)
    original = next(r for r in members if r['type'] == 'Requirement')
    if configured:
        bind_review_input_capacity(ws.store, policy(ws))
    fake = model()
    with delegated_task(ws, 'coordinator', review_call(snapshot, refs)) as (_, reviewer):
        await perform_review(ws, reviewer, fake, 'selected', ['rule-comparison'], original_requirement_refs=[original])
    packet = json.loads(fake.calls[0][1][1])
    originals = [e['object'] for e in packet['evidence'] if e.get('object', {}).get('ref') == original]
    assert len(originals) == 1 and originals[0]['payload']['text'] == 'x' * 90000



async def test_caller_cannot_supply_capacity_override(ws):
    from report_agent.bounded_review import review_tool
    tool = review_tool(ws, model())
    import inspect
    assert 'capacity' not in inspect.signature(tool).parameters
    assert 'max_input_utf8_bytes' not in inspect.signature(tool).parameters


def test_low_configured_capacity_does_not_mask_snapshot_target_capability(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    bind_review_input_capacity(ws.store, policy(ws, 1))
    call = review_call(snapshot, refs)
    call['args']['review_requirements'][0]['target_ref'] = snapshot
    readiness = review_readiness(cs, snapshot, normalize_review_requirements(call['args']['review_requirements']))
    assert any(i['kind'] == 'capability' for i in readiness['issues'])
    assert not any(i['kind'] == 'capacity' for i in readiness['issues'])


async def test_review_legacy_policy_does_not_reintroduce_producer_material_limit(ws):
    from report_agent.text_work import produce
    from test_text_work import content
    cs, actor, refs, snapshot, _ = seed(ws)
    large = cs.commit(actor, 'large-producer-input', [{'client_key': 'large', 'type': 'ContentNode',
        'payload': {**cs.read(refs['claim'])['payload'], 'body': {'text': 'x' * 100000}}}])['result']['refs']['large']
    source = next(r for r in cs.read(snapshot)['payload']['refs'] if r['type'] == 'SourceArtifact')
    bind_review_input_capacity(ws.store, policy(ws))
    from test_bounded_review import Model
    fake = Model(json.dumps(content()))
    # The owner/source constraints remain; a ContentNode producer receives full material.
    from test_text_work import writer_call
    with delegated_task(ws, 'coordinator', writer_call()) as (_, writer):
        await produce(ws, writer, fake, 'large-producer', 'Create exact located content',
                      'ContentNode', input_refs=[large, source])
    assert len(fake.calls) == 1 and 'x' * 100000 in fake.calls[0][1][1]



@pytest.mark.parametrize('configured', [False, True])
async def test_large_source_bearing_packet_is_exact_or_default_refused_portably(ws, configured):
    # Portable CI counterpart to the retained real 74-item case, using original
    # user-source and node bodies large enough to exercise the former failure.
    source_text = 'SOURCE_FULL_BODY_SENTINEL ' + 's' * 40000
    store = Store(ws.store.root / 'large-located-source-case')
    store.initialize({**ws.store.manifest,
        'sources': [{'id': 's', 'title': 'Large rule', 'content': source_text, 'coverage': 'complete'}]})
    store.set('role_model_services', ws.store.get('role_model_services'))
    ws = Workspace(store)
    cs, actor, refs, snapshot, members = seed(ws)
    body = 'NODE_FULL_BODY_SENTINEL ' + 'n' * 40000
    large = cs.commit(actor, 'large-target', [{'client_key': 'target', 'type': 'ContentNode',
        'payload': {**cs.read(refs['claim'])['payload'], 'body': {'text': body}}}])['result']['refs']['target']
    snapshot = cs.freeze(actor, 'large-bounded-scope', refs['root'], [*members, large])['result']['snapshot_ref']
    refs['claim'] = large
    source = next(r for r in members if r['type'] == 'SourceArtifact')
    with ws.store.connect() as db:
        block_count = db.execute("SELECT count(*) FROM source_blocks WHERE source_id='s'").fetchone()[0]
    assert 1 <= block_count <= 50
    call = review_call(snapshot, refs)
    call['args']['review_requirements'][0]['required_materials'][0]['source_spans'] = [
        {'source_ref': source, 'offset': 0, 'limit': block_count, 'table_detail': 'references'}]
    if configured:
        bind_review_input_capacity(ws.store, policy(ws))
    fake = model()
    with delegated_task(ws, 'coordinator', call) as (_, reviewer):
        await perform_review(ws, reviewer, fake, 'large-original-comparison', ['rule-comparison'])
        packet = json.loads(fake.calls[0][1][1])
        assert len(encode(packet['evidence'])) > 64000
        assert body in encode(packet)
        source_parts = [e for e in packet['evidence'] if e['kind'] == 'source_blocks']
        assert len(source_parts) == 1
        assert source_parts[0]['selection']['limit'] == block_count
        from report_agent.catalog import Catalog
        assert source_parts[0]['observation']['blocks'] == Catalog(ws.store).read('s', 0, block_count)['blocks']
        assert packet['assignment']['review_requirements'][0]['required_checks'] == ['rule comparison']
