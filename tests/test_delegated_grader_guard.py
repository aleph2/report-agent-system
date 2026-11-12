"""Default native startup must distinguish delegated review from legacy rubric trials."""
import pytest

from report_agent import deep_runtime
from report_agent.store import Store
from report_agent.workspace import Workspace


@pytest.mark.parametrize(('entrypoint', 'history', 'explicit', 'factory', 'rejected'), [
    ('delegated-reviewer-v1', {}, False, False, False),
    ('delegated-reviewer-v1', {'checkpoint_resume': True}, False, False, False),
    ('delegated-reviewer-v1', {'rubric_reviews': [{'result': 'satisfied'}]}, False, False, True),
    ('delegated-reviewer-v1', {'grader_model_trial': {'model': 'glm-5.3'}}, False, False, True),
    ('delegated-reviewer-v1', {}, True, False, True),
    ('native-rubric-v1', {}, False, False, True),
    ('native-rubric-v1', {}, False, True, False),
])
async def test_default_factory_legacy_guard_follows_review_contract(tmp_path, monkeypatch, entrypoint, history, explicit, factory, rejected):
    store = Store(tmp_path)
    store.initialize({'goal': 'Synthetic delegated review',
        'sources': [{'id': 's', 'title': 'Source', 'content': 'Synthetic', 'coverage': 'complete'}],
        'content_contract': 'hierarchical-review-v1', 'review_entrypoint': entrypoint})
    for key, value in history.items():
        store.set(key, value)
    monkeypatch.setenv('REPORT_MODEL', 'deepseek-v4.1-flash-1017')
    monkeypatch.delenv('REPORT_GRADER_MODEL', raising=False)
    if explicit:
        monkeypatch.setenv('REPORT_GRADER_MODEL', 'deepseek-v4.1-flash-1017')
    monkeypatch.setattr(deep_runtime, 'require_native_runtime', lambda *_: None)
    from report_agent import operator_instructions, decision_data, source_search, review_context, model_config
    monkeypatch.setattr(operator_instructions, 'sync_operator_instructions', lambda *_: None)
    monkeypatch.setattr(decision_data, 'bind', lambda *_: None)
    monkeypatch.setattr(source_search, 'bind_source_search', lambda *_: None)
    monkeypatch.setattr(review_context, 'bind_context_experiment', lambda *_: None)
    monkeypatch.setattr(model_config, 'bind_role_services', lambda *_: None)

    class ReachedInitialization(Exception):
        pass

    monkeypatch.setattr(Workspace, 'initialize', lambda *_: (_ for _ in ()).throw(ReachedInitialization()))
    expected = RuntimeError if rejected else ReachedInitialization
    with pytest.raises(expected) as error:
        await deep_runtime.run_report(Workspace(store), model_factory=(lambda *_: None) if factory else None)
    if rejected:
        assert 'GRADER_MODEL_SWITCH_REQUIRES_FRESH_REVIEW_FORK' in str(error.value)
    assert store.get('grader_model_trial') == history.get('grader_model_trial')
