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


def test_native_artifact_reference_must_be_in_the_host_issued_packet(tmp_path):
    from dataclasses import replace
    from uuid import NAMESPACE_URL, uuid5
    from report_agent import assertions
    from report_agent.assertion_host import AssertionHost, Grant
    from report_agent.assertions.ids import canonical_json
    from report_agent.assertions.queries import packet
    host = AssertionHost(tmp_path)
    author = str(uuid5(NAMESPACE_URL, 'coordinator'))
    source_grant = Grant(author, 'coordinator', 'planning', 'source', 'plan',
        frozenset(['report']), frozenset(), frozenset(['assert_source']))
    fact = assertions.assert_source(host.issue_once(source_grant, 'assert_source', 'source'),
        subject='report', claim=dict(kind='source', predicate='condition', state='unknown', coverage='report'))
    grant = Grant(str(uuid5(NAMESPACE_URL, 'report-agent:report-assembler')), 'calculator',
        'assembler/report', 'assemble', 'plan', frozenset(['report']),
        frozenset([fact['id'], 'assembler-v1']), frozenset(['derive_result']),
        resources={'rules': {'assembler-v1': {'version': 'assembler-v1'}}})
    with pytest.raises(ValueError, match='C4'):
        assertions.derive_result(host.issue_once(grant, 'derive_result', 'assemble'), subject='report',
            claim=dict(kind='derived', inputs=[fact['id']], rule_version='assembler-v1',
                strength='undetermined', artifact_ref=dict(type='DocumentSnapshot', id='unissued', version=1)))
    ref = dict(type='DocumentSnapshot', id='issued', version=1)
    resource = canonical_json(ref)
    granted = replace(grant, attempt='issued', packet=grant.packet | {resource})
    saved = assertions.derive_result(host.issue_once(granted, 'derive_result', 'issued'), subject='report',
        claim=dict(kind='derived', inputs=[fact['id']], rule_version='assembler-v1',
            strength='undetermined', artifact_ref=ref))
    assert saved['was_generated_by'] == 'assembler/report'
    for visible in [False, True]:
        read = replace(grant, attempt='read/' + str(visible), actions=frozenset(),
            packet=frozenset([saved['id'], *([resource] if visible else [])]))
        body, = packet(host.issue_once(read, 'derive_result', 'read/' + str(visible)))
        assert ('artifact_ref' in body['claim']) is visible
