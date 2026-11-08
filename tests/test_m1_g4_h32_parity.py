"""Effective native planning schemas and field-specific failures, without providers."""
from copy import deepcopy
import json
import pytest
from jsonschema import Draft202012Validator
from langchain_core.tools import BaseTool, StructuredTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from report_agent import commission_planning as planning
from report_agent.errors import ActionRejected
from report_agent.native_operation_tools import native_write_tools
from test_m1_g4_planning_steps import current_native_profiles

from test_m1_g4_planning_steps import (method_commission, anchored, required_case, entries, linked, draft_case, text_source, offline_only)
STEP_NAMES = {'read_planning_draft', 'set_requirement_status', 'link_convention',
              'set_scope_boundary', 'set_planning_details', 'add_object', 'add_section',
              'add_substitution', 'add_reconciliation', 'add_question'}
ASSERTION_STEPS = {'assert_source', 'record_conflict', 'ask'}


def tools(f):
    current_native_profiles(f)
    functions = planning.planning_tools(f.cs, lambda: f.co)
    wrapped = native_write_tools(f.ws, 'coordinator', functions)
    return {getattr(t, 'name', None) or t.__name__: t if isinstance(t, BaseTool)
            else StructuredTool.from_function(t) for t in wrapped}


def inputs(f):
    scope = next(a for a in f.anchors if a['kind'] == 'scope')
    outline = next(a for a in f.anchors if a['kind'] == 'section')
    return {
        'read_planning_draft': {},
        'set_requirement_status': {'anchor_id': scope['id'], 'status': 'required', 'interpretation': 'Use the declared scope.'},
        'link_convention': {'anchor_id': f.weight_anchor['id'], 'entry_id': f.entries[1]['id'], 'interpretation': 'Use the reviewed weights.'},
        'set_scope_boundary': {'boundary': {'start_meter': '1000', 'end_meter': '2000',
            'source': deepcopy(scope['source']), 'customer_basis_anchor_id': scope['id']}},
        'set_planning_details': {'details': {'inventory_attributes': ['height'], 'deliverables': ['report']}},
        'add_object': {'object': deepcopy(f.plan['objects'][0])},
        'add_section': {'section_id': outline['section_id'], 'title': 'Scope', 'kind': 'extracted',
            'outline_anchor_id': outline['id'], 'sources': [deepcopy(scope['source'])]},
        'add_substitution': {'section_id': outline['section_id'], 'substitution': {'requested_source': 'missing survey',
            'replacement_sources': [deepcopy(scope['source'])], 'customer_basis': deepcopy(scope['source']), 'reason': 'Proposed replacement for owner review.'}},
        'add_reconciliation': {'reconciliation': {'reconciliation_id': 'comparison',
            'sources': [deepcopy(scope['source']), deepcopy(f.weight_anchor['source'])], 'result': 'Retain distinct purposes.', 'differences': []}},
        'add_question': {'question': {'question_id': 'question', 'text': 'Confirm scope at checkpoint.', 'resolved': False}},
    }


def invoke(tool, arguments, identity):
    return tool.invoke({'name': tool.name, 'type': 'tool_call', 'id': identity, 'args': arguments})


def assert_fields(error):
    fields = (error.diagnostic or {}).get('fields', [])
    assert fields, (str(error), error.diagnostic)
    assert all(item.get('field') and item.get('reason') for item in fields), fields


@pytest.mark.parametrize('name', sorted(STEP_NAMES))
def test_every_step_schema_valid_minimum_is_accepted_or_field_diagnosed(draft_case, name):
    offered = tools(draft_case)
    assert set(offered) == STEP_NAMES | ASSERTION_STEPS
    tool = offered[name]
    arguments = inputs(draft_case)[name]
    schema = convert_to_openai_tool(tool)['function']['parameters']
    assert 'operation_id' not in schema['properties']
    Draft202012Validator(schema).validate(arguments)
    try:
        result = invoke(tool, arguments, 'parity-minimal-' + name)
    except ActionRejected as error:
        assert_fields(error)
    else:
        payload = json.loads(result.content)
        assert isinstance(payload, dict)
        assert payload.get('ok', True), payload


