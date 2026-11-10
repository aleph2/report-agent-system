"""Deterministic boundary oracles, not model/engineering acceptance.

Run the real graph, middleware, task contracts and DOCX writer with local fake
models. All payloads are synthetic; original historical traces are preserved privately.
"""
import json
import hashlib
from copy import deepcopy
from io import BytesIO
from pathlib import Path

import pytest
from docx import Document
from docx.oxml.ns import qn
from langchain_core.messages import AIMessage, ToolMessage
from PIL import Image

from report_agent import deep_runtime
from report_agent.bounded_review import perform_review
from report_agent.content_export import export_snapshot
from report_agent.content_layout import ParagraphLayout, emit_text
from report_agent.content_tasks import delegated_task, normalize_review_requirements
from report_agent.errors import ActionRejected
from report_agent.task_context import TaskContext
from report_agent.task_supervision import reconcile, validate_requirements
from test_bounded_review import Model, review_call
from test_decision_data import activate
from test_deep_runtime import Driver, invoke
from test_hierarchical_content import seed
from test_task_supervision import ws, offline


async def test_explicit_source_read_reaches_next_model_without_field_clipping(ws):
    seed(ws)
    activate(ws)
    literal = 'Relevant original paragraph. ' * 30 + 'FINAL CONDITION MUST REMAIN VISIBLE.'
    ws.store.set('manifest', {**ws.store.manifest, 'sources': [
        {'id': 's', 'title': 'Source', 'content': literal, 'coverage': 'complete'}]})
    with ws.store.connect() as db:
        db.execute('delete from source_blocks')
        db.execute('insert into source_blocks values (?,?,?,?)',
                   ('s', 0, json.dumps({'page': 1}), literal))

    def inspect_request(messages):
        response = next(m for m in reversed(messages)
                        if isinstance(m, ToolMessage) and m.name == 'read_source_page')
        assert literal in json.dumps(json.loads(response.content), ensure_ascii=False)
        return AIMessage(content='Offline boundary inspected; no semantic verdict.')

    driver = Driver(coordinator=[invoke('read_source_page', source_id='s', offset=0, limit=1),
                                 inspect_request])
    result = await deep_runtime.run_report(ws, driver)
    assert result['last_error'] is None, result
    assert len(driver.calls) == 2


def test_completed_return_keeps_exact_late_limitations(ws):
    seed(ws)
    activate(ws)
    warning = 'Source condition; ' * 100 + 'REQUIRED GUIDE TABLE NOT SUPPLIED.'
    payload = {'kind': 'block', 'body': {'text': 'Synthetic body.'},
               'claim_kind': 'fact', 'qualifiers': {'limitations': warning}}
    raw = {'state': 'completed', 'semantic_correctness_verified': False,
           'text_work_id': 'synthetic-receipt', 'object_type': 'ContentNode',
           'payloads': [payload], 'limitations': [warning]}
    message = ToolMessage(content=json.dumps(raw), name='process_report_content', tool_call_id='recorded-output')
    returned = TaskContext(ws, 'coordinator').bound_result(message)
    assert warning in json.dumps(json.loads(returned.content), ensure_ascii=False)


def test_ambiguous_scope_is_rejected_at_assignment_before_any_model(ws):
    cs, _, refs, snapshot, _ = seed(ws)
    first = review_call(snapshot, refs)['args']['review_requirements'][0]
    second = {**deepcopy(first), 'target_ref': refs['root']}
    with pytest.raises(ActionRejected, match='DUPLICATE_TASK_REVIEW_SCOPE'):
        validate_requirements(cs, snapshot, normalize_review_requirements([first, second]))
    assert not cs.list_objects('DelegatedTask')


