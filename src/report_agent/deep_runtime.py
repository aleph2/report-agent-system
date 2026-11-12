"""Native DeepAgents runtime with project-bound business tools, not a stage engine."""
from __future__ import annotations
from . import issue_state
from . import legacy_state
from .prompt_sources import load_prompt

import asyncio
import json
import os
import httpx
import openai
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Annotated, Literal
from pydantic import Field
from uuid import uuid4

from deepagents import create_deep_agent, register_harness_profile, HarnessProfile, GeneralPurposeSubagentProfile
from deepagents.backends import StateBackend
from deepagents.middleware.filesystem import FilesystemMiddleware
from langchain.agents.middleware import AgentMiddleware, TodoListMiddleware, hook_config
from langchain.tools import ToolRuntime
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command, interrupt

from .catalog import Catalog
from .calculations import sum_products
from .deep_models import configured_model, error_data
from .model_invocation import is_model_timeout
from .errors import ActionRejected, ActionForbidden
from .store import digest, encode
from .workspace import OWNERS, Workspace
from .knowledge_state import project_state, delivery_state, inspect_evidence
from .review import load_rules, native_review, reconcile_review, reviewer_prompt
from .acceptance import AcceptanceCriterionInput
from .evidence_analysis import SourceSelection, ResultSelection, analyze_selected_evidence
from .content_models import Ref
from .content_selection import ContentSelection
from .tool_argument_feedback import InvalidToolFeedback


# Historical direct-test entry points use the same current files; no inline fallback.
from .hierarchical_tools import role_prompt
COORDINATOR = role_prompt('coordinator')
ACCEPTANCE_GUIDANCE = ''


def repeated_observation(messages):
    """Recognize identical observed exchanges, not semantic lack of progress."""
    tail = messages[-6:]
    if len(tail) != 6:
        return None
    exchanges = []
    for action, observation in zip(tail[::2], tail[1::2]):
        if (not isinstance(action, AIMessage) or len(action.tool_calls) != 1
                or not isinstance(observation, ToolMessage) or observation.status != "success"):
            return None
        call = action.tool_calls[0]
        if observation.tool_call_id != call["id"]:
            return None
        value = observation.content
        if call['name'] in {'read_context', 'read_content_export', 'observe_evidence'}:
            try:
                parsed = json.loads(value)
            except (TypeError, ValueError):
                parsed = None
            if isinstance(parsed, dict) and parsed.get('ok') is True and 'receipt_id' in parsed:
                value = encode({k: v for k, v in parsed.items() if k != 'receipt_id'})
        exchanges.append({"tool": call["name"], "args": call["args"],
                          "observation": value})
    return exchanges[-1]["tool"] if exchanges[0] == exchanges[1] == exchanges[2] else None


class _ManagedSummarySlot(AgentMiddleware):
    # Deep Agents replaces this named slot per graph. WorkingSummary keeps its
    # separate checkpoint node; other graphs in this process keep their native summary.
    name = "SummarizationMiddleware"


