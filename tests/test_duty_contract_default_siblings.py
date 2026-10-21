"""Native sibling probes for declared defaults versus substantive unknowns.

All agent choices and independent responses are fake. The real registration,
middleware, task binding, parsing, adoption and storage paths remain in use.
An expected valid adoption that fails stays RED; no application repair here.
"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

from jsonschema.validators import validator_for
from langchain_core.messages import AIMessage, messages_to_dict
import pytest

from duty_probe_agent_decisions import dump
from report_agent.content_models import Evidence
from report_agent.deep_runtime import run_report
from report_agent.task_context import exact_task_context
from report_agent.task_supervision import reconcile
from test_agent_duty_trace_cases import action, result_value, tool_reply
from test_agent_result_delivery import run_role
from test_bounded_review import Model, review_call
from test_decision_data import activate
from test_deep_runtime import Driver
from test_hierarchical_content import seed
from test_task_supervision import ws, offline, global_reviewer_steps


def evidence_folder(tmp_path, request):
    root = Path(os.environ.get('DUTY_DEFAULT_SIBLINGS_EVIDENCE', str(tmp_path / 'evidence')))
    folder = root / request.node.name
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def retain(folder, capture, messages, call_id, *, structured=True):
    message = tool_reply(messages, call_id)
    raw = {'message': message.model_dump(), 'consumer_messages': messages_to_dict(messages)}
    dump(folder / (call_id + '-raw.json'), raw)
    if not structured:
        raw['value'] = {'native_text': message.content}
    else:
        try:
            raw['value'] = result_value(message)
        except json.JSONDecodeError:
            if message.status != 'error':
                raise
            raw['value'] = {'unparsed_native_error': message.content}
    capture.setdefault('observed', {})[call_id] = raw
    return raw['value']


def schema_errors(schema, value):
    validator = validator_for(schema)
    validator.check_schema(schema)
    return [{'path': list(e.absolute_path), 'message': e.message}
            for e in validator(schema).iter_errors(value)]


def finish_capture(folder, capture, driver, cs, originals, ws):
    capture.update(fake_models_only=True, application_repair_applied=False,
        role_calls=[{'role': r, 'step': s, 'messages': messages_to_dict(m)}
                    for r, s, m in driver.calls] if driver else [],
        registered_bindings=driver.bindings if driver else {},
        originals_before=originals)
    capture.setdefault('execution_error', None)
    dump(folder / 'raw-capture.json', capture)
    try:
        capture.update(objects_after=cs.list_objects(), events=ws.store.events(),
            originals_unchanged=all(cs.read(o['ref']) == o for o in originals))
    except Exception as exc:
        capture['observer_error'] = {'type': type(exc).__name__, 'message': str(exc)}
        raise
    finally:
        dump(folder / 'capture.json', capture)


@pytest.mark.parametrize('presence', ['explicit-null', 'omit-default-null'])
async def test_coordinator_evidence_default_equivalence(ws, tmp_path, request, presence):
    cs, _, refs, snapshot, members = seed(ws)
    activate(ws)
    originals = deepcopy(cs.list_objects())
    source = next(r for r in members if r['type'] == 'SourceArtifact')
    payload = {'source_refs': [source], 'locator': 's: text block 0',
               'excerpt': 'Class B permits 75 to 100.',
               'method': 'Exact synthetic rule; no engineering acceptance.'}
    response = json.dumps(payload)
    model, folder = Model(response), evidence_folder(tmp_path, request)
    capture, driver = {'presence': presence, 'raw_fake_response': response}, None

    def adopt_work(messages):
        value = retain(folder, capture, messages, 'co-produce')
        receipt = value.get('text_work_id')
        capture['receipt_id'] = receipt
        if not receipt:
            script.pop()
            return AIMessage(content='No adoptable receipt; keep the native refusal.')
        typed = deepcopy(ws.store.get('text_work_receipt:' + receipt))
        public = value['outputs']['entries'][0]
        submitted = {k: deepcopy(public[k]) for k in Evidence.model_fields}
        capture.update(typed_before=typed, complete_public_payload=deepcopy(submitted))
        if presence == 'omit-default-null':
            del submitted['extraction_ref']
        args = {'operation_id': 'co-adopt', 'objects': [
            {'client_key': 'adopted', 'type': 'Evidence', 'text_work_id': receipt,
             'text_work_index': 0, 'payload': submitted}]}
        capture['submitted_arguments'] = deepcopy(args)
        dump(folder / 'submitted-arguments.json', args)
        return action('commit_objects', 'co-adopt', **args)

    def after_adoption(messages):
        retain(folder, capture, messages, 'co-adopt')
        return AIMessage(content='Adoption observed; no reviewed report or acceptance.')

    script = [action('process_report_content', 'co-produce', operation_id='co-produce',
                     objective='Extract the exact supplied class B rule, with its actual source and locator.',
                     object_type='Evidence', input_refs=[source],
                     source_selections=[{'source_id': 's', 'offset': 0, 'limit': 1}]),
              adopt_work, after_adoption]
    try:
        driver = await run_role(ws, 'coordinator', script, refs, snapshot, model)
        packet = json.loads(model.calls[0][1][1])
        commit_schema = next(t['parameters'] for t in driver.bindings['coordinator'][-1]
                             if t['name'] == 'commit_objects')
        submitted = capture['submitted_arguments']['objects'][0]['payload']
        capture.update(independent_packet=packet, actual_commit_schema=commit_schema,
            producer_schema_errors=schema_errors(packet['output_schema'], payload),
            commit_schema_errors=schema_errors(commit_schema, capture['submitted_arguments']),
            normalized_submitted=Evidence.model_validate(submitted).model_dump(),
            typed_after=ws.store.get('text_work_receipt:' + capture['receipt_id']))
    except Exception as exc:
        capture['execution_error'] = {'type': type(exc).__name__, 'message': str(exc)}
        raise
    finally:
        capture['independent_calls'] = model.calls
        finish_capture(folder, capture, driver, cs, originals, ws)
    assert capture['originals_unchanged'] and len(model.calls) == 1
    assert capture['producer_schema_errors'] == capture['commit_schema_errors'] == []
    assert capture['normalized_submitted'] == capture['complete_public_payload']
    assert capture['typed_before'] == capture['typed_after']
    expected = capture['typed_before']['result']['payloads'][0]
    assert expected == capture['normalized_submitted']
    assert capture['typed_before']['result']['actor_id'] == 'content:coordinator'
    assert capture['typed_before']['result']['task_id'] == 'content-task:coordinator'
    old_refs = [o['ref'] for o in originals]
    saved = [o for o in cs.list_objects('Evidence') if o['ref'] not in old_refs]
    assert len(saved) == 1, 'VALID_COORDINATOR_DEFAULT_OMISSION_MUST_ADOPT_EXACT_CANDIDATE'
    assert saved[0]['payload'] == expected
    assert saved[0]['owner_id'] == capture['typed_before']['result']['actor_id'] == 'content:coordinator'
    assert saved[0]['task_id'] == 'content-task:coordinator'


@pytest.mark.parametrize('unknown', ['preserve', 'delete'])
async def test_writer_substantive_unknown_is_not_a_declared_default(ws, tmp_path, request, unknown):
    cs, _, refs, snapshot, _ = seed(ws)
    activate(ws)
    originals = deepcopy(cs.list_objects())
    payload = {'kind': 'block', 'body': {'text': 'The actual class is unresolved in the selected synthetic evidence.'},
               'qualifiers': {'actual_class': None, 'verified': False, 'measured_zero': 0,
                              'note': '', 'limit': 'No engineering acceptance.'}, 'claim_kind': 'inference'}
    response = json.dumps(payload)
    model, folder = Model(response), evidence_folder(tmp_path, request)
    capture, driver = {'unknown': unknown, 'raw_fake_response': response}, None

    def inspect_work(messages):
        value = retain(folder, capture, messages, 'writer-produce')
        receipt = value.get('text_work_id')
        capture['receipt_id'] = receipt
        if not receipt:
            del script[2:]
            return AIMessage(content='No adoptable receipt; preserve the native refusal.')
        typed = deepcopy(ws.store.get('text_work_receipt:' + receipt))
        envelope = json.loads(tool_reply(messages, 'writer-produce').content)
        capture.update(typed_before=typed, production_envelope=envelope)
        args = {'observation_ref': envelope['observation_ref'], 'offset': 0, 'characters': 6000}
        capture['recovery_arguments'] = deepcopy(args)
        return action('read_tool_observation', 'writer-recover', **args)

    def adopt_work(messages):
        recovered = retain(folder, capture, messages, 'writer-recover')
        envelope = capture['production_envelope']
        assert recovered['observation_ref'] == envelope['observation_ref']
        assert recovered['complete_tool_result'] is True and recovered['next_offset'] is None
        assert recovered['offset'] == 0 and recovered['end'] == recovered['total_characters'] == len(recovered['text'])
        assert hashlib.sha256(recovered['text'].encode('utf-8')).hexdigest() == recovered['sha256'] == envelope['sha256']
        original = json.loads(recovered['text'])
        candidate = original
        for key in envelope['metadata']['outputs']['entries'][0]['original_path']:
            candidate = candidate[key]
        submitted = {k: deepcopy(candidate[k]) for k in payload}
        capture.update(recovered_original=original, complete_public_payload=deepcopy(submitted))
        if unknown == 'delete':
            del submitted['qualifiers']['actual_class']
        args = {'operation_id': 'writer-adopt', 'objects': [
            {'client_key': 'adopted', 'type': 'ContentNode', 'text_work_id': capture['receipt_id'],
             'text_work_index': 0, 'payload': submitted}]}
        capture['submitted_arguments'] = deepcopy(args)
        dump(folder / 'submitted-arguments.json', args)
        return action('commit_objects', 'writer-adopt', **args)

    def after_adoption(messages):
        retain(folder, capture, messages, 'writer-adopt')
        return AIMessage(content='Native result observed; preserve actual technical uncertainty.')

    script = [action('process_report_content', 'writer-produce', operation_id='writer-produce',
                     objective='Explain the limits of the selected synthetic material; retain actual technical unknowns.',
                     object_type='ContentNode', input_refs=[refs['claim']]), inspect_work, adopt_work, after_adoption]
    try:
        driver = await run_role(ws, 'writer', script, refs, snapshot, model)
        packet = json.loads(model.calls[0][1][1])
        commit_schema = next(t['parameters'] for t in driver.bindings['writer'][-1]
                             if t['name'] == 'commit_objects')
        capture.update(independent_packet=packet, actual_commit_schema=commit_schema,
            producer_schema_errors=schema_errors(packet['output_schema'], payload),
            commit_schema_errors=schema_errors(commit_schema, capture['submitted_arguments']),
            typed_after=ws.store.get('text_work_receipt:' + capture['receipt_id']))
    except Exception as exc:
        capture['execution_error'] = {'type': type(exc).__name__, 'message': str(exc)}
        raise
    finally:
        capture['independent_calls'] = model.calls
        finish_capture(folder, capture, driver, cs, originals, ws)
    assert capture['originals_unchanged'] and len(model.calls) == 1
    assert capture['producer_schema_errors'] == capture['commit_schema_errors'] == []
    assert capture['complete_public_payload'] == payload
    assert capture['typed_before'] == capture['typed_after']
    task, = cs.list_objects('DelegatedTask')
    assert task['payload']['role'] == 'writer'
    assert task['owner_id'] == task['payload']['delegated_by'] == 'content:coordinator'
    assert task['payload']['write_scope'] == 'Only artifacts produced by this task; read other project artifacts.'
    assert capture['typed_before']['result']['actor_id'] == 'content:writer:' + task['ref']['id']
    assert capture['typed_before']['result']['task_id'] == task['ref']['id']
    old_refs = [o['ref'] for o in originals]
    saved = [o for o in cs.list_objects('ContentNode') if o['ref'] not in old_refs]
    if unknown == 'preserve':
        assert len(saved) == 1 and saved[0]['payload'] == payload
        assert saved[0]['owner_id'] == capture['typed_before']['result']['actor_id']
        assert saved[0]['task_id'] == task['ref']['id']
    else:
        raw = capture['observed']['writer-adopt']['message']
        assert 'TEXT_WORK_OUTPUT_CHANGED' in json.dumps(raw, ensure_ascii=False)
        assert saved == [], 'SUBSTANTIVE_UNKNOWN_DELETION_MUST_NOT_BE_ADOPTED'
    for value in [capture['complete_public_payload'], *[o['payload'] for o in saved]]:
        qualifiers = value['qualifiers']
        assert qualifiers['actual_class'] is None and qualifiers['verified'] is False
        assert type(qualifiers['measured_zero']) is int and qualifiers['measured_zero'] == 0
        assert isinstance(qualifiers['note'], str) and qualifiers['note'] == ''


@pytest.mark.parametrize('presence', ['explicit-null', 'omit-default-null'])
async def test_reviewer_resume_preserves_default_equivalent_assignment(ws, tmp_path, request, presence):
    cs, _, refs, snapshot, members = seed(ws)
    activate(ws)
    originals = deepcopy(cs.list_objects())
    source = next(r for r in members if r['type'] == 'SourceArtifact')
    first_args = deepcopy(review_call(snapshot, refs, reads=[source])['args'])
    first_args['supervision_plugin'] = None  # Fresh task selects no automatic follow-up plugin.
    first_args['review_requirements'][0]['presentation_reference_ref'] = None
    folder, capture = evidence_folder(tmp_path, request), {'presence': presence, 'first_arguments': first_args}
    unused_text_model = Model(AssertionError('This task-binding probe must not invoke text work.'))

    def resume(messages):
        retain(folder, capture, messages, 'review-create', structured=False)
        task, = cs.list_objects('DelegatedTask')
        capture['task_before_resume'] = deepcopy(task)
        args = deepcopy(first_args)
        args['resume_content_task_id'] = task['ref']['id']
        if presence == 'omit-default-null':
            del args['review_requirements'][0]['presentation_reference_ref']
        capture['resume_arguments'] = deepcopy(args)
        dump(folder / 'resume-arguments.json', args)
        return action('task', 'review-resume', **args)

    def read_assignment(messages, call_id):
        value = retain(folder, capture, messages, call_id)
        capture.setdefault('child_reads', []).append({'value': value, 'server_context': exact_task_context(ws, 'reviewer')})
        return AIMessage(content='Assigned checks were not performed; no review or acceptance claimed.')

    def parent_finish(messages):
        retain(folder, capture, messages, 'review-resume', structured=False)
        return AIMessage(content='The same review task remains unexecuted; no report acceptance.')

    driver = Driver(coordinator=[action('task', 'review-create', **first_args), resume, parent_finish])
    counter = global_reviewer_steps(driver, [
        action('read_task_assignment', 'assignment-first'),
        lambda messages: read_assignment(messages, 'assignment-first'),
        action('read_task_assignment', 'assignment-resumed'),
        lambda messages: read_assignment(messages, 'assignment-resumed')])
    try:
        result = await run_report(ws, lambda role: unused_text_model if role == 'text_tool' else driver(role))
        capture['run_result'] = result
        task_schema = next(t['parameters'] for t in driver.bindings['coordinator'][-1] if t['name'] == 'task')
        capture.update(actual_task_schema=task_schema,
            first_schema_errors=schema_errors(task_schema, first_args),
            resume_schema_errors=schema_errors(task_schema, capture['resume_arguments']))
        task, = cs.list_objects('DelegatedTask')
        capture['task_after_resume'] = deepcopy(task)
        capture['supervision'] = reconcile(cs, task['ref']['id'])
    except Exception as exc:
        capture['execution_error'] = {'type': type(exc).__name__, 'message': str(exc)}
        raise
    finally:
        capture['independent_calls'] = unused_text_model.calls
        finish_capture(folder, capture, driver, cs, originals, ws)
    assert capture['originals_unchanged'] and not unused_text_model.calls
    assert capture['run_result']['last_error'] is None
    assert capture['first_schema_errors'] == capture['resume_schema_errors'] == []
    assert counter['n'] == 4 and len(capture['child_reads']) == 2
    assert capture['task_before_resume'] == capture['task_after_resume']
    for call_id in ['review-create', 'review-resume']:
        parent = capture['observed'][call_id]['message']
        assert parent['status'] == 'success'
        assert parent['content'] == 'Assigned checks were not performed; no review or acceptance claimed.'
    task = capture['task_after_resume']
    assert task['payload']['role'] == 'reviewer'
    assert task['owner_id'] == task['payload']['delegated_by'] == 'content:coordinator'
    assert task['payload']['write_scope'] == 'Only artifacts produced by this task; read other project artifacts.'
    assert cs.list_objects('ReviewRecord') == []
    for entry, call_id in zip(capture['child_reads'], ['review-create', 'review-resume'], strict=True):
        value, context = entry['value'], entry['server_context']
        assert isinstance(value.get('assignment'), dict), 'PUBLIC_INLINE_ASSIGNMENT_REQUIRED_FOR_THIS_FIXTURE'
        assert value['task_id'] == task['ref']['id']
        assert value['assignment'] == context['assignment'] == task['payload']
        assert context['role'] == 'reviewer'
        assert context['actor_id'] == 'content:reviewer:' + task['ref']['id']
        assert value['current_invocation']['delegate_operation_id'] == 'delegate:' + call_id
        assert context['current_invocation'] == value['current_invocation']
    assert not capture['supervision']['execution_complete']
    assert len(capture['supervision']['remaining']) == 1
