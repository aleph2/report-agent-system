"""Documentation-only, static extraction. Does not import application modules."""
from pathlib import Path
import ast
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
RAW = OUT / "prompts"
RAW.mkdir(exist_ok=True)
SRC = ROOT / "src/report_agent"

def sha(value):
    return hashlib.sha256(value).hexdigest()

def link(path, line=None):
    return "/" + path.resolve().as_posix() + (f":{line}" if line else "")

def source(path):
    text = path.read_text(encoding="utf-8")
    return text, ast.parse(text), text.splitlines(keepends=True)

def nodes(tree, prefix=""):
    for n in tree.body:
        if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            name = prefix + n.name
            yield name, n
            yield from nodes(n, name + ".")

manifest = {
    "as_of_date": "2026-10-17",
    "client_timezone": "Australia/Sydney",
    "base_commit": "b5525a3474b2f284f7a638f226be35a57d6e5d13",
    "source_basis": "current working tree, including pre-existing uncommitted changes",
    "method": "filesystem reads and Python AST only; no application import, store creation, provider call or runtime dispatch",
    "limitation": "Static prompts, exact source assembly, and declared tool descriptions. Dynamic per-call messages, database instructions, material packets and provider-converted tool schemas are not reconstructed by executing the application.",
    "prompts": [], "source_excerpts": [], "tool_descriptions": [],
}
sections = []

def add_prompt(title, path, value, line, status, expression=None):
    key = f"p{len(manifest['prompts']) + 1:02}"
    name = key + "-" + re.sub(r"[^a-zA-Z0-9_-]", "-", path.stem + "-" + title)[:90] + ".txt"
    dest = RAW / name
    dest.write_text(value, encoding="utf-8", newline="\n")
    row = {
        "id": key, "title": title, "status": status,
        "source_path": str(path.resolve()), "source_line": line,
        "source_sha256": sha(path.read_bytes()), "prompt_characters": len(value),
        "prompt_utf8_sha256": sha(value.encode("utf-8")),
        "extracted_file": str(dest), "expression": expression,
    }
    manifest["prompts"].append(row)
    sections.append(
        f"## {key} · {title}\n\n适用性：{status}\n\n"
        f"源码：[原位置]({link(path, line)})；[独立原文]({link(dest)})。\n\n"
        f"字符数：{len(value)}；原文UTF-8 SHA256：{row['prompt_utf8_sha256']}。\n\n"
        + (f"提取方法：{expression}。\n\n" if expression else "")
        + "~~~~text\n" + value + ("" if value.endswith("\n") else "\n") + "~~~~\n"
    )

rules = [
    ("content-common.md", "Common", "当前Coordinator／Writer／Layout公共基底；当前delegated Reviewer被ORGANIZER覆盖，不能默认也收到本文件。"),
    ("content-coordinator.md", "Coordinator", "当前协调者；拼接Common。"),
    ("content-writer.md", "Writer", "当前写作者；拼接Common和context_guidance。"),
    ("content-layout.md", "Layout", "当前排版角色；拼接Common和context_guidance。"),
    ("experience-optimizer.md", "Learner", "独立学习任务；非报告必经角色。"),
    ("content-reviewer.md", "Reviewer-stored-role", "源码保留文本；当前build_agent实际替换为ORGANIZER_PROMPT。部分身份hash仍取本文件组合，不可视作有效prompt证据。"),
    ("report-reviewer.md", "Historical-report-reviewer", "历史／兼容路径；不是当前hierarchical主路径有效角色提示。"),
    ("report-review.md", "Historical-report-review", "历史／兼容rubric；不代表当前委派审核的任务与标准。"),
    ("acceptance-reviewer.md", "Historical-acceptance-reviewer", "历史／兼容路径；当前原生入口拒绝非hierarchical运行。"),
]
for filename, title, status in rules:
    p = SRC / "rules" / filename
    add_prompt(title, p, p.read_text(encoding="utf-8"), 1, status)

