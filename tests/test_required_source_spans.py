"""Offline contract checks. Scripted judgments do not prove semantic acceptance."""
import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from report_agent.bounded_review import perform_review
from report_agent.content_models import ReviewSubmission
from report_agent.content_tasks import delegated_task, normalize_review_requirements
from report_agent.errors import ActionRejected
from report_agent.prepared_material import PreparedMaterial
from report_agent.store import encode
from report_agent.task_supervision import (RequiredSourceSpan, missing_required_materials,
    source_extents_in_observation, reconcile, material_refs_in_observation)
from test_task_supervision import ws, offline
from test_hierarchical_content import seed
from test_bounded_review import Model, review_call


def setup(ws, *, limit=1, detail='references', count=26000):
    manifest = deepcopy(ws.store.manifest)
    manifest['sources'][0]['content'] = 'Class B permits 75 to 100.\n' + 'original text ' * count
    ws.store.set('manifest', manifest)
    cs, _, refs, snapshot, _ = seed(ws)
    source = next(r for r in cs.read(snapshot)['payload']['refs'] if r['type'] == 'SourceArtifact')
    call = review_call(snapshot, refs)
    span = {'source_ref':source, 'offset':0, 'limit':limit}
    if detail is not None: span['table_detail'] = detail
    call['args']['review_requirements'][0]['required_materials'][0]['source_spans'] = [span]
    return cs, refs, snapshot, source, call


async def test_large_source_span_autoload_adopt_reconcile_and_dedup(ws):
    cs, refs, snapshot, source, call = setup(ws)
    model = Model()
    before = cs.list_objects('ContentNode'), cs.list_objects('Evidence')
    with delegated_task(ws, 'coordinator', call) as (_, actor):
        result = await perform_review(ws, actor, model, 'first', ['rule-comparison'],
            [{'source_id':'s', 'offset':0, 'limit':1, 'table_detail':'references'}])
        packet = json.loads(model.calls[0][1][1])
        blocks = [e for e in packet['evidence'] if e['kind'] == 'source_blocks']
        assert len(blocks) == 1
        assert len(cs.read(source)['payload']['content']) > 16000
        assert len(blocks[0]['observation']['blocks']) == 1
        assert len(blocks[0]['observation']['blocks'][0]['text']) == 4000
        assert blocks[0]['source_version_refs'] == [source]
        bindings = [e for e in packet['evidence'] if e['kind'] == 'source_version_binding']
        assert 'content' not in bindings[0]['object']['payload']
        assert not material_refs_in_observation({'source_version_binding':bindings[0]})
        assert reconcile(cs, actor.task_id)['execution_complete']
        assert (await perform_review(ws, actor, model, 'second', ['rule-comparison']))['review_ref'] == result['review_ref']
        assert len(model.calls) == 1
    assert before == (cs.list_objects('ContentNode'), cs.list_objects('Evidence'))


@pytest.mark.parametrize('managed_context',[False, True])
async def test_native_driver_exposes_span_schema_and_completes_check(ws, managed_context):
    from report_agent import deep_runtime
    from test_deep_runtime import Driver, invoke
    from langchain_core.messages import AIMessage
    cs, _, _, _, call = setup(ws)
    ws.store.set('manifest', {**ws.store.manifest, 'review_execution_mode':'bounded-tool-v1'})
    if managed_context:
        ws.store.set('context_policy','stateful-tools-v1')
        ws.store.set('manifest', {**ws.store.manifest, 'decision_data_policy':'reference-data-v1'})
    response = await Model().ainvoke([])
    driver = Driver(coordinator=[AIMessage(content='', tool_calls=[call]), AIMessage(content='Scoped review saved.')],
        reviewer=[invoke('perform_assigned_review', operation_id='native-span', scope_ids=['rule-comparison'],
                         source_selections=[], content_selections=[]), AIMessage(content='Saved judgment.')], text_tool=[response])
    result = await deep_runtime.run_report(ws, driver)
    assert result['last_error'] is None, result
    record = cs.list_objects('ReviewRecord')[0]
    assert reconcile(cs, record['task_id'])['execution_complete']
    assert len([c for c in driver.calls if c[0] == 'text_tool']) == 1
    task_wire = next(t for batch in driver.bindings['coordinator'] for t in batch if t['name']=='task')
    req_schema = task_wire['parameters']['properties']['review_requirements']
    req_array = next(s for s in req_schema['anyOf'] if s.get('type')=='array')
    spans_schema = req_array['items']['properties']['required_materials']['items']['properties']['source_spans']['items']['properties']
    assert spans_schema['source_ref']['properties']['type']['const'] == 'SourceArtifact'
    assert spans_schema['offset']['minimum'] == 0 and spans_schema['limit']['maximum'] == 50
    assert 'references' in encode(spans_schema['table_detail']) and 'full' in encode(spans_schema['table_detail'])
    assert 'ToolRuntime' not in encode(task_wire)
    checker_messages = next(messages for role,_,messages in driver.calls if role=='text_tool')
    packet = json.loads(next(m.content for m in checker_messages if m.type=='human'))
    span = packet['assignment']['review_requirements'][0]['required_materials'][0]['source_spans'][0]
    source_entry = next(e for e in packet['evidence'] if e['kind']=='source_blocks')
    assert source_entry['source_version_refs'] == [span['source_ref']]
    assert len(source_entry['observation']['blocks']) == span['limit']


