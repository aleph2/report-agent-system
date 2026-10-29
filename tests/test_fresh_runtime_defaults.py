"""Only a new implicit native CLI case adopts the accepted common contract bundle."""
import json
import pytest

from report_agent.cli import main
from report_agent.handoff_release import release
from report_agent.store import Store

CURRENT = {
    'review_interface_profile': 'review-interfaces-v4',
    'operation_identity_profile': 'native-tool-runtime-v1',
    'content_input_profile': 'relation-endpoints-v2',
    'report_expression_profile': 'reader-expression-v2',
    'report_prompt_profile': 'concise-v1',
    'context_policy': 'stateful-tools-v2',
    'context_projection': 'review-materials-v1',
    'review_plan_contract': 'work-units-v1',
    'review_submission_contract': 'task-scope-selectors-v1',
}


def initialize(tmp_path, monkeypatch, extra=None):
    source = tmp_path / 'input.json'
    source.write_text(json.dumps({'goal':'Synthetic report.',
        'sources':[{'id':'synthetic','title':'Fake data','content':'Synthetic verified input.', 'coverage':'complete'}],
        **(extra or {})}))
    root = tmp_path / 'case'
    monkeypatch.setattr('sys.argv', ['report-agent','init','--project',str(root),'--manifest',str(source)])
    assert main() == 0
    return Store(root)


def test_fresh_implicit_native_case_uses_complete_valid_current_bundle(tmp_path, monkeypatch):
    store = initialize(tmp_path, monkeypatch)
    fresh = {**CURRENT, 'review_plan_contract':'optional-v1', 'history_projection_profile':'exact-history-v1'}
    assert {key:store.manifest.get(key) for key in fresh} == fresh
    bound = release(store.manifest)
    assert bound['review_plan_contract'] == 'optional-v1'
    assert bound['delegation_prompt_profile'] == 'separate-description-v1'


@pytest.mark.parametrize('explicit', [
    {'review_execution_mode':'bounded-tool-v1'},
    {'review_interface_profile':'review-interfaces-v1'},
    {'context_policy':'stateful-tools-v1'},
])
def test_explicit_historical_configuration_is_not_silently_upgraded(tmp_path, monkeypatch, explicit):
    store = initialize(tmp_path, monkeypatch, explicit)
    for key, value in explicit.items():
        assert store.manifest[key] == value
    assert 'review_plan_contract' not in store.manifest
    assert 'report_prompt_profile' not in store.manifest


def test_reinitializing_current_case_retains_all_bound_contract_choices(tmp_path, monkeypatch):
    store = initialize(tmp_path, monkeypatch, CURRENT)
    original = release(store.manifest)
    store = initialize(tmp_path, monkeypatch)
    assert release(store.manifest) == original


def test_reinitializing_historical_case_keeps_its_original_release(tmp_path, monkeypatch):
    store = initialize(tmp_path, monkeypatch, {'review_interface_profile':'review-interfaces-v1'})
    original = release(store.manifest)
    store = initialize(tmp_path, monkeypatch)
    assert release(store.manifest) == original
    assert 'review_plan_contract' not in store.manifest
