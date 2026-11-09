"""New a150ecc regressions; synthetic/offline, not report quality acceptance.

Run only after the actual external test review. Existing source, scope, CAS,
receipt, and recovery tests remain authoritative; these do not replace them.
"""
from report_agent import report_state
from copy import deepcopy
import json
import shutil

import pytest
from langchain.agents.middleware.types import ModelRequest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from langchain_core.utils.function_calling import convert_to_openai_tool

from report_agent import deep_runtime, prompt_sources
from report_agent.content_export import export_snapshot
from report_agent.content_delivery import current_delivery
from report_agent.content_store import ContentStore
from report_agent.content_tasks import delegated_task
from report_agent.errors import ActionForbidden, ActionRejected
from report_agent.knowledge_state import project_state
from report_agent.hierarchical_tools import actor_for
from report_agent.layout_revision import status as layout_status
from report_agent.live_messages import _co_request, _receipt_label
from report_agent.prompt_sources import load_prompt
from test_deep_runtime import Driver
from test_hierarchical_content import seed, review_item
from test_task_supervision import ws, offline


def configure(ws, **values):
    ws.store.set('manifest', {**ws.store.manifest, **values})


def configure_v4(ws):
    configure(ws, review_interface_profile='review-interfaces-v4',
        review_execution_mode='native-reviewer-v2', delegation_prompt_profile='separate-description-v1',
        operation_identity_profile='native-tool-runtime-v1')


@pytest.mark.parametrize('role', ['writer', 'reviewer', 'layout'])
@pytest.mark.parametrize('flat_v4', [False, True])
async def test_native_delegation_description_contains_complete_role_file(ws, tmp_path, monkeypatch, role, flat_v4):
    if flat_v4:
        configure_v4(ws)
    rules = tmp_path / 'rules'
    shutil.copytree(prompt_sources.RULES, rules)
    definition = f'# {role}\n\nROLE_OBJECTIVE_{role}\n\nROLE_CONDITIONS_AT_END_{role}'
    (rules / f'agent-{role}.md').write_text(definition, encoding='utf-8')
    monkeypatch.setattr(prompt_sources, 'RULES', rules)
    driver = Driver(coordinator=[AIMessage(content='No work was commissioned in this fixture.')])
    await deep_runtime.build_agent(ws, driver, None).ainvoke({'messages': [HumanMessage(content='Inspect tools only.')]})
    task = next(f for f in driver.bindings['coordinator'][0] if f['name'] == 'task')
    assert definition in task['description']
    assert load_prompt('agent-common') not in task['description']


async def test_normal_graph_return_is_execution_end_without_report_acceptance(ws):
    driver = Driver(coordinator=[AIMessage(content='No review or delivery has been performed.')])
    result = await deep_runtime.run_report(ws, driver)
    assert result['last_error'] is None
    assert result['execution_status'] == 'completed'
    assert result['status'] == 'not_assessed'
    assert result['report_review_required'] is True
    assert result['content_current_review']['overall_verdict'] is None
    assert ws.store.get('report_status') == 'completed'
    assert any(e['kind'] == 'deep_run_finished' for e in ws.store.events())
    assert not ContentStore(ws.store).list_objects('ReviewRecord')


@pytest.mark.parametrize('raw', ['failed', 'interrupted', 'needs_attention', 'running'])
def test_public_projection_keeps_execution_failure_or_pending_state(ws, monkeypatch, raw):
    seed(ws)
    ws.store.set('report_status', raw)
    # Stale legacy delivery must not replace a newer execution failure.
    ws.store.set('delivery', {'draft_id': 'legacy-draft', 'review_id': 'legacy-review'})
    monkeypatch.setattr(ws, 'delivery', lambda *_: {'status': 'reviewed_draft'})
    result = project_state(ws)
    assert result['execution_status'] == raw
    assert result['status'] == raw


@pytest.mark.parametrize('public,raw,error,exit_code', [
    ('not_assessed', 'completed', None, 0),
    ('review_evidence_available', 'completed', None, 0),
    ('review_evidence_available', 'interrupted', None, 2),
    ('review_evidence_available', 'completed', {'type': 'RuntimeError'}, 2),
])
def test_cli_uses_public_review_state_and_execution_outcome(ws, monkeypatch, capsys, public, raw, error, exit_code):
    from report_agent import cli
    result = {'status': public, 'execution_status': raw, 'last_error': error,
              'report_review_required': True, 'whole_report_acceptance': None}
    calls = []
    async def run(*args, **kwargs):
        calls.append((args, kwargs))
        return deepcopy(result)
    monkeypatch.setattr(deep_runtime, 'run_report', run)
    monkeypatch.setattr('sys.argv', ['report-agent', 'report-run', '--project', str(ws.store.root)])
    assert cli.main() == exit_code
    assert len(calls) == 1
    assert json.loads(capsys.readouterr().out) == result


def test_one_saved_review_is_scoped_evidence_not_whole_report_acceptance(ws):
    cs, actor, refs, snapshot, _ = seed(ws)
    exported = export_snapshot(cs, actor, 'export', snapshot)['result']['export_ref']
    receipt = cs.read_context(actor_for('reviewer'), refs['claim'])['receipt_id']
    item = {**review_item(refs['claim'], refs['k'], receipt, verdict='satisfied'),
            'scope_id': 'one-claim', 'dependency_refs': []}
    cs.submit_review(actor_for('reviewer'), 'one-review', {
        'snapshot_ref': snapshot, 'target_ref': refs['claim'], 'scope': 'Only this claim',
        'criteria_refs': [refs['k']], 'dependency_refs': [], 'items': [item]}, {})
    report_state.set_content_delivery(ws.store, {'snapshot_ref': snapshot, 'export_ref': exported})
    ws.store.set('report_status', 'completed')
    evidence = current_delivery(ws.store)
    state = project_state(ws)
    assert evidence['overall_verdict'] is None and evidence['coverage_complete'] is None
    assert state['execution_status'] == 'completed'
    assert state['status'] == 'review_evidence_available'
    assert state['report_review_required'] is True
    assert state['whole_report_acceptance'] is None
    assert state['content_current_review']['overall_verdict'] is None


