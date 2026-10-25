"""Operator launcher provenance with a stub runtime; no credentials or model work."""
from argparse import Namespace

import pytest

from report_agent.store import Store
import importlib.util
from pathlib import Path
_spec = importlib.util.spec_from_file_location('trial_launcher', Path(__file__).resolve().parents[1] / 'scripts/run_deepagents_trial.py')
launcher = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(launcher)


@pytest.mark.parametrize('note', [None, '', '  ', 'Existing desktop decision: necessary scoped validation only'])
async def test_launcher_does_not_invent_or_expand_user_authorization(tmp_path, monkeypatch, note):
    store = Store(tmp_path)
    store.initialize({'goal': 'Synthetic invocation', 'content_contract': 'hierarchical-review-v1', 'sources': [
        {'id': 's', 'title': 'Synthetic rule', 'content': 'A rule.', 'coverage': 'complete'}]})
    store.set('review_import017', {'historical_only': True})
    monkeypatch.setattr(launcher, 'load_service_environment', lambda _: None)
    monkeypatch.setenv('REPORT_MODEL', 'offline-transport')
    async def no_model(workspace):
        return {'status': 'needs_attention', 'last_error': None, 'delivery': None, 'results': [], 'issues': []}
    monkeypatch.setattr(launcher, 'run_report', no_model)
    args = Namespace(project=tmp_path, manifest=None, inspect=False, resume=False,
                     authorization_note=note, credential_container='never-inspected')
    await launcher.main(args)
    intent = store.get('task006_call_intent')
    assert intent['authorization'] == ((note or '').strip() or None)
    assert intent['authorization_origin'] == ('operator_note' if (note or '').strip() else 'not_supplied')
    assert intent['invocation_scope'] == {'project': str(tmp_path), 'resume': False}
    assert 'unlimited' not in str(intent) and 'Task017:' not in str(intent)


async def test_inspection_does_not_read_credentials_build_models_or_initialize_store(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(launcher, 'load_service_environment', lambda _: pytest.fail('No credentials during read-only inspection'))
    await launcher.main(Namespace(project=tmp_path, inspect=True))
    assert '"found": false' in capsys.readouterr().out and not (tmp_path/'state.db').exists()


async def test_archived_launcher_rejects_before_new_intent_or_credential_access(tmp_path, monkeypatch):
    from report_agent.errors import ActionRejected
    store = Store(tmp_path)
    store.initialize({'goal': 'Historical scope', 'sources': [
        {'id': 's', 'title': 'Source', 'content': 'Original', 'coverage': 'complete'}]})
    store.set('task006_call_intent', {'authorization': 'Dated bounded approval'})
    monkeypatch.setattr(launcher, 'load_service_environment', lambda _: pytest.fail('Archived execution never loads credentials'))
    with pytest.raises(ActionRejected, match='HISTORICAL_AGENT_EXECUTION_INACTIVE'):
        await launcher.main(Namespace(project=tmp_path, inspect=False, manifest=None))
    assert store.get('task006_call_intent') == {'authorization': 'Dated bounded approval'}
