"""Read-only compact audit; no prompts, engineering text or credentials printed."""
import argparse
import json
import sqlite3
from pathlib import Path


def audit(root):
    db = sqlite3.connect(f"file:{(root / 'state.db').resolve()}?mode=ro", uri=True)
    state = {key: json.loads(value) for key, value in db.execute("SELECT key,value FROM state")}
    counts = dict(db.execute("SELECT kind,count(*) FROM events GROUP BY kind"))
    requests, responses, totals, missing = {}, set(), {}, 0
    rejected = {}
    for kind, value in db.execute("SELECT kind,data FROM events WHERE kind IN ('deep_model_request','deep_model_response','deep_model_error') ORDER BY sequence"):
        event = json.loads(value)
        if kind == "deep_model_request":
            requests[event["run_id"]] = event["role"]
            for batch in event["messages"]:
                for message in batch:
                    if message.get("type") != "tool" or not isinstance(message.get("content"), str):
                        continue
                    try:
                        payload = json.loads(message["content"])
                    except (ValueError, TypeError):
                        continue
                    if isinstance(payload, dict) and payload.get("accepted") is False:
                        rejected[message.get("tool_call_id", "unknown")] = payload.get("error")
        else:
            responses.add(event["run_id"])
            if kind == "deep_model_response":
                usage = event.get("usage")
                if usage is None:
                    missing += 1
                else:
                    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                        if isinstance(usage.get(key), int):
                            totals[key] = totals.get(key, 0) + usage[key]
    tools = []
    for at, value in db.execute("SELECT at,data FROM events WHERE kind='deep_tool_start' ORDER BY sequence DESC LIMIT 15"):
        event = json.loads(value)
        tools.append({"at": at, "role": event["role"], "tool": event["tool"]})
    result = {"project": str(root), "runtime": state.get("runtime"), "status": state.get("report_status"),
              "activity": state.get("report_activity"), "error": state.get("report_error"),
              "delivery": state.get("delivery"), "checkpoint_resume": state.get("checkpoint_resume"),
              "events": counts, "unsettled_request_roles": [role for key, role in requests.items() if key not in responses],
              "inflight_not_established": "Unsettled requests do not prove a live process; interrupted requests may lack final usage.",
              "usage": totals, "responses_without_usage": missing, "recent_tools": list(reversed(tools))}
    result["rejected_actions"] = list(rejected.values())
    submissions = []
    for value, in db.execute("SELECT data FROM events WHERE kind='deep_tool_start' ORDER BY sequence"):
        event = json.loads(value)
        if event["tool"] == "submit_result":
            args = event["arguments"]
            submissions.append({"role": event["role"], "kind": args.get("kind"),
                                "outcome": args.get("outcome"), "target_id": args.get("target_id"),
                                "source_ids": args.get("source_ids"), "body_characters": len(args.get("body", ""))})
    result["submissions"] = submissions[-8:]
    # Legacy transcript metrics remain historical evidence; normal runs now
    # retain messages in LangGraph, not a duplicate events table transcript.
    result["transcript_metrics_scope"] = "historical_local_audit_events_only"
    if state.get("native_trace_thread_id"):
        from report_agent.native_trace import recent_tool_events
        result["recent_tools"] = recent_tool_events(root.resolve(), state["native_trace_thread_id"])
        result["recent_tools_source"] = "native_checkpoint_bounded_recent_page"
    db.close()
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path)
    print(json.dumps(audit(parser.parse_args().project), ensure_ascii=False, indent=2))
