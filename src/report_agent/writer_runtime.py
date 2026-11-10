"""Fresh, compact native Writer tasks; no model selection, launch command or paid call."""
from contextlib import contextmanager
import json
from typing import Annotated, Literal
from uuid import uuid4

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, StructuredTool
from pydantic import Field, create_model

from .content_models import Contract
from .content_store import ContentStore
from .errors import ActionRejected


class ReadPage(Contract):
    source_handle: str = Field(min_length=1)
    page: int = Field(strict=True, ge=1)
    view: Literal["text", "native_text", "tables"] = "text"


def _public(value):
    if isinstance(value, dict):
        hidden = {'source_id','source_ref','source_pin','sha256','image_ref','image_data_url','image_sha256'}
        return {k:_public(v) for k,v in value.items() if k not in hidden}
    if isinstance(value, list):
        return [_public(v) for v in value]
    return value


def writer_tools(workspace, actor, *, include_images=True, assessment_only=False):
    from .writer_issues import tool_functions as issues
    from .writer_assignments import (read_assigned_page as read_page, mark_visual_page_delivered, page_view)
    from .native_operation_tools import _native_write, MessageTool
    from .operation_identity import NATIVE_WRITES
    cs = ContentStore(workspace.store)
    functions = issues(cs, lambda:actor)
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
        content: list[str | dict] = [{'type':'text','text':json.dumps(_public(projected),ensure_ascii=False)}]
        if include_images:
            content.append({'type':'image_url','image_url':{'url':value['image_data_url']}})
        message=ToolMessage(content=content,tool_call_id=tool_call_id,name='read_assigned_page')
        if include_images:
            handle = value['page_handle']
            mark_visual_page_delivered(cs,actor,handle,value['image_sha256'])
        else:
            from .writer_assignments import mark_text_page_delivered
            handle = mark_text_page_delivered(cs, actor, args.source_handle, args.page, projected)
        message.artifact = {'writer_page_delivery': handle}
        return message
    if not include_images:
        read_assigned_page.__doc__ = 'Read one physical-page view: text uses frozen citation text with native fallback; native_text reads the PDF text; tables returns exact mechanical cell rows. Reopen another view when needed. This text-only Writer cannot inspect image pixels; drawing-only evidence remains unverified.'
    invocation=create_model('ReadAssignedPageInvocation',__base__=ReadPage,
        tool_call_id=(Annotated[str,InjectedToolCallId],...))
    tools.append(MessageTool.from_function(read_assigned_page,args_schema=invocation,message_model=ReadPage))

    from .writer_extraction import tools as extraction_tools
    return [*tools, *extraction_tools(workspace, actor)]


@contextmanager
def writer_session(workspace, object_label, model, *, assessment_only=False, indicator_steps=False, section_id=None):
    """Bind one fresh slope task; the caller separately owns any authority to invoke a model."""
    if indicator_steps is not True:
        raise ActionRejected('WRITER_INDICATOR_WORKFLOW_REQUIRED')
    if not assessment_only:
        raise ActionRejected('ASSESSMENT_ONLY_WORKFLOW_REQUIRED')
    from .commission_plan import _confirmed
    from .content_tasks import delegated_task
    from .section_writing import enabled
    from .writer_assignments import prepare_assignment_pages
    from .writer_indicator_steps import IndicatorRun
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
    goal += ' Save this one canonical assessment and necessary material issues only; do not write prose, assess other slopes, approve plans or export.'
    if not include_images:
        goal += ' This service is text-only. Page reads provide frozen/native text and mechanical table views, not visual interpretation. Drawing-only needs remain SYSTEM_VISUAL_CAPABILITY_UNAVAILABLE, not missing sources; never claim image verification.'
    call={'name':'task','id':'writer-'+uuid4().hex,'args':{'subagent_type':'writer',
        'description':goal,
        'section_ids':[sections[0]['section_id']],'assessment_object_id':matches[0]['object_id']}}
    with delegated_task(workspace,'coordinator',call) as (_,actor):
        from .writer_assignments import bound_assignment
        from .writer_fact_packet import bind_writer_facts
        from .writer_judgment_authority import provision_criteria
        with workspace.store.connect() as db:
            scope = bound_assignment(cs,db,actor)
        bind_writer_facts(cs,actor,scope)
        provision_criteria(cs,scope)
        prepare_assignment_pages(cs,actor)
        tools=writer_tools(workspace,actor,include_images=include_images,assessment_only=assessment_only)
        yield IndicatorRun(workspace,actor,model,tools)
