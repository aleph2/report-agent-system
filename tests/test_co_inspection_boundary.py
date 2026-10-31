"""Current V4 role boundary, including service bypass and legacy compatibility."""
from types import SimpleNamespace

import pytest

from report_agent.content_export import inspect_render
from report_agent.errors import ActionForbidden
from report_agent.hierarchical_tools import actor_for, content_tools, role_prompt
from report_agent.store import Store
from report_agent.workspace import Workspace
from test_task_supervision import offline


@pytest.fixture
def project(tmp_path):
    store = Store(tmp_path)
    store.initialize({'goal':'Synthetic responsibility boundary only.',
        'sources':[{'id':'synthetic','content':'Fictional input only.','coverage':'complete'}],
        'content_contract':'hierarchical-review-v1',
        'review_entrypoint':'delegated-reviewer-v1',
        'review_execution_mode':'native-reviewer-v2',
        'delegation_prompt_profile':'separate-description-v1',
        'operation_identity_profile':'native-tool-runtime-v1',
        'review_interface_profile':'review-interfaces-v4',
        'report_expression_profile':'reader-expression-v2',
        'report_prompt_profile':'concise-v1'})
    return store


def test_current_co_has_no_page_inspection_tool(project):
    names = {tool.__name__ for tool in content_tools(Workspace(project), 'coordinator')}
    assert 'inspect_rendered_page' not in names
    assert {'read_review_status', 'export_content_workbook'} <= names


@pytest.mark.parametrize('role', ['reviewer', 'layout', 'writer'])
def test_specialists_keep_existing_page_inspection_tool(project, role):
    assert 'inspect_rendered_page' in {t.__name__ for t in content_tools(Workspace(project), role)}


async def test_co_service_bypass_is_rejected_before_read_or_model(project, monkeypatch):
    def forbidden_client():
        pytest.fail('A rejected Co must not construct a visual client')
    monkeypatch.setattr('report_agent.deep_models.configured_vision_client', forbidden_client)
    def forbidden_read(ref):
        pytest.fail('Role rejection must happen before reading artifacts or invoking a model')
    contents = SimpleNamespace(store=project, read=forbidden_read)
    with pytest.raises(ActionForbidden, match='coordinator'):
        await inspect_render(contents, actor_for('coordinator'),
            {'type':'RenderArtifact','id':'fake-render','version':1}, 1, 'Inspect')


@pytest.mark.parametrize('role,legacy', [('reviewer',False), ('layout',False), ('writer',False), ('coordinator',True)])
async def test_allowed_roles_reach_existing_artifact_validation(project, role, legacy):
    if legacy:
        manifest = project.get('manifest')
        manifest.pop('review_interface_profile', None)
        manifest.pop('report_prompt_profile', None)
        project.set('manifest', manifest)
    class ArtifactValidationReached(Exception):
        pass
    def read(ref):
        raise ArtifactValidationReached
    with pytest.raises(ArtifactValidationReached):
        await inspect_render(SimpleNamespace(store=project, read=read), actor_for(role),
            {'type':'RenderArtifact','id':'fake-render','version':1}, 1, 'Inspect', client=object())


@pytest.mark.parametrize('text_profile', ['concise-v1', 'legacy-v1'])
def test_current_co_prompt_delegates_visual_checking(text_profile):
    from report_agent.prompt_sources import load_prompt, role_sources
    prompt = role_prompt('coordinator', expression_profile='reader-expression-v2',
        interface_profile='review-interfaces-v4', prompt_profile=text_profile)
    assert role_sources('coordinator', 'reader-expression-v2', 'review-interfaces-v4', text_profile) == ['agent-common', 'agent-coordinator']
    assert prompt == '\n\n'.join(t for t in [load_prompt('agent-common'), load_prompt('agent-coordinator')] if t.strip())
    assert 'You own resolution of delivery-format feedback.' not in prompt
    assert 'You remain responsible for resolving delivery-format feedback.' not in prompt


async def test_bound_v4_co_cannot_bypass_by_changing_store_profile(project):
    from langchain_core.runnables.config import var_child_runnable_config
    from report_agent.handoff_release import release
    bound = release(project.manifest)
    project.set('manifest', {**project.manifest, 'review_interface_profile':'review-interfaces-v1',
        'report_prompt_profile':'legacy-v1'})
    def read(ref):
        pytest.fail('Bound V4 role rejection must precede artifact read')
    token = var_child_runnable_config.set({'metadata':{'report_handoff_release':bound}})
    try:
        with pytest.raises(ActionForbidden, match='coordinator'):
            await inspect_render(SimpleNamespace(store=project, read=read), actor_for('coordinator'),
                {'type':'RenderArtifact','id':'fake-render','version':1}, 1, 'Inspect', client=object())
    finally:
        var_child_runnable_config.reset(token)


@pytest.mark.parametrize('interface', ['review-interfaces-v1', 'review-interfaces-v2', 'review-interfaces-v3', 'review-interfaces-v4'])
def test_workbook_help_preserves_legacy_contract_and_current_source_trace(project, interface):
    from report_agent.prompt_sources import load_prompt, source_manifest
    project.set('manifest', {**project.manifest, 'review_interface_profile':interface,
        'report_prompt_profile':'legacy-v1'})
    tools = {t.__name__:t for t in content_tools(Workspace(project), 'coordinator')}
    help_text = tools['export_content_workbook'].__doc__
    if interface != 'review-interfaces-v4':
        assert 'Read/render/review the saved export' in help_text
        assert 'inspect_rendered_page' in tools
    else:
        assert help_text == load_prompt('export-content-workbook-v4')
        assert 'Read/render/review' not in help_text
        observed = source_manifest(project, ['export-content-workbook-v4'], {'messages':[],
            'tools':[{'type':'function','function':{'name':'export_content_workbook',
                'description':help_text}}]})
        assert observed['unresolved_sources'] == []
        assert observed['files'][0]['offered_match'] != 'not_observed'
