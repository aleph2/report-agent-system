"""Native agents, real PDF/Office images, fake vision only; no visual verdict."""
import base64
import hashlib
import json

import pytest
from langchain_core.messages import AIMessage

from report_agent.content_export import export_snapshot
from report_agent.deep_runtime import run_report
from test_agent_duty_trace_cases import action, result_value, tool_reply
from test_bounded_review import review_call
from test_decision_data import activate
from test_deep_runtime import Driver, invoke
from test_hierarchical_content import seed
from test_ingestion import pdf_bytes
from test_task_supervision import ws, offline
from test_vision import VisionModel


@pytest.mark.parametrize('role', ['reviewer', 'layout'])
async def test_native_page_and_render_observations_keep_actual_images_and_extent(ws, monkeypatch, role, request):
    data = pdf_bytes(('Printed label 91; physical page 1.', 'Printed label 110; physical page 2.'))
    source_dir = ws.store.root / 'sources'
    source_dir.mkdir(exist_ok=True)
    original = source_dir / 'synthetic-reference.pdf'
    original.write_bytes(data)
    manifest = ws.store.manifest
    manifest['sources'][0].update(filename=original.name, copied_path='sources/' + original.name,
                                 sha256=hashlib.sha256(data).hexdigest())
    ws.store.set('manifest', manifest)
    activate(ws)
    cs, owner, refs, snapshot, _ = seed(ws)
    before = cs.read(snapshot), cs.read(refs['claim']), original.read_bytes()
    exported = export_snapshot(cs, owner, 'fixture-word', snapshot)['result']
    export_ref = exported['export_ref']
    service = VisionModel(content='Synthetic image observation only; unseen pages and engineering status are unverified.')
    monkeypatch.setattr('report_agent.vision.configured_vision_client', lambda: service)
    monkeypatch.setattr('report_agent.deep_models.configured_vision_client', lambda: service)
    observed = {}

    def render(messages):
        value = result_value(tool_reply(messages, 'source-page'))
        assert value['status'] == 'observed', value
        assert value['source']['page'] == 2
        assert value['source']['source_id'] == 's'
        assert value['source']['source_sha256'] == hashlib.sha256(data).hexdigest()
        observed['source'] = value
        return action('render_content_export', 'render-word', operation_id='native-render', export_ref=export_ref)

    def inspect(messages):
        value = result_value(tool_reply(messages, 'render-word'))
        assert value['ok'] is True, value
        rendered = value['result']
        # Missing local Office is an explicit environment gap, not a fake pass.
        assert rendered['execution_state'] == 'completed', rendered
        record = cs.read(rendered['render_ref'])
        assert record['payload']['export_ref'] == export_ref
        assert record['payload']['export_digest'] == cs.read(export_ref)['payload']['file_digest']
        assert record['payload']['renderer_identity']['binary_digest']
        asset = record['payload']['page_assets'][0]
        png = (ws.store.root / asset['asset_ref']).read_bytes()
        assert hashlib.sha256(png).hexdigest() == asset['sha256']
        assert png.startswith(b'\x89PNG')
        observed['render'] = rendered
        return action('inspect_rendered_page', 'full-page', render_ref=rendered['render_ref'], page=1,
                      question='Describe this physical page only; no acceptance verdict.')

    def repeat(messages):
        value = result_value(tool_reply(messages, 'full-page'))
        result = value['result']
        assert result['status'] == 'observed', result
        assert result['source']['export_ref'] == export_ref
        assert result['source']['render_ref'] == observed['render']['render_ref']
        assert result['source']['coverage'] == 'full_page_image'
        assert result['source']['crop'] is None
        assert len(service.calls) == 2
        observed['full_page'] = value
        return action('inspect_rendered_page', 'same-page', render_ref=observed['render']['render_ref'], page=1,
                      question='Describe this physical page only; no acceptance verdict.')

    def crop(messages):
        value = result_value(tool_reply(messages, 'same-page'))['result']
        assert value['reused'] is True
        assert len(service.calls) == 2
        return action('inspect_rendered_page', 'cropped-page', render_ref=observed['render']['render_ref'], page=1,
                      question='Describe this physical page only; no acceptance verdict.', crop=[0, 0, .5, .5])

    def invalid_page(messages):
        value = result_value(tool_reply(messages, 'cropped-page'))
        result = value['result']
        assert result['status'] == 'observed' and result['reused'] is False
        assert result['source']['coverage'] == 'region_only'
        assert result['source']['crop'] == [0, 0, .5, .5]
        assert result['image_sha256'] != observed['full_page']['result']['image_sha256']
        assert len(service.calls) == 3
        observed['crop'] = value
        return action('inspect_rendered_page', 'outside-page', render_ref=observed['render']['render_ref'], page=999,
                      question='Read this page.')

    def finish(messages):
        value = result_value(tool_reply(messages, 'outside-page'))
        assert value['ok'] is False and value['code'] == 'PAGE_OUT_OF_RANGE', value
        assert len(service.calls) == 3
        observed['rejected_page'] = value
        return AIMessage(content='Observed selected images only. No full-document review or acceptance.')

    args = {'subagent_type': role, 'description': 'Inspect the selected original physical page and generated Word only.'}
    if role == 'layout':
        args['layout_snapshot_ref'] = snapshot
    else:
        args = {**review_call(snapshot, refs)['args'], 'description': args['description']}
        args.pop('supervision_plugin', None)
    driver = Driver(coordinator=[invoke('task', **args), AIMessage(content='Limited image observations received.')],
                    **{role: [action('analyze_source_image', 'source-page', source_id='s', page=2,
                                     question='Read only physical page 2; printed labels are not page indexes.'),
                              render, inspect, repeat, crop, invalid_page, finish]})
    result = await run_report(ws, driver)
    assert result['last_error'] is None, result
    image_hashes = []
    for call in service.calls:
        blocks = call['messages'][1]['content']
        url = next(block['image_url']['url'] for block in blocks if block['type'] == 'image_url')
        image_hashes.append(hashlib.sha256(base64.b64decode(url.split(',', 1)[1])).hexdigest())
    assert image_hashes == [observed['source']['image_sha256'],
                            observed['full_page']['result']['image_sha256'],
                            observed['crop']['result']['image_sha256']]
    assert before == (cs.read(snapshot), cs.read(refs['claim']), original.read_bytes())
    assert not cs.list_objects('ReviewRecord')
    request.node.user_properties.append(('trace_case', json.dumps({
        'case': 'TC05', 'role': role, 'observed': observed, 'actual_image_hashes': image_hashes,
        'office_conversion_mocked': False, 'image_loader_mocked': False,
        'fake_vision_responses': 3, 'paid_calls': 0, 'visual_correctness_proven': False})))