class BusinessBoundary(InvalidToolFeedback):
    """Serialize native tools and report rejected actions as observations."""

    def __init__(self, workspace, role, decision_only=False, *, subagent_descriptions=(), indicator_step=False):
        self.indicator_step = indicator_step
        self.workspace, self.role = workspace, role
        self.decision_only = decision_only
        self.subagent_descriptions = subagent_descriptions
        self.lock = asyncio.Lock()
        from .repetition_guard import KnownWriteRepetition
        self.write_repetition = KnownWriteRepetition(workspace, role)
        self.planning_before = {}
        self.export_before = {}

    @hook_config(can_jump_to=['model'])
    async def aafter_model(self, state, runtime):
        from .planning_guard import record_planning_result
        latest = next((m for m in reversed(state['messages']) if isinstance(m, AIMessage)), None)
        if latest:
            for call in latest.invalid_tool_calls:
                record_planning_result(self.workspace, self.role, call.get('name'), call.get('id'),
                                       rejected=True, error_code='INVALID_TOOL_ARGUMENT_JSON')
                from .delivery_guard import record_export_result
                record_export_result(self.workspace, self.role, call.get('name'), call.get('id'),
                                     rejected=True, error_code='INVALID_TOOL_ARGUMENT_JSON')
        return await super().aafter_model(state, runtime)

    async def awrap_model_call(self, request, handler):
        from .prompt_provenance import append_declared_system
        from .tool_argument_feedback import diagnostic_messages
        request = request.override(messages=diagnostic_messages(request.messages))
        from .section_writing import enabled as system_writing
        if not self.indicator_step and system_writing(self.workspace.store) and self.role in {'coordinator', 'writer'}:
            request = append_declared_system(request,
                'This run uses system-assembler-v1. Writers save assigned section prose and current citations, '
                'calculate canonical assessments, and propose material issues for their nodes. The system owns '
                'fixed text, tables, chapter 5, relationships, snapshots and comment anchors. The coordinator '
                'requests system delivery from saved inputs. Do not manually reconstruct those system objects. '
                'A successful export is a draft, not engineering sign-off. Missing engineering judgments remain explicit.',
                'system_assembler/writing_boundary')
        from .hierarchical_tools import enabled as content_enabled
        if self.role == "coordinator" and content_enabled(self.workspace):
            from .content_tasks import task_tool
            from .prompt_sources import review_profile, review_interface_profile, report_prompt_profile
            request = request.override(tools=[task_tool(t, review_profile=review_profile(self.workspace.store),
                interface_profile=review_interface_profile(self.workspace.store),
                prompt_profile=report_prompt_profile(self.workspace.store),
                subagent_descriptions=self.subagent_descriptions)
                if getattr(t, "name", None) == "task" else t for t in request.tools])
            from .content_store import ContentStore
            from .task_supervision import task_status
            from .task_context import enabled as managed_context_enabled
            status = ({"tasks": [], "total": 0} if managed_context_enabled(self.workspace)
                      else task_status(ContentStore(self.workspace.store)))
            status = {**status, "tasks": [t for t in status["tasks"] if t["supervision_plugin"] is not None]}
            status["total"] = len(status["tasks"])
            if status["total"] and not managed_context_enabled(self.workspace):
                compact = {**status, "tasks": [{"task_id": t["task_id"], "snapshot_ref": t["snapshot_ref"],
                    "execution_complete": t["execution_complete"], "followup": t["followup"],
                    "remaining": [{"target_ref": r["requirement"]["target_ref"], "scope_id": r["requirement"]["scope_id"],
                                   "state": r["state"], "reason": r["reason"]} for r in t["remaining"]]} for t in status["tasks"]]}
                notice = encode({"task_supervision": compact})
                request = append_declared_system(request, notice, "task_supervision/current_state")
        from .acceptance import enabled, active_criteria, criteria_identity
        from .hierarchical_tools import enabled as content_enabled
        if enabled(self.workspace) and not content_enabled(self.workspace) and self.role in {"writer", "coordinator"}:
            criteria = active_criteria(self.workspace)
            if criteria:
                notice = ("Shared acceptance standards available before report production. "
                          "Explicitly adopt this criteria_id when saving; request corrections if needed. "
                          "These define required outcomes, not a prescribed investigation.\n"
                          + encode({"acceptance_identity": criteria_identity(criteria),
                                    "criteria": criteria["criteria"],
                                    "current": criteria["current"]}))
            else:
                notice = "Acceptance standards are not yet saved. The coordinator must define them from the commission before report production."
            request = append_declared_system(request, notice, 'acceptance/current_criteria')
        from .task_state_delivery import business_messages
        business = business_messages(self.workspace.store, request.messages)
        tool = repeated_observation(business)
        if tool and not (self.workspace.store.manifest.get('execution_progress_policy') is not None
                and tool in {'read_tool_observation','read_content_index'}):
            notice = encode({"execution_observation": {
                "tool": tool, "identical_successful_exchanges": 3,
                "semantic_progress_assessed": False}})
            self.workspace.store.event("deep_repetition_observed", {"role": self.role, "tool": tool})
            request = append_declared_system(request, notice, 'repetition/actual_observation')
        prepared = self.write_repetition.prepare(business, tool)
        if prepared is not None:
            request = append_declared_system(request, encode({'known_write_repetition': {'observed_call_ids': prepared['observed_call_ids'],
                    'operation_id': prepared['proof']['operation_id'], 'receipt_state': 'known_success'}}),
                'repetition/known_write_state')
        from .live_messages import prepare_request, model_offer, bind_response
        request, offer = prepare_request(self.workspace, self.role, request)
        with model_offer(offer):
            response = await handler(request)
        bind_response(self.workspace, offer, response)
        self.write_repetition.after_model(prepared, response)
        return response

    async def awrap_tool_call(self, request, handler):
        from .tool_selection import reject_unoffered
        rejected = reject_unoffered(self.workspace, self.role, request)
        if rejected is not None:
            return self._record_tool_result(request, rejected)
        from .live_messages import tool_binding
        try:
            with tool_binding(self.workspace, self.role, request) as bound_request:
                result = await self._awrap_bound_tool_call(bound_request, handler)
            return self._record_tool_result(request, result)
        except ActionRejected as exc:
            from .errors import LocalStorageBusy
            if isinstance(exc, LocalStorageBusy):
                return self._record_tool_result(request, ToolMessage(encode({'ok': False, 'code': 'LOCAL_STORAGE_BUSY',
                    'message': str(exc), 'retryable': bool((exc.diagnostic or {}).get('retryable')),
                    'diagnostic': exc.diagnostic}), tool_call_id=request.tool_call['id'],
                    name=request.tool_call['name'], status='error'))
            if legacy_state.get_decision_observation(self.workspace.store):
                raise
            return self._record_tool_result(request, ToolMessage(encode({'ok': False, 'code': str(exc).split(':')[0],
                'message': str(exc), 'retryable': bool((exc.diagnostic or {}).get('retryable')),
                **({'diagnostic': exc.diagnostic} if exc.diagnostic is not None else {})}), tool_call_id=request.tool_call['id'],
                name=request.tool_call['name'], status='error'))

    def _record_tool_result(self, request, result):
        from .runtime_metrics import emit
        messages = result.update.get('messages', []) if isinstance(result, Command) and isinstance(result.update, dict) else [result]
        if any(isinstance(message, ToolMessage) and message.status == 'error' for message in messages):
            emit(self.workspace.store.root, 'tool_rejected', {'role': self.role,
                'tool_call_id': request.tool_call['id']})
        from .planning_guard import record_planning_result, fingerprint, TOOLS
        call = request.tool_call
        if self.role == 'coordinator' and call['name'] in TOOLS:
            before = self.planning_before.pop(call['id'], None)
            record_planning_result(self.workspace, self.role, call['name'], call['id'],
                rejected=any(isinstance(m, ToolMessage) and m.status == 'error' for m in messages),
                error_code='PLANNING_TOOL_REJECTED', changed=before is not None and before != fingerprint(self.workspace))
        from .delivery_guard import record_export_result, TOOLS as EXPORT_TOOLS
        if call['name'] in EXPORT_TOOLS and self.export_before.get(call['id']) is not None:
            before = self.export_before.pop(call['id'], None)
            with self.workspace.store.connect() as db:
                after = db.execute("SELECT count(*) FROM content_versions WHERE type='ExportArtifact'").fetchone()[0]
            record_export_result(self.workspace, self.role, call['name'], call['id'],
                rejected=any(isinstance(m, ToolMessage) and m.status == 'error' for m in messages),
                error_code='EXPORT_TOOL_REJECTED', changed=before is not None and after > before)
        return result

    async def _awrap_bound_tool_call(self, request, handler):
        async with self.lock:
            call = request.tool_call
            from .delivery_guard import require_resumed as require_delivery_resumed, enabled as delivery_enabled, TOOLS as EXPORT_TOOLS
            require_delivery_resumed(self.workspace)
            if delivery_enabled(self.workspace.store) and call['name'] in EXPORT_TOOLS:
                with self.workspace.store.connect() as db:
                    self.export_before[call['id']] = db.execute("SELECT count(*) FROM content_versions WHERE type='ExportArtifact'").fetchone()[0]
            if self.role == 'coordinator':
                from .planning_guard import require_resumed
                require_resumed(self.workspace)
            from .planning_guard import TOOLS, fingerprint
            from .commission_planning import enabled as planning_enabled
            if self.role == 'coordinator' and call['name'] in TOOLS and planning_enabled(self.workspace.store):
                self.planning_before[call['id']] = fingerprint(self.workspace)
            store = self.workspace.store
            if legacy_state.get_decision_observation(store):
                raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
            if self.decision_only and call["name"] in {
                    "process_report_content", "perform_assigned_review", "perform_assigned_artifact_review",
                    "analyze_text", "analyze_evidence", "analyze_source_image", "inspect_rendered_page"}:
                observed = {"kind": "unexecuted_text_work_intent", "role": self.role,
                            "tool_call": call, "executed": False,
                            "text_output_or_correctness_verified": False}
                legacy_state.set_decision_observation(store, observed)
                interrupt(observed)
                # Observation runs are terminal measurements, never deferred paid work.
                raise ActionRejected("DECISION_OBSERVATION_CANNOT_DISPATCH_OR_RESUME_TEXT_WORK")
            # Calls and returned observations live in native checkpoint writes.
            # Keep only a current activity indicator, not a duplicate transcript.
            store.set("report_activity", self.role)
            runtime = getattr(request, "runtime", None)
            thread_id = runtime.config.get("configurable", {}).get("thread_id") if runtime else None
            if thread_id:
                store.set("native_trace_thread_id", thread_id)
            self.write_repetition.intercept(call, runtime.state.get("messages", []) if runtime else [])
            pending_updates = {}
            try:
                from .tool_transport import decode_object_arguments
                # Use the actual public call schema; injected ToolRuntime is not
                # model input and is intentionally absent from this schema.
                public_schema = request.tool.tool_call_schema if request.tool else {}
                schema = public_schema if isinstance(public_schema, dict) else public_schema.model_json_schema()
                decoded, fields = decode_object_arguments(call["args"], schema)
                if fields:
                    call = {**call, "args": decoded}
                    request = request.override(tool_call=call)
                    store.event("deep_tool_argument_decoded", {"role": self.role, "tool": call["name"],
                        "tool_call_id": call["id"], "fields": fields, "codec": "strict-json-object-v1"})
                from .review_work_units import require_before_verification, prepare_native_todos, retain_native_todos
                review_todos = prepare_native_todos(self.workspace, self.role, call, runtime.state if runtime else {})
                require_before_verification(self.workspace, self.role, call, runtime.state if runtime else {})
                from .prompt_sources import review_interface_profile
                if (call['name'] == 'export_content_snapshot'
                        and review_interface_profile(store) == 'review-interfaces-v4'):
                    # Old callers may still send operation_id; native identity overrides it below.
                    extra = sorted(set(call['args']) - set(schema.get('properties', {})) - {'operation_id'})
                    if extra:
                        field = extra[0]
                        raise ActionRejected('NATIVE_TOOL_VALIDATION_ERROR', diagnostic={
                            'reason': 'unsupported_export_parameter', 'parameter_path': [field],
                            'allowed_parameters': sorted(schema.get('properties', {})),
                            **({'correct_parameter_path': ['layout', 'refresh_toc']}
                               if field in {'refresh_toc', 'refresh_toc_default'} else {})})
                    if call['args'].get('snapshot_ref') is None and call['args'].get('deliverable') is None:
                        raise ActionRejected('NATIVE_TOOL_VALIDATION_ERROR', diagnostic={
                            'reason': 'missing_export_selector', 'parameter_path': [],
                            'required_one_of': ['snapshot_ref', 'deliverable']})
                from .operation_identity import NATIVE_WRITES, NATIVE, effective_call, profile
                if call['name'] in NATIVE_WRITES and profile(store) == NATIVE:
                    from .text_work import actor_for_tool
                    call = effective_call(store, call, actor_for_tool(self.workspace, self.role).id)
                if call["name"] == "task" and call["args"].get("subagent_type") == "writer":
                    from .acceptance import enabled, required_criteria
                    from .hierarchical_tools import enabled as content_enabled
                    if enabled(self.workspace) and not content_enabled(self.workspace):
                        required_criteria(self.workspace)
                if call["name"] == "search_sources" and set(call["args"]) - set(request.tool.args):
                    raise ActionRejected("SEARCH_ARGUMENTS_MUST_BE_QUERY_OFFSET_LIMIT_SOURCE_ID_TABLE_DETAIL")
                from .hierarchical_tools import enabled as content_enabled
                if call["name"] == "task" and content_enabled(self.workspace):
                    if self.role == "coordinator":
                        if request.tool is None:
                            # Native ToolNode owns unregistered-tool feedback;
                            # do not create business task state before it runs.
                            return await handler(request)
                        from .content_tasks import task_tool
                        from pydantic import ValidationError
                        from langgraph.prebuilt.tool_node import ToolInvocationError
                        from .tool_argument_feedback import compact_native_tool_error
                        # The delegation guard reads business state before the native
                        # handler. Validate against the same public schema first;
                        # retain the original arguments and unset/default fields.
                        from .prompt_sources import review_profile, review_interface_profile, report_prompt_profile, REVIEW_INTERFACE_V2, REVIEW_INTERFACE_V3
                        interface = review_interface_profile(store)
                        schema = task_tool(request.tool, review_profile=review_profile(store), interface_profile=interface,
                            prompt_profile=report_prompt_profile(store)).tool_call_schema
                        try:
                            # The current flat message was validated before resource assembly.
                            if interface != 'review-interfaces-v4':
                                schema.model_validate(call["args"])
                        except ValidationError as exc:
                            error = ToolInvocationError(call["name"], exc, call["args"])
                            message = ToolMessage(error.message, tool_call_id=call["id"],
                                                  name=call["name"], status="error")
                            native = compact_native_tool_error(message, store, args=call["args"], schema=schema)
                            requirements = call["args"].get("review_requirements")
                            schema_errors = exc.errors(include_input=False, include_context=False,
                                                       include_url=False)
                            if (isinstance(requirements, list) and any(
                                    e["loc"] and e["loc"][0] == "review_requirements"
                                    for e in schema_errors)):
                                from .content_tasks import normalize_review_requirements
                                try:
                                    normalize_review_requirements(requirements)
                                except ValidationError as domain:
                                    from .task_supervision import review_contract_issues
                                    detail = "INVALID_REVIEW_REQUIREMENTS: " + str(domain)
                                    return ToolMessage(encode({
                                        "accepted": False, "ok": False,
                                        "code": "INVALID_REVIEW_REQUIREMENTS",
                                        "message": detail,
                                        "error": error_data(ActionRejected(detail)),
                                        "retryable": False,
                                        "receipt_id": call["args"].get("operation_id"),
                                        "domain_validation_errors": domain.errors(
                                            include_input=False, include_context=False, include_url=False),
                                        **({'review_contract_issues': review_contract_issues(requirements)}
                                           if interface in {REVIEW_INTERFACE_V2, REVIEW_INTERFACE_V3} else {}),
                                        "native_validation": json.loads(native.content),
                                        "native_schema_errors": schema_errors}),
                                        tool_call_id=call["id"], name=call["name"], status="error")
                            return native
                    from .content_tasks import delegated_task, invocation_binding
                    from .content_store import ContentStore
                    from .task_supervision import batch_needs_review_decision, task_status
                    from .supervision_plugins import delegated_return
                    role = call["args"].get("subagent_type")
                    from .handoff_release import manifest as bound_manifest
                    entrypoint = bound_manifest(store).get('review_entrypoint')
                    messages = runtime.state.get("messages", []) if runtime else []
                    if batch_needs_review_decision(messages, call):
                        raise ActionRejected("REVIEW_RESULT_DECISION_REQUIRED: Request dependent layout in a later model turn after examining the review return.")
                    if (role == "reviewer" and not call["args"].get("resume_content_task_id")
                            and entrypoint != "native-rubric-v1"
                            and not call["args"].get('review' if interface == 'review-interfaces-v4' else 'review_requirements')):
                        if interface == 'review-interfaces-v4':
                            raise ActionRejected('REVIEW_SELECTION_REQUIRED: choose deliverable, standards and scope in review')
                        raise ActionRejected("REVIEW_REQUIREMENTS_REQUIRED: Specify the exact assigned checks and snapshot; a free-text goal cannot be reconciled.")
                    contents = ContentStore(store)
                    if (role == "reviewer" and call["args"].get("resume_content_task_id")
                            and entrypoint != "native-rubric-v1"):
                        from .task_supervision import assignment
                        prior_assignment = assignment(contents, call["args"]["resume_content_task_id"])
                        if not prior_assignment.get("review_requirements"):
                            raise ActionRejected("REVIEW_ASSIGNMENT_UPGRADE_REQUIRED: Retain this historical task; create a new explicit review assignment instead of silently changing its scope.")
                    if role == "layout":
                        snapshot = call["args"].get("layout_snapshot_ref")
                        offset = 0
                        while True:
                            page = task_status(contents, offset)
                            if any(t["supervision_plugin"] is not None and t["snapshot_ref"] == snapshot and t["remaining"] for t in page["tasks"]):
                                raise ActionRejected("REVIEW_WORK_INCOMPLETE: Saved required checks remain incomplete. Read task supervision and retain the reasons; do not treat partial checks as content stability.")
                            if page["next_offset"] is None:
                                break
                            offset = page["next_offset"]
                    with delegated_task(self.workspace, self.role, call) as (native_call, actor):
                        native_invocations = 0
                        async def invoke_native(next_call):
                            nonlocal native_invocations
                            from dataclasses import replace
                            next_request = request.override(tool_call=next_call)
                            # Native wrappers allow multiple handler invocations,
                            # but each starts from its supplied state. Carry forward
                            # returned channels (not conversation messages) before
                            # a completion follow-up; preserve file/working state.
                            if pending_updates and runtime:
                                state = {**runtime.state, **{k: v for k, v in pending_updates.items() if k != "messages"}}
                                next_request = replace(next_request, state=state,
                                                       runtime=replace(runtime, state=state))
                            native_invocations += 1
                            with invocation_binding(self.workspace, actor, next_call):
                                returned = await handler(next_request)
                            if isinstance(returned, Command) and isinstance(returned.update, dict):
                                pending_updates.update(returned.update)
                                return Command(graph=returned.graph, goto=returned.goto, resume=returned.resume,
                                               update=dict(pending_updates))
                            return returned
                        result = await delegated_return(contents, actor, native_call, invoke_native, runtime=runtime)
                        from .prompt_sources import review_interface_profile, REVIEW_INTERFACE_V3
                        if actor.role == 'writer' and review_interface_profile(store) in {REVIEW_INTERFACE_V3, 'review-interfaces-v4'}:
                            from .content_tasks import attach_saved_reference_metadata
                            from .hierarchical_tools import actor_for
                            result = attach_saved_reference_metadata(contents, actor_for('coordinator'),
                                {'type':'DelegatedTask', 'id':actor.task_id, 'version':1}, result, call['id'])
                        returned_event = {"task_id": actor.task_id, "role": actor.role,
                            "native_invocations": native_invocations, "reused_without_invocation": native_invocations == 0}
                        if review_interface_profile(store) == 'review-interfaces-v4':
                            from .transport_observation import observe_safely
                            observe_safely(lambda: store.event('content_delegation_returned', returned_event))
                        else:
                            store.event('content_delegation_returned', returned_event)
                elif call["name"] == "process_report_content":
                    from .text_work_interrupts import admitted_call
                    call = effective_call(store, call)
                    result = await admitted_call(self.workspace, self.role, call, lambda: handler(request))
                elif call["name"] in {"analyze_source_image", "inspect_rendered_page"}:
                    from .vision_admission import admitted_call
                    from .hierarchical_tools import enabled as content_enabled
                    result = (await admitted_call(self.workspace, self.role, call, lambda: handler(request))
                              if content_enabled(self.workspace) else await handler(request))
                else:
                    result = await handler(request)
                result = retain_native_todos(result, review_todos)
            except (ActionRejected, ActionForbidden) as exc:
                from .errors import LocalStorageBusy
                if isinstance(exc, LocalStorageBusy):
                    # Error delivery must not itself require another DB write.
                    return ToolMessage(encode({'ok': False, 'code': 'LOCAL_STORAGE_BUSY',
                        'message': str(exc), 'retryable': bool((exc.diagnostic or {}).get('retryable')),
                        'diagnostic': exc.diagnostic, 'receipt_id': call['args'].get('operation_id')}),
                        tool_call_id=call['id'], name=call['name'], status='error')
                from .hierarchical_tools import enabled as content_enabled
                error = {"accepted": False, "error": error_data(exc)}
                if content_enabled(self.workspace):
                    error.update(ok=False, code="FORBIDDEN" if isinstance(exc, ActionForbidden) else str(exc).split(":")[0],
                                 message=str(exc), retryable=bool(getattr(exc, 'diagnostic', None) and exc.diagnostic.get('retryable')), receipt_id=call["args"].get("operation_id"))
                if isinstance(exc, ActionRejected) and exc.diagnostic is not None:
                    error["diagnostic"] = exc.diagnostic
                result = ToolMessage(encode(error),
                                     tool_call_id=call["id"], name=call["name"], status="error")
            except Exception as exc:
                from .hierarchical_tools import enabled as content_enabled
                from .input_capacity import capacity_failure, capacity_handling
                from .model_recovery import load_recovery_policy, transient
                capacity = capacity_failure(exc)
                technical = is_model_timeout(exc) or transient(exc)
                if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError)):
                    raise
                if capacity is None and not (technical or isinstance(exc, (httpx.HTTPError, openai.APIError))):
                    raise
                if call["name"] != "task" or not (content_enabled(self.workspace)
                        or (technical and load_recovery_policy(store))):
                    raise
                error = {"ok": False, "code": "DELEGATED_CAPACITY_BLOCKED" if capacity else "DELEGATED_EXECUTION_FAILED", "error": error_data(exc),
                         "message": "Delegated execution failed. Saved work and operation receipts remain available; decide the next action from actual state."}
                if capacity is not None:
                    error.update(capacity=capacity, handling=capacity_handling(capacity, 'delegated_agent'),
                                 retryable=False, completed=False)
                result = ToolMessage(encode(error), tool_call_id=call["id"], name=call["name"], status="error")
                if pending_updates:
                    result = Command(update={**pending_updates, "messages": [result]})
                store.event("content_delegation_failed", {"tool_call_id": call["id"], **error_data(exc)})
            from .tool_argument_feedback import compact_native_tool_error
            self.write_repetition.observe(call, result, runtime.state.get("messages", []) if runtime else [])
            return compact_native_tool_error(result, store, args=request.tool_call["args"],
                                             schema=request.tool.tool_call_schema if request.tool else None)