targets = [
    ("bounded_review.py", "ORGANIZER_PROMPT", "当前Reviewer决策角色的实际基底，后加reviewer context_guidance。"),
    ("bounded_review.py", "TOOL_PROMPT", "独立内容审核工具内部prompt；不等于Reviewer决策prompt。"),
    ("text_work.py", "TEXT_WORK_PROMPT", "正文／证据生成工具内部prompt，输入材料packet另行组装。"),
    ("text_work.py", "QUALIFIER_WORK_PROMPT", "显式qualifiers-only修订工具prompt，由基础文本替换生成；正文等由服务端保留。"),
    ("evidence_analysis.py", "ANALYSIS_PROMPT", "analyze_text／analyze_evidence共用的有界资料分析prompt。"),
    ("vision.py", "VISION_INSTRUCTION", "图像分析工具prompt；question、图像和provenance是动态输入。"),
    ("working_summary.py", "PROMPT", "工作历史摘要工具prompt；不是Agent、不是应用权威状态。"),
]
for filename, target, status in targets:
    p = SRC / filename
    text, tree, lines = source(p)
    known = {}
    found = None
    for n in tree.body:
        if not isinstance(n, ast.Assign):
            continue
        names = [t.id for t in n.targets if isinstance(t, ast.Name)]
        try:
            value = ast.literal_eval(n.value)
        except (ValueError, TypeError):
            if (isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Attribute)
                    and n.value.func.attr == "replace" and isinstance(n.value.func.value, ast.Name)
                    and n.value.func.value.id in known):
                value = known[n.value.func.value.id].replace(*[ast.literal_eval(a) for a in n.value.args])
            else:
                continue
        for name in names:
            known[name] = value
        if target in names:
            found = (value, n.lineno, ast.get_source_segment(text, n.value) if target == "QUALIFIER_WORK_PROMPT" else None)
    assert found, (filename, target)
    add_prompt(target, p, *found[:2], status, found[2])

for filename, qualname, status in [
    ("artifact_review.py", "bounded_artifact_review_tool.perform_assigned_artifact_review", "独立产物审核工具内部prompt；实际观察receipt、scope和output_schema另行传入。"),
    ("learning_text_work.py", "learning_analysis_tool.analyze_learning_material", "学习资料分析工具内部prompt；不替Learner形成一般行动策略。"),
]:
    p = SRC / filename
    text, tree, lines = source(p)
    fn = dict(nodes(tree))[qualname]
    candidates = [n for n in ast.walk(fn) if isinstance(n, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == "prompt" for t in n.targets)]
    assert len(candidates) == 1
    n = candidates[0]
    add_prompt(qualname + ".prompt", p, ast.literal_eval(n.value), n.lineno, status)

assembly = [
    ("hierarchical_tools.py", "role_prompt"),
    ("deep_runtime.py", "build_agent"),
    ("deep_runtime.py", "BusinessBoundary.awrap_model_call"),
    ("task_context.py", "exact_task_context"),
    ("task_context.py", "TaskContext.awrap_model_call"),
    ("working_summary.py", "working_summary"),
    ("learning_runtime.py", "build_optimizer"),
]
assembly_parts = []
for filename, qualname in assembly:
    p = SRC / filename
    text, tree, lines = source(p)
    n = dict(nodes(tree))[qualname]
    excerpt = "".join(lines[n.lineno - 1:n.end_lineno])
    manifest["source_excerpts"].append({"path": str(p), "symbol": qualname,
        "start_line": n.lineno, "end_line": n.end_lineno,
        "source_sha256": sha(p.read_bytes()), "excerpt_sha256": sha(excerpt.encode())})
    assembly_parts.append(f"### {qualname}\n\n[源码]({link(p, n.lineno)})\n\n~~~~python\n{excerpt}~~~~\n")

