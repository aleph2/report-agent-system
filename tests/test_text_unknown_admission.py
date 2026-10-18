"""Actual one-shot tool admission: no provider retries disguised by new IDs."""
import json
import pytest
from report_agent.content_tasks import delegated_task
from report_agent.errors import ActionRejected
from report_agent.text_work import produce
from test_bounded_review import Model
from test_hierarchical_content import seed
from test_task_supervision import ws
from test_text_work import writer_call, content
from langchain_core.messages import AIMessage


@pytest.mark.parametrize('reverse_duplicate', [False, True])
async def test_unknown_same_material_cannot_be_reissued_with_shorter_objective_or_new_id(ws, reverse_duplicate):
    _, _, refs, _, _ = seed(ws)
    selected = [refs['claim'], refs['root']]
    with delegated_task(ws, 'coordinator', writer_call()) as (_, actor):
        failed = Model(RuntimeError('Synthetic unknown transport result'))
        with pytest.raises(RuntimeError):
            await produce(ws, actor, failed, 'original', 'Assess this selected evidence in detail',
                          'ContentNode', selected)
        new_model = Model(json.dumps(content()))
        retry_refs = [*reversed(selected), selected[0]] if reverse_duplicate else selected
        with pytest.raises(ActionRejected, match='TEXT_WORK_SAME_EVIDENCE_OUTCOME_UNRESOLVED'):
            await produce(ws, actor, new_model, 'renamed', 'Same task, shorter wording',
                          'ContentNode', retry_refs)
        assert len(failed.calls) == 1 and new_model.calls == []
        assert ws.store.get('text_work:'+actor.id+':renamed') is None


async def test_known_rejected_response_allows_corrected_request_and_new_material_is_not_equated(ws):
    _, _, refs, _, _ = seed(ws)
    with delegated_task(ws, 'coordinator', writer_call()) as (_, actor):
        rejected = Model('invalid JSON')
        with pytest.raises(ActionRejected):
            await produce(ws, actor, rejected, 'known', 'Original task', 'ContentNode', [refs['claim']])
        good = Model(json.dumps(content()))
        result = await produce(ws, actor, good, 'known-corrected', 'Correct output contract',
                               'ContentNode', [refs['claim']])
        assert result['state'] == 'completed' and len(good.calls) == 1
        unknown = Model(RuntimeError('Synthetic unknown'))
        with pytest.raises(RuntimeError):
            await produce(ws, actor, unknown, 'unknown', 'Separate material', 'ContentNode', [refs['root']])
        different = Model(json.dumps(content()))
        result = await produce(ws, actor, different, 'different', 'Actual different material',
                               'ContentNode', [refs['claim']])
        assert result['state'] == 'completed' and len(different.calls) == 1


async def test_actor_scope_is_not_a_foreign_attempt_disclosure(ws):
    _, _, refs, _, _ = seed(ws)
    with delegated_task(ws, 'coordinator', writer_call('first')) as (_, actor):
        with pytest.raises(RuntimeError):
            await produce(ws, actor, Model(RuntimeError('Unknown')), 'unknown', 'Read',
                          'ContentNode', [refs['claim']])
    with delegated_task(ws, 'coordinator', writer_call('other')) as (_, other):
        model = Model(json.dumps(content()))
        result = await produce(ws, other, model, 'separate', 'Independent assignment',
                               'ContentNode', [refs['claim']])
        assert result['actor_id'] == other.id and len(model.calls) == 1


async def test_received_length_is_not_unknown_and_legacy_batch_is_not_same_material(ws):
    _, _, refs, _, _ = seed(ws)
    class Truncated(Model):
        async def ainvoke(self, messages):
            self.calls.append(messages)
            return AIMessage('Partial known output', response_metadata={'finish_reason':'length'})
    with delegated_task(ws, 'coordinator', writer_call()) as (_, actor):
        with pytest.raises(ActionRejected, match='INCOMPLETE'):
            await produce(ws, actor, Truncated(), 'length', 'Produce', 'ContentNode', [refs['claim']])
        good = Model(json.dumps(content()))
        assert (await produce(ws, actor, good, 'corrected', 'Bounded correction',
                              'ContentNode', [refs['claim']]))['state'] == 'completed'
        with pytest.raises(RuntimeError):
            await produce(ws, actor, Model(RuntimeError('Unknown batch')), 'batch', 'Batch',
                          'ContentNode', [refs['claim'], refs['root']])
        # Emulate original reservation rows, which lacked material metadata.
        key = 'text_work:'+actor.id+':batch'
        old = ws.store.get(key)
        old.pop('material_identity', None); old.pop('object_type', None)
        ws.store.set(key, old)
        changed = Model(json.dumps(content()))
        result = await produce(ws, actor, changed, 'new-selection', 'Different actual selection',
                               'ContentNode', [refs['root']])
        assert result['state'] == 'completed'
        with pytest.raises(ActionRejected, match='SAME_EVIDENCE'):
            await produce(ws, actor, changed, 'same-legacy-batch', 'Paraphrased batch',
                          'ContentNode', [refs['root'], refs['claim']])


