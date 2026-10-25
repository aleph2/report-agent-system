"""Native middleware and transport provenance, not a prompt judge or agent loop.

Static role replacement is a non-retryable admission error. Public captures and
unexplained composition residuals are diagnostic; none prove semantic purity.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import hashlib
import json
from uuid import uuid4

import openai
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import SystemMessage

from .prompt_sources import (load_prompt, native_reviewer, review_profile, source_manifest,
                             delegation_profile, SEPARATE_DESCRIPTION, review_interface_profile,
                             review_handoff_source, expression_source, report_expression_profile,
                             REPORT_EXPRESSION_V1)
from .store import digest, encode

_CALL = ContextVar('report_prompt_call', default=None)


class PromptCompositionError(openai.OpenAIError):
    non_retryable = True


def public_projection(value):
    """Preserve public messages/tools/parameters, never opaque private reasoning.

    Image bytes/URLs are represented by digest and length. Headers/clients are
    never arguments to this function. No whitespace or instruction normalization.
    """
    if isinstance(value, list):
        return [public_projection(v) for v in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if key in {'reasoning_content', 'reasoning', 'signature', 'encrypted_content'}:
            result[key + '_metadata'] = {'present':item is not None,
                'characters':len(item) if isinstance(item, str) else None}
        elif key in {'image_url', 'image', 'file_data'}:
            raw = encode(item)
            result[key + '_metadata'] = {'sha256':hashlib.sha256(raw.encode()).hexdigest(), 'characters':len(raw)}
        else:
            result[key] = public_projection(item)
    return result


def _capture(store, kind, value):
    from .transport_observation import observe_safely
    call = _CALL.get()
    context = {'capture_kind':kind, 'purpose':call['purpose'] if call else None,
               'call_id':call['call_id'] if call else None}
    def write():
        captured = value() if callable(value) else value
        key = 'prompt_capture:' + digest(captured)
        if store.get(key) is None:
            store.set(key, captured)
        store.event(kind, {'capture_key':key, 'purpose':captured.get('purpose'),
                          'call_id':captured.get('call_id'), 'status':captured.get('status'),
                          'semantic_guarantee':'none'})
        if call is not None and kind == 'prompt_final_http_input':
            call.setdefault('final_captures', []).append(key)
    def save():
        try:
            write()
        except Exception as exc:
            gap = {**context, 'status':'unexplained', 'exception_type':type(exc).__name__,
                   'semantic_guarantee':'none'}
            observe_safely(lambda: store.event('prompt_capture_unavailable',gap))
            import logging
            logging.getLogger(__name__).warning('Prompt capture unavailable: %s', encode(gap))
            raise
    if store is not None:
        observe_safely(save)


@contextmanager
def prompt_call(store, purpose, *, sources=(), status='unexplained', offered=None):
    call = {'store':store, 'purpose':purpose, 'call_id':str(uuid4()),
            'sources':tuple(sources), 'status':status, 'expected_wire':None,
            'source_manifest':{'status':'unavailable', 'files':[], 'semantic_guarantee':'none'},
            'runtime_version_ref':None}
    token = _CALL.set(call)
    try:
        def offered_capture():
            public = public_projection(offered)
            from langgraph.config import get_config
            try:
                call['runtime_version_ref'] = get_config().get('metadata', {}).get('report_runtime_version_ref')
            except RuntimeError:
                pass  # Direct SDK/helper invocation has no native graph binding.
            call['source_manifest'] = source_manifest(store, call['sources'], public)
            return {'purpose':purpose, 'call_id':call['call_id'],
                'sources':list(call['sources']), 'source_manifest':call['source_manifest'],
                'runtime_version_ref':call['runtime_version_ref'],
                'status':status, 'public_input':public}
        _capture(store, 'prompt_model_input', offered_capture)
        yield call
    finally:
        _CALL.reset(token)


def check_static_prompt(actual, source, *, suffix=''):
    if actual != load_prompt(source) + suffix:
        raise PromptCompositionError('PROMPT_STATIC_COMPOSITION_MISMATCH')


def analysis_source(contract, inputs, store=None):
    if contract == 'independent-text-tools-v1':
        return expression_source('qualifier-work' if inputs.get('revision') else 'text-work',
            report_expression_profile(store) if store is not None else REPORT_EXPRESSION_V1)
    if contract == 'selected-evidence-v3':
        return 'evidence-analysis'
    if contract.startswith('assigned-review-'):
        return 'legacy-bounded-review'
    if contract == 'assigned-artifact-text-work-v1':
        return 'artifact-analysis'
    if contract == 'learning-evidence-text-work-v1':
        return 'learning-analysis'
    return None  # Explicit host diagnostic/custom callers are not relabelled.


def bind_wire_payload(payload):
    """Called after the adapter's documented transformations, before serialization.

    HTTPX compares the serialized request again before accounting. This proves
    that no later public payload mutation was hidden, not that the adapter's own
    implementation is correct; adapter behavior has independent fixture oracles.
    """
    call = _CALL.get()
    if call is not None:
        expected = deepcopy(payload)
        # The OpenAI SDK flattens extra_body into json_data, including {}.
        # Account for this explicit protocol transform, not broad normalization.
        extra = expected.pop('extra_body', None) or {}
        if any(key in extra for key in ('messages','tools','response_format','model')):
            _refuse('PROMPT_EXTRA_BODY_OVERRIDES_COMPOSITION', 'adapter_before_serialization')
        for key, value in extra.items():
            expected[key] = value
        call['expected_wire'] = public_projection(expected)


def _refuse(code, origin):
    # Same-exception, zero-admission proof only. Earlier admitted attempts and
    # historical unknown operations cannot acquire a not-dispatched proof.
    from .request_budget import record_local_refusal
    error = PromptCompositionError(code)
    record_local_refusal(error, None, guard_origin=origin)
    raise error


def admit_prompt_request(request):
    call = _CALL.get()
    if call is None or call['expected_wire'] is None:
        return  # Uninstrumented historical/direct SDK paths remain a named gap.
    actual = public_projection(json.loads(request.content))
    if actual != call['expected_wire']:
        _capture(call['store'], 'prompt_composition_rejected', {'purpose':call['purpose'],
            'call_id':call['call_id'], 'status':'unexplained', 'expected':call['expected_wire'],
            'actual':actual, 'admitted':False, 'automatic_retry':False})
        _refuse('PROMPT_FINAL_WIRE_COMPOSITION_MISMATCH', 'http_request_hook_before_financial_accounting')


def observe_prompt_request(request, store=None, role=None):
    call = _CALL.get()
    def final_capture():
        public = public_projection(json.loads(request.content))
        return {'purpose':call['purpose'] if call else 'unattributed:' + str(role),
            'call_id':call['call_id'] if call else None,
            'status':call['status'] if call else 'unexplained',
            'expected_wire_available':bool(call and call['expected_wire'] is not None),
            'sources':list(call['sources']) if call else [],
            'source_manifest':call['source_manifest'] if call else {'status':'unattributed', 'files':[]},
            'runtime_version_ref':call['runtime_version_ref'] if call else None,
            'final_tool_schema_sha256':digest(public['tools']) if 'tools' in public else None,
            'public_input':public, 'body_sha256':hashlib.sha256(request.content).hexdigest(),
            'attempt_id':(request.extensions.get('report_token_budget') or (None,None))[1],
            'limitation':'Only public composition and local dispatch facts. Source matches are observations, not authority or semantic guarantees. Runtime ref comes from native graph config; direct calls may be unbound. No retry authority.'}
    _capture(store if store is not None else call['store'] if call else None,
        'prompt_final_http_input', final_capture)


def append_declared_system(request, text, source, *, references=None, files=()):
    """Keep exact app contribution bytes with the SystemMessage, outside wire text."""
    old = request.system_message
    blocks = old.content_blocks if old else []
    declared = list((old.additional_kwargs if old else {}).get('report_system_contributions', []))
    declared.append({'source':source, 'text':text,
        **({'references':deepcopy(references)} if references is not None else {}),
        **({'files':list(files)} if files else {})})
    system = SystemMessage(content=[*blocks, {'type':'text', 'text':text}],
        additional_kwargs={'report_system_contributions':declared})
    return request.override(system_message=system)


def progress_response_fact(store, call, response, contributions):
    """Diagnostic same-call delivery/completion facts; never infer comprehension."""
    from langchain_core.messages import AIMessage
    messages = getattr(response,'result',[])
    message = messages[0] if len(messages)==1 and isinstance(messages[0],AIMessage) else None
    completed = bool(message and message.id and not message.invalid_tool_calls
        and message.response_metadata.get('finish_reason') in {'stop','tool_calls'})
    captures = []
    for key in dict.fromkeys(call.get('final_captures',[])):
        captured = store.get(key)
        if (captured and captured.get('call_id')==call['call_id']
                and captured.get('purpose')==call['purpose']
                and captured.get('expected_wire_available') and captured.get('status')=='exact'):
            captures.append((key,captured))
    notices,conditions = [],[]
    for part in contributions:
        if part['source'] not in {'execution_progress/repetition','execution_progress/recovery_condition'}: continue
        for key,captured in captures:
            system = [m.get('content') for m in captured['public_input']['messages'] if m.get('role')=='system']
            texts = [b.get('text') for c in system if isinstance(c,list) for b in c if isinstance(b,dict)]
            texts += [c for c in system if isinstance(c,str)]
            if any(part['text']==text or part['text'] in text for text in texts if isinstance(text,str)):
                target=notices if part['source']=='execution_progress/repetition' else conditions
                target.append({**part['references'], 'capture_ref':key,
                    'text_sha256':hashlib.sha256(part['text'].encode()).hexdigest()})
                break
    fact = {'purpose':call['purpose'],'call_id':call['call_id'],
        'ai_message_id':message.id if message else None,
        'tool_call_ids':[c['id'] for c in message.tool_calls] if message else [],
        'completed':completed and bool(captures),
        'finish_reason':message.response_metadata.get('finish_reason') if message else None,
        'final_capture_refs':[k for k,_ in captures], 'notices':notices,'recovery_conditions':conditions,
        'limitation':'Final request bytes plus a completed local model response; not provider comprehension or semantic progress.'}
    _capture(store,'prompt_response_fact',fact)


def classify_agent_system(system, expected):
    """Compare ordered application blocks and named platform contributions.

    An unexplained residual is retained, never erased or called validated. The
    static-role guard only claims to reject a missing/replaced configured base;
    independent snapshots and final-wire comparison cover other mutation points.
    """
    from langchain.agents.middleware.todo import WRITE_TODOS_SYSTEM_PROMPT
    blocks = system.content_blocks if system else []
    sources = [{'source':'configured_role_files', 'sha256':hashlib.sha256(expected.encode()).hexdigest()}]
    if not blocks or blocks[0].get('type') != 'text' or not blocks[0].get('text','').startswith(expected):
        return 'static_mismatch', sources
    exact = blocks[0]['text'] == expected
    declared = (system.additional_kwargs if system else {}).get('report_system_contributions', [])
    # Declared appends are ordered, not a set of allowed substrings.
    remaining = list(declared)
    for block in blocks[1:]:
        text = block.get('text')
        if block.get('type') == 'text' and text in {WRITE_TODOS_SYSTEM_PROMPT, '\n\n'+WRITE_TODOS_SYSTEM_PROMPT}:
            sources.append({'source':'langchain/TodoListMiddleware', 'sha256':digest(text)})
        elif remaining and block == {'type':'text','text':remaining[0]['text']}:
            part = remaining.pop(0)
            sources.append({'source':part['source'], 'sha256':digest(part['text']),
                **{k:part[k] for k in ('references','files') if k in part}})
        else:
            exact = False
            sources.append({'source':'unexplained_residual', 'sha256':digest(block)})
    if remaining:
        exact = False
    if not exact:
        sources.append({'source':'unexplained_composition', 'semantic_guarantee':'none'})
    return ('exact' if exact else 'unexplained'), sources


class CurrentReviewPlan(AgentMiddleware):
    """Project the selected child namespace's current native todos, without a gate."""
    def __init__(self, workspace):
        self.workspace = workspace

    async def awrap_model_call(self, request, handler):
        todos = request.state.get('todos')
        if todos:
            from .task_context import actor_id
            text = load_prompt('current-review-plan') + '\n' + encode({
                'actor_id':actor_id(self.workspace, 'reviewer'), 'todos':todos,
                'authority':'working intentions only; assignment and saved checks remain independent'})
            request = append_declared_system(request, text, 'native_todos/current_child_state',
                files=['current-review-plan'])
        return await handler(request)