def result_view(result):
    return {key: value for key, value in result.items() if key != "task_id"}


def project_view(workspace):
    state = project_state(workspace)
    state["presentation_references"] = workspace.store.manifest.get("presentation_references", [])
    if workspace.store.manifest.get('commission_checkpoint_required'):
        state['commission_source_roles'] = legacy_state.get_commission_source_roles(workspace.store, {})
        state['commission_checkpoint'] = {'plan_ref': legacy_state.get_commission_plan(workspace.store),
            'confirmation_ref': legacy_state.get_commission_confirmation(workspace.store),
            'writing_requires_current_owner_confirmation': True}
    # Submission bookkeeping is not an agent plan or a saved report.
    state.pop("tasks", None)
    state["impact"] = {key: value for key, value in state["impact"].items()
                       if "task" not in key}
    state["results"] = [{k: v for k, v in result_view(r).items() if k != "body"} for r in state["results"]]
    from .acceptance import enabled, active_criteria
    if enabled(workspace):
        state["acceptance_standards"] = active_criteria(workspace)
    from .hierarchical_tools import enabled as content_enabled
    if content_enabled(workspace):
        state["content_contract"] = "hierarchical-review-v1"
        state["content_delivery"] = legacy_state.get_content_delivery(workspace.store)
        state["content_final_review"] = legacy_state.get_content_final_review(workspace.store)
    return state


