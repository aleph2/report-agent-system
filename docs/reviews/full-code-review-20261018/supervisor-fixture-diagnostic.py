import asyncio,json,os,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path('tests').resolve()))
os.environ['LANGSMITH_TRACING']='false'
import httpx
httpx.Client.send=httpx.AsyncClient.send=lambda *a,**k: (_ for _ in ()).throw(AssertionError('Network forbidden'))
import test_task_supervision as suite
from report_agent.store import Store
from report_agent.workspace import Workspace
from report_agent.task_supervision import task_status
from report_agent.content_store import ContentStore
from langchain_core.messages import ToolMessage
seen=[]
Base=suite.Driver
class Capture(Base):
    def __init__(self,**kw):super().__init__(**kw);seen.append(self)
suite.Driver=Capture
with tempfile.TemporaryDirectory() as tmp:
    ws=suite.ws.__wrapped__(Path(tmp))
    try:asyncio.run(suite.test_native_supervisor_follows_up_once_and_preserves_remaining(ws,True))
    except AssertionError:pass
    d=seen[0]
    result={'case':'existing supervisor followup True', 'provider_calls':0,
      'registered_reviewer_tools':[[s['name'] for s in batch] for batch in d.bindings.get('reviewer',[])],
      'tool_returns':[m.model_dump() for role,step,messages in d.calls for m in messages if isinstance(m,ToolMessage)],
      'status':task_status(ContentStore(ws.store))}
    Path('docs/reviews/full-code-review-20261018/supervisor-fixture-diagnostic.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps({'reviewer_tools':result['registered_reviewer_tools'], 'tool_returns':[{'name':r.get('name'),'content':r['content']} for r in result['tool_returns'] if r.get('name')=='submit_review'], 'status':result['status']},ensure_ascii=False))
