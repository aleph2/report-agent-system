"""Render only the documentation dossier; no external assets or application imports."""
from pathlib import Path
import hashlib
import html
import json
import re
from urllib.parse import quote
from markdown_it import MarkdownIt

HERE = Path(__file__).resolve().parent
md = MarkdownIt("commonmark", {"html": False}).enable("table")

def local_links(s):
    def convert(m):
        target = m.group(1)
        # Markdown source retains clickable app line links. Browser uses the file.
        target = re.sub(r":\d+$", "", target)
        if target.endswith("/agent-prompts.md"):
            return 'href="agent-prompts.html"'
        if target.endswith("/README.md"):
            return 'href="index.html"'
        if target.endswith("/framework-prompts.md"):
            return 'href="framework-prompts.html"'
        return 'href="' + "file:///" + quote(target.lstrip("/"), safe="/:") + '"'
    return re.sub(r'href="(/C:/[^"]+)"', convert, s)

def render_sections(text, fold=False):
    blocks = re.split(r"(?=^## )", text, flags=re.M)
    output, navigation = [], []
    for i, block in enumerate(blocks):
        first = block.splitlines()[0] if block else ""
        title = first.removeprefix("## ")
        if first.startswith("## "):
            anchor = "s" + str(i)
            navigation.append(f'<a href="#{anchor}">{html.escape(title)}</a>')
            if fold and (title.startswith("p") or title.startswith("工具声明") or title.startswith("运行时拼装")):
                output.append(f'<details id="{anchor}"><summary>{html.escape(title)}</summary>'
                              + md.render("\n".join(block.splitlines()[1:])) + "</details>")
            else:
                output.append(f'<section id="{anchor}">' + md.render(block) + "</section>")
        else:
            output.append(md.render(block))
    body = "".join(output)
    flow = """<div class="flow" aria-label="系统依赖示意">
    <div>委托、要求、来源 → 项目状态 → Coordinator</div>
    <div class="lanes"><span>Writer<br>↓<br>有界文字工具<br>↓<br>内容／证据／快照</span>
    <span>Layout／导出工具<br>↓<br>Word／问题Excel<br>↓<br>实际渲染</span>
    <span>Reviewer<br>↓<br>有界审核工具<br>↓<br>检查与未完成项</span></div>
    <div>观察反馈 → Coordinator选择下一步与交付</div>
    <small>独立学习：反馈 → Learner → 未发布候选 → 经评估与授权发布；不是报告固定流水线。</small>
    </div>"""
    body = re.sub(r'<pre><code class="language-mermaid">.*?</code></pre>', flow, body, flags=re.S)
    return local_links(body), "".join(navigation)

CSS = """
:root{font-family:system-ui,'Microsoft YaHei',sans-serif;color:#1e293b;background:#f5f7fb;line-height:1.85}
*{box-sizing:border-box}body{margin:0}header{padding:18px 28px;background:#12243b;color:white;display:flex;gap:24px;align-items:center;flex-wrap:wrap}
header a{color:#d6e9ff;text-decoration:none}header strong{font-size:20px}aside{position:fixed;left:0;top:85px;width:245px;max-height:calc(100vh - 100px);overflow:auto;padding:16px}
aside a{display:block;padding:7px 10px;color:#43546a;font-size:13px;line-height:1.45;text-decoration:none;border-radius:6px}
aside a:hover{background:#e6edf7}main{max-width:1190px;margin:26px 30px 90px 255px;background:white;padding:34px 46px;border:1px solid #e0e6ee;border-radius:12px}
h1{font-size:30px;line-height:1.35;color:#102b45}h2{font-size:23px;line-height:1.5;border-bottom:2px solid #e4edf6;padding-bottom:8px;margin-top:44px}
h3{font-size:18px;margin-top:28px}p,li{font-size:15px}a{color:#1d5f9a;overflow-wrap:anywhere}strong{color:#172d44}
table{width:100%;border-collapse:collapse;font-size:13px;margin:20px 0;line-height:1.75;table-layout:auto}
th,td{border:1px solid #dce4ee;padding:11px 13px;vertical-align:top}th{background:#edf3fa;text-align:left}tr:nth-child(even){background:#fafbfd}
blockquote{border-left:4px solid #70a2ce;margin:20px 0;padding:8px 22px;background:#f2f7fb;color:#34465a}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f6f9;padding:20px;border:1px solid #dfe5ed;border-radius:8px;font:13px/1.7 Consolas,monospace}
code{font-family:Consolas,monospace}details{margin:18px 0;border:1px solid #d3deeb;border-radius:8px;padding:15px 20px}
summary{cursor:pointer;font-size:17px;font-weight:650;color:#153957}section,details{scroll-margin-top:16px}
.flow{padding:25px;background:#eff5fb;border-radius:10px;text-align:center;font-size:15px}.lanes{display:flex;justify-content:center;gap:18px;margin:17px 0}
.lanes span{background:white;padding:15px;min-width:180px;border:1px solid #c8d8e8;border-radius:8px}.flow small{display:block;margin-top:14px}
.note{font-size:12px;color:#64748b;border-top:1px solid #e0e6ee;margin-top:50px;padding-top:14px}
@media(max-width:1050px){aside{position:static;width:auto;max-height:230px}main{margin:15px;padding:22px}.lanes{flex-wrap:wrap}}
@media print{header,aside{display:none}main{margin:0;max-width:none;border:0;padding:0}body{background:white}table{font-size:10px}pre{font-size:10px}a{color:inherit}}
"""

for name, dest, fold in [("README.md", "index.html", False), ("agent-prompts.md", "agent-prompts.html", True),
                         ("framework-prompts.md", "framework-prompts.html", False)]:
    source = (HERE/name).read_text(encoding="utf-8")
    body, nav = render_sections(source, fold)
    title = source.splitlines()[0].removeprefix("# ")
    page = ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{title}</title><style>{CSS}</style></head><body>'
            '<header><strong>Report Agent System · 2026-10-17</strong>'
            '<a href="index.html">系统与需求</a><a href="agent-prompts.html">Prompt 原文册</a>'
            '<a href="framework-prompts.html">框架提示</a>'
            '<a href="prompt-sources.json">提取清单</a></header>'
            f'<aside aria-label="目录">{nav}</aside><main>{body}'
            f'<p class="note">本地阅读版 · 由{name}生成 · 无外部脚本／字体／网络资源。'
            '该文档整理设计与证据，不恢复应用执行。</p></main></body></html>')
    (HERE/dest).write_text(page, encoding="utf-8", newline="\n")
print(json.dumps({"html_files": ["index.html", "agent-prompts.html", "framework-prompts.html"], "external_assets": 0}))
