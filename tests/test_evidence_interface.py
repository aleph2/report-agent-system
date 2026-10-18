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


async def test_size_failure_reaches_native_agent_with_exact_components_and_no_text_call(ws, monkeypatch):
    item = {'kind': 'source_blocks', 'selection': {'source_id': 's', 'offset': 0, 'limit': 1},
            'observation': {'blocks': [{'text': 'Relevant text'}],
                            'source_table_views': [{'geometry': 'x' * 65000}]}}
    original = deepcopy(item)
    monkeypatch.setattr(text_work, 'selected_evidence', lambda *a, **k: [item])
    diagnostics = []
    def inspect(messages):
        error = observation(messages, 'process_report_content')
        assert error['code'] == 'TEXT_WORK_SELECT_SMALLER_LOCATED_EVIDENCE'
        details = json.loads(error['message'].split(': ', 1)[1])
        assert details['encoded_characters'] == len(encode([item]))
        assert details['maximum_encoded_characters'] == 64000
        assert details['items'][0]['table_supplements_characters'] == len(encode(item['observation']['source_table_views']))
        assert details['producer_invoked'] is False
        diagnostics.append(details)
        return AIMessage(content='Size diagnosed; choose next material separately.')
    driver = Driver(coordinator=[AIMessage(content='', tool_calls=[writer_call()]),
        AIMessage(content='No text producer invoked, no report acceptance.')],
        writer=[invoke('process_report_content', operation_id='large', objective='Describe selected material',
            object_type='ContentNode', source_selections=[{'source_id': 's'}]), inspect])
    await run_report(ws, driver)
    assert diagnostics and item == original
    assert not any(role == 'text_tool' for role, _, _ in driver.calls)
    # Inspect the schema actually bound by the native graph, after middleware.
    schemas = [s for batch in driver.bindings['writer'] for s in batch]
    for schema in (s for s in schemas if s['name'] == 'process_report_content'):
        assert schema['parameters']['properties']['output_count']['maximum'] == 32
    with ws.store.connect() as db:
        assert not db.execute("SELECT key FROM state WHERE key LIKE 'text_work:%:large'").fetchall()


def test_valid_success_packet_is_unchanged_and_not_limited_to_two_selections(ws, monkeypatch):
    items = [{'kind': 'source_blocks', 'selection': {'source_id': 's', 'offset': i, 'limit': 1},
              'observation': {'blocks': [{'text': f'Located fact {i}'}], 'source_table_views': []}}
             for i in range(5)]
    original = deepcopy(items)
    monkeypatch.setattr(text_work, 'selected_evidence', lambda *a, **k: items)
    actual = text_work.evidence_packet(ws, [], [{'source_id': 's'}])
    assert actual == original and digest(actual) == digest(original)