async def test_native_layout_adjustment_generates_new_render_without_relabelling_old_observation(ws, monkeypatch, request):
    from io import BytesIO
    from docx import Document
    from report_agent.content_export import render_export

    cs, owner, refs, snapshot, _ = seed(ws)
    activate(ws)
    content_before = cs.read(snapshot), cs.read(refs['claim'])
    old_export = export_snapshot(cs, owner, 'old-word', snapshot,
        layout={'toc': False, 'right_margin_mm': 15,
                'styles': [{'name': 'Normal', 'font_size': 12}]})['result']
    old_render = render_export(cs, owner, 'old-render', old_export['export_ref'])['result']
    assert old_render['execution_state'] == 'completed', old_render
    original_docx = (ws.store.root / old_export['file_ref']).read_bytes()
    old_doc = Document(BytesIO(original_docx))
    service = VisionModel(content='Synthetic observation of only this attached image; no layout verdict.')
    monkeypatch.setattr('report_agent.deep_models.configured_vision_client', lambda: service)
    observed = {}
    question = 'Inspect this actual generated page only.'

    def choose_adjustment(messages):
        value = result_value(tool_reply(messages, 'inspect-old'))['result']
        assert value['source']['export_ref'] == old_export['export_ref']
        assert value['source']['render_ref'] == old_render['render_ref']
        observed['old'] = value
        return action('export_content_snapshot', 'adjust-layout', operation_id='adjust-layout', snapshot_ref=snapshot,
                      layout={'toc': False, 'right_margin_mm': 20,
                              'styles': [{'name': 'Normal', 'font_size': 20}]})

    def render_adjusted(messages):
        value = result_value(tool_reply(messages, 'adjust-layout'))
        assert value['ok'] is True, value
        current = value['result']
        assert current['export_ref'] != old_export['export_ref']
        doc = Document(BytesIO((ws.store.root / current['file_ref']).read_bytes()))
        assert abs(doc.sections[0].right_margin.mm - 20) < .05
        assert doc.styles['Normal'].font.size.pt == 20
        assert abs(old_doc.sections[0].right_margin.mm - 15) < .05
        assert old_doc.styles['Normal'].font.size.pt == 12
        assert [p.text for p in doc.paragraphs] == [p.text for p in old_doc.paragraphs]
        assert cs.read(current['export_ref'])['payload']['snapshot_ref'] == snapshot
        observed['new_export'] = current
        return action('render_content_export', 'render-adjusted', operation_id='render-adjusted',
                      export_ref=current['export_ref'])

    def inspect_adjusted(messages):
        value = result_value(tool_reply(messages, 'render-adjusted'))
        assert value['ok'] is True, value
        current = value['result']
        assert current['execution_state'] == 'completed', current
        assert current['render_ref'] != old_render['render_ref']
        render_payload = cs.read(current['render_ref'])['payload']
        assert render_payload['export_ref'] == observed['new_export']['export_ref']
        assert render_payload['export_digest'] == cs.read(observed['new_export']['export_ref'])['payload']['file_digest']
        observed['new_render'] = current
        return action('inspect_rendered_page', 'inspect-adjusted', render_ref=current['render_ref'], page=1, question=question)

    def historical_read(messages):
        value = result_value(tool_reply(messages, 'inspect-adjusted'))['result']
        assert value['source']['export_ref'] == observed['new_export']['export_ref']
        assert value['source']['render_ref'] == observed['new_render']['render_ref']
        assert value['reused'] is False
        assert len(service.calls) == 2
        observed['new'] = value
        return action('inspect_rendered_page', 'read-old-again', render_ref=old_render['render_ref'], page=1, question=question)

    def finish(messages):
        value = result_value(tool_reply(messages, 'read-old-again'))['result']
        assert value['reused'] is True and len(service.calls) == 2
        assert value['source']['export_ref'] == old_export['export_ref']
        assert value['source']['render_ref'] == old_render['render_ref']
        assert value['image_sha256'] == observed['old']['image_sha256']
        observed['historical_read'] = value
        return AIMessage(content='New parameters exported and observed; old observation remains historical. No visual acceptance.')

    driver = Driver(coordinator=[invoke('task', subagent_type='layout', layout_snapshot_ref=snapshot,
                   description='Change right margin to20mm and Normal font to20pt; keep all report content unchanged.'),
                   AIMessage(content='Adjusted export received; independent acceptance pending.')],
                   layout=[action('inspect_rendered_page', 'inspect-old', render_ref=old_render['render_ref'], page=1, question=question),
                           choose_adjustment, render_adjusted, inspect_adjusted, historical_read, finish])
    result = await run_report(ws, driver)
    assert result['last_error'] is None, result
    for index, key in enumerate(['old', 'new']):
        blocks = service.calls[index]['messages'][1]['content']
        url = next(block['image_url']['url'] for block in blocks if block['type'] == 'image_url')
        assert hashlib.sha256(base64.b64decode(url.split(',', 1)[1])).hexdigest() == observed[key]['image_sha256']
    assert observed['old']['image_sha256'] != observed['new']['image_sha256']
    assert (ws.store.root / old_export['file_ref']).read_bytes() == original_docx
    assert content_before == (cs.read(snapshot), cs.read(refs['claim']))
    assert not cs.list_objects('ReviewRecord')
    request.node.user_properties.append(('trace_case', json.dumps({
        'case': 'TC05-L6-adjust-observe', 'observed': observed,
        'parameters_changed': {'right_margin_mm': [15, 20], 'Normal.font_size': [12, 20]},
        'office_conversion_mocked': False, 'model_chose_adjustment': False,
        'visual_correctness_proven': False, 'paid_calls': 0})))


