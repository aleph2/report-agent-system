import pytest
from report_agent.errors import ActionRejected
from report_agent.prompt_provenance import AgentPromptBoundary
from report_agent.workspace import Workspace
from test_deliverable_declaration_v4 import case


def test_fresh_opt_in_binds_and_legacy_defaults_to_no_projection(case):
    cs, *_ = case
    ws = Workspace(cs.store)
    assert not AgentPromptBoundary(ws, 'coordinator').history_projection
    assert cs.store.get('history_projection_binding') is None
    cs.store.set('manifest', {**cs.store.manifest, 'history_projection_profile':'exact-history-v1'})
    assert AgentPromptBoundary(ws, 'coordinator').history_projection
    assert AgentPromptBoundary(ws, 'reviewer').history_projection
    assert cs.store.get('history_projection_binding') == 'exact-history-v1'
    cs.store.set('manifest', {k:v for k,v in cs.store.manifest.items() if k != 'history_projection_profile'})
    with pytest.raises(ActionRejected, match='HISTORY_PROJECTION_BINDING_CHANGED'):
        AgentPromptBoundary(ws, 'coordinator')


def test_cannot_enable_for_existing_execution(case):
    cs, *_ = case
    ws = Workspace(cs.store)
    cs.store.event('deep_model_request', {'fixture':True})
    cs.store.set('manifest', {**cs.store.manifest, 'history_projection_profile':'exact-history-v1'})
    with pytest.raises(ActionRejected, match='HISTORY_PROJECTION_REQUIRES_FRESH_PROJECT'):
        AgentPromptBoundary(ws, 'coordinator')
    assert cs.store.get('history_projection_binding') is None


def test_unknown_profile_is_rejected(case):
    cs, *_ = case
    ws = Workspace(cs.store)
    cs.store.set('manifest', {**cs.store.manifest, 'history_projection_profile':'unexpected'})
    with pytest.raises(ActionRejected, match='UNKNOWN_HISTORY_PROJECTION_PROFILE'):
        AgentPromptBoundary(ws, 'coordinator')


def test_cannot_enable_for_old_checkpoint_without_events(case):
    import sqlite3
    cs, *_ = case
    ws = Workspace(cs.store)
    with sqlite3.connect(ws.store.root / 'checkpoints.db') as db:
        db.execute('CREATE TABLE checkpoints(checkpoint_id TEXT)')
        db.execute("INSERT INTO checkpoints VALUES ('historic')")
    cs.store.set('manifest', {**cs.store.manifest, 'history_projection_profile':'exact-history-v1'})
    with pytest.raises(ActionRejected, match='HISTORY_PROJECTION_REQUIRES_FRESH_PROJECT'):
        AgentPromptBoundary(ws, 'reviewer')
    assert cs.store.get('history_projection_binding') is None


def test_release_captures_opt_in_without_changing_legacy_shape(case):
    from report_agent.handoff_release import release
    from report_agent.store import digest
    cs, *_ = case
    legacy = release(cs.store.manifest)
    assert 'history_projection_profile' not in legacy
    assert legacy['digest'] == digest({k:v for k,v in legacy.items() if k != 'digest'})
    chosen = release({**cs.store.manifest, 'history_projection_profile':'exact-history-v1'})
    assert chosen['history_projection_profile'] == 'exact-history-v1'
    assert chosen['digest'] != legacy['digest']


def test_child_profile_uses_captured_release_after_store_manifest_changes(case):
    from langchain_core.runnables.config import var_child_runnable_config
    from report_agent.handoff_release import release
    cs, *_ = case
    ws = Workspace(cs.store)
    original = {**cs.store.manifest, 'history_projection_profile':'exact-history-v1'}
    cs.store.set('manifest', original)
    bound = release(original)
    assert AgentPromptBoundary(ws, 'coordinator').history_projection
    cs.store.set('manifest', {k:v for k,v in original.items() if k != 'history_projection_profile'})
    token = var_child_runnable_config.set({'metadata': {'report_handoff_release':bound}})
    try:
        assert AgentPromptBoundary(ws, 'reviewer').history_projection
    finally:
        var_child_runnable_config.reset(token)


def test_empty_legacy_release_digest_stays_exact():
    from report_agent.handoff_release import release
    assert release({})['digest'] == 'c491358a731e7b7dd4e17dd9b817762861d57675a67801a9f6488060ab42a204'


def test_independent_optimizer_never_binds_report_history_policy(tmp_path, monkeypatch):
    import report_agent.prompt_provenance as provenance
    from report_agent.store import Store
    ws = Workspace(Store(tmp_path / 'learning-only'))
    assert ws.store.get('manifest') is None
    def forbidden(_):
        raise AssertionError('Independent optimizer must not bind report history')
    monkeypatch.setattr(provenance, 'bind_history_projection', forbidden)
    boundary = AgentPromptBoundary(ws, 'experience_optimizer', source='experience-optimizer')
    assert boundary.history_projection is False
    assert ws.store.get('manifest') is None


def test_report_boundary_without_manifest_still_fails_closed(tmp_path):
    from report_agent.store import Store
    ws = Workspace(Store(tmp_path / 'not-a-report'))
    with pytest.raises(ValueError, match='PROJECT_NOT_INITIALIZED'):
        AgentPromptBoundary(ws, 'coordinator')
