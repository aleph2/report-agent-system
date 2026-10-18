"""Operator CLI for scoped learning. Only authorized `reflect`/`watch` call models."""
import argparse
import asyncio
import json
from pathlib import Path

from report_agent.learning import binding, submit_feedback
from report_agent.store import Store
from report_agent.workspace import Workspace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    configure = commands.add_parser("configure")
    configure.add_argument("--library", type=Path, required=True)
    configure.add_argument("--customer", required=True)
    commands.add_parser("status")
    feedback = commands.add_parser("feedback")
    feedback.add_argument("--file", type=Path, required=True)
    release = commands.add_parser("release")
    release.add_argument("--id", required=True)
    release.add_argument("--version", type=int)
    release.add_argument("--reason", required=True)
    reflect = commands.add_parser("reflect")
    reflect.add_argument("--authorize-model-calls", action="store_true")
    reflect.add_argument("--max-steps", type=int, default=40)
    watch = commands.add_parser("watch")
    watch.add_argument("--authorize-model-calls", action="store_true")
    watch.add_argument("--max-steps", type=int, default=40)
    watch.add_argument("--max-jobs", type=int, required=True)
    retry = commands.add_parser("retry")
    retry.add_argument("--feedback-id", required=True)
    retry.add_argument("--reason", required=True)
    args = parser.parse_args()
    ws = Workspace(Store(args.project))
    ws.store.manifest  # Never silently initialize an empty report project.
    if args.command == "configure":
        if not args.customer.strip():
            parser.error("customer required")
        config = {"library_path": str(args.library.resolve()), "customer_id": args.customer}
        with ws.store.run_lock():
            old = ws.store.get("learning_config")
            if old and old != config:
                parser.error("scope is already configured; explicit migration required")
            ws.store.set("learning_config", config)
        result = config
    elif args.command == "feedback":
        result = submit_feedback(ws, **json.loads(args.file.read_text(encoding="utf-8")))
    elif args.command in {"reflect", "watch"}:
        if not args.authorize_model_calls:
            parser.error("reflect requires explicit model-call authorization")
        from report_agent.learning_worker import consume_pending, watch_feedback
        from report_agent.deep_models import configured_model
        # Explicit process environment selects the model. Never reuse historical roles.
        import os
        if not all(os.environ.get(k) for k in ("REPORT_MODEL", "REPORT_BASE_URL", "REPORT_API_KEY")):
            parser.error("explicit REPORT_MODEL/REPORT_BASE_URL/REPORT_API_KEY required")
        factory = lambda: configured_model(ws.store, "experience_optimizer")
        if args.command == "watch":
            async def watch_loop():
                return await watch_feedback(ws, factory, stop=asyncio.Event(), max_jobs=args.max_jobs,
                                            max_steps=args.max_steps)
            result = asyncio.run(watch_loop())
        else:
            result = asyncio.run(consume_pending(ws, factory, max_steps=args.max_steps))
    else:
        bound = binding(ws)
        if not bound:
            parser.error("learning not configured")
        library, scope = bound
        if args.command == "retry":
            with ws.store.run_lock():
                result = library.retry_feedback(scope, args.feedback_id, args.reason)
        else:
            result = (library.release(scope, args.id, args.version, args.reason) if args.command == "release"
                      else {"feedback": library.feedback_items(scope), "experience": library.list_versions(scope),
                            "queue": library.queue_status(scope), "job": ws.store.get("learning_job")})
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
