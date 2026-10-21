"""Real registered agent paths with fake models; not semantic acceptance.

Inspect the next model input, not only the tool-side archive. Report children
enter through the coordinator's native task tool. All data lives in tmp_path.
"""
import hashlib
import json

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_openai.chat_models.base import _convert_message_to_dict

from report_agent import deep_runtime
from report_agent.content_store import ContentStore
from report_agent.learning import binding
from report_agent.learning_runtime import build_optimizer
from test_bounded_review import Model, review_call
from test_decision_data import activate
from test_deep_runtime import Driver, invoke
from test_hierarchical_content import seed
from test_task_supervision import ws, offline


def reply(messages, name):
    result = next(m for m in reversed(messages)
                  if isinstance(m, ToolMessage) and m.name == name)
    assert result.status == 'success', result
    assert result.tool_call_id == name
    return result


def packet(message):
    if isinstance(message.content, str):
        return json.loads(message.content)
    # Native offload text is followed by the exact restored control packet.
    return json.loads(message.content[-1]['text'])


def wire_text(message):
    wire = _convert_message_to_dict(message)
    assert 'artifact' not in wire
    assert wire['role'] == 'tool'
    assert wire['tool_call_id'] == message.tool_call_id
    return json.dumps(wire, ensure_ascii=False)


def expected_owner(ws, role):
    if role == 'coordinator':
        return 'content:coordinator'
    tasks = [t for t in ContentStore(ws.store).list_objects('DelegatedTask')
             if t['payload']['role'] == role]
    assert len(tasks) == 1
    return f"content:{role}:{tasks[0]['ref']['id']}"


def force_offload(monkeypatch, enabled, threshold=100):
    if enabled:
        native = deep_runtime.FilesystemMiddleware
        monkeypatch.setattr(deep_runtime, 'FilesystemMiddleware',
                            lambda **kw: native(**kw, tool_token_limit_before_evict=threshold))


async def run_role(ws, role, script, refs, snapshot, text_model=None):
    if role == 'coordinator':
        driver = Driver(coordinator=script)
    else:
        args = {'subagent_type': role, 'description': 'Inspect synthetic tool delivery only.'}
        if role == 'reviewer':
            args = dict(review_call(snapshot, refs)['args'])
            args.pop('supervision_plugin', None)
        if role == 'layout':
            args['layout_snapshot_ref'] = snapshot
        driver = Driver(coordinator=[invoke('task', **args), AIMessage(content='Inspection ended.')],
                        **{role: script})

    def factory(name):
        return text_model if name == 'text_tool' and text_model is not None else driver(name)

    result = await deep_runtime.run_report(ws, factory)
    assert result['last_error'] is None, result
    assert len([c for c in driver.calls if c[0] == role]) == len(script)
    if role != 'coordinator':
        assert len([c for c in driver.calls if c[0] == 'coordinator']) == 2
    return driver


