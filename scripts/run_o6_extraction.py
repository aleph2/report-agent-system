"""Trusted operator entry for the approved single HP02 extraction after the offline gate."""
import argparse
import asyncio
from contextlib import AsyncExitStack
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess

from report_agent.deep_models import configured_model, model_client_ownership
from report_agent.extraction_probe import SUBJECT, prepare, extract
from report_agent.model_config import load_mixed_services, bind_role_services, role_service
from report_agent.o6_budget import O6Budget, MODEL, CAMPAIGN_LIMIT, RUN_LIMIT
from report_agent.store import Store
from report_agent.token_budget import token_budget


def verify_gate(gate_path, checkout):
    gate = json.loads(gate_path.read_bytes())
    verified = subprocess.check_output(["git", "-C", str(gate_path.parent / "src-tree"),
                                        "rev-parse", "HEAD"], text=True).strip()
    revision = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
    if (verified != revision or gate["expected"] < 1 or not gate["exit_codes"]
            or any(gate["exit_codes"]) or gate["coverage_exit"]
            or any(gate[k] for k in ("failed", "missing", "unexpected", "duplicates", "collection_errors"))
            or gate["outcomes"].get("passed", 0) + gate["outcomes"].get("skipped", 0) != gate["expected"]):
        raise ValueError("O6_OFFLINE_GATE_REQUIRED")
    return verified


VERIFICATION_GRANT = Path.home() / "report-agent-m1" / "finance" / "verification-20261108"
ROUTE_DIGEST = "d0f4a4f1ccceb1d1fca126562e5ca74c56d833fad6be379ae376c86ccc4c69a5"


async def run(args):
    checkout = Path(__file__).resolve().parents[1]
    revision = verify_gate(args.gate, checkout)
    from importlib.util import find_spec
    spec = find_spec("report_agent.extraction_probe")
    if spec is None or not spec.origin or not Path(spec.origin).resolve().is_relative_to(checkout / "src"):
        raise ValueError("O6_IMPORT_CHECKOUT_MISMATCH")
    if subprocess.check_output(["git", "-C", str(checkout), "status", "--porcelain",
                                "--", "src", "scripts/run_o6_extraction.py"]).strip():
        raise ValueError("O6_UNTESTED_SOURCE_CHANGES")
    load_mixed_services(args.env)
    name, url, _ = role_service("coordinator")
    if args.grant.resolve() != VERIFICATION_GRANT or args.grant.is_symlink():
        raise ValueError("O6_CANONICAL_VERIFICATION_GRANT_REQUIRED")
    if name != MODEL or sha256(url.rstrip("/").encode()).hexdigest() != ROUTE_DIGEST:
        raise ValueError("O6_COORDINATOR_MODEL_MISMATCH")
    os.environ.update(REPORT_SDK_RETRIES="0", REPORT_CONNECT_RETRIES="0",
                      LANGSMITH_TRACING="false", LANGCHAIN_TRACING_V2="false")
    budget = O6Budget(args.grant)
    args.evidence.mkdir(mode=0o700, exist_ok=False)
    case = args.evidence / "case"
    prepare(args.library, case)
    store = Store(case)
    bind_role_services(store)
    opened = datetime.now(timezone.utc)
    public = dict(subject=SUBJECT, code=revision, gate_sha256=sha256(args.gate.read_bytes()).hexdigest(),
                  model=MODEL, start=opened.isoformat(), run_cap=RUN_LIMIT, verification_cap=CAMPAIGN_LIMIT,
                  sdk_retries=0, automatic_relaunch=False)
    record = args.evidence / "operator-result.json"
    def save(status):
        body = dict(public, status=status, elapsed_seconds=(datetime.now(timezone.utc)-opened).total_seconds(),
                    run_settled_held=budget.run_totals(), campaign=budget.snapshot())
        temp = record.with_suffix(".tmp")
        temp.write_text(json.dumps(body, indent=2))
        temp.replace(record)

    async with AsyncExitStack() as stack:
        def own(client, asynchronous):
            if asynchronous:
                stack.push_async_callback(client.aclose)
            else:
                stack.callback(client.close)
        with model_client_ownership(own):
            model = configured_model(store, "coordinator")
        if model.model_name != MODEL or model.root_async_client.max_retries != 0:
            raise ValueError("O6_EFFECTIVE_MODEL_MISMATCH")
        budget.claim_launch(case)
        save("running")
        try:
            with token_budget(budget):
                result = await extract(case, model)
            public.update(model_invocations=result["model_invocations"],
                          tool_attempts=len(result["tool_attempts"]), saved_assertions=len(result["assertions"]))
            used, held = budget.run_totals()
            if held or used <= 0 or used > RUN_LIMIT or budget.snapshot()["attempt_states"].get("bound_violation", 0):
                raise RuntimeError("O6_USAGE_RECONCILIATION_REQUIRED")
            save("coordinator_final")
        except BaseException as exc:
            public["error_type"] = type(exc).__name__
            save("interrupted")
            raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("gate", "env", "library", "grant", "evidence"):
        parser.add_argument("--" + name, type=Path, required=True)
    asyncio.run(run(parser.parse_args()))