async def test_explicit_historical_comparison_can_execute_save_and_reconcile(ws):
    cs, actor, refs, snapshot, _ = seed(ws)
    ws.store.set('manifest', {**ws.store.manifest, 'review_execution_mode': 'bounded-tool-v1'})
    historical = cs.commit(actor, 'comparison-body', [{
        'client_key': 'old', 'type': 'ContentNode', 'payload': {
            'kind': 'block', 'body': {'text': 'Historical comparison: B permits 75 to 100.'},
            'claim_kind': 'structure', 'qualifiers': {}}}])['result']['refs']['old']
    original_snapshot = cs.read(snapshot)
    call = review_call(snapshot, refs)
    call['args']['review_requirements'][0]['required_read_refs'] = [historical]
    model = Model()
    with delegated_task(ws, 'coordinator', call) as (_, reviewer):
        result = await perform_review(ws, reviewer, model, 'compare-history', ['rule-comparison'])
        assert result['review_ref']['type'] == 'ReviewRecord'
        assert reconcile(cs, reviewer.task_id)['execution_complete']
        stored = cs.read(result['review_ref'])
        assert historical in stored['payload']['dependency_refs']
    assert len(model.calls) == 1
    assert cs.read(snapshot) == original_snapshot
    assert historical not in original_snapshot['payload']['refs']


def test_document_has_one_directory_even_with_nested_report_nodes(ws):
    cs, actor, refs, _, members = seed(ws)
    added = cs.commit(actor, 'nested-report', [
        {'client_key': 'child', 'type': 'ContentNode', 'payload': {
            'kind': 'report', 'body': {'text': 'Nested report\nExact nested body.'},
            'claim_kind': 'structure', 'qualifiers': {}}},
        {'client_key': 'edge', 'type': 'Relation', 'payload': {
            'subject_ref': refs['root'], 'object_ref': {'client_key': 'child'},
            'predicate': 'contains', 'position': 1, 'provenance_kind': 'adopted_during_generation'}}
    ])['result']['refs']
    snap = cs.freeze(actor, 'nested-snapshot', refs['root'],
                     [*members, *added.values()])['result']['snapshot_ref']
    before = cs.read(added['child'])
    exported = export_snapshot(cs, actor, 'nested-export', snap, {'toc': True})['result']
    doc = Document(ws.store.root / exported['file_ref'])
    assert len([n for n in doc.element.iter(qn('w:instrText')) if 'TOC ' in n.text]) == 1
    assert 'Exact nested body.' in [p.text for p in doc.paragraphs]
    assert cs.read(added['child']) == before


def test_paragraph_formatting_preserves_markdown_image_and_emphasis():
    png = BytesIO()
    Image.new('RGB', (4, 4), 'white').save(png, format='PNG')
    line = '![Original figure](source:fixture.png)'
    doc = Document()
    def renderer(target, token, width=None):
        target.add_run().add_picture(BytesIO(png.getvalue()))
        return True
    emit_text(doc, line + '\n**Required emphasis**', renderer, [
        ParagraphLayout(text=line, line_spacing=1.5),
        ParagraphLayout(text='**Required emphasis**', line_spacing=1.5)])
    assert len(doc.inline_shapes) == 1
    assert not any('![' in p.text or '**' in p.text for p in doc.paragraphs)
    assert any(r.bold and r.text == 'Required emphasis' for p in doc.paragraphs for r in p.runs)
    assert all(p.paragraph_format.line_spacing == 1.5 for p in doc.paragraphs)


@pytest.mark.parametrize('sequence', [1005, 1147])
def test_historical_public_trace_keeps_original_material_and_qualifications(ws, sequence):
    seed(ws); activate(ws)
    fixture = json.loads((Path(__file__).parent / 'fixtures/boundary-trace-20261018.json').read_text())
    entry = next(e for e in fixture['items'] if e['trace_sequence'] == sequence)
    assert hashlib.sha256(entry['content'].encode()).hexdigest() == entry['sha256']
    original = json.loads(entry['content'])
    returned = TaskContext(ws, 'coordinator').bound_result(ToolMessage(
        content=entry['content'], name=entry['tool'], tool_call_id=f'trace-{sequence}'))
    presented = json.loads(returned.content)
    if sequence == 1005:
        assert presented['metadata'] == original
    else:
        outputs = original.get('payloads', [original.get('payload')])
        for i, value in enumerate(outputs):
            assert presented['metadata']['outputs']['entries'][i]['qualifiers'] == value['qualifiers']
    archive = ws.store.get('tool_observation:' + presented['observation_ref'])
    assert archive['text'] == entry['content'] and archive['sha256'] == entry['sha256']


