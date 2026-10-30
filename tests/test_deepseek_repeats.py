"""Repeat scheduling and validation regression tests, no network/credentials."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from run_deepseek_repeats import EXPECTED, read, schedule, sha, validate_result

BASE = Path(__file__).parent / 'fixtures/historical-duty/deepseek-strict'


def test_fixed_schedule_and_frozen_requests():
    rows = schedule()
    assert len({r['id'] for r in rows}) == 6
    assert [r['effort'] for r in rows] == ['high', 'max'] * 3
    for effort, digest in EXPECTED.items():
        assert sha((BASE / effort / 'request.json').read_bytes()) == digest


def test_raw_result_preserved_and_missing_or_duplicate_ids_rejected():
    public = read(BASE / 'max/response.json')
    expected = read(BASE / 'max/output.json')
    ids = [r['name'] for r in expected['criteria']]
    assert validate_result(public, ids) == expected
    for mutation in ('missing', 'duplicate', 'reordered'):
        result = deepcopy(expected)
        if mutation == 'missing':
            result['criteria'].pop(0)
        elif mutation == 'duplicate':
            result['criteria'][1]['name'] = ids[0]
        else:
            result['criteria'][:2] = reversed(result['criteria'][:2])
        altered = deepcopy(public)
        altered['choices'][0]['message']['tool_calls'][0]['function']['arguments'] = json.dumps(result)
        with pytest.raises(ValueError, match='CRITERION_COVERAGE_MISMATCH'):
            validate_result(altered, ids)
