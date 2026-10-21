"""R26 actual CLI registration/cap checks, stopped before real configuration."""
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
    'wrong-output', 'changed-source', 'valid', 'missing-http', 'missing-increment', 'missing-phase'])
async def test_r26_actual_main_requires_registration_and_all_caps(tmp_path, monkeypatch, request, variant):
    root = tmp_path / 'isolated-root'
    root.mkdir()
    out = root / 'fresh-output'
    env_file = root / 'synthetic.env'
    env_file.write_text('SYNTHETIC_GUARD_TEST_ONLY=1\n', encoding='utf-8')
    source = root / 'synthetic-bound-source.txt'
    source.write_text('Original synthetic version.\n', encoding='utf-8')
    registered = {'status': 'approved_after_offline_and_neo_review',
        'cases': ['layout-current-document-outcome'], 'maximum_http_attempts_including_retries': 8,
        'live_output': out.name, 'approved_source_sha256': {
            source.name: hashlib.sha256(source.read_bytes()).hexdigest()}}
    if variant == 'pending':
        registered['status'] = 'pending_neo_exact_source_review'
    elif variant == 'wrong-case':
        registered['cases'] = ['different-case']
    elif variant == 'wrong-cap':
        registered['maximum_http_attempts_including_retries'] = 9
    elif variant == 'wrong-output':
        registered['live_output'] = 'another-output'
    elif variant == 'changed-source':
        source.write_text('A later changed synthetic version.\n', encoding='utf-8')
    missing_maps = {'missing-http': 'HTTP_ATTEMPT_LIMITS',
                    'missing-increment': 'INCREMENT_ATTEMPT_LIMITS', 'missing-phase': 'PHASE_ATTEMPT_LIMITS'}
    if variant in missing_maps:
        monkeypatch.delitem(getattr(runner, missing_maps[variant]), 'R26')
    registration = root / '.analysis/agent-duty-validation-20261018/completion-execution-20261019/real/r26-registration.json'
    if variant != 'absent':
        registration.parent.mkdir(parents=True)
        dump(registration, registered)
    monkeypatch.setattr(runner, 'ROOT', root)
    monkeypatch.setattr(sys, 'argv', ['probe_duty_completion.py', '--wave', 'R26', '--live',
                                    '--out', str(out), '--env-file', str(env_file)])
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
        folder = Path(os.environ.get('REPORT_R26_GUARD_OUT', str(tmp_path / 'guard-evidence')))
        folder.mkdir(parents=True, exist_ok=True)
        dump(folder / (variant + '.json'), {'variant': variant, 'registration': registered,
            'registration_exists': registration.exists(), 'configuration_boundary_calls': configured,
            'forbidden_accesses': forbidden, 'error_type': type(error).__name__ if error else None,
            'error_message': str(error) if error else None, 'error_filename': str(getattr(error, 'filename', '')),
            'actual_main_location': location, 'paid_HTTP': 0, 'models_created': 0,
            'source_sha256': hashlib.sha256(Path(runner.__file__).read_bytes()).hexdigest(),
            'scope': 'Stopped synthetic configuration boundary only; no real configuration, ledger or model access.'})
        request.node.user_properties.append(('guard_capture', str(folder / (variant + '.json'))))
    assert forbidden == []
    assert out.is_dir() and env_file.is_file()
    if variant == 'valid':
        assert runner.wave_attempt_limit('R26') == 8
        assert configured == [str(env_file)] and isinstance(error, GuardBoundaryReached)
        assert location and 'load_mixed_services' in location['source']
    else:
        assert configured == [], 'UNAPPROVED_OR_UNBOUNDED_R26_REACHED_CONFIGURATION_BOUNDARY'
        if variant == 'absent':
            assert isinstance(error, FileNotFoundError) and Path(error.filename).resolve() == registration.resolve()
            assert location and 'registration.read_text' in location['source']
        else:
            assert isinstance(error, AssertionError)
            marker = {'pending': "registered['status']", 'wrong-case': "registered['cases']",
                'wrong-cap': 'maximum_http_attempts_including_retries',
                'wrong-output': 'REGISTERED_OUTPUT_REQUIRED', 'changed-source': 'REGISTERED_SOURCE_CHANGED',
                'missing-http': 'WAVE_HTTP_CAP_REQUIRED', 'missing-increment': 'WAVE_INCREMENT_CAP_REQUIRED',
                'missing-phase': 'WAVE_PHASE_CAP_REQUIRED'}[variant]
            assert location and marker in location['source']
