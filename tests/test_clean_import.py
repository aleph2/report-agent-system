"""Independent fresh-input isolation, not semantic model-quality evidence."""
import importlib.util
from pathlib import Path

import pytest

from report_agent.catalog import Catalog
from report_agent.store import Store
from report_agent.workspace import Workspace
from test_revision_import import baseline


spec = importlib.util.spec_from_file_location('trial009', Path(__file__).parents[1] / 'scripts/prepare_clean_trial009.py')
trial = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trial)


def test_copies_inputs_only_preserves_baseline(baseline, tmp_path):
    root, _, _ = baseline
    old = Store(root)
    old.set('feedback', ['HIDDEN_REFERENCE_DEFECT_LIST'])
    old.set('report_issues', ['OLD_HUMAN_ISSUE'])
    old.set('knowledge_project_id', 'OLD_GRAPH_PROJECT')
    manifest = old.manifest
    manifest['existing_artifacts'] = [{'body': 'HIDDEN_REFERENCE_REPORT'}]
    manifest['document_uses'] = {'s': 'OLD_MODEL_JUDGMENT'}
    old.set('manifest', manifest)
    original_hash = trial.file_hash(root / 'state.db')
    receipt = trial.prepare(root, tmp_path / 'fresh')
    new = Store(tmp_path / 'fresh')
    assert new.manifest['goal'] == old.manifest['goal']
    assert set(new.manifest) == {'goal', 'sources', 'scope_instruction', 'export'}
    assert not Workspace(new).results()
    for key in ('feedback', 'report_issues', 'knowledge_project_id', 'selected_draft'):
        assert not new.get(key)
    assert not (new.root / 'checkpoints.db').exists()
    assert Catalog(new).read('s')['blocks'][0]['locator'] == 'physical page 8'
    assert receipt['copied_results'] is receipt['copied_feedback'] is False
    assert trial.file_hash(root / 'state.db') == original_hash
    with pytest.raises(ValueError, match='NEW_ISOLATED'):
        trial.prepare(root, new.root)


def test_rejects_tampered_input_before_creation(baseline, tmp_path):
    root, _, _ = baseline
    (root / 'sources/source.txt').write_bytes(b'Changed')
    dest = tmp_path / 'fresh'
    with pytest.raises(ValueError, match='HASH_MISMATCH'):
        trial.prepare(root, dest)
    assert not dest.exists()


def test_nested_destination_rejected(baseline):
    root, _, _ = baseline
    with pytest.raises(ValueError, match='NEW_ISOLATED'):
        trial.prepare(root, root / 'fresh')