async def test_archived_complete_raw_before_local_parse_failure_is_not_unknown(ws, monkeypatch):
    import report_agent.text_work as text_work
    _, _, refs, _, _ = seed(ws)
    original_parser = text_work.parse_output
    def failed_local_parse(*args):
        raise OSError('Synthetic post-response local failure')
    with delegated_task(ws, 'coordinator', writer_call()) as (_, actor):
        monkeypatch.setattr(text_work, 'parse_output', failed_local_parse)
        with pytest.raises(OSError, match='post-response'):
            await produce(ws, actor, Model(json.dumps(content())), 'received', 'Old task',
                          'ContentNode', [refs['claim']])
        assert ws.store.get('text_work:'+actor.id+':received')['state'] == 'reserved'
        monkeypatch.setattr(text_work, 'parse_output', original_parser)
        result = await produce(ws, actor, Model(json.dumps(content())), 'corrected',
                               'Corrected known local failure', 'ContentNode', [refs['claim']])
        assert result['state'] == 'completed'


def test_material_identity_does_not_treat_new_public_receipt_id_as_new_text():
    from report_agent.text_work import material_identity
    first = {'kind':'public_tool_return','observation_ref':'old','tool':'read_source_page',
        'sha256':'exact-sha','text':'Actual unchanged source content','note':'Public return'}
    second = {**first, 'observation_ref':'new'}
    assert material_identity([first]) == material_identity([second, first])
    assert material_identity([first]) != material_identity([{**second, 'text':'Actual different material'}])


@pytest.mark.parametrize('old_via_observation', [False, True])
async def test_registered_tool_detects_same_version_through_real_selection_receipt(ws, old_via_observation):
    from langchain_core.messages import ToolMessage
    from langchain_core.tools import StructuredTool
    from report_agent.task_context import save_observation
    from report_agent.store import encode
    from test_text_work import tools
    _, _, refs, snapshot, _ = seed(ws)
    with delegated_task(ws, 'coordinator', writer_call()) as (_, actor):
        model = Model(RuntimeError('Unknown original'))
        registered = tools(ws, 'writer', model)
        read = StructuredTool.from_function(registered['read_content_selection']).invoke({
            'snapshot_ref':snapshot, 'selections':[{'ref':refs['claim'], 'offset':0, 'limit':12}]})
        observation, _ = save_observation(ws, 'writer', ToolMessage(encode(read),
            name='read_content_selection', tool_call_id='actual-selection'))
        tool = StructuredTool.from_function(coroutine=registered['process_report_content'])
        original = {'operation_id':'old', 'objective':'Assess selected node', 'object_type':'ContentNode',
            'input_refs':[] if old_via_observation else [refs['claim']],
            'observation_refs':[observation] if old_via_observation else []}
        with pytest.raises(RuntimeError):
            await tool.ainvoke(original)
        next_args = {**original, 'operation_id':'new', 'objective':'Changed wording with extra evidence',
            'input_refs':[refs['evidence']], 'observation_refs':[observation]}
        with pytest.raises(ActionRejected, match='RELATED_OUTCOME'):
            await tool.ainvoke(next_args)
        assert len(model.calls) == 1
        assert ws.store.get('text_work:'+actor.id+':new') is None