async def test_real_review_controls_survive_native_filesystem_eviction(ws):
    from langchain.agents import create_agent
    from deepagents.middleware.filesystem import FilesystemMiddleware
    from deepagents.backends import StateBackend
    from report_agent.bounded_review import review_tool
    from report_agent.decision_data import deliver_controls
    from langchain_openai.chat_models.base import _convert_message_to_dict
    cs, _, refs, snapshot, _ = seed(ws); activate(ws)
    base = json.loads((await Model().ainvoke([])).content)
    warning = 'Located comparison remains incomplete. ' * 100 + 'LATE REQUIRED CHECK STILL NOT DONE.'
    item = base['items'][0]
    item.update(execution_state='running', verdict=None, reason=warning, checked_requirement_indexes=[])
    item['coverage']['unchecked'] = [warning]
    item['check_results'][0].update(execution_state='blocked', remaining=warning)
    with delegated_task(ws, 'coordinator', review_call(snapshot, refs)) as (_, actor):
        checker = Model(json.dumps(base))
        def inspect_request(messages):
            reply = next(m for m in messages if isinstance(m, ToolMessage))
            assert reply.additional_kwargs.get('report_controls_restored') is True, reply.model_dump()
            assert deliver_controls(ws, 'reviewer', reply) is reply
            # Verify the adapter's actual wire view too: artifact is not sent.
            wire = _convert_message_to_dict(reply)
            assert 'artifact' not in wire
            assert warning in json.dumps(wire, ensure_ascii=False)
            assert 'platform_managed_not_prevalidated' in json.dumps(wire)
            return AIMessage(content='Synthetic inspection only.')
        driver = Driver(reviewer=[invoke('perform_assigned_review', operation_id='check',
            scope_ids=['rule-comparison'], source_selections=[], content_selections=[]), inspect_request])
        graph = create_agent(driver('reviewer'), tools=[review_tool(ws, checker)], middleware=[
            FilesystemMiddleware(backend=StateBackend(), tools=['read_file'], tool_token_limit_before_evict=100),
            TaskContext(ws, 'reviewer')])
        await graph.ainvoke({'messages': [{'role': 'user', 'content': 'Inspect this fixed test case.'}]})
        assert len(driver.calls) == 2 and len(checker.calls) == 1
        assert not reconcile(cs, actor.task_id)['execution_complete']


@pytest.mark.parametrize('mutation', ['owner', 'sha256', 'tool_call_id', 'public_digest', 'stored_text'])
def test_final_delivery_rejects_changed_identity_or_original(ws, mutation):
    from report_agent.decision_data import deliver_controls
    seed(ws); activate(ws)
    reply = TaskContext(ws, 'coordinator').bound_result(ToolMessage(
        content=json.dumps({'observation': 'Exact public fact', 'limitations': ['Unverified']}),
        name='analyze_source_image', tool_call_id='test'))
    binding = reply.artifact['report_public_delivery']
    if mutation == 'stored_text':
        key = 'tool_observation:' + binding['observation_ref']
        ws.store.set(key, {**ws.store.get(key), 'text': 'Changed original'})
    else:
        reply.artifact['report_public_delivery'][mutation] = 'changed'
    with pytest.raises(ActionRejected, match='PUBLIC_DELIVERY_'):
        deliver_controls(ws, 'coordinator', reply)


async def test_artifact_review_returns_saved_findings_on_fresh_and_cached_path(ws):
    from test_artifact_review import setup, visual, payload
    from report_agent.artifact_review import bounded_artifact_review_tool
    cs, refs, snap, export, render, source, requested = setup(ws, pages=2)
    activate(ws)
    with delegated_task(ws, 'coordinator', requested) as (_, actor):
        receipt = visual(cs, actor, render, export, source, 1)
        partial = payload(snap, refs, render, [receipt], complete=False)
        model = Model(partial.model_dump_json())
        tool = bounded_artifact_review_tool(ws, model)
        first = await tool('partial', ['rule-comparison'], [receipt])
        again = await tool('partial', ['rule-comparison'], [receipt])
        saved = cs.read(first['result']['review_ref'])['payload']
        assert first['review'] == again['review'] == saved
        for raw in (first, again):
            result = TaskContext(ws, 'reviewer').bound_result(ToolMessage(content=json.dumps(raw),
                name='perform_assigned_artifact_review', tool_call_id='artifact'))
            assert json.loads(result.content)['metadata']['review']['items'] == saved['items']
        assert again['reused'] and len(model.calls) == 1


