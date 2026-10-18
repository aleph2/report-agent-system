from fastapi.testclient import TestClient
import pytest

from test_hierarchical_content import ws
from test_content_workbook import prepared
from report_agent.content_export import export_snapshot
from report_agent.content_workbook import export_workbook
from report_agent.content_models import Ref
from report_agent.hierarchical_tools import content_tools
from report_agent.webapp import create_app
from report_agent.errors import ActionRejected


def selected_pair(ws):
    cs, actor, original, snap, sheets = prepared(ws)
    word = export_snapshot(cs, actor, 'selected-word', snap)['result']['export_ref']
    workbook = export_workbook(cs, actor, 'selected-workbook', snap, sheets, word)['result']['export_ref']
    select = next(t for t in content_tools(ws, 'coordinator') if t.__name__ == 'select_content_delivery')
    select('pair', Ref(**snap), Ref(**word), workbook_export_ref=Ref(**workbook))
    return cs, actor, snap, word, workbook, select


def test_selected_pair_downloads_exact_assets_without_model_execution(ws):
    cs, actor, snap, word, workbook, select = selected_pair(ws)
    before = cs.list_objects()
    with TestClient(create_app(ws.store.root)) as client:
        state = client.get('/api/status').json()
        assert state['content_delivery']['workbook_export_ref'] == workbook
        for companion, ref, suffix, media in [(False, word, '.docx', 'wordprocessingml'),
                                               (True, workbook, '.xlsx', 'spreadsheetml')]:
            response = client.get('/api/content/delivery', params={
                'companion': companion, 'expected_export_id': word['id']})
            assert response.status_code == 200
            payload = cs.read(ref)['payload']
            assert response.content == (ws.store.root / payload['file_ref']).read_bytes()
            assert suffix in response.headers['content-disposition']
            assert media in response.headers['content-type']
        assert client.get('/api/content/delivery', params={'expected_export_id': 'stale'}).status_code == 409
    assert cs.list_objects() == before


def test_companion_must_link_selected_word_and_reselection_removes_old_companion(ws):
    cs, actor, snap, word, workbook, select = selected_pair(ws)
    other_word = export_snapshot(cs, actor, 'other-word', snap)['result']['export_ref']
    with pytest.raises(ActionRejected, match='COMPANION_EXPORT_VERSION_MISMATCH'):
        select('bad-pair', Ref(**snap), Ref(**other_word), workbook_export_ref=Ref(**workbook))
    select('word-only', Ref(**snap), Ref(**other_word))
    with TestClient(create_app(ws.store.root)) as client:
        assert client.get('/api/content/delivery?companion=true').status_code == 404
        assert client.get('/api/content/delivery').status_code == 200


def test_reusing_immutable_asset_does_not_rewrite_a_hardlinked_prior_file(ws, monkeypatch):
    import os
    from pathlib import Path
    from report_agent.content_export import _asset
    original = ws.store.root / 'prior-file.docx'
    original.write_bytes(b'synthetic immutable bytes')
    assets = ws.store.root / 'content-assets'
    assets.mkdir()
    os.link(original, assets / 'saved.docx')
    def forbidden(*args, **kwargs):
        pytest.fail('An existing verified immutable asset must not be rewritten')
    monkeypatch.setattr(Path, 'write_bytes', forbidden)
    assert _asset(ws.store, 'saved.docx', b'synthetic immutable bytes') == 'content-assets/saved.docx'
