import json
import pytest
from langchain_core.messages import AIMessage, ToolMessage
from report_agent.errors import ActionRejected
from report_agent.store import Store, encode
from report_agent.workspace import Workspace
from report_agent.learning import binding
from report_agent.learning_runtime import optimizer_tools, build_optimizer
from report_agent.learning_worker import consume_pending
from test_deep_runtime import Driver, invoke


@pytest.fixture
def case(tmp_path):
    ws = Workspace(Store(tmp_path/'project'))
    ws.store.set('learning_config', {'library_path': str(tmp_path/'library'), 'customer_id': 'a'})
    lib, scope = binding(ws)
    old = lib.feedback(scope, {}, {}, 'Old feedback', {}, [{'old': True}])
    new = lib.feedback(scope, {}, {}, 'New feedback: compare actual results', {'text': '旧报告'*40000},
                       [{'text': '真实对照证据🙂'*30000, 'final': 'TAIL_MARKER'}])
    ws.store.set('learning_active_feedback', {'id': 'test-claim', 'feedback_ids': [new['id']]})
    ws.store.set('learning_job', {'id': 'test-job', 'state': 'running'})
    tools = {f.__name__: f for f in optimizer_tools(ws)}
    return ws, lib, scope, old, new, tools


def test_large_feedback_remains_bounded_and_exactly_reconstructable(case):
    ws, lib, scope, old, new, tools = case
    index = tools['read_learning_feedback']()
    assert index['feedback'][0]['id'] == new['id']
    assert len(encode(index)) < 8000
    text = ''; offset = 0; digests = set()
    while offset is not None:
        page = tools['read_learning_feedback'](new['id'], 'evidence', offset, 8000)
        assert len(page['text']) <= 8000
        text += page['text']; offset = page['next_offset']; digests.add(page['digest'])
    assert text == encode(new['evidence']) and len(digests) == 1
    with pytest.raises(ActionRejected, match='OUTSIDE_PROJECT'):
        tools['read_learning_feedback']('foreign-id')
    with pytest.raises(ActionRejected, match='INVALID_LEARNING_PAGE'):
        tools['read_learning_feedback'](new['id'], limit=8001)
    for i in range(8):
        lib.propose(scope, [old['id']], 'general_skill', 'title', 'strategy'*2000, 'conditions', 'check')
    listing = tools['read_experience_candidates']()
    assert listing['next_offset'] == 6 and len(encode(listing)) < 8000
    first = listing['items'][0]
    assert tools['read_experience_candidates'](first['id'], first['version'])['next_offset'] == 6000


@pytest.mark.asyncio
async def test_real_framework_does_not_offload_feedback_pages(case):
    ws, lib, scope, old, new, tools = case
    driver = Driver(optimizer=[invoke('read_learning_feedback'),
        invoke('read_learning_feedback', feedback_id=new['id'], field='evidence', offset=8000, limit=8000),
        AIMessage(content='Read a page.')])
    result = await build_optimizer(ws, driver('optimizer')).ainvoke({'messages': [{'role':'user','content':'Read feedback'}]})
    messages = [m for m in result['messages'] if isinstance(m, ToolMessage)]
    assert len(messages) == 2
    assert all('Tool result too large' not in m.content for m in messages)
    assert json.loads(messages[1].content)['offset'] == 8000


def test_dispositions_enforce_claim_and_candidate_links(case):
    ws, lib, scope, old, new, tools = case
    candidate = lib.propose(scope, [old['id']], 'general_skill', 'Old', 's', 'c', 'v')
    with pytest.raises(ActionRejected, match='CANDIDATE_FEEDBACK_MISMATCH'):
        tools['record_feedback_disposition'](new['id'], 'candidate', 'Old candidate', candidate['id'], 1)
    with pytest.raises(ActionRejected, match='FEEDBACK_NOT_ASSIGNED'):
        tools['record_feedback_disposition'](old['id'], 'no_change', 'Not assigned')
    record = tools['record_feedback_disposition'](new['id'], 'insufficient_evidence', 'Need a located comparison')
    assert not record['quality_verified']
    assert record['outcome'] == 'insufficient_evidence'


def test_assignment_index_does_not_repeat_unbounded_claim(case):
    ws, lib, scope, old, new, tools = case
    ids = [str(i).zfill(64) for i in range(10000)]
    ws.store.set('learning_active_feedback', {'id': 'large-claim', 'feedback_ids': ids})
    index = tools['read_learning_feedback']()
    assert len(encode(index)) < 8000
    assert index['pending_assignment']['total'] == 10000
    assert index['pending_assignment']['next_offset'] == 6
    assert tools['read_learning_feedback'](offset=6)['pending_assignment']['feedback_ids'] == ids[6:12]


@pytest.mark.asyncio
async def test_parallel_dispositions_preserve_both_successful_receipts(case):
    ws, lib, scope, old, new, tools = case
    calls = [
        {'name': 'record_feedback_disposition', 'id': str(i), 'type': 'tool_call',
         'args': {'feedback_id': item['id'], 'outcome': 'insufficient_evidence', 'rationale': 'Need source verification'}}
        for i, item in enumerate((old, new))]
    driver = Driver(optimizer=[AIMessage(content='', tool_calls=calls), AIMessage(content='Unresolved, recorded both.')])
    result = await consume_pending(ws, lambda: driver('optimizer'))
    assert result['state'] == 'completed'
    assert set(ws.store.get('learning_job')['feedback_dispositions']) == {old['id'], new['id']}
    assert all(x['status'] == 'completed' for x in lib.queue_status(scope))


@pytest.mark.asyncio
async def test_partial_handling_cannot_complete_claim_and_is_preserved(case):
    ws, lib, scope, old, new, tools = case
    driver = Driver(optimizer=[invoke('record_feedback_disposition', feedback_id=old['id'],
        outcome='no_change', rationale='Already covered'), AIMessage(content='Done')])
    with pytest.raises(ActionRejected, match='LEARNING_FEEDBACK_UNACCOUNTED'):
        await consume_pending(ws, lambda: driver('optimizer'))
    assert all(x['status'] == 'failed' for x in lib.queue_status(scope))
    assert old['id'] in ws.store.get('learning_job')['feedback_dispositions']
    assert new['id'] not in ws.store.get('learning_job')['feedback_dispositions']
    assert not lib.search(scope)
