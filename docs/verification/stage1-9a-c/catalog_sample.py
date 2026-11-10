from test_fake03_qualitative_steps import mini

def test_capture_current_catalogs(mini):
    from report_agent.deep_runtime import business_tools
    from langchain_core.tools import StructuredTool
    ws, _, _ = mini
    ws.store.set('manifest', {**ws.store.manifest, 'operation_identity_profile':'native-tool-runtime-v1'})
    for role in ('coordinator', 'writer', 'reviewer', 'layout', 'rubric_grader'):
        tools = business_tools(ws, role, None, None)
        assert tools, role
        for fn in tools:
            sdk = fn if isinstance(fn, StructuredTool) else StructuredTool.from_function(fn)
            assert sdk.tool_call_schema.model_json_schema()['type'] == 'object'
