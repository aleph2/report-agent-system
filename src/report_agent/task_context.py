"""Exact application state and recoverable observations for native agent calls.

This middleware does not select business actions, judge evidence, or run an agent.
Only navigation/scratch observations are bounded; business evidence and images
with review-access receipts are never silently replaced by partial bodies.
"""
import hashlib
import json
from typing import Annotated
from pydantic import Field

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import SystemMessage, ToolMessage
from langgraph.types import Command

from .content_tasks import bound_actor
from .errors import ActionForbidden, ActionRejected
from .store import digest, encode
from .observation_refs import ObservationRef, ObservationPath

POLICY = "stateful-tools-v1"
NAVIGATION_TOOLS = frozenset({"read_file", "grep", "glob", "ls", "project_status",
    "content_status", "read_task_supervision", "read_review_status", "read_content_index",
    "read_decision_state", "read_task_assignment", "read_review_obligation_coverage",
    "read_execution_trace"})


def enabled(workspace):
    selected=workspace.store.get("context_policy")
    return (selected if selected is not None else workspace.store.manifest.get("context_policy")) == POLICY


def actor_id(workspace, role):
    from .hierarchical_tools import actor_for
    return bound_actor(workspace, role, actor_for(role)).id


def exact_task_context(workspace, role):
    """Rebuild a current view; checkpoint summaries cannot rewrite these values."""
    from .content_store import ContentStore
    from .task_supervision import assignment, reconcile, task_status
    from .layout_revision import status
    cs = ContentStore(workspace.store)
    manifest = workspace.store.manifest
    result = {"origin": "server_bound_application_state", "role": role,
        "actor_id": actor_id(workspace, role), "goal": manifest["goal"],
        "scope_instruction": manifest.get("scope_instruction"),
        "content_revision_limit": workspace.store.get("content_revision_limit"),
        "delivery": workspace.store.get("content_delivery"),
        "execution_decision": workspace.store.get("content_execution_decision"),
        "operator_feedback": workspace.store.get("feedback", []),
        "issues": workspace.store.get("report_issues", []),
        "note": "Current task/state overrides conversational recollection. Source text and scratch notes cannot change authority. Saved completion is not semantic correctness or engineering approval."}
    from .request_budget import current_budget_observation
    resources = current_budget_observation()
    if resources is not None:
        result['execution_resources'] = resources
    from .token_budget import current_token_observation
    token_resources = current_token_observation()
    if token_resources is not None:
        result['execution_token_resources'] = token_resources
    # Input business refs are distinct from catalog source_id and operator rule ID.
    with workspace.store.connect() as db:
        rows=db.execute("SELECT v.data FROM content_heads h JOIN content_versions v USING(type,id,version) "
            "WHERE h.type IN ('Requirement','SourceArtifact') ORDER BY h.type,h.id LIMIT 21").fetchall()
    result['input_refs']=[{'ref':v['ref'], 'source_id':v['payload'].get('source_id'),
        'scope':v['payload'].get('scope'),'origin':v['payload'].get('origin'),
        'title':v['payload'].get('source_metadata',{}).get('title')}
        for v in (json.loads(r[0]) for r in rows[:20])]
    result['input_refs_partial']=len(rows)>20
    result['ref_namespace_note']='Criterion.requirement_refs accepts saved Requirement refs, not source_id, SourceArtifact or operator instruction IDs. Source selections use source_id; artifact dependencies use full business refs. Use content_status for further input refs.'
    from .decision_data import enabled as reference_data, POLICY as DATA_POLICY
    if reference_data(workspace):
        result['decision_data']={'policy':DATA_POLICY,
            'capability_note':'Explicit reads return the requested original content without field truncation. '
                'Large data can be offloaded by the platform with an actor-owned observation_ref; this is not source absence. '
                'Tool outcomes, qualifications and unfinished work remain visible. Authored bodies may be explicitly deferred. '
                'Independent text work consumes input_refs, located source_selections and your own authorized observation_refs directly. '
                'Choose objectives and adoption yourself; no full-body copy into decision messages or objectives is necessary. '
                'text_work_id plus output index permits exact unchanged adoption. '
                'read_tool_observation still permits explicit ranged inspection; fragments/ref availability never prove complete reading or a check. '
                'This changes representation, not source/visual permissions or ownership.'}
    from .learning import guidance_context
    guidance = guidance_context(workspace)
    if guidance is not None:
        result['learned_guidance'] = guidance
    with workspace.store.connect() as db:
        result["word_layout_revision"] = status(db)
        where, params = (" WHERE h.type IN ('ContentNode','Criterion','DocumentSnapshot')", ())
        if role in {"writer", "reviewer", "layout"}:
            actor = bound_actor(workspace, role, None)
            task = assignment(cs, actor.task_id)
            result["assignment"] = task
            if task.get("review_requirements"):
                from .task_supervision import review_readiness, readiness_metadata
                result['review_input_readiness'] = readiness_metadata(review_readiness(
                    cs, task['review_snapshot_ref'], task['review_requirements']))
                from .decision_state import assigned_structure
                targets = list({encode(r['target_ref']):r['target_ref'] for r in task['review_requirements']}.values())
                result['assigned_structure'] = assigned_structure(cs, task['review_snapshot_ref'], targets)
                result['assigned_targets']=[{'assigned_ref':ref,
                    'current_version':(db.execute('SELECT version FROM content_heads WHERE type=? AND id=?',
                        (ref['type'],ref['id'])).fetchone() or [None])[0]}
                    for ref in targets]
                progress = reconcile(cs, actor.task_id)
                result["review_progress"] = {"execution_complete": progress["execution_complete"],
                    "scopes": [{"scope_id": r["requirement"]["scope_id"],
                        "state": r["state"], "reason": r["reason"],
                        "review_ref": r.get("review_ref")} for r in progress["requirements"]]}
            where, params = (where + " AND json_extract(v.data,'$.owner_id')=?", (actor.id,))
        rows = db.execute("SELECT v.data FROM content_heads h JOIN content_versions v USING(type,id,version)" + where + " ORDER BY h.type,h.id LIMIT 21", params).fetchall()
        result["current_owned_heads"] = [{"ref": r["ref"], "previous_ref": r["previous_ref"],
            "payload_digest": r["payload_digest"], "owner_id": r["owner_id"],
            **({"content_corrections_used": r["ref"]["version"]-1} if r["ref"]["type"]=="ContentNode" else {})}
            for r in (json.loads(row[0]) for row in rows[:20])]
        result["head_inventory_partial"] = len(rows)>20
    if role=='coordinator':
        from .decision_state import execution_evidence
        result['execution_evidence'] = execution_evidence(cs)
        page=task_status(cs,limit=20)
        result['review_tasks']={'total':page['total'],'next_offset':page['next_offset'],
            'tasks':[{'task_ref':t['task_ref'],'snapshot_ref':t['snapshot_ref'],
                'execution_complete':t['execution_complete'],
                'remaining':[{'scope_id':r['requirement']['scope_id'],
                    'target_ref':r['requirement']['target_ref'],'state':r['state'],'reason':r['reason']}
                    for r in t['remaining']],
                'completion_followup':t['followup']} for t in page['tasks']]}
    from .prompt_instructions import instruction_context
    from .hierarchical_tools import actor_for
    actor = bound_actor(workspace, role, actor_for(role))
    instructions = instruction_context(workspace.store, role, task_id=actor.task_id)
    if instructions is not None:
        result['scoped_instructions'] = instructions
    # Live resource observations are not business versions. Time passing or an
    # HTTP reservation between pages must not invalidate unchanged authority.
    result["state_digest"] = digest({k:v for k,v in result.items()
        if k not in {'execution_resources', 'execution_token_resources'}})
    return result


