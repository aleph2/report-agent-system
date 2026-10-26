import json
from copy import deepcopy
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from report_agent.content_tasks import delegated_task
from report_agent.errors import ActionRejected
from report_agent.review_work_units import public_plan_update, require_before_verification, validate_todos
from test_review_work_units import configured, unit_todo
from test_deliverable_declaration_v4 import case
from test_deep_runtime import call


@pytest.mark.parametrize('mode',['missing-method','empty-condition','duplicate-scope','outside-scope','caller-binding',
                                 'malformed-json','extra-wrapper','dual-conflict','source-tool','user','reasoning','prose'])
def test_invalid_or_untrusted_plan_cannot_authorize_verification(case,mode):
    cs, output, ws, request = configured(case)
    todo=unit_todo(output['refs']['a-body'])
    if mode=='missing-method':todo['review_unit'].pop('method')
    if mode=='empty-condition':todo['review_unit']['decision_conditions']=' '
    if mode=='duplicate-scope':todo['review_unit']['assigned_scope_indexes']=[0,0]
    if mode=='outside-scope':todo['review_unit']['assigned_scope_indexes']=[2]
    if mode=='caller-binding':todo['review_unit']['_binding']='invented'
    content=json.dumps({'review_plan':{'todos':[todo]}})
    if mode=='malformed-json':content=content[:-1]
    if mode=='extra-wrapper':content=json.dumps({'wrapper':json.loads(content)})
    message=AIMessage(content)
    if mode=='dual-conflict':message=AIMessage(content,tool_calls=[call('write_todos',{'todos':[]})])
    if mode=='source-tool':message=ToolMessage(content,tool_call_id='untrusted-source')
    if mode=='user':message=HumanMessage(content)
    if mode=='reasoning':message=AIMessage('No public declaration.',additional_kwargs={'reasoning_content':content})
    if mode=='prose':message=AIMessage('My plan is: '+content)
    with delegated_task(ws,'coordinator',request):
        before=cs.list_objects()
        state={'messages':[message]}
        with pytest.raises(ActionRejected):
            declared=public_plan_update(ws,state)
            if declared is not None:state['todos']=declared
            require_before_verification(ws,'reviewer',call('calculate',{'terms':[['1','2']]}),state)
        assert cs.list_objects()==before
        assert not cs.list_objects('ReviewRecord')


def test_recon_is_allowed_and_overlapping_units_do_not_require_duplicate_manifest(case):
    cs, output, ws, request=configured(case)
    with delegated_task(ws,'coordinator',request):
        for name,args in [('read_context',{}),('read_source_page',{}),('render_export',{}),
                          ('observe_evidence',{'kind':'source'})]:
            require_before_verification(ws,'reviewer',call(name,args),{})
        todo=unit_todo(output['refs']['a-body'])
        second=deepcopy(todo);second['content']='Independent cross-check'
        result=validate_todos(ws,[todo,second],declaration=True)
        assert len(result)==2
        assert result[0]['review_unit']['_binding']==result[1]['review_unit']['_binding']
        assert not cs.list_objects('ReviewRecord')
