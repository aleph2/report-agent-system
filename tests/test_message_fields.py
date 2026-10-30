"""One field definition must explain schema, dictionary and boundary errors."""
import pytest


def test_review_dictionary_comes_from_the_field_definitions():
    from report_agent.message_fields import field_dictionary
    from report_agent.review_message import ReviewMessage
    dictionary = field_dictionary(ReviewMessage)
    schema = ReviewMessage.model_json_schema()
    assert set(dictionary) == set(schema['properties'])
    for key, definition in dictionary.items():
        assert definition['description'] == schema['properties'][key]['description']
        assert definition['required'] == (key in schema.get('required', []))
        assert definition['schema'] == schema['properties'][key]
    assert dictionary['verdict']['nullable']
    assert not dictionary['evidence_indexes']['nullable']
    assert not dictionary['remaining_work']['required']
    assert dictionary['remaining_work']['default'] == ''
    assert 'operation_id' not in dictionary and 'receipt_id' not in dictionary


@pytest.mark.parametrize('key', ['execution_state', 'assessment', 'evidence_indexes', 'remaining_work'])
def test_review_type_errors_are_explained_by_the_same_dictionary(key):
    from report_agent.message_fields import validate_message
    from report_agent.review_message import ReviewMessage
    from report_agent.errors import ActionRejected
    value = {'execution_state': 'completed', 'verdict': 'satisfied',
             'assessment': 'Compared the actual input.', 'evidence_indexes': [0]}
    value[key] = None
    with pytest.raises(ActionRejected) as failure:
        validate_message(ReviewMessage, value)
    assert key in str(failure.value)


@pytest.mark.parametrize('update,code,fields', [
    ({'assessment': ' '}, 'ASSESSMENT_REQUIRED', ['assessment']),
    ({'execution_state': 'not_started'}, 'NOT_STARTED_VERDICT_MUST_BE_NULL', ['execution_state', 'verdict']),
    ({'execution_state': 'partial'}, 'SATISFIED_REQUIRES_COMPLETED', ['execution_state', 'verdict']),
    ({'execution_state': 'blocked', 'verdict': None}, 'REMAINING_WORK_REQUIRED', ['execution_state', 'remaining_work']),
    ({'remaining_work': 'Still investigating.'}, 'COMPLETED_REMAINING_WORK_CONFLICT', ['execution_state', 'remaining_work']),
    ({'evidence_indexes': []}, 'JUDGMENT_EVIDENCE_REQUIRED', ['verdict', 'evidence_indexes']),
    ({'evidence_indexes': [0, 0]}, 'INVALID_EVIDENCE_SELECTION', ['evidence_indexes']),
])
def test_root_rejections_explain_business_fields_without_echoing_input(update, code, fields):
    import json
    from report_agent.message_fields import validate_message
    from report_agent.review_message import ReviewMessage
    from report_agent.errors import ActionRejected
    value = {'execution_state': 'completed', 'verdict': 'satisfied',
        'assessment': 'PRIVATE_SYNTHETIC_INPUT', 'evidence_indexes': [0], **update}
    with pytest.raises(ActionRejected) as caught:
        validate_message(ReviewMessage, value)
    diagnostic, = caught.value.diagnostic['fields']
    assert diagnostic['field'] == [] and diagnostic['reason'] == code
    assert diagnostic['related_fields'] == fields and diagnostic['message']
    assert code in str(caught.value)
    assert 'PRIVATE_SYNTHETIC_INPUT' not in json.dumps(caught.value.diagnostic)


def test_field_dictionary_explains_selectors_and_remains_strict_codec_compatible():
    from report_agent.review_message import ReviewMessage
    from report_agent.co_review_message import CoTaskMessage
    from report_agent.deepseek_strict import StrictCodec
    from report_agent.message_fields import field_dictionary
    reviewer, co = field_dictionary(ReviewMessage), field_dictionary(CoTaskMessage)
    assert 'zero-based' in reviewer['assigned_scope_index']['description']
    assert 'THIS request' in reviewer['evidence_indexes']['description']
    assert reviewer['evidence_indexes']['schema']['items']['minimum'] == 0
    assert co['commission_criterion_scopes']['schema']['items']['type'] == 'string'
    assert co['artifact_scopes']['schema']['items']['type'] == 'string'
    assert 'review' not in co
    assert 'exactly the empty string' in reviewer['remaining_work']['description']
    assert 'uniqueItems' not in reviewer['evidence_indexes']['schema']
    for model in (ReviewMessage, CoTaskMessage):
        StrictCodec({'name': 'probe', 'parameters': model.model_json_schema()})


def test_unknown_root_error_never_reflects_exception_text():
    import json
    from pydantic import BaseModel, model_validator
    from report_agent.message_fields import validate_message
    from report_agent.errors import ActionRejected
    class UntrustedException(BaseModel):
        text: str
        @model_validator(mode='after')
        def reject(self):
            raise ValueError(self.text)
    with pytest.raises(ActionRejected) as caught:
        validate_message(UntrustedException, {'text': 'PRIVATE_EXCEPTION_TEXT'})
    assert 'PRIVATE_EXCEPTION_TEXT' not in str(caught.value) + json.dumps(caught.value.diagnostic)
