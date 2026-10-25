"""Probe capacity must match configuration unless an experiment overrides it.

Use the real role/tool input, SDK and adapter with the probe's MockTransport.
No provider request or production budget ledger is used.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

import httpx
import pytest


spec = importlib.util.spec_from_file_location(
    'probe_capacity_under_test',
    Path(__file__).resolve().parents[1] / 'scripts/probe_agent_io.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


@pytest.fixture
def models(monkeypatch):
    for role in ('WRITER_', 'TEXT_TOOL_'):
        for key, value in {'MODEL': 'glm-5.3', 'BASE_URL': 'https://offline.invalid/v1',
                           'API_KEY': 'synthetic-key'}.items():
            monkeypatch.setenv('REPORT_' + role + key, value)
    monkeypatch.setenv('REPORT_DEEPSEEK_STRICT', '0')
    captured = []
    actual_factory = probe.configured_model

    def configured(store, role):
        model = actual_factory(store, role)
        captured.append((model, model.max_tokens))
        return model

    monkeypatch.setattr(probe, 'configured_model', configured)
    return captured


@pytest.mark.parametrize('case', ['writer', 'text-normal'])
@pytest.mark.parametrize('override', [None, 4096])
async def test_probe_final_wire_inherits_configuration_unless_explicit(
        tmp_path, models, case, override, record_property):
    kwargs = {} if override is None else {'requested_output_limit': override}
    result = await probe.probe(case, tmp_path, False, **kwargs)
    model, configured = models[0]
    expected = configured if override is None else override
    assert result['status'] == 'passed_structure', result
    assert result['output_limit'] == expected
    assert result['configured_output_limit'] == configured
    assert result['requested_output_limit'] == (0 if override is None else override)
    assert result['output_limit_source'] == ('configured_model' if override is None else 'explicit_probe_override')
    assert model.max_tokens == configured
    folder = tmp_path / case
    wire = json.loads((folder / 'wire-requests.json').read_text(encoding='utf-8'))
    assert len(wire) == 1
    # LangChain's OpenAI-compatible wire name differs by provider adapter.
    limits = [wire[0][k] for k in ('max_tokens', 'max_completion_tokens') if k in wire[0]]
    assert limits == [expected]
    assert wire[0]['messages']
    if case == 'writer':
        assert wire[0]['tools'] and result['returned_actions']
    else:
        candidate = result['tool_result']
        assert candidate['state'] == 'completed'
        assert candidate['payload']['body']['text'] == 'Class B permits values from 75 to 100.'
        assert candidate['model']['max_tokens'] == expected
    assert result['observed_http_requests'] == result['observed_http_responses'] == 1
    record_property('probe_evidence_dir', str(folder))
    record_property('output_capacity', json.dumps({
        'configured': configured, 'override': override, 'effective_wire': limits[0]}))


async def test_cli_default_inherits_without_starting_a_wave(monkeypatch, tmp_path):
    class Parsed(Exception):
        pass

    actual_parse = argparse.ArgumentParser.parse_args
    captured = []

    def parse(parser, *args, **kwargs):
        captured.append(actual_parse(parser, *args, **kwargs))
        raise Parsed

    monkeypatch.setattr(sys, 'argv', ['probe_agent_io.py', '--out', str(tmp_path / 'wave')])
    monkeypatch.setattr(argparse.ArgumentParser, 'parse_args', parse)
    with pytest.raises(Parsed):
        await probe.main()
    assert captured[0].output_limit == 0
    assert not (tmp_path / 'wave').exists()


@pytest.mark.parametrize('case', ['writer', 'text-normal'])
@pytest.mark.parametrize('problem', ['negative_override', 'missing_configuration'])
async def test_invalid_capacity_does_not_send_http(tmp_path, models, monkeypatch, case, problem):
    attempted = []

    async def send(client, request, *args, **kwargs):
        attempted.append(request)
        raise AssertionError('Invalid capacity must be rejected before HTTP')

    monkeypatch.setattr(httpx.AsyncClient, 'send', send)
    configured = probe.configured_model
    if problem == 'missing_configuration':
        def missing(store, role):
            model = configured(store, role)
            model.max_tokens = None
            return model
        monkeypatch.setattr(probe, 'configured_model', missing)
    with pytest.raises(ValueError, match='OUTPUT_LIMIT'):
        await probe.probe(case, tmp_path, False,
                          requested_output_limit=-1 if problem == 'negative_override' else 0)
    assert attempted == []
    assert not (tmp_path / case / 'wire-requests.json').exists()
