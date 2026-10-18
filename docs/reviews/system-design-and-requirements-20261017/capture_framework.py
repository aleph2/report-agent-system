"""Run with the pinned WSL Python. Read installed sources without importing them."""
from pathlib import Path
from importlib.metadata import distribution, version
import ast, hashlib, json

OUT = Path(__file__).resolve().parent
WINDOWS_OUT = "C:/Users/dongy/Documents/ChatGPT/report-agent-system/docs/reviews/system-design-and-requirements-20261017"
rows = []
parts = ["""# 安装框架的提示与摘要默认值

日期：2026-10-17。读取实际WSL虚拟环境的已安装源码，不启动Agent或模型。版本号不能单独证明安装内容与上游完全一致；本册另保存文件hash。

## 当前实际追加关系

- 项目注册openai HarnessProfile，没有设置base_system_prompt或system_prompt_suffix；其默认值为None。当前框架不会因为graph.py中仍存在LEGACY_BASE_AGENT_PROMPT就自动追加该旧提示。
- 安装的DeepAgents 0.7.19在graph.py说明：文件系统／subagent默认不再重复追加整段工具使用prose，工具说明和可用Agent列表主要进入tool schema。不能把默认tool description算作必然存在于system message中的文字。
- Coordinator显式使用TodoListMiddleware，其系统提示见下文。Writer／Reviewer／Layout没有在项目middleware列表中显式加入TodoListMiddleware，不能由Coordinator推断所有角色都有该系统提示。
- FilesystemMiddleware当前项目没有提供自定义system_prompt，使用StateBackend和所声明六种文件工具；它不是无约束host文件或shell访问。
- 当前build_agent没有传skills或memory，不能宣称框架已自动加载项目SKILL.md或所有历史反馈。
- stateful报告路径排除框架默认SummarizationMiddleware，改用项目WorkingSummary，但复用框架的摘要默认计算函数。Learner的独立构建另行配置，不能默认照搬报告上下文。
- 下面原文含未被当前角色调用的模板部分；如read_file模板中的格式占位符，由框架依实际工具和backend填入。它不是完整provider请求。

## 摘要触发值

安装函数compute_summarization_defaults的逻辑是：模型profile含整数max_input_tokens时，trigger为fraction 0.85，keep为fraction 0.10；无该profile时trigger为170000 tokens，keep为最近6条messages。项目working_summary使用这个trigger/keep，另设输出上限16384、提示目标约1200 tokens。这些数值分别是触发、保留和输出目标，不能混为一谈，也不是Codex应用自身设置。

"""]

specs = [
    ("langchain", "langchain/agents/middleware/todo.py", "WRITE_TODOS_SYSTEM_PROMPT", "Coordinator显式TodoListMiddleware系统提示"),
    ("langchain", "langchain/agents/middleware/todo.py", "WRITE_TODOS_TOOL_DESCRIPTION", "todo工具描述"),
    ("deepagents", "deepagents/middleware/subagents.py", "TASK_TOOL_DESCRIPTION", "task工具模板；available_agents由实际注册角色填入"),
    ("deepagents", "deepagents/middleware/filesystem.py", "LIST_FILES_TOOL_DESCRIPTION", "ls工具描述"),
    ("deepagents", "deepagents/middleware/filesystem.py", "_READ_FILE_TOOL_DESCRIPTION_TEMPLATE", "read_file模板；含动态格式字段"),
    ("deepagents", "deepagents/middleware/filesystem.py", "EDIT_FILE_TOOL_DESCRIPTION", "edit_file工具描述"),
    ("deepagents", "deepagents/middleware/filesystem.py", "WRITE_FILE_TOOL_DESCRIPTION", "write_file工具描述"),
    ("deepagents", "deepagents/middleware/filesystem.py", "GLOB_TOOL_DESCRIPTION", "glob工具描述"),
    ("deepagents", "deepagents/middleware/filesystem.py", "_GREP_TOOL_DESCRIPTION_TEMPLATE", "grep模板；含动态格式字段"),
]
for package, rel, name, applicability in specs:
    p = distribution(package).locate_file(rel)
    text = p.read_text()
    tree = ast.parse(text)
    ns = [n for n in tree.body if isinstance(n, ast.Assign)
          and any(isinstance(t, ast.Name) and t.id == name for t in n.targets)]
    assert len(ns) == 1
    node = ns[0]
    value = ast.literal_eval(node.value)
    rows.append({"distribution":package,"version":version(package),"path":str(p),"line":node.lineno,
                 "name":name,"applicability":applicability,"source_sha256":hashlib.sha256(p.read_bytes()).hexdigest(),
                 "text":value,"text_sha256":hashlib.sha256(value.encode()).hexdigest()})
    parts.append(f"## {name}\n\n适用性：{applicability}。\n\n安装来源：{p}:{node.lineno}，版本{version(package)}。\n\n~~~~text\n{value}\n~~~~\n")

p = distribution("deepagents").locate_file("deepagents/middleware/summarization.py")
text=p.read_text()
node=next(n for n in ast.parse(text).body if isinstance(n,ast.FunctionDef) and n.name=="compute_summarization_defaults")
excerpt=ast.get_source_segment(text,node)
parts.append("## 摘要默认计算函数原文\n\n~~~~python\n"+excerpt+"\n~~~~\n")
doc={"as_of_date":"2026-10-17","versions":{name:version(name) for name in ["deepagents","langchain","langchain-core","langgraph","pydantic","langchain-openai"]},
     "prompts":rows,"summary_function":{"path":str(p),"line":node.lineno,"source_sha256":hashlib.sha256(p.read_bytes()).hexdigest(),"text":excerpt}}
(OUT/"framework-prompts.md").write_text("\n".join(parts),encoding="utf-8")
(OUT/"framework-sources.json").write_text(json.dumps(doc,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print(json.dumps({"framework_texts":len(rows),"versions":doc["versions"]}))
