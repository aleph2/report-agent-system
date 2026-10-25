"""Serial real-graph/local-model smoke test, using only synthetic engineering text.

Run: python scripts/check_knowledge.py [--text-only] [--project ID]
No cleanup deletes: the unique check project and its receipts remain inspectable.
"""

import argparse
import json
from importlib.metadata import version
from uuid import uuid4

from report_agent.knowledge import Knowledge


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--text-only", action="store_true")
    parser.add_argument("--project", default="knowledge-check-" + str(uuid4()))
    args = parser.parse_args()
    with Knowledge(args.project, embedding=False if args.text_only else None) as k:
        bridge = k.put("\u6865\u6881\u517b\u62a4", "\u6df7\u51dd\u571f\u6865\u6881\u51fa\u73b0\u88c2\u7f1d\uff0c\u9700\u8981\u7ef4\u4fee\u52a0\u56fa\u3002",
                       [{"source_id": "synthetic-source-1", "locator": "page 1"}], operation_id="bridge")
        menu = k.put("Lunch", "The restaurant serves noodles and vegetables.", ["synthetic-menu"], operation_id="menu")
        assert k.put("Lunch", "The restaurant serves noodles and vegetables.", ["synthetic-menu"], operation_id="menu")["reused"]
        relation = k.link(bridge["id"], menu["id"], "synthetic_test_relation")
        assert k.traverse(bridge["id"])["paths"]
        text = k.search("\u6865\u6881", mode="text")
        assert text["matches"]
        semantic = None
        if not args.text_only:
            semantic = k.search("\u8fc7\u6cb3\u901a\u9053\u7684\u7ed3\u6784\u7834\u635f\u5982\u4f55\u4fee\u590d", mode="vector")
            assert semantic["matches"][0]["id"] == bridge["id"]
            assert k.search("\u6865\u6881\u4fee\u590d", mode="hybrid")["matches"]
        print(json.dumps({"ok": True, "project_id": args.project, "neo4j_driver": version("neo4j"),
                          "fastembed": version("fastembed") if not args.text_only else None,
                          "description": k.describe(), "bridge_id": bridge["id"], "relation_id": relation["id"],
                          "text_hits": len(text["matches"]),
                          "vector_top_id": semantic["matches"][0]["id"] if semantic else None}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
