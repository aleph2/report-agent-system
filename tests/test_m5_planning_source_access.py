import json

import pytest

from report_agent.content_models import Ref
from report_agent.content_store import ContentStore
from report_agent.deep_runtime import business_tools
from report_agent.errors import ActionRejected
from report_agent.hierarchical_tools import actor_for
from report_agent.store import Store
from report_agent.workspace import Workspace


@pytest.fixture
def case(tmp_path):
    store = Store(tmp_path)
    store.initialize({'goal': 'Plan from A', 'commission_checkpoint_required': True,
        'content_contract': 'hierarchical-review-v1',
        'sources': [{'id': n, 'title': n, 'coverage': 'complete', 'content': 'matched ' + secret}
                    for n,secret in [('B', 'excluded-private-text'), ('A', 'allowed-text')]],
        'source_use': {'source_ids': ['A'], 'authorization_origin': 'Supplied for planning'}})
    from support.source_policy import restrict_supplied_case_files
    restrict_supplied_case_files(store, ['A'])
    ws = Workspace(store)
    cs = ContentStore(store)
    tools = {t.__name__: t for t in business_tools(ws, 'coordinator', None, None) if hasattr(t, '__name__')}
    return cs, tools


@pytest.mark.parametrize('name', ['import_source_versions','read_context','observe_evidence','read_source_page','inspect_source_page','search_sources'])
def test_private_source_is_refused_before_receipt(case, name):
    cs, tools = case
    excluded = cs.capture_sources(actor_for('coordinator'), 'host-intake', ['B'])['result']['source_refs'][0]
    args = {'import_source_versions': {'operation_id': 'attempt', 'source_ids': ['A','B']},
            'read_context': {'target_ref': Ref.model_validate(excluded)}, 'observe_evidence': {'kind': 'source','source_id': 'B'},
            'read_source_page': {'source_id':'B'}, 'inspect_source_page': {'source_id':'B','page':1},
            'search_sources': {'source_id':'B','query':'matched'}}[name]
    with pytest.raises(ActionRejected, match='CASE_SOURCE_NOT_SUPPLIED'):
        tools[name](**args)
    with cs.store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM content_observations').fetchone()[0] == 0


def test_search_filters_before_pagination_and_allowed_sources_are_readable(case):
    cs, tools = case
    output = tools['search_sources']('matched', limit=1)
    assert output['scope']['searched_source_ids'] == ['A']
    assert output['total'] == 1 and output['next_offset'] is None and output['matches'][0]['source_id'] == 'A'
    assert 'excluded-private-text' not in json.dumps(output)
    ref = tools['import_source_versions']('capture-A', ['A'])['result']['source_refs'][0]
    assert 'allowed-text' in str(tools['read_context'](Ref.model_validate(ref)))
    assert 'allowed-text' in str(tools['observe_evidence']('source','A'))
    assert 'allowed-text' in str(tools['read_source_page']('A'))
