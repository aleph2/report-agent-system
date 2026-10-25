"""Historical I/O failure mechanisms at sibling native entry points.

Fixtures are independent synthetic requirements, never current projections used
as expected answers. Models are scripted; this does not prove model judgment.
"""
import json

import pytest
from langchain_core.messages import AIMessage

from test_agent_result_delivery import packet, reply, run_role, wire_text
from test_bounded_review import Model
from test_decision_data import activate
from test_deep_runtime import invoke
from test_hierarchical_content import seed
from test_task_supervision import ws, offline


TAIL = 'TAIL: missing guide table means unresolved; it does not permit acceptance.'
TEXT = 'Synthetic selected paragraph. ' * 110 + TAIL
NOTE = 'Source qualification. ' * 70 + 'FINAL: no engineering sign-off.'


def material(ws):
    cs, owner, refs, snapshot, members = seed(ws)
    added = cs.commit(owner, 'sibling-material', [
        {'client_key': 'body', 'type': 'ContentNode', 'payload': {
            'kind': 'block', 'body': {'text': TEXT}, 'claim_kind': 'structure',
            'qualifiers': {'limitations': NOTE}}},
        {'client_key': 'edge2', 'type': 'Relation', 'payload': {
            'subject_ref': refs['root'], 'object_ref': {'client_key': 'body'},
            'predicate': 'contains', 'position': 1,
            'provenance_kind': 'adopted_during_generation'}}])['result']['refs']
    snapshot = cs.freeze(owner, 'sibling-snapshot', refs['root'],
                         [*members, *added.values()])['result']['snapshot_ref']
    return cs, refs, snapshot, added['body']


def set_source(ws):
    ws.store.set('manifest', {**ws.store.manifest, 'sources': [
        {'id': 's', 'title': 'Synthetic source', 'content': TEXT, 'coverage': 'partial'}]})
    with ws.store.connect() as db:
        db.execute('delete from source_blocks')
        db.execute('insert into source_blocks values (?,?,?,?)',
                   ('s', 0, json.dumps({'page': 1}), TEXT))


@pytest.mark.parametrize('role', ['coordinator', 'writer', 'reviewer', 'layout'])
@pytest.mark.parametrize('tool', ['read_context', 'read_content_selection', 'search_sources'])
@pytest.mark.parametrize('managed', [False, True], ids=['native', 'managed'])
async def test_other_read_entries_keep_selected_tail_and_qualifications(ws, role, tool, managed):
    cs, refs, snapshot, body = material(ws)
    if managed:
        activate(ws)
    if tool == 'read_context':
        args = {'target_ref': body}
    elif tool == 'read_content_selection':
        args = {'snapshot_ref': snapshot, 'selections': [
            {'ref': body, 'unit': 'text', 'offset': 0, 'limit': len(TEXT)}]}
    else:
        set_source(ws)
        args = {'query': 'TAIL', 'offset': 0, 'limit': 1}
    before = cs.read(body)
    inspected = []

    def inspect(messages):
        message = reply(messages, tool)
        # Assert at the next actual model boundary, before any scripted repair.
        wire = wire_text(message)
        assert TEXT in wire
        if tool != 'search_sources':
            assert NOTE in wire
        assert cs.read(body) == before
        inspected.append(tool)
        return AIMessage(content='Exact selected data observed, no quality claim.')

    await run_role(ws, role, [invoke(tool, **args), inspect], refs, snapshot)
    assert inspected == [tool]


@pytest.mark.parametrize('role', ['coordinator', 'writer', 'layout'])
@pytest.mark.parametrize('tool', ['analyze_text', 'analyze_evidence'])
async def test_sibling_text_tools_receive_exact_selection_and_return_exact_findings(ws, role, tool):
    _, refs, snapshot, _ = material(ws)
    activate(ws)
    set_source(ws)
    question = 'Compare only the selected synthetic paragraph and keep its restrictions.'
    finding = 'Synthetic observation. ' * 100 + TAIL
    model = Model(finding)
    args = ({'source_id': 's', 'purpose': question, 'offset': 0, 'limit': 1}
            if tool == 'analyze_text' else
            {'question': question, 'source_selections': [{'source_id': 's', 'offset': 0, 'limit': 1}],
             'result_selections': []})

    def inspect(messages):
        message = reply(messages, tool)
        assert finding in wire_text(message)
        assert len(model.calls) == 1
        actual = json.loads(model.calls[0][1][1])
        assert actual['question'] == question
        assert len(actual['evidence']) == 1
        selected = actual['evidence'][0]
        assert selected['observation']['blocks'][0]['text'] == TEXT
        assert selected['selection'] == {'source_id': 's', 'offset': 0, 'limit': 1}
        return AIMessage(content='Exact input and output checked; no semantic acceptance.')

    await run_role(ws, role, [invoke(tool, **args), inspect], refs, snapshot, model)


@pytest.mark.parametrize('role', ['coordinator', 'writer', 'reviewer', 'layout'])
@pytest.mark.parametrize('tool', ['read_context', 'read_content_selection'])
async def test_sibling_read_failures_reach_agent_without_success_or_side_effect(ws, role, tool):
    cs, refs, snapshot, body = material(ws)
    activate(ws)
    missing = {**body, 'version': body['version'] + 17}
    args = ({'target_ref': missing} if tool == 'read_context' else
            {'snapshot_ref': snapshot, 'selections': [{'ref': missing}]})
    before = []
    observed = []

    def request(messages):
        # Native delegation is legitimate; measure immediately before the read.
        before.extend(cs.list_objects())
        return invoke(tool, **args)

    def inspect(messages):
        # Business errors may use success ToolMessage transport; inspect the
        # business envelope instead of equating transport status with success.
        from langchain_core.messages import ToolMessage
        message = next(m for m in reversed(messages) if isinstance(m, ToolMessage) and m.name == tool)
        wrapped = packet(message)
        assert wrapped['status'] == 'error'
        value = wrapped['metadata']
        assert value.get('ok') is False, value
        assert value['code'] == ('NOT_FOUND' if tool == 'read_context'
                                 else 'CONTENT_SELECTION_OUTSIDE_SNAPSHOT')
        assert cs.list_objects() == before
        assert value['code'] in wire_text(message)
        observed.append(value['code'])
        return AIMessage(content='Read rejected, no supplied material or acceptance.')

    await run_role(ws, role, [request, inspect], refs, snapshot)
    assert len(observed) == 1
