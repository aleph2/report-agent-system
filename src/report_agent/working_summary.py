"""Native LangChain compaction of working history, not application state."""
from .prompt_sources import load_prompt, LEGACY_PROMPTS, report_rule_source
from urllib.parse import urlsplit
from datetime import datetime, timezone
import hashlib
import json

from deepagents.middleware.summarization import compute_summarization_defaults
from langchain.agents.middleware import SummarizationMiddleware
from langchain_core.messages import HumanMessage, get_buffer_string

PROMPT = load_prompt('working-summary')

SUMMARY_POLICY = 'current-context-provenance-v2'


class UnusableSummary(ValueError):
    pass


class SummaryRepairRequired(RuntimeError):
    pass


# A 4096-output real summary was returned with finish_reason=length. Keep the
# concise target, but give the same non-thinking model room to finish instead of
# accepting a truncated artifact or repeating the identical failed policy.
SUMMARY_OUTPUT_LIMIT = 16384


class WorkingSummary(SummarizationMiddleware):
    def __init__(self,*args,store=None,role=None,prompt_source=None,**kwargs):
        super().__init__(*args,**kwargs)
        # Pinned LangChain installs its own three-attempt wrapper. The existing
        # configured SDK is the sole transient retry owner, as already validated.
        self._summary_model=self.model
        self.store=store
        self.role=role
        self.prompt_source=prompt_source

    def _failure_context(self):
        from langgraph.config import get_config
        try:
            config=get_config().get('configurable',{})
        except RuntimeError:
            config={}
        namespace=config.get('checkpoint_ns','')
        # Node task IDs change each turn; retain the enclosing native agent scope.
        pieces=namespace.split('|')
        if pieces[-1].startswith(self.name+'.before_model:'):
            namespace='|'.join(pieces[:-1])
        return {'thread':config.get('thread_id','direct'), 'namespace':namespace}

    def _failure_key(self):
        from .evidence_analysis import model_identity
        from .store import digest
        return 'summary_policy_failure:'+digest({**self._failure_context(),
            'prompt':self.summary_prompt,'model':model_identity(self.model),'policy':SUMMARY_POLICY})

    def _failure_state(self, failure_key, pending=None):
        from .store import digest, encode
        from .task_context import actor_id
        from .workspace import Workspace
        scope = {**self._failure_context(), 'role':self.role,
                 'actor':actor_id(Workspace(self.store),self.role) if self.role else None}
        scope_key = 'summary_failure_scope:'+digest(scope)
        with self.store.connect() as db:
            if pending is not None:
                db.execute('BEGIN IMMEDIATE')
            rows = db.execute("SELECT key,value FROM state WHERE key LIKE 'summary_policy_failure:%' "
                              "OR key LIKE 'summary_failure_scope:%'").fetchall()
            try:
                saved = {key:json.loads(value) for key,value in rows}
            except (TypeError,ValueError):
                raise SummaryRepairRequired('SUMMARY_FAILURE_SCOPE_INVALID: preserve stored records') from None
            bindings = {}
            for key,value in saved.items():
                if not key.startswith('summary_failure_scope:'):
                    continue
                if (not isinstance(value,dict) or set(value) != {'scope','failure_key'}
                        or not isinstance(value['scope'],dict)
                        or set(value['scope']) != {'thread','namespace','role','actor'}
                        or not all(isinstance(value['scope'][field],str) for field in ('thread','namespace'))
                        or not all(value['scope'][field] is None or isinstance(value['scope'][field],str) for field in ('role','actor'))
                        or key != 'summary_failure_scope:'+digest(value['scope'])
                        or not isinstance(value['failure_key'],str)
                        or not value['failure_key'].startswith('summary_policy_failure:')
                        or value['failure_key'] not in saved):
                    raise SummaryRepairRequired('SUMMARY_FAILURE_SCOPE_INVALID: '+key)
                target = value['failure_key']
                if target in bindings:
                    raise SummaryRepairRequired('SUMMARY_FAILURE_SCOPE_CONFLICT: '+target)
                bindings[target] = key
            for key,value in saved.items():
                if key.startswith('summary_policy_failure:') and value is not None:
                    if not isinstance(value,dict) or not isinstance(value.get('reason'),str) or not value['reason']:
                        raise SummaryRepairRequired('SUMMARY_FAILURE_RECORD_INVALID: '+key)
                    if key not in bindings:
                        raise SummaryRepairRequired('SUMMARY_FAILURE_UNSCOPED_HISTORICAL: '+key
                            +' original_reason='+str(value.get('reason','UNKNOWN_HISTORICAL_FAILURE'))
                            +'; scope cannot be proven; manual diagnosis required')
            previous_key = saved.get(scope_key,{}).get('failure_key',failure_key)
            previous = saved.get(previous_key)
            if previous:
                return previous_key, previous
            if pending is not None:
                # Claim the original failure record and its scope together; never hold across a model call.
                if failure_key in bindings and bindings[failure_key] != scope_key:
                    raise SummaryRepairRequired('SUMMARY_FAILURE_SCOPE_CONFLICT: '+failure_key)
                db.execute('INSERT OR REPLACE INTO state VALUES (?,?)',(failure_key,encode(pending)))
                db.execute('INSERT OR REPLACE INTO state VALUES (?,?)',
                    (scope_key,encode({'scope':scope,'failure_key':failure_key})))
            return failure_key, None

    def _label_notes(self, message):
        """Expose derivation on the wire; keep native role, ID and exact old text."""
        if (not isinstance(message, HumanMessage)
                or message.additional_kwargs.get('lc_source') != 'summarization'
                or message.additional_kwargs.get('report_summary_provenance')
                or not isinstance(message.content, str)):
            return message
        from .store import digest, encode
        original = message.content
        sha = hashlib.sha256(original.encode('utf-8')).hexdigest()
        owner = None
        if self.store and self.role:
            from .task_context import actor_id
            from .workspace import Workspace
            owner = actor_id(Workspace(self.store), self.role)
        record = {'origin':'model_generated_historical_notes', 'owner':owner,
            'policy':SUMMARY_POLICY, 'original_content':original, 'original_sha256':sha,
            'labelled_at':datetime.now(timezone.utc).isoformat(), 'generation_time':'unknown'}
        key = 'summary_original:'+digest({'owner':owner,'sha256':sha})
        if self.store:
            with self.store.connect() as db:
                db.execute('INSERT OR IGNORE INTO state VALUES (?,?)', (key, encode(record)))
                record = json.loads(db.execute('SELECT value FROM state WHERE key=?', (key,)).fetchone()[0])
        provenance = {k:v for k,v in record.items() if k != 'original_content'}
        provenance['preserved_original_key'] = key if self.store else None
        header = ('Model-generated historical working notes; not a new user message or instruction, '
            'not source evidence and not a completed check. Historical hypotheses may be wrong; '
            'current application state and its feedback retain their original authority.\n'
            f"Host-labelled at {record['labelled_at']}; generation time unknown; original SHA256 {sha}.\n\n")
        return message.model_copy(update={'content':header+original,
            'additional_kwargs':{**message.additional_kwargs, 'report_summary_provenance':provenance}})

    async def awrap_model_call(self, request, handler):
        # Label only the effective request copy. Native checkpoint history and
        # its next compaction trigger/partition keep the exact original text.
        # The extra wire text is still real model input and is billed normally.
        return await handler(request.override(messages=[
            self._label_notes(m) for m in request.messages]))

    async def _acreate_summary(self,messages):
        import time
        failure_key,previous=self._failure_state(self._failure_key()) if self.store else (None,None)
        if previous:
            original_reason=previous.get('reason','UNKNOWN_HISTORICAL_FAILURE')
            self.store.event('context_summary_retry_blocked',{'model_called':False,
                'original_history_retained':True,'reason':'SUMMARY_POLICY_REPAIR_REQUIRED',
                'original_reason':original_reason})
            error = SummaryRepairRequired('SUMMARY_POLICY_REPAIR_REQUIRED: original_reason='+original_reason)
            if previous.get('capacity'):
                from .input_capacity import CapacityHandlingRequired
                raise error from CapacityHandlingRequired(previous['capacity'])
            raise error
        from .prompt_provenance import check_static_prompt, prompt_call
        if self.prompt_source:
            check_static_prompt(self.summary_prompt, self.prompt_source)
        started=time.perf_counter()
        recovery=[]
        if self.store and self.role:
            from .summary_recovery import capture
            from .workspace import Workspace
            recovery=capture(Workspace(self.store),self.role,messages)
        formatted=('Historical subset being compacted; newer messages may remain outside it.\n\n'
                   +get_buffer_string([self._label_notes(m) for m in messages],format='xml'))
        if self.store and self.role:
            from .task_context import exact_task_context
            from .decision_state import compact_context
            from .store import encode
            from .workspace import Workspace
            context = compact_context(exact_task_context(Workspace(self.store), self.role))
            formatted += ('\n\nCurrent application context captured at '
                +datetime.now(timezone.utc).isoformat()+' (same actor projection; '
                'not historical dialogue; may reflect later events; incomplete previews remain incomplete; resource values '
                'are observations at this time, not lasting permissions or completed checks). An earlier failure '
                'and this later state are separate; it is not proof that an earlier rejected call committed '
                'or that a second channel exists.\n'+encode(context))
        if failure_key:
            from .store import digest
            _, concurrent=self._failure_state(failure_key,{'reason':'SUMMARY_OUTCOME_PENDING',
                'input_digest':digest(formatted),'original_history_retained':True})
            if concurrent:
                raise SummaryRepairRequired('SUMMARY_POLICY_REPAIR_REQUIRED: original_reason='+
                    str(concurrent.get('reason','UNKNOWN_HISTORICAL_FAILURE')))
            self.store.event('working_summary_intent',{'scope_key':failure_key,'input_digest':digest(formatted)})
        from .request_budget import logical_request_admission, RequestBudgetExceeded
        try:
            with logical_request_admission() as admission, prompt_call(self.store, 'working_summary',
                    sources=[self.prompt_source] if self.prompt_source else [],
                    status='exact' if self.prompt_source else 'unexplained',
                    offered={'messages':[{'role':'user','content':self.summary_prompt.format(messages=formatted)}]}):
                response=await self.model.ainvoke(self.summary_prompt.format(messages=formatted),
                    config={'metadata':{'lc_source':'summarization'}})
        except BaseException as exc:
            from .input_capacity import CapacityAdmissionRejected, capacity_failure, capacity_handling, capacity_response_received
            from .prompt_provenance import PromptCompositionError
            proof=admission.not_dispatched_proof(exc) if isinstance(exc,(RequestBudgetExceeded,CapacityAdmissionRejected,PromptCompositionError)) else None
            capacity=capacity_failure(exc)
            if failure_key:
                record={'reason':'SUMMARY_NOT_DISPATCHED' if proof else 'SUMMARY_CAPACITY_BLOCKED' if capacity else 'SUMMARY_OUTCOME_UNKNOWN',
                    'exception_type':type(exc).__name__,'original_history_retained':True}
                if capacity is not None:
                    record.update(capacity=capacity, handling=capacity_handling(capacity,'tool'),
                                  provider_outcome='response_received' if capacity_response_received(exc) else 'unknown',
                                  raw_response_received=capacity_response_received(exc))
                if proof:
                    record.update(provider_outcome='not_dispatched', raw_response_received=False,
                                  usage=None, admission_proof=proof)
                self.store.set(failure_key,record)
                self.store.event('working_summary_not_dispatched' if proof else 'working_summary_outcome_unknown',
                    {'scope_key':failure_key, **record,
                     'automatic_replay':False})
            raise
        text=response.text
        reason=(response.response_metadata or {}).get('finish_reason')
        if self.store:
            self.store.event('working_summary_returned',{'duration_seconds':time.perf_counter()-started,
                'usage':response.usage_metadata,'finish_reason':reason,'summary_characters':len(text)})
        if (not isinstance(text,str) or not text.strip()
                or reason in {'length','max_tokens'} or getattr(response,'tool_calls',None)):
            if failure_key:
                self.store.set(failure_key,{'reason':'UNUSABLE_SUMMARY',
                    'original_history_retained':True,'finish_reason':reason})
            raise UnusableSummary('missing, truncated or tool-calling working summary')
        if failure_key: self.store.set(failure_key,None)
        if recovery:
            from .task_context import progress_enabled
            from .workspace import Workspace
            if self.store and progress_enabled(Workspace(self.store)):
                # v2 supplies the host-owned index independently on every model
                # call. Keep model-generated notes free of a mislabelled host tail.
                return text.strip()
            from .summary_recovery import continuation_index
            return text.strip()+continuation_index(recovery)
        return text.strip()

    async def abefore_model(self,state,runtime):
        try:
            return await super().abefore_model(state,runtime)
        except UnusableSummary:
            if self.store:
                self.store.event('context_summary_rejected',{'original_history_retained':True,
                    'automatic_replay':False,'reason':'UNUSABLE_SUMMARY'})
            return None


