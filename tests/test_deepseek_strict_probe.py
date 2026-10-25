"""Protocol regression checks; no model calls or credentials."""
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
from run_deepseek_strict_probe import strict_schema, GraderResponse, read, FREEZE


def test_actual_wire_schema_preserves_fields_and_binds_ids():
    schema = read(FREEZE)['tools'][0]['function']['parameters']
    before = repr(schema)
    converted = strict_schema(schema, ['c1', 'c2'])
    assert repr(schema) == before
    branches = converted['properties']['criteria']['items']['anyOf']
    assert len(branches) == 2
    for old, new in zip(schema['properties']['criteria']['items']['oneOf'], branches):
        assert set(old['properties']) == set(new['properties'])
        assert new['properties']['name']['enum'] == ['c1', 'c2']
        assert new['properties']['passed']['enum'] == [old['properties']['passed']['const']]

    def check(node):
        if isinstance(node, dict):
            assert not {'oneOf', 'discriminator', 'minLength', 'const'} & node.keys()
            if node.get('type') == 'object':
                assert node['additionalProperties'] is False
                assert set(node['required']) == set(node['properties'])
            for value in node.values():
                check(value)
        elif isinstance(node, list):
            for value in node:
                check(value)
    check(converted)


def test_local_validation_still_rejects_empty_reason_and_inconsistent_result():
    result = dict(result='satisfied', criteria=[dict(name='c1', passed=True,
                  status='satisfied', evidence=[], explanation='', needed_outcome='')])
    with pytest.raises(ValueError):
        GraderResponse.model_validate(result)
    result['criteria'][0]['explanation'] = 'Supported.'
    result['result'] = 'needs_revision'
    with pytest.raises(ValueError):
        GraderResponse.model_validate(result)