def business_tools(workspace: Workspace, role: str, knowledge, text_model, *, reviewer_handles=False):
    if reviewer_handles and role != 'reviewer':
        raise ActionForbidden('REVIEW_MESSAGE_TASK_BINDING_REQUIRED')
    from .content_tasks import qualitative_review_active
    if role == 'reviewer' and qualitative_review_active():
        from .hierarchical_tools import content_tools
        return content_tools(workspace, role, reviewer_handles=reviewer_handles)
    store, catalog = workspace.store, Catalog(workspace.store)
    allowed_kinds = {"purpose", "plan"} if role == "knowledge" else {"review"} if role == "reviewer" else {"draft"}

    from .source_use import check_source_read

    def source_consumer_actor():
        from .hierarchical_tools import enabled as content_enabled
        from .text_work import actor_for_tool
        # Retained non-hierarchical read-only helpers never had delegated actors.
        # A configured policy without an actual actor still fails closed below.
        return actor_for_tool(workspace, role) if content_enabled(workspace) else None

    def observations(runtime, result_id=None):
        # Native checkpoint namespaces distinguish separate delegated contexts.
        namespace = runtime.config.get("configurable", {}).get("checkpoint_ns", "") if runtime else "direct"
        # A ToolRuntime namespace ends with the current tool node, which changes
        # between reads and submissions. Its parent is the delegated graph scope.
        namespace = namespace.rpartition("|")[0] if runtime else namespace
        key = "observations:" + digest({"role": role, "namespace": namespace})
        seen = store.get(key, [])
        if result_id is not None and result_id not in seen:
            seen.append(result_id)
            store.set(key, seen)
        return seen

    def project_status() -> dict:
        """Observe project goal, source catalog, saved results, issues and feedback."""
        return project_view(workspace)

    def read_source_page(source_id: str,
            offset: Annotated[int, Field(ge=0, strict=True, description="Zero-based frozen text-block offset, not a physical or printed PDF page number.")] = 0,
            limit: Annotated[int, Field(ge=1, le=50, strict=True, description="Number of frozen text blocks, from 1 to 50; not characters or PDF pages.")] = 10,
            table_detail: Literal['references', 'full'] | None = None,
            runtime: ToolRuntime = None) -> dict:
        """Read frozen text blocks at a zero-based block offset. next_offset is the
        next block offset in the source result, not a character or PDF-page cursor.
        Blocks and physical pages are not interchangeable: use each returned locator.
        inspect_source_page accepts a 1-based physical PDF page instead.
        Selected frozen block text is preserved, not silently cropped by field name.
        The platform may defer tool-return bodies. Follow the supplied recovery
        reference/path; when observation_ref is supplied, read_tool_observation
        recovers that actor-owned original. Recovery does not expand access.
        next_offset=None covers source-block pagination only, not complete reading
        of the saved observation or its deferred content.

        source_table_views adds mechanical PDF table rows for the returned physical
        pages when available. These separate whole-page supplements may be incomplete;
        they do not replace the original text, perform OCR or verify column meanings.
        table_detail='references' retains all selected frozen text and defers table
        extraction with exact inspect_source_page access. Unexpanded is not absent.
        Omitted/full preserves historical full supplements, independent of search
        defaults. Switching views does not authorize retrying unknown paid work.
        """
        from .source_tables import present_source_tables
        from .source_materials import returned, block_material
        check_source_read(workspace, source_consumer_actor, [source_id])
        value = present_source_tables(workspace, catalog.read(source_id, offset, limit), table_detail)
        return returned(workspace,role,'read_source_page',value,block_material(value),runtime, reviewer_handles=reviewer_handles)

    def search_sources(query: str, offset: int = 0, limit: int = 10,
                       source_id: str | None = None,
                       table_detail: Literal["references", "full"] | None = None,
                       runtime: ToolRuntime = None) -> dict:
        """Search current source text literally, optionally within one exact source ID.

        Returns actual searched source IDs, located matches and next_offset. Omit
        source_id to search all current sources. No match is not proof of absence;
        read_source_page can read a specific historical version when needed.
        table_detail='full' adds the original unverified whole-page mechanical table
        views; 'references' defers those views with explicit inspect_source_page access.
        Omit it to use this project's bound default (full unless configured otherwise).
        Deferral does not mean tables/information are absent. Matched frozen text and
        pagination are unchanged. No new OCR or semantic interpretation.
        """
        from .source_search import search_observation
        from .source_materials import returned
        allowed = check_source_read(workspace, source_consumer_actor, None if source_id is None else [source_id])
        hits = catalog.search(query, offset, limit, source_id=source_id, allowed_source_ids=allowed)
        value = search_observation(workspace, hits, table_detail)
        materials = [{'source_id':m['source_id'],'kind':'literal_source_search_match',
            'selection':{'units':'zero-based text blocks','ordinals':m.get('ordinals',[m['ordinal']]),
                         'locators':m.get('locators',[m['locator']])},
            'selected_value_digest':digest(m),'coverage':{'complete_source':False},
            'limitations':['Literal returned matches only; searched scope is not read coverage.']}
            for m in value['matches']]
        return returned(workspace,role,'search_sources',value,materials,runtime, reviewer_handles=reviewer_handles)

    def calculate(terms: list[list[str]], runtime: ToolRuntime = None) -> dict:
        """Add the products of decimal factors: [["50","0.03"],["-0.2"]] gives 1.30.

        Returns every product and total. You choose inputs, signs, units and the applicable
        rule; this tool does arithmetic only, not engineering judgments or report edits.
        """
        value = sum_products(terms)
        from .prompt_sources import native_reviewer
        if role == 'reviewer' and native_reviewer(store):
            from .content_store import ContentStore
            from .text_work import actor_for_tool
            return ContentStore(store).observe(actor_for_tool(workspace, role),
                {'tool':'calculate', 'terms':terms, 'result':value})
        return value

    def inspect_source_page(source_id: str, page: int, runtime: ToolRuntime = None) -> dict:
        """Inspect a 1-based physical PDF page, not a text-block offset or printed page label.

        Returns original-page text, frozen extraction, mechanical table rows and a
        source-page:// image reference usable in Markdown figures. Table geometry
        is unverified and may be incomplete. No new OCR or visual interpretation.
        """
        from .document_tools import source_page_info
        from .source_materials import returned
        check_source_read(workspace, source_consumer_actor, [source_id])
        value = source_page_info(workspace, source_id, page)
        has_text = (bool(value['native_text'].strip()) or bool(value['frozen_text_blocks'])
                    or any(t.get('rows') for t in value['table_view'].get('tables',[])))
        materials = [{'source_id':source_id,'kind':'source_page_text_and_mechanical_tables',
            'selection':{'units':'one-based physical PDF page','page':page},
            'selected_value_digest':digest(value), 'coverage':{'complete_source':False},
            'limitations':value['limitations']}] if has_text else []
        return returned(workspace,role,'inspect_source_page',value,materials,runtime, reviewer_handles=reviewer_handles)

    async def analyze_source_image(source_id: str, question: str, page: int = 1,
                                   crop: list[float] | None = None, runtime: ToolRuntime = None) -> dict:
        """Ask a visual model about a project PDF page or PNG/JPEG/WebP image, including OCR.

        page is a 1-based physical PDF page (1 for images). Optional crop is normalized
        [left, top, right, bottom] within that page/image. Ask what you need to observe;
        reuse existing extraction when suitable. Returns located, cached observations,
        not verified facts. Does not edit sources, existing OCR, shared knowledge or reports.
        """
        from .vision import observe_source_image
        from .hierarchical_tools import enabled as content_enabled
        from .text_work import actor_for_tool
        actor = actor_for_tool(workspace, role) if content_enabled(workspace) else None
        from .source_materials import returned
        value = await observe_source_image(workspace, source_id, question, page, crop, actor=actor)
        materials = [{'source_id':source_id,'kind':'model_image_interpretation',
            'selection':{'units':'one-based physical page with normalized crop','page':page,'crop':crop},
            'selected_value_digest':digest(value), 'coverage':{'complete_source':False,'response_status':value['status']},
            'limitations':value.get('limitations',[])}]
        if value.get('status') not in {'observed','incomplete'} or not value.get('observation','').strip():
            materials=[]
        return returned(workspace,role,'analyze_source_image',value,materials,runtime, reviewer_handles=reviewer_handles)

    def preview_report(draft_id: str, offset: int = 0, limit: int = 30,
                       preview_version: str = "", runtime: ToolRuntime = None) -> dict:
        """Export an exact saved draft and inspect its actual document structure and text.

        Omit preview_version to create a new export. Pass its returned preview_version
        on subsequent pages to inspect that exact snapshot without exporting again.
        Does not review, approve, select delivery or imply visual/engineering correctness.
        """
        from .report_preview import preview_saved_report, read_preview
        preview = None if preview_version else preview_saved_report(workspace, draft_id)
        version = preview_version or preview["preview_version"]
        content = read_preview(workspace, draft_id, offset, limit, preview_version=version)
        if content["text"]:
            observations(runtime, draft_id)
        return {"preview": preview, "content": content}

    def read_result(result_id: str, offset: int = 0, characters: int = 12000,
                    runtime: ToolRuntime = None) -> dict:
        """Read a saved result version; paginate until next_offset is null for full text.

        offset must be nonnegative; characters must be between 1 and 16000.
        """
        if offset < 0 or not 1 <= characters <= 16000:
            raise ActionRejected("INVALID_RESULT_PAGE")
        result = result_view(workspace.result(result_id))
        body = result.pop("body")
        if body[offset:offset + characters]:
            observations(runtime, result_id)
        evidence = inspect_evidence(workspace, [result_id], knowledge)
        return {**result, "body": body[offset:offset + characters],
                "next_offset": offset + characters if offset + characters < len(body) else None,
                "current": result_id not in workspace.impact()["affected_result_ids"] and evidence["status"] in {"not_used", "current"},
                "version_note": "Currentness describes version changes, not whether the content is correct or usable. "
                                "Assess actual relevance; historical review feedback may guide a new revision.",
                "knowledge": {k: v for k, v in evidence.items() if k != "facts"}}

    async def analyze_text(source_id: str, purpose: str, offset: int = 0, limit: int = 10,
                           runtime: ToolRuntime = None) -> dict:
        """Optional one-shot LLM analysis of a source page for a stated purpose, no delegation or writes."""
        result = await analyze_selected_evidence(workspace, text_model, purpose,
            [{"source_id": source_id, "offset": offset, "limit": limit}], [],
            actor=source_consumer_actor())
        page = result["evidence"][0]["observation"]
        value = {**result, "source_id": source_id, "offset": offset, "next_offset": page.get("next_offset")}
        from .source_use import resolve_source_use_binding
        if resolve_source_use_binding(workspace, source_consumer_actor()):
            from .source_materials import returned, analysis_materials
            return returned(workspace, role, 'analyze_text', value, analysis_materials(result), runtime)
        return value

    async def analyze_evidence(question: str, source_selections: list[SourceSelection],
                               result_selections: list[ResultSelection],
                               snapshot_ref: Ref | None = None,
                               content_selections: list[ContentSelection] | None = None,
                               runtime: ToolRuntime = None) -> dict:
        """Optional local LLM comparison of caller-selected project evidence, with bound versions.

        Choose a question and sources, legacy results, or exact ContentNode versions.
        For tree content supply snapshot_ref and content_selections: ref, unit=text/rows,
        offset and limit (characters up to 16000, table rows up to 100). Read the index
        to choose one or related nodes; no descendants are fetched automatically.
        Empty source/result lists are allowed. Source offsets count blocks, not PDF pages.
        Existing whole-page mechanical table supplements are identified separately.
        The question can have a false premise. One model call; no search, delegation,
        business-artifact writes or acceptance decision. Returns observations and limits.
        """
        content_owner = None
        from .prompt_sources import native_reviewer
        native_review_analysis = role == 'reviewer' and native_reviewer(store)
        if content_selections or native_review_analysis:
            from .content_store import ContentStore
            from .content_tasks import bound_actor
            from .hierarchical_tools import actor_for
            content_owner = bound_actor(workspace, role, actor_for(role))
        result = await analyze_selected_evidence(workspace, text_model, question,
                                                  source_selections, result_selections,
                                                  snapshot_ref, content_selections,
                                                  actor=source_consumer_actor())
        for selection in result["evidence"]:
            if selection["kind"] == "saved_result_text":
                observations(runtime, selection["result_id"])
        if content_selections or native_review_analysis:
            receipt = ContentStore(store).observe(content_owner, result)
            result = {**result, "receipt_id": receipt["receipt_id"]}
        from .source_use import resolve_source_use_binding
        if resolve_source_use_binding(workspace, source_consumer_actor()):
            from .source_materials import returned, analysis_materials
            return returned(workspace, role, 'analyze_evidence', result, analysis_materials(result), runtime, reviewer_handles=reviewer_handles)
        return result

    def submit_result(kind: Literal["purpose", "plan", "materials", "draft", "review"],
                      title: str, body: str, source_ids: list[str], input_ids: list[str],
                      outcome: str = "", target_id: str = "", replaces_id: str = "",
                      fact_ids: list[str] = [],
                      runtime: ToolRuntime = None) -> dict:
        """Save your own outcome with adopted sources/results. Review targets an exact draft.

        kind is an outcome tag, not a required stage. To revise, supply your own replaces_id.
        fact_ids are exact shared knowledge versions actually used, not search candidates.
        """
        if kind not in allowed_kinds:
            raise ActionForbidden("RESULT_OWNER_MISMATCH")
        submission_id = digest({"role": role, "kind": kind, "title": title, "body": body,
                                "sources": sorted(set(source_ids)), "inputs": sorted(set(input_ids)),
                                "facts": sorted(set(fact_ids)), "outcome": outcome,
                                "target": target_id, "replaces": replaces_id})
        receipt = workspace.submission_receipt(submission_id)
        if receipt is not None:
            return result_view(receipt)
        if kind == "draft":
            from .document_tools import markdown_source_ids
            source_ids = sorted(set(source_ids) | set(markdown_source_ids(body)))
        if replaces_id:
            # The explicit predecessor is editing history, not a live dependency.
            input_ids = [ref for ref in input_ids if ref != replaces_id]
        if kind == "review" and target_id and target_id not in input_ids:
            input_ids = [*input_ids, target_id]
        if fact_ids:
            if knowledge is None:
                raise ActionRejected("KNOWLEDGE_NOT_AVAILABLE")
            facts = knowledge.read_many(fact_ids)
            # Store immutable source references, not a second copy of graph facts.
            source_ids = sorted(set(source_ids) | {ref["source_id"] for fact in facts for ref in fact["provenance"]})
        actor = OWNERS[kind]
        if replaces_id:
            previous = workspace.result(replaces_id)
            if previous["owner"] != actor or previous["kind"] != kind:
                raise ActionForbidden("REPLACEMENT_OWNER_MISMATCH")
            task = workspace.request_revision(replaces_id, title + ": " + digest({"body": body, "facts": fact_ids,
                                                                                 "sources": source_ids, "inputs": input_ids}))
        else:
            task = workspace.request_task(kind, title + ": " + digest({"body": body, "sources": source_ids,
                                                                      "facts": fact_ids,
                                                                      "outcome": outcome, "target": target_id}), input_ids)
        workspace.record_read(task["id"], result_ids=observations(runtime))
        return result_view(workspace.submit(task["id"], actor=actor, title=title, body=body, source_ids=source_ids,
                                input_ids=input_ids, outcome=outcome, target_id=target_id, fact_ids=fact_ids,
                                submission_id=submission_id))

    def request_correction(result_id: str, description: str) -> dict:
        """Ask the responsible producer to correct an upstream result; does not change it."""
        return workspace.request_correction(result_id, description)

    def assess_result_impact(result_id: str, description: str) -> dict:
        """Judge whether your existing result remains usable after an adopted input changed."""
        result = workspace.result(result_id)
        if result["kind"] not in allowed_kinds:
            raise ActionForbidden("RESULT_OWNER_MISMATCH")
        return workspace.assess_result_impact(result_id, OWNERS[result["kind"]], description)

    def ask_human(category: Literal["source_missing", "source_conflict", "system_failure", "requirement"],
                  description: str, source_ids: list[str] = [], pause: bool = True) -> dict:
        """Record an unresolved issue for human handling; choose whether to pause.

        Set pause=False when supported work can continue with an explicit limitation.
        This does not resolve the issue or grant permission to guess an answer.
        With pause=True, wait at a native checkpoint for an operator response.
        """
        issue = workspace.issue(category, description, source_ids)
        if issue.get("decision_origin") == "operator":
            return issue
        if not pause:
            return {"issue": issue, "waiting_for_human": True, "execution_paused": False}
        answer = interrupt({"issue_id": issue["id"], "category": category, "description": description})
        # Only run_report can supply a resume answer, from a saved operator decision.
        return {"issue": issue, "human_decision": answer}

    def knowledge_search(query: str, mode: Literal["hybrid", "text", "vector"] = "hybrid",
                         limit: int = 10, offset: int = 0) -> dict:
        """Search shared indexed facts/summaries using semantic vectors, text or both."""
        return knowledge.search(query, mode=mode, limit=limit, offset=offset)

    def knowledge_read(fact_id: str) -> dict:
        """Read a shared fact version with sources, ownership and revision history."""
        return knowledge.read(fact_id)

    def knowledge_traverse(fact_id: str, depth: int = 1, limit: int = 20, offset: int = 0) -> dict:
        """Explore related shared facts through graph edges; paginated results are partial."""
        return knowledge.traverse(fact_id, depth=depth, limit=limit, offset=offset)

    def save_draft(title: str, body: str, source_ids: list[str], input_ids: list[str],
                   fact_ids: list[str] = [], replaces_id: str = "", kind: Literal["draft"] = "draft",
                   criteria_id: str = "",
                   runtime: ToolRuntime = None) -> dict:
        """Save a report draft, not an approval. Adopt exact source/result/fact IDs.

        Use full source IDs from the catalog. To revise your draft, supply replaces_id.
        Its historical base is retained there, not duplicated in input_ids.
        The complete draft belongs in body. In requirement-derived acceptance mode,
        criteria_id must be the exact shared standard version you used to produce it.
        Stale versions are rejected; review outcomes are a separate capability.
        """
        from .acceptance import enabled, required_criteria
        if enabled(workspace):
            if not criteria_id:
                raise ActionRejected("DRAFT_REQUIRES_ADOPTED_CRITERIA_ID")
            # Recover a previous identical save before checking today's standards.
            adopted = sorted(set(input_ids) | {criteria_id})
            receipt_id = digest({"role": role, "kind": kind, "title": title, "body": body,
                                 "sources": sorted(set(source_ids)), "inputs": adopted,
                                 "facts": sorted(set(fact_ids)), "outcome": "",
                                 "target": "", "replaces": replaces_id})
            receipt = workspace.submission_receipt(receipt_id)
            if receipt is not None:
                return result_view(receipt)
            required_criteria(workspace, criteria_id)
            input_ids = adopted
        return submit_result(kind, title, body, source_ids, input_ids, fact_ids=fact_ids,
                             replaces_id=replaces_id, runtime=runtime)

    def save_review(title: str, body: str, source_ids: list[str],
                    target_id: str, outcome: Literal["accepted", "changes_required"], input_ids: list[str] = [],
                    fact_ids: list[str] = [], replaces_id: str = "", kind: Literal["review"] = "review",
                    runtime: ToolRuntime = None) -> dict:
        """Save your review of the exact draft read in this context.

        target_id is a saved results[].id, not a task ID or scratch-file path.
        Its evidence link is saved automatically; input_ids lists other adopted results.
        If no saved draft exists, return this fact to the delegating agent.
        outcome is accepted or changes_required, never prose.
        Put assessment reasons and remaining issues in body. This is not engineering approval.
        """
        return submit_result(kind, title, body, source_ids, input_ids, outcome, target_id,
                             replaces_id, fact_ids, runtime)

    def save_knowledge_artifact(kind: Literal["purpose", "plan"], title: str, body: str,
                                source_ids: list[str], input_ids: list[str], fact_ids: list[str] = [],
                                replaces_id: str = "", runtime: ToolRuntime = None) -> dict:
        """Save an optional document-use interpretation or plan. Indexed evidence belongs in knowledge_put."""
        return submit_result(kind, title, body, source_ids, input_ids, fact_ids=fact_ids,
                             replaces_id=replaces_id, runtime=runtime)

    exposed_submit = save_knowledge_artifact if role == "knowledge" else save_review if role == "reviewer" else save_draft
    exposed_submit.__name__ = "submit_result"
    tools = [project_status, read_source_page, search_sources, inspect_source_page, analyze_source_image,
             calculate, preview_report, read_result, analyze_text,
             exposed_submit, request_correction, assess_result_impact, ask_human]
    if role == "reviewer":
        tools.append(analyze_evidence)
    if knowledge is not None:
        tools += [knowledge_search, knowledge_read, knowledge_traverse]
    if role == "knowledge" and knowledge is not None:
        def knowledge_put(title: str, body: str, source_ids: list[str], replaces_id: str = "") -> dict:
            """Publish source-grounded knowledge or revise your own fact; retain provenance."""
            store.sources(source_ids)
            return knowledge.put(title, body, source_ids, owner="knowledge", replaces_id=replaces_id)

        def knowledge_link(source_id: str, target_id: str, relation: str) -> dict:
            """Save a meaningful relationship between two indexed knowledge records."""
            return knowledge.link(source_id, target_id, relation, owner="knowledge")

        def knowledge_retract(fact_id: str, reason: str) -> dict:
            """Retract your own invalid knowledge without deleting its audit history."""
            return knowledge.retract(fact_id, owner="knowledge", reason=reason)
        tools += [knowledge_put, knowledge_link, knowledge_retract]
    if role == "coordinator":
        from .acceptance import enabled

        def save_acceptance_criteria(title: str, criteria: list[AcceptanceCriterionInput],
                                     source_ids: list[str], input_ids: list[str], reason: str,
                                     replaces_id: str = "") -> dict:
            """Publish or revise your requirement-derived standards before report production.

            State required outcomes, scope and allowable limits with requirement references.
            Code assigns IDs to new criteria; preserve IDs for the same criterion on revision.
            Give the reason and exact predecessor for a change. Do not weaken requirements
            to fit a draft. Writers/reviewers may request corrections, not overwrite standards.
            """
            from .acceptance import save_criteria
            items = [c.model_dump() if hasattr(c, "model_dump") else c for c in criteria]
            return save_criteria(workspace, actor="coordinator", title=title, criteria=items,
                                 source_ids=source_ids, input_ids=input_ids,
                                 reason=reason, replaces_id=replaces_id)

        def assess_source_change(change_id: str, description: str, affected_result_ids: list[str]) -> dict:
            """Judge relevance of an added source within project scope; does not schedule or rewrite work."""
            return workspace.assess_source_change(change_id, description, affected_result_ids)

        def select_delivery(draft_id: str, review_id: str = "") -> dict:
            """Select a saved draft for native rubric assessment; this does not approve it.

            review_id is optional historical review evidence, never a substitute for
            the native rubric verdict. Unresolved issues remain visible.
            """
            if enabled(workspace):
                from .acceptance import draft_criteria
                draft_criteria(workspace, workspace.result(draft_id))
            workspace.select_delivery(draft_id, review_id)
            return delivery_state(workspace, draft_id, review_id, knowledge)[0]
        tools += [select_delivery, assess_source_change]
        if enabled(workspace):
            tools.append(save_acceptance_criteria)
    from .hierarchical_tools import enabled as content_enabled, content_tools
    if content_enabled(workspace):
        # Read-only substantive interpretation of located source/body material is
        # an independent tool for every decision role, including Layout. Agents
        # need not copy full originals into analyze_text or their own histories.
        from .prompt_sources import native_reviewer
        if role in {'coordinator','writer','layout'} or (role == 'reviewer' and native_reviewer(store)):
            tools.append(analyze_evidence)
        # Reuse bounded original-source observations. Legacy writes and delivery
        # selection cannot bypass the versioned contract or reviewer ownership.
        allowed = {"project_status", "read_source_page", "search_sources", "inspect_source_page",
                   "analyze_source_image", "calculate", "read_result", "analyze_text", "analyze_evidence"}
        if role == "coordinator":
            allowed.add("ask_human")
        tools = [t for t in tools if t.__name__ in allowed]
        from .text_work import guarded_tools
        tools += guarded_tools(workspace, role, text_model, content_tools(workspace, role, reviewer_handles=reviewer_handles))
        from .commission_plan import enabled as commission_enabled
        if role == 'coordinator' and commission_enabled(store):
            def request_commission_confirmation() -> dict:
                """Publish the current scope/section brief and wait for its owner's exact confirmation.

                Use after saving the source-linked plan and inventory. No reply keeps
                writing blocked. Corrections require a revised plan and new confirmation;
                agent proposals and ordinary approval prose cannot authorize reductions.
                """
                from .commission_plan import request_checkpoint
                checkpoint = request_checkpoint(workspace)
                return ask_human('requirement', checkpoint['description'], checkpoint['source_ids'], pause=True)
            from .commission_planning import enabled as planning_enabled
            if planning_enabled(store):
                def submit_plan(operation_id: str) -> dict:
                    """Submit the saved planning items. Returns all remaining gaps, or publishes the complete brief and waits for owner confirmation. No report writing is authorized by submission alone."""
                    from .commission_planning import submit_plan as submit
                    from .content_store import ContentStore
                    from .text_work import actor_for_tool
                    submit(ContentStore(store), actor_for_tool(workspace, 'coordinator'), operation_id)
                    return request_commission_confirmation()
                def request_requirement_resolution(operation_id: str) -> dict:
                    """Ask the owner to resolve listed parsing ambiguities or unknown requirement classifications. This never approves the report plan."""
                    from .commission_planning import request_requirements_checkpoint
                    from .text_work import actor_for_tool
                    checkpoint = request_requirements_checkpoint(workspace, operation_id, actor_for_tool(workspace, 'coordinator'))
                    return ask_human('requirement', checkpoint['description'], checkpoint['source_ids'], pause=True)
                tools += [submit_plan, request_requirement_resolution]
            else:
                tools.append(request_commission_confirmation)
        if role == "reviewer" and not native_reviewer(store):
            from .bounded_review import review_tool
            tools = [t for t in tools if t.__name__ not in {
                "submit_review", "correct_own_review", "analyze_text", "analyze_evidence"}]
            tools.append(review_tool(workspace, text_model))
            from .artifact_review import bounded_artifact_review_tool
            tools.append(bounded_artifact_review_tool(workspace, text_model))
        from .native_operation_tools import native_write_tools
        tools = native_write_tools(workspace, role, tools)
        from .prompt_sources import review_interface_profile
        from .task_context import enabled as context_enabled
        if review_interface_profile(store) == 'review-interfaces-v4' and not context_enabled(workspace):
            from .decision_state import state_tool
            tools.append(state_tool(workspace, role))
    if reviewer_handles:
        from .content_store import ContentStore
        from .text_work import actor_for_tool
        from .review_handles import read_tools
        tools = read_tools(ContentStore(store), lambda: actor_for_tool(workspace, role), tools)
    if role == 'reviewer':
        from .hierarchical_tools import general_reviewer_tool
        return [general_reviewer_tool(tool) for tool in tools]
    return tools


