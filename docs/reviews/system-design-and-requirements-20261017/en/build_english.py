"""English documentation only. Preserve captured source prompts and code."""
from pathlib import Path
import ast, hashlib, html, json, re
from urllib.parse import quote
from markdown_it import MarkdownIt
HERE=Path(__file__).resolve().parent
BASE=HERE.parent
ROOT=BASE.parents[2]
SRC=ROOT/"src/report_agent"
M=json.loads((BASE/"prompt-sources.json").read_text(encoding="utf-8"))
F=json.loads((BASE/"framework-sources.json").read_text(encoding="utf-8"))
def sha(b):return hashlib.sha256(b).hexdigest()
def link(p,line=None):return "/"+p.resolve().as_posix()+(f":{line}" if line else "")

intro="""# Agents and Tools: Original Prompts, Assembly, and Interfaces

Date: 17 October 2026. Companion to the [system and requirements summary](README_LINK). This English edition preserves the captured working-tree evidence: role rules, independent LLM-tool prompts, runtime assembly functions, and tool declarations. It does not instantiate the application, create a business store, call a model, or rebuild a report.

**This is not the complete input of a particular model call.** Goals, assignments, current state, scoped instructions, released experience, selected materials, provider-converted schemas, and message history vary by call. Consult the archived effective request for execution-level evidence.

See also [installed framework prompts and summarization defaults](FRAMEWORK_LINK). Filesystem/delegation guidance in the captured framework is primarily supplied through tool schemas. Not every default tool description is also system-message prose. Coordinator's explicit TodoListMiddleware system prompt and its applicability are documented separately.

## Effective prompt relationships

| Component | Current base | Additional layers |
|---|---|---|
| Coordinator | content-common.md + content-coordinator.md | Framework/middleware, TaskContext, instructions/experience, schemas, messages. |
| Writer | content-common.md + content-writer.md | context_guidance, framework, TaskContext, tools, messages. |
| Reviewer | bounded_review.ORGANIZER_PROMPT | Reviewer context_guidance, framework, TaskContext, tools, messages; not directly content-reviewer.md. |
| Layout | content-common.md + content-layout.md | context_guidance, framework, TaskContext, tools, messages. |
| Learner | experience-optimizer.md | Independent build_optimizer and learning assignment; CandidateBoundary filters tools to registered business capabilities. |
| Content-review tool | TOOL_PROMPT | Saved assignment, selected scopes, evidence, criteria, output schema. |
| Artifact-review tool | Function-local prompt | Actual observation receipts, versions, scopes, output schema. |
| Content-production tool | TEXT_WORK_PROMPT or QUALIFIER_WORK_PROMPT | Objective, commission, material packet, count/schema, revision bindings. |
| Evidence/vision/learning analysis | Respective internal prompts | Selected material, question, locations, applicability; no automatic inheritance of agent reading history. |
| Summary tool | working_summary.PROMPT | History and available application context; a copy of the Coordinator service. |

The p01 onward excerpts are original source strings, not translated runtime instructions. Text files use UTF-8/LF. File-byte and extracted-string hashes are separate to avoid CRLF confusion. QUALIFIER_WORK_PROMPT was derived only through the source's explicit string replacement, without running application code.

### Three distinct forms of input

- Static prompt source: the original text preserved here.
- Effective system message: role plus framework/middleware plus current application context.
- Complete model request: system message, history/current messages, schemas, and model options. Inspect the actual call to establish this.

Some Reviewer metadata still hashes role_prompt('reviewer') while the effective base is ORGANIZER_PROMPT. A prompt_hash or file's existence does not prove what the model received. This dossier records that discrepancy; it does not repair it.

"""
statuses=[
"Shared base for Coordinator, Writer, and Layout. The current delegated Reviewer is overridden by ORGANIZER_PROMPT; do not assume it also receives this file.",
"Current Coordinator role, combined with Common.",
"Current Writer role, combined with Common and context_guidance.",
"Current Layout role, combined with Common and context_guidance.",
"Independent learning task, not a mandatory report role.",
"Retained source text. Current build_agent replaces it with ORGANIZER_PROMPT. Some identity hashes still use this combined role text; they are not proof of the effective prompt.",
"Historical/compatibility path, not the current hierarchical role prompt.",
"Historical/compatibility rubric, not the current delegated assignment and criteria.",
"Historical/compatibility path; the current native entry point rejects non-hierarchical execution.",
"Actual base of the current Reviewer decision role, followed by Reviewer context_guidance.",
"Internal independent content-review prompt, distinct from the Reviewer decision prompt.",
"Internal content/evidence production prompt; the material packet is assembled separately.",
"Explicit qualifiers-only revision prompt derived by replacement. The server preserves the body and other protected fields.",
"Bounded source-analysis prompt shared by analyze_text and analyze_evidence.",
"Image-analysis prompt; the question, image, and provenance are dynamic.",
"Working-history summary prompt; neither an agent nor authoritative application state.",
"Independent artifact-review prompt; observations, scope, and output_schema are supplied separately.",
"Learning-material analysis prompt; it does not formulate general strategies in place of Learner."
]
parts=[intro.replace("README_LINK",link(HERE/"README.md")).replace("FRAMEWORK_LINK",link(HERE/"framework-prompts.md"))]
for row,status in zip(M["prompts"],statuses,strict=True):
 raw=Path(row["extracted_file"]).read_bytes()
 assert sha(raw)==row["prompt_utf8_sha256"]
 value=raw.decode("utf-8")
 parts.append(f"## {row['id']} · {row['title']}\n\nApplicability: {status}\n\n"
  f"Source: [original location]({link(Path(row['source_path']),row['source_line'])}); "
  f"[standalone original]({link(Path(row['extracted_file']))}).\n\n"
  f"Characters: {row['prompt_characters']}; UTF-8 SHA256: {row['prompt_utf8_sha256']}.\n\n")
 if row.get("expression"):parts.append("Exact extraction expression:\n\n~~~~python\n"+row["expression"]+"\n~~~~\n\n")
 parts.append("~~~~text\n"+value+("" if value.endswith("\n") else "\n")+"~~~~\n\n")