async def test_distinct_work_disposition_cannot_release_unchanged_material(ws, tmp_path):
    import hashlib
    from report_agent.text_work_disposition import authorize_distinct_work
    _, _, refs, _, _ = seed(ws)
    with delegated_task(ws, 'coordinator', writer_call()) as (_, actor):
        with pytest.raises(RuntimeError):
            await produce(ws, actor, Model(RuntimeError('Unknown')), 'old', 'Assess',
                          'ContentNode', [refs['claim']])
        with pytest.raises(ActionRejected, match='SAME_EVIDENCE') as failure:
            await produce(ws, actor, Model(), 'new', 'Shorter words', 'ContentNode', [refs['claim']])
        details = json.loads(str(failure.value).split(': ', 1)[1])
        path = tmp_path/'inspection.txt'
        path.write_text('No new factual material exists.')
        with pytest.raises(ActionRejected, match='UNCHANGED_MATERIAL'):
            authorize_distinct_work(ws, actor, 'new', details['candidate_request_hash'],
                details['candidate_material_identity'], details['conflicts'], rationale='Changed wording',
                evidence_path=path, evidence_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                authorization_basis='Validation scope does not authorize unknown retries')


async def test_unknown_same_content_plus_compact_unrelated_page_does_not_reach_producer(ws):
    """Size rejection of a large page must not be the only replay containment."""
    from report_agent.store import digest
    _, _, refs, _, _ = seed(ws)
    with delegated_task(ws, 'coordinator', writer_call()) as (_, actor):
        with pytest.raises(RuntimeError):
            await produce(ws, actor, Model(RuntimeError('Unknown original result')),
                          'original', 'Revise the same selected node', 'ContentNode', [refs['claim']])
        body = 'Different source page concerns another site, not this assessment.'
        ws.store.set('tool_observation:unrelated', {'owner':actor.id, 'tool':'read_source_page',
            'sha256':digest(body), 'text':body})
        retry = Model(json.dumps(content()))
        with pytest.raises(ActionRejected, match='TEXT_WORK_RELATED_OUTCOME_UNRESOLVED'):
            await produce(ws, actor, retry, 'renamed-with-extra-page',
                          'Revise the same selected node using an additional page',
                          'ContentNode', [refs['claim']], observation_refs=['unrelated'])
        assert retry.calls == []
        assert ws.store.get('text_work:'+actor.id+':renamed-with-extra-page') is None


@pytest.mark.parametrize('tamper', ['none', 'objective', 'evidence_file', 'material'])
async def test_host_disposition_is_exact_once_and_preserves_unknown(ws, tmp_path, tamper):
    import hashlib
    from report_agent.store import digest
    from report_agent.text_work_disposition import authorize_distinct_work
    _, _, refs, _, _ = seed(ws)
    with delegated_task(ws, 'coordinator', writer_call()) as (_, actor):
        with pytest.raises(RuntimeError):
            await produce(ws, actor, Model(RuntimeError('Unknown')),
                          'original', 'Old work', 'ContentNode', [refs['claim']])
        old_key = 'text_work:'+actor.id+':original'
        old = ws.store.get(old_key)
        body = 'New located observation resolves the actual class of this site.'
        ws.store.set('tool_observation:relevant', {'owner':actor.id, 'tool':'read_source_page',
            'sha256':digest(body), 'text':body})
        model = Model(json.dumps(content()))
        async def run(objective='Reassess from the new factual observation'):
            return await produce(ws, actor, model, 'new-work', objective, 'ContentNode',
                                 [refs['claim']], observation_refs=['relevant'])
        with pytest.raises(ActionRejected, match='RELATED_OUTCOME') as failure:
            await run()
        details = json.loads(str(failure.value).split(': ', 1)[1])
        path = tmp_path/'host-inspection.json'
        path.write_text('Inspected new source applicability; prior response stays unknown.')
        key = authorize_distinct_work(ws, actor, 'new-work', details['candidate_request_hash'],
            details['candidate_material_identity'], details['conflicts'],
            rationale='New evidence resolves a factual prerequisite; this is distinct work, not recovery of the old response.',
            evidence_path=path, evidence_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            authorization_basis='Existing user-authorized validation scope and spending budget')
        if tamper == 'evidence_file':
            path.write_text('Altered after registration')
        if tamper == 'material':
            ws.store.set('tool_observation:relevant', {'owner':actor.id, 'tool':'read_source_page',
                'sha256':digest('Other text'), 'text':'Other text'})
        if tamper != 'none':
            with pytest.raises(ActionRejected, match='RELATED_OUTCOME'):
                await run('Changed objective' if tamper == 'objective' else 'Reassess from the new factual observation')
            assert model.calls == [] and ws.store.get(key)['state'] == 'authorized'
        else:
            first = await run()
            assert first['state'] == 'completed' and len(model.calls) == 1
            assert (await run())['reused'] and len(model.calls) == 1
            assert ws.store.get(key)['state'] == 'consumed'
            with pytest.raises(ActionRejected, match='RELATED_OUTCOME'):
                await produce(ws, actor, model, 'another-id', 'Reassess from the new factual observation',
                              'ContentNode', [refs['claim']], observation_refs=['relevant'])
            assert len(model.calls) == 1
            with pytest.raises(ActionRejected, match='ALREADY_REGISTERED'):
                authorize_distinct_work(ws, actor, 'new-work', details['candidate_request_hash'],
                    details['candidate_material_identity'], details['conflicts'],
                    rationale='Cannot refresh the allowance', evidence_path=path,
                    evidence_sha256=hashlib.sha256(path.read_bytes()).hexdigest(), authorization_basis='Same authority')
        assert ws.store.get(old_key) == old


