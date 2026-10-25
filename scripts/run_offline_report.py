"""Exercise actual ADK tool dispatch with a scripted fixture, never provider credentials."""
import argparse
import asyncio
import json
import runpy
from pathlib import Path

from report_agent.exporting import export_docx
from report_agent.report_runtime import run_report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--attention", action="store_true", help="Produce an isolated failure and human-issue UI fixture")
    args = parser.parse_args()
    fixtures = runpy.run_path(str(Path(__file__).resolve().parents[1] / "tests/test_report_trunk.py"))
    ws = fixtures["workspace"](args.project)
    ws.store.set("model_mode", "scripted_fixture")
    if args.attention:
        factory = fixtures["ModelFactory"](ws, ["request_plan", "run_last", "request_draft", "run_last", "final"], fail_draft=True)
        status = asyncio.run(run_report(ws, factory))
        assert status["tasks"][-1]["status"] == "failed"
        ws.issue("source_missing", "SYNTHETIC UI CHECK: confirm the scope date. <img src=x onerror=alert(1)>", ["access"])
        print(json.dumps({"mode": "scripted_fixture", "status": status["status"], "project": str(args.project)}))
        return
    status = asyncio.run(run_report(ws, fixtures["ModelFactory"](ws)))
    if status["status"] != "reviewed_draft":
        raise RuntimeError("OFFLINE_TRUNK_FAILED")
    output = args.project / "protocol-fixture.docx"
    output.write_bytes(export_docx(ws, status["delivery"]["draft_id"]))
    print(json.dumps({"mode": "scripted_fixture", "status": status["status"],
                      "tasks": len(status["tasks"]), "docx": str(output)}, indent=2))


if __name__ == "__main__":
    main()
