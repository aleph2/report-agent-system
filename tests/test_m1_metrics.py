"""Log-only metrics expose observed counters without querying the live database."""
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import sqlite3

import pytest


def test_log_only_counts_deduplicate_calls_attempts_and_rejections(tmp_path, monkeypatch):
    from report_agent.runtime_metrics import emit, summarize
    started = {'role': 'writer', 'call_id': 'logical-1', 'started_at': '2026-11-03T01:00:00+00:00'}
    emit(tmp_path, 'model_invocation_started', started)
    emit(tmp_path, 'model_invocation_started', started)
    emit(tmp_path, 'model_invocation_started', {**started, 'call_id': 'logical-2'})
    # Prompt provenance identifies an agent turn; helper invocations are not extra turns.
    emit(tmp_path, 'prompt_model_input', {'purpose': 'writer', 'call_id': 'prompt-1'})
    emit(tmp_path, 'prompt_model_input', {'purpose': 'writer', 'call_id': 'prompt-1'})
    emit(tmp_path, 'prompt_model_input', {'purpose': 'source_vision', 'call_id': 'helper-1'})
    usage = {'role': 'writer', 'call_id': 'prompt-1', 'attempt_id': 'attempt-1',
        'usage': {'prompt_tokens': 90, 'completion_tokens': 10, 'total_tokens': 100}, 'cached_tokens': 20}
    emit(tmp_path, 'prompt_provider_usage', usage)
    emit(tmp_path, 'prompt_provider_usage', usage)
    emit(tmp_path, 'prompt_provider_usage', {**usage, 'attempt_id': 'attempt-2',
        'usage': {'prompt_tokens': 40, 'completion_tokens': 10, 'total_tokens': 50}, 'cached_tokens': 0})
    emit(tmp_path, 'model_invocation_outcome', {'role': 'writer', 'call_id': 'logical-1',
        'elapsed_seconds': 8.5, 'outcome': 'returned'})
    emit(tmp_path, 'model_invocation_outcome', {'role': 'writer', 'call_id': 'logical-2',
        'elapsed_seconds': 3.5, 'outcome': 'returned'})
    rejected = {'role': 'writer', 'tool_call_id': 'tool-1', 'code': 'LOCAL_STORAGE_BUSY', 'retryable': True}
    emit(tmp_path, 'tool_rejected', rejected)
    emit(tmp_path, 'tool_rejected', rejected)
    monkeypatch.setattr(sqlite3, 'connect', lambda *args, **kwargs: pytest.fail('Metrics must not open SQLite'))
    result = summarize(tmp_path / 'runtime-metrics.jsonl')
    datetime.fromisoformat(result['statistical_timestamp'].replace('Z', '+00:00'))
    row = result['roles']['writer']
    assert row['invocations'] == 2 and row['current_turn'] == 1
    assert row['tokens'] == 150 and row['cached_tokens'] == 20 and row['usage_attempts'] == 2
    assert row['rejections'] == 1 and row['elapsed_seconds'] == 12
    assert row['elapsed_label'] == 'summed_invocation_seconds'
    assert result['malformed_lines'] == 0


def test_missing_usage_and_duration_are_unavailable_not_zero(tmp_path):
    from report_agent.runtime_metrics import emit, summarize
    emit(tmp_path, 'model_invocation_started', {'role': 'reviewer', 'call_id': 'pending'})
    result = summarize(tmp_path / 'runtime-metrics.jsonl')['roles']['reviewer']
    assert result['tokens'] is None and result['cached_tokens'] is None
    assert result['elapsed_seconds'] is None and result['current_turn'] is None
    assert result['invocations'] == 1


def test_metric_projection_excludes_prompt_material_and_secrets(tmp_path):
    from report_agent.runtime_metrics import emit
    sentinel = 'SYNTHETIC_PRIVATE_CONTENT_NOT_FOR_METRICS'
    emit(tmp_path, 'prompt_provider_usage', {'role': 'writer', 'call_id': 'logical', 'attempt_id': 'attempt',
        'usage': {'total_tokens': 42, 'private': sentinel}, 'cached_tokens': 4,
        'prompt': sentinel, 'messages': [{'content': sentinel}], 'api_key': sentinel,
        'source_text': sentinel, 'reasoning_content': sentinel, 'headers': {'Authorization': sentinel}})
    emit(tmp_path, 'unrecognized_private_event', {'role': 'writer', 'data': sentinel})
    emit(tmp_path, 'tool_rejected', {'role': 'writer', 'tool_call_id': 'one',
        'code': 'request failed: ' + sentinel, 'message': sentinel, 'retryable': False})
    raw = (tmp_path / 'runtime-metrics.jsonl').read_text()
    assert sentinel not in raw
    assert 'total_tokens' in raw


def test_invalid_numeric_usage_does_not_become_a_cost_estimate(tmp_path):
    from report_agent.runtime_metrics import emit, summarize
    emit(tmp_path, 'model_invocation_started', {'role': 'writer', 'call_id': 'one'})
    emit(tmp_path, 'prompt_provider_usage', {'role': 'writer', 'call_id': 'one', 'attempt_id': 'attempt',
        'usage': {'total_tokens': True, 'prompt_tokens': -10, 'completion_tokens': float('nan')},
        'cached_tokens': -1})
    row = summarize(tmp_path / 'runtime-metrics.jsonl')['roles']['writer']
    assert row['tokens'] is None and row['cached_tokens'] is None


def test_partial_last_line_is_reported_and_not_counted(tmp_path):
    from report_agent.runtime_metrics import emit, summarize
    emit(tmp_path, 'model_invocation_started', {'role': 'layout', 'call_id': 'one'})
    path = tmp_path / 'runtime-metrics.jsonl'
    with path.open('a') as output:
        output.write('{"kind":"model_invocation_started","data":')
    result = summarize(path)
    assert result['malformed_lines'] == 1
    assert result['roles']['layout']['invocations'] == 1


def test_file_append_failure_is_explicit_without_sensitive_exception_text(tmp_path, monkeypatch, caplog):
    from report_agent.runtime_metrics import emit
    original = Path.open

    def fail(path, *args, **kwargs):
        if path.name == 'runtime-metrics.jsonl':
            raise OSError('SYNTHETIC_SECRET_ERROR_DETAIL')
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'open', fail)
    assert emit(tmp_path, 'model_invocation_started', {'role': 'writer', 'call_id': 'one'}) is False
    assert caplog.records, 'A metric capture gap must be visible'
    assert 'SYNTHETIC_SECRET_ERROR_DETAIL' not in caplog.text


def test_metrics_survive_audit_database_busy(tmp_path, monkeypatch):
    from report_agent.errors import LocalStorageBusy
    from report_agent.runtime_metrics import summarize
    from report_agent.store import Store
    store = Store(tmp_path)

    @contextmanager
    def busy():
        raise LocalStorageBusy()
        yield  # A context manager that fails before the database write.

    monkeypatch.setattr(store, 'connect', busy)
    with pytest.raises(LocalStorageBusy):
        store.event('model_invocation_started', {'role': 'writer', 'call_id': 'one'})
    assert summarize(tmp_path / 'runtime-metrics.jsonl')['roles']['writer']['invocations'] == 1