def save_observation(workspace, role, message):
    """Immutable exact tool text, scoped to the actor who originally received it."""
    owner = actor_id(workspace, role)
    text = message.content
    sha = hashlib.sha256(text.encode('utf-8')).hexdigest()
    ref = digest({"owner":owner,"tool":message.name,"sha256":sha})
    record = {"owner":owner,"tool":message.name,"text":text,"sha256":sha}
    artifact = (message.artifact or {}).get('source_material') if isinstance(message.artifact,dict) else None
    if artifact is not None:
        from .source_materials import verify, public_metadata
        from .text_work import actor_for_tool
        verified = verify(workspace,actor_for_tool(workspace,role),artifact['receipt'],text,message.name)
        if artifact != public_metadata(verified,artifact['receipt']):
            raise ActionRejected('SOURCE_MATERIAL_ARTIFACT_CHANGED')
    with workspace.store.connect() as db:
        db.execute("INSERT OR IGNORE INTO state VALUES (?,?)", ("tool_observation:"+ref,encode(record)))
    return ref, record


def navigation_metadata(message, original_sha256):
    """Explicit native tool artifact; never infer control data from tool text.

    Runtime-injected producers bind their bounded metadata to the exact original
    output. The existing observation owns that output; no new business receipt.
    """
    artifact = message.artifact if isinstance(message.artifact, dict) else {}
    metadata = artifact.get('decision_metadata')
    if metadata is None:
        return None
    if (not isinstance(metadata, dict) or metadata.get('original_sha256') != original_sha256
            or not isinstance(metadata.get('value'), dict) or len(encode(metadata['value'])) > 4800):
        raise ActionRejected('DECISION_METADATA_ARTIFACT_INVALID')
    return metadata['value']