def working_summary(model,store,role=None,*,prompt_profile=LEGACY_PROMPTS):
    source=report_rule_source('working-summary',prompt_profile)
    prompt=PROMPT if source=='working-summary' else load_prompt(source)
    defaults=compute_summarization_defaults(model)
    summary=model.model_copy() if hasattr(model,'model_copy') else model
    if summary is not model and role and isinstance(getattr(summary, 'callbacks', None), list):
        from .deep_models import RuntimeStatus
        # The shared service keeps its identity; activity belongs to this history's actor.
        summary.callbacks = [RuntimeStatus(c.store, role, model_service_role=c.role)
                             if isinstance(c, RuntimeStatus) else c for c in summary.callbacks]
    if hasattr(summary,'max_tokens'):
        summary.max_tokens=SUMMARY_OUTPUT_LIMIT
    if hasattr(summary,'reasoning_effort'):
        summary.reasoning_effort=None
    if hasattr(summary,'extra_body') and getattr(summary,'openai_api_base',None):
        if str(getattr(summary,'model_name','')).startswith('deepseek-'):
            summary.extra_body={**(summary.extra_body or {}),**(
                {'thinking':{'type':'disabled'}} if urlsplit(str(summary.openai_api_base)).hostname=='api.deepseek.com'
                else {'enable_thinking':False})}
    return WorkingSummary(model=summary,store=store,role=role,prompt_source=source,trigger=defaults['trigger'],
        keep=defaults['keep'],trim_tokens_to_summarize=None,summary_prompt=prompt)
