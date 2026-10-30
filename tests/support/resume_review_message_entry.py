"""Fresh-process resume of production-bound tools, with the network guard installed first."""
import asyncio
import json
import os
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests')]
runpy.run_path(str(ROOT / 'tests/support/offline-guard/sitecustomize.py'))
import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from report_agent.content_store import ContentStore
from report_agent.content_tasks import delegated_task
from report_agent.store import Store
from report_agent.workspace import Workspace
from support.review_message_entry import ReviewEntryProbe


async def main():
    root, checkpoint, intent = map(Path, sys.argv[1:])
    call = json.loads(intent.read_text())
    contents = ContentStore(Store(root))
    workspace = Workspace(contents.store)
    patch = pytest.MonkeyPatch()
    try:
        with delegated_task(workspace, 'coordinator', call) as (_, actor):
            bridge = ReviewEntryProbe(workspace, patch)
            config = {'configurable': {'thread_id': 'saved-entry'}}
            async with AsyncSqliteSaver.from_conn_string(str(checkpoint)) as saver:
                graph = bridge.graph(checkpointer=saver, interrupt_before=['tools'])
                assert (await graph.aget_state(config)).next == ('tools',)
                result = await graph.ainvoke(None, config)
            assert bridge.context_is_clear() and not bridge.requests
            print(json.dumps({'pid': os.getpid(), 'status': result['messages'][-1].status,
                'actor_id': actor.id, 'task_id': actor.task_id,
                'review_count': len(contents.list_objects('ReviewRecord')), 'model_requests': 0}))
    finally:
        patch.undo()


if __name__ == '__main__':
    asyncio.run(main())
