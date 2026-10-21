"""Advertised table schema versus native production and exact adoption.

Only the row's JSON type changes. Equal lengths deliberately exercise the
boundary that rectangularity-only checks miss. Raw invalid fake output is not
evidence about real-model frequency; no rendering or report acceptance is tested.
"""
from copy import deepcopy
import json
import os
from pathlib import Path

from jsonschema.validators import validator_for
from langchain_core.messages import AIMessage, messages_to_dict
import pytest

from duty_probe_agent_decisions import dump
from test_agent_duty_trace_cases import action, result_value, tool_reply
from test_agent_result_delivery import run_role
from test_bounded_review import Model
from test_decision_data import activate
from test_hierarchical_content import seed
from test_task_supervision import ws, offline


@pytest.mark.parametrize('row_type', ['array', 'string'])
async def test_native_table_row_shape_matches_actual_advertised_schema(ws, tmp_path, request, row_type):
    cs, _, refs, snapshot, _ = seed(ws)
    activate(ws)
    originals = deepcopy(cs.list_objects())
    row = ['w', 'x', 'y', 'z'] if row_type == 'array' else 'wxyz'
    payload = {'kind': 'table', 'body': {'columns': ['C1', 'C2', 'C3', 'C4'], 'rows': [row]},
               'qualifiers': {'status': 'Synthetic structural probe; not reviewed or engineering accepted.'},
               'claim_kind': 'structure'}
    response = json.dumps({'payloads': [payload], 'generation_notes': []})
    model = Model(response)
    root = Path(os.environ.get('DUTY_TABLE_ROW_EVIDENCE', str(tmp_path / 'evidence')))
    folder = root / request.node.name
    folder.mkdir(parents=True, exist_ok=True)
    observed, driver, execution_error = {}, None, None

    def retain(messages, call_id):
        message = tool_reply(messages, call_id)
        raw = {'message': message.model_dump(), 'consumer_messages': messages_to_dict(messages)}
        observed[call_id] = raw
        dump(folder / (call_id + '-raw.json'), raw)
        try:
            value = result_value(message)
        except json.JSONDecodeError:
            if message.status != 'error':
                raise
            value = {'unparsed_native_error': message.content}
        raw['value'] = value
        return value

    def consume_work(messages):
        value = retain(messages, 'table-row-produce')
        receipt = value.get('text_work_id')
        observed['receipt_id'] = receipt
        if receipt:
            observed['typed_receipt_before_adoption'] = deepcopy(ws.store.get('text_work_receipt:' + receipt))
            dump(folder / 'typed-receipt-before-adoption.json', observed['typed_receipt_before_adoption'])
            return action('save_text_node', 'table-row-adopt', operation_id='table-row-adopt',
                          text_work_id=receipt, text_work_index=0)
        # A genuine refusal has no candidate to adopt. Remove the unused
        # readback callback so run_role verifies this shorter native branch.
        script.pop()
        return AIMessage(content='The producer returned no adoptable receipt; original response retained.')

    def consume_adoption(messages):
        retain(messages, 'table-row-adopt')
        return AIMessage(content='Native adoption response retained; structural correctness is still under test.')

    script = [action('process_report_content', 'table-row-produce', operation_id='table-row-produce',
                     objective='Format the synthetic four-cell record w, x, y, z as four columns, preserving order. Structural probe only.',
                     object_type='ContentNode', output_count=1, input_refs=[refs['claim']]),
              consume_work, consume_adoption]
    try:
        driver = await run_role(ws, 'writer', script, refs, snapshot, model)
    except Exception as exc:
        execution_error = {'type': type(exc).__name__, 'message': str(exc)}
        raise
    finally:
        capture = {'row_type': row_type, 'raw_fake_response': response, 'supplied_payload': payload,
                   'independent_calls': model.calls, 'observed': observed,
                   'execution_error': execution_error, 'originals_before': originals,
                   'role_calls': [{'role': role, 'step': step, 'messages': messages_to_dict(messages)}
                                  for role, step, messages in driver.calls] if driver else [],
                   'application_repair_applied': False, 'fake_model_only': True}
        dump(folder / 'raw-capture.json', capture)
        try:
            packet = json.loads(model.calls[0][1][1])
            schema = packet['output_schema']
            validator_class = validator_for(schema)
            validator_class.check_schema(schema)
            errors = list(validator_class(schema).iter_errors(json.loads(response)))
            capture.update(actual_independent_packet=packet,
                schema_errors=[{'path': list(e.absolute_path), 'schema_path': list(e.absolute_schema_path),
                                'validator': e.validator, 'message': e.message} for e in errors],
                content_objects=cs.list_objects(), events=ws.store.events(),
                originals_unchanged=all(cs.read(o['ref']) == o for o in originals))
        except Exception as exc:
            capture['observer_error'] = {'type': type(exc).__name__, 'message': str(exc)}
            raise
        finally:
            dump(folder / 'capture.json', capture)
    assert len(model.calls) == 1 and capture['originals_unchanged']
    original_refs = [o['ref'] for o in originals]
    adopted = [o for o in capture['content_objects'] if o['ref']['type'] == 'ContentNode'
               and o['ref'] not in original_refs]
    if row_type == 'array':
        assert capture['schema_errors'] == [], 'NORMAL_ROW_REJECTED_BY_ADVERTISED_SCHEMA'
        assert observed['receipt_id'] and len(adopted) == 1
        assert adopted[0]['payload'] == payload
        assert observed['typed_receipt_before_adoption']['result']['payloads'] == [payload]
    else:
        assert capture['schema_errors'], 'STRING_ROW_MUST_FAIL_ACTUAL_ADVERTISED_ARRAY_SCHEMA'
        assert not observed['receipt_id'], 'INVALID_TABLE_ROW_MUST_NOT_BECOME_COMPLETED_CANDIDATE'
        assert adopted == [], 'INVALID_TABLE_ROW_MUST_NOT_BE_ADOPTED'
        assert not any(e['kind'] == 'text_work_completed' for e in capture['events'])
