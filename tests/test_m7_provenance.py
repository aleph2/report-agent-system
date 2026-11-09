"""Report derivations identify immutable artifacts and invalidate stale exports."""
import pytest
from pydantic import ValidationError

from report_agent.assertions.schema.kinds import Derived


def test_artifact_reference_is_additive_and_does_not_change_numeric_records():
    original = dict(kind='derived', rule_version='rule', inputs=['fact'], strength='undetermined', value=None)
    assert Derived.model_validate(original).model_dump(mode='json') == original
    ref = dict(type='ContentNode', id='section', version=1)
    saved = Derived.model_validate({**original, 'artifact_ref': ref})
    assert saved.artifact_ref.model_dump() == ref
    assert saved.model_dump(mode='json')['artifact_ref'] == ref
    with pytest.raises(ValidationError):
        Derived.model_validate({**original, 'artifact_ref': {**ref, 'version': 0}})
    with pytest.raises(ValidationError):
        Derived.model_validate({**original, 'artifact_ref': ref, 'value': '42'})