def test_styles_do_not_split_lists_soft_lines_or_tables():
    from report_agent.exporting import _add_markdown
    body = '3. **First**\n4. Second\n\nSoft line one\nsoft line two\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n---\n\n```\ncode\n```'
    baseline, styled = Document(), Document()
    _add_markdown(baseline, body, None)
    emit_text(styled, body, None, [ParagraphLayout(text=text, line_spacing=1.5)
        for text in ['3. **First**', '4. Second', 'soft line two', '---', 'code']])
    assert [p.text for p in styled.paragraphs] == [p.text for p in baseline.paragraphs]
    assert [[c.text for row in t.rows for c in row.cells] for t in styled.tables] == [['A', 'B', '1', '2']]
    numbers = [p._p.pPr.numPr.numId.val for p in styled.paragraphs if p._p.pPr is not None and p._p.pPr.numPr is not None]
    assert len(numbers) == 2 and len(set(numbers)) == 1
    assert styled.paragraphs[2].paragraph_format.line_spacing == 1.5
    with pytest.raises(ActionRejected, match='CONFLICTING_LAYOUT_FOR_SAME_RENDERED_PARAGRAPH'):
        emit_text(Document(), 'one\ntwo', None, [ParagraphLayout(text='one', line_spacing=1.5),
                                              ParagraphLayout(text='two', line_spacing=2)])


@pytest.mark.parametrize('case', ['undeclared', 'unread', 'foreign_read', 'wrong_version', 'target'])
def test_historical_comparison_exception_does_not_expand_authority(ws, case):
    from test_task_supervision import review_call as assignment_call
    from test_hierarchical_content import review_item, submission
    from report_agent.content_store import Actor
    cs, author, refs, snapshot, _ = seed(ws)
    historical = cs.commit(author, 'old', [{'client_key': 'old', 'type': 'ContentNode', 'payload': {
        'kind': 'block', 'body': {'text': 'Comparison'}, 'claim_kind': 'structure', 'qualifiers': {}}}])['result']['refs']['old']
    second = cs.commit(author, 'old-next', [{'client_key': 'old', 'type': 'ContentNode',
        'previous_ref': historical, 'payload': {**cs.read(historical)['payload'],
        'body': {'text': 'Later comparison'}}}])['result']['refs']['old']
    call = assignment_call(snapshot, refs, reads=[] if case == 'undeclared' else [historical])
    with delegated_task(ws, 'coordinator', call) as (_, reviewer):
        if case != 'unread':
            cs.read_context(Actor('other', 'reviewer', 'other') if case == 'foreign_read' else reviewer,
                            second if case == 'wrong_version' else historical)
        receipt = cs.read_context(reviewer, refs['claim'])['receipt_id']
        item = review_item(historical if case == 'target' else refs['claim'], refs['k'], receipt)
        item['scope_id'] = 'rule-comparison'
        request = submission(snapshot, refs, item)
        request['dependency_refs'].append(second if case == 'wrong_version' else historical)
        with pytest.raises(ActionRejected, match='REVIEW_(VERSION|TARGET)_OUTSIDE_SNAPSHOT'):
            cs.submit_review(reviewer, 'invalid-comparison', request, {})
        assert not cs.list_objects('ReviewRecord')


async def test_native_offload_keeps_source_data_deferred_and_exactly_recoverable(ws, monkeypatch):
    from report_agent.task_context import read_observation
    native = deep_runtime.FilesystemMiddleware
    def small_threshold(**kwargs):
        return native(**kwargs, tool_token_limit_before_evict=100)
    monkeypatch.setattr(deep_runtime, 'FilesystemMiddleware', small_threshold)
    seed(ws); activate(ws)
    literal = 'Exact located source material; ' * 2000 + 'TAIL CONDITION.'
    ws.store.set('manifest', {**ws.store.manifest, 'sources': [
        {'id': 's', 'title': 'Source', 'content': literal, 'coverage': 'partial'}]})
    with ws.store.connect() as db:
        db.execute('delete from source_blocks')
        db.execute('insert into source_blocks values (?,?,?,?)', ('s', 0, json.dumps({'page': 1}), literal))
    def inspect(messages):
        reply = next(m for m in reversed(messages) if isinstance(m, ToolMessage) and m.name == 'read_source_page')
        assert reply.additional_kwargs.get('report_controls_restored'), reply
        assert literal not in str(reply.content)
        controls = json.loads(reply.content[-1]['text'])
        assert not controls['complete_original_in_decision']
        assert controls['metadata']['blocks']['total_returned'] == 1
        ref = controls['observation_ref']
        recovered, offset = '', 0
        while True:
            page = read_observation(ws, 'coordinator', ref, offset)
            recovered += page['text']
            if page['next_offset'] is None:
                break
            offset = page['next_offset']
        original = json.loads(recovered)
        assert original['blocks'][0]['text'] == literal
        assert controls['metadata']['coverage_note'] == original['coverage_note']
        assert controls['sha256'] == hashlib.sha256(recovered.encode()).hexdigest()
        return AIMessage(content='Source remains partial; synthetic boundary check only.')
    driver = Driver(coordinator=[invoke('read_source_page', source_id='s', offset=0, limit=1), inspect])
    result = await deep_runtime.run_report(ws, driver)
    assert result['last_error'] is None, result


