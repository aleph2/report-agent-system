"""Absence of a saved mode has a legacy meaning, not a fresh-case default."""
from report_agent.prompt_sources import review_profile
from report_agent.handoff_release import release
from test_fresh_runtime_defaults import initialize


def test_reinit_preserves_effective_legacy_mode_when_old_manifest_omitted_it(tmp_path, monkeypatch):
    store = initialize(tmp_path, monkeypatch, {'review_execution_mode':'bounded-tool-v1'})
    manifest = store.manifest
    manifest.pop('review_execution_mode')
    store.set('manifest', manifest)
    before = store.manifest
    before_release = release(before)
    assert review_profile(store) == 'bounded-tool-v1'
    reopened = initialize(tmp_path, monkeypatch)
    assert review_profile(reopened) == 'bounded-tool-v1'
    assert reopened.manifest == before
    assert 'review_execution_mode' not in reopened.manifest
    assert release(reopened.manifest) == before_release
    assert 'review_plan_contract' not in reopened.manifest
