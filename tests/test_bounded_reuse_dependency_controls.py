"""Real bounded producer + native reuse: conservative dependency controls."""
from copy import deepcopy
import json

from langchain_core.messages import AIMessage
import pytest

from report_agent.bounded_review import perform_review
from report_agent.catalog import Catalog
from report_agent.content_tasks import bound_actor, delegated_task
from report_agent.deep_runtime import run_report
from report_agent.hierarchical_tools import actor_for
from report_agent.task_supervision import assignment
from test_agent_duty_repro_artifacts import save_evidence
from test_agent_duty_trace_cases import action, result_value, tool_reply
from test_bounded_review import Model, review_call
from test_decision_data import activate
from test_deep_runtime import Driver
from test_hierarchical_content import seed
from test_task_supervision import ws, offline


@pytest.mark.parametrize('variant', ['no-extent', 'subtree', 'structure-observed',
                                     'source-changed', 'criterion-changed', 'mixed-extents'])
async def test_bounded_producer_keeps_reuse_dependencies(ws, request, variant):
    cs, owner, refs, snapshot, members = seed(ws)
    source = next(ref for ref in members if ref['type'] == 'SourceArtifact')
    reads = [source]
    extra = None
    if variant == 'source-changed':
        extra = Catalog(ws.store).import_file('extra.txt', b'Synthetic extra rule A.')['source']['id']
        extra_ref = cs.capture_sources(owner, 'extra-source', [extra])['result']['source_refs'][0]
        reads.append(extra_ref)
        members = [*members, extra_ref]
        snapshot = cs.freeze(owner, 'old-with-extra', refs['root'], members)['result']['snapshot_ref']
    if variant == 'mixed-extents':
        reads.append(refs['root'])
    old_call = review_call(snapshot, refs, 'dependency-old', reads=reads)
    if variant != 'no-extent':
        old_call['args']['review_requirements'][0]['content_check_scopes'] = [{
            'requirement_index': 0, 'node_ref': refs['claim'],
            'kind': 'subtree_bodies' if variant == 'subtree' else 'local_body'}]
    if variant == 'mixed-extents':
        old_call['args']['review_requirements'][0]['content_check_scopes'].append({
            'requirement_index': 0, 'node_ref': refs['root'], 'kind': 'subtree_bodies'})

    class Checker(Model):
        async def ainvoke(self, messages):
            answer = await super().ainvoke(messages)
            packet = json.loads(messages[1][1])
            value = json.loads(answer.content)
            item = value['items'][0]
            indexes = [i for i, entry in enumerate(packet['evidence'])
                       if entry['kind'] != 'snapshot_structure' or variant == 'structure-observed']
            item['observations'] = [{'evidence_index': i, 'locator': 'synthetic material ' + str(i),
                'observation': 'Synthetic supplied material inspected; no report acceptance.'} for i in indexes]
            item['check_results'][0]['observation_indexes'] = list(range(len(indexes)))
            return AIMessage(content=json.dumps(value))

    model = Checker()
    observed = {'variant': variant, 'scope': 'Dependency preservation only; fake decisions and text, no semantic acceptance.'}
    driver = None
    try:
        with delegated_task(ws, 'coordinator', old_call) as (_, reviewer):
            result = await perform_review(ws, reviewer, model, 'dependency-check', ['rule-comparison'])
        review_ref = result['review_ref']
        original = deepcopy(cs.read(review_ref))
        packet = json.loads(model.calls[0][1][1])
        assert packet['assignment']['review_snapshot_ref'] == snapshot
        assert packet['criteria'] == [cs.read(refs['k'])]
        assert [entry['object'] for entry in packet['evidence'] if entry['kind'] == 'saved_object'] == [
            cs.read(ref) for ref in [refs['claim'], *reads]]
        protected = [cs.read(ref) for ref in [snapshot, *members]]
        observed.update(old_review=original, original_inputs=model.calls, old_snapshot=snapshot)
        additions = cs.commit(owner, 'dependency-child', [
            {'client_key': 'child', 'type': 'ContentNode', 'payload': {'kind': 'block',
                'body': {'text': 'New synthetic child.'}, 'qualifiers': {}, 'claim_kind': 'structure'}},
            {'client_key': 'edge', 'type': 'Relation', 'payload': {'subject_ref': refs['root'],
                'object_ref': {'client_key': 'child'}, 'predicate': 'contains', 'position': 1,
                'provenance_kind': 'adopted_during_generation'}}])['result']['refs']
        new_members, new_reads, new_refs = [*members, *additions.values()], list(reads), deepcopy(refs)
        if variant == 'source-changed':
            new_id = Catalog(ws.store).import_file('extra.txt', b'Synthetic extra rule B.', replaces_id=extra)['source']['id']
            replacement = cs.capture_sources(owner, 'changed-source', [new_id])['result']['source_refs'][0]
            new_members = [replacement if ref == extra_ref else ref for ref in new_members]
            new_reads = [replacement if ref == extra_ref else ref for ref in new_reads]
            observed['source_replacement'] = {'old': extra_ref, 'new': replacement}
        if variant == 'criterion-changed':
            payload = deepcopy(cs.read(refs['k'])['payload'])
            payload['allowed_limits'] += ' Synthetic changed condition.'
            replacement = cs.commit(owner, 'changed-criterion', [{'client_key': 'criterion', 'type': 'Criterion',
                'previous_ref': refs['k'], 'payload': payload}])['result']['refs']['criterion']
            new_members = [replacement if ref == refs['k'] else ref for ref in new_members]
            new_refs['k'] = replacement
            observed['criterion_replacement'] = {'old': refs['k'], 'new': replacement}
        new_snapshot = cs.freeze(owner, 'dependency-current', refs['root'], new_members)['result']['snapshot_ref']
        current_call = review_call(new_snapshot, new_refs, 'dependency-current', reads=new_reads)
        current_call['args'].pop('supervision_plugin', None)
        observed['new_snapshot'] = new_snapshot
        activate(ws)

        def capture_same(messages):
            observed['same_snapshot_public'] = result_value(tool_reply(messages, 'same'))
            observed['same_actor'] = bound_actor(ws, 'reviewer', actor_for('reviewer')).id
            return AIMessage(content='Same snapshot result recorded, not report acceptance.')

        def start_current(messages):
            observed['same_snapshot_parent'] = tool_reply(messages, 'dependency-same').model_dump()
            return AIMessage(content='', tool_calls=[current_call])

        def capture_cross(messages):
            observed['cross_snapshot_public'] = result_value(tool_reply(messages, 'cross'))
            return AIMessage(content='Cross-snapshot outcome recorded without rechecking or changing the original.')

        def finish(messages):
            observed['current_parent'] = tool_reply(messages, 'dependency-current').model_dump()
            return AIMessage(content='Scoped dependency control finished.')

        reuse = action('confirm_review_reuse', 'cross', operation_id='dependency-cross',
            review_ref=review_ref, new_snapshot=new_snapshot, reason='Check actual unchanged-input applicability.', item_indexes=[0])
        coordinator = [AIMessage(content='', tool_calls=[current_call]), finish]
        reviewer_steps = [reuse, capture_cross]
        if variant == 'no-extent':
            same_call = deepcopy(old_call)
            same_call['id'] = 'dependency-same'
            same_call['args'].pop('supervision_plugin', None)
            coordinator = [AIMessage(content='', tool_calls=[same_call]), start_current, finish]
            def begin_reuse(messages):
                actor = bound_actor(ws, 'reviewer', actor_for('reviewer'))
                same = assignment(cs, actor.task_id)['review_snapshot_ref'] == snapshot
                return action('confirm_review_reuse', 'same' if same else 'cross',
                    operation_id='dependency-same' if same else 'dependency-cross', review_ref=review_ref,
                    new_snapshot=snapshot if same else new_snapshot, reason='Explicit exact input applicability.', item_indexes=[0])
            def capture_reuse(messages):
                actor = bound_actor(ws, 'reviewer', actor_for('reviewer'))
                same = assignment(cs, actor.task_id)['review_snapshot_ref'] == snapshot
                return capture_same(messages) if same else capture_cross(messages)
            reviewer_steps = [begin_reuse, capture_reuse]
        driver = Driver(coordinator=coordinator, reviewer=reviewer_steps)
        observed['runtime_result'] = await run_report(ws, driver)
        observed['records_after'] = cs.list_objects('ReviewRecord')
        observed['reuses_after'] = cs.list_objects('ReviewReuse')
        assert observed['runtime_result']['last_error'] is None, observed
        assert len(model.calls) == 1 and not any(role == 'text_tool' for role, _, _ in driver.calls)
        assert cs.read(review_ref) == original and len(observed['records_after']) == 1
        assert observed['current_parent']['content'] == 'Cross-snapshot outcome recorded without rechecking or changing the original.'
        assert all(cs.read(record['ref']) == record for record in protected)
        item = original['payload']['items'][0]
        assert snapshot in original['payload']['dependency_refs']
        if variant in {'no-extent', 'subtree', 'structure-observed', 'mixed-extents'}:
            assert item['dependency_refs'] is None
        else:
            assert source in item['dependency_refs'] and refs['claim'] in item['dependency_refs']
            if variant == 'source-changed':
                assert extra_ref in item['dependency_refs']
        if variant == 'no-extent':
            assert observed['same_snapshot_public']['ok'] is True, observed['same_snapshot_public']
            assert observed['same_snapshot_parent']['content'] == 'Same snapshot result recorded, not report acceptance.'
            reuse_record, = observed['reuses_after']
            assert reuse_record['payload']['review_ref'] == review_ref
            assert reuse_record['payload']['snapshot_ref'] == snapshot
            assert reuse_record['payload']['item_indexes'] == [0]
            assert reuse_record['owner_id'] == observed['same_actor']
        else:
            assert observed['reuses_after'] == []
        cross = observed['cross_snapshot_public']
        assert cross['ok'] is False
        assert cross['code'] == ('CHANGED_REVIEW_SOURCE_REQUIRES_RECHECK' if variant == 'source-changed'
                                 else 'CHANGED_REVIEW_INPUT_REQUIRES_RECHECK')
    except Exception as exc:
        observed['execution_error'] = {'type': type(exc).__name__, 'message': str(exc)}
        raise
    finally:
        observed['checker_calls'] = model.calls
        save_evidence(request, ws, observed, driver)
        try:
            observed['objects_after'] = cs.list_objects()
        except Exception as exc:
            observed['observer_error'] = {'type': type(exc).__name__, 'message': str(exc)}
            raise
        finally:
            save_evidence(request, ws, observed, driver)