parts.append("""## Dynamic inputs and runtime configuration

The assembly excerpts show actual fields rather than invented example requests. Common fields include goal, scope_instruction, actor, assignment, current object versions, feedback, issues, remaining checks, budget, learned_guidance, and scoped_instructions. Input/object inventories can be paginated and marked partial. Dynamic context does not mean all sources are automatically injected.

Source data and business authority differ. Tasks and authorization are server-bound. The commission/evidence packet inside a tool needs separate inspection; Writer having read an original does not establish that the tool received it.

## Current tool-registration relationships

Underlying factories contain historical functions that are not all exposed today. The declaration inventory retains factory names and is not a final per-role callable-tool list.

- Shared content tools: content_status, read_object_index, read_context, read_content_index, read_content_selection, read_review_status, observe_evidence, read_feedback, record_handoff, assess_change_impact, get_operation_receipt, read_content_export, render_content_export, inspect_rendered_page, read_delivery_review_context, read_layout_capabilities; learning configuration may add search_experience and record_experience_use.
- Coordinator/Writer add import_source_versions, commit_objects, save_text_node, freeze_snapshot, derive_snapshot, export_content_snapshot, and export_content_workbook. Current Coordinator removes save_text_node, and its commit_objects cannot create ContentNode. guarded_tools replaces adoption interfaces and adds process_report_content.
- Coordinator additionally has select_content_delivery, record_execution_decision, request_layout_capability, read_task_supervision, list_supervision_plugins, and read_review_obligation_coverage.
- Reviewer adds capture_review_sources, confirm_review_reuse, and read_task_assignment. Current business_tools removes submit_review, correct_own_review, analyze_text, and analyze_evidence, and adds perform_assigned_review and perform_assigned_artifact_review.
- Layout adds export_content_snapshot and request_layout_capability. Tool names do not authorize changing prose or ownership.
- The source layer is filtered by role to project_status, read_source_page, search_sources, inspect_source_page, analyze_source_image, calculate, read_result, analyze_text, and analyze_evidence. Coordinator also has ask_human. Reviewer removes the two text-analysis entry points above.
- Stateful TaskContext provides read_tool_observation, decision-state reading, and summary recovery. Native capabilities may include filesystem, todo, and Coordinator delegation. Scratch files are not committed business objects.
- Learner registers read_learning_feedback, read_learning_evidence, read_experience_candidates, propose_experience, and record_feedback_disposition. A text_model enables analyze_learning_material; an explicit experiment_runner enables optimize_saved_guidance. CandidateBoundary limits visible tools to these registered capabilities.

Schemas are generated through annotations, Pydantic, the framework, and model adapters. The inventory preserves Python signatures and original docstrings, not a provider's final JSON schema. guarded_tools replaces some same-named interfaces.

## Runtime assembly source excerpts

""")
original=(BASE/"agent-prompts.md").read_text(encoding="utf-8")
assembly=original.split("## 运行时拼装源码原样摘录",1)[1].split("## 工具声明源码清单",1)[0]
for row in M["source_excerpts"]:
 match=re.search(r"### "+re.escape(row["symbol"])+r"\n.*?~~~~python\n(.*?)~~~~",assembly,re.S)
 assert match,row["symbol"]
 excerpt=match.group(1)
 assert sha(excerpt.encode())==row["excerpt_sha256"],row["symbol"]
 parts.append(f"### {row['symbol']}\n\n[Source]({link(Path(row['path']),row['start_line'])})\n\n~~~~python\n{excerpt}~~~~\n\n")
