import sqlite3

import pytest
from fastapi.testclient import TestClient

from report_agent.catalog import Catalog
from report_agent.report_runtime import library_tools
from report_agent.webapp import create_app
from test_report_trunk import workspace


def test_import_version_receipt_and_located_paging(tmp_path):
    ws = workspace(tmp_path)
    cat = Catalog(ws.store)
    text = 'Synthetic material ' * 700
    one = cat.import_file('notes.txt', text.encode())
    sid = one['source']['id']
    assert cat.import_file('notes.txt', text.encode())['source']['id'] == sid
    page = cat.read(sid, limit=1)
    assert page['next_offset'] == 1 and page['total_blocks'] > 1
    chunks = []
    offset = 0
    while offset is not None:
        page = cat.read(sid, offset, 1)
        chunks += [b['text'] for b in page['blocks']]
        offset = page['next_offset']
    assert ''.join(chunks) == text
    two = cat.import_file('notes.txt', b'Updated synthetic material', sid)
    assert ws.store.sources([sid])[0]['content'] == text
    assert ws.store.superseded_sources()[sid] == two['source']['id']
    assert cat.import_file('notes.txt', b'Updated synthetic material', sid)['reused']
    with pytest.raises(ValueError, match='CURRENT_SOURCE'):
        cat.import_file('notes.txt', b'A conflicting update', sid)
    assert len(ws.store.get('source_changes')) == 2
    with ws.store.connect() as db:
        assert db.execute('SELECT original FROM source_versions WHERE id=?', (sid,)).fetchone()[0] == text.encode()


def test_literal_search_versions_paging_and_partial_observations(tmp_path):
    ws = workspace(tmp_path)
    cat = Catalog(ws.store)
    old = cat.import_file('one.md', ('alpha ' * 1700).encode())['source']['id']
    page = cat.search('alpha', limit=1)
    assert page['total'] == 3 and page['next_offset'] == 1
    task = ws.request_task('materials', 'Read selected text', [])
    tools = {t.__name__: t for t in library_tools(ws, task['id'])}
    tools['read_source_page'](old, limit=1)
    observation = ws.store.events()[-1]
    assert observation['data']['extent'] == 'page' and observation['data']['ordinals'] == [0]
    assert observation['data']['next_offset'] == 1
    new = cat.import_file('one.md', b'beta', old)['source']['id']
    assert not cat.search('alpha')['matches']
    assert cat.search('alpha', include_history=True)['matches']
    assert cat.search('beta')['matches'][0]['source_id'] == new
    assert 'No match' in cat.search('synonym')['coverage_note']
    with pytest.raises(ValueError):
        cat.read(new, -1)


def test_import_is_atomic_and_locked(tmp_path):
    ws = workspace(tmp_path)
    cat = Catalog(ws.store)
    before = cat.metadata()
    with ws.store.run_lock(), pytest.raises(RuntimeError, match='ALREADY_RUNNING'):
        cat.import_file('one.txt', b'Synthetic')
    with ws.store.connect() as db:
        db.execute("""CREATE TRIGGER import_failure BEFORE INSERT ON events
                      WHEN NEW.kind='source_imported' BEGIN SELECT RAISE(ABORT, 'simulated'); END""")
    with pytest.raises(sqlite3.IntegrityError, match='simulated'):
        cat.import_file('one.txt', b'Synthetic')
    assert cat.metadata() == before and not ws.store.get('source_changes')
    with ws.store.connect() as db:
        assert db.execute('SELECT count(*) FROM source_versions').fetchone()[0] == 0


def test_http_upload_read_search_no_model_and_reject_paths(tmp_path, monkeypatch):
    ws = workspace(tmp_path)
    with TestClient(create_app(tmp_path)) as client:
        path = '/api/sources?filename=notes.txt'
        assert client.post(path, content=b'Example').status_code == 403
        headers = {'X-Report-Action': '1'}
        response = client.post(path, content=b'Synthetic searchable sample', headers=headers)
        assert response.status_code == 200
        sid = response.json()['source']['id']
        assert client.get(f'/api/sources/{sid}').json()['blocks'][0]['text'] == 'Synthetic searchable sample'
        assert client.get('/api/library/search?q=searchable').json()['matches'][0]['source_id'] == sid
        assert client.post('/api/sources?filename=../bad.txt', content=b'Text', headers=headers).status_code == 409
        monkeypatch.setattr('report_agent.ingestion.MAX_UPLOAD_BYTES', 5)
        assert client.post(path, content=b'Too large', headers=headers).status_code == 413
        assert not ws.tasks()
        assert not any(e['kind'] == 'model_request' for e in ws.store.events())