async def test_typed_rejection_is_not_erased_or_promoted_after_offload(ws):
    from langchain.agents import create_agent
    from deepagents.middleware.filesystem import FilesystemMiddleware
    from deepagents.backends import StateBackend
    seed(ws); activate(ws)
    error = {'ok': False, 'code': 'REQUIRED_MATERIAL_NOT_SUPPLIED', 'model_called': False,
             'message': 'Exact actionable rejection. ' * 100, 'retryable': False}
    def rejected_tool():
        """Return a deterministic typed rejection fixture."""
        return ToolMessage(content=json.dumps(error), name='rejected_tool',
                           tool_call_id='rejected_tool', status='error')
    def inspect(messages):
        reply = next(m for m in messages if isinstance(m, ToolMessage))
        assert reply.status == 'error' and reply.additional_kwargs['report_controls_restored']
        assert json.loads(reply.content[-1]['text'])['metadata'] == error
        return AIMessage(content='Rejection retained; no retry or success claim.')
    driver = Driver(coordinator=[invoke('rejected_tool'), inspect])
    graph = create_agent(driver('coordinator'), tools=[rejected_tool], middleware=[
        FilesystemMiddleware(backend=StateBackend(), tools=['read_file'], tool_token_limit_before_evict=100),
        TaskContext(ws, 'coordinator')])
    await graph.ainvoke({'messages': [{'role': 'user', 'content': 'Test typed error delivery.'}]})
    assert len(driver.calls) == 2


def test_explicit_heading_boundaries_preserve_cross_line_emphasis_links_and_numbering():
    doc = Document()
    body = '3. **Before\nheading\nAfter**\n4. Next\n\n[before\nLink heading\nafter](https://example.com)'
    emit_text(doc, body, None, [ParagraphLayout(text='heading', heading_level=2),
                              ParagraphLayout(text='Link heading', heading_level=2)])
    assert [p.text for p in doc.paragraphs] == ['Before', 'heading', 'After', 'Next',
                                              'before', 'Link heading', 'after (https://example.com)']
    assert all(r.bold for p in doc.paragraphs[:3] for r in p.runs if r.text)
    assert doc.paragraphs[1].style.name == doc.paragraphs[5].style.name == 'Heading 2'
    numbered = [p._p.pPr.numPr.numId.val for p in doc.paragraphs
                if p._p.pPr is not None and p._p.pPr.numPr is not None]
    assert len(numbered) == 2 and len(set(numbered)) == 1


