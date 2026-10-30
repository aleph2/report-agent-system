"""Offline fresh-process continuation: tools only, no model configured or invoked."""
import asyncio
import json
import sys

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from report_agent.content_store import ContentStore
from report_agent.content_tasks import delegated_task
from report_agent.store import Store
from report_agent.workspace import Workspace
from test_live_review_message import live_tools, live_graph


async def main():
    from pathlib import Path
    args = json.loads(Path(sys.argv[1]).read_text())
    ws = Workspace(Store(Path(args['workspace'])))
    with delegated_task(ws, 'coordinator', args['call']):
        async with AsyncSqliteSaver.from_conn_string(args['checkpoint']) as saver:
            graph = live_graph(ws, live_tools(ws), saver)
            result = await graph.ainvoke(None, {'configurable': {'thread_id': 'live-resume'}})
    print(json.dumps({'status': result['messages'][-1].status,
                      'records': len(ContentStore(ws.store).list_objects('ReviewRecord')), 'model_calls': 0}))


if __name__ == '__main__':
    asyncio.run(main())
