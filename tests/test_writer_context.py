"""Page eviction preserves evidence handles and new tool batches without inference."""
from copy import deepcopy
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain.agents.middleware import ContextEditingMiddleware
from report_agent.writer_runtime import writer_context


def exchange(name,call_id,text,**args):
    return [AIMessage(content='',tool_calls=[{'name':name,'id':call_id,'args':args}]),
            ToolMessage(text,tool_call_id=call_id,name=name)]


def edit(messages):
    middleware=writer_context(['read_assignment','read_assigned_page','read_assigned_text','set_indicator','submit_assessment','propose_material_issue'])
    assert isinstance(middleware,ContextEditingMiddleware)
    result=deepcopy(messages)
    for strategy in middleware.edits:strategy.apply(result,count_tokens=lambda m:100)
    return result


def test_old_page_cleared_but_latest_page_and_saved_quote_arguments_survive():
    messages=[HumanMessage(content='assess'),*exchange('read_assignment','a','BOUND_ASSIGNMENT'),
        *exchange('read_assigned_page','p1','OLD_PAGE_RAW',source_handle='source-1',page=96),
        *exchange('set_indicator','s1','SAVED_INDICATOR',quotes=['EXACT_SAVED_QUOTE']),
        *exchange('read_assigned_page','p2','LATEST_PAGE_RAW',source_handle='source-2',page=43)]
    original=deepcopy(messages);result=edit(messages)
    contents=[str(m.content) for m in result]
    assert 'OLD_PAGE_RAW' not in contents and 'LATEST_PAGE_RAW' in contents
    assert 'BOUND_ASSIGNMENT' in contents and 'SAVED_INDICATOR' in contents
    assert result[3].tool_calls==original[3].tool_calls
    assert result[5].tool_calls[0]['args']['quotes']==['EXACT_SAVED_QUOTE']
    assert messages==original, 'Native checkpoint remains intact'
    cleared=next(m for m in result if isinstance(m,ToolMessage) and m.tool_call_id=='p1')
    assert cleared.response_metadata['context_editing']['strategy']=='clear_tool_uses'


def test_all_unseen_results_in_latest_multi_page_batch_survive():
    messages=[HumanMessage(content='assess'),*exchange('read_assigned_page','old','OLD_RAW',source_handle='source-1',page=22),
        AIMessage(content='',tool_calls=[{'name':'read_assigned_page','id':'new1','args':{'source_handle':'source-2','page':43}},
                                       {'name':'read_assigned_page','id':'new2','args':{'source_handle':'source-2','page':45}}]),
        ToolMessage('UNSEEN_PAGE_43',tool_call_id='new1',name='read_assigned_page'),
        ToolMessage('UNSEEN_PAGE_45',tool_call_id='new2',name='read_assigned_page')]
    result=edit(messages)
    assert result[-2].content=='UNSEEN_PAGE_43' and result[-1].content=='UNSEEN_PAGE_45'
    assert result[2].content!='OLD_RAW'
    later=edit([*messages,*exchange('set_indicator','s','SAVED',quotes=['EXACT'])])
    assert all(str(m.content) not in {'OLD_RAW','UNSEEN_PAGE_43','UNSEEN_PAGE_45'} for m in later)
    assert later[-1].content=='SAVED'


def test_text_windows_clear_like_pages_but_errors_and_issues_are_not_forged():
    messages=[HumanMessage(content='assess'),*exchange('read_assigned_text','t','OLD_WINDOW',source_handle='source-1',offset=0),
        *exchange('propose_material_issue','i','ISSUE_SAVED'),*exchange('read_assigned_text','u','CURRENT_WINDOW',source_handle='source-1',offset=10)]
    result=edit(messages)
    assert result[2].content!='OLD_WINDOW' and result[-1].content=='CURRENT_WINDOW'
    assert result[4].content=='ISSUE_SAVED'


def test_read_error_keeps_its_code_and_unseen_batch_survives_later_notice():
    messages=[HumanMessage(content='assess'),*exchange('read_assigned_page','bad','WRITER_SOURCE_HANDLE_UNKNOWN',source_handle='foreign',page=1)]
    messages[-1].status='error'
    messages += [AIMessage(content='',tool_calls=[{'name':'read_assigned_page','id':'n1','args':{'source_handle':'source-1','page':1}},
                                              {'name':'read_assigned_page','id':'n2','args':{'source_handle':'source-1','page':2}}]),
                 ToolMessage('NEW_ONE',tool_call_id='n1',name='read_assigned_page'),
                 ToolMessage('NEW_TWO',tool_call_id='n2',name='read_assigned_page'),HumanMessage(content='Current host notice')]
    result=edit(messages)
    assert result[2].status=='error' and result[2].content=='WRITER_SOURCE_HANDLE_UNKNOWN'
    assert result[-3].content=='NEW_ONE' and result[-2].content=='NEW_TWO'
