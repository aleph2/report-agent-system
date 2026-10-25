"""Native graph checks for paid-output failure classification; no real model calls."""
import json
import pytest
from langchain_core.messages import AIMessage, ToolMessage
from report_agent.deep_runtime import run_report
from report_agent.tool_argument_feedback import compact_native_tool_error
from test_deep_runtime import Driver, invoke, observation
from test_text_work import writer_call, content
from test_task_supervision import ws


async def test_received_invalid_output_is_not_reported_as_unexecuted_arguments(ws):
    bad = content()
    del bad['claim_kind']
    feedback = []
    def inspect(messages):
        error = observation(messages, 'process_report_content')
        feedback.append(error)
        assert error['code'] == 'TEXT_WORK_OUTPUT_CONTRACT_INVALID'
        assert error.get('execution_state') != 'not_executed'
        assert 'raw_operation=' in error['message']
        return AIMessage(content='Received invalid tool output remains unadopted.')
    driver = Driver(coordinator=[AIMessage(content='', tool_calls=[writer_call()]),
        AIMessage(content='Preserved the known output failure; no report acceptance.')],
        writer=[invoke('process_report_content', operation_id='bad-output', objective='Describe selected rule',
            object_type='ContentNode', source_selections=[{'source_id':'s'}]), inspect],
        text_tool=[AIMessage(content=json.dumps(bad))])
    await run_report(ws, driver)
    assert feedback
    assert feedback[0]['code'] == 'TEXT_WORK_OUTPUT_CONTRACT_INVALID'
    assert feedback[0].get('execution_state') != 'not_executed'
    assert sum(role == 'text_tool' for role, _, _ in driver.calls) == 1
    with ws.store.connect() as db:
        failures=[json.loads(value) for value, in db.execute("select value from state where key like 'text_work:%:bad-output'")]
    assert len(failures)==1 and failures[0]['state']=='known_failed'
    assert failures[0]['raw_response_received'] is True
    assert ws.store.analysis(failures[0]['operation'])['analysis'] == json.dumps(bad)
    import jsonschema
    actual = next(e['data']['input']['output_schema'] for e in ws.store.events()
                  if e['kind']=='evidence_analysis_input')
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({**content(), 'body': {'paragraphs':['Wrong rendered field']}}, actual)


def test_kind_body_invariants_are_machine_visible_in_output_and_adoption_schema():
    import jsonschema
    from report_agent.content_models import ContentNode
    from report_agent.content_inputs import NodeInput
    for schema in (ContentNode.model_json_schema(), NodeInput.model_json_schema()):
        for kind, valid_body in [('report', {'text':'Cover'}), ('block', {'text':'Actual text'}),
            ('table', {'columns':['Name'], 'rows':[['Value']]}),
            ('figure', {'source_id':'s', 'caption':'Caption', 'page':1})]:
            valid = {**content(), 'kind':kind, 'body':valid_body}
            jsonschema.validate(valid, schema)
            invalid = {**valid, 'body': {'paragraphs':['Actual text']}}
            with pytest.raises(jsonschema.ValidationError):
                jsonschema.validate(invalid, schema)


def test_generic_native_error_text_alone_cannot_establish_nonexecution(ws):
    message=ToolMessage("Error invoking tool 'example' with error: field: Field required",
        name='example',tool_call_id='known-handler-validation',status='error')
    result=json.loads(compact_native_tool_error(message,ws.store).content)
    assert result['code']=='NATIVE_TOOL_VALIDATION_ERROR'
    assert result['execution_state']=='not_established'
    assert 'receipt' in result['note']