async def test_reconciliation_independently_rechecks_per_check_linkage(ws):
    cs, _, _, _, call = setup(ws)
    with delegated_task(ws, 'coordinator', call) as (_, actor):
        result = await perform_review(ws, actor, Model(), 'valid', ['rule-comparison'])
        record = cs.read(result['review_ref'])
        # Fault-injection only in the disposable test store: imitate historical
        # bad adoption to prove reconciliation cannot silently accept it.
        record['payload']['items'][0]['check_results'][0]['observation_indexes'] = [0]
        with cs.store.connect() as db:
            db.execute('UPDATE content_versions SET data=? WHERE type=? AND id=? AND version=?',
                (encode(record),record['ref']['type'],record['ref']['id'],record['ref']['version']))
        status = reconcile(cs, actor.task_id)
        assert not status['execution_complete']
        assert status['remaining'][0]['missing_required_materials'][0]['missing_source_spans']


@pytest.mark.parametrize('detail', [None, 'full', 'references'])
async def test_same_table_view_required_at_all_boundaries(ws, detail):
    cs, _, _, _, call = setup(ws, detail=detail)
    with delegated_task(ws, 'coordinator', call) as (_, actor):
        await perform_review(ws, actor, Model(), 'view', ['rule-comparison'])
        assert reconcile(cs, actor.task_id)['execution_complete']


@pytest.mark.parametrize('case', ['metadata_only','wrong_view','wrong_version','wrong_ordinal','wrong_source','missing_block'])
def test_extent_matcher_rejects_wrong_or_unread_material(case):
    ref = {'type':'SourceArtifact','id':'s','version':1}
    span = {'source_ref':ref,'offset':3,'limit':2,'table_detail':'full'}
    req = {'required_materials':[{'requirement_index':0,'purpose':'Original source','refs':[], 'source_spans':[span]}]}
    extent = {'source_ref':deepcopy(ref), 'ordinals':[3,4], 'table_detail':'full'}
    assert not missing_required_materials(req, set(), {0}, [extent])
    if case == 'metadata_only': extents = []
    else:
        if case == 'wrong_view': extent['table_detail'] = 'references'
        if case == 'wrong_version': extent['source_ref']['version'] = 2
        if case == 'wrong_source': extent['source_ref']['id'] = 'other'
        if case == 'wrong_ordinal': extent['ordinals'] = [4,5]
        if case == 'missing_block': extent['ordinals'] = [3]
        extents = [extent]
    assert missing_required_materials(req, {encode(ref)}, {0}, extents)[0]['missing_source_spans'] == [span]


