"""Explicit interface releases validate before persistence; legacy init stays legacy."""
import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from report_agent import deep_runtime
from report_agent.errors import ActionRejected
from test_deep_runtime import Driver
from test_task_supervision import ws, offline


PROFILES = [('operation_identity_profile', 'native-tool-runtime-v1', 'UNKNOWN_OPERATION_IDENTITY_PROFILE'),
            ('content_input_profile', 'relation-endpoints-v2', 'UNKNOWN_CONTENT_INPUT_PROFILE'),
            ('report_expression_profile', 'reader-expression-v2', 'UNKNOWN_REPORT_EXPRESSION_PROFILE')]


@pytest.mark.parametrize('key,value,error', PROFILES)
def test_cli_validates_explicit_release_before_manifest_write(ws, tmp_path, monkeypatch, key, value, error):
    from report_agent.cli import main
    before = ws.store.manifest
    supplied = {**before, key: 'unrecognized'}
    path = tmp_path / 'invalid-manifest.json'
    path.write_text(json.dumps(supplied), encoding='utf-8')
    monkeypatch.setattr('sys.argv', ['report-agent', 'init', '--project', str(ws.store.root), '--manifest', str(path)])
    with pytest.raises(ActionRejected, match=error):
        main()
    assert ws.store.manifest == before


@pytest.mark.parametrize('key,value,error', PROFILES)
def test_cli_reinit_preserves_explicit_prior_release_when_field_absent(ws, tmp_path, monkeypatch, capsys, key, value, error):
    from report_agent.cli import main
    from report_agent.store import Store
    manifest = {**ws.store.manifest, key: value}
    path = tmp_path / 'reinit-manifest.json'
    path.write_text(json.dumps(manifest), encoding='utf-8')
    root = tmp_path / 'cli-case'
    monkeypatch.setattr('sys.argv', ['report-agent', 'init', '--project', str(root), '--manifest', str(path)])
    main()
    initialized = Store(root).manifest
    path.write_text(json.dumps({k: v for k, v in initialized.items() if k != key}), encoding='utf-8')
    main()
    assert Store(root).manifest == initialized


@pytest.mark.parametrize('key,value,error', PROFILES)
def test_unknown_graph_release_rejected_before_model_factory(ws, key, value, error):
    ws.store.set('manifest', {**ws.store.manifest, key: 'unrecognized'})
    def forbidden(role):
        pytest.fail('Invalid interface must fail before model construction')
    with pytest.raises(ActionRejected, match=error):
        deep_runtime.build_agent(ws, forbidden, None)


async def test_content_input_release_is_fixed_per_graph_and_legacy_schema_stays_exact(ws, tmp_path):
    ws.store.set('manifest', {**ws.store.manifest, 'content_input_profile': 'relation-endpoints-v2'})
    driver = Driver(coordinator=[AIMessage('Schema observation only.'), AIMessage('Schema observation only.')])
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / 'two-releases.db')) as saver:
        current = deep_runtime.build_agent(ws, driver, saver)
        ws.store.set('manifest', {**ws.store.manifest, 'content_input_profile': 'content-inputs-v1'})
        legacy = deep_runtime.build_agent(ws, driver, saver)
        for graph, thread in [(current, 'current'), (legacy, 'legacy')]:
            await graph.ainvoke({'messages': [HumanMessage('Observe interfaces only.')]},
                {'configurable': {'thread_id': thread}})
    assert current.config['metadata']['report_content_input_profile'] == 'relation-endpoints-v2'
    assert legacy.config['metadata']['report_content_input_profile'] == 'content-inputs-v1'
    schemas = [next(t for t in tools if t['name'] == 'commit_objects') for tools in driver.bindings['coordinator']]
    assert 'not SourceArtifact' in json.dumps(schemas[0])
    assert 'not SourceArtifact' not in json.dumps(schemas[1])
