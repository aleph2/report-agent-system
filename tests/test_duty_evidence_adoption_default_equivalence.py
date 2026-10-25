"""R30-derived optional-null equivalence through native production and adoption.

Only extraction_ref key presence differs at adoption. Public schemas and the
existing Evidence default semantics supply independent preconditions; an actual
refusal remains a failed expectation, not a passing rejection test.
"""
from copy import deepcopy
import json
import os
from pathlib import Path

from jsonschema.validators import validator_for
from langchain_core.messages import AIMessage, messages_to_dict
import pytest

from duty_probe_agent_decisions import dump
from report_agent.content_models import Evidence
from test_agent_duty_trace_cases import action, result_value, tool_reply
from test_agent_result_delivery import run_role
from test_bounded_review import Model
from test_decision_data import activate
from test_hierarchical_content import seed
from test_task_supervision import ws, offline


@pytest.mark.parametrize('field_presence', ['explicit-null', 'omit-default-null'])
async def test_native_evidence_default_equivalence_preserves_exact_candidate(ws, tmp_path, request, field_presence):
    cs, _, refs, snapshot, members = seed(ws)
    activate(ws)
    originals = deepcopy(cs.list_objects())
    source = next(ref for ref in members if ref['type'] == 'SourceArtifact')
    raw_payload = {'source_refs': [source], 'locator': 's: text block 0',
                   'excerpt': 'Class B permits 75 to 100.',
                   'method': 'Extract the exact selected synthetic rule; no engineering acceptance.'}
    raw_response = json.dumps(raw_payload)
    model = Model(raw_response)
    root = Path(os.environ.get('DUTY_EVIDENCE_DEFAULT_EVIDENCE', str(tmp_path / 'evidence')))
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
        value = retain(messages, 'defaults-produce')
        receipt = value.get('text_work_id')
        observed['receipt_id'] = receipt
        if not receipt:
            script.pop()
            return AIMessage(content='No adoptable receipt was returned; preserve the native refusal.')
        observed['typed_receipt_before_adoption'] = deepcopy(ws.store.get('text_work_receipt:' + receipt))
        dump(folder / 'typed-receipt-before-adoption.json', observed['typed_receipt_before_adoption'])
        # Copy only business fields from the actual complete public output,
        # rather than supplying private receipt data to the scripted caller.
        entry = value['outputs']['entries'][0]
        public_payload = {key: deepcopy(entry[key]) for key in Evidence.model_fields}
        observed['complete_public_payload'] = deepcopy(public_payload)
        submitted = deepcopy(public_payload)
        if field_presence == 'omit-default-null':
            del submitted['extraction_ref']
        args = {'operation_id': 'defaults-adopt', 'objects': [
            {'client_key': 'adopted', 'type': 'Evidence', 'text_work_id': receipt,
             'text_work_index': 0, 'payload': submitted}]}
        observed['commit_args'] = deepcopy(args)
        dump(folder / 'submitted-arguments.json', args)
        return action('commit_objects', 'defaults-adopt', **args)

    def consume_adoption(messages):
        retain(messages, 'defaults-adopt')
        return AIMessage(content='Native adoption response captured; no report or engineering acceptance claimed.')

    script = [action('process_report_content', 'defaults-produce', operation_id='defaults-produce',
                     objective='Extract the exact selected synthetic class B rule as one Evidence payload, retaining its source and locator.',
                     object_type='Evidence', output_count=1, input_refs=[source],
                     source_selections=[{'source_id': 's', 'offset': 0, 'limit': 1}]),
              consume_work, consume_adoption]
    try:
        driver = await run_role(ws, 'writer', script, refs, snapshot, model)
    except Exception as exc:
        execution_error = {'type': type(exc).__name__, 'message': str(exc)}
        raise
    finally:
        capture = {'field_presence': field_presence, 'raw_fake_response': raw_response,
                   'independent_calls': model.calls, 'observed': observed,
                   'execution_error': execution_error, 'originals_before': originals,
                   'role_calls': [{'role': role, 'step': step, 'messages': messages_to_dict(messages)}
                                  for role, step, messages in driver.calls] if driver else [],
                   'application_repair_applied': False, 'fake_model_only': True}
        dump(folder / 'raw-capture.json', capture)
        try:
            packet = json.loads(model.calls[0][1][1])
            output_validator = validator_for(packet['output_schema'])
            output_validator.check_schema(packet['output_schema'])
            output_errors = list(output_validator(packet['output_schema']).iter_errors(raw_payload))
            schema = next(t['parameters'] for t in driver.bindings['writer'][-1]
                          if t['name'] == 'commit_objects')
            validator = validator_for(schema)
            validator.check_schema(schema)
            errors = list(validator(schema).iter_errors(observed['commit_args']))
            typed = observed['typed_receipt_before_adoption']
            submitted = observed['commit_args']['objects'][0]['payload']
            capture.update(actual_independent_packet=packet, actual_commit_schema=schema,
                producer_schema_errors=[{'path': list(e.absolute_path), 'message': e.message} for e in output_errors],
                commit_schema_errors=[{'path': list(e.absolute_path), 'message': e.message} for e in errors],
                existing_Evidence_schema=Evidence.model_json_schema(),
                normalized_submitted_payload=Evidence.model_validate(submitted).model_dump(),
                content_objects=cs.list_objects(), events=ws.store.events(),
                typed_receipt_after_adoption=ws.store.get('text_work_receipt:' + observed['receipt_id']),
                originals_unchanged=all(cs.read(o['ref']) == o for o in originals))
        except Exception as exc:
            capture['observer_error'] = {'type': type(exc).__name__, 'message': str(exc)}
            raise
        finally:
            dump(folder / 'capture.json', capture)

    expected = typed['result']['payloads'][0]
    assert len(model.calls) == 1 and capture['originals_unchanged']
    assert capture['producer_schema_errors'] == [], 'PRODUCER_FIXTURE_MUST_MATCH_ACTUAL_OUTPUT_SCHEMA'
    assert capture['commit_schema_errors'] == [], 'BOTH_ARGUMENT_VARIANTS_MUST_BE_VALID_PUBLIC_INPUT'
    assert capture['normalized_submitted_payload'] == expected == observed['complete_public_payload']
    assert capture['existing_Evidence_schema']['properties']['extraction_ref']['default'] is None
    assert ('extraction_ref' in submitted) == (field_presence == 'explicit-null')
    assert observed['defaults-produce']['value']['outputs']['complete'] is True
    assert observed['defaults-produce']['value']['outputs']['entries'][0]['body_deferred'] is False
    assert capture['typed_receipt_after_adoption'] == typed
    original_refs = [o['ref'] for o in originals]
    adopted = [o for o in capture['content_objects'] if o['ref']['type'] == 'Evidence'
               and o['ref'] not in original_refs]
    assert len(adopted) == 1, 'VALID_EQUIVALENT_DEFAULT_OMISSION_MUST_ADOPT_EXACT_CANDIDATE'
    assert adopted[0]['payload'] == expected
    assert adopted[0]['owner_id'] == typed['result']['actor_id']
    task, = [o for o in capture['content_objects'] if o['ref']['type'] == 'DelegatedTask']
    assert typed['result']['task_id'] == task['ref']['id']