parts.append("""## Tool declaration inventory, including historical functions

Applicability follows the registration relationships above. A historical function's presence does not make it callable today. Signatures are AST-formatted; docstrings are preserved without semantic rewriting.

""")
for row in M["tool_descriptions"]:
 assert sha(row["docstring"].encode())==row["docstring_sha256"]
 parts.append(f"### {row['symbol']}\n\n[Source]({link(Path(row['path']),row['line'])})\n\n"
  f"~~~~python\n{row['signature']}\n~~~~\n\n~~~~text\n{row['docstring']}\n~~~~\n\n")
(HERE/"agent-prompts.md").write_text("".join(parts),encoding="utf-8",newline="\n")

framework_intro="""# Installed Framework Prompts and Summarization Defaults

Date: 17 October 2026. This appendix uses captured installed source from the actual WSL environment, without starting an agent or model. Version numbers alone do not prove identical upstream content; the source manifest also records file hashes.

## Current contributions

- The project registers an openai HarnessProfile without base_system_prompt or system_prompt_suffix; their defaults are None. LEGACY_BASE_AGENT_PROMPT remaining in graph.py does not automatically append that old prompt.
- Installed DeepAgents 0.7.19 states that filesystem/subagent middleware no longer duplicates complete tool-usage prose by default. Tool descriptions and available agents primarily enter tool schemas. Default descriptions are not necessarily system-message text.
- Coordinator explicitly uses TodoListMiddleware. Writer, Reviewer, and Layout do not explicitly add it in the project's middleware list; do not infer identical instructions for every role.
- No custom FilesystemMiddleware system_prompt is supplied. The project uses StateBackend and six declared file tools, not unrestricted host-file or shell access.
- Current build_agent does not pass skills or memory. This does not establish automatic loading of SKILL.md files or all historical feedback.
- The stateful report path excludes default SummarizationMiddleware and uses WorkingSummary while reusing the framework's default calculation. Learner is built separately; do not assume the same context policy.
- Templates may contain fields not active for a particular role. Placeholders are filled according to the actual tools/backend. These excerpts are not complete provider requests.

## Summarization trigger

With an integer max_input_tokens in the model profile, compute_summarization_defaults uses trigger fraction 0.85 and retention fraction 0.10. Otherwise, it uses a 170,000-token trigger and retains six recent messages. Project working_summary uses those trigger/keep settings, with a separate 16,384-token output cap and an approximately 1,200-token prompt target. Trigger, retention, and output target differ. These are not the Codex application's settings.

"""
fs=["System prompt from Coordinator's explicit TodoListMiddleware.","Todo tool description.",
 "Task template; available_agents is filled from registered roles.","ls tool description.",
 "read_file template, including dynamic formatting fields.","edit_file tool description.",
 "write_file tool description.","glob tool description.","grep template, including dynamic formatting fields."]
fp=[framework_intro]
for row,status in zip(F["prompts"],fs,strict=True):
 assert sha(row["text"].encode())==row["text_sha256"]
 fp.append(f"## {row['name']}\n\nApplicability: {status}\n\n"
  f"Installed source: {row['path']}:{row['line']}; version {row['version']}.\n\n~~~~text\n{row['text']}\n~~~~\n\n")
fp.append("## Original summarization-default function\n\n~~~~python\n"+F["summary_function"]["text"]+"\n~~~~\n")
(HERE/"framework-prompts.md").write_text("".join(fp),encoding="utf-8",newline="\n")