def p12_two_version_artifacts(ws):
    """Actual two-page files; only second table gains its missing fourth column."""
    from copy import deepcopy
    from report_agent.content_export import render_export
    cs, owner, refs, _, members = seed(ws)
    created = cs.commit(owner, 'p12-pages', [
        {'client_key': 'one', 'type': 'ContentNode', 'payload': {'kind': 'table',
         'body': {'columns': ['Indicator', 'Class', 'Score', 'Note'], 'rows': [['PAGE-ONE', 'B', '75', 'UNCHANGED']]},
         'qualifiers': {}, 'claim_kind': 'structure'}},
        {'client_key': 'two', 'type': 'ContentNode', 'payload': {'kind': 'table',
         'body': {'columns': ['Indicator', 'Class', 'Score'], 'rows': [['PAGE-TWO', 'B', '75']]},
         'qualifiers': {}, 'claim_kind': 'structure'}},
        *[{'client_key': key + '_edge', 'type': 'Relation', 'payload': {'subject_ref': refs['root'],
          'object_ref': {'client_key': key}, 'predicate': 'contains', 'position': position,
          'provenance_kind': 'adopted_during_generation'}} for key, position in [('one', 1), ('two', 2)]]
        ])['result']['refs']
    old = cs.freeze(owner, 'p12-old-snapshot', refs['root'], members + list(created.values()))['result']['snapshot_ref']
    second = cs.commit(owner, 'p12-page-two-v2', [
        {'client_key': 'two', 'type': 'ContentNode', 'previous_ref': created['two'],
         'payload': {**cs.read(created['two'])['payload'], 'body': {'columns': ['Indicator', 'Class', 'Score', 'Note'],
         'rows': [['PAGE-TWO', 'B', '75', 'NEW-FOURTH-COLUMN']]}}},
        {'client_key': 'edge', 'type': 'Relation', 'previous_ref': created['two_edge'],
         'payload': {**cs.read(created['two_edge'])['payload'], 'object_ref': {'client_key': 'two'}}}])['result']['refs']
    new = cs.derive_snapshot(owner, 'p12-new-snapshot', old, [], [
        {'previous_ref': created['two'], 'new_ref': second['two']},
        {'previous_ref': created['two_edge'], 'new_ref': second['edge']}])['result']['snapshot_ref']
    saved = {'old_snapshot': old, 'new_snapshot': new}
    for label, snap, node in [('old', old, created['two']), ('new', new, second['two'])]:
        exported = export_snapshot(cs, owner, 'p12-' + label + '-word', snap,
            {'toc': False, 'nodes': [{'node_ref': node, 'page_break_before': True}]})['result']
        rendered = render_export(cs, owner, 'p12-' + label + '-render', exported['export_ref'])['result']
        assert rendered['execution_state'] == 'completed', {'environment_or_render_gap': rendered}
        payload = cs.read(rendered['render_ref'])['payload']
        assert len(payload['page_assets']) == 2, 'Two-page synthetic fixture precondition failed.'
        saved[label] = {'export': exported, 'render': rendered, 'render_payload': payload}
    assert saved['old']['render_payload']['page_assets'][1]['sha256'] != saved['new']['render_payload']['page_assets'][1]['sha256']
    return cs, refs, saved