async def prepared_disposition(ws, tmp_path, actor, refs):
    """A real blocked request and host disposition, without any paid service."""
    import hashlib
    from report_agent.text_work_disposition import authorize_distinct_work
    with pytest.raises(RuntimeError):
        await produce(ws, actor, Model(RuntimeError('Unknown')), 'old', 'Old task',
                      'ContentNode', [refs['claim']])
    async def run(model):
        return await produce(ws, actor, model, 'new', 'New facts', 'ContentNode',
                             [refs['claim'], refs['evidence']])
    with pytest.raises(ActionRejected, match='RELATED_OUTCOME') as failure:
        await run(Model())
    details = json.loads(str(failure.value).split(': ', 1)[1])
    path = tmp_path/'inspection.txt'
    path.write_text('Inspected new evidence and actual source applicability.')
    key = authorize_distinct_work(ws, actor, 'new', details['candidate_request_hash'],
        details['candidate_material_identity'], details['conflicts'], rationale='Distinct new factual basis',
        evidence_path=path, evidence_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        authorization_basis='Existing validation authority')
    return key, run


@pytest.mark.parametrize('change', ['new_conflict', 'missing_binding', 'wrong_binding'])
async def test_disposition_cannot_ignore_changed_unknown_bindings(ws, tmp_path, change):
    _, _, refs, _, _ = seed(ws)
    with delegated_task(ws, 'coordinator', writer_call()) as (_, actor):
        key, run = await prepared_disposition(ws, tmp_path, actor, refs)
        if change == 'new_conflict':
            with pytest.raises(RuntimeError):
                await produce(ws, actor, Model(RuntimeError('Other unknown')), 'other', 'Independent evidence',
                              'ContentNode', [refs['evidence']])
        else:
            value = ws.store.get(key)
            if change == 'missing_binding':
                value['unresolved_attempts'] = []
            else:
                value['unresolved_attempts'][0]['request_hash'] = 'f'*64
            ws.store.set(key, value)
        model = Model(json.dumps(content()))
        with pytest.raises(ActionRejected, match='RELATED_OUTCOME'):
            await run(model)
        assert model.calls == [] and ws.store.get(key)['state'] == 'authorized'


async def test_disposition_consumption_rolls_back_if_reservation_fails(ws, tmp_path):
    import sqlite3
    _, _, refs, _, _ = seed(ws)
    with delegated_task(ws, 'coordinator', writer_call()) as (_, actor):
        key, run = await prepared_disposition(ws, tmp_path, actor, refs)
        with ws.store.connect() as db:
            db.execute("CREATE TRIGGER fail_new_reservation BEFORE INSERT ON state "
                       "WHEN NEW.key LIKE 'text_work:%:new' BEGIN SELECT RAISE(ABORT, 'synthetic reservation failure'); END")
        model = Model(json.dumps(content()))
        with pytest.raises(sqlite3.IntegrityError, match='synthetic reservation failure'):
            await run(model)
        assert model.calls == [] and ws.store.get(key)['state'] == 'authorized'
        assert ws.store.get('text_work:'+actor.id+':new') is None
        assert not [e for e in ws.store.events() if e['kind'] == 'text_work_distinct_disposition_consumed']