@pytest.mark.parametrize('selected', [False, True])
async def test_native_offloaded_object_reads_keep_controls_without_reinlining_bodies(ws, monkeypatch, selected):
    from report_agent.task_context import read_observation
    from langchain_openai.chat_models.base import _convert_message_to_dict
    native = deep_runtime.FilesystemMiddleware
    monkeypatch.setattr(deep_runtime, 'FilesystemMiddleware',
        lambda **kwargs: native(**kwargs, tool_token_limit_before_evict=100))
    literal = 'Unchanged source/body content. ' * 400 + 'TAIL MUST BE RECOVERABLE.'
    ws.store.set('manifest', {**ws.store.manifest, 'sources': [
        {'id': 's', 'title': 'Source', 'content': literal, 'coverage': 'partial'}]})
    cs, actor, refs, _, members = seed(ws)
    node = cs.commit(actor, 'large-node', [{'client_key': 'node', 'type': 'ContentNode',
        'payload': {'kind': 'block', 'body': {'text': literal}, 'claim_kind': 'structure',
                    'qualifiers': {'warning': 'Exact unverified condition; ' * 60}}}])['result']['refs']['node']
    edge = cs.commit(actor, 'large-edge', [{'client_key': 'edge', 'type': 'Relation', 'payload': {
        'subject_ref': refs['root'], 'object_ref': node, 'predicate': 'contains', 'position': 1,
        'provenance_kind': 'adopted_during_generation'}}])['result']['refs']['edge']
    snapshot = cs.freeze(actor, 'large-snapshot', refs['root'], [*members, node, edge])['result']['snapshot_ref']
    activate(ws)
    tool = 'read_content_selection' if selected else 'read_context'
    args = {'snapshot_ref': snapshot, 'selections': [{'ref': node, 'limit': 16000}]} if selected else {
        'target_ref': snapshot, 'limit': 100}

    def inspect(messages):
        reply = next(m for m in reversed(messages) if isinstance(m, ToolMessage) and m.name == tool)
        assert reply.additional_kwargs['report_controls_restored']
        wire = _convert_message_to_dict(reply)
        assert literal not in json.dumps(wire)
        controls = json.loads(reply.content[-1]['text'])
        assert not controls['complete_original_in_decision']
        original = ws.store.get('tool_observation:' + controls['observation_ref'])
        assert hashlib.sha256(original['text'].encode()).hexdigest() == controls['sha256']
        raw = json.loads(original['text'])
        assert controls['metadata']['receipt_id'] == raw['receipt_id']
        assert 'not proof' in controls['note']
        paths = controls['platform_offloaded_data_paths']
        assert paths
        for path in paths:
            source = raw
            shown = controls['metadata']
            for key in path:
                source, shown = source[key], shown[key]
            assert shown['platform_deferred'] and shown['observation_path'] == path
            string_path = path + ['text'] if isinstance(source, dict) else path
            expected = source['text'] if isinstance(source, dict) else source
            recovered, offset = '', 0
            while True:
                page = read_observation(ws, 'coordinator', controls['observation_ref'],
                                        offset, field_path=string_path)
                recovered += page['text']
                if page['next_offset'] is None:
                    break
                offset = page['next_offset']
            assert recovered == expected
        data, original_data = controls['metadata']['result'], raw['result']
        if selected:
            assert {k:v for k,v in data['selections'][0].items() if k != 'body'} == {
                k:v for k,v in original_data['selections'][0].items() if k != 'body'}
        else:
            assert {k:v for k,v in data.items() if k != 'objects'} == {
                k:v for k,v in original_data.items() if k != 'objects'}
            for obj, original_obj in zip(data['objects'], original_data['objects'], strict=True):
                field = {'ContentNode': 'body', 'SourceArtifact': 'content'}.get(obj['ref']['type'])
                if field:
                    restored = deepcopy(obj)
                    restored['payload'][field] = original_obj['payload'][field]
                    assert restored == original_obj
                else:
                    assert obj == original_obj
        return AIMessage(content='Synthetic I/O verification only.')
    driver = Driver(coordinator=[invoke(tool, **args), inspect])
    result = await deep_runtime.run_report(ws, driver)
    assert result['last_error'] is None, result
    assert len(driver.calls) == 2


