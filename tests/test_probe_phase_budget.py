"""Test-harness wave admission; no model call or production ledger write."""
from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('probe_phase_under_test',
    Path(__file__).resolve().parents[1] / 'scripts/probe_agent_io.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def row(identity, used=None, state='reserved', reserved=2_000_000):
    return [identity, 'verified-model', reserved, used, state, None, None, 'synthetic-time']


def before():
    # Historical unknowns remain unchanged, but are not charged twice to phase.
    return {'authorization': [[1, 170_000_000, 'unchanged bounds']],
            'attempts': {'old': row('old', state='unknown', reserved=26_000_000)}}


@pytest.mark.parametrize('over', [0, 1])
def test_phase_wave_exact_boundary_and_one_token_over(over):
    baseline = before()
    current = deepcopy(baseline)
    current['attempts'].update(first=row('first', 1_000_000, 'settled'),
                               second=row('second', 1_000_000 + over, 'settled'))
    if over:
        with pytest.raises(ValueError, match='PHASE_TOKEN_BUDGET_REACHED'):
            probe.phase_admission(baseline, current, 10_000_000, {'verified-model': 2_000_000})
    else:
        result = probe.phase_admission(baseline, current, 10_000_000, {'verified-model': 2_000_000})
        assert result['recorded_tokens'] == 2_000_000
        assert result['reserved_or_unknown_upper_bounds'] == 0
        assert result['next_wave_worst_case_tokens'] == 8_000_000
        assert current['attempts']['old'] == baseline['attempts']['old']


def test_new_unknown_keeps_upper_bound_even_without_usage():
    baseline = before()
    current = deepcopy(baseline)
    current['attempts'].update(unknown=row('unknown', state='unknown'),
                               small=row('small', 1, 'settled'))
    with pytest.raises(ValueError, match='PHASE_TOKEN_BUDGET_REACHED'):
        probe.phase_admission(baseline, current, 10_000_000, {'verified-model': 2_000_000})
    assert current['attempts']['unknown'][3] is None


def test_old_attempt_drift_is_not_reinterpreted_as_phase_allowance():
    baseline = before()
    current = deepcopy(baseline)
    current['attempts']['old'][4] = 'known_not_sent'
    with pytest.raises(ValueError, match='PHASE_BASELINE_CHANGED'):
        probe.phase_admission(baseline, current, 10_000_000, {'verified-model': 2_000_000})


def test_phase_cannot_spend_more_http_attempts_despite_small_usage():
    baseline = before()
    current = deepcopy(baseline)
    current['attempts'].update({str(i): row(str(i), 1, 'settled') for i in range(9)})
    with pytest.raises(ValueError, match='PHASE_HTTP_ATTEMPT_LIMIT'):
        probe.phase_admission(baseline, current, 10_000_000, {'verified-model': 2_000_000})


@pytest.mark.parametrize('next_attempts,limit', [(0, 38), (4, 42)])
def test_confirmed_local_refusal_is_a_ledger_row_not_an_http_attempt(next_attempts, limit):
    baseline = before()
    current = deepcopy(baseline)
    current['attempts'].update({str(i): row(str(i), 1, 'settled') for i in range(38)})
    current['attempts']['refused'] = row('refused', 0, 'known_not_sent')
    untouched = deepcopy(current)
    result = probe.phase_admission(baseline, current, 10_000_000,
                                   {'verified-model': 2_000_000},
                                   attempts=next_attempts, max_attempts=limit)
    assert result['ledger_row_count'] == 39
    assert result['known_not_sent_rows'] == 1
    assert result['admitted_or_unresolved_attempts'] == 38
    assert result['http_attempt_rows'] == 39  # Historical field retains its row-count meaning.
    assert result['recorded_tokens'] == 38
    assert result['reserved_or_unknown_upper_bounds'] == 0
    assert current == untouched and current['attempts']['old'] == baseline['attempts']['old']


@pytest.mark.parametrize('unresolved', ['reserved', 'unknown'])
def test_unresolved_attempt_still_counts_alongside_confirmed_local_refusal(unresolved):
    baseline = before()
    current = deepcopy(baseline)
    current['attempts'].update({str(i): row(str(i), 1, 'settled') for i in range(38)})
    current['attempts']['refused'] = row('refused', 0, 'known_not_sent')
    current['attempts']['uncertain'] = row('uncertain', state=unresolved)
    with pytest.raises(ValueError, match='PHASE_HTTP_ATTEMPT_LIMIT'):
        probe.phase_admission(baseline, current, 10_000_000,
                              {'verified-model': 2_000_000}, attempts=0, max_attempts=38)
