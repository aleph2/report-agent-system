"""Host-owned, finite indicator steps for the explicitly selected assessment workflow."""
import json
import re
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.errors import GraphRecursionError

from .content_store import ContentStore
from .deep_runtime import BusinessBoundary
from .errors import ActionRejected
from .native_operation_tools import _native_write
from .prompt_provenance import AgentPromptBoundary, append_declared_system
from .prompt_sources import load_prompt, record_runtime_version

READ = 'read_assigned_page'
SAVES = ('save_evidence','save_assumption','save_gap')
ISSUE = 'propose_material_issue'
EXTRACTION = {'assert_source', 'record_conflict'}
PAGE_LIMIT = 3


def refusal_rows(messages):
    from langchain_core.messages import ToolMessage
    result = {}
    for message in messages:
        if not isinstance(message,ToolMessage) or message.status != 'error':
            continue
        try:
            body = json.loads(message.content) if isinstance(message.content, str) else {}
        except (TypeError,ValueError):
            body = {}
        code = body.get('code') if isinstance(body,dict) else None
        result[message.tool_call_id] = {'tool':message.name,'tool_call_id':message.tool_call_id,
            'code':code if isinstance(code,str) and re.fullmatch('[A-Z][A-Z0-9_]{0,150}',code) else 'TOOL_REFUSED'}
    return list(result.values())



class IndicatorBoundary(AgentMiddleware):
    """BusinessBoundary serializes tool execution, including calls in one model batch."""
    def __init__(self, *, one_request=False):
        self.one_request = one_request
        self.requested = False
        self.reads = 0
        self.locations = []
        self.issue_saved = False
        self.saved = False
        self.save_refusals = {}

    def offered(self, name):
        return not self.saved and len(self.save_refusals)<2 and (
            name in SAVES or name in EXTRACTION or name==READ and self.reads<PAGE_LIMIT or name==ISSUE and not self.issue_saved)

    async def awrap_model_call(self, request, handler):
        if self.one_request and self.requested:
            raise ActionRejected('WRITER_CONTINUATION_REQUEST_USED')
        self.requested = True
        request = append_declared_system(request,
            f'Page read attempts left for this indicator: {PAGE_LIMIT-self.reads}.',
            'indicator_step/reading_allowance')
        return await handler(request.override(tools=[t for t in request.tools if self.offered(t.name)]))

    async def awrap_tool_call(self, request, handler):
        call = request.tool_call
        name = call['name']
        if not self.offered(name):
            raise ActionRejected('WRITER_STEP_TOOL_UNAVAILABLE')
        if name == READ:
            self.reads += 1
        result = await handler(request)
        if isinstance(result, ToolMessage) and result.status == 'success':
            if name == READ:
                location = {k:call['args'][k] for k in ('source_handle','page')}
                if isinstance(result.artifact, dict) and result.artifact.get('writer_page_delivery'):
                    location['delivery'] = result.artifact['writer_page_delivery']
                self.locations.append(location)
            elif name == ISSUE:
                self.issue_saved = True
        return result

    @hook_config(can_jump_to=['end'])
    async def abefore_model(self, state, runtime):
        if self.saved or len(self.save_refusals)==2 or (self.one_request and self.requested):
            return {'jump_to':'end'}


class IndicatorToolReceipts(BusinessBoundary):
    """Keep observed errors even when the following provider request is interrupted."""
    def __init__(self, workspace):
        super().__init__(workspace,'writer',indicator_step=True)
        self.refusals_by_call = {}
        self.boundary = None

    def _observe_refusal(self, message):
        for row in refusal_rows([message]):
            call_id = row['tool_call_id']
            try:
                body = json.loads(message.content)
            except (TypeError, ValueError):
                body = {}
            body = body if isinstance(body, dict) else {}
            parser = body.get('parser_diagnostic')
            if isinstance(parser, dict):
                row = {**row, 'parser_diagnostic': {
                    k: parser[k] for k in ('message','line','column','character_offset') if k in parser}}
            self.refusals_by_call.setdefault(call_id, row)
            if (self.boundary is None or row['tool'] not in SAVES
                    or len(self.boundary.save_refusals) >= 2 or row['code'] == 'WRITER_STEP_TOOL_UNAVAILABLE'):
                continue
            diagnostic = body.get('diagnostic')
            if isinstance(diagnostic, dict):
                fields = diagnostic.get('fields', [])
                row = {**row, 'diagnostic': {'fields': [
                    {k: f[k] for k in ('field','reason','correction','message','related_fields') if k in f}
                    for f in fields if isinstance(f, dict)]}}
            self.boundary.save_refusals.setdefault(call_id, row)

    def _record_tool_result(self, request, result):
        result = super()._record_tool_result(request, result)
        self._observe_refusal(result)
        return result

    @hook_config(can_jump_to=['model', 'end'])
    async def aafter_model(self, state, runtime):
        updates = await super().aafter_model(state, runtime)
        if not updates or not updates.get('messages'):
            return updates
        latest = next(m for m in reversed(state['messages']) if isinstance(m, AIMessage))
        invalid_names = {c['id']: c['name'] for c in latest.invalid_tool_calls}
        from .runtime_metrics import emit
        # Parser refusals are known before the tool node executes any valid siblings.
        for message in updates['messages']:
            if not isinstance(message, ToolMessage) or message.tool_call_id not in invalid_names:
                continue
            call_id = message.tool_call_id
            if call_id not in self.refusals_by_call:
                emit(self.workspace.store.root, 'tool_rejected', {'role': self.role, 'tool_call_id': call_id})
            self._observe_refusal(message.model_copy(update={'name': invalid_names[call_id]}))
        if (self.boundary is not None and len(self.boundary.save_refusals) == 2
                and updates.get('jump_to') == 'model'):
            updates['jump_to'] = 'end'
        return updates


