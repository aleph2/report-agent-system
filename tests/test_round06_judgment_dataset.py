"""Validate a portable paired oracle's shape, never replace a semantic reviewer."""
import json
from collections import defaultdict
from pathlib import Path


def test_semantic_cases_are_self_contained_paired_controls_not_runtime_history():
    data = json.loads((Path(__file__).parent / 'fixtures/round06_review_judgment_pairs.json').read_text())
    pairs = defaultdict(list)
    assert len({case['id'] for case in data['cases']}) == 12
    for case in data['cases']:
        assert case['goal'] and case['evidence'] and case['candidate']
        assert type(case['expected']['claim_supported']) is bool
        assert not any(marker in json.dumps(case) for marker in ('.runs/', '.analysis/', 'state.db'))
        pairs[case['pair']].append(case)
    assert set(pairs) == {f'SR{i}' for i in range(1, 7)}
    for pair in pairs.values():
        assert len(pair) == 2 and pair[0]['goal'] == pair[1]['goal']
        assert {case['expected']['claim_supported'] for case in pair} == {False, True}