def require_native_runtime(workspace):
    """Reject retired execution before locks, status changes or checkpoint setup."""
    from .hierarchical_tools import enabled
    if legacy_state.get_decision_observation(workspace.store):
        raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
    from .prompt_sources import delegation_profile, validate_review_interface_profile, validate_report_prompt_profile
    delegation_profile(workspace.store)
    validate_review_interface_profile(workspace.store.manifest)
    validate_report_prompt_profile(workspace.store.manifest)
    from .execution_progress import validate_policy
    validate_policy(workspace)
    if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
        raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")

    from .native_trace import inspect_checkpoint
    from .task_state_delivery import HISTORY_FORMAT_VERSION
    history = inspect_checkpoint(workspace.store.root)
    if history['found'] and history['history_format_version'] != HISTORY_FORMAT_VERSION:
        raise ActionRejected('HISTORY_FORMAT_REQUIRES_FRESH_RUN: redo on a fresh authorized run; view originals on their writing tag')


def build_agent(workspace, model_factory, checkpointer, knowledge=None, rules="", *, decision_only=False):
    require_native_runtime(workspace)
    manifest = workspace.store.manifest
    from .tool_selection import selection_mode, NativeToolSelection
    tool_selection_mode = selection_mode(manifest)
    from .operation_identity import validate_profile as operation_profile
    identity_profile = operation_profile(manifest)
    from .prompt_sources import validate_content_input_profile, validate_report_expression_profile, REPORT_EXPRESSION_V1
    input_profile = validate_content_input_profile(manifest)
    expression_profile = validate_report_expression_profile(manifest)
    from .prompt_sources import validate_report_prompt_profile, CONCISE_PROMPTS
    text_profile = validate_report_prompt_profile(manifest)
    from .review_work_units import bind_contract
    bind_contract(workspace, manifest)
    from .review_scope_selectors import bind_contract as bind_submission_contract
    submission_contract = bind_submission_contract(workspace, manifest)
    from .prompt_sources import record_runtime_version
    from .task_state_delivery import HISTORY_FORMAT_VERSION
    runtime_version_ref = record_runtime_version(workspace.store)
    from .prompt_sources import delegation_profile, SEPARATE_DESCRIPTION, validate_review_interface_profile
    prompt_profile = delegation_profile(workspace.store)
    interface_profile = validate_review_interface_profile(workspace.store.manifest)
    from .acceptance import enabled
    from .hierarchical_tools import enabled as content_enabled, role_prompt
    hierarchical = content_enabled(workspace)
    if not hierarchical or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
        raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
    acceptance = enabled(workspace) and not hierarchical
    native_enabled = bool(rules) or acceptance or hierarchical
    if workspace.store.get("knowledge_enabled", True) is False:
        knowledge = None
    from .task_context import enabled as context_enabled, bind_projection
    bind_projection(workspace, manifest=manifest)
    managed_context = hierarchical and context_enabled(workspace)
    register_harness_profile("openai", HarnessProfile(
        general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False)))
    backend = StateBackend()
    summary_service = model_factory("coordinator") if managed_context else None
    summary_options = {'prompt_profile': text_profile} if text_profile == CONCISE_PROMPTS else {}

    def middleware(role, subagent_descriptions=()):
        from .task_context import enabled as context_enabled, TaskContext
        from .working_summary import working_summary
        from .prompt_sources import native_reviewer
        from .prompt_provenance import AgentPromptBoundary, CurrentReviewPlan
        from .execution_progress import ExecutionProgress
        from .prompt_sources import validate_review_plan_contract
        from .review_work_units import ReviewPlanning
        todo = ReviewPlanning(workspace) if role == 'reviewer' and validate_review_plan_contract(manifest) else TodoListMiddleware()
        from .commission_planning import enabled as planning_enabled
        from .planning_guard import PlanningGuard
        from .delivery_guard import DeliveryGuard, enabled as delivery_enabled
        return [*([DeliveryGuard(workspace)] if delivery_enabled(workspace.store) else []),
                *([PlanningGuard(workspace)] if role == 'coordinator' and planning_enabled(workspace.store) else []),
                FilesystemMiddleware(backend=backend, tools=["ls", "read_file", "write_file", "edit_file", "glob", "grep"]),
                *([todo, CurrentReviewPlan(workspace)] if role == 'reviewer' and native_reviewer(workspace.store) else
                  [TodoListMiddleware()] if role == 'coordinator' else []),
                *([TaskContext(workspace, role)] if hierarchical and context_enabled(workspace) else []),
                *([ExecutionProgress(workspace,role)]
                    if workspace.store.manifest.get('execution_progress_policy') is not None else []),
                # Use the already selected coordinator service for summaries.
                # Writer GLM-5.3 has forced thinking; its authored calls remain unchanged.
                *([_ManagedSummarySlot(), working_summary(summary_service,workspace.store,role,**summary_options)] if managed_context else []),
                BusinessBoundary(workspace, role, decision_only, subagent_descriptions=subagent_descriptions),
                *([NativeToolSelection(workspace, role)] if tool_selection_mode == 'on' else []),
                AgentPromptBoundary(workspace, role, expression_profile=expression_profile,
                                    interface_profile=interface_profile, prompt_profile=text_profile,
                                    review_submission_contract=submission_contract)]

    def configured_prompt(role):
        return role_prompt(role)

    roles = {role: configured_prompt(role) for role in ("writer", "reviewer", "layout")}
    from .prompt_sources import native_reviewer
    subagents = [{"name": role,
                  "description": load_prompt('agent-' + role),
                  "system_prompt": prompt,
                  "model": model_factory(role), "tools": business_tools(workspace, role, knowledge, model_factory("text_tool")),
                  "middleware": middleware(role)} for role, prompt in roles.items()
                 if hierarchical or not (native_enabled and role == "reviewer")]
    # New hierarchical runs use the delegated reviewer only. The former automatic
    # grader remains behind an explicit historical compatibility setting.
    review_middleware = []
    if hierarchical and workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
        from .hierarchical_review import HierarchicalRubric
        review_tools = business_tools(workspace, "rubric_grader", None, model_factory("text_tool"))
        review_middleware = [HierarchicalRubric(workspace, model_factory("rubric_grader"), review_tools,
            [TodoListMiddleware(), BusinessBoundary(workspace, "rubric_grader")])]
    elif native_enabled and not hierarchical:
        read_names = {"project_status", "read_source_page", "search_sources", "inspect_source_page", "analyze_source_image",
                      "calculate", "read_result", "knowledge_search", "knowledge_read", "knowledge_traverse"}
        if acceptance:
            read_names.update({"analyze_text", "analyze_evidence"})
        evidence_tools = [t for t in business_tools(workspace, "reviewer", knowledge, model_factory("text_tool"))
                          if t.__name__ in read_names]
        review_middleware = [native_review(workspace, model_factory("rubric_grader"), evidence_tools, rules,
                                           middleware=[*([TodoListMiddleware()] if acceptance else []),
                                                       BusinessBoundary(workspace, "rubric_grader")])]
    from .native_trace import trace_tools
    agent = create_deep_agent(model=model_factory("coordinator"),
                             tools=business_tools(workspace, "coordinator", knowledge, model_factory("text_tool")) + trace_tools(checkpointer),
                             system_prompt=configured_prompt("coordinator"), subagents=subagents, backend=backend,
                             middleware=[*middleware("coordinator", tuple((s['name'], s['description']) for s in subagents)),
                                         *review_middleware],
                             checkpointer=checkpointer, name="report_coordinator")
    from .failure_diagnostics import FailureDiagnostics
    diagnostics = FailureDiagnostics(workspace.store)
    from .handoff_release import release
    agent = agent.with_config(callbacks=[diagnostics],
        metadata={'history_format_version': HISTORY_FORMAT_VERSION,
                  'report_runtime_version_ref':runtime_version_ref,
                  'report_delegation_prompt_profile':prompt_profile,
                  'report_review_interface_profile':interface_profile,
                  'report_operation_identity_profile':identity_profile,
                  'report_content_input_profile':input_profile,
                  'report_expression_profile':expression_profile,
                  **({'report_prompt_profile':text_profile} if 'report_prompt_profile' in manifest else {}),
                  **({'report_review_submission_contract':submission_contract} if submission_contract else {}),
                  **({'report_handoff_release': release(manifest)} if interface_profile == 'review-interfaces-v4' else {})})
    agent.report_failure_diagnostics = diagnostics
    return agent


