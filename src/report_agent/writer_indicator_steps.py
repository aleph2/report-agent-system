"""Host-owned, finite indicator steps for the explicitly selected assessment workflow."""
import json
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_core.messages import HumanMessage, ToolMessage

from .content_store import ContentStore
from .deep_runtime import BusinessBoundary
from .errors import ActionRejected
from .native_operation_tools import _native_write
from .prompt_provenance import AgentPromptBoundary, append_declared_system
from .prompt_sources import load_prompt, record_runtime_version

READ = 'read_assigned_page'
SAVE = 'save_indicator_outcome'
ISSUE = 'propose_material_issue'
PAGE_LIMIT = 3


class IndicatorBoundary(AgentMiddleware):
    """BusinessBoundary serializes tool execution, including calls in one model batch."""
    def __init__(self):
        self.reads = 0
        self.locations = []
        self.issue_saved = False
        self.saved = False

    def offered(self, name):
        return not self.saved and (name == SAVE or self.reads < PAGE_LIMIT and
            (name == READ or name == ISSUE and not self.issue_saved))

    async def awrap_model_call(self, request, handler):
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
                self.locations.append({k:call['args'][k] for k in ('source_handle','page')})
            elif name == ISSUE:
                self.issue_saved = True
        return result

    @hook_config(can_jump_to=['end'])
    async def abefore_model(self, state, runtime):
        if self.saved:
            return {'jump_to':'end'}


class IndicatorToolReceipts(BusinessBoundary):
    """Keep observed errors even when the following provider request is interrupted."""
    def __init__(self, workspace):
        super().__init__(workspace,'writer',indicator_step=True)
        self.refusals_by_call = {}

    def _record_tool_result(self, request, result):
        from .writer_probe import refusal_rows
        result = super()._record_tool_result(request,result)
        # Each run owns one actor. Native call IDs deduplicate within that actor.
        for row in refusal_rows([result]):
            self.refusals_by_call.setdefault(row['tool_call_id'],row)
        return result


class IndicatorRun:
    def __init__(self, workspace, actor, model, tools):
        self.workspace, self.actor, self.model = workspace, actor, model
        self.tools = [t for t in tools if t.name in {READ,ISSUE}]
        self.tool_names = [*(t.name for t in self.tools), SAVE]
        self.receipts = IndicatorToolReceipts(workspace)
        self.progress = None

    @property
    def refusals(self):
        return list(self.receipts.refusals_by_call.values())

    def _record_progress(self, status):
        self.progress = {k:status[k] for k in ('progress','assessment_ref','gap_indicators')}

    async def run(self):
        from .writer_assessment import read_indicator_step, save_indicator_outcome, step_outcome_schema
        cs = ContentStore(self.workspace.store)
        step = read_indicator_step(cs, self.actor)
        self._record_progress(step)
        while not step['complete']:
            indicator_id = step['indicator_id']
            boundary = IndicatorBoundary()
            def save(operation_id: str, **outcome) -> dict:
                """Save this indicator as evidence, an assumption or an explicit gap."""
                receipt = save_indicator_outcome(cs, self.actor, operation_id, indicator_id,
                    outcome, read_locations=boundary.locations)
                self._record_progress(receipt['result'])
                boundary.saved = True
                return receipt
            save.__name__ = SAVE
            save.message_model = step_outcome_schema(cs, self.actor, indicator_id)
            tools = [*self.tools, _native_write(self.workspace,'writer',save)]
            agent = create_agent(self.model,tools,system_prompt=load_prompt('writer-indicator-step'),
                middleware=[self.receipts,boundary,
                            AgentPromptBoundary(self.workspace,'writer',source='writer-indicator-step')],
                name='assessment_writer')
            # An independent graph invocation per indicator keeps only the current three pages.
            config = {'recursion_limit':30,'configurable':{'thread_id':self.actor.task_id+':'+indicator_id},
                'metadata':{'report_runtime_version_ref':record_runtime_version(self.workspace.store),
                    'report_operation_identity_profile':'native-tool-runtime-v1'}}
            message = HumanMessage(content=json.dumps(step,ensure_ascii=False))
            await agent.ainvoke({'messages':[message]},config)
            if not boundary.saved:
                raise ActionRejected('PROBE_INDICATOR_STEP_INTERRUPTED')
            next_step = read_indicator_step(cs, self.actor)
            if next_step['progress']['recorded'] != step['progress']['recorded']+1:
                raise ActionRejected('PROBE_INDICATOR_PROGRESS_MISMATCH')
            step = next_step
        return self.progress


async def run_mini_assessment(workspace, model, *, verified_run):
    """Two assessment delegations from an approved synthetic plan; caller owns the grant and run lock."""
    import re
    from .commission_plan import _confirmed, outside_boundary
    from .fake_verification import assert_active_fake_run
    from .writer_runtime import writer_session
    assert_active_fake_run(verified_run,workspace)
    cs = ContentStore(workspace.store)
    with cs.store.connect() as db:
        plan, decision = _confirmed(cs,db)
    if plan['ref'] != verified_run.plan_ref:
        raise ActionRejected('FAKE_CONFIRMED_PLAN_CHANGED')
    payload = plan['payload']
    reduced = {r['object_id'] for r in decision['payload'].get('reductions',[])}
    objects = {obj['object_id']:obj for obj in payload['objects']
               if obj['included'] and not outside_boundary(payload,obj) and obj['object_id'] not in reduced}
    ids = [row['id'] for row in (payload.get('method_pack') or {}).get('indicators',[])]
    order = (payload.get('indicator_rank_order') or {}).get('indicator_ids',[])
    if (set(objects) != {'A','B'} or len({obj['label'] for obj in objects.values()}) != 2
            or len(ids) != 11 or len(order) != 11 or set(order) != set(ids)):
        raise ActionRejected('FAKE_TWO_SLOPE_RANKED_PLAN_REQUIRED')
    result = {'status':'running','scope':'assessment_writer_only','plan_ref':plan['ref'],
              'decision_ref':decision['ref'],'slopes':[],'engineering_acceptance':False}
    for object_id in ('A','B'):
        slope = {'object_id':object_id}
        result['slopes'].append(slope)
        try:
            with writer_session(workspace,objects[object_id]['label'],model,assessment_only=True,
                                indicator_steps=True,section_id=verified_run.assessment_section_id) as session:
                slope['writer_actor'] = session.actor.id
                try:
                    await session.run()
                    if session.progress['gap_indicators']:
                        slope['status'] = 'closed_with_gaps'
                    elif session.progress['assessment_ref']:
                        slope['status'] = 'assessment_saved'
                    else:
                        raise ActionRejected('WRITER_COMPLETION_RECEIPT_MISSING')
                finally:
                    slope.update(indicator_steps=session.progress,refusals=session.refusals)
        except Exception as exc:
            slope.update(status='interrupted',error_type=type(exc).__name__)
            code = str(exc)
            if re.fullmatch(r'(WRITER|FAKE|PROBE|SCOPED|COMMISSION|REQUEST|TOKEN)_[A-Z0-9_]{1,140}',code):
                slope['stop_code'] = code
            result['status'] = 'interrupted'
            return result
    result['status'] = 'closed_with_gaps' if any(s['status']=='closed_with_gaps' for s in result['slopes']) else 'assessments_saved'
    return result
