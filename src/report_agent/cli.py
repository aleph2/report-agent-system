import argparse
import asyncio
import json
import sys
from pathlib import Path

from .store import Store
from .workspace import Workspace


def main():
    parser = argparse.ArgumentParser(description="Independent report-agent prototype")
    parser.add_argument("command", choices=["init", "run", "status", "events", "feedback",
                                            "report-run", "report-status", "serve", "export", "import", "content-delivery"])
    parser.add_argument("--project", required=True, type=Path, help="Isolated writable project directory")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--feedback")
    parser.add_argument("--port", type=int, default=18140)
    parser.add_argument("--draft-id")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--file", type=Path)
    parser.add_argument("--replaces-id", default="")
    args = parser.parse_args()
    store = Store(args.project)
    if args.command == "init":
        if not args.manifest:
            parser.error("init requires --manifest")
        with store.run_lock():
            store.initialize(json.loads(args.manifest.read_text(encoding="utf-8")))
            Workspace(store).initialize()
        result = store.status()
    elif args.command == "import":
        from .catalog import Catalog
        from .ingestion import MAX_UPLOAD_BYTES
        if not args.file:
            parser.error("import requires --file")
        with args.file.open("rb") as handle:
            data = handle.read(MAX_UPLOAD_BYTES + 1)
        result = Catalog(store).import_file(args.file.name, data, args.replaces_id)
    elif args.command == "serve":
        import uvicorn
        from .webapp import create_app
        store.manifest
        uvicorn.run(create_app(args.project), host="127.0.0.1", port=args.port)
        return 0
    elif args.command == "report-run":
        from .deep_runtime import run_report
        result = asyncio.run(run_report(Workspace(store)))
    elif args.command == "report-status":
        from .knowledge_state import project_state
        result = project_state(Workspace(store))
    elif args.command == "content-delivery":
        from .content_store import ContentStore
        from .content_export import _bytes
        from .content_delivery import current_delivery
        selected = store.get("content_delivery")
        if not selected:
            parser.error("No versioned content delivery has been selected")
        artifact = ContentStore(store).read(selected["export_ref"])["payload"]
        data = _bytes(store, artifact["file_ref"], artifact["file_digest"])
        path = args.output or (store.root / artifact["file_ref"])
        if args.output:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        result = {"path": str(path.resolve()), "delivery": selected,
                  "current_review": current_delivery(store),
                  "review": store.get("content_final_review"), "note": "Saved document; see actual review and unresolved scope."}
    elif args.command == "export":
        from .exporting import export_docx
        if not args.draft_id:
            parser.error("export requires --draft-id")
        data = export_docx(Workspace(store), args.draft_id)
        output = args.output or (store.root / "exports" / (args.draft_id + ".docx"))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(data)
        result = {"path": str(output.resolve()), "draft_id": args.draft_id}
    elif args.command == "run":
        from .runtime import run_task  # Historical prototype command, not the report runtime.
        result = asyncio.run(run_task(store))
    elif args.command == "events":
        result = store.events()
    elif args.command == "feedback":
        if not args.feedback:
            parser.error("feedback requires --feedback")
        store.add_feedback(args.feedback)
        result = store.status()
    else:
        result = store.status()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.command == "report-run":
        return 0 if result["status"] == "reviewed_draft" and not result.get("last_error") else 2
    if args.command == "run":
        if result["status"] in {"failed", "interrupted"}:
            return 1
        if result["status"] != "draft_ready" or result.get("last_error"):
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
