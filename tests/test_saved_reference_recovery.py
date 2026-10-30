"""Large saved-reference directories use existing exact actor-owned recovery."""
import json

from langchain_core.messages import ToolMessage

from report_agent.content_tasks import attach_saved_reference_metadata
from report_agent.content_store import ContentStore
from report_agent.store import Store
from report_agent.task_context import read_observation
from report_agent.workspace import Workspace
from test_saved_reference_receipts import saved


def test_source_material_proof_is_retained_without_appending_under_its_old_hash(saved):
    _, cs, co, _, task, _, _ = saved
    message=ToolMessage('Original source material.',name='task',tool_call_id='material',
        artifact={'source_material':{'public_sha256':'bound-original-proof'}})
    result=attach_saved_reference_metadata(cs,co,task,message,'material')
    assert result.content == message.content
    assert result.artifact['source_material'] == message.artifact['source_material']
    assert result.artifact['saved_reference_metadata']['status']=='unavailable'


def test_large_multi_save_directory_is_bounded_and_exact_after_reopen(saved):
    workspace, cs, co, writer, task, _, _ = saved
    workspace.store.set('context_policy','stateful-tools-v2')
    identity='opaque-receipt-identity-' + 'x'*200
    cs.commit(writer,identity,[{'client_key':str(i),'type':'ContentNode','payload':{
        'kind':'claim','body':{'text':'Extra saved claim '+str(i)},'qualifiers':{},'claim_kind':'fact'}}
        for i in range(60)])
    expected=cs.saved_reference_summary(co,task)
    assert len(json.dumps(expected))>4800
    original=ToolMessage('Original Writer text retained.',name='task',tool_call_id='large',status='error')
    result=attach_saved_reference_metadata(cs,co,task,original,'large')
    metadata=result.artifact['saved_reference_metadata']
    assert len(json.dumps(metadata,ensure_ascii=False))<=4800
    assert metadata['partial'] is True and metadata['receipt_count']==2
    assert metadata['semantic_acceptance'] is False
    assert result.status=='error' and original.content in result.content
    assert original.artifact is None
    pointer=metadata['exact_recovery']
    assert pointer['tool']=='read_tool_observation'
    reopened=Workspace(Store(workspace.store.root))
    args=pointer['arguments']
    pieces=[]
    while True:
        page=read_observation(reopened,'coordinator',**args)
        assert page['sha256']==pointer['sha256']
        pieces.append(page['text'])
        if page['next_offset'] is None: break
        args={**args,'offset':page['next_offset']}
    recovered=json.loads(''.join(pieces))
    assert recovered==expected
    assert recovered['receipts'][1]['receipt_id']==identity
    assert len(recovered['receipts'][1]['content_nodes'])==60
    assert ContentStore(reopened.store).saved_reference_summary(co,task)==expected