mapping={"AGENT_PROMPTS":HERE/"agent-prompts.md","SOURCE_MANIFEST":BASE/"prompt-sources.json",
 "FRAMEWORK_PROMPTS":HERE/"framework-prompts.md","CHINESE_EDITION":BASE/"README.md",
 "CUSTOMER_FEEDBACK":ROOT/".analysis/implementation-resumed-20261014/layout-feedback-rca-20261016/customer-feedback-collected-20261016.md",
 "FORMAT_ORIGINAL":ROOT/".analysis/implementation-resumed-20261014/layout-feedback-rca-20261016/format-standard-original-text.txt",
 "NEO_DECISIONS":ROOT/".analysis/neo/current-user-decisions-20261015.md",
 "LAYOUT_RCA":ROOT/".analysis/implementation-resumed-20261014/layout-feedback-rca-20261016/neo-trace-review.md",
 "R6_RCA":ROOT/".analysis/implementation-resumed-20261014/layout-feedback-rca-20261016/r6-layout-origin-root-cause-20261016.md",
 "MATERIAL_PROOF":ROOT/".analysis/implementation-resumed-20261014/layout-feedback-rca-20261016/table-material-program-transformation-proof-20261016.md",
 "TABLE_RCA":ROOT/".analysis/implementation-resumed-20261014/layout-feedback-rca-20261016/guide-table-execution-root-cause-20261016.md",
 "OMITTED_TEXT":ROOT/".analysis/implementation-resumed-20261014/layout-feedback-rca-20261016/omitted-tool-return-verbatim-20261016.txt",
 "PROJECT_AGENTS":ROOT/"AGENTS.md","ARCHITECTURE":ROOT/"ARCHITECTURE.md",
 "TEXT_DOC":ROOT/"docs/independent-text-tools.md","LEARNING_DOC":ROOT/"docs/feedback-learning.md",
 "PROMPT_DOC":ROOT/"docs/prompt-instructions.md",
 "USER_ARCHIVE":ROOT/".analysis/neo/user-statements-20261014.md",
 "USER_SUPPLEMENT":ROOT/".analysis/neo/user-statements-since-creation-20261015.md",
 "BUG_INVENTORY":ROOT/".analysis/full-chain-acceptance-20261014/complete-bug-inventory-20261015.html",
 "DESIGN_REVIEW":ROOT/".analysis/full-chain-acceptance-20261014/actual-design-review-20261015.html"}
for k in ["DEEP_RUNTIME","HIERARCHICAL_TOOLS","MODEL_CONFIG","DEEP_MODELS","TASK_CONTEXT","WORKING_SUMMARY",
 "TEXT_WORK","DECISION_DATA","BOUNDED_REVIEW","ARTIFACT_REVIEW","CATALOG","SOURCE_SEARCH","LEARNING_RUNTIME","PROMPT_INSTRUCTIONS"]:
 mapping[k]=SRC/(k.lower()+".py")
text=(HERE/"README.md").read_text(encoding="utf-8")
for k,p in mapping.items():
 assert p.is_file(),p
 text=text.replace("]("+k+")","]("+link(p)+")")
assert not re.search(r"\]\([A-Z_]{3,}\)",text)
(HERE/"README.md").write_text(text,encoding="utf-8",newline="\n")

# Importing the Chinese renderer would rewrite its pages; extract stylesheet data only.
tree=ast.parse((BASE/"render_dossier.py").read_text(encoding="utf-8"))
css=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign)
 and any(isinstance(t,ast.Name) and t.id=="CSS" for t in n.targets))
md=MarkdownIt("commonmark",{"html":False}).enable("table")
def sections(text):
 result=[];current=[];fence=None
 for line in text.splitlines(keepends=True):
  m=re.match(r"^\s{0,3}([~\x60]{3,})",line)
  if m:
   marker=m.group(1)
   if fence is None:fence=marker
   elif marker[0]==fence[0] and len(marker)>=len(fence):fence=None
  if fence is None and line.startswith("## ") and current:
   result.append("".join(current));current=[]
  current.append(line)
 if current:result.append("".join(current))
 return result
def fix_links(body):
 def convert(m):
  target=re.sub(r":\d+$","",m.group(1));p=Path(target[1:])
  names={"README.md":"index.html","agent-prompts.md":"agent-prompts.html","framework-prompts.md":"framework-prompts.html"}
  if p.parent==HERE and p.name in names:return 'href="'+names[p.name]+'"'
  if p==BASE/"README.md":return 'href="../index.html"'
  return 'href="file:///'+quote(target.lstrip("/"),safe="/:")+'"'
 return re.sub(r'href="(/C:/[^"]+)"',convert,body)
