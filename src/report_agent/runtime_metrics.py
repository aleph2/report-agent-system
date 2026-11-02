"""Allowlisted local metrics; the reader never opens a runtime database."""
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re

KINDS = {'model_invocation_started', 'model_invocation_outcome', 'prompt_model_input',
         'prompt_provider_usage', 'tool_rejected', 'deep_run_started', 'deep_run_finished', 'deep_run_error'}
FIELDS = {'role', 'purpose', 'call_id', 'attempt_id', 'tool_call_id', 'code', 'retryable',
          'outcome', 'elapsed_seconds', 'cached_tokens', 'started_at', 'status'}
AGENTS = {'coordinator', 'writer', 'reviewer', 'rubric_grader', 'layout', 'materials'}


def _metric_value(key, value):
    if value is None:
        return True
    if key == 'retryable':
        return type(value) is bool
    if key == 'cached_tokens':
        return type(value) is int and value >= 0
    if key == 'elapsed_seconds':
        return type(value) in (int, float) and math.isfinite(value) and value >= 0
    if not isinstance(value, str):
        return False
    pattern = '[A-Z][A-Z0-9_]{0,99}' if key == 'code' else '[A-Za-z0-9_.:+/-]{1,200}'
    return re.fullmatch(pattern, value) is not None


def emit(root, kind, data):
    if kind not in KINDS or not isinstance(data, dict):
        return
    import fcntl
    record = {'kind': kind, 'at': datetime.now(timezone.utc).isoformat()}
    record.update({k: v for k, v in data.items() if k in FIELDS and _metric_value(k, v)})
    usage = data.get('usage')
    if isinstance(usage, dict):
        record['usage'] = {k: v for k, v in usage.items()
                           if k in {'prompt_tokens', 'completion_tokens', 'total_tokens', 'input_tokens', 'output_tokens'}
                           and type(v) is int and v >= 0}
    path = Path(root) / 'runtime-metrics.jsonl'
    try:
        fd = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        os.close(fd)
        with path.open('ab') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            stream.write((json.dumps(record, ensure_ascii=False, allow_nan=False) + '\n').encode())
            stream.flush()
        return True
    except (OSError, ValueError) as error:
        import logging
        logging.getLogger(__name__).warning('Runtime metrics unavailable: %s', type(error).__name__)
        return False


def summarize(path):
    groups, malformed = {}, 0
    path = Path(path)
    if not path.is_file():
        return {'statistical_timestamp': datetime.now(timezone.utc).isoformat(),
                'coverage': 'unavailable', 'roles': {}, 'malformed_lines': 0}
    with path.open('rb') as stream:
        for line in stream:
            try:
                if not line.endswith(b'\n'):
                    raise ValueError('incomplete log line')
                item = json.loads(line)
                if not isinstance(item, dict) or item.get('kind') not in KINDS:
                    raise ValueError('invalid log record')
            except (ValueError, UnicodeError):
                malformed += 1
                continue
            role = item.get('role') or (item.get('purpose') if item.get('purpose') in AGENTS else None)
            if not isinstance(role, str):
                continue
            group = groups.setdefault(role, {'starts': set(), 'turns': set(), 'rejects': set(),
                                              'outcomes': {}, 'usage': {}})
            kind, call = item['kind'], item.get('call_id')
            if kind == 'model_invocation_started' and call:
                group['starts'].add(call)
            elif kind == 'model_invocation_outcome' and call:
                group['outcomes'][call] = item
            elif kind == 'prompt_model_input' and call and item.get('purpose') == role:
                group['turns'].add(call)
            elif kind == 'tool_rejected' and item.get('tool_call_id'):
                group['rejects'].add(item['tool_call_id'])
            elif kind == 'prompt_provider_usage' and item.get('attempt_id'):
                group['usage'][item['attempt_id']] = item
    roles = {}
    for role, group in groups.items():
        tokens, cached, unknown = [], [], 0
        for item in group['usage'].values():
            usage = item.get('usage') or {}
            total = usage.get('total_tokens')
            if total is None:
                inputs = usage.get('prompt_tokens', usage.get('input_tokens'))
                outputs = usage.get('completion_tokens', usage.get('output_tokens'))
                total = inputs + outputs if type(inputs) is int and type(outputs) is int else None
            if type(total) is int and total >= 0:
                tokens.append(total)
            else:
                unknown += 1
            if type(item.get('cached_tokens')) is int and item['cached_tokens'] >= 0:
                cached.append(item['cached_tokens'])
        elapsed = [v['elapsed_seconds'] for v in group['outcomes'].values()
                   if type(v.get('elapsed_seconds')) in (int, float)
                   and math.isfinite(v['elapsed_seconds']) and v['elapsed_seconds'] >= 0]
        roles[role] = {'invocations': len(group['starts']), 'current_turn': len(group['turns']) or None,
            'rejections': len(group['rejects']), 'tokens': sum(tokens) if tokens else None,
            'cached_tokens': sum(cached) if cached else None, 'usage_attempts': len(group['usage']),
            'usage_attempts_unavailable': unknown, 'elapsed_seconds': sum(elapsed) if elapsed else None,
            'elapsed_label': 'summed_invocation_seconds', 'completed_invocations': len(group['outcomes'])}
    return {'statistical_timestamp': datetime.now(timezone.utc).isoformat(),
            'coverage': 'observed_log_records_only', 'roles': roles, 'malformed_lines': malformed,
            'limitation': 'Observed counters are not the budget ledger. Missing usage is unavailable; summed concurrent invocation time is not wall-clock runtime.'}