@pytest.mark.parametrize('variant', ['full_current', 'partial_page1', 'old_page2', 'crop_page2', 'wrong_page1', 'foreign_owner'])
async def test_p12_native_reviewer_artifact_judgment_keeps_actual_page_extent(ws, monkeypatch, request, variant):
    """Fake vision/checker, real native observations/publication/parent receipt."""
    from copy import deepcopy
    from test_artifact_review import payload as artifact_payload
    from test_agent_duty_repro_artifacts import save_evidence
    from report_agent.task_supervision import reconcile
    cs, refs, actual = p12_two_version_artifacts(ws)
    ws.store.set('manifest', {**ws.store.manifest, 'review_execution_mode': 'bounded-tool-v1'})
    activate(ws)
    snapshot = actual['new_snapshot']
    render = actual['new']['render']['render_ref']
    old_render = actual['old']['render']['render_ref']
    old_bytes = (ws.store.root / actual['old']['export']['file_ref']).read_bytes()
    service = VisionModel(content='Public synthetic visual observation. This receipt covers only its exact attached page/region; no engineering verdict.')
    monkeypatch.setattr('report_agent.deep_models.configured_vision_client', lambda: service)
    foreign = None
    if variant == 'foreign_owner':
        from report_agent.content_store import Actor
        from report_agent.content_export import inspect_render
        foreign = await inspect_render(cs, Actor('p12:foreign-reviewer', 'reviewer', 'p12:foreign-task'),
            render, 2, 'Observe only this attached physical page.', client=service)
    call = review_call(snapshot, refs, 'p12-review')
    call['args'].pop('supervision_plugin', None)
    req = call['args']['review_requirements'][0]
    req.update(assessment_kind='render', artifact_refs=[render], required_materials=[{
        'requirement_index': 0, 'purpose': 'Compare the declared content against both current physical pages.',
        'refs': [refs['claim']]}])
    receipts, observed = [], {'case': 'P12', 'variant': variant, 'artifacts': actual, 'observations': [], 'assets': []}
    for label in ('old', 'new'):
        value = actual[label]
        observed['assets'] += [{'file_ref': value['export']['file_ref'], 'kind': 'docx'},
                              {'file_ref': value['render_payload']['pdf_ref'], 'kind': 'pdf'}]
        observed['assets'] += [{'file_ref': p['asset_ref'], 'kind': 'png'} for p in value['render_payload']['page_assets']]

    def read_material(messages):
        value = result_value(tool_reply(messages, 'material'))
        assert value['ok'], value
        receipts.append(value['receipt_id'])
        observed['observations'].append(value['result'])
        return action('inspect_rendered_page', 'page-one', render_ref=render, page=1,
                      question='Observe only this attached physical page.')

    def second(messages):
        envelope = result_value(tool_reply(messages, 'page-one'))
        value = envelope['result']
        assert value['source']['render_ref'] == render and value['source']['page'] == 1
        receipts.append(envelope['receipt_id'])
        observed['observations'].append(value)
        if variant == 'partial_page1':
            return action('perform_assigned_artifact_review', 'compare', operation_id='p12-compare',
                          scope_ids=['rule-comparison'], observation_receipts=receipts)
        args = {'render_ref': old_render if variant == 'old_page2' else render,
                'page': 1 if variant == 'wrong_page1' else 2, 'question': 'Observe only this attached physical page.'}
        if variant == 'crop_page2':
            args['crop'] = [0, 0, .5, .5]
        return action('inspect_rendered_page', 'page-two', **args)

    def compare(messages):
        envelope = result_value(tool_reply(messages, 'page-two'))
        value = envelope['result']
        expected_render = old_render if variant == 'old_page2' else render
        assert value['source']['render_ref'] == expected_render
        assert value['source']['export_ref'] == actual['old' if variant == 'old_page2' else 'new']['export']['export_ref']
        assert value['source']['page'] == (1 if variant == 'wrong_page1' else 2)
        assert value['source']['coverage'] == ('region_only' if variant == 'crop_page2' else 'full_page_image')
        receipts.append(foreign['receipt_id'] if foreign is not None else envelope['receipt_id'])
        observed['observations'].append(foreign['result'] if foreign is not None else value)
        return action('perform_assigned_artifact_review', 'compare', operation_id='p12-compare',
                      scope_ids=['rule-comparison'], observation_receipts=receipts)

    def checker(messages):
        packet = json.loads(messages[-1].content)
        observed['checker_packet'] = packet
        assert packet['requirements'][0]['artifact_refs'] == [render]
        assert [e['receipt_id'] for e in packet['evidence']] == receipts
        for evidence, expected in zip(packet['evidence'], observed['observations'], strict=True):
            assert evidence['actual_observation'] == expected
        result = artifact_payload(snapshot, refs, render, receipts, complete=variant != 'partial_page1').model_dump()
        item = result['items'][0]
        item['reason'] = 'PUBLIC-REASON: selected pages compared; no whole-report engineering conclusion.'
        item['observations'][0]['limitations'] = 'PUBLIC-LIMIT: original source facts were not revalidated.'
        item['findings'] = [{'finding_type': 'unresolved', 'locator_state': 'located',
            'description': 'PUBLIC-FINDING: interpretation remains unconfirmed.', 'impact': 'PUBLIC-IMPACT: scoped draft only.',
            'needed_outcome': 'PUBLIC-NEED: independent technical review.', 'basis_kind': None,
            'observation_indexes': None, 'requirement_index': None}]
        if variant == 'partial_page1':
            item['coverage']['unchecked'] = ['PUBLIC-UNCHECKED: current physical page 2']
            item['checked_requirement_indexes'] = []
            item['check_results'] = [{'requirement_index': 0, 'execution_state': 'partial',
                'result': 'PUBLIC-RESULT: page1 observation only.', 'observation_indexes': [0],
                'remaining': 'PUBLIC-REMAINING: inspect current page2.'}]
        else:
            item['verdict'] = 'not_satisfied'
            item['checked_requirement_indexes'] = [0]
            item['check_results'] = [{'requirement_index': 0, 'execution_state': 'completed',
                'result': 'PUBLIC-RESULT: synthetic comparison completed, not satisfied.',
                'observation_indexes': list(range(len(receipts))), 'remaining': ''}]
        observed['checker_public_output'] = deepcopy(result)
        return AIMessage(content=json.dumps(result))

    def child_finish(messages):
        value = result_value(tool_reply(messages, 'compare'))
        observed['child_return'] = value
        if variant in {'old_page2', 'crop_page2', 'wrong_page1', 'foreign_owner'}:
            expected_code = 'ARTIFACT_OBSERVATION_REQUIRES_CURRENT_TASK_RECEIPT' if variant == 'foreign_owner' else 'ARTIFACT_REVIEW_COVERAGE_INCOMPLETE'
            assert value['ok'] is False and value['code'] == expected_code, value
            assert not cs.list_objects('ReviewRecord')
        else:
            assert value['ok'] is True, value
            saved = cs.read(value['result']['review_ref'])['payload']
            expected = observed['checker_public_output']['items'][0]
            got = value['review']['items'][0]
            for field in ('reason', 'observations', 'coverage', 'findings', 'check_results', 'verdict', 'execution_state'):
                assert got[field] == saved['items'][0][field] == expected[field], (field, got[field], expected[field])
            status = reconcile(cs, value['review_identity']['task_id'])
            observed['reconcile'] = status
            assert status['execution_complete'] is (variant == 'full_current')
        return AIMessage(content=json.dumps(value, ensure_ascii=False))

    def parent(messages):
        value = result_value(tool_reply(messages, 'p12-review'))
        observed['parent_return'] = value
        text = json.dumps(value, ensure_ascii=False)
        if variant in {'full_current', 'partial_page1'}:
            for marker in ('PUBLIC-REASON', 'PUBLIC-LIMIT', 'PUBLIC-FINDING', 'PUBLIC-RESULT'):
                assert marker in text
            if variant == 'partial_page1':
                assert 'PUBLIC-REMAINING' in text and 'PUBLIC-UNCHECKED' in text
        return AIMessage(content='Bounded artifact result received with exact remaining work and limitations.')
    steps = [action('read_context', 'material', target_ref=refs['claim']), read_material, second]
    if variant != 'partial_page1':
        steps.append(compare)
    steps.append(child_finish)
    driver = Driver(coordinator=[AIMessage(content='', tool_calls=[call]), parent], reviewer=steps, text_tool=[checker])
    result = await run_report(ws, driver)
    observed['runtime_result'] = result
    observed['fake_vision_calls'] = len(service.calls)
    observed['original_old_word_preserved'] = (ws.store.root / actual['old']['export']['file_ref']).read_bytes() == old_bytes
    save_evidence(request, ws, observed, driver)
    assert result['last_error'] is None, result
    assert ('checker_packet' in observed) is (variant != 'foreign_owner')
    assert 'child_return' in observed and observed['fake_vision_calls'] > 0
    image_hashes = []
    for actual_call in service.calls:
        blocks = actual_call['messages'][1]['content']
        url = next(b['image_url']['url'] for b in blocks if b['type'] == 'image_url')
        image_hashes.append(hashlib.sha256(base64.b64decode(url.split(',', 1)[1])).hexdigest())
    for observation in observed['observations']:
        if 'image_sha256' in observation:
            assert observation['image_sha256'] in image_hashes
    assert observed['original_old_word_preserved']


