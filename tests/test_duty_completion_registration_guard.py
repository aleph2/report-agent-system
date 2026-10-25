"""Actual R25 CLI guard, isolated before configuration/ledger/model access."""
import hashlib
import json
import linecache
import os
from pathlib import Path
import sys

import pytest

from duty_probe_agent_decisions import dump
from test_duty_optimizer_adapter import no_external_network

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import probe_duty_completion as runner


class GuardBoundaryReached(RuntimeError):
    pass


@pytest.mark.parametrize('variant', ['absent', 'pending', 'wrong-case', 'wrong-cap',
                                     'wrong-output', 'changed-source', 'valid'])
async def test_r25_actual_main_enforces_registration_before_service_configuration(tmp_path, monkeypatch, request, variant):
    root = tmp_path / 'isolated-root'
    root.mkdir()
    out = root / 'fresh-output'
    assert not out.exists()
    env_file = root / 'synthetic.env'
    env_file.write_text('SYNTHETIC_GUARD_TEST_ONLY=1\n', encoding='utf-8')
    source = root / 'synthetic-bound-source.txt'
    source.write_text('Original synthetic version.\n', encoding='utf-8')
    registered = {'status': 'approved_after_offline_and_neo_review',
        'cases': ['coordinator-review-commission'], 'maximum_http_attempts_including_retries': 4,
        'live_output': out.name, 'approved_source_sha256': {
            source.name: hashlib.sha256(source.read_bytes()).hexdigest()}}
    if variant == 'pending':
        registered['status'] = 'pending_neo_exact_source_review'
    elif variant == 'wrong-case':
        registered['cases'] = ['different-case']
    elif variant == 'wrong-cap':
        registered['maximum_http_attempts_including_retries'] = 5
    elif variant == 'wrong-output':
        registered['live_output'] = 'another-output'
    elif variant == 'changed-source':
        source.write_text('A later changed synthetic version.\n', encoding='utf-8')
    registration = root / '.analysis/agent-duty-validation-20261018/completion-execution-20261019/real/r25-registration.json'
    if variant != 'absent':
        registration.parent.mkdir(parents=True)
        dump(registration, registered)
    monkeypatch.setattr(runner, 'ROOT', root)
    monkeypatch.setattr(sys, 'argv', ['probe_duty_completion.py', '--wave', 'R25', '--live',
                                    '--out', str(out), '--env-file', str(env_file)])
    # Always register an undo, including variables originally absent: main
    # changes these directly rather than through this test's monkeypatch.
    for key in ('LANGSMITH_TRACING', 'LANGCHAIN_TRACING_V2', 'REPORT_SDK_RETRIES',
                'REPORT_CONNECT_RETRIES', 'REPORT_GRAPH_TEST_URI'):
        monkeypatch.setenv(key, os.environ.get(key, 'synthetic-guard-placeholder'))
    configured, forbidden = [], []

    def stop_at_configuration(path):
        configured.append(str(path))
        raise GuardBoundaryReached('SYNTHETIC_CONFIGURATION_BOUNDARY_ONLY')

    def never_reached(label):
        def stop(*args, **kwargs):
            forbidden.append(label)
            raise RuntimeError('FORBIDDEN_GUARD_TEST_ACCESS:' + label)
        return stop

    monkeypatch.setattr(runner, 'load_mixed_services', stop_at_configuration)
    monkeypatch.setattr(runner.sqlite3, 'connect', never_reached('sqlite_ledger'))
    monkeypatch.setattr(runner, 'TokenBudget', never_reached('TokenBudget'))
    monkeypatch.setattr(runner, 'configured_model', never_reached('configured_model'))
    monkeypatch.setattr(runner, 'run_wave', never_reached('run_wave'))
    monkeypatch.setattr(runner.base, 'ledger_rows', never_reached('ledger_rows'))
    error, location = None, None
    try:
        await runner.main()
    except Exception as exc:
        error = exc
        trace = exc.__traceback__
        while trace:
            if (Path(trace.tb_frame.f_code.co_filename).resolve() == Path(runner.__file__).resolve()
                    and trace.tb_frame.f_code.co_name == 'main'):
                location = {'line': trace.tb_lineno,
                            'source': linecache.getline(runner.__file__, trace.tb_lineno).strip()}
            trace = trace.tb_next
    finally:
        folder = Path(os.environ.get('REPORT_R25_GUARD_OUT', str(tmp_path / 'guard-evidence')))
        folder.mkdir(parents=True, exist_ok=True)
        capture = {'variant': variant, 'synthetic_root': str(root),
            'registration_path': str(registration), 'registration': None if variant == 'absent' else registered,
            'out_created': out.exists(), 'configuration_boundary_calls': configured,
            'forbidden_accesses': forbidden, 'error_type': type(error).__name__ if error else None,
            'error_message': str(error) if error else None,
            'error_filename': str(getattr(error, 'filename', '')),
            'actual_main_location': location, 'paid_HTTP': 0, 'models_created': 0,
            'source_sha256': hashlib.sha256(Path(runner.__file__).read_bytes()).hexdigest(),
            'scope': 'Valid only reaches a stopped synthetic configuration boundary; no real provider, ledger or complete paid admission.'}
        dump(folder / (variant + '.json'), capture)
        request.node.user_properties.append(('guard_capture', str(folder / (variant + '.json'))))
    assert forbidden == []
    assert out.is_dir() and env_file.is_file()
    assert runner.wave_attempt_limit('R25') == 4
    if variant == 'valid':
        assert configured == [str(env_file)]
        assert isinstance(error, GuardBoundaryReached)
        assert location and 'load_mixed_services' in location['source']
    else:
        assert configured == [], 'UNAPPROVED_R25_REACHED_CONFIGURATION_BOUNDARY'
        if variant == 'absent':
            assert isinstance(error, FileNotFoundError)
            assert Path(error.filename).resolve() == registration.resolve()
            assert location and 'registration.read_text' in location['source']
        else:
            assert isinstance(error, AssertionError)
            marker = {'pending': "registered['status']", 'wrong-case': "registered['cases']",
                      'wrong-cap': 'maximum_http_attempts_including_retries',
                      'wrong-output': 'REGISTERED_OUTPUT_REQUIRED',
                      'changed-source': 'REGISTERED_SOURCE_CHANGED'}[variant]
            assert location and marker in location['source']
