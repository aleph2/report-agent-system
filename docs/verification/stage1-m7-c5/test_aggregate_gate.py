"""Desired M7 cross-slope lineage through authenticated existing S2 actions."""
from uuid import NAMESPACE_URL, uuid5

import pytest

from report_agent import assertions
from report_agent.assertion_host import AssertionHost, Grant
from report_agent.assertions.ids import canonical_json


def derive(tmp_path, artifact):
    host = AssertionHost(tmp_path)
    artifact_ref = dict(type='DocumentSnapshot', id='report', version=1)
    inputs = []
    for subject in ['A', 'B']:
        grant = Grant(str(uuid5(NAMESPACE_URL, 'coordinator')), 'coordinator', 'planning', subject,
            'plan', frozenset([subject]), frozenset(), frozenset(['assert_source']))
        row = assertions.assert_source(host.issue_once(grant, 'assert_source', subject), subject=subject,
            claim=dict(kind='source', predicate='condition', state='unknown', coverage=subject))
        inputs.append(row['id'])
    grant = Grant(str(uuid5(NAMESPACE_URL, 'report-agent:report-assembler')), 'calculator',
        'assembler/report', 'assemble', 'plan', frozenset(['report']),
        frozenset([*inputs, 'assembler-v1', canonical_json(artifact_ref)]), frozenset(['derive_result']),
        resources={'rules': {'assembler-v1': {'version': 'assembler-v1'}}})
    claim = dict(kind='derived', inputs=inputs, rule_version='assembler-v1', strength='undetermined')
    if artifact:
        claim['artifact_ref'] = artifact_ref
    return assertions.derive_result(host.issue_once(grant, 'derive_result', 'assemble'), subject='report',
        claim=claim, grounds=[dict(assertion_id=key, purpose='input', proposition='report generation')
                             for key in inputs])


def test_report_artifact_can_record_authorized_cross_slope_lineage(tmp_path):
    saved = derive(tmp_path, True)
    assert saved['claim']['artifact_ref']['type'] == 'DocumentSnapshot'
    assert saved['was_generated_by'] == 'assembler/report'


def test_non_artifact_derivation_still_requires_cross_slope_transfer(tmp_path):
    with pytest.raises(ValueError, match='C5'):
        derive(tmp_path, False)
