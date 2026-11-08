"""Fresh, compact native Writer tasks; no model selection, launch command or paid call."""
from . import legacy_state as legacy
from contextlib import contextmanager
from dataclasses import dataclass
import json
from typing import Annotated, Literal
from uuid import uuid4

from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.tools import InjectedToolCallId, StructuredTool
from pydantic import Field, create_model

from .content_models import Contract
from .content_store import ContentStore
from .errors import ActionRejected


class ReadPage(Contract):
    source_handle: str = Field(min_length=1)
    page: int = Field(strict=True, ge=1)
    view: Literal["text", "native_text", "tables"] = "text"


class ReadText(Contract):
    source_handle: str = Field(min_length=1)
    offset: int = Field(default=0, strict=True, ge=0)
    characters: int = Field(default=12000, strict=True, ge=1, le=20000)


def _public(value):
    if isinstance(value, dict):
        hidden = {'source_id','source_ref','source_pin','sha256','image_ref','image_data_url','image_sha256'}
        return {k:_public(v) for k,v in value.items() if k not in hidden}
    if isinstance(value, list):
        return [_public(v) for v in value]
    return value


def writer_tools(workspace, actor, *, include_images=True, assessment_only=False):
    from .writer_assessment import tool_functions as assessments
    from .writer_issues import tool_functions as issues
    from .writer_assignments import (read_assigned_page as read_page, mark_visual_page_delivered,
        prepare_assignment_pages, bound_assignment, page_view)
    from .native_operation_tools import _native_write, MessageTool
    from .operation_identity import NATIVE_WRITES
    cs = ContentStore(workspace.store)
    functions = [*assessments(cs, lambda:actor), *issues(cs, lambda:actor)]
    if assessment_only:
        functions = [f for f in functions if f.__name__ != 'save_section_prose']
    tools = [_native_write(workspace,'writer',f) if f.__name__ in NATIVE_WRITES
             else StructuredTool.from_function(f) for f in functions]

    def read_assigned_page(source_handle: str, page: int,
            tool_call_id: Annotated[str, InjectedToolCallId],
            view: Literal["text", "native_text", "tables"] = "text") -> ToolMessage:
        """Read an offered physical page. Default text is citation-aligned frozen text, falling back to native text; choose native_text or tables for an alternate view."""
        args=ReadPage.model_validate({'source_handle':source_handle,'page':page,'view':view})
        value=read_page(cs,actor,args.source_handle,args.page,include_image=include_images)
        projected=page_view({**value,'source_handle':args.source_handle},args.view)
        content=[{'type':'text','text':json.dumps(_public(projected),ensure_ascii=False)}]
        if include_images:
            content.append({'type':'image_url','image_url':{'url':value['image_data_url']}})
        message=ToolMessage(content=content,tool_call_id=tool_call_id,name='read_assigned_page')
        if include_images:
            mark_visual_page_delivered(cs,actor,value['page_handle'],value['image_sha256'])
        return message
    if not include_images:
        read_assigned_page.__doc__ = 'Read one physical-page view: text uses frozen citation text with native fallback; native_text reads the PDF text; tables returns exact mechanical cell rows. Reopen another view when needed. This text-only Writer cannot inspect image pixels; drawing-only evidence remains unverified.'
    invocation=create_model('ReadAssignedPageInvocation',__base__=ReadPage,
        tool_call_id=(Annotated[str,InjectedToolCallId],...))
    tools.append(MessageTool.from_function(read_assigned_page,args_schema=invocation,message_model=ReadPage))

    def read_assigned_text(source_handle: str, offset: int=0, characters: int=12000) -> dict:
        """Read an exact frozen text window. Follow next_offset for remaining source text."""
        args=ReadText.model_validate(dict(source_handle=source_handle,offset=offset,characters=characters))
        pages=prepare_assignment_pages(cs,actor)
        with cs.store.connect() as db:
            scope=bound_assignment(cs,db,actor)
            pairs=list(zip(pages['sources'],scope['sources']))
            selected=next((ref for entry,ref in pairs if entry['source_handle']==args.source_handle),None)
            if selected is None:raise ActionRejected('WRITER_SOURCE_HANDLE_UNKNOWN')
            text=cs._read(db,selected)['payload']['content']
        end=min(len(text),args.offset+args.characters)
        return {'source_handle':args.source_handle,'text':text[args.offset:end],
            'offset':args.offset,'next_offset':end if end<len(text) else None,'total_characters':len(text),
            'coverage':'exact window only; quote resolution retains the original frozen locations'}
    tools.append(MessageTool.from_function(read_assigned_text,args_schema=ReadText,message_model=ReadText))
    return tools


