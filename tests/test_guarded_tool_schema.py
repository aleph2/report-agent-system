"""Check the final registered surface, not just base APIs or descriptions."""
import json
import pytest
from langchain_core.utils.function_calling import convert_to_openai_tool
from langchain.tools import tool
from pydantic import ValidationError
from report_agent.deep_runtime import business_tools
from report_agent.task_context import exact_task_context
from report_agent.text_work import AdoptionObject,produce
from report_agent.content_models import Evidence
from report_agent.hierarchical_tools import actor_for
from langchain_core.messages import AIMessage
from langgraph.prebuilt import ToolNode
from langgraph.graph import StateGraph,MessagesState,START,END
from test_task_supervision import ws
from test_hierarchical_content import seed
from test_text_work import Model


def actual(ws):
    seed(ws)
    return {f.__name__:f for f in business_tools(ws,'coordinator',None,Model('{}'))}['commit_objects']


def test_final_registered_schema_retains_contracts_and_receipt_adoption(ws):
    function=actual(ws)
    schema=convert_to_openai_tool(function)['function']['parameters']
    branches=schema['properties']['objects']['items']['oneOf']
    by_type={b['properties']['type']['const']:b for b in branches}
    criterion=by_type['Criterion']['properties']['payload']
    assert set(criterion['required'])=={'requirement_refs','purpose','scope','expected_outcome','evidence_expectation','allowed_limits'}
    assert criterion['additionalProperties'] is False
    assert criterion['properties']['requirement_refs']['items']['properties']['type']['const']=='Requirement'
    assert 'text_work_id' not in by_type['Criterion']['properties']
    assert 'text_work_id' not in by_type['Relation']['properties']
    relation=by_type['Relation']['properties']['payload']
    assert {'subject_ref','predicate','object_ref','provenance_kind'}<=set(relation['required'])
    assert 'client_key' in json.dumps(relation['properties']['subject_ref'])
    for kind in ('ContentNode','Evidence'):
        assert 'text_work_id' in by_type[kind]['properties']
        assert 'payload' not in by_type[kind]['required']
        assert not any(p.get('additionalProperties') is True for p in by_type[kind]['properties']['payload']['anyOf'] if p.get('type')=='object')


def test_native_tool_input_rejects_old_guesses_before_business_write(ws):
    wrapped=tool(actual(ws))
    before=ws.store.events()
    for payload in (
        {'title':'K1','text':'old guessed fields','scope':'report'},
        {'requirement_refs':['commission:invented'],'purpose':'check','scope':'report','expected_outcome':'useful','evidence_expectation':'source','allowed_limits':''},
        {'requirement_refs':[{'type':'SourceArtifact','id':'s','version':1}],'purpose':'check','scope':'report','expected_outcome':'useful','evidence_expectation':'source','allowed_limits':''},
    ):
        with pytest.raises(ValidationError):
            wrapped.invoke({'operation_id':'invalid','objects':[{'client_key':'k','type':'Criterion','payload':payload}]})
    assert ws.store.events()==before


def test_native_registered_tool_saves_real_requirement_bound_criterion(ws):
    wrapped=tool(actual(ws))
    requirement=next(r['ref'] for r in exact_task_context(ws,'coordinator')['input_refs'] if r['ref']['type']=='Requirement')
    result=wrapped.invoke({'operation_id':'real-criterion','objects':[{'client_key':'k','type':'Criterion','payload':{
        'requirement_refs':[requirement],'purpose':'Scoped test','scope':'report','expected_outcome':'Requested outcome',
        'evidence_expectation':'Applicable sources','allowed_limits':'Unresolved sources retained'}}]})
    assert result['result']['refs']['k']['type']=='Criterion'


async def test_registered_exact_evidence_payload_keeps_explicit_null_defaults(ws):
    actual(ws)
    from report_agent.content_store import ContentStore
    cs=ContentStore(ws.store)
    source=next(o['ref'] for o in cs.list_objects() if o['ref']['type']=='SourceArtifact')
    payload=Evidence(source_refs=[source],locator='s:0',excerpt='Class B permits 75 to 100.').model_dump()
    model=Model(json.dumps(payload))
    work=await produce(ws,actor_for('coordinator'),model,'evidence-produce','Extract literal rule','Evidence',input_refs=[source],source_selections=[{'source_id':'s','offset':0,'limit':1}])
    function={f.__name__:f for f in business_tools(ws,'coordinator',None,model)}['commit_objects']
    saved=tool(function).invoke({'operation_id':'exact-evidence','objects':[{'client_key':'e','type':'Evidence','payload':payload,'text_work_id':work['text_work_id']}]})
    assert cs.read(saved['result']['refs']['e'])['payload']==payload


def test_native_toolnode_dispatch_keeps_typed_model_to_compatibility_boundary(ws):
    function=actual(ws)
    requirement=next(r['ref'] for r in exact_task_context(ws,'coordinator')['input_refs'] if r['ref']['type']=='Requirement')
    args={'operation_id':'native-toolnode','objects':[{'client_key':'k','type':'Criterion','payload':{
        'requirement_refs':[requirement],'purpose':'Native dispatch','scope':'report','expected_outcome':'Outcome',
        'evidence_expectation':'Sources','allowed_limits':''}}]}
    graph=StateGraph(MessagesState)
    graph.add_node('tools',ToolNode([function]));graph.add_edge(START,'tools');graph.add_edge('tools',END)
    result=graph.compile().invoke({'messages':[AIMessage(content='',tool_calls=[{'id':'call','name':'commit_objects','args':args,'type':'tool_call'}])]})
    returned=json.loads(result['messages'][-1].content)
    assert returned['ok'] and returned['result']['refs']['k']['type']=='Criterion'