tool_sources = [
    ("deep_runtime.py", "business_tools"),
    ("hierarchical_tools.py", "content_tools"),
    ("text_work.py", "guarded_tools"),
    ("bounded_review.py", "review_tool"),
    ("artifact_review.py", "bounded_artifact_review_tool"),
    ("learning_runtime.py", "optimizer_tools"),
    ("learning_text_work.py", "learning_analysis_tool"),
    ("learning.py", "report_tools"),
    ("task_context.py", "observation_tool"),
    ("decision_state.py", "state_tool"),
    ("summary_recovery.py", "recovery_tool"),
]
tool_parts = []
for filename, parent in tool_sources:
    p = SRC / filename
    text, tree, lines = source(p)
    nd = dict(nodes(tree))
    assert parent in nd, (filename, parent)
    for name, n in nodes(nd[parent], parent + "."):
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        doc = ast.get_docstring(n, clean=False)
        if not doc:
            continue
        sig = ("async " if isinstance(n, ast.AsyncFunctionDef) else "") + "def " + n.name + "(" + ast.unparse(n.args) + ")"
        if n.returns:
            sig += " -> " + ast.unparse(n.returns)
        row = {"path": str(p), "symbol": name, "line": n.lineno, "signature": sig,
               "docstring": doc, "docstring_sha256": sha(doc.encode())}
        manifest["tool_descriptions"].append(row)
        tool_parts.append(f"### {name}\n\n[源码]({link(p, n.lineno)})\n\n~~~~python\n{sig}\n~~~~\n\n~~~~text\n{doc}\n~~~~\n")

