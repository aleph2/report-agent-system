"""Offline scripted planning through the real Coordinator and imported PDF pages."""
import json
from uuid import NAMESPACE_URL, uuid5

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from report_agent.assertion_host import AssertionHost, Grant
from report_agent.catalog import Catalog
from report_agent.commission_planning import save_item
from report_agent.content_store import ContentStore
from report_agent.deep_runtime import build_agent
from report_agent.source_use import configure_source_use, immutable_version_digest
from test_deep_runtime import Driver, call
from test_ingestion import pdf_bytes
from test_m1_g4_planning_steps import (anchored, current_native_profiles, draft_case, entries,
    method_commission, offline_only, required_case)


async def test_planning_assertions_follow_real_page_read_and_reopen(draft_case):
    f = draft_case
    current_native_profiles(f)
    subject = f.plan['objects'][0]['object_id']
    save_item(f.cs, f.co, 'register-object', 'object', f.plan['objects'][0])
    catalogue = Catalog(f.ws.store)
    quotes = ('Observed on 2025-05-06: slope height 18 m.', 'Slope height 19 m.')
    source_id = catalogue.import_file('survey.pdf', pdf_bytes(quotes))['source']['id']
    configure_source_use(f.ws.store, [source_id], 'Test commission')
    version = immutable_version_digest(ContentStore.source_payload(f.ws.store.sources([source_id])[0]))
    host = AssertionHost(f.ws.store.root)
    principal = str(uuid5(NAMESPACE_URL, f.co.id))
    lookup = dict(actor=principal, task=f.co.task_id, subject=subject, kind='source')
    assert not host.commission.produced_ids(**lookup)

    def invoke(name, native_id, **args):
        return AIMessage(content='', tool_calls=[call(name, args, native_id)])

    args = dict(subject=subject, predicate='height', state='value', coverage='slope',
        value=18, unit='m', source_id=source_id, page=1, quote=quotes[0])
    rows = []

    def last(messages):
        return next(m for m in reversed(messages) if isinstance(m, ToolMessage))

    def result(messages):
        value = json.loads(last(messages).content)
        return value.get('metadata', value)

    def first(messages):
        assert last(messages).status != "error", last(messages).content
        page = result(messages)
        assert 'blocks' in page, page
        assert any(b['locator'].startswith('page 1;') and b['text'] == quotes[0] for b in page['blocks'])
        return invoke('assert_source', 'observation-one', **args)

    def second(messages):
        body = result(messages)
        assert body['was_attributed_to'] == principal and body['was_generated_by'] == f.co.task_id
        assert body['claim']['citation'] == dict(source_version=version, page=1, quote=quotes[0])
        assert body['observed_at'] is None
        rows.append(body)
        return invoke('assert_source', 'observation-two', **{**args, 'page':2, 'quote':quotes[1],
            'value':19})

    def conflict(messages):
        body = result(messages)
        assert body['observed_at'] is None
        rows.append(body)
        return invoke('record_conflict', 'conflict', subject=subject, observations=[r['id'] for r in rows])

    def question(messages):
        assert result(messages)['claim']['kind'] == 'conflict'
        return invoke('ask', 'question', subject=subject, text='Which survey applies?', affects='classification')

    def stop(messages):
        assert result(messages)['claim']['kind'] == 'question'
        return invoke('ask_human', 'stop', category='requirement', description='Review survey discrepancy.',
                      source_ids=[], pause=True)

    async def run(*steps):
        driver = Driver(coordinator=list(steps))
        await build_agent(f.ws, driver, None).ainvoke({'messages':[HumanMessage('Plan this commission.')]})
        return driver

    driver = await run(invoke('read_source_page', 'page', source_id=source_id, table_detail='references'),
                       first, second, conflict, question, stop)
    schemas = {s['name']:s for s in driver.bindings['coordinator'][0]}
    assert 'observed_at' not in schemas['assert_source']['parameters']['properties']
    for name in ('assert_source', 'ask', 'record_conflict'):
        assert name in schemas['read_planning_draft']['description']
        assert not {'runtime', 'operation_id', 'actor', 'packet', 'task'} & schemas[name]['parameters']['properties'].keys()
    assert host.commission.produced_ids(**lookup) == {r['id'] for r in rows}

    def observe_index(messages):
        values = result(messages)
        assert set(values['source_assertion_ids']) == {r['id'] for r in rows}
        return invoke('assert_source', 'observation-one', **args)

    def replay(messages):
        assert result(messages) == rows[0]
        return invoke('assert_source', 'observation-one', **{**args, 'value':17})

    def rejected(next_action):
        def step(messages):
            result = last(messages)
            assert isinstance(result, ToolMessage) and result.status == 'error', result
            return next_action
        return step

    await run(invoke('read_planning_draft', 'recover', collection='source_assertions', item_id=subject),
              observe_index, replay,
              rejected(invoke('assert_source', 'out-of-scope', **{**args, 'source_id':'design'})),
              rejected(invoke('assert_source', 'bad-page', **{**args, 'page':2})),
              rejected(invoke('ask', 'bad-subject', subject='outside inventory', text='Hidden?', affects='other')),
              rejected(invoke('record_conflict', 'bad-id', subject=subject, observations=[rows[0]['id'], 'unissued'])),
              rejected(invoke('ask_human', 'stop-again', category='requirement', description='Pause.', source_ids=[], pause=True)))
    assert host.commission.produced_ids(**lookup) == {r['id'] for r in rows}

    receipt = host.recover_receipt(rows[0]['operation_id'])
    binding = receipt['binding']
    host.revoke(Grant(principal, 'coordinator', f.co.task_id, binding['attempt'], binding['plan'],
                      {subject}, {version}, {'assert_source'}))
    await run(invoke('assert_source', 'observation-one', **args),
              rejected(invoke('ask_human', 'stop-revoked', category='requirement', description='Pause.', source_ids=[], pause=True)))
    assert host.recover_receipt(rows[0]['operation_id'])['result'] == rows[0]


def test_planning_tool_closure_cannot_escalate_from_delegated_task(method_commission):
    import pytest
    from report_agent.content_store import Actor
    from report_agent.content_tasks import _native_binding
    from report_agent.errors import ActionForbidden
    from report_agent.planning_assertions import planning_assertion_tools

    f = method_commission
    tools = {t.__name__: t for t in planning_assertion_tools(f.cs, lambda: f.co)}
    writer = Actor('content:writer:example-task', 'writer', 'example-task')
    with _native_binding(f.ws, writer, {'id':'delegate', 'args':{'description':'Writer assignment'}}, False):
        with pytest.raises(ActionForbidden, match='COORDINATOR_REQUIRED'):
            tools['ask']('S1', 'Can I inherit the coordinator binding?', 'other')
