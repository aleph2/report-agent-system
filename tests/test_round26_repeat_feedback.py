"""Receipt identity is bookkeeping; changed content/selection remains progress."""
import json
import pytest
from langchain_core.messages import AIMessage,ToolMessage
from report_agent.deep_runtime import repeated_observation

@pytest.mark.parametrize('change',[None,'body','version','selection'])
def test_read_repetition_uses_actual_result_not_new_receipt_uuid(change):
    messages=[]
    for i in range(3):
        args={'target_ref':{'type':'ContentNode','id':'claim','version':1}}
        payload={'ok':True,'receipt_id':'own-receipt-'+str(i),
            'result':{'objects':[{'ref':dict(args['target_ref']),
                'payload':{'body':{'text':'Exact same source information.'}}}]}}
        if i==2 and change=='body':payload['result']['objects'][0]['payload']['body']['text']='New evidence.'
        if i==2 and change=='version':payload['result']['objects'][0]['ref']['version']=2
        if i==2 and change=='selection':args['offset']=20
        messages.extend([AIMessage('',tool_calls=[{'name':'read_context','args':args,'id':str(i),'type':'tool_call'}]),
            ToolMessage(json.dumps(payload),name='read_context',tool_call_id=str(i))])
    assert repeated_observation(messages)==('read_context' if change is None else None)
