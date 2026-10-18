"""Capture current role prompts and framework-composed messages with offline models."""
import asyncio
import ast
import hashlib
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from langchain_core.messages import AIMessage, SystemMessage
from report_agent.store import Store
from report_agent.workspace import Workspace
from report_agent.deep_runtime import build_agent
from report_agent.learning_runtime import run_optimizer
from test_deep_runtime import Driver, call
from test_hierarchical_content import seed


async def main():
    sections = ["报告系统 Agent 职责与提示词盘点 — 2026-10-04\n"
        "当前主路径为4类报告agent（coordinator/writer/reviewer/layout），加1类独立经验优化agent。"
        "这是角色类型数，不是固定实例数：一次运行可委派多个writer任务。后台优化仍需显式触发，未常驻自动运行。\n"
        "职责：coordinator负责目标、标准、委派及交付选择；writer维护自己负责的内容；"
        "reviewer审查具体版本并保存结论；layout仅调整冻结内容的呈现；experience_optimizer提炼候选经验，不能发布或修改报告。\n"
        "范围：当前仓库配置和合成任务下实际组装的消息/工具定义。不是此前真实运行的完整聊天轨迹，"
        "不包括私有推理、凭据、工程原始资料。动态任务、检索和恢复会增加上下文。"
        "此文档区分当前、历史及辅助模型组件，不能把不同分支角色相加成当前同时运行数量。\n"]
    for name in ("content-common", "content-coordinator", "content-writer", "content-reviewer", "content-layout", "experience-optimizer"):
        path = ROOT / "src/report_agent/rules" / (name + ".md")
        value = path.read_text(encoding="utf-8")
        sections.append(f"\n===== 项目角色原文：{path.relative_to(ROOT)} =====\nSHA256 {hashlib.sha256(value.encode()).hexdigest()}\n{value}")
    with tempfile.TemporaryDirectory(prefix="report-agent-prompt-audit-") as tmp:
        ws = Workspace(Store(Path(tmp) / "project"))
        ws.store.initialize({"goal": "Synthetic prompt inventory, no engineering work", "content_contract": "hierarchical-review-v1",
            "review_entrypoint": "delegated-reviewer-v1", "sources": [{"id": "s", "title": "Synthetic rule", "content": "Class B permits 75 to 100.", "coverage": "complete"}]})
        ws.store.set("knowledge_enabled", False)
        ws.store.set("learning_config", {"library_path": str(Path(tmp) / "library"), "customer_id": "synthetic-customer"})
        _, _, _, snapshot, _ = seed(ws)
        driver = Driver(coordinator=[AIMessage(content="", tool_calls=[call("task", {"subagent_type": role,
            "description": "Synthetic prompt inventory only; reply without business actions.",
            **({"layout_snapshot_ref": snapshot} if role == "layout" else {})}, "inventory-" + role)])
            for role in ("writer", "reviewer", "layout")] + [AIMessage(content="Inventory finished.")],
            writer=[AIMessage(content="Writer inventory.")], reviewer=[AIMessage(content="Reviewer inventory.")],
            layout=[AIMessage(content="Layout inventory.")], optimizer=[AIMessage(content="No candidate: synthetic inspection only.")])
        await build_agent(ws, driver, None).ainvoke({"messages": [{"role": "user", "content": "Collect offline prompt inventory."}]}, config={"recursion_limit": 30})
        await run_optimizer(ws, driver("optimizer"))
        for role in ("coordinator", "writer", "reviewer", "layout", "optimizer"):
            observed = [messages for observed_role, _, messages in driver.calls if observed_role == role]
            if not observed:
                raise RuntimeError("ROLE_NOT_OBSERVED: " + role)
            systems = []
            for messages in observed:
                for message in messages:
                    if isinstance(message, SystemMessage) and message.content not in systems:
                        systems.append(message.content)
            sections.append(f"\n===== 实际离线组装的系统消息：{role} =====\n" + json.dumps(systems, ensure_ascii=False, indent=2))
            bindings = driver.bindings[role][-1]
            sections.append(f"\n===== 实际工具定义：{role}（{len(bindings)}项）=====\n" + json.dumps(bindings, ensure_ascii=False, indent=2))
        counts = {role: len(driver.bindings[role][-1]) for role in driver.bindings}
    from deepagents.middleware.rubric import GRADER_SYSTEM_PROMPT
    sections.append("\n===== 历史 native grader 的框架提示词全文（当前主路径不启用）=====\n" + GRADER_SYSTEM_PROMPT)
    sections.append("\n===== 额外模型组件与历史分支 =====\n"
        "text_tool/analyze_text/analyze_evidence及视觉/OCR调用是有界工具，不是额外自主agent。"
        "DSPy/GEPA包含任务模型与反思模型调用，是显式调用的优化程序，尚未作为常驻agent运行。"
        "general-purpose subagent已禁用。当前主路径没有独立knowledge agent或自动第二grader。\n"
        "历史兼容：非hierarchical DeepAgents路径仍有knowledge/writer/reviewer定义及native rubric grader分支；"
        "hierarchical的native-rubric-v1开关仍保留rubric_grader兼容入口。ADK旧路径保留materials、purpose、plan、writer、reviewer等定义，"
        "它们不属于当前主路径。下附历史角色文件与相关构造代码，不将其描述为当前已启用。\n"
        "开发助手Main和邮件心跳属于外部开发/沟通环境，不计入报告产品agent。后台经验优化agent未获得代码修改或自动发布权。\n")
    for path in sorted((ROOT / "src/report_agent/rules").glob("*.md")):
        if path.stem not in {"content-common", "content-coordinator", "content-writer", "content-reviewer", "content-layout", "experience-optimizer"}:
            sections.append(f"\n===== 其他/历史规则文件：{path.relative_to(ROOT)} =====\n" + path.read_text(encoding="utf-8"))
    for name in ("deep_runtime", "runtime", "report_runtime", "review", "hierarchical_review", "evidence_analysis", "vision", "review_context", "content_tasks"):
        path = ROOT / "src/report_agent" / (name + ".py")
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                value = ast.get_source_segment(source, node)
                if any(token in value for token in ("PROMPT", "INSTRUCTION", "GUIDANCE", "COORDINATOR =", "ROLES =", "WORKER =", "ROLE_GOALS =")):
                    sections.append(f"\n===== 提示词常量：{name}.py:{node.lineno} =====\n" + value)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in {
                    "build_agent", "reviewer_prompt", "native_review", "delegated_task"}:
                sections.append(f"\n===== 组装逻辑：{name}.py:{node.lineno} =====\n" + ast.get_source_segment(source, node))
            if isinstance(node, ast.ClassDef) and node.name in {"BusinessBoundary", "HierarchicalRubric"}:
                sections.append(f"\n===== 动态上下文/历史审核适配：{name}.py:{node.lineno} =====\n" + ast.get_source_segment(source, node))
    output = ROOT / ".analysis/learning/agent-inventory-2026-10-04.txt"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(sections), encoding="utf-8")
    print(json.dumps({"path": str(output), "bytes": output.stat().st_size, "tool_counts": counts,
                     "optimizer_tools": [t["name"] for t in driver.bindings["optimizer"][-1]]}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