class _ClearUsedReadResults:
    def __init__(self, excluded):
        self.excluded = excluded

    def apply(self, messages, *, count_tokens):
        from langchain_core.messages import AIMessage
        from langchain.agents.middleware import ClearToolUsesEdit
        # Protect every result in the new batch, including batches with appended notices.
        unseen = 0
        for message in reversed(messages):
            if isinstance(message, AIMessage):
                break
            unseen += isinstance(message, ToolMessage)
        errors = {i:m for i,m in enumerate(messages) if isinstance(m,ToolMessage) and m.status=='error'}
        ClearToolUsesEdit(trigger=1,keep=max(1,unseen),clear_tool_inputs=False,
            exclude_tools=self.excluded,
            placeholder='[Earlier page/window text cleared. Its source handle and page/offset remain in the tool call; saved indicator quotes remain in saved inputs. Re-read the offered source when needed.]'
        ).apply(messages,count_tokens=count_tokens)
        for i,message in errors.items():
            messages[i] = message


def writer_context(tool_names):
    from langchain.agents.middleware import ContextEditingMiddleware
    excluded=tuple(name for name in tool_names if name not in {'read_assigned_page','read_assigned_text'})
    return ContextEditingMiddleware(edits=[_ClearUsedReadResults(excluded)])


@dataclass
class WriterSession:
    actor: object
    agent: object
    tools: list
    config: dict
    initial_message: HumanMessage


@contextmanager
def writer_session(workspace, object_label, model, *, assessment_only=False, indicator_steps=False, section_id=None):
    """Bind one fresh slope task; the caller separately owns any authority to invoke a model."""
    from langchain.agents import create_agent
    from langgraph.checkpoint.memory import InMemorySaver
    from .commission_plan import _confirmed
    from .content_tasks import delegated_task
    from .section_writing import enabled
    from .prompt_provenance import AgentPromptBoundary
    from .prompt_sources import load_prompt, record_runtime_version
    from .writer_assignments import prepare_assignment_pages
    from .deep_runtime import BusinessBoundary
    cs=ContentStore(workspace.store)
    if not enabled(workspace.store):raise ActionRejected('SYSTEM_ASSEMBLER_CONTRACT_REQUIRED')
    with workspace.store.connect() as db:
        plan,_=_confirmed(cs,db)
        matches=[o for o in plan['payload']['objects'] if o['label']==object_label]
        sections=[s for s in plan['payload']['sections'] if s['kind']=='extracted' and
                  (s['section_id']==section_id if section_id is not None else s['section_id'].split('.')[0]=='4')]
    if len(matches)!=1 or len(sections)!=1:raise ActionRejected('WRITER_SINGLE_OBJECT_ASSIGNMENT_REQUIRED')
    include_images = (getattr(model, 'profile', None) or {}).get('image_inputs') is not False
    goal = 'Assess the assigned slope using the bound assignment.'
    if assessment_only:
        goal += ' Save this one canonical assessment and necessary material issues only; do not write prose, assess other slopes, approve plans or export.'
    if not include_images:
        goal += ' This service is text-only. Page reads provide frozen/native text and mechanical table views, not visual interpretation. Drawing-only needs remain SYSTEM_VISUAL_CAPABILITY_UNAVAILABLE, not missing sources; never claim image verification.'
    call={'name':'task','id':'writer-'+uuid4().hex,'args':{'subagent_type':'writer',
        'description':goal,
        'section_ids':[sections[0]['section_id']],'assessment_object_id':matches[0]['object_id']}}
    with delegated_task(workspace,'coordinator',call) as (native,actor):
        if (workspace.store.root / "assertion-access.sqlite3").is_file():
            from .writer_assignments import bound_assignment
            from .writer_fact_packet import bind_writer_facts
            with workspace.store.connect() as db:
                bind_writer_facts(cs, actor, bound_assignment(cs, db, actor))
        prepare_assignment_pages(cs,actor)
        tools=writer_tools(workspace,actor,include_images=include_images,assessment_only=assessment_only)
        if indicator_steps:
            from .writer_indicator_steps import IndicatorRun
            if not assessment_only:
                raise ValueError('ASSESSMENT_ONLY_WORKFLOW_REQUIRED')
            yield IndicatorRun(workspace,actor,model,tools)
            return
        middleware=[BusinessBoundary(workspace,'writer')]
        if not include_images:
            middleware.append(writer_context([tool.name for tool in tools]))
        middleware.append(AgentPromptBoundary(workspace,'writer',source='writer-judgments'))
        if assessment_only:
            from .assessment_completion import AssessmentCompletionStop
            from .store import digest
            def completed():
                ref = legacy.get_g6_assessment(workspace.store, digest([plan['ref'], matches[0]['object_id']]))
                return bool(ref and cs.read(ref)['owner_id'] == actor.id)
            middleware.insert(0, AssessmentCompletionStop(completed))
        agent=create_agent(model,tools,system_prompt=load_prompt('writer-judgments'),
            middleware=middleware,checkpointer=InMemorySaver(),name='writer_judgments')
        config={'configurable':{'thread_id':actor.task_id},'metadata':{
            'report_runtime_version_ref':record_runtime_version(workspace.store),
            'report_operation_identity_profile':'native-tool-runtime-v1'}}
        yield WriterSession(actor,agent,tools,config,HumanMessage(content=native['args']['description']))