class IndicatorRun:
    def __init__(self, workspace, actor, model, tools):
        self.workspace, self.actor, self.model = workspace, actor, model
        self.tools = [t for t in tools if t.name in {READ,ISSUE,*EXTRACTION}]
        self.tool_names = [*(t.name for t in self.tools), *SAVES]
        self.receipts = IndicatorToolReceipts(workspace)
        self.progress = None

    @property
    def refusals(self):
        return list(self.receipts.refusals_by_call.values())

    def _record_progress(self, status):
        self.progress = {k:status[k] for k in ('progress','assessment_ref','gap_indicators','interrupted_indicators')}

    async def run(self, *, continuation=None):
        from .writer_assessment import (read_indicator_step, save_indicator_outcome, step_outcome_schema,
                                        interrupt_indicator_step)
        cs = ContentStore(self.workspace.store)
        step = read_indicator_step(cs, self.actor)
        self._record_progress(step)
        while not step['complete']:
            indicator_id = step['indicator_id']
            boundary = IndicatorBoundary(one_request=continuation is not None)
            if continuation is not None:
                original_step, prior_reads = continuation
                if original_step != step or len(prior_reads) != PAGE_LIMIT:
                    raise ActionRejected('WRITER_CONTINUATION_STEP_MISMATCH')
                boundary.locations = [r['location'] for r in prior_reads]
                boundary.reads = len(prior_reads)
            self.receipts.boundary = boundary
            def save_tool(kind):
                schema = step_outcome_schema(cs, self.actor, indicator_id, kind)
                def save(operation_id: str, **outcome) -> dict:
                    # Native tools pass nested Pydantic objects. Hash the supplied JSON fields.
                    outcome = schema.model_validate(outcome).model_dump(mode='json', exclude_unset=True)
                    receipt = save_indicator_outcome(cs,self.actor,operation_id,indicator_id,
                        {**outcome,'kind':kind},read_locations=boundary.locations)
                    self._record_progress(receipt['result'])
                    boundary.saved = True
                    return receipt
                save.__name__ = 'save_'+kind
                save.__doc__ = {
                    'evidence':'Save a supported grade, numeric value, rationale and exact evidence quotes.',
                    'assumption':'Save a supported assumption, rationale, plausible grades and a review question.',
                    'gap':'Record missing information, a review question and optional rationale without a score.'}[kind]
                save.message_model=schema
                return _native_write(self.workspace,'writer',save)
            kinds = ('gap',) if step.get('engineering_review') else ('evidence','assumption','gap')
            tools=[*self.tools,*(save_tool(k) for k in kinds)]
            agent = create_agent(self.model,tools,system_prompt=load_prompt('writer-indicator-step'),
                middleware=[self.receipts,boundary,
                            AgentPromptBoundary(self.workspace,'writer',source='writer-indicator-step')],
                name='assessment_writer')
            # An independent graph invocation per indicator keeps only the current three pages.
            from .run_authority import graph_config
            config = {**graph_config('assessment'),'configurable':{'thread_id':self.actor.task_id+':'+indicator_id},
                'metadata':{'report_runtime_version_ref':record_runtime_version(self.workspace.store),
                    'report_operation_identity_profile':'native-tool-runtime-v1'}}
            message = HumanMessage(content=json.dumps(step,ensure_ascii=False))
            messages = [message]
            if continuation is not None:
                messages.append(HumanMessage(content=json.dumps(
                    {'prior_page_read_results_for_this_indicator':prior_reads},ensure_ascii=False)))
            try:
                await agent.ainvoke({'messages':messages},config)
            except GraphRecursionError:
                # The native save can commit on the last graph step, before the end hook runs.
                if not boundary.saved:
                    outcome={'task_id':self.actor.task_id,'object_label':step['object_label'],
                        'indicator_id':indicator_id,'supersteps':config['recursion_limit']}
                    self.workspace.store.event('assessment_graph_step_limit',outcome)
                    raise ActionRejected('ASSESSMENT_GRAPH_STEP_LIMIT',diagnostic=outcome) from None
            if len(boundary.save_refusals)==2 and not boundary.saved:
                receipt=interrupt_indicator_step(cs,self.actor,indicator_id,list(boundary.save_refusals.values()))
                self._record_progress(receipt['result'])
            elif not boundary.saved and continuation is None:
                raise ActionRejected('PROBE_INDICATOR_STEP_INTERRUPTED')
            if continuation is not None:
                return self.progress
            next_step = read_indicator_step(cs, self.actor)
            if (next_step['progress']['recorded']+len(next_step['interrupted_indicators'])
                    != step['progress']['recorded']+len(step['interrupted_indicators'])+1):
                raise ActionRejected('PROBE_INDICATOR_PROGRESS_MISMATCH')
            step = next_step
        return self.progress
