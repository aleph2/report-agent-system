"""Actual registered native interfaces, not model quality tests; no provider calls."""
import json
from copy import deepcopy

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import ValidationError

from report_agent import text_work
from report_agent.catalog import Catalog
from report_agent.deep_runtime import business_tools, run_report
from report_agent.store import encode, digest
from test_deep_runtime import Driver, invoke, observation
from test_task_supervision import ws
from test_text_work import writer_call


def test_final_registered_schema_exposes_count_and_block_units(ws):
    functions = {f.__name__: f for f in business_tools(ws, 'writer', None, None)}
    for name in ('process_report_content', 'read_source_page'):
        function = functions[name]
        tool = (StructuredTool.from_function(coroutine=function) if name == 'process_report_content'
                else StructuredTool.from_function(function))
        schema = convert_to_openai_tool(tool)['function']['parameters']
        props = schema['properties']
        if name == 'process_report_content':
            assert props['output_count']['minimum'] == 1
            assert props['output_count']['maximum'] == 32
            assert 'selection-count' in tool.description
            for count in (0, 33, True):
                with pytest.raises(ValidationError):
                    tool.args_schema.model_validate(dict(operation_id='x', objective='x',
                        object_type='ContentNode', output_count=count))
        else:
            assert props['offset']['minimum'] == 0
            assert 'text-block' in props['offset']['description']
            assert props['limit']['maximum'] == 50
            assert 'next_offset=None' in tool.description
            # No new fields alter a successful retrieval/receipt evidence digest.
            actual = function('s', 0, 1)
            from report_agent.source_tables import with_source_tables
            expected = with_source_tables(ws, Catalog(ws.store).read('s', 0, 1))
            assert actual == expected


async def test_large_material_reaches_native_producer_without_trimming(ws, monkeypatch):
    from test_text_work import content
    item = {'kind': 'source_blocks', 'selection': {'source_id': 's', 'offset': 0, 'limit': 1},
            'observation': {'blocks': [{'text': 'Relevant text'}],
                            'source_table_views': [{'geometry': 'x' * 65000}]}}
    original = deepcopy(item)
    monkeypatch.setattr(text_work, 'selected_evidence', lambda *a, **k: [item])
    def inspect(messages):
        work = observation(messages, 'process_report_content')
        assert work['text_work_id']
        return AIMessage(content='Generation received; not adopted.')
    driver = Driver(coordinator=[AIMessage(content='', tool_calls=[writer_call()]), AIMessage(content='No acceptance claim.')],
        writer=[invoke('process_report_content', operation_id='large', objective='Describe selected material',
            object_type='ContentNode', source_selections=[{'source_id': 's'}]), inspect],
        text_tool=[AIMessage(content=json.dumps(content()))])
    result = await run_report(ws, driver)
    assert result['last_error'] is None, result
    assert item == original
    calls = [messages for role, _, messages in driver.calls if role == 'text_tool']
    assert len(calls) == 1 and 'x' * 65000 in calls[0][-1].content



def test_valid_success_packet_is_unchanged_and_not_limited_to_two_selections(ws, monkeypatch):
    items = [{'kind': 'source_blocks', 'selection': {'source_id': 's', 'offset': i, 'limit': 1},
              'observation': {'blocks': [{'text': f'Located fact {i}'}], 'source_table_views': []}}
             for i in range(5)]
    original = deepcopy(items)
    monkeypatch.setattr(text_work, 'selected_evidence', lambda *a, **k: items)
    actual = text_work.evidence_packet(ws, [], [{'source_id': 's'}])
    assert actual == original and digest(actual) == digest(original)