intro = """# 智能体与工具：prompt原文、拼装和接口明细

日期：2026-10-17。对应[系统与需求总结](README_LINK)。这是当前工作树的静态取证册，包含角色规则、独立LLM工具prompt、运行时拼装函数以及工具声明。没有import项目模块、创建业务Store、发起模型调用或重建任何报告。

**不能把本册当作某次调用的完整模型输入。** 动态目标、委派任务、当前状态、scope指令、已发布经验、所选资料、模型转换后的tool schema及历史messages随调用变化。真实执行应查该次归档的有效请求。

另见[已安装框架的提示原文和摘要默认值](/C:/Users/dongy/Documents/ChatGPT/report-agent-system/docs/reviews/system-design-and-requirements-20261017/framework-prompts.md)。当前框架的文件系统／委派说明主要经工具schema提供，不是每段默认工具说明都会重复加入system message；Coordinator显式TodoListMiddleware的系统提示及具体条件在该附录列明。

## 生效关系

| 对象 | 当前基底 | 其他层 |
|---|---|---|
| Coordinator | content-common.md＋content-coordinator.md | DeepAgents／middleware追加、TaskContext、指令／经验、工具schema、当前消息历史。 |
| Writer | content-common.md＋content-writer.md | context_guidance、框架／TaskContext／工具／消息。 |
| Reviewer | bounded_review.ORGANIZER_PROMPT | reviewer context_guidance及框架／TaskContext／工具／消息；不是直接用content-reviewer.md。 |
| Layout | content-common.md＋content-layout.md | context_guidance及框架／TaskContext／工具／消息。 |
| Learner | experience-optimizer.md | 独立build_optimizer、动态学习任务；实际工具被CandidateBoundary过滤为已注册业务能力。 |
| 内容审核工具 | TOOL_PROMPT | 已保存assignment、所选scope、证据、criterion、output schema。 |
| 产物审核工具 | 函数内部prompt | 真实观察receipt、版本、范围与output schema。 |
| 正文工具 | TEXT_WORK_PROMPT或QUALIFIER_WORK_PROMPT | objective、commission、材料、目标数量、schema及修订绑定。 |
| 资料／视觉／学习分析工具 | 各自内部prompt | 选择的资料、问题、位置和适用范围；不继承Agent全部阅读历史。 |
| 摘要工具 | working_summary.PROMPT | 待摘要历史和可用应用上下文；使用Coordinator服务副本。 |

以下p01起的文本直接从源码提取，保留内容而不人为摘要。独立txt用UTF-8／LF保存；文件字节哈希和运行字符串哈希分开记录，以避免CRLF换行造成混淆。QUALIFIER提示仅执行源码中明确的字符串replace，不运行应用代码。

### 不应混用的三个概念

- 静态prompt源码：本册保存的文本。
- 生效的运行时系统提示：角色＋框架／middleware＋当次应用上下文。
- 完整模型请求：系统提示＋历史／当前messages＋当次工具schema／模型选项。其内容必须查实际调用。

代码仍有Reviewer元数据hash取role_prompt('reviewer')而实际基底使用ORGANIZER的情况。因此某个prompt_hash或文件存在，不能证明模型真正收到了该文件。这是当前调用点差异记录；本次未修。

"""
footer = """## 动态输入和运行配置

本册后面的拼装源码展示了实际字段，不用虚构样例替代真实输入。常见字段包括goal、scope_instruction、actor、assignment、当前对象版本、feedback、issues、剩余检查、预算、learned_guidance和scoped_instructions。输入与对象清单有分页／partial标记；动态上下文不意味着自动注入全量资料。

来源数据与业务权限不同；任务和当前授权由服务端绑定。工具内部的commission／evidence构造需要另外核对，不能因为Writer见过原文就假设独立工具也见过。

## 当前工具注册关系

此处描述静态注册逻辑；底层factory内有历史函数，但并非所有函数都暴露给当前角色。下面的源码声明清单故意保留所属factory，不能当作最终每角色工具列表。

- 共用内容工具：content_status、read_object_index、read_context、read_content_index、read_content_selection、read_review_status、observe_evidence、read_feedback、record_handoff、assess_change_impact、get_operation_receipt、read_content_export、render_content_export、inspect_rendered_page、read_delivery_review_context、read_layout_capabilities，以及按学习配置提供的search_experience／record_experience_use。
- Coordinator／Writer增加import_source_versions、commit_objects、save_text_node、freeze_snapshot、derive_snapshot、export_content_snapshot、export_content_workbook；当前Coordinator再移除save_text_node，其commit_objects不能创建ContentNode。guarded_tools替换采用接口并加入process_report_content。
- Coordinator另有select_content_delivery、record_execution_decision、request_layout_capability、read_task_supervision、list_supervision_plugins、read_review_obligation_coverage。
- Reviewer内容层增加capture_review_sources、confirm_review_reuse、read_task_assignment；当前business_tools移除submit_review／correct_own_review以及analyze_text／analyze_evidence，加入perform_assigned_review／perform_assigned_artifact_review。
- Layout内容层增加export_content_snapshot、request_layout_capability。不能据工具名推断其可以修改正文或业务owner。
- 基础资料层按当前角色过滤到project_status、read_source_page、search_sources、inspect_source_page、analyze_source_image、calculate、read_result、analyze_text／analyze_evidence；Coordinator还可ask_human。Reviewer进一步剔除上面所述两种文字分析入口。
- stateful TaskContext还提供read_tool_observation、决策状态读取、摘要恢复工具；原生框架可提供文件系统、todo和Coordinator委派。临时文件不等于已提交业务对象。
- Learner注册read_learning_feedback、read_learning_evidence、read_experience_candidates、propose_experience、record_feedback_disposition；有text_model时加analyze_learning_material，有显式experiment_runner才加optimize_saved_guidance。CandidateBoundary将模型可见工具限制为这些业务注册项。

动态工具schema由类型注解、Pydantic模型、框架及模型适配生成。下面保存的是Python签名和原始docstring，不冒称是某个provider最终收到的JSON schema；尤其guarded_tools已经替换部分同名接口。

## 运行时拼装源码原样摘录

"""

(OUT / "agent-prompts.md").write_text(
    intro.replace("README_LINK", link(OUT / "README.md")) + "\n".join(sections) + "\n" + footer
    + "\n".join(assembly_parts)
    + "\n## 工具声明源码清单（含被过滤的历史函数）\n\n"
    + "精确适用性见上面的注册关系。原文保留，历史函数存在不等于当前可调用。签名由AST格式化，docstring文本不作语义改写。\n\n"
    + "\n".join(tool_parts), encoding="utf-8", newline="\n")

