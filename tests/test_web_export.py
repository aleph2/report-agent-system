from io import BytesIO

from docx import Document
from fastapi.testclient import TestClient

from report_agent.exporting import export_docx
from report_agent.webapp import create_app
from test_report_trunk import ModelFactory, baseline, save, workspace


def test_export_saved_version_without_execution(tmp_path):
    ws = workspace(tmp_path)
    ws.store.set("model_mode", "scripted_fixture")
    draft = baseline(ws)
    before = ws.tasks()
    doc = Document(BytesIO(export_docx(ws, draft["id"])))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "Unreviewed draft" in text
    assert "SYNTHETIC PROTOCOL FIXTURE" in text
    assert draft["id"] in text and "[access]" in text
    assert before == ws.tasks()
    review = save(ws, "review", [draft["id"]], outcome="accepted", target_id=draft["id"])
    text = "\n".join(p.text for p in Document(BytesIO(export_docx(ws, draft["id"]))).paragraphs)
    assert review["id"] in text and "Model-reviewed draft" in text


def test_desktop_api_read_only_poll_export_and_local_actions(tmp_path):
    ws = workspace(tmp_path)
    ws.store.set("model_mode", "scripted_fixture")
    draft = baseline(ws)
    ws.select_delivery(draft["id"], "")
    issue = ws.issue("source_missing", "Missing date", ["access"])
    ws.store.event("model_request", {"contents": "PRIVATE_PROMPT", "key": "PRIVATE_KEY"})
    before = ws.tasks()
    with TestClient(create_app(tmp_path)) as client:
        assert client.get("/").status_code == 200
        status = client.get("/api/status")
        assert "PRIVATE_" not in status.text
        assert not status.json()["can_run"]
        assert status.json()["delivery"]["status"] == "needs_human"
        assert client.get("/api/export/" + draft["id"]).content[:2] == b"PK"
        assert client.get("/api/export/unknown").status_code == 404
        assert client.post("/api/run", json={}).status_code == 403
        assert client.post("/api/run", json={}, headers={"X-Report-Action": "1"}).status_code == 409
        path = "/api/issues/" + issue["id"] + "/decision"
        assert client.post(path, json={"message": "Keep gap explicit"}, headers={
            "X-Report-Action": "1", "Origin": "https://foreign.invalid"}).status_code == 403
        result = client.post(path, json={"message": "Keep gap explicit"}, headers={"X-Report-Action": "1"})
        assert result.status_code == 200
        assert result.json()["resolved"] is False
        assert client.get("/", headers={"Host": "foreign.invalid"}).status_code == 400
    assert ws.tasks() == before


def test_event_tail_does_not_load_historical_payloads(tmp_path):
    ws = workspace(tmp_path)
    for number in range(105):
        ws.store.event("test", {"number": number})
    events = ws.store.events(limit=3)
    assert [e["data"]["number"] for e in events] == [102, 103, 104]


def test_stopped_cli_worker_is_visible_and_can_resume(tmp_path, monkeypatch):
    ws = workspace(tmp_path)
    for key in ("REPORT_MODEL", "REPORT_BASE_URL", "REPORT_API_KEY"):
        monkeypatch.setenv(key, "configured-test-only")
    ws.store.set("report_status", "running")
    ws.store.set("checkpoint_resume", True)
    with TestClient(create_app(tmp_path)) as client:
        with ws.store.run_lock():
            busy = client.get("/api/status").json()
            assert busy["status"] == "running"
            assert not busy["can_run"]
        stopped = client.get("/api/status").json()
        assert stopped["status"] == "interrupted"
        assert stopped["can_run"] and stopped["checkpoint_resume"]
        assert stopped["last_error"]["message"] == "WORKER_STOPPED_RESUME_AVAILABLE"
    assert ws.store.get("report_status") == "running"  # Polling only projects state.


def test_http_explicit_run_and_busy_project_protection(tmp_path, monkeypatch):
    import time
    from test_deep_runtime import trunk_driver
    monkeypatch.setattr("report_agent.deep_runtime.load_rules", lambda: "")

    ws = workspace(tmp_path)
    ws.store.set("model_mode", "scripted_fixture")
    factory = trunk_driver("access")
    with TestClient(create_app(tmp_path, factory, allow_fixture_run=True)) as client:
        assert not factory.created
        headers = {"X-Report-Action": "1"}
        with ws.store.run_lock():
            assert client.post("/api/run", json={}, headers=headers).status_code == 409
        assert not factory.created
        assert client.post("/api/run", json={}, headers=headers).status_code == 202
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            status = client.get("/api/status").json()
            if status["status"] == "reviewed_draft" and status["can_run"]:
                break
            time.sleep(0.01)
        assert status["status"] == "reviewed_draft"
        assert len(status["tasks"]) == 2
        assert factory.created
