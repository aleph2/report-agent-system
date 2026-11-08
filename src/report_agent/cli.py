from . import legacy_state as legacy
import argparse
import asyncio
import json
import sys
from pathlib import Path

from .store import Store
from .workspace import Workspace

FRESH_NATIVE_DEFAULTS = {
    'review_interface_profile': 'review-interfaces-v4',
    'delegation_prompt_profile': 'separate-description-v1',
    'operation_identity_profile': 'native-tool-runtime-v1',
    'content_input_profile': 'relation-endpoints-v2',
    'report_expression_profile': 'reader-expression-v2',
    'report_prompt_profile': 'concise-v1',
    'context_policy': 'stateful-tools-v2',
    'context_projection': 'review-materials-v1',
    'review_plan_contract': 'work-units-v1',
    'review_submission_contract': 'task-scope-selectors-v1',
}


def main():
    parser = argparse.ArgumentParser(description="Independent report-agent prototype")
    parser.add_argument("command", choices=["init", "run", "status", "events", "feedback",
                                            "report-run", "report-status", "serve", "export", "import", "content-delivery", "commission-reply"])
    parser.add_argument("--project", required=True, type=Path, help="Isolated writable project directory")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--report-category", help="Host-declared report category; no title inference")
    parser.add_argument("--report-id", help="Stable host-declared report identity")
    parser.add_argument("--instruction-pack", type=Path, help="Host-managed confirmed instruction pack")
    parser.add_argument("--feedback")
    parser.add_argument("--port", type=int, default=18140)
    parser.add_argument("--draft-id")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--file", type=Path)
    parser.add_argument('--issue-id', help='Exact commission checkpoint issue from its saved request JSON')
    parser.add_argument("--replaces-id", default="")
    parser.add_argument("--decision-only", action="store_true", help="Isolated report-run: stop before substantive model-tool dispatch")
    parser.add_argument("--execution-record", action="store_true", help="export: include diagnostic execution appendices")
    args = parser.parse_args()
    store = Store(args.project)
    if args.command == "init":
        if not args.manifest:
            parser.error("init requires --manifest")
        with store.run_lock():
            manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
            existing = store.get('manifest')
            if existing is not None:
                for key in (*FRESH_NATIVE_DEFAULTS, 'content_contract', 'review_entrypoint', 'review_execution_mode'):
                    if key not in manifest and key in existing:
                        manifest[key] = existing[key]
            elif (not any(key in manifest for key in FRESH_NATIVE_DEFAULTS)
                  and manifest.get('content_contract', 'hierarchical-review-v1') == 'hierarchical-review-v1'
                  and manifest.get('review_entrypoint', 'delegated-reviewer-v1') == 'delegated-reviewer-v1'
                  and manifest.get('review_execution_mode', 'native-reviewer-v2') == 'native-reviewer-v2'):
                manifest.update(FRESH_NATIVE_DEFAULTS)
            if args.report_category:
                manifest['report_category'] = args.report_category
            if args.report_id:
                manifest['report_id'] = args.report_id
            if args.instruction_pack:
                manifest['operator_instruction_pack'] = str(args.instruction_pack.resolve())
            if manifest.get('report_category') or manifest.get('operator_instruction_pack'):
                manifest.setdefault('context_policy', 'stateful-tools-v1')
            manifest.setdefault("content_contract", "hierarchical-review-v1")
            manifest.setdefault("review_entrypoint", "delegated-reviewer-v1")
            if existing is None:
                manifest.setdefault("review_execution_mode", "native-reviewer-v2")
            if manifest['content_contract']=='hierarchical-review-v1':
                manifest.setdefault('context_policy','stateful-tools-v1')
                manifest.setdefault('decision_data_policy','reference-data-v1')
            from .prompt_sources import (SEPARATE_DESCRIPTION, separate_description_supported,
                                         validate_delegation_profile, validate_review_interface_profile)
            if 'delegation_prompt_profile' not in manifest:
                if existing is not None and 'delegation_prompt_profile' in existing:
                    manifest['delegation_prompt_profile'] = existing['delegation_prompt_profile']
                elif existing is None and separate_description_supported(manifest):
                    manifest['delegation_prompt_profile'] = SEPARATE_DESCRIPTION
            validate_delegation_profile(manifest)
            if ('review_interface_profile' not in manifest and existing is not None
                    and 'review_interface_profile' in existing):
                manifest['review_interface_profile'] = existing['review_interface_profile']
            validate_review_interface_profile(manifest)
            from .operation_identity import validate_profile as validate_operation_profile
            from .prompt_sources import validate_content_input_profile, validate_report_expression_profile
            for key in ('operation_identity_profile', 'content_input_profile', 'report_expression_profile'):
                if key not in manifest and existing is not None and key in existing:
                    manifest[key] = existing[key]
            validate_operation_profile(manifest)
            validate_content_input_profile(manifest)
            validate_report_expression_profile(manifest)
            from .handoff_release import release
            release(manifest)
            store.initialize(manifest)
            Workspace(store).initialize()
        result = store.status()
    elif args.command == 'commission-reply':
        if not args.file or not args.issue_id:
            parser.error('commission-reply requires --issue-id and --file')
        from .commission_plan import reply
        result = reply(Workspace(store), args.issue_id, json.loads(args.file.read_text(encoding='utf-8-sig')))
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
        result = asyncio.run(run_report(Workspace(store), decision_only=args.decision_only))
    elif args.command == "report-status":
        from .knowledge_state import project_state
        result = project_state(Workspace(store))
    elif args.command == "content-delivery":
        from .content_store import ContentStore
        from .content_export import _bytes
        from .content_delivery import current_delivery
        selected = legacy.get_content_delivery(store)
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
                  "review": legacy.get_content_final_review(store), "note": "Saved document; see actual review and unresolved scope."}
    elif args.command == "export":
        from .exporting import export_docx
        if not args.draft_id:
            parser.error("export requires --draft-id")
        data = export_docx(Workspace(store), args.draft_id, include_execution_record=args.execution_record)
        output = args.output or (store.root / "exports" / (args.draft_id + ".docx"))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(data)
        result = {"path": str(output.resolve()), "draft_id": args.draft_id}
    elif args.command == "run":
        parser.error("Historical prototype execution is inactive; initialize a fresh native project and use report-run. Saved history remains readable.")
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
        if result.get('status') == 'incomplete':
            return 2
        if args.decision_only and legacy.get_decision_observation(store):
            return 0
        if result.get("execution_status") is not None and store.manifest.get("review_entrypoint") != "native-rubric-v1":
            return 0 if result["execution_status"] == "completed" and not result.get("last_error") else 2
        return 0 if result["status"] == "reviewed_draft" and not result.get("last_error") else 2
    if args.command == "run":
        if result["status"] in {"failed", "interrupted"}:
            return 1
        if result["status"] != "draft_ready" or result.get("last_error"):
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