@pytest.mark.parametrize('role', ['coordinator', 'writer', 'reviewer', 'layout'])
@pytest.mark.parametrize('offload', [False, True], ids=['inline', 'native-offload'])
async def test_each_report_agent_receives_source_tail_or_recovers_exact_field(ws, monkeypatch, role, offload):
    _, _, refs, snapshot, _ = seed(ws)
    activate(ws)
    # Leave room for a 6000-character recovery page plus its identity metadata.
    # An artificial 100-token cap cannot carry even that metadata; see the
    # preserved first/second diagnostic runs. The source still exceeds this cap.
    force_offload(monkeypatch, offload, threshold=2000)
    literal = 'Synthetic source paragraph; ' * 1000 + 'TAIL: required guide is missing; no acceptance.'
    ws.store.set('manifest', {**ws.store.manifest, 'sources': [
        {'id': 's', 'title': 'Synthetic source', 'content': literal, 'coverage': 'partial'}]})
    with ws.store.connect() as db:
        db.execute('delete from source_blocks')
        db.execute('insert into source_blocks values (?,?,?,?)',
                   ('s', 0, json.dumps({'page': 1}), literal))
    observed = []
    recovered_parts = []

    def inspect_source(messages):
        message = reply(messages, 'read_source_page')
        shown = packet(message)
        original = ws.store.get('tool_observation:' + shown['observation_ref'])
        raw = json.loads(original['text'])
        assert original['owner'] == expected_owner(ws, role)
        assert raw['blocks'][0]['text'] == literal
        assert shown['sha256'] == hashlib.sha256(original['text'].encode()).hexdigest()
        assert shown['metadata']['coverage_note'] == raw['coverage_note']
        assert raw['coverage_note'] in wire_text(message)
        observed.append(shown['observation_ref'])
        if offload:
            assert message.additional_kwargs.get('report_controls_restored')
            assert not shown['complete_original_in_decision']
            assert literal not in wire_text(message)
            return invoke('read_tool_observation', observation_ref=shown['observation_ref'],
                          offset=0, characters=6000, field_path=['blocks', 0, 'text'])
        assert shown['complete_original_in_decision']
        assert shown['metadata']['blocks'][0]['text'] == literal
        assert literal in wire_text(message)
        return AIMessage(content='Exact source seen; no semantic verdict.')

    def inspect_recovery(messages):
        message = reply(messages, 'read_tool_observation')
        recovered = packet(message)
        offset = sum(map(len, recovered_parts))
        assert recovered['observation_ref'] == observed[0]
        assert recovered['offset'] == offset
        assert recovered['text'] == literal[offset:offset + 6000]
        assert recovered['field_sha256'] == hashlib.sha256(literal.encode()).hexdigest()
        assert recovered['complete_field'] is False
        assert recovered['complete_tool_result'] is False
        assert recovered['text'] in wire_text(message)
        recovered_parts.append(recovered['text'])
        end = sum(map(len, recovered_parts))
        if end < len(literal):
            assert recovered['next_offset'] == end
            return invoke('read_tool_observation', observation_ref=observed[0],
                          offset=end, characters=6000, field_path=['blocks', 0, 'text'])
        assert recovered['next_offset'] is None
        assert ''.join(recovered_parts) == literal
        return AIMessage(content='Exact selected field recovered; source remains partial.')

    script = [invoke('read_source_page', source_id='s', offset=0, limit=1), inspect_source]
    if offload:
        script.extend([inspect_recovery] * ((len(literal) + 5999) // 6000))
    driver = await run_role(ws, role, script, refs, snapshot)
    assert len(observed) == 1
    if offload:
        assert ''.join(recovered_parts) == literal
    assert 'read_source_page' in {s['name'] for s in driver.bindings[role][-1]}


@pytest.mark.parametrize('offload', [False, True], ids=['inline', 'native-offload'])
async def test_writer_generation_qualifications_reach_next_model_and_exact_save(ws, monkeypatch, offload):
    cs, _, refs, snapshot, _ = seed(ws)
    activate(ws)
    force_offload(monkeypatch, offload)
    warning = 'Evidence limitation; ' * 100 + 'TAIL: no supplied guide table; keep judgment unresolved.'
    payload = {'kind': 'block', 'body': {'text': 'Synthetic draft, not an approved report.'},
               'claim_kind': 'fact', 'qualifiers': {'limitations': warning}}
    model = Model(json.dumps(payload))
    saved = []

    def inspect_generation(messages):
        message = reply(messages, 'process_report_content')
        shown = packet(message)
        value = shown['metadata']
        assert value['outputs']['entries'][0]['qualifiers'] == payload['qualifiers']
        assert value['semantic_correctness_verified'] is False
        assert warning in wire_text(message)
        if offload:
            assert message.additional_kwargs.get('report_controls_restored')
        return invoke('save_text_node', operation_id='save-synthetic', text_work_id=value['text_work_id'])

    def inspect_saved(messages):
        value = packet(reply(messages, 'save_text_node'))
        ref = value['result']['refs']['text']
        assert cs.read(ref)['payload'] == payload
        saved.append(ref)
        return AIMessage(content='Exact qualified draft saved; not accepted.')

    await run_role(ws, 'writer', [invoke('process_report_content', operation_id='generate',
        objective='Draft from selected synthetic material; retain limitations.', object_type='ContentNode',
        input_refs=[refs['claim']]), inspect_generation, inspect_saved], refs, snapshot, model)
    assert len(model.calls) == 1 and len(saved) == 1


@pytest.mark.parametrize('offload', [False, True], ids=['inline', 'native-offload'])
async def test_reviewer_incomplete_judgment_reaches_next_model(ws, monkeypatch, offload):
    cs, _, refs, snapshot, _ = seed(ws)
    activate(ws)
    force_offload(monkeypatch, offload)
    warning = 'Unfinished comparison; ' * 100 + 'TAIL: assigned check remains incomplete.'
    raw = json.loads((await Model().ainvoke([])).content)
    item = raw['items'][0]
    item.update(execution_state='running', verdict=None, reason=warning, checked_requirement_indexes=[])
    item['coverage']['unchecked'] = [warning]
    item['check_results'][0].update(execution_state='blocked', remaining=warning)
    model = Model(json.dumps(raw))
    checked = []

    def inspect(messages):
        message = reply(messages, 'perform_assigned_review')
        value = packet(message)['metadata']
        assert warning in wire_text(message)
        stored = cs.read(value['review_ref'])['payload']['items'][0]
        assert stored['reason'] == warning and stored['verdict'] is None
        assert stored['execution_state'] != 'completed'
        delivered = value['items'][0]
        for field in ('reason', 'verdict', 'execution_state', 'coverage', 'check_results'):
            assert delivered[field] == stored[field]
        assert delivered['coverage']['unchecked'] == [warning]
        assert delivered['check_results'][0]['remaining'] == warning
        assert cs.read(value['review_ref'])['owner_id'] == expected_owner(ws, 'reviewer')
        if offload:
            assert message.additional_kwargs.get('report_controls_restored')
        checked.append(value['review_ref'])
        return AIMessage(content='Assigned review remains incomplete; no acceptance.')

    await run_role(ws, 'reviewer', [invoke('perform_assigned_review', operation_id='check',
        scope_ids=['rule-comparison'], source_selections=[], content_selections=[]), inspect],
        refs, snapshot, model)
    assert len(model.calls) == 1 and len(checked) == 1


@pytest.mark.parametrize('tool', ['read_learning_feedback', 'analyze_learning_material'])
async def test_optimizer_exact_feedback_and_analysis_tails(ws, tmp_path, tool):
    ws.store.set('learning_config', {'library_path': str(tmp_path / 'library'), 'customer_id': 'synthetic'})
    ws.store.set('learning_job', {'id': 'synthetic-job', 'state': 'running'})
    library, scope = binding(ws)
    literal = 'Synthetic feedback evidence; ' * 100 + 'TAIL: missing evidence is not permission to accept.'
    feedback = library.feedback(scope, {}, {}, literal, {}, literal)
    finding = 'Synthetic analysis limitation; ' * 100 + 'TAIL: unresolved and not verified.'
    model = Model(json.dumps({'findings': finding, 'project_fact': None}))
    if tool == 'read_learning_feedback':
        first = invoke(tool, feedback_id=feedback['id'], field='correction', offset=0, limit=6000)
    else:
        first = invoke(tool, question='Inspect synthetic evidence without claiming acceptance.',
                       feedback_selections=[{'feedback_id': feedback['id'], 'field': 'evidence'}])
    inspected = []

    def inspect(messages):
        message = reply(messages, tool)
        value = packet(message)
        if tool == 'read_learning_feedback':
            assert value['text'] == literal and value['next_offset'] is None
            assert literal in wire_text(message)
        else:
            assert value['payload'] == {'findings': finding, 'project_fact': None}
            assert value['fact_correctness_verified'] is False
            assert finding in wire_text(message)
            assert json.loads(model.calls[0][1][1])['evidence'][0]['text'] == literal
        inspected.append(tool)
        return AIMessage(content='Synthetic inspection only; no candidate or publication.')

    driver = Driver(optimizer=[first, inspect])
    await build_optimizer(ws, driver('optimizer'), text_model=model).ainvoke(
        {'messages': [('user', 'Inspect result delivery.')]}, config={'recursion_limit': 8})
    assert len(driver.calls) == 2 and inspected == [tool]
    assert len(model.calls) == (tool == 'analyze_learning_material')
    assert library.list_versions(scope) == []