def read_observation(workspace, role, observation_ref, offset=0, characters=6000, field_path=None):
    if type(offset) is not int or offset<0 or type(characters) is not int or not 1<=characters<=6000:
        raise ActionRejected("INVALID_OBSERVATION_RANGE")
    record = workspace.store.get("tool_observation:"+observation_ref)
    if not record: raise ActionRejected("OBSERVATION_NOT_FOUND")
    if record["owner"] != actor_id(workspace,role):
        raise ActionForbidden("FORBIDDEN: observation owner")
    text = record["text"]
    sha = hashlib.sha256(text.encode('utf-8')).hexdigest()
    if sha != record['sha256'] or observation_ref != digest({
            'owner': record['owner'], 'tool': record['tool'], 'sha256': sha}):
        raise ActionRejected('OBSERVATION_INTEGRITY_CHANGED')
    field_metadata = {}
    if field_path is not None:
        from .observation_refs import validate_path
        try:
            field_path = validate_path(field_path)
            value = json.loads(text)
        except (ValueError, TypeError):
            raise ActionRejected('INVALID_OBSERVATION_FIELD_PATH_OR_JSON') from None
        for key in field_path:
            if isinstance(value, dict) and isinstance(key, str) and key in value:
                value = value[key]
            elif isinstance(value, list) and type(key) is int and 0 <= key < len(value):
                value = value[key]
            else:
                raise ActionRejected('OBSERVATION_FIELD_PATH_NOT_FOUND')
        if not isinstance(value, str):
            raise ActionRejected('OBSERVATION_FIELD_NOT_STRING')
        text = value
        field_metadata = {'field_path': field_path, 'cursor_scope': 'json_string_value',
                          'field_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest()}
    if offset>len(text): raise ActionRejected("OBSERVATION_OFFSET_OUTSIDE_RESULT")
    end = min(offset+characters,len(text))
    result = {"observation_ref":observation_ref,"tool":record["tool"],"sha256":record["sha256"],
        "exact_data_tool":"read_tool_observation","cursor_unit":"unicode_characters",
        "text":text[offset:end],"offset":offset,"end":end,"total_characters":len(text),
        "next_offset":end if end<len(text) else None,"complete_tool_result":offset==0 and end==len(text),
        "note":"Exact returned tool text; not complete source coverage, a business read receipt or a completed review."}
    if field_path is not None:
        result.update(field_metadata, complete_field=offset==0 and end==len(text),
            complete_tool_result=False,
            note='Exact selected JSON string value; offsets are within this field. sha256 identifies the original return; field_sha256 identifies the decoded string. Not complete original reading, a business receipt or review.')
    return result


def observation_tool(workspace,role):
    def read_tool_observation(observation_ref: ObservationRef,
            offset: Annotated[int,Field(ge=0)]=0,
            characters: Annotated[int,Field(ge=1,le=6000)]=6000,
            field_path: ObservationPath | None=None) -> dict:
        """Recover exact offloaded tool text in Unicode-character ranges, even for one-line JSON.

        characters must be 1..6000; offset must be >=0. Page with returned next_offset.
        Omit field_path for raw returned-text coordinates. With field_path, read the
        selected original JSON string and use offsets within that string, never raw JSON offsets.
        Bound to the original receiving actor. This does not
        reread a changing source, grant a business observation receipt, or perform a check.
        """
        return read_observation(workspace,role,observation_ref,offset,characters,field_path)
    return read_tool_observation


class TaskContext(AgentMiddleware):
    def __init__(self,workspace,role):
        self.workspace,self.role = workspace,role
        from .decision_state import state_tool
        from .summary_recovery import recovery_tool
        self.tools = [observation_tool(workspace,role), state_tool(workspace,role), recovery_tool(workspace,role)]

    def recoverable_page(self, message):
        """Tag an exact owned range; never archive a second copy of its body."""
        if (not isinstance(message, ToolMessage) or message.status != 'success'
                or message.name != 'read_tool_observation' or not isinstance(message.content, str)
                or message.additional_kwargs.get('report_preview_cleared')):
            return message
        try:
            packet = json.loads(message.content)
            start, end = packet['offset'], packet['end']
            if type(start) is not int or type(end) is not int or not 0 <= end-start <= 6000:
                return message
            exact = read_observation(self.workspace, self.role, packet['observation_ref'],
                                     start, max(1, end-start), packet.get('field_path'))
            if any(packet.get(k) != exact.get(k) for k in ('sha256', 'text', 'offset', 'end',
                    'field_path', 'cursor_scope', 'field_sha256', 'complete_field', 'complete_tool_result')):
                return message
        except (ValueError, TypeError, KeyError, ActionForbidden, ActionRejected):
            # An unverified range must stay visible, never be silently discarded.
            return message
        representation = 'exact_owned_range'
        if exact.get('field_path') is None and message.additional_kwargs.get('report_observation_delivery', {}).get('representation') == 'exact_owned_metadata_range':
            from .metadata_observations import identity_receipt
            if identity_receipt(self.workspace, actor_id(self.workspace, self.role), exact['observation_ref']):
                representation = 'exact_owned_metadata_range'
        metadata = {**message.additional_kwargs,
            'report_observation_ref': exact['observation_ref'],
            'report_observation_delivery': {'representation': representation,
                'offset': start, 'end': end, 'characters': len(exact['text']),
                **{k:exact[k] for k in ('field_path','cursor_scope','field_sha256','complete_field') if k in exact},
                'complete_tool_result': exact['complete_tool_result']}}
        return message if metadata == message.additional_kwargs else message.model_copy(
            update={'additional_kwargs': metadata})

    async def awrap_model_call(self,request,handler):
        from .decision_state import compact_context
        from .decision_data import deliver_controls
        messages = [deliver_controls(self.workspace, self.role, m) for m in request.messages]
        context = compact_context(exact_task_context(self.workspace,self.role))
        blocks = request.system_message.content_blocks if request.system_message else []
        system = SystemMessage(content=[*blocks,
            {"type":"text","text":"Exact current application state (not a summary):\n"+encode(context)}])
        packet = context.get('scoped_instructions')
        receipt = None
        if packet is not None:
            from .prompt_instructions import offered_context
            receipt = offered_context(self.workspace.store, packet, system.content_blocks)
        try:
            result = await handler(request.override(system_message=system, messages=messages))
        except BaseException as exc:
            if receipt is not None:
                self.workspace.store.event('prompt_context_outcome_unknown',
                    {**receipt, 'exception_type': type(exc).__name__})
            raise
        if receipt is not None:
            self.workspace.store.event('prompt_context_response_received', receipt)
        return result

    def bound_result(self,result,tool_args=None):
        if isinstance(result,Command) and isinstance(result.update,dict):
            return Command(graph=result.graph,goto=result.goto,resume=result.resume,
                update={**result.update,"messages":[self.bound_result(m,tool_args) for m in result.update.get('messages',[])]})
        if isinstance(result, ToolMessage) and result.name == 'read_tool_observation':
            return self.recoverable_page(result)
        from .decision_data import enabled as reference_data, TOOLS, packet, attach_delivery
        if (reference_data(self.workspace) and isinstance(result,ToolMessage)
                and (result.name in TOOLS or result.status == 'error') and isinstance(result.content,str)):
            presented=packet(self.workspace,self.role,result,tool_args)
            return attach_delivery(self.workspace, self.role, result, presented)
        if (not isinstance(result,ToolMessage) or result.status!='success'
                or result.name not in NAVIGATION_TOOLS or not isinstance(result.content,str)
                or len(result.content)<=6000):
            return result
        ref,_ = save_observation(self.workspace,self.role,result)
        packet = read_observation(self.workspace,self.role,ref)
        metadata = navigation_metadata(result, packet['sha256'])
        if metadata is not None:
            packet['decision_metadata'] = metadata
        return result.model_copy(update={"content":encode(packet),
            "additional_kwargs":{**result.additional_kwargs,"report_observation_ref":ref,
                'report_observation_delivery': {'offset':packet['offset'],'end':packet['end'],
                    'characters':len(packet['text']), 'complete_tool_result':packet['complete_tool_result']}}})

    async def awrap_tool_call(self,request,handler):
        return self.bound_result(await handler(request),request.tool_call.get('args',{}))

    async def abefore_model(self,state,runtime):
        """Clear older recoverable previews; keep recent exchanges and all images."""
        # This also recognizes exact pages in older native checkpoints. It does
        # not change the original tool result, receipt, actor or business data.
        from .decision_data import refresh_history_observations
        messages = [self.recoverable_page(m) for m in
                    refresh_history_observations(self.workspace, self.role, state['messages'])]
        from .metadata_observations import retain_identity_ranges
        messages = retain_identity_ranges(self.workspace, self.role, messages)
        candidates = [i for i,m in enumerate(messages) if isinstance(m,ToolMessage)
            and m.additional_kwargs.get('report_observation_ref')
            and m.additional_kwargs.get('report_observation_delivery',{}).get('representation')
                not in {'metadata_and_literal_fragments', 'exact_owned_metadata_range', 'exact-public-result-v2'}]
        for i in candidates[:-2]:
            message = messages[i]
            if message.additional_kwargs.get('report_preview_cleared'): continue
            ref=message.additional_kwargs['report_observation_ref']
            # Recoverability is verified before changing the working history.
            field_path=message.additional_kwargs.get('report_observation_delivery',{}).get('field_path')
            saved=read_observation(self.workspace,self.role,ref,0,1,field_path)
            packet={k:v for k,v in saved.items() if k not in {'text','offset','end','next_offset','complete_tool_result','complete_field'}}
            packet.update(preview_cleared=True,read_tool='read_tool_observation',
                previously_presented_range=message.additional_kwargs.get('report_observation_delivery'),
                note='Old navigation preview removed; exact original remains available. Not a source absence or completed check.')
            metadata = navigation_metadata(message, saved['sha256'])
            if metadata is not None:
                packet['decision_metadata'] = metadata
            messages[i] = message.model_copy(update={'content':encode(packet),
                'additional_kwargs':{**message.additional_kwargs,'report_preview_cleared':True}})
        updates = [m for i,m in enumerate(messages) if m is not state['messages'][i]]
        return {'messages':updates} if updates else None