class AgentPromptBoundary(AgentMiddleware):
    def __init__(self, workspace, role, *, source=None, expression_profile=None, interface_profile=None, prompt_profile=None):
        self.workspace, self.role, self.source = workspace, role, source
        self.expression_profile = expression_profile
        self.interface_profile = interface_profile
        self.prompt_profile = prompt_profile

    async def awrap_model_call(self, request, handler):
        independent_optimizer = self.source == 'experience-optimizer' and self.role == 'experience_optimizer'
        expression_profile = (REPORT_EXPRESSION_V1 if independent_optimizer else
                              self.expression_profile if self.expression_profile is not None
                              else report_expression_profile(self.workspace.store))
        role_source = expression_source('content-' + self.role, expression_profile)
        expected = (load_prompt(self.source) if self.source else load_prompt('legacy-review-organizer') if self.role == 'reviewer'
                    and not native_reviewer(self.workspace.store) else
                    load_prompt('content-common') + '\n\n' + load_prompt(role_source))
        from .prompt_sources import (REVIEW_INTERFACE_V3, role_sources, context_source, describe_current_tools,
            report_prompt_profile, report_rule_source, LEGACY_PROMPTS, CONCISE_PROMPTS)
        text_profile = (LEGACY_PROMPTS if self.source is not None else self.prompt_profile
            if self.prompt_profile is not None else report_prompt_profile(self.workspace.store))
        interface = ('not_applicable' if self.source is not None else self.interface_profile
                     if self.interface_profile is not None else review_interface_profile(self.workspace.store))
        if interface == 'review-interfaces-v4' and self.source is None:
            expected = '\n\n'.join(load_prompt(s) for s in role_sources(self.role, expression_profile, interface, text_profile))
        saved_handoff = interface == REVIEW_INTERFACE_V3 and self.role in {'coordinator', 'writer'}
        if saved_handoff:
            expected += '\n\n' + load_prompt('saved-reference-handoff')
        if self.role in {'writer','reviewer','layout'}:
            expected += '\n' + load_prompt(context_source(self.role, interface, text_profile))
        blocks = request.system_message.content_blocks if request.system_message else []
        status, sources = classify_agent_system(request.system_message, expected)
        if status == 'static_mismatch':
            raise PromptCompositionError('PROMPT_STATIC_ROLE_REPLACED')
        files = ([self.source] if self.source else ['legacy-review-organizer'] if self.role == 'reviewer'
            and not native_reviewer(self.workspace.store) else ['content-common', role_source])
        if interface == 'review-interfaces-v4' and self.source is None:
            files = role_sources(self.role, expression_profile, interface, text_profile)
        if saved_handoff:
            files.append('saved-reference-handoff')
        if self.role in {'writer','reviewer','layout'}:
            files.append(context_source(self.role, interface, text_profile))
        sources[0]['files'] = files
        from langchain_core.utils.function_calling import convert_to_openai_tool
        tools = [convert_to_openai_tool(t) for t in request.tools]
        description_files = []
        if text_profile == CONCISE_PROMPTS:
            tools, description_files = describe_current_tools(tools)
            request = request.override(tools=tools)
        profile = 'not_applicable'
        if self.source is None:
            profile = delegation_profile(self.workspace.store)
            from langgraph.config import get_config
            try:
                profile = get_config().get('metadata', {}).get('report_delegation_prompt_profile', profile)
            except RuntimeError:
                pass  # Direct middleware fixtures use the explicit host manifest.
        # Provenance and the handler receive the same description-only projection.
        tool_text = encode(tools)
        tool_files = [('native-content-index-tool-v4' if text_profile == CONCISE_PROMPTS else 'native-content-index-tool')] if any(
            t.get('function', {}).get('name') == 'read_content_index' for t in tools) and native_reviewer(self.workspace.store) else []
        tool_files += description_files
        if any(t.get('function', {}).get('name') == 'task' for t in tools):
            if profile == SEPARATE_DESCRIPTION:
                tool_files += ['content-writer-description', 'content-layout-description', 'content-reviewer-description']
            else:
                tool_files += ['content-common', expression_source('content-writer', expression_profile), 'content-layout',
                    'content-reviewer' if native_reviewer(self.workspace.store) else 'legacy-review-organizer']
            if native_reviewer(self.workspace.store):
                tool_files.append(review_handoff_source(interface, text_profile))
                if interface == 'review-interfaces-v4':
                    tool_files.append(report_rule_source('native-task-description-v4', text_profile))
        if interface == REVIEW_INTERFACE_V3:
            names = {t.get('function', {}).get('name') for t in tools}
            if 'freeze_snapshot' in names:
                tool_files.append('freeze-receipts-v3')
            if 'read_decision_state' in names:
                tool_files.append('state-paths-v3')
        if interface == 'review-interfaces-v4':
            names = {t.get('function', {}).get('name') for t in tools}
            tool_files += [report_rule_source(source, text_profile) if name != 'confirm_review_reuse' else source for name, source in {
                'select_content_delivery':'select-content-delivery-v4',
                'submit_review':'native-submit-review-v4',
                'confirm_review_reuse':'native-review-reuse-v4',
                'commit_objects':'deliverable-save-tool-v4',
                'save_text_node':'deliverable-save-tool-v4'}.items() if name in names]
            if 'export_content_workbook' in names:
                tool_files.append('export-content-workbook-v4')
            if 'export_content_snapshot' in names:
                tool_files.append('export-content-snapshot-v4')
        if tool_files:
            sources.append({'source':'native_registered_tools', 'files':tool_files, 'sha256':digest(tool_text)})
        offered = {'messages':[{'role':'system','content':blocks},
            *[m.model_dump(mode='json') for m in request.messages]], 'tools':tools,
            'delegation_prompt_profile':profile,
            'review_profile':('not_applicable' if self.source == 'experience-optimizer'
                and self.role == 'experience_optimizer' else review_profile(self.workspace.store))}
        with prompt_call(self.workspace.store, self.role, sources=sources,
                         status=status, offered=offered) as call:
            response = await handler(request)
            from .transport_observation import observe_safely
            observe_safely(lambda:progress_response_fact(self.workspace.store,call,response,
                request.system_message.additional_kwargs.get('report_system_contributions',[]))
                if (self.workspace.store.get('manifest') or {}).get('execution_progress_policy') is not None else None)
            return response
