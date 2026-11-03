"""Public export adapters preserve caller choices; no renderer/provider execution."""
import pytest
from langchain_core.tools import StructuredTool

from report_agent.hierarchical_tools import content_tools
from report_agent.store import Store
from report_agent.workspace import Workspace


@pytest.mark.parametrize('interface', ['review-interfaces-v1', 'review-interfaces-v4'])
@pytest.mark.parametrize('layout', [
    None,
    {'refresh_toc': True},
    {'refresh_toc': True, 'toc_depth': 2, 'right_margin_mm': None,
     'line_spacing': 1.3},
])
def test_native_export_forwards_only_explicit_layout_choices(tmp_path, monkeypatch,
                                                            interface, layout):
    from report_agent import content_export
    from report_agent.prompt_sources import NATIVE_REVIEW, SEPARATE_DESCRIPTION

    store = Store(tmp_path)
    store.initialize({'goal': 'Export the selected immutable report.',
        'content_contract': 'hierarchical-review-v1',
        'sources': [{'id': 'scope', 'title': 'Scope', 'content': 'Export report.',
                     'coverage': 'complete'}],
        'review_entrypoint': 'delegated-reviewer-v1',
        'review_execution_mode': NATIVE_REVIEW,
        'review_interface_profile': interface,
        'delegation_prompt_profile': SEPARATE_DESCRIPTION,
        'operation_identity_profile': 'native-tool-runtime-v1'})
    calls = []

    def capture(contents, actor, operation_id, snapshot_ref, raw_layout, reuse_ref,
                **kwargs):
        calls.append((operation_id, snapshot_ref, raw_layout, reuse_ref))
        return {'ok': True}

    monkeypatch.setattr(content_export, 'export_snapshot', capture)
    function = next(t for t in content_tools(Workspace(store), 'coordinator')
                    if t.__name__ == 'export_content_snapshot')
    tool = StructuredTool.from_function(function)
    snapshot = {'type': 'DocumentSnapshot', 'id': 'snapshot', 'version': 1}
    arguments = {'operation_id': 'export-test', 'snapshot_ref': snapshot}
    if layout is not None:
        arguments['layout'] = layout

    assert tool.invoke(arguments) == {'ok': True}
    assert calls == [('export-test', snapshot, layout, None)]
