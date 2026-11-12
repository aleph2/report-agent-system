"""Private live tool/model observations using LangChain's inherited callbacks."""
from collections import Counter, defaultdict, deque
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from threading import RLock
from time import monotonic

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.tracers.context import register_configure_hook

_capture = ContextVar('live_tool_trace', default=None)
register_configure_hook(_capture, inheritable=True)


def _key(name, args):
    return name, json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)


def _codes(error=None, output=None):
    text = str(error) if error is not None else getattr(output, 'content', '')
    if isinstance(text, str):
        try: body = json.loads(text)
        except ValueError: body = None
        if isinstance(body, dict) and isinstance(body.get('code'), str):text = body['code']
        codes = re.findall(r'\bC(?:1[0-2]|[1-9])(?=:)', text)
        if codes:return sorted(set(codes))
        match = re.match(r'^([A-Z][A-Z0-9_]+)(?=:|$)', text)
        if match:return [match[1]]
    return [type(error).__name__ if error is not None else 'TOOL_REFUSED']


class ToolTrace(BaseCallbackHandler):
    run_inline = True
    raise_error = True

    def __init__(self, workspace, run_id, path, fallback_actor):
        self.workspace, self.run_id, self.path = workspace, run_id, Path(path)
        self.fallback_actor = fallback_actor
        self.models, self.tools = {}, {}
        self.calls = defaultdict(deque)
        self.native_calls, self.observed = {},set()
        self.turns = Counter()
        self.last_admission_code = None
        self.lock = RLock()

    def actor(self):
        from .content_tasks import model_owner_identity
        identity = model_owner_identity(self.workspace.store)
        actor = identity['actor'] if identity else self.fallback_actor.__dict__
        return {'actor':actor['id'], 'role':actor['role'], 'task':actor['task_id']}

    def write(self, kind, **data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock, self.path.open('a', encoding='utf-8') as stream:
            self.path.chmod(0o600)
            stream.write(json.dumps({'kind':kind,'run_id':self.run_id,
                'utc':datetime.now(timezone.utc).isoformat(),**data}, ensure_ascii=False)+'\n')
            stream.flush()

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        from .prompt_provenance import _CALL
        call = _CALL.get()
        actor = {**self.actor(), 'prompt_call_id': call['call_id'] if call else None}
        self.turns[actor['actor']] += 1
        self.models[str(run_id)] = {**actor,'turn':self.turns[actor['actor']], 'started':monotonic()}
        self.write('model_started', callback_id=str(run_id), **actor, turn=self.turns[actor['actor']])

    def on_llm_end(self, response, *, run_id, **kwargs):
        row = self.models.pop(str(run_id), None)
        if row is None:return
        started = row.pop('started')
        for batch in response.generations:
            for generation in batch:
                for call in getattr(generation.message, 'tool_calls', []):
                    native={**row,'native_call_id':call['id']}
                    self.calls[_key(call['name'],call['args'])].append(native)
                    self.native_calls[call['id']]=native
        usage = (response.llm_output or {}).get('token_usage') or {}
        usage = {k:v for k,v in usage.items() if k in {'prompt_tokens','completion_tokens','total_tokens'} and type(v) is int and v>=0}
        self.write('model_outcome',callback_id=str(run_id),**row,usage=usage,
                   elapsed_seconds=monotonic()-started,failed=False)

    def on_llm_error(self, error, *, run_id, **kwargs):
        from .request_budget import RequestBudgetExceeded
        if isinstance(error,RequestBudgetExceeded):self.last_admission_code=str(error)
        row = self.models.pop(str(run_id), None)
        if row is not None:
            started = row.pop('started')
            self.write('model_outcome',callback_id=str(run_id),**row,failed=True,
                       error_type=type(error).__name__,admission_denied=isinstance(error,RequestBudgetExceeded),
                       elapsed_seconds=monotonic()-started)

    def on_tool_start(self, serialized, input_str, *, run_id, inputs=None, tool_call_id=None, **kwargs):
        name = serialized.get('name')
        args = inputs if isinstance(inputs,dict) else {}
        match = self.calls.get(_key(name,args))
        row = match.popleft() if match else {**self.actor(),'native_call_id':tool_call_id}
        self.tools[str(run_id)] = {**row,'tool':name,'callback_id':str(run_id)}
        self.write('tool_started',**self.tools[str(run_id)])

    def finish(self, run_id, error=None, output=None):
        row = self.tools.pop(str(run_id),None)
        if row is None:return
        from langgraph.errors import GraphInterrupt
        interrupted = isinstance(error,GraphInterrupt)
        rejected = (error is not None and not interrupted) or getattr(output,'status',None)=='error'
        if not row['native_call_id']:row['native_call_id']=getattr(output,'tool_call_id',None)
        details = ({'validation_errors':[{'type':v['type'],'loc':v['loc']} for v in error.errors()]}
                   if error is not None and callable(getattr(error,'errors',None)) else {})
        if rejected and error is None:
            try:body=json.loads(getattr(output,'content',''))
            except (ValueError,TypeError):body={}
            if isinstance(body,dict) and body.get('diagnostic') is not None:details['diagnostic']=body['diagnostic']
        if row['native_call_id']:self.observed.add((row['actor'],row['native_call_id']))
        self.write('tool_outcome',**row,rejected=rejected,interrupted=interrupted,codes=_codes(error,output) if rejected else [],**details)

    def on_chain_end(self, outputs, *, run_id, **kwargs):
        # ToolNode can refuse an unavailable tool without invoking BaseTool callbacks.
        from langchain_core.messages import ToolMessage
        messages=outputs.get('messages',[]) if isinstance(outputs,dict) else outputs if isinstance(outputs,list) else []
        for message in messages:
            if not isinstance(message,ToolMessage) or message.status!='error':continue
            row=self.native_calls.get(message.tool_call_id,{'actor':None,'role':None,'task':None,'native_call_id':message.tool_call_id})
            key=(row['actor'],message.tool_call_id)
            if key in self.observed:continue
            self.observed.add(key)
            self.write('tool_outcome',**row,tool=message.name,callback_id=str(run_id),
                       rejected=True,codes=_codes(output=message),origin='returned_tool_message')

    def on_tool_error(self, error, *, run_id, **kwargs):self.finish(run_id,error=error)
    def on_tool_end(self, output, *, run_id, **kwargs):self.finish(run_id,output=output)


@contextmanager
def capture_tools(trace):
    token = _capture.set(trace)
    try:yield trace
    finally:_capture.reset(token)


def summarize_trace(path):
    groups = defaultdict(lambda:dict(calls=set(),rejects=set(),models={},codes=Counter()))
    unattributed, malformed = 0, 0
    started,finished = {},set()
    for line in Path(path).read_text().splitlines() if Path(path).exists() else []:
        try:row=json.loads(line)
        except ValueError:
            malformed+=1;continue
        role=row.get('role');group=groups[role]
        if row['kind']=='model_started':started[row['callback_id']]=row
        elif row['kind']=='model_outcome':
            group['models'][row['callback_id']]=row;finished.add(row['callback_id'])
        elif row['kind']=='tool_outcome':
            if not row.get('actor') or not row.get('native_call_id'):
                unattributed+=1;continue
            key=(row['run_id'],row['actor'],row['native_call_id']);group['calls'].add(key)
            if row['rejected'] and key not in group['rejects']:
                group['rejects'].add(key);group['codes'].update(row['codes'])
    roles={}
    for role,group in groups.items():
        models=list(group['models'].values());usage=[m.get('usage',{}).get('total_tokens') for m in models]
        roles[role]={'model_calls':len(models),'model_failures':sum(m['failed'] and not m.get('admission_denied',False) for m in models),
            'admission_denials':sum(m.get('admission_denied',False) for m in models),
            'provider_usage_calls':sum(v is not None for v in usage),
            'tokens':sum(v for v in usage if v is not None) if any(v is not None for v in usage) else None,
            'tool_calls':len(group['calls']),'tool_rejections':len(group['rejects']),'reasons':dict(group['codes']),
            'model_invocation_ordinal':max((m.get('turn',0) for m in models),default=None),
            'completed_model_seconds':sum(m.get('elapsed_seconds',0) for m in models) if models else None}
    now=datetime.now(timezone.utc)
    inflight=[{'callback_id':key,'role':row['role'],'actor':row['actor'],
        'elapsed_seconds':max(0,(now-datetime.fromisoformat(row['utc'])).total_seconds())}
        for key,row in started.items() if key not in finished]
    return {'roles':roles,'unattributed_tool_outcomes':unattributed,'malformed_lines':malformed,
            'inflight':inflight,'coverage':'partial' if malformed else 'observed callbacks only' if Path(path).exists() else 'unavailable'}