async def test_assertion_steps_accept_native_calls_and_leave_no_receipt_on_refusal(draft_case):
    from uuid import NAMESPACE_URL, uuid5
    from langchain_core.messages import AIMessage
    from langgraph.graph import StateGraph, MessagesState, START, END
    from langgraph.prebuilt import ToolNode
    from report_agent.assertion_host import AssertionHost
    from report_agent.catalog import Catalog
    from report_agent.operation_identity import bound_native_id
    from test_ingestion import pdf_bytes

    f = draft_case
    offered = tools(f)
    graph = StateGraph(MessagesState)
    graph.add_node('tools', ToolNode([offered[name] for name in ASSERTION_STEPS], handle_tool_errors=True))
    graph.add_edge(START, 'tools')
    graph.add_edge('tools', END)
    runner = graph.compile()
    subject = f.plan['objects'][0]['object_id']
    planning.save_item(f.cs, f.co, 'parity-subject', 'object', f.plan['objects'][0])
    source = Catalog(f.ws.store).import_file('surveys.pdf', pdf_bytes(['Height 18 m.', 'Height 19 m.']))
    principal = str(uuid5(NAMESPACE_URL, f.co.id))
    host = AssertionHost(f.ws.store.root)

    async def submit(name, native_id, args, *, refusal=None):
        schema = convert_to_openai_tool(offered[name])['function']['parameters']
        assert not {'runtime', 'actor', 'task', 'packet', 'operation_id'} & schema['properties'].keys()
        Draft202012Validator(schema).validate(args)
        call = {'name': name, 'args': args, 'id': native_id, 'type': 'tool_call'}
        result = await runner.ainvoke({'messages': [AIMessage('', tool_calls=[call])]})
        reply = result['messages'][-1]
        receipt = host.recover_receipt(bound_native_id(principal, name, native_id))
        if refusal:
            assert reply.status == 'error' and refusal in reply.content
            assert receipt is None
            return
        assert reply.status == 'success', reply.content
        saved = json.loads(reply.content)
        assert receipt['result'] == saved and saved['was_generated_by'] == f.co.task_id
        return saved['id']

    facts = []
    for page, height in enumerate((18, 19), start=1):
        args = dict(subject=subject, predicate='height', state='value', coverage='slope', value=height,
                    unit='m', source_id=source['source']['id'], page=page, quote=f'Height {height} m.')
        facts.append(await submit('assert_source', f'height-{page}', args))
    await submit('assert_source', 'wrong-quote', {**args, 'quote': 'Height 20 m.'}, refusal='C2')
    await submit('record_conflict', 'compare', dict(subject=subject, observations=facts))
    await submit('record_conflict', 'foreign', dict(subject=subject, observations=[facts[0], 'outside']),
                 refusal='PLANNING_CONFLICT_REQUIRES_OWN_SUBJECT_OBSERVATIONS')
    question = dict(subject=subject, text='Which survey applies?', affects='value')
    await submit('ask', 'question', question)
    await submit('ask', 'outside-scope', {**question, 'subject': 'outside inventory'},
                 refusal='PLANNING_ASSERTION_INVENTORY_SUBJECT_REQUIRED')


@pytest.mark.parametrize('name', ['set_requirement_status', 'link_convention', 'set_scope_boundary',
                                   'add_object', 'add_section', 'add_substitution', 'add_reconciliation'])
def test_schema_valid_domain_fault_names_the_actual_field(draft_case, name):
    tool = tools(draft_case)[name]
    arguments = inputs(draft_case)[name]
    expected = ''
    if name == 'set_requirement_status':
        arguments['anchor_id'] = 'absent-anchor'; expected = 'anchor_id'
    elif name == 'link_convention':
        arguments['entry_id'] = 'absent-entry'; expected = 'entry_id'
    elif name == 'set_scope_boundary':
        arguments['boundary']['customer_basis_anchor_id'] = 'absent-anchor'; expected = 'customer_basis_anchor_id'
    elif name == 'add_section':
        arguments['outline_anchor_id'] = 'absent-anchor'; expected = 'outline_anchor_id'
    else:
        target = arguments['object']['sources'][0] if name == 'add_object' else (
            arguments['substitution']['customer_basis'] if name == 'add_substitution' else arguments['reconciliation']['sources'][0])
        target['quote'] = 'This exact quotation does not exist in the registered source.'
        expected = 'quote'
    Draft202012Validator(convert_to_openai_tool(tool)['function']['parameters']).validate(arguments)
    with pytest.raises(ActionRejected) as caught:
        invoke(tool, arguments, 'parity-domain-' + name)
    assert_fields(caught.value)
    fields = caught.value.diagnostic['fields']
    assert any(expected in str(item['field']) for item in fields), fields

@pytest.mark.parametrize('name', ['submit_plan', 'request_requirement_resolution'])
def test_runtime_planning_actions_preserve_structured_gaps_or_fields(draft_case, name):
    from report_agent.deep_runtime import business_tools
    from test_bounded_review import Model
    current_native_profiles(draft_case)
    offered = native_write_tools(draft_case.ws, 'coordinator', business_tools(draft_case.ws, 'coordinator', None, Model('unused')))
    selected = next(t for t in offered if (getattr(t, 'name', None) or t.__name__) == name)
    if not isinstance(selected, BaseTool):
        selected = StructuredTool.from_function(selected)
    Draft202012Validator(convert_to_openai_tool(selected)['function']['parameters']).validate({})
    with pytest.raises(ActionRejected) as caught:
        invoke(selected, {}, 'runtime-parity-' + name)
    if name == 'submit_plan':
        gaps = (caught.value.diagnostic or {}).get('gaps', [])
        assert gaps and all(gap.get('path') and gap.get('code') for gap in gaps), caught.value.diagnostic
    else:
        assert_fields(caught.value)
    assert draft_case.ws.store.get('commission_confirmation') is None


async def test_native_missing_quote_returns_nested_field_diagnostic(draft_case):
    from langchain_core.messages import AIMessage
    from langgraph.graph import StateGraph, MessagesState, START, END
    from langgraph.prebuilt import ToolNode
    from report_agent.tool_argument_feedback import compact_native_tool_error
    tool = tools(draft_case)['set_scope_boundary']
    arguments = inputs(draft_case)['set_scope_boundary']
    arguments['boundary']['source'].pop('quote')
    graph = StateGraph(MessagesState)
    graph.add_node('tools', ToolNode([tool]))
    graph.add_edge(START, 'tools'); graph.add_edge('tools', END)
    result = await graph.compile().ainvoke({'messages': [AIMessage('', tool_calls=[{
        'name': tool.name, 'type': 'tool_call', 'id': 'missing-quote', 'args': arguments}])]})
    raw = result['messages'][-1]
    assert raw.status == 'error'
    compact = compact_native_tool_error(raw, draft_case.ws.store, args=arguments, schema=tool.tool_call_schema)
    payload = json.loads(compact.content)
    assert payload['code'] == 'NATIVE_TOOL_VALIDATION_ERROR'
    fields = payload['diagnostic']['fields']
    assert any('boundary' in str(f['field']) and 'source' in str(f['field']) and 'quote' in str(f['field']) for f in fields)