@asynccontextmanager
async def project_agent(workspace, model_factory=None, knowledge=None, rules="", *, decision_only=False):
    require_native_runtime(workspace)
    async with AsyncExitStack() as resources:
        factory = model_factory
        if factory is None:
            models, clients = {}, set()
            def own(client, asynchronous):
                if id(client) not in clients:
                    clients.add(id(client))
                    if asynchronous:
                        resources.push_async_callback(client.aclose)
                    else:
                        resources.callback(client.close)
            def factory(role):
                if role not in models:
                    from .deep_models import model_client_ownership
                    with model_client_ownership(own):
                        models[role] = configured_model(workspace.store, role)
                return models[role]
        async with AsyncSqliteSaver.from_conn_string(str(workspace.store.root / "checkpoints.db")) as saver:
            yield build_agent(workspace, factory, saver, knowledge, rules, decision_only=decision_only)


async def run_report(workspace, model_factory=None, *, knowledge=None, decision_only=False):
    require_native_runtime(workspace)
    if type(decision_only) is not bool:
        raise ActionRejected("DECISION_OBSERVATION_MODE_MUST_BE_BOOLEAN")
    if legacy_state.get_decision_observation(workspace.store):
        raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
    with workspace.store.run_lock():
        from .operator_instructions import sync_operator_instructions
        sync_operator_instructions(workspace.store)
        from .decision_data import bind as bind_decision_data
        bind_decision_data(workspace)
        from .source_search import bind_source_search
        bind_source_search(workspace)
        from .review_context import bind_context_experiment, experiment_config
        bind_context_experiment(workspace.store)
        from .handoff_release import manifest as bound_manifest
        manifest = bound_manifest(workspace.store)
        if model_factory is None:
            from .deep_models import bind_grader_trial
            delegated = (manifest.get('content_contract') == 'hierarchical-review-v1'
                and manifest.get('review_entrypoint') == 'delegated-reviewer-v1')
            legacy = any(workspace.store.get(key) for key in
                ('grader_model_trial', 'review_import017', 'rubric_targets', 'rubric_reviews'))
            if not delegated or legacy or os.environ.get('REPORT_GRADER_MODEL'):
                bind_grader_trial(workspace.store)
            from .model_config import bind_role_services
            bind_role_services(workspace.store)
        workspace.initialize()
        store = workspace.store
        from .acceptance import bind_mode, enabled, active_criteria, criteria_rules
        bind_mode(workspace)
        from .hierarchical_tools import enabled as content_enabled, role_prompt
        hierarchical = content_enabled(workspace)
        acceptance = enabled(workspace) and not hierarchical
        criteria = active_criteria(workspace) if acceptance else None
        rules = (criteria_rules(criteria) if criteria else "") if acceptance else load_rules()
        delegated_review = hierarchical and manifest.get("review_entrypoint") != "native-rubric-v1"
        if hierarchical:
            rules = "" if delegated_review else "Review the exact selected version using hierarchical-review-v1."
        native_enabled = acceptance or bool(rules)
        if native_enabled:
            store.set("active_rubric_hash", digest(rules))
            store.set("active_reviewer_prompt_hash", digest(role_prompt("reviewer") if hierarchical else reviewer_prompt(experiment_config(store), requirement_acceptance=acceptance)))
        elif delegated_review:
            store.set("active_reviewer_prompt_hash", digest(role_prompt("reviewer")))
        if not delegated_review and project_state(workspace)["status"] == "reviewed_draft" and not store.get("checkpoint_resume"):
            return project_state(workspace)
        # Do not throttle the framework's checkpoint executor: its writes have their
        # own dependencies. BusinessBoundary serializes business tool/delegation work.
        from .failure_diagnostics import FailureDiagnostics
        diagnostics = FailureDiagnostics(store)
        config = {"configurable": {"thread_id": "report"}, "recursion_limit": 10000}
        store.set("report_status", "running")
        store.set("report_error", None)
        store.set("runtime", "deepagents-0.7.19")
        own_knowledge = None
        progress_recovery_keys = []
        try:
            if (not hierarchical and knowledge is None and model_factory is None
                    and store.get("knowledge_enabled", True) is not False):
                from .knowledge import Knowledge
                project_id = store.get("knowledge_project_id") or str(uuid4())
                store.set("knowledge_project_id", project_id)
                own_knowledge = knowledge = Knowledge(project_id)
            async with project_agent(workspace, model_factory, knowledge, rules, decision_only=decision_only) as agent:
                diagnostics = agent.report_failure_diagnostics
                snapshot = await agent.aget_state(config)
                if delegated_review and snapshot.values and (snapshot.values.get("_active_rubric") or snapshot.values.get("rubric")):
                    raise RuntimeError("LEGACY_REVIEW_CHECKPOINT_REQUIRES_EXPLICIT_LEGACY_ENTRYPOINT")
                review_update = {"rubric": rules} if rules else {}
                store.set("checkpoint_resume", bool(snapshot.next))
                interrupts = snapshot.interrupts
                if interrupts:
                    issues = {i["id"]: i for i in issue_state.get_report_issues(store, [])}
                    answers = {}
                    for pending in interrupts:
                        from .execution_progress import KIND as PROGRESS_KIND, resume_answer as progress_answer
                        if pending.value.get('kind')==PROGRESS_KIND:
                            answer=progress_answer(workspace,pending.value)
                            if answer is None:
                                store.set('report_status','needs_attention')
                                store.set('report_error',{'failure_kind':'execution_progress_attention',
                                    'episode_id':pending.value['episode_id'],'automatic_resume':False})
                                return workspace.status()
                            answers[pending.id]=answer
                            progress_recovery_keys.append(store.get('execution_progress_episode:'+pending.value['episode_id'])['recovery_key'])
                            continue
                        from .text_work_interrupts import KIND, resume_answer
                        if pending.value.get("kind") == KIND:
                            answer = resume_answer(workspace, pending.value)
                            if answer is None:
                                store.set("report_status", "needs_attention")
                                return workspace.status()
                            answers[pending.id] = answer
                            continue
                        item = issues.get(pending.value.get("issue_id"), {})
                        if item.get("decision_origin") != "operator":
                            store.set("report_status", "needs_human")
                            return workspace.status()
                        answers[pending.id] = item["decision"]
                    payload = Command(resume=answers, update=review_update) if rules else Command(resume=answers)
                elif snapshot.next:
                    payload = Command(update=review_update) if rules else None
                else:
                    payload = {"messages": [("user", encode(project_view(workspace)))], "rubric": rules}
                store.event("deep_run_started", {"resume": bool(snapshot.next), "native_checkpoint": bool(snapshot.values)})
                store.set("checkpoint_resume", True)
                from .execution_progress import protected, active_episodes, reserve_recovery_request
                from .request_budget import request_reservation_observer
                if not interrupts and protected(workspace):
                    from .execution_progress import limited_model_resume_keys,consume_recovery
                    exact_keys=limited_model_resume_keys(workspace,snapshot)
                    if exact_keys is None:
                        store.set('report_status','needs_attention')
                        store.set('report_error',{'failure_kind':'execution_progress_attention','automatic_resume':False,
                            'recovery_boundary':'unsupported_or_unproven_root_model_zero_send'})
                        return workspace.status()
                    for key in exact_keys:consume_recovery(workspace,store.get(key)['episode_id'])
                    progress_recovery_keys.extend(exact_keys)
                # An incomplete checkpoint may have consumed a grant before a
                # local refusal. Reopening a host budget never refreshes it.
                progress_recovery_keys=list(dict.fromkeys([*progress_recovery_keys,*[
                    e['recovery_key'] for e in active_episodes(workspace)
                    if e['state']=='recovery_observe' and e.get('recovery_key')]]))
                from contextlib import nullcontext
                def reserve_progress():
                    for key in progress_recovery_keys:reserve_recovery_request(workspace,key)
                with (request_reservation_observer(reserve_progress) if progress_recovery_keys else nullcontext()):
                    try:
                        result = await agent.ainvoke(payload, config)
                    except Exception as exc:
                        from .request_budget import RequestBudgetExceeded
                        if isinstance(exc,RequestBudgetExceeded) and progress_recovery_keys:
                            pending=await agent.aget_state(config)
                            exc.execution_progress_pending_nodes=list(pending.next)
                        raise
                snapshot = await agent.aget_state(config)
                if delegated_review:
                    store.set("report_status", "completed")
                elif native_enabled:
                    if hierarchical:
                        from .hierarchical_review import reconcile
                        reconcile(workspace, snapshot.values)
                    else:
                        reconcile_review(workspace, snapshot.values)
                store.set("checkpoint_resume", bool(snapshot.next))
                store.set("native_interrupts", [{"id": i.id, "value": i.value} for i in snapshot.interrupts])
                if snapshot.interrupts:
                    from .text_work_interrupts import KIND
                    from .execution_progress import KIND as PROGRESS_KIND
                    status = ("needs_attention" if any(i.value.get("kind") in {KIND,PROGRESS_KIND} for i in snapshot.interrupts)
                              else "needs_human")
                    store.set("report_status", "decision_observed" if legacy_state.get_decision_observation(store) else status)
                    if any(i.value.get('kind')==PROGRESS_KIND for i in snapshot.interrupts):
                        store.set('report_error',{'failure_kind':'execution_progress_attention','automatic_resume':False})
                elif store.get("report_status") == "running":
                    store.set("report_status", "needs_attention")
                if not snapshot.interrupts and store.get('report_status') == 'completed':
                    from .content_delivery import current_delivery
                    if current_delivery(store).get('commission_coverage', {}).get('complete') is False:
                        store.set('report_status', 'incomplete')
                messages = result.get("messages", [])
                if messages:
                    store.set("agent_summary", messages[-1].content)
                store.event("deep_run_finished", {"status": store.get("report_status")})
        except asyncio.CancelledError:
            store.set("report_status", "interrupted")
            store.set("report_error", {"type": "CancelledError", "message": "INTERRUPTED_CHECKPOINT_AVAILABLE"})
            store.event("deep_run_cancelled", {"type": "CancelledError", "message": "MODEL_RESPONSE_MAY_BE_INCOMPLETE"})
            raise
        except Exception as exc:
            diagnostic = diagnostics.record(exc, phase="run_report")
            failure = {**error_data(exc), **(diagnostic or {})}
            from .model_recovery import recovery_block
            from .input_capacity import capacity_failure, capacity_handling
            technical_timeout = is_model_timeout(exc)
            recovery_blocked = recovery_block(exc) is not None
            capacity = capacity_failure(exc)
            from .request_budget import RequestBudgetExceeded
            progress_limit=bool(progress_recovery_keys) and isinstance(exc,RequestBudgetExceeded)
            own_progress_limit = progress_limit and getattr(exc, 'execution_progress_recovery_key', None) in progress_recovery_keys
            if progress_limit:
                from .execution_progress import mark_observation_limit
                mark_observation_limit(workspace,progress_recovery_keys,exc)
            store.set("report_status", "needs_attention" if technical_timeout or recovery_blocked or capacity or progress_limit else "failed")
            if capacity is not None:
                handling = capacity_handling(capacity, 'root_agent')
                failure.update(failure_kind='model_capacity_blocked', capacity=capacity,
                               handling=handling, handling_owner=handling['handling_owner'], automatic_resume=False)
            elif progress_limit:
                failure.update(failure_kind='execution_progress_attention' if own_progress_limit else 'host_admission_blocked',automatic_resume=False,
                    observation_window_stopped=True,
                    recovery='Host diagnosis and a different verified condition are required; the consumed observation grant cannot be replayed.')
            elif technical_timeout or recovery_blocked:
                failure.update(failure_kind='model_recovery_blocked' if recovery_blocked else 'model_request_timeout', automatic_resume=False,
                               recovery='Inspect the existing native checkpoint and attempt receipts; '
                                        'no unknown request replay or successful review is implied.')
            store.set("report_error", failure)
            store.event("deep_run_error", failure)
        finally:
            store.set("report_activity", "")
            if own_knowledge is not None:
                own_knowledge.close()
        state = project_state(workspace)
        if hierarchical:
            state.update(content_delivery=legacy_state.get_content_delivery(store), content_final_review=legacy_state.get_content_final_review(store),
                         content_execution_decision=store.get("content_execution_decision"))
        return state