def test_unconfigured_layout_allows_successive_revisions_without_resetting_count(ws):
    cs, actor, _, snapshot, _ = seed(ws)
    assert ws.store.get('layout_revision_limit') is None
    for operation, options in [('first', {}), ('second', {'toc': False}),
                               ('third', {'toc': False, 'margin_mm': 30})]:
        export_snapshot(cs, actor, operation, snapshot, options)
    with ws.store.connect() as db:
        actual = layout_status(db)
    assert actual['max_revisions'] is None
    assert actual['revisions_used'] == 2
    assert len(cs.list_objects('ExportArtifact')) == 6


@pytest.mark.parametrize('limit', [0, 1])
def test_explicit_layout_limit_still_rejects_extra_revision_and_retains_history(ws, limit):
    cs, actor, _, snapshot, _ = seed(ws)
    ws.store.set('layout_revision_limit', limit)
    export_snapshot(cs, actor, 'initial', snapshot)
    if limit:
        export_snapshot(cs, actor, 'allowed', snapshot, {'toc': False})
    saved_exports = cs.list_objects('ExportArtifact')
    with pytest.raises(ActionRejected, match='LAYOUT_REVISION_LIMIT_REACHED'):
        export_snapshot(ContentStore(ws.store), actor, 'refused', snapshot, {'margin_mm': 31})
    assert cs.list_objects('ExportArtifact') == saved_exports
    with ws.store.connect() as db:
        assert layout_status(db)['revisions_used'] == limit
        assert layout_status(db)['max_revisions'] == limit
    assert cs.receipt(actor, 'refused')['state'] == 'known_failure'


def test_source_directory_preserves_complete_names_and_distinct_stable_scopes(ws, monkeypatch):
    names = ['共同来源前缀' * 40 + suffix for suffix in ('甲.pdf', '乙.pdf')]
    monkeypatch.setattr(ws.store, 'source_catalog', lambda: [
        {'id': str(i), 'name': name} for i, name in enumerate(names)])
    contents, resources = ContentStore(ws.store), {}
    results = [_receipt_label(contents, {'source_id': str(i), 'source_digest': str(i) * 64}, resources)
               for i in range(2)]
    assert [r['source_name'] for r in results] == names
    assert results[0] != results[1]
    assert _receipt_label(contents, {'source_id': '0', 'source_digest': '0' * 64}, resources) == results[0]
    assert len(resources) == 2


def test_object_directory_links_owner_task_and_resume_preserves_exact_writer_authority(ws):
    from report_agent.co_review_message import CoTaskMessage
    configure_v4(ws)
    cs = ContentStore(ws.store)
    original_goal = 'Maintain only this commissioned structure, including its original condition.'
    first_call = {'id': 'first-writer', 'args': {'subagent_type': 'writer', 'description': original_goal}}
    with delegated_task(ws, 'coordinator', first_call) as (_, writer):
        task_ref = {'type': 'DelegatedTask', 'id': writer.task_id, 'version': 1}
        root = cs.commit(writer, 'create-root', [{'client_key': 'root', 'type': 'ContentNode', 'payload': {
            'kind': 'report', 'body': {'title': 'Owned root', 'text': 'Structure'},
            'qualifiers': {}, 'claim_kind': 'structure'}}])['result']['refs']['root']
        first_actor = writer
    def task_function(**kwargs):
        """Delegate with actual grants."""
        return kwargs
    tool = StructuredTool.from_function(task_function, name='task', args_schema=CoTaskMessage)
    request = ModelRequest(model=Driver()('coordinator'), tools=[tool], state={'messages': []},
        system_message=SystemMessage(content='Role'), messages=[HumanMessage(content='Revise the owned root.')])
    _, offer = _co_request(ws, request)
    packet = offer['packet']['resource_scopes']
    internal = {json.dumps(x['resource'], sort_keys=True): x['scope'] for x in offer['resources']}
    task_scope = internal[json.dumps(task_ref, sort_keys=True)]
    root_scope = internal[json.dumps(root, sort_keys=True)]
    entry = next(x for x in packet if x['scope'] == root_scope)
    assert entry['owner_task_scope'] == task_scope
    assert 'owner_task_scope' not in next(x for x in packet if x['scope'] == task_scope)
    with delegated_task(ws, 'coordinator', {'id': 'new-writer', 'args': {
            'subagent_type': 'writer', 'description': 'Same role is not the same owner.'}}) as (_, other):
        with pytest.raises(ActionForbidden, match='object owner'):
            cs.commit(other, 'cannot-steal', [{'client_key': 'root', 'type': 'ContentNode',
                'previous_ref': root, 'payload': cs.read(root)['payload']}])
    with delegated_task(ws, 'coordinator', {'id': 'resume-original', 'args': {
            'subagent_type': 'writer', 'description': 'Correct the original structure.',
            'resume_content_task_id': task_ref['id']}}) as (_, same):
        assert same == first_actor
        assert cs.read(task_ref)['payload']['goal'] == original_goal
        revised = cs.commit(same, 'revise-original', [{'client_key': 'root', 'type': 'ContentNode',
            'previous_ref': root, 'payload': {**cs.read(root)['payload'],
                'body': {**cs.read(root)['payload']['body'], 'title': 'Revised owned root'}}}])
        assert revised['result']['refs']['root']['version'] == 2
