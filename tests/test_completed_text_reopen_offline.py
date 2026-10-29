import hashlib
import json
import pytest
from report_agent.content_tasks import delegated_task
from report_agent.store import Store
from report_agent.workspace import Workspace
from test_task_supervision import ws, offline
from test_hierarchical_content import seed
from test_bounded_review import Model
from test_text_work import content, tools, writer_call

async def test_three_real_completed_receipts_and_adoptions_survive_reopen_without_new_model_calls(ws):
    cs, _, refs, _, _ = seed(ws)
    model=Model(json.dumps(content()))
    with delegated_task(ws, 'coordinator', writer_call()) as (_, actor):
        original=tools(ws, 'writer', model)
        works=[]; nodes=[]; state_before=[]
        for i in range(3):
            work=await original['process_report_content']('work-'+str(i), 'Describe supplied rule '+str(i), 'ContentNode', [refs['claim']])
            saved=original['save_text_node']('save-'+str(i),work['text_work_id'])
            key='text_work:'+actor.id+':work-'+str(i)
            record=ws.store.get(key)
            assert record['state']=='completed'
            works.append(work);nodes.append(saved['result']['refs']['text']);state_before.append(record)
        assert len(model.calls)==3
        reopened=Workspace(Store(ws.store.root))
        again=tools(reopened,'writer',model)
        for i in range(3):
            work=await again['process_report_content']('work-'+str(i), 'Describe supplied rule '+str(i), 'ContentNode', [refs['claim']])
            assert work['reused'] and work['text_work_id']==works[i]['text_work_id']
            assert reopened.store.get('text_work:'+actor.id+':work-'+str(i))==state_before[i]
            assert cs.read(nodes[i])['payload']==content()
        assert len(model.calls)==3
        assert len(cs.list_objects('ContentNode'))>=3
