"""Trace planning obligations separately from Writer issue materialization."""
import json
import os
from pathlib import Path

import pytest

from report_agent.content_store import Actor, ContentStore
from report_agent.content_tasks import delegated_task
from report_agent.errors import ActionRejected
from report_agent.hierarchical_tools import actor_for
from report_agent.mini_commission import prepare_mini_commission
from report_agent.section_writing import propose_material_issue, save_section_prose
from report_agent.store import Store, digest
from report_agent.system_assembler import assemble_current_report, record_issue_routes
from report_agent.workspace import Workspace


def test_confirmed_planning_conflicts_need_writer_records_and_routes(tmp_path):
    case = tmp_path / 'fresh-case'
    assert not case.exists()
    prepared = prepare_mini_commission(
        Path(__file__).parent / 'fake_data/mini_commission/inputs', case)
    cs, co = ContentStore(Store(case)), actor_for('coordinator')
    ws = Workspace(cs.store)
    plan_ref = prepared['plan_ref']
    plan = cs.read(plan_ref)['payload']
    required = cs.read(prepared['decision_ref'])['payload']['required_material_issues']
    reconciliation_ids = [digest([plan_ref, ['reconciliation', i, 0]]) for i in range(2)]
    inventory_id = digest([plan_ref, ['inventory', 'A', '坡率']])
    assert {i['id'] for i in required} == {*reconciliation_ids, inventory_id}

    def preflight(operation):
        with pytest.raises(ActionRejected, match='ASSEMBLY_INPUT_INCOMPLETE') as error:
            assemble_current_report(cs, co, operation)
        return error.value.diagnostic

    before = preflight('before-writing')
    for field in ('missing_issue_records', 'missing_issue_bindings', 'missing_issue_routes'):
        assert set(before[field]) == {i['id'] for i in required}
    # The confirmed plan already states these choices; this test makes no new judgment.
    destinations = {
        reconciliation_ids[0]: ('3', plan['reconciliations'][0]['result']),
        reconciliation_ids[1]: ('2', plan['reconciliations'][1]['result']),
        inventory_id: ('3', plan['reconciliations'][0]['result'])}
    call = {'name': 'task', 'id': 'conflict-prose', 'args': {
        'subagent_type': 'writer', 'description': 'Preserve confirmed planning conflicts in prose.',
        'section_ids': ['2', '3', '4']}}
    with delegated_task(ws, 'coordinator', call) as (_, writer):
        nodes = {}
        for section in plan['sections']:
            sid = section['section_id']
            if sid not in ('2', '3', '4'):
                continue
            citation = section['sources'][0]
            nodes[sid] = save_section_prose(cs, writer, 'context-' + sid, sid,
                citation['quote'], [citation])['result']['refs']['prose']
        for item in required:
            sid, adopted = destinations[item['id']]
            proposal = {**item, 'adopted_value': adopted, 'affects_level': False}
            first = propose_material_issue(cs, writer, 'issue-' + item['id'], nodes[sid], proposal)
            assert propose_material_issue(cs, writer, 'issue-' + item['id'], nodes[sid], proposal) == first
    after_proposals = preflight('after-proposals')
    assert after_proposals['missing_issue_records'] == []
    assert after_proposals['missing_issue_bindings'] == []
    assert set(after_proposals['missing_issue_routes']) == {i['id'] for i in required}
    routes = {issue_id: {'section_id': destinations[issue_id][0],
                         'reason': 'Synthetic operator maps the confirmed reconciliation to its prose section.'}
              for issue_id in reconciliation_ids}
    record_issue_routes(cs, Actor('operator', 'operator', 'trace'), 'operator-routes', routes,
                        note='Scripted fixture routes only; no new engineering or owner decision.')
    after_routes = preflight('after-routes')
    assert after_routes['missing_issue_records'] == []
    assert after_routes['missing_issue_bindings'] == []
    assert after_routes['missing_issue_routes'] == [inventory_id]
    assert set(after_routes['missing_assessments']) == {'A', 'B'}
    assert not cs.list_objects('ExportArtifact')
    if destination := os.environ.get('PLANNING_CONFLICT_TRACE'):
        Path(destination).write_text(json.dumps({
            'required': required, 'before': before, 'after_proposals': after_proposals,
            'after_routes': after_routes, 'exported': False}, ensure_ascii=False, indent=2))
