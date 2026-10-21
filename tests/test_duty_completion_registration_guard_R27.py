"""R27 sibling admission paths stop before configuration/ledger/model access."""
import hashlib
import json
import linecache
import os
from pathlib import Path
import sys

import pytest

from duty_probe_agent_decisions import dump
from test_duty_layout_registration_guard import GuardBoundaryReached, runner
from test_duty_optimizer_adapter import no_external_network


async def assert_actual_main_registration_and_positive_caps(
        tmp_path, monkeypatch, request, variant, *, wave, case, http_cap, increment_cap, phase_cap, output_env):
    root = tmp_path / 'isolated-root'
    root.mkdir()
    out = root / 'fresh-output'
    env_file = root / 'synthetic.env'
    env_file.write_text('SYNTHETIC_GUARD_ONLY=1\n', encoding='utf-8')
    source = root / 'synthetic-source.txt'
    source.write_text('Immutable synthetic version.\n', encoding='utf-8')
    registered = {'status': 'approved_after_offline_and_neo_review',
        'cases': [case], 'maximum_http_attempts_including_retries': http_cap,
        'live_output': out.name, 'approved_source_sha256': {source.name: hashlib.sha256(source.read_bytes()).hexdigest()}}
    registration = root / ('.analysis/agent-duty-validation-20261018/completion-execution-20261019/real/'
                           + wave.lower() + '-registration.json')
    if variant != 'absent':
        registration.parent.mkdir(parents=True)
        dump(registration, registered)
    missing = {'missing-http': 'HTTP_ATTEMPT_LIMITS', 'missing-increment': 'INCREMENT_ATTEMPT_LIMITS',
               'missing-phase': 'PHASE_ATTEMPT_LIMITS'}
    if variant in missing:
        monkeypatch.delitem(getattr(runner, missing[variant]), wave)
    monkeypatch.setattr(runner, 'ROOT', root)
    monkeypatch.setattr(sys, 'argv', ['probe_duty_completion.py', '--wave', wave, '--live',
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
        folder = Path(os.environ.get(output_env, str(tmp_path / 'guard-evidence')))
        folder.mkdir(parents=True, exist_ok=True)
        dump(folder / (variant + '.json'), {'variant': variant, 'registration': registered,
            'registration_exists': registration.exists(), 'configuration_boundary_calls': configured,
            'forbidden_accesses': forbidden, 'error_type': type(error).__name__ if error else None,
            'error_message': str(error) if error else None,
            'error_filename': str(getattr(error, 'filename', '')), 'actual_main_location': location,
            'paid_HTTP': 0, 'models_created': 0,
            'source_sha256': hashlib.sha256(Path(runner.__file__).read_bytes()).hexdigest()})
        request.node.user_properties.append(('guard_capture', str(folder / (variant + '.json'))))
    assert forbidden == [] and out.is_dir() and env_file.is_file()
    if variant == 'valid':
        assert runner.wave_attempt_limit(wave) == http_cap
        assert runner.INCREMENT_ATTEMPT_LIMITS[wave] == increment_cap and runner.PHASE_ATTEMPT_LIMITS[wave] == phase_cap
        assert configured == [str(env_file)] and isinstance(error, GuardBoundaryReached)
        assert location and 'load_mixed_services' in location['source']
    else:
        assert configured == [], 'UNREGISTERED_OR_UNBOUNDED_' + wave + '_REACHED_CONFIGURATION'
        if variant == 'absent':
            assert isinstance(error, FileNotFoundError) and Path(error.filename).resolve() == registration.resolve()
            assert location and 'registration.read_text' in location['source']
        else:
            assert isinstance(error, AssertionError)
            marker = {'missing-http': 'WAVE_HTTP_CAP_REQUIRED', 'missing-increment': 'WAVE_INCREMENT_CAP_REQUIRED',
                      'missing-phase': 'WAVE_PHASE_CAP_REQUIRED'}[variant]
            assert location and marker in location['source']


@pytest.mark.parametrize('variant', ['valid', 'absent', 'missing-http', 'missing-increment', 'missing-phase'])
async def test_r27_actual_main_registration_and_positive_caps(tmp_path, monkeypatch, request, variant):
    await assert_actual_main_registration_and_positive_caps(tmp_path, monkeypatch, request, variant,
        wave='R27', case='writer-current-paired-delivery', http_cap=6, increment_cap=105, phase_cap=113,
        output_env='REPORT_R27_GUARD_OUT')