mapping = {
    "AGENT_PROMPTS": OUT/"agent-prompts.md", "SOURCE_MANIFEST": OUT/"prompt-sources.json",
    "CUSTOMER_FEEDBACK": ROOT/".analysis/implementation-resumed-20261014/layout-feedback-rca-20261016/customer-feedback-collected-20261016.md",
    "FORMAT_ORIGINAL": ROOT/".analysis/implementation-resumed-20261014/layout-feedback-rca-20261016/format-standard-original-text.txt",
    "NEO_DECISIONS": ROOT/".analysis/neo/current-user-decisions-20261015.md",
    "LAYOUT_RCA": ROOT/".analysis/implementation-resumed-20261014/layout-feedback-rca-20261016/neo-trace-review.md",
    "R6_RCA": ROOT/".analysis/implementation-resumed-20261014/layout-feedback-rca-20261016/r6-layout-origin-root-cause-20261016.md",
    "MATERIAL_PROOF": ROOT/".analysis/implementation-resumed-20261014/layout-feedback-rca-20261016/table-material-program-transformation-proof-20261016.md",
    "TABLE_RCA": ROOT/".analysis/implementation-resumed-20261014/layout-feedback-rca-20261016/guide-table-execution-root-cause-20261016.md",
    "OMITTED_TEXT": ROOT/".analysis/implementation-resumed-20261014/layout-feedback-rca-20261016/omitted-tool-return-verbatim-20261016.txt",
    "PROJECT_AGENTS": ROOT/"AGENTS.md", "ARCHITECTURE": ROOT/"ARCHITECTURE.md",
    "TEXT_DOC": ROOT/"docs/independent-text-tools.md", "LEARNING_DOC": ROOT/"docs/feedback-learning.md",
    "PROMPT_DOC": ROOT/"docs/prompt-instructions.md",
    "USER_ARCHIVE": ROOT/".analysis/neo/user-statements-20261014.md",
    "USER_SUPPLEMENT": ROOT/".analysis/neo/user-statements-since-creation-20261015.md",
    "BUG_INVENTORY": ROOT/".analysis/full-chain-acceptance-20261014/complete-bug-inventory-20261015.html",
    "DESIGN_REVIEW": ROOT/".analysis/full-chain-acceptance-20261014/actual-design-review-20261015.html",
}
for key in ["DEEP_RUNTIME", "HIERARCHICAL_TOOLS", "MODEL_CONFIG", "DEEP_MODELS", "TASK_CONTEXT",
            "WORKING_SUMMARY", "TEXT_WORK", "DECISION_DATA", "BOUNDED_REVIEW", "ARTIFACT_REVIEW",
            "CATALOG", "SOURCE_SEARCH", "LEARNING_RUNTIME", "PROMPT_INSTRUCTIONS"]:
    mapping[key] = SRC / (key.lower() + ".py")
main = (OUT/"README.md").read_text(encoding="utf-8")
for key, p in mapping.items():
    if key != "SOURCE_MANIFEST":
        assert p.exists(), p
    main = main.replace("](" + key + ")", "](" + link(p) + ")")
(OUT/"README.md").write_text(main, encoding="utf-8", newline="\n")
manifest["documentation_sources"] = [
    {"path": str(p), "sha256": sha(p.read_bytes())}
    for p in sorted(set(mapping.values())) if p.exists() and p.parent != OUT
]
(OUT/"prompt-sources.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")

for item in manifest["prompts"]:
    data = Path(item["extracted_file"]).read_bytes()
    assert sha(data) == item["prompt_utf8_sha256"]
    assert sha(Path(item["source_path"]).read_bytes()) == item["source_sha256"]
assert not re.search(r"\]\([A-Z_]{3,}\)", main)
print(json.dumps({"prompts": len(manifest["prompts"]), "assembly_excerpts": len(manifest["source_excerpts"]),
    "tool_declarations_including_historical": len(manifest["tool_descriptions"]),
    "readme_characters":len(main), "prompt_book_characters":len((OUT/"agent-prompts.md").read_text(encoding="utf-8")),
    "all_static_prompt_hashes_match":True}, ensure_ascii=False))
