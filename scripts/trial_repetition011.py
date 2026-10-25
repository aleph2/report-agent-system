"""Real-agent local probe: identical successful tool observations, then free choice."""
import argparse
import asyncio
from pathlib import Path
from unittest.mock import patch

from langchain_core.messages import AIMessage, ToolMessage

import trial_working_state010 as working
from run_deepagents_trial import load_service_environment


async def main(args):
    load_service_environment(args.credential_container)
    manifest, payload = working.fixture(False)
    action, result = payload["messages"][-2:]
    for index in range(2):
        identity = f"fixture-repeat-{index}"
        payload["messages"] += [
            AIMessage(content="", tool_calls=[{**action.tool_calls[0], "id": identity}]),
            ToolMessage(content=result.content, name="calculate", tool_call_id=identity, status="success")]
    with patch.object(working, "fixture", return_value=(manifest, payload)):
        result = await working.probe(args.root, "candidate", False)
    print({"draft_saved": result["stop_reason"] == "draft_saved",
           "new_calculations": sum(c["tool"] == "calculate" for c in result["calls"])})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--credential-container", default="hunan-highway-trial067-api-1")
    asyncio.run(main(parser.parse_args()))