@pytest.mark.parametrize('field', ['remaining', 'limitations'])
async def test_p12_public_judgment_loss_is_detected_by_original_oracle(ws, monkeypatch, request, field):
    """Single-field output mutation only in this test process, after real save."""
    from copy import deepcopy
    from functools import wraps
    from report_agent import artifact_review
    original_factory = artifact_review.bounded_artifact_review_tool
    injected = []
    def altered_factory(workspace, model):
        original = original_factory(workspace, model)
        @wraps(original)
        async def altered(*args, **kwargs):
            returned = await original(*args, **kwargs)
            result = deepcopy(returned)
            item = result['review']['items'][0]
            target = item['check_results'][0] if field == 'remaining' else item['observations'][0]
            assert target[field], 'Mutation precondition: actual successful public result has this field.'
            injected.append({'field': field, 'old': target[field], 'review_ref': result['result']['review_ref']})
            target[field] = ''
            return result
        return altered
    monkeypatch.setattr(artifact_review, 'bounded_artifact_review_tool', altered_factory)
    import traceback
    original_respond = Driver.respond
    assertions = []
    async def capture_assertion(driver, role, messages):
        try:
            return await original_respond(driver, role, messages)
        except AssertionError as exc:
            frames = traceback.extract_tb(exc.__traceback__)
            cursor, compared_field = exc.__traceback__, None
            while cursor is not None:
                if cursor.tb_frame.f_code.co_name == 'child_finish':
                    compared_field = cursor.tb_frame.f_locals.get('field')
                cursor = cursor.tb_next
            assertions.append({'role': role, 'args': repr(exc.args),
                'compared_field': compared_field,
                'frames': [{'file': f.filename, 'line': f.lineno, 'function': f.name, 'expression': f.line} for f in frames]})
            raise
    monkeypatch.setattr(Driver, 'respond', capture_assertion)
    with pytest.raises(AssertionError):
        await test_p12_native_reviewer_artifact_judgment_keeps_actual_page_extent(ws, monkeypatch, request, 'partial_page1')
    assert len(injected) == 1, 'A setup/fixture failure must not count as sensitivity.'
    expected_field = 'check_results' if field == 'remaining' else 'observations'
    exact_failure = [a for a in assertions if a['role'] == 'reviewer' and a['compared_field'] == expected_field
        and any(f['function'] == 'child_finish' and 'assert got[field]' in (f['expression'] or '') for f in a['frames'])]
    assert len(exact_failure) == 1, assertions
    request.node.user_properties.append(('original_oracle_assertion', json.dumps({'mutation': field, 'failure': exact_failure[0]})))
    from report_agent.content_store import ContentStore
    saved = ContentStore(ws.store).read(injected[0]['review_ref'])['payload']['items'][0]
    target = saved['check_results'][0] if field == 'remaining' else saved['observations'][0]
    assert target[field] == injected[0]['old'], 'Only public output was mutated; saved original must remain intact.'
    request.node.user_properties.append(('controlled_public_mutation', json.dumps(injected)))


