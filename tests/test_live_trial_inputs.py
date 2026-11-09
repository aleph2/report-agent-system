"""A clean live trial preserves located OCR without inheriting previous answers."""
from report_agent import report_state
import hashlib
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from import_verified_sources import rows_hash
from run_hierarchical_live_trial import prepare_inputs_only
from report_agent.catalog import Catalog
from report_agent.content_store import ContentStore
from report_agent.store import Store


def baseline(tmp_path):
    store = Store(tmp_path / 'baseline')
    source = store.root / 'sources/input.txt'
    source.parent.mkdir()
    source.write_bytes(b'Original input')
    rows = [('s', 0, 'page 7; chars 1-14', 'Original input')]
    store.initialize({'goal': 'Compile the supplied input', 'sources': [{
        'id': 's', 'title': 'Input', 'filename': 'input.txt', 'content': 'Original input',
        'coverage': 'complete', 'copied_path': 'sources/input.txt',
        'sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'blocks': 1, 'blocks_sha256': rows_hash(rows)}]})
    Catalog(store)
    with store.connect() as db:
        db.execute('DELETE FROM source_blocks')
        db.executemany('INSERT INTO source_blocks VALUES (?,?,?,?)', rows)
    report_state.set_content_final_review(store, {'secret_old_answer': 'pass'})
    store.set('rubric_reviews', [{'secret_old_answer': 'defect'}])
    store.event('deep_model_response', {'content': 'old model output'})
    return store, rows


def test_clean_import_keeps_exact_ocr_locations_and_excludes_feedback(tmp_path):
    old, rows = baseline(tmp_path)
    destination = tmp_path / 'new'
    receipt = prepare_inputs_only(old.root, destination)
    fresh = Store(destination)
    assert receipt['source_blocks'] == 1
    with fresh.connect() as db:
        assert db.execute('SELECT source_id,ordinal,locator,text FROM source_blocks').fetchall() == rows
        assert not db.execute("SELECT 1 FROM events WHERE kind='deep_model_response'").fetchone()
    assert Catalog(fresh).read('s')['blocks'][0]['locator'] == rows[0][2]
    assert fresh.get('content_final_review') is None
    assert fresh.get('rubric_reviews') is None
    assert not ContentStore(fresh).list_objects()
    assert fresh.manifest['coverage_contract'] == 'object-coverage-v1'
    assert not (destination / 'checkpoints.db').exists()


def test_rechunked_source_with_stale_metadata_is_rejected_before_copy(tmp_path):
    old, _ = baseline(tmp_path)
    with old.connect() as db:
        db.execute("UPDATE source_blocks SET locator='manifest text; chars 1-14'")
    destination = tmp_path / 'new'
    with pytest.raises(ValueError, match='FROZEN_SOURCE_BLOCKS_MISMATCH'):
        prepare_inputs_only(old.root, destination)
    assert not destination.exists()
