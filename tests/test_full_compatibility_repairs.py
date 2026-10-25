"""Keep legacy call instrumentation and strict explicit-selection validation."""
import pytest

from report_agent.content_store import ContentStore
from report_agent.content_tasks import delegated_task
from report_agent.errors import ActionRejected
from report_agent.hierarchical_tools import content_tools
from report_agent.workspace import Workspace
from test_deliverable_declaration_v4 import case, node


def writer_call():
    return {'name': 'task', 'id': 'compat-writer', 'args': {
        'subagent_type': 'writer', 'description': 'Save one structural fixture node.'}}


@pytest.mark.parametrize('tool', ['commit_objects', 'save_text_node'])
def test_omitted_selection_preserves_four_argument_commit_call(case, monkeypatch, tool):
    cs = case[0]
    workspace = Workspace(cs.store)
    original, calls = ContentStore.commit, []
    def legacy_commit(self, actor, operation_id, objects):
        calls.append(operation_id)
        return original(self, actor, operation_id, objects)
    monkeypatch.setattr(ContentStore, 'commit', legacy_commit)
    with delegated_task(workspace, 'coordinator', writer_call()):
        functions = {f.__name__: f for f in content_tools(workspace, 'writer')}
        if tool == 'commit_objects':
            result = functions[tool]('compat-save', [node('section', 'chapter')])
        else:
            result = functions[tool]('compat-save', 'Synthetic section', 'chapter', 'structure', '')
        assert result['ok'] and calls == ['compat-save']


def test_empty_explicit_selection_still_reaches_validation(case, monkeypatch):
    cs = case[0]
    workspace = Workspace(cs.store)
    original, seen = ContentStore.commit, []
    def inspect_selection(self, actor, operation_id, objects, **kwargs):
        seen.append(kwargs)
        return original(self, actor, operation_id, objects, **kwargs)
    monkeypatch.setattr(ContentStore, 'commit', inspect_selection)
    with delegated_task(workspace, 'coordinator', writer_call()):
        functions = {f.__name__: f for f in content_tools(workspace, 'writer')}
        before = cs.list_objects('ContentNode')
        with pytest.raises(ActionRejected):
            functions['commit_objects']('invalid-selection', [node('section', 'chapter')],
                deliverable_selection={})
        assert seen == [{'deliverable_selection': {}}]
        assert cs.list_objects('ContentNode') == before


def test_history_only_context_defers_tools_but_offered_v3_help_is_fixed(case, monkeypatch):
    from report_agent.task_context import TaskContext
    from report_agent.prompt_sources import load_prompt
    cs = case[0]
    cs.store.set('context_policy', 'stateful-tools-v1')
    cs.store.set('manifest', {**cs.store.manifest, 'review_interface_profile': 'review-interfaces-v3'})
    reads, original = [], cs.store.get
    def observed(key, *args, **kwargs):
        if key == 'manifest':
            reads.append(key)
        return original(key, *args, **kwargs)
    monkeypatch.setattr(cs.store, 'get', observed)
    context = TaskContext(Workspace(cs.store), 'coordinator')
    assert reads == []
    tools = context.tools
    assert reads == ['manifest']
    state = next(t for t in tools if t.__name__ == 'read_decision_state')
    assert state.__doc__ == load_prompt('state-paths-v3')
    assert context.tools is tools and reads == ['manifest']
    cs.store.set('manifest', {**cs.store.manifest, 'review_interface_profile': 'review-interfaces-v4'})
    assert context.tools is tools and state.__doc__ == load_prompt('state-paths-v3')