@pytest.mark.parametrize('case', ['layout-standard', 'layout-old-reference'])
async def test_r3_layout_packet_capture_uses_native_read_results(ws, request, case):
    import os
    from pathlib import Path
    from duty_probe_visual_packets import capture_layout, LAYOUT_STANDARD
    folder = Path(os.environ.get('REPORT_ARTIFACT_REPRO_OUT', str(ws.store.root))) / ('r3-' + case)
    result = await capture_layout(ws, case, folder)
    native = result['observations']['native_tool_results']
    names = [r['tool'] for r in native]
    assert 'read_layout_capabilities' in names and names.count('read_context') == (3 if case.endswith('reference') else 2)
    assert result['observations']['standard_original']['payload']['body']['text'] == LAYOUT_STANDARD
    assert result['messages'][-1].type == 'tool'
    assert any(t['function']['name'] == 'export_content_snapshot' for t in result['tools'])
    assert result['observations']['old_reference'] is not None if case.endswith('reference') else result['observations']['old_reference'] is None
    request.node.user_properties.append(('r3_probe_preflight', json.dumps({'case': case, 'folder': str(folder), 'paid_calls': 0})))


async def test_r3_real_image_then_bounded_artifact_helper_offline_preflight(ws, request):
    import os
    from pathlib import Path
    from duty_probe_visual_packets import prepare_visual, perform_visual_and_artifact
    folder = Path(os.environ.get('REPORT_ARTIFACT_REPRO_OUT', str(ws.store.root))) / 'r3-visual'
    prepared = await prepare_visual(ws, folder)
    class FakeArtifactModel:
        model_name = 'offline-artifact-contract-preflight'
        def __init__(self):
            self.calls = []
        async def ainvoke(self, messages):
            self.calls.append(messages)
            last = messages[-1]
            packet = json.loads(last.content if hasattr(last, 'content') else last[1])
            receipts = [e['receipt_id'] for e in packet['evidence']]
            assert len(receipts) == 3
            assert packet['evidence'][2]['actual_observation']['source']['render_ref'] == prepared['render_ref']
            result = {'snapshot_ref': prepared['snapshot'], 'target_ref': prepared['snapshot'],
                'scope': 'Single synthetic page only', 'criteria_refs': [prepared['refs']['criterion']],
                'dependency_refs': [prepared['refs']['standard_source']], 'items': [{
                    'target_ref': prepared['refs']['table'], 'criterion_ref': prepared['refs']['criterion'],
                    'scope': 'Single page', 'scope_id': 'r3-visible-table', 'assessment_kind': 'render',
                    'artifact_refs': [prepared['render_ref']], 'execution_state': 'completed', 'verdict': 'not_satisfied',
                    'checked_requirement_indexes': [0, 1],
                    'observations': [{'locator': str(i), 'observation': 'Synthetic comparison based on this exact receipt.',
                        'receipt_id': r, 'limitations': 'Fake observation does not validate vision semantics.'} for i, r in enumerate(receipts)],
                    'check_results': [{'requirement_index': i, 'execution_state': 'completed',
                        'result': '70 differs from 75.' if i == 0 else 'Note column absent.',
                        'observation_indexes': [0, 1, 2], 'remaining': ''} for i in range(2)],
                    'coverage': {'checked': ['score', 'columns'], 'unchecked': [], 'blocked': [], 'basis': 'Exact source and actual page receipt.'},
                    'reason': 'Two synthetic discrepancies remain; no engineering acceptance.', 'findings': []}],
                'delivery_checks': [], 'coverage_accounting': []}
            return AIMessage(content=json.dumps(result))
    vision = VisionModel(content='Displayed rule says Class B uses 75. Table columns are Indicator, Class, Score; row TEST-OBJECT/B/70. No Note column is visible. Synthetic observation only.')
    model = FakeArtifactModel()
    result = await perform_visual_and_artifact(ws, prepared, folder, vision_client=vision, artifact_model=model)
    assert len(vision.calls) == len(model.calls) == 1
    assert result['artifact_check_completed'] is True and result['engineering_acceptance'] is False
    assert result['saved_review']['payload']['items'][0]['verdict'] == 'not_satisfied'
    assert result['saved_review']['owner_id'] == result['actor']['id']
    with ws.store.connect() as db:
        owners = [db.execute('SELECT actor_id FROM content_observations WHERE id=?', (r,)).fetchone()[0] for r in result['receipts']]
    assert owners == [result['actor']['id']] * 3
    blocks = vision.calls[0]['messages'][1]['content']
    url = next(b['image_url']['url'] for b in blocks if b['type'] == 'image_url')
    digest = hashlib.sha256(base64.b64decode(url.split(',', 1)[1])).hexdigest()
    assert digest == result['vision']['result']['image_sha256']
    assert digest == prepared['cs'].read(prepared['render_ref'])['payload']['page_assets'][0]['sha256']
    request.node.user_properties.append(('r3_probe_preflight', json.dumps({'folder': str(folder), 'vision_fake_calls': 1, 'artifact_fake_calls': 1, 'paid_calls': 0})))