@pytest.mark.parametrize('case', ['unlinked','metadata','wrong_owner','changed_bytes'])
async def test_adoption_rechecks_linked_origin_receipt(ws, case):
    cs, refs, snapshot, source, call = setup(ws)
    with delegated_task(ws, 'coordinator', call) as (_, actor):
        result = await perform_review(ws, actor, Model(), 'valid', ['rule-comparison'])
        saved = cs.read(result['review_ref'])['payload']
        sub = {k:deepcopy(v) for k,v in saved.items() if k in ReviewSubmission.model_fields}
        item = sub['items'][0]
        if case == 'unlinked':
            item['check_results'][0]['observation_indexes'] = [0]
        else:
            receipt = item['observations'][1]['receipt_id']
            with cs.store.connect() as db:
                data = json.loads(db.execute('SELECT data FROM content_observations WHERE id=?',(receipt,)).fetchone()[0])
            if case == 'metadata': data = {'source_version_binding':{'object':cs.read(source)}}
            if case == 'wrong_owner':
                with pytest.raises(ActionRejected, match='OWNER_MISMATCH'):
                    source_extents_in_observation(cs, 'different-reviewer', data)
                return
            if case == 'changed_bytes': data['evidence'][0]['observation']['blocks'][0]['text'] = 'forged'
            item['observations'][1]['receipt_id'] = cs.observe(actor, data)['receipt_id']
        with pytest.raises(ActionRejected, match='COMPLETED_CHECK_MISSING_REQUIRED_MATERIAL|SOURCE_MATERIAL_PUBLIC_RETURN_CHANGED'):
            cs.submit_review(actor, 'invalid-'+case, sub, saved['runtime_identity'])


async def test_one_check_cannot_borrow_another_checks_source(ws):
    cs, _, _, _, call = setup(ws)
    req = call['args']['review_requirements'][0]
    req['required_checks'].append('second comparison')
    req['required_materials'].append({**deepcopy(req['required_materials'][0]), 'requirement_index':1})
    raw = json.loads((await Model().ainvoke([])).content)
    item = raw['items'][0]
    item['checked_requirement_indexes'] = [0,1]
    item['check_results'].append({**item['check_results'][0], 'requirement_index':1, 'observation_indexes':[0]})
    with delegated_task(ws, 'coordinator', call) as (_, actor):
        with pytest.raises(ActionRejected, match='COMPLETED_CHECK_MISSING_REQUIRED_MATERIAL'):
            await perform_review(ws, actor, Model(json.dumps(raw)), 'cross-check', ['rule-comparison'])
    assert not cs.list_objects('ReviewRecord')


async def test_missing_actual_tail_is_precall_gap(ws):
    _, _, _, _, call = setup(ws, limit=50, count=1000)
    model = Model()
    with delegated_task(ws, 'coordinator', call) as (_, actor):
        with pytest.raises(ActionRejected, match='REVIEW_REQUIRED_SOURCE_SPANS_NOT_SUPPLIED'):
            await perform_review(ws, actor, model, 'tail', ['rule-comparison'])
    assert not model.calls
    assert not ws.store.get('evidence_analysis_attempts')


async def test_whole_packet_material_survives_without_independent_size_gate(ws):
    _, _, _, _, call = setup(ws, limit=20)
    from test_explicit_original_requirement_selection import partial_model
    model = partial_model()
    with delegated_task(ws, 'coordinator', call) as (_, actor):
        await perform_review(ws, actor, model, 'large-material', ['rule-comparison'])
    packet = json.loads(model.calls[0][1][1])
    assert len(encode(packet['evidence'])) > 64000
    sources = [e for e in packet['evidence'] if e['kind'] == 'source_blocks']
    assert sources and sources[0]['selection']['limit'] == 20



def test_existing_requirement_serialization_does_not_gain_empty_fields(ws):
    _, refs, snapshot, _, _ = setup(ws)
    req = review_call(snapshot, refs)['args']['review_requirements']
    old = normalize_review_requirements(req)
    assert 'source_spans' not in old[0]['required_materials'][0]
    assert normalize_review_requirements(old) == old
    with pytest.raises(ValidationError):
        RequiredSourceSpan.model_validate({'source_ref':refs['claim'],'offset':0,'limit':1})


def test_material_measurement_preserves_unicode_without_a_capacity_gate():
    item = {'kind':'saved_object', 'object':{'text':'汉'*65000}}
    prepared = PreparedMaterial(encode([item]), frozenset())
    assert prepared.encoded_characters == len(encode([item]))
    assert prepared.evidence == [item]
    assert not hasattr(prepared, 'require_bounded_size')