@pytest.mark.parametrize('page_read', [False, True])
async def test_native_page_and_saved_result_offload_preserves_limits_and_source_receipt(ws, monkeypatch, page_read):
    from test_ingestion import pdf_bytes
    from report_agent.task_context import read_observation
    from report_agent.decision_data import deliver_controls
    native = deep_runtime.FilesystemMiddleware
    monkeypatch.setattr(deep_runtime, 'FilesystemMiddleware',
        lambda **kwargs: native(**kwargs, tool_token_limit_before_evict=100))
    literal = 'Original only; ' * 400 + 'UNTRUNCATED TAIL'
    pdf = pdf_bytes([literal])
    (ws.store.root / 'sources').mkdir(exist_ok=True)
    (ws.store.root / 'sources/original.pdf').write_bytes(pdf)
    ws.store.set('manifest', {**ws.store.manifest, 'sources': [{
        'id': 's', 'title': 'Synthetic', 'filename': 'original.pdf', 'copied_path': 'sources/original.pdf',
        'sha256': hashlib.sha256(pdf).hexdigest(), 'content': literal, 'coverage': 'partial'}]})
    seed(ws); activate(ws)
    with ws.store.connect() as db:
        db.execute('delete from source_blocks')
        db.execute('insert into source_blocks values (?,?,?,?)', ('s', 0, 'page 1', literal))
    if page_read:
        tool, args, paths = 'inspect_source_page', {'source_id': 's', 'page': 1}, [
            ['native_text'], ['frozen_text_blocks', 0, 'text'], ['table_view', 'tables']]
    else:
        ws._seed('materials', 'Stored result', literal, ['s'])
        tool, args, paths = 'read_result', {'result_id': ws.results()[-1]['id']}, [['body']]

    def inspect(messages):
        reply = next(m for m in reversed(messages) if isinstance(m, ToolMessage) and m.name == tool)
        assert reply.status == 'success', reply.content
        assert reply.additional_kwargs['report_controls_restored']
        assert literal not in str(reply.content)
        assert deliver_controls(ws, 'coordinator', reply) is reply
        controls = json.loads(reply.content[-1]['text'])
        assert controls['complete_original_in_decision'] is False
        saved = ws.store.get('tool_observation:' + controls['observation_ref'])
        raw = json.loads(saved['text'])
        restored = deepcopy(controls['metadata'])
        assert controls['platform_offloaded_data_paths'] == paths
        assert reply.additional_kwargs['report_observation_delivery']['complete_tool_result'] is False
        assert reply.additional_kwargs['report_observation_delivery']['characters'] == len(reply.content[-1]['text'])
        for path in paths:
            original, projected = raw, restored
            for key in path[:-1]:
                original, projected = original[key], projected[key]
            assert projected[path[-1]]['observation_path'] == path
            projected[path[-1]] = original[path[-1]]
        assert restored == raw  # Includes all nested mechanical table warnings/status.
        if page_read:
            assert controls['source_material'] == reply.artifact['source_material']
            assert controls['metadata']['table_view']['status'] == 'no_tables_detected'
            assert controls['metadata']['frozen_text_blocks'][0]['locator'] == 'page 1'
        recovered = read_observation(ws, 'coordinator', controls['observation_ref'], field_path=paths[0])
        assert recovered['text'] == literal[:6000]
        return AIMessage(content='Synthetic page/result boundary verified.')
    result = await deep_runtime.run_report(ws, Driver(coordinator=[invoke(tool, **args), inspect]))
    if result['last_error'] is not None:
        diagnostic = ws.store.root / 'diagnostics/private' / (result['last_error']['diagnostic_id'] + '.json')
        pytest.fail(str(json.loads(diagnostic.read_text())['exceptions'][0]['frames'][-3:]))


@pytest.mark.parametrize('tool', ['read_source_page', 'search_sources'])
def test_offloaded_table_supplements_keep_all_page_failures_and_limitations(ws, tool):
    from report_agent.decision_data import deliver_controls
    seed(ws); activate(ws)
    table = {'page': 1, 'status': 'extracted', 'limitations': ['Geometric candidates, not verified facts.'],
        'tables': [{'rows': [[None, 'Actual cell']], 'nonempty_cell_bounds': [{'row': 1, 'column': 2}]}]}
    unavailable = {'page': 2, 'status': 'unavailable', 'error': 'SOURCE_TABLE_EXTRACTION_FAILED',
                   'limitations': ['No claim of absent information.']}
    original = {'source_table_views': [table, unavailable], 'next_offset': None, 'total_blocks': 1}
    reply = TaskContext(ws, 'coordinator').bound_result(ToolMessage(
        content=json.dumps(original), name=tool, tool_call_id='table'))
    offloaded = deliver_controls(ws, 'coordinator', reply.model_copy(update={'content': 'Native offload notice'}))
    controls = json.loads(offloaded.content[-1]['text'])
    views = controls['metadata']['source_table_views']
    assert views[1] == unavailable
    assert {k:v for k,v in views[0].items() if k != 'tables'} == {k:v for k,v in table.items() if k != 'tables'}
    assert views[0]['tables']['total_returned'] == 1
    assert views[0]['tables']['observation_path'] == ['source_table_views', 0, 'tables']
