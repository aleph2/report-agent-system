"""Current render facts reach the model; old previews/receipts remain historical."""
import json

import httpx
import pytest

from report_agent.content_export import export_snapshot, read_export, render_export
from report_agent.deep_models import GLMChatOpenAI, model_async_client
from report_agent.deep_runtime import run_report
from report_agent.workspace import Workspace
from report_agent.store import digest, encode
from test_deliverable_declaration_v4 import case
from test_deliverable_recovery_v4 import declaration, resolve
from test_prompt_native_sdk_inputs import completion
from test_render_transaction import pdf_bytes


def saved_export(case):
    cs, co, writer, _, _ = case
    declaration(case)
    snapshot = resolve(cs, writer, 'bind', {'kind': 'deliverable', 'operation_id': 'published'})
    return export_snapshot(cs, co, 'export', snapshot)['result']['export_ref']


def test_current_read_reports_no_attempt_and_no_capability_probe(case):
    cs, co, *_ = case
    ref = saved_export(case)
    original = cs.read(ref)
    result = read_export(cs, co, ref)['result']
    state = result['structure']['render']
    assert state['status'] == state['execution_state'] == 'not_attempted'
    assert state['capability_state'] == 'not_probed'
    assert state['page_count'] is None and state['visual_verification'] == 'not_performed'
    assert 'a-body' in result['text'] and cs.read(ref) == original
    assert cs.list_objects('RenderArtifact') == []


@pytest.mark.parametrize('diagnostic,execution,capability', [
    ({'code': 'RENDER_UNAVAILABLE', 'attempts': []}, 'blocked', 'unavailable'),
    ({'code': 'RENDER_UNAVAILABLE', 'attempts': [{'code': 'PDF_NOT_PRODUCED'}]}, 'failed', 'unknown'),
    ({'code': 'RENDER_UNAVAILABLE'}, 'blocked', 'unknown'),
    ({'attempts': []}, 'blocked', 'unknown'),
    ({'code': 'RENDER_UNAVAILABLE', 'attempts': None}, 'blocked', 'unknown'),
])
def test_failed_attempt_is_not_an_unsupported_environment(case, monkeypatch, diagnostic, execution, capability):
    cs, co, *_ = case
    ref = saved_export(case)
    monkeypatch.setattr('report_agent.office_render.convert_pdf', lambda *args: (None, diagnostic))
    result = render_export(cs, co, 'render', ref)
    # Tool-level blockage and renderer attempt facts are different dimensions.
    assert result['result']['execution_state'] == 'blocked'
    assert result['result']['render_state'] == {
        'execution_state': execution, 'capability_state': capability}
    assert cs.list_objects('RenderArtifact') == []
    assert render_export(cs, co, 'render', ref) == result


def test_success_means_rendered_not_visually_verified(case, monkeypatch):
    cs, co, *_ = case
    ref = saved_export(case)
    monkeypatch.setattr('report_agent.office_render.convert_pdf', lambda *args: (pdf_bytes(), {'engine': 'synthetic'}))
    result = render_export(cs, co, 'render', ref)['result']
    assert result['execution_state'] == 'completed' and result['verdict'] is None
    assert result['render_state'] == {'execution_state': 'completed', 'capability_state': 'available'}
    assert len(result['pages']) == 1


@pytest.mark.parametrize('mutate_manifest', [False, True])
async def test_actual_sdk_receives_one_consistent_preview_state(case, mutate_manifest):
    cs, _, *_ = case
    ref = saved_export(case)
    models, requests = {}, []

    def factory(role):
        if role in models:
            return models[role]
        client = model_async_client(cs.store, role)

        def transport(request):
            body = json.loads(request.content)
            requests.append(body)
            if mutate_manifest and len(requests) == 1:
                cs.store.set('manifest', {**cs.store.manifest, 'review_interface_profile': 'review-interfaces-v1'})
            return completion(request, 'Synthetic limited result; no whole-report pass.',
                ('read_content_export', {'export_ref': ref}) if len(requests) == 1 else None)

        client._transport = httpx.MockTransport(transport)
        client._mounts.clear()
        models[role] = GLMChatOpenAI(model='glm-5.3', api_key='fixture-only',
            base_url='https://fixture.invalid/v1', use_responses_api=False,
            http_async_client=client, max_retries=0, disable_streaming=True)
        return models[role]

    try:
        result = await run_report(Workspace(cs.store), factory)
        assert result['last_error'] is None, result
        returns = [m['content'] for m in requests[-1]['messages'] if m['role'] == 'tool']
        preview = next(json.loads(text) for text in returns if 'file_digest' in text)
        facts = preview['result']['structure']['render']
        assert facts['status'] == facts['execution_state'] == 'not_attempted'
        assert facts['capability_state'] == 'not_probed'
        assert 'render_unavailable' not in json.dumps(preview)
    finally:
        for model in models.values():
            await model.root_async_client.close()
            model.root_client.close()


def test_current_profile_replays_old_render_receipt_without_rewriting_it(case, monkeypatch):
    cs, co, *_ = case
    ref = saved_export(case)
    old = {'ok': True, 'result': {'execution_state': 'blocked', 'code': 'RENDER_UNAVAILABLE'}, 'receipt_id': 'old'}
    encoded = encode(old)
    with cs.store.connect() as db:
        db.execute('INSERT INTO content_operations VALUES (?,?,?,?)',
                   ('old', co.id, digest({'actor': co.__dict__, 'request': {'render': ref}}), encoded))
    monkeypatch.setattr('report_agent.office_render.convert_pdf', lambda *args: pytest.fail('cached receipt cannot dispatch'))
    assert render_export(cs, co, 'old', ref) == old
    with cs.store.connect() as db:
        assert db.execute('SELECT response FROM content_operations WHERE operation_id=?', ('old',)).fetchone()[0] == encoded