flow="""<div class="flow" aria-label="System dependencies">
<div>Commission, requirements, sources → Project state → Coordinator</div>
<div class="lanes"><span>Writer<br>↓<br>Bounded text tools<br>↓<br>Content / evidence / snapshot</span>
<span>Layout / export tools<br>↓<br>Word / issue workbook<br>↓<br>Actual renderings</span>
<span>Reviewer<br>↓<br>Bounded review tools<br>↓<br>Findings / unfinished checks</span></div>
<div>Observations → Coordinator selects the next action and delivery</div>
<small>Separate learning: feedback → Learner → unpublished candidates → evaluated and authorized release.
These are dependencies, not a mandatory report pipeline.</small></div>"""
for filename,output,fold in [("README.md","index.html",False),("agent-prompts.md","agent-prompts.html",True),
 ("framework-prompts.md","framework-prompts.html",False)]:
 doc=(HERE/filename).read_text(encoding="utf-8");nav=[];rendered=[]
 for i,block in enumerate(sections(doc)):
  title=block.splitlines()[0]
  if title.startswith("## "):
   title=title[3:];anchor="s"+str(i)
   nav.append(f'<a href="#{anchor}">{html.escape(title)}</a>')
   if fold and (re.match(r"p\d\d",title) or title.startswith(("Tool declaration","Runtime assembly"))):
    rendered.append(f'<details id="{anchor}"><summary>{html.escape(title)}</summary>'
     +md.render("\n".join(block.splitlines()[1:]))+"</details>")
   else:rendered.append(f'<section id="{anchor}">'+md.render(block)+"</section>")
  else:rendered.append(md.render(block))
 body=re.sub(r'<pre><code class="language-mermaid">.*?</code></pre>',flow,fix_links("".join(rendered)),flags=re.S)
 page=('<!doctype html><html lang="en"><head><meta charset="utf-8">'
  '<meta name="viewport" content="width=device-width, initial-scale=1"><title>'
  +html.escape(doc.splitlines()[0].removeprefix("# "))+'</title><style>'+css+'</style></head><body>'
  '<header><strong>Report Agent System · 17 October 2026</strong>'
  '<a href="index.html">Design &amp; requirements</a><a href="agent-prompts.html">Agent prompts</a>'
  '<a href="framework-prompts.html">Framework prompts</a><a href="../index.html">Chinese edition</a>'
  '<a href="../prompt-sources.json">Source manifest</a></header>'
  '<aside aria-label="Contents">'+"".join(nav)+'</aside><main>'+body
  +f'<p class="note">English reading edition · Generated from {filename} · No external scripts, fonts, or network assets. '
  'This dossier records design and evidence; it does not resume application execution.</p></main></body></html>')
 (HERE/output).write_text(page,encoding="utf-8",newline="\n")
missing=[];untranslated=[]
for name in ["README.md","agent-prompts.md","framework-prompts.md"]:
 text=(HERE/name).read_text(encoding="utf-8")
 for target in re.findall(r"\]\((/C:/[^)]+)\)",text):
  p=Path(re.sub(r":\d+$","",target[1:]))
  if not p.exists():missing.append(str(p))
 prose=re.sub(r"^~~~~[^\n]*\n.*?^~~~~\s*$","",text,flags=re.M|re.S)
 if re.search(r"[\u4e00-\u9fff]",prose):untranslated.append(name)
assert not missing,missing
assert not untranslated,untranslated
verification={"date":"2026-10-17","scope":"English documentation edition only",
 "source_edition":"../README.md","project_prompt_strings_preserved":len(M["prompts"]),
 "framework_prompt_strings_preserved":len(F["prompts"]),"assembly_source_blocks_preserved":len(M["source_excerpts"]),
 "tool_docstrings_preserved":len(M["tool_descriptions"]),"missing_local_links":missing,
 "untranslated_editorial_prose":untranslated,"application_code_changes":False,"paid_report_calls":0,
 "independent_final_review":"not newly performed for translation",
 "files":{p.name:{"bytes":p.stat().st_size,"sha256":sha(p.read_bytes())} for p in HERE.iterdir() if p.suffix in {".md",".html"}}}
(HERE/"verification.json").write_text(json.dumps(verification,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print(json.dumps({k:v for k,v in verification.items() if k!="files"}))
