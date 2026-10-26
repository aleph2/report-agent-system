"""Replay the first Writer reference error at the registered schema boundary."""
import json
import pytest
from langchain_core.tools import StructuredTool
from pydantic import ValidationError
from report_agent.content_tasks import delegated_task
from test_bounded_review import Model
from test_hierarchical_content import ws, seed
from test_text_work import tools, writer_call


@pytest.mark.parametrize("reference", ["cbb48bd9-a24a-49f6-a74c-d50b7a1d8774", "a" * 32])
async def test_business_uuid_or_prefix_cannot_reach_text_producer(ws, reference):
    cs, _, _, _, _ = seed(ws)
    model = Model(json.dumps({}))
    with delegated_task(ws, "coordinator", writer_call()):
        before = cs.list_objects()
        tool = StructuredTool.from_function(coroutine=tools(ws, "writer", model)["process_report_content"])
        with pytest.raises(ValidationError):
            await tool.ainvoke({"operation_id": "wrong-namespace", "objective": "Extract supplied evidence", "object_type": "Evidence", "observation_refs": [reference]})
        assert not model.calls
        assert cs.list_objects() == before