async def test_concurrent_exact_request_consumes_once(ws, tmp_path):
    import asyncio
    _, _, refs, _, _ = seed(ws)
    with delegated_task(ws, 'coordinator', writer_call()) as (_, actor):
        key, run = await prepared_disposition(ws, tmp_path, actor, refs)
        entered, release = asyncio.Event(), asyncio.Event()
        class Held(Model):
            async def ainvoke(self, messages):
                entered.set()
                await release.wait()
                return await super().ainvoke(messages)
        model = Held(json.dumps(content()))
        first = asyncio.create_task(run(model))
        await entered.wait()
        try:
            with pytest.raises(ActionRejected, match='OUTCOME_UNRESOLVED'):
                await run(model)
        finally:
            release.set()
        assert (await first)['state'] == 'completed'
        assert len(model.calls) == 1 and ws.store.get(key)['state'] == 'consumed'
        assert len([e for e in ws.store.events() if e['kind'] == 'text_work_distinct_disposition_consumed']) == 1


@pytest.mark.parametrize('tamper', ['owner', 'sha', 'receipt_owner', 'receipt_data'])
async def test_real_selection_observation_requires_unchanged_receipt(ws, tamper):
    from langchain_core.messages import ToolMessage
    from langchain_core.tools import StructuredTool
    from report_agent.task_context import save_observation
    from report_agent.errors import ActionForbidden
    from report_agent.store import encode
    from test_text_work import tools
    _, _, refs, snapshot, _ = seed(ws)
    with delegated_task(ws, 'coordinator', writer_call()) as (_, actor):
        model = Model(json.dumps(content()))
        registered = tools(ws, 'writer', model)
        raw = StructuredTool.from_function(registered['read_content_selection']).invoke({
            'snapshot_ref':snapshot, 'selections':[{'ref':refs['claim']}]})
        observation, saved = save_observation(ws, 'writer', ToolMessage(encode(raw),
            name='read_content_selection', tool_call_id='selection'))
        if tamper in {'owner', 'sha'}:
            saved['owner' if tamper == 'owner' else 'sha256'] = 'wrong'
            ws.store.set('tool_observation:'+observation, saved)
        else:
            with ws.store.connect() as db:
                column = 'actor_id' if tamper == 'receipt_owner' else 'data'
                db.execute('UPDATE content_observations SET '+column+'=? WHERE id=?', ('{}', raw['receipt_id']))
        tool = StructuredTool.from_function(coroutine=registered['process_report_content'])
        with pytest.raises((ActionForbidden, ActionRejected), match='owner|UNVERIFIED'):
            await tool.ainvoke({'operation_id':'new', 'objective':'Use owned data',
                'object_type':'ContentNode', 'observation_refs':[observation]})
        assert model.calls == []


async def test_shared_structural_heading_observation_does_not_block_other_content(ws):
    from langchain_core.messages import ToolMessage
    from langchain_core.tools import StructuredTool
    from report_agent.task_context import save_observation
    from report_agent.store import encode
    from test_text_work import tools
    _, _, refs, snapshot, _ = seed(ws)
    with delegated_task(ws, 'coordinator', writer_call()) as (_, actor):
        raw = StructuredTool.from_function(tools(ws, 'writer', Model())['read_content_selection']).invoke({
            'snapshot_ref':snapshot, 'selections':[{'ref':refs['root']}]})
        observation, _ = save_observation(ws, 'writer', ToolMessage(encode(raw),
            name='read_content_selection', tool_call_id='root'))
        with pytest.raises(RuntimeError):
            await produce(ws, actor, Model(RuntimeError('Unknown')), 'old', 'Old work',
                          'ContentNode', [refs['evidence']], observation_refs=[observation])
        model = Model(json.dumps(content()))
        assert (await produce(ws, actor, model, 'new', 'Other content', 'ContentNode',
            [refs['claim']], observation_refs=[observation]))['state'] == 'completed'
        assert len(model.calls) == 1


async def test_host_registration_requires_inactive_project(ws, tmp_path):
    _, _, refs, _, _ = seed(ws)
    with delegated_task(ws, 'coordinator', writer_call()) as (_, actor):
        with ws.store.run_lock(), pytest.raises(RuntimeError, match='PROJECT_ALREADY_RUNNING'):
            await prepared_disposition(ws, tmp_path, actor, refs)
        with ws.store.connect() as db:
            assert db.execute("SELECT COUNT(*) FROM state WHERE key LIKE 'text_work_disposition:%'").fetchone()[0] == 0
