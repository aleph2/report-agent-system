"""P16.C1 native continuation after a qualifiers-only pass leaves body feedback open.

Two scripted, legal routes: exact full-node regeneration/adoption or an open
handoff. This proves finite program transport, not autonomous route selection,
semantic title interpretation, exported Word appearance, or report acceptance.
"""
from copy import deepcopy
import json

from langchain_core.messages import AIMessage
import pytest

from report_agent.deep_runtime import run_report
from test_agent_duty_repro_artifacts import save_evidence
from test_agent_duty_trace_cases import action, result_value, tool_reply
from test_decision_data import activate
from test_deep_runtime import Driver
from test_hierarchical_content import seed
from test_task_supervision import ws, offline
from test_text_work_scoped_revision import TABLE, DELTA


FEEDBACK = 'Correct the body title Assessment to Updated Assessment; retain technical uncertainty.'
SCOPED = {**deepcopy(TABLE), **deepcopy(DELTA)}
FULL = {**deepcopy(SCOPED), 'body': {**deepcopy(TABLE['body']), 'title': 'Updated Assessment'}}


@pytest.mark.parametrize('route', ['full-node-adoption', 'open-handoff'])
async def test_native_body_feedback_continuation_keeps_exact_result_and_remaining(ws, request, route):
    cs, _, refs, snapshot, members = seed(ws)
    source = next(r for r in members if r['type'] == 'SourceArtifact')
    originals = {json.dumps(r, sort_keys=True): deepcopy(cs.read(r)) for r in [snapshot, *members]}
    original_sources = deepcopy(ws.store.manifest['sources'])
    activate(ws)
    observed = {'case': 'P16.C1-body-feedback-continuation', 'route': route, 'feedback': FEEDBACK,
        'scripted_route_not_model_autonomy': True, 'body_title_visibility_not_tested': True,
        'expected_base': deepcopy(TABLE), 'expected_scoped': deepcopy(SCOPED),
        'expected_full': deepcopy(FULL), 'producer_packets': [], 'producer_raws': [],
        'receipts_before_continuation': {}, 'assets': []}

    def received(messages, call_id):
        message = tool_reply(messages, call_id)
        observed.setdefault('public_messages', {})[call_id] = message.model_dump()
        assert message.status == 'success', message
        value = result_value(message)
        assert value.get('ok') is not False, value
        return value

    def output_directory(value, expected):
        assert value['state'] == 'completed' and value['details_deferred'] is True
        assert value['outputs']['complete'] and value['outputs']['total'] == 1
        entry, = value['outputs']['entries']
        assert entry['index'] == 0 and entry['body_deferred'] is True
        assert entry['original_path'] == ['payloads', 0]
        for field in ('kind', 'claim_kind', 'qualifiers'):
            assert entry[field] == expected[field]
        stored = deepcopy(ws.store.get('text_work_receipt:' + value['text_work_id']))
        assert stored['state'] == 'completed' and stored['result']['payloads'] == [expected]
        observed['receipts_before_continuation'][value['text_work_id']] = stored

    def producer(messages):
        packet = json.loads(messages[-1].content)
        index = len(observed['producer_packets'])
        observed['producer_packets'].append(packet)
        assert packet['actor']['role'] == 'writer'
        if index == 0:
            assert 'revision' not in packet
            expected = TABLE
        elif index == 1:
            assert packet['objective'] == FEEDBACK
            assert packet['revision']['scope'] == 'qualifiers'
            assert [t['ref'] for t in packet['revision']['targets']] == [observed['base']['ref']]
            target = next(e['object'] for e in packet['evidence']
                          if e.get('object', {}).get('ref') == observed['base']['ref'])
            assert target == observed['base'] and target['payload'] == TABLE
            expected = DELTA
        else:
            assert index == 2 and route == 'full-node-adoption'
            assert packet['objective'] == FEEDBACK and 'revision' not in packet
            objects = [e['object'] for e in packet['evidence'] if 'object' in e]
            assert observed['scoped'] in objects and cs.read(source) in objects
            expected = FULL
        observed['producer_raws'].append(deepcopy(expected))
        return AIMessage(content=json.dumps(expected))

    def adopt_base(messages):
        work = received(messages, 'produce-base')
        output_directory(work, TABLE)
        return action('save_text_node', 'save-base', operation_id='body-feedback-base-save',
                      text_work_id=work['text_work_id'])

    def request_qualifiers(messages):
        ref = received(messages, 'save-base')['result']['refs']['text']
        observed['base'] = deepcopy(cs.read(ref))
        assert observed['base']['payload'] == TABLE
        return action('process_report_content', 'produce-qualifiers', operation_id='body-feedback-qualifiers',
            objective=FEEDBACK, object_type='ContentNode', revision={'scope': 'qualifiers', 'targets': [ref]})

    def adopt_qualifiers(messages):
        work = received(messages, 'produce-qualifiers')
        output_directory(work, SCOPED)
        return action('save_text_node', 'save-qualifiers', operation_id='body-feedback-qualifiers-save',
            text_work_id=work['text_work_id'], previous_ref=observed['base']['ref'])

    def read_scoped(messages):
        ref = received(messages, 'save-qualifiers')['result']['refs']['text']
        observed['scoped'] = deepcopy(cs.read(ref))
        assert ref == {**observed['base']['ref'], 'version': 2}
        assert observed['scoped']['previous_ref'] == observed['base']['ref']
        assert observed['scoped']['payload'] == SCOPED
        return action('read_context', 'writer-read-scoped', target_ref=ref)

    def choose_continuation(messages):
        actual = received(messages, 'writer-read-scoped')['result']['objects']
        assert actual == [observed['scoped']]
        assert actual[0]['payload']['body'] == TABLE['body']
        assert actual[0]['payload']['body']['title'] == 'Assessment'
        assert actual[0]['payload']['qualifiers'] == DELTA['qualifiers']
        observed['body_request_unfulfilled_before_continuation'] = True
        observed['before_continuation_nodes'] = deepcopy(cs.list_objects('ContentNode'))
        if route == 'full-node-adoption':
            return action('process_report_content', 'produce-full', operation_id='body-feedback-full-node',
                objective=FEEDBACK, object_type='ContentNode', input_refs=[observed['scoped']['ref'], source])
        return action('record_handoff', 'open-handoff', operation_id='body-feedback-handoff',
            target_ref=observed['scoped']['ref'], problem=FEEDBACK,
            evidence=['Exact current body.title is Assessment; qualifiers-only revision did not alter the body.'],
            impact='Requested body title change remains unresolved; technical uncertainty must remain.',
            handling_state='open')

    def adopt_full(messages):
        work = received(messages, 'produce-full')
        output_directory(work, FULL)
        observed['full_work'] = work
        return action('save_text_node', 'save-full', operation_id='body-feedback-full-save',
            text_work_id=work['text_work_id'], previous_ref=observed['scoped']['ref'])

    def writer_return(messages):
        if route == 'full-node-adoption':
            ref = received(messages, 'save-full')['result']['refs']['text']
            current = cs.read(ref)
            assert ref == {**observed['base']['ref'], 'version': 3}
            assert current['previous_ref'] == observed['scoped']['ref']
            assert current['payload'] == FULL
            result = {'current_ref': ref, 'body_feedback': FEEDBACK,
                      'body_request_state': 'field_updated', 'remaining_body_request': [],
                      'technical_qualifiers': DELTA['qualifiers'], 'rendered_title_verified': False}
        else:
            ref = received(messages, 'open-handoff')['result']['handling_ref']
            handling = cs.read(ref)
            observed['handling'] = deepcopy(handling)
            assert handling['payload']['target_ref'] == observed['scoped']['ref']
            assert handling['payload']['problem'] == FEEDBACK and handling['payload']['handling_state'] == 'open'
            assert cs.list_objects('ContentNode') == observed['before_continuation_nodes']
            result = {'current_ref': observed['scoped']['ref'], 'handling_ref': ref, 'body_feedback': FEEDBACK,
                      'body_request_state': 'open', 'remaining_body_request': [FEEDBACK],
                      'technical_qualifiers': DELTA['qualifiers'], 'rendered_title_verified': False}
        observed['writer_result'] = result
        return AIMessage(content=json.dumps(result))

    def parent_read(messages):
        public = received(messages, 'body-writer')
        observed['parent_return'] = public
        assert public == observed['writer_result']
        return action('read_context', 'parent-read-current', target_ref=public['current_ref'])

    def parent_current(messages):
        value = received(messages, 'parent-read-current')
        observed['parent_current_read'] = value
        current, = value['result']['objects']
        assert current['ref'] == observed['parent_return']['current_ref']
        assert current['owner_id'] == observed['base']['owner_id'] == observed['scoped']['owner_id']
        assert current['task_id'] == observed['base']['task_id'] == observed['scoped']['task_id']
        assert current['payload'] == (FULL if route == 'full-node-adoption' else SCOPED)
        if route == 'open-handoff':
            return action('read_feedback', 'parent-read-handoff')
        assert observed['parent_return']['remaining_body_request'] == []
        return AIMessage(content='Body title field saved in owned version 3; technical uncertainty remains. No exported title or report acceptance checked.')

    def parent_handoff(messages):
        value = received(messages, 'parent-read-handoff')
        observed['parent_feedback_read'] = value
        records = value['result']['records']
        assert records == [observed['handling']]
        assert records[0]['payload']['handling_state'] == 'open'
        assert records[0]['payload']['problem'] == FEEDBACK
        assert records[0]['payload']['target_ref'] == observed['parent_return']['current_ref']
        assert observed['parent_return']['remaining_body_request'] == [FEEDBACK]
        return AIMessage(content='Body feedback remains open in the saved HandlingRecord; current title remains Assessment. Technical uncertainty retained.')

    writer = [action('process_report_content', 'produce-base', operation_id='body-feedback-base',
        objective='Prepare the synthetic table with its original technical uncertainty.',
        object_type='ContentNode', input_refs=[source]), adopt_base, request_qualifiers,
        adopt_qualifiers, read_scoped, choose_continuation]
    if route == 'full-node-adoption':
        writer.append(adopt_full)
    writer.append(writer_return)
    parent = [action('task', 'body-writer', subagent_type='writer',
        description=FEEDBACK + ' Preserve exact owned versions and technical uncertainty; leave unresolved body work explicit.'),
        parent_read, parent_current]
    if route == 'open-handoff':
        parent.append(parent_handoff)
    driver = Driver(coordinator=parent, writer=writer, text_tool=[producer])
    try:
        observed['runtime_result'] = await run_report(ws, driver)
        assert observed['runtime_result']['last_error'] is None, observed['runtime_result']
        assert 'parent_current_read' in observed
        assert len(observed['producer_packets']) == (3 if route == 'full-node-adoption' else 2)
        assert cs.read(observed['base']['ref']) == observed['base']
        assert cs.read(observed['scoped']['ref']) == observed['scoped']
        assert originals == {key: cs.read(json.loads(key)) for key in originals}
        assert ws.store.manifest['sources'] == original_sources
        for receipt_id, before in observed['receipts_before_continuation'].items():
            assert ws.store.get('text_work_receipt:' + receipt_id) == before
        with ws.store.connect() as db:
            head = db.execute('SELECT version FROM content_heads WHERE type=? AND id=?',
                ('ContentNode', observed['base']['ref']['id'])).fetchone()[0]
        assert head == (3 if route == 'full-node-adoption' else 2)
        assert len(cs.list_objects('HandlingRecord')) == (0 if route == 'full-node-adoption' else 1)
        assert not cs.list_objects('ReviewRecord')
        observed['old_versions_source_and_receipts_unchanged'] = True
    finally:
        observed['content_after'] = cs.list_objects('ContentNode')
        observed['handling_after'] = cs.list_objects('HandlingRecord')
        save_evidence(request, ws, observed, driver)