async def test_completed_but_outdated_task_cannot_be_reported_as_reused(tmp_path):
    # Explicit retired execute_task migration: old committed content remains
    # readable, but stale source-version bindings cannot be reused as current work.
    from copy import deepcopy
    import json
    from langchain_core.messages import AIMessage
    from report_agent import deep_runtime
    from report_agent.store import Store
    from report_agent.workspace import Workspace
    from report_agent.content_store import ContentStore
    from test_deep_runtime import Driver, call, invoke, observation
    store = Store(tmp_path)
    store.initialize({"goal": "Compile the selected current source version.",
        "content_contract": "hierarchical-review-v1", "review_entrypoint": "delegated-reviewer-v1",
        "sources": [{"id": "s", "title": "Access", "content": "Daytime access only.", "coverage": "complete"}]})
    current, cs = Workspace(store), ContentStore(store)
    public = {}
    body = {"kind": "block", "body": {"text": "Daytime access only."}, "qualifiers": {}, "claim_kind": "fact"}
    def first_task(messages):
        public["old_source"] = observation(messages, "import_source_versions")["result"]["source_refs"][0]
        return AIMessage(content="", tool_calls=[call("task", {"subagent_type": "writer",
            "description": json.dumps({"goal": "Compile this selected source.", "input_ref": public["old_source"]})},
            "catalog-original-writer")])
    def produce(messages):
        assert public["old_source"]["id"] in json.dumps([m.content for m in messages])
        return invoke("process_report_content", operation_id="catalog-original-work", objective="Compile selected access restriction.",
            object_type="ContentNode", input_refs=[public["old_source"]], source_selections=[{"source_id": "s"}])
    def adopt(messages):
        work = observation(messages, "process_report_content")
        public["text_work_id"] = work["text_work_id"]
        return invoke("commit_objects", operation_id="catalog-original-adoption", objects=[{
            "client_key": "body", "type": "ContentNode", "text_work_id": work["text_work_id"]}])
    def writer_return(messages):
        return AIMessage(content=json.dumps({"node_ref": observation(messages, "commit_objects")["result"]["refs"]["body"],
                                            "text_work_id": public["text_work_id"]}))
    def finish_first(messages):
        public["node_ref"] = observation(messages, "task")["node_ref"]
        return AIMessage(content="Saved original source-bound draft only.")
    first_driver = Driver(coordinator=[invoke("import_source_versions", operation_id="catalog-original-inputs", source_ids=["s"]),
        first_task, finish_first], writer=[produce, adopt, writer_return], text_tool=[AIMessage(content=json.dumps(body))])
    first = await deep_runtime.run_report(current, first_driver)
    assert first["last_error"] is None, first
    assert sum(role == "text_tool" for role, _, _ in first_driver.calls) == 1
    old_node, old_source = deepcopy(cs.read(public["node_ref"])), deepcopy(cs.read(public["old_source"]))
    old_receipt = deepcopy(store.get("text_work_receipt:" + public["text_work_id"]))
    old_blocks = Catalog(store).read("s", 0, 10)["blocks"]
    assert old_node["payload"] == body and old_node["owner_id"].startswith("content:writer:")
    changed = Catalog(store).import_file("access.txt", b"Nighttime access only.", replaces_id="s")
    new_id = changed["source"]["id"]
    catalog = {x["id"]: x for x in Catalog(store).sources()}
    assert catalog["s"]["current"] is False and catalog[new_id]["current"] is True
    assert catalog["s"]["content"] == "Daytime access only."
    def stale_produce(messages):
        transcript = json.dumps([m.content for m in messages])
        assert public["old_source"]["id"] in transcript and public["node_ref"]["id"] in transcript
        return invoke("process_report_content", operation_id="catalog-stale-work", objective="Reuse only if selected source bindings are current.",
            object_type="ContentNode", input_refs=[public["node_ref"], public["old_source"]],
            source_selections=[{"source_id": "s"}])
    def rejected(messages):
        value = observation(messages, "process_report_content")
        assert value["ok"] is False and value["code"] == "TEXT_WORK_SOURCE_VERSION_NOT_CURRENT_FOR_SELECTION"
        assert not value.get("reused")
        return AIMessage(content="Stale source binding rejected; no replacement content or successful reuse claimed.")
    offset = max(step for role, step, _ in first_driver.calls if role == "coordinator") + 1
    second_driver = Driver(coordinator=[None] * offset + [AIMessage(content="", tool_calls=[call("task", {
        "subagent_type": "writer", "description": json.dumps({"goal": "Check currentness before new text work.",
        "old_source_ref": public["old_source"], "old_content_ref": public["node_ref"]})}, "catalog-stale-writer")]),
        AIMessage(content="Original draft preserved as historical; no current delivery selected.")],
        writer=[stale_produce, rejected])
    second = await deep_runtime.run_report(Workspace(Store(store.root)), second_driver)
    assert second["last_error"] is None, second
    assert not any(role == "text_tool" for role, _, _ in second_driver.calls)
    assert len(cs.list_objects("ContentNode")) == 1 and not cs.list_objects("ReviewRecord")
    assert cs.read(public["node_ref"]) == old_node and cs.read(public["old_source"]) == old_source
    assert store.get("text_work_receipt:" + public["text_work_id"]) == old_receipt
    assert Catalog(store).read("s", 0, 10)["blocks"] == old_blocks
    assert second["status"] != "reviewed_draft" and not store.get("content_delivery")


def test_result_search_is_metadata_and_paged_read_is_observed(tmp_path):
    ws = workspace(tmp_path)
    result = ws.results()[0]
    task = ws.request_task('plan', 'Search supplied basis', [])
    tools = {t.__name__: t for t in library_tools(ws, task['id'])}
    page = tools['search_results'](result['title'])
    assert page['matches'][0]['id'] == result['id']
    assert 'body' not in page['matches'][0]
    assert not ws.task(task['id'])['used_result_ids']
    read = tools['read_result_page'](result['id'], characters=5)
    assert len(read['text']) == 5 and read['next_offset'] == 5
    assert ws.task(task['id'])['used_result_ids'] == [result['id']]


def test_search_across_artificial_chunk_boundary(tmp_path):
    ws = workspace(tmp_path)
    cat = Catalog(ws.store)
    source = cat.import_file('boundary.txt', ('x' * 3997 + 'BoundaryNeedle' + 'y' * 100).encode())['source']['id']
    result = cat.search('boundaryneedle')
    assert result['total'] == 1
    assert result['matches'][0]['source_id'] == source
    assert result['matches'][0]['ordinals'] == [0, 1]
    assert 'BoundaryNeedle' in result['matches'][0]['text']
