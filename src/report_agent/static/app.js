"use strict";

const $ = (id) => document.getElementById(id);
const labels = {
  ready: "就绪", running: "执行中", completed: "执行结束", failed: "执行失败",
  not_assessed: "报告尚未评估", review_evidence_available: "已有审核记录，尚非整体验收",
  error: "执行错误", paused: "已暂停", interrupted: "执行中断", needs_attention: "需要处理",
  waiting: "等待中", waiting_for_human: "等待人工处理", pending: "待执行",
  draft: "报告草稿", draft_ready: "草稿已保存", unreviewed_draft: "草稿未审核",
  reviewed_draft: "草稿已审核", changes_required: "需要修改", accepted: "审核通过",
  purpose: "用途理解", plan: "编制计划", materials: "材料整理", review: "报告审核",
  needs_human: "待人处理", source_missing: "原始资料缺失", source_conflict: "原始资料矛盾", system_failure: "系统故障", system_error: "系统故障待处理",
  configured: "已配置模型", unconfigured: "未配置模型", scripted_fixture: "脚本模拟 · 非真实模型",
  stale: "已过期，待核对", superseded: "已被替代", resolved: "已处理", unassessed: "未评估",
  needs_assessment: "影响待评估", coordinator: "统筹", knowledge: "知识维护", writer: "编写", reviewer: "审核",
};
const translate = (value) => labels[value] || value || "未提供";
const display = (value) => typeof value === "string" ? value : JSON.stringify(value, null, 2) ?? "";
const list = (value) => Array.isArray(value) ? value : [];
function text(node, value) {
  const next = display(value);
  if (node.textContent !== next) node.textContent = next;
}
function element(tag, value, className) {
  const node = document.createElement(tag);
  if (value !== undefined) text(node, value);
  if (className) node.className = className;
  return node;
}
function message(id, value) { text($(id), value); $(id).hidden = !value; }
function state(node, value) {
  text(node, translate(value));
  node.dataset.tone = /fail|error|attention|changes_required|interrupted|needs_human|needs_assessment/.test(value) ? "error"
    : ["ready", "running", "completed", "reviewed_draft", "accepted"].includes(value) ? "success" : "neutral";
}
function errorText(error) {
  if (!error) return "";
  if (typeof error === "string") return error;
  return [error.type, error.http_status ? `HTTP ${error.http_status}` : "", error.message || display(error)].filter(Boolean).join(" · ");
}

function interruptions(data) {
  return list(data.native_interrupts).map(item => {
    const value = item.value && typeof item.value === "object" ? item.value : item;
    return { issueId: value.issue_id, description: value.description,
      issue: list(data.issues).find(issue => issue.id === value.issue_id) };
  });
}

function eventLabel(event) {
  const data = event.data || {};
  if (event.kind === "deep_run_started") return data.resume ? "从断点继续运行" : "开始运行";
  if (event.kind === "deep_run_finished") return "本轮运行结束";
  if (event.kind === "deep_run_error") return `运行出错${data.type ? ` · ${data.type}` : ""}`;
  if (event.kind === "deep_tool_rejected") {
    const reason = errorText({ type: data.type, http_status: data.http_status,
      message: data.message || "本次工具调用被拒绝" });
    return `${data.role ? translate(data.role) : "智能体"} · ${data.tool || "工具"} · 调用被拒绝 · ${reason}`;
  }
  if (event.kind === "deep_tool_start" || event.kind === "deep_tool_end") {
    return `${data.role ? translate(data.role) : "智能体"} · ${data.tool || "工具"} · ${event.kind === "deep_tool_start" ? (data.observation === "requested" ? "已请求调用" : "调用开始") : "已返回"}`;
  }
  return event.kind;
}

function runView(data) {
  const events = list(data.events).filter(event => /^deep_(run_(started|finished|error)|tool_(start|end|rejected))$/.test(event.kind));
  const active = new Map();
  for (const event of events) {
    // A bounded event tail can omit starts. Only matched IDs establish active calls.
    if (event.kind.startsWith("deep_run_")) active.clear();
    const callId = event.data?.tool_call_id;
    const key = callId ? JSON.stringify([event.data.role || "", callId]) : null;
    if (key && event.kind === "deep_tool_start") active.set(key, event);
    if (key && ["deep_tool_end", "deep_tool_rejected"].includes(event.kind)) active.delete(key);
  }
  const last = events.at(-1);
  let activity = data.activity ? translate(data.activity) : "";
  if (!activity) {
    if (data.status === "running") {
      activity = active.size ? [...active.values()].map(event => `${translate(event.data.role)} · ${event.data.tool}`).join("\n")
        : "运行中，等待下一条动作记录";
    } else if (interruptions(data).length) {
      activity = "运行已暂停，等待人工决定或恢复";
    } else if (["failed", "error", "system_error", "interrupted"].includes(data.status)) {
      activity = "运行已停止，请查看错误信息";
    } else if (data.checkpoint_resume === true) {
      activity = "已保存断点，等待继续";
    } else if (last?.kind === "deep_run_finished") {
      activity = "本轮运行已结束";
    } else {
      activity = "等待运行";
    }
  }
  return { activity, events: events.slice(-6), last };
}

function summaryText(value) {
  if (typeof value === "string") return value;
  return list(value).filter(block => block?.type === "text" && typeof block.text === "string")
    .map(block => block.text).join("\n\n");
}

function renderRun(data) {
  const view = runView(data);
  text($("activity"), view.activity);
  text($("runtime"), typeof data.runtime === "string" ? data.runtime : "");
  $("run-history-empty").hidden = view.events.length > 0;
  $("run-history").replaceChildren(...view.events.map(event => {
    const row = element("li");
    const time = element("time", event.at || "时间未提供");
    row.append(time, element("span", eventLabel(event), ["deep_run_error", "deep_tool_rejected"].includes(event.kind) ? "danger" : ""));
    return row;
  }));
  const summary = summaryText(data.agent_summary);
  $("agent-summary-panel").hidden = !summary;
  text($("agent-summary"), summary);
  const runError = ["failed", "error", "system_error"].includes(data.status) && view.last?.kind === "deep_run_error"
    ? errorText(view.last.data) || "运行失败，错误详情尚未提供" : "";
  message("system-error", data.last_error || runError ? `执行错误\n${errorText(data.last_error) || runError}` : "");
  const pending = interruptions(data);
  $("interrupt-panel").hidden = !pending.length || data.status === "running";
  const undecided = pending.some(item => !item.issue?.decision);
  text($("interrupt-heading"), undecided ? "运行等待人工决定" : "人工决定已记录，等待恢复");
  text($("interrupt-status"), undecided ? "尚有人工决定待记录。" : "运行尚未恢复。");
  $("interrupts").replaceChildren(...pending.map(item => {
    const row = element("li");
    const description = item.issue?.description || item.description || "待处理的运行中断";
    row.append(element("span", `${description}${item.issueId ? ` · 问题 ${item.issueId}` : ""} `));
    if (item.issue) {
      const link = element("a", item.issue.decision ? "查看已记录决定" : "处理问题");
      link.href = `#${encodeURIComponent(`issue-${item.issue.id}`)}`;
      row.append(link);
    } else {
      row.append(element("span", "问题记录尚未获取", "metadata"));
    }
    return row;
  }));
}

let snapshot = null;
let connected = false;
let posting = false;
let downloading = false;
let refreshInFlight = null;
let epoch = 0;
let taskSignature = "";
const resultNodes = new Map();
const issueNodes = new Map();
const sourceNodes = new Map();
let sourceSignature = "";
let correctionSignature = "";
const pages = {
  source: { key: "", offset: 0, next: null, busy: false, serial: 0 },
  search: { key: "", offset: 0, next: null, busy: false, serial: 0 },
};

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(path, { cache: "no-store", ...options, signal: AbortSignal.timeout(30000) });
  } catch (error) {
    throw new Error(`${path}：${error.name === "TimeoutError" ? "请求超时" : "网络连接失败"}。${options.method === "POST" ? "操作可能已被接收，请核实状态后再决定是否重试。" : "请检查后台连接。"}`);
  }
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`${path}：HTTP ${response.status} ${response.statusText}${body ? `\n${body}` : ""}`);
  }
  return response;
}
const post = (path, body) => request(path, {
  method: "POST", headers: { "Content-Type": "application/json", "X-Report-Action": "1" }, body: JSON.stringify(body),
});

function controls() {
  const running = snapshot?.status === "running";
  $("run").disabled = !connected || posting || running || snapshot?.can_run !== true;
  text($("run"), posting ? "正在提交…" : running ? "执行中" : snapshot?.checkpoint_resume === true ? "断点继续" : "运行");
  text($("run-reason"), !connected ? "状态不可用，执行已禁用" : posting ? "等待操作响应" : running ? "正在执行" : snapshot?.can_run !== true ? "当前状态不允许执行" : snapshot.model_mode === "scripted_fixture" ? "当前为脚本模拟" : snapshot.model_mode === "configured" ? "已配置模型" : "由后台检查模型配置");
  $("download").disabled = !connected || downloading || !(snapshot?.content_delivery?.export_ref || snapshot?.delivery?.draft_id);
  $("download-workbook").disabled = !connected || downloading || !snapshot?.content_delivery?.workbook_export_ref;
  for (const entry of issueNodes.values()) {
    entry.submit.disabled = !connected || posting || entry.data.resolved === true || !entry.input.value.trim();
  }
  const replacement = $("source-replaces").value;
  $("upload-submit").disabled = !connected || posting || snapshot?.status === "running" || !$("source-file").files.length
    || Boolean(replacement && !list(snapshot?.sources).some(source => source.id === replacement && source.current === true));
  $("source-file").disabled = posting;
  $("source-replaces").disabled = posting;
  $("correction-submit").disabled = !connected || posting || !$("correction-description").value.trim()
    || !list(snapshot?.results).some(result => result.id === $("correction-result").value);
  $("correction-result").disabled = posting;
  $("correction-description").disabled = posting;
}

function syncOptions(node, choices, placeholder) {
  const signature = JSON.stringify(choices);
  if (node.dataset.options === signature) return;
  const value = node.value;
  const option = (id, title) => { const item = element("option", title); item.value = id; return item; };
  const items = [option("", placeholder), ...choices.map(item => option(item.id, item.title))];
  if (value && !choices.some(item => item.id === value)) {
    const unavailable = option(value, `已不可选：${value}（请重新选择）`);
    unavailable.disabled = true;
    items.push(unavailable);
  }
  node.replaceChildren(...items);
  node.value = value;
  node.dataset.options = signature;
}

function sourceMeta(source) {
  return [source.current === true ? "当前版本" : source.current === false ? "历史版本" : "版本状态未提供",
    `资料 ${source.id}`, source.filename ? `文件：${source.filename}` : "",
    source.replaces_id ? `替换的资料：${source.replaces_id}` : "",
    source.document_id ? `文档：${source.document_id}` : "",
    source.coverage ? `提取范围：${display(source.coverage)}` : "",
    source.bytes !== undefined ? `大小：${source.bytes} 字节` : ""].filter(Boolean).join("\n");
}

function limitationText(source) {
  const value = source.limitations;
  return Array.isArray(value) ? value.map(display).join("\n") : value ? display(value) : "";
}

function resultAnnotations(result, data) {
  const impact = data.impact || data;
  const replacement = result.replacement_id || result.superseded_by || impact.replacements?.[result.id];
  const notes = [];
  if (result.needs_assessment || result.status === "needs_assessment" || list(impact.needs_assessment_result_ids).includes(result.id)) notes.push("影响待评估");
  else if (result.stale || result.status === "stale" || list(impact.stale_result_ids).includes(result.id)) notes.push("已过期，待核对");
  if (result.superseded || result.status === "superseded" || replacement || list(impact.superseded_result_ids).includes(result.id)) notes.push(`已被替代${replacement ? `：${display(replacement)}` : ""}`);
  if (result.replaces_id) notes.push(`替换成果：${result.replaces_id}`);
  return notes.join(" · ");
}

function renderSources(data) {
  const sources = list(data.sources);
  syncOptions($("source-replaces"), sources.filter(source => source.current === true).map(source => ({ id: source.id, title: `${source.title || source.filename || "未命名资料"} · ${source.id}` })), "新增资料（不替换）");
  text($("sources-count"), `${sources.length} 份 · 当前 ${sources.filter(source => source.current === true).length} · 历史 ${sources.filter(source => source.current === false).length}`);
  $("sources-empty").hidden = sources.length > 0;
  text($("sources-empty"), data.sources === undefined ? "后台尚未提供资料目录" : "暂无资料");
  const ids = new Set(sources.map(source => source.id));
  for (const [id, entry] of sourceNodes) {
    if (!ids.has(id)) { entry.root.remove(); sourceNodes.delete(id); }
  }
  for (const source of sources) {
    let entry = sourceNodes.get(source.id);
    if (!entry) {
      entry = { root: element("article", undefined, "source-item"), title: element("h3"), meta: element("p", undefined, "metadata"), limitations: element("p", undefined, "source-limitations"), read: element("button", "阅读正文") };
      entry.read.type = "button";
      entry.read.addEventListener("click", () => openSource(source.id));
      entry.root.append(entry.title, entry.meta, entry.limitations, entry.read);
      sourceNodes.set(source.id, entry);
      $("sources").append(entry.root);
    }
    text(entry.title, source.title || source.filename || "未命名资料");
    text(entry.meta, sourceMeta(source));
    text(entry.limitations, limitationText(source) ? `解析限制：\n${limitationText(source)}` : "");
    entry.limitations.hidden = !limitationText(source);
    entry.read.setAttribute("aria-label", `阅读正文：${source.title || source.id}`);
  }
  const changes = list(data.source_changes);
  const unassessed = data.unassessed_source_changes !== undefined ? list(data.unassessed_source_changes)
    : changes.filter(change => !change.assessment && change.status !== "assessed");
  const count = typeof data.unassessed_source_changes === "number" ? data.unassessed_source_changes : unassessed.length;
  message("source-change-notice", count ? `资料变更未评估：${count} 项。对现有成果的影响尚待核对。\n${unassessed.map(change => typeof change === "string" ? change : `资料 ${change.source_id || change.id}${change.replaces_id ? ` · 替换 ${change.replaces_id}` : " · 新增资料"}`).join("\n")}` : "");
  const signature = JSON.stringify(sources);
  if (sourceSignature && sourceSignature !== signature && pages.search.key) {
    text($("search-status"), "资料目录已变更；当前检索结果可能已过期，请重新检索。");
  }
  sourceSignature = signature;
  const selected = sources.find(source => source.id === pages.source.key);
  if (selected) text($("source-reader-meta"), sourceMeta(selected));
}

function renderCorrections(data) {
  syncOptions($("correction-result"), data.results.map(result => ({ id: result.id, title: `${result.title || translate(result.kind)} · ${result.id}${resultAnnotations(result, data) ? ` · ${resultAnnotations(result, data)}` : ""}` })), "选择成果");
  const corrections = list(data.corrections);
  text($("corrections-count"), `${corrections.length} 项`);
  $("corrections-empty").hidden = corrections.length > 0;
  const signature = JSON.stringify(corrections);
  if (signature === correctionSignature) return;
  correctionSignature = signature;
  $("corrections").replaceChildren(...corrections.map(item => {
    const root = element("article", undefined, "correction-item");
    const status = item.status ? (item.status === "pending" ? "待处理" : translate(item.status)) : item.resolved === true ? "已处理" : "已记录，处理状态未提供";
    root.append(element("h3", status), element("p", item.description, "correction-description"), element("p", [
      item.id ? `请求 ${item.id}` : "", `成果 ${item.result_id || "未提供"}`, item.owner ? `责任方：${display(item.owner)}` : "",
      ...["replacement_id", "replacement_result_id", "replaces_id", "revision_task_id"].filter(key => item[key]).map(key => `${({ replacement_id: "替代成果", replacement_result_id: "替代成果", replaces_id: "原成果", revision_task_id: "修订任务" })[key]}：${display(item[key])}`),
    ].filter(Boolean).join("\n"), "metadata"));
    return root;
  }));
}

function pageControls(kind) {
  const page = pages[kind];
  $(`${kind}-prev`).disabled = page.busy || !page.key || page.offset === 0;
  $(`${kind}-next`).disabled = page.busy || page.next === null;
  $(`${kind}-retry`).hidden = !page.failed;
  $(`${kind}-retry`).disabled = page.busy;
}

function openSource(id, offset = 0) {
  $("source-reader").hidden = false;
  loadPage("source", id, offset);
  $("source-reader").scrollIntoView({ block: "nearest" });
}

async function loadPage(kind, key, offset = 0) {
  const page = pages[kind];
  const serial = ++page.serial;
  Object.assign(page, { key, offset, next: null, busy: true, failed: false });
  const isSource = kind === "source";
  const statusId = isSource ? "source-read-status" : "search-status";
  const errorId = isSource ? "source-read-error" : "search-error";
  const container = $(isSource ? "source-blocks" : "search-matches");
  container.replaceChildren();
  container.setAttribute("aria-busy", "true");
  message(errorId, "");
  text($(statusId), "正在读取…");
  if (isSource) {
    text($("source-reader-heading"), `资料正文 · ${key}`);
    text($("source-reader-meta"), "");
    message("source-reader-limitations", "");
  } else {
    text($("search-method"), ""); text($("search-coverage"), "");
  }
  pageControls(kind);
  try {
    const path = isSource ? `/api/sources/${encodeURIComponent(key)}?offset=${offset}&limit=10`
      : `/api/library/search?q=${encodeURIComponent(key)}&offset=${offset}&limit=10`;
    const data = await (await request(path)).json();
    if (serial !== page.serial) return;
    const rows = isSource ? data.blocks : data.matches;
    const total = isSource ? data.total_blocks : data.total;
    if (!Array.isArray(rows) || !Number.isInteger(total) || total < 0
      || (data.next_offset != null && (!Number.isInteger(data.next_offset) || data.next_offset <= offset))) throw new Error("分页响应格式不符合约定。");
    if (isSource) {
      if (!data.source || data.source.id !== key) throw new Error("资料响应与所选资料不一致。");
      text($("source-reader-heading"), `资料正文 · ${data.source.title || data.source.filename || key}`);
      text($("source-reader-meta"), sourceMeta(data.source));
      message("source-reader-limitations", limitationText(data.source) ? `解析限制：\n${limitationText(data.source)}` : "");
    } else {
      text($("search-method"), `检索词：${key}\n方法：${data.method || "未提供"}`);
      text($("search-coverage"), `覆盖说明：${data.coverage_note || "未提供"}\n未匹配不代表原始资料缺失。`);
    }
    const blocks = rows.map(block => {
      const root = element("article", undefined, "text-block");
      root.append(element("p", `${isSource ? "" : `资料 ${block.source_id} · `}原文块 ${block.ordinal} · ${display(block.locator)}`, "metadata"), element("pre", block.text ?? ""));
      if (!isSource) {
        const read = element("button", "查看原文"); read.type = "button";
        read.addEventListener("click", () => openSource(block.source_id, Math.floor(block.ordinal / 10) * 10));
        root.append(read);
      }
      return root;
    });
    container.replaceChildren(...blocks);
    page.next = data.next_offset ?? null;
    text($(statusId), `${rows.length ? `第 ${offset + 1}–${offset + rows.length} 条 / 共 ${total} 条` : `本页无内容 / 共 ${total} 条`}${page.next !== null ? " · 后续仍有内容" : " · 已到末页"}${isSource && data.coverage_note ? `\n覆盖说明：${data.coverage_note}` : ""}`);
  } catch (error) {
    if (serial !== page.serial) return;
    page.failed = true;
    message(errorId, `${isSource ? "资料读取" : "检索"}失败：${error.message}`);
    text($(statusId), "本页未读取成功。");
  } finally {
    if (serial === page.serial) {
      page.busy = false;
      container.setAttribute("aria-busy", "false");
      pageControls(kind);
    }
  }
}

async function recordAction(feedbackId, action) {
  posting = true; epoch++; controls();
  $(feedbackId).className = "notice";
  message(feedbackId, "正在提交，请等待响应…");
  try { await action(); }
  catch (error) { $(feedbackId).className = "error"; message(feedbackId, `提交失败：${error.message}`); }
  finally {
    epoch++;
    await refreshInFlight;
    await refresh();
    posting = false; controls();
  }
}

function renderTasks(tasks) {
  text($("tasks-count"), `${tasks.length} 条`);
  $("tasks-empty").hidden = tasks.length > 0;
  text($("tasks-empty"), "暂无成果提交记录");
  const signature = JSON.stringify(tasks);
  if (signature === taskSignature) return;
  taskSignature = signature;
  const rows = tasks.map((task) => {
    const row = element("tr");
    const content = element("td");
    content.append(element("p", task.goal));
    if (task.error) content.append(element("p", errorText(task.error), "danger"));
    content.append(element("p", `提交记录 ${task.id}${task.result_id ? ` · 成果 ${task.result_id}` : ""}`, "metadata"));
    const status = element("td");
    const statusLabel = element("span", undefined, "state");
    state(statusLabel, task.status);
    if (task.result_id) text(statusLabel, "已提交");
    else if (task.status === "ready") {
      text(statusLabel, "未形成成果");
      statusLabel.dataset.tone = "neutral";
    }
    status.append(statusLabel);
    row.append(element("td", translate(task.kind)), content, status);
    return row;
  });
  $("tasks").replaceChildren(...rows);
}

function renderResults(results, data) {
  text($("results-count"), `${results.length} 项`);
  $("results-empty").hidden = results.length > 0;
  text($("results-empty"), "暂无成果");
  const ids = new Set(results.map((result) => result.id));
  for (const [id, entry] of resultNodes) {
    if (!ids.has(id)) { entry.root.remove(); resultNodes.delete(id); }
  }
  for (const result of results) {
    let entry = resultNodes.get(result.id);
    if (!entry) {
      entry = { root: element("details", undefined, "result"), title: element("summary"), body: element("pre"), meta: element("p", undefined, "metadata"), annotation: element("p", undefined, "source-limitations") };
      entry.root.append(entry.title, entry.annotation, entry.meta, entry.body);
      resultNodes.set(result.id, entry);
      $("results").append(entry.root);
    }
    const annotations = resultAnnotations(result, data);
    const signature = JSON.stringify([result, annotations]);
    if (entry.signature === signature) continue;
    entry.signature = signature;
    text(entry.title, `${translate(result.kind)} · ${result.title || "未命名成果"}${annotations ? ` · ${annotations}` : ""}`);
    text(entry.annotation, annotations);
    entry.annotation.hidden = !annotations;
    text(entry.body, result.body || "（正文为空）");
    text(entry.meta, [`成果 ${result.id}`, `来源：${list(result.source_ids).join("、") || "未列出"}`, `输入成果：${list(result.input_ids).join("、") || "未列出"}`, result.outcome ? `审核结论：${translate(result.outcome)}` : "", result.target_id ? `审核对象：${result.target_id}` : ""].filter(Boolean).join("\n"));
  }
}

function createIssue(issue) {
  const entry = { root: element("article", undefined, "issue"), title: element("h3"), description: element("p", undefined, "issue-description"), meta: element("p", undefined, "metadata"), form: element("form"), input: element("textarea"), submit: element("button", "提交决定"), feedback: element("p", "", "issue-message"), decision: element("p", "", "metadata"), data: issue };
  const label = element("label", "人工决定");
  entry.root.id = `issue-${issue.id}`;
  entry.root.tabIndex = -1;
  entry.input.id = `decision-${issue.id}`;
  entry.input.required = true;
  label.htmlFor = entry.input.id;
  entry.submit.type = "submit";
  entry.resolved = element("input");
  entry.resolved.type = "checkbox";
  const resolvedLabel = element("label", undefined, "check-label");
  resolvedLabel.append(entry.resolved, element("span", "我确认此问题已处理"));
  entry.feedback.setAttribute("role", "status");
  entry.form.append(label, entry.input, resolvedLabel, entry.submit);
  entry.root.append(entry.title, entry.description, entry.meta, entry.decision, entry.form, entry.feedback);
  entry.input.addEventListener("input", controls);
  entry.form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const value = entry.input.value.trim();
    if (!value || entry.submit.disabled) return;
    posting = true; epoch++; controls();
    text(entry.feedback, "正在提交决定…");
    entry.feedback.classList.remove("danger");
    try {
      await post(`/api/issues/${encodeURIComponent(issue.id)}/decision`, { message: value, resolved: entry.resolved.checked });
      text(entry.feedback, "决定已提交，正在核实状态。");
    } catch (error) {
      text(entry.feedback, error.message);
      entry.feedback.classList.add("danger");
    } finally {
      epoch++;
      await refreshInFlight;
      await refresh();
      const recorded = snapshot?.issues.find(item => item.id === issue.id);
      if (connected && recorded?.decision === value) {
        const continuation = snapshot.checkpoint_resume === true ? "可点击“断点继续”恢复运行。" : "可点击“运行”继续。";
        text(entry.feedback, `${recorded.resolved ? "决定已记录，事项已由人工确认处理。" : "决定已记录，事项仍待处理。"}${continuation}`);
        entry.feedback.classList.remove("danger");
      }
      posting = false; controls();
    }
  });
  return entry;
}

function renderIssues(issues, data) {
  const pausedIds = new Set(interruptions(data).map(item => item.issueId));
  text($("issues-count"), issues.filter((issue) => !issue.resolved).length);
  $("issues-empty").hidden = issues.some((issue) => !issue.resolved);
  text($("issues-empty"), "暂无待处理事项");
  const ids = new Set(issues.map((issue) => issue.id));
  for (const [id, entry] of issueNodes) {
    if (!ids.has(id)) { entry.root.remove(); issueNodes.delete(id); }
  }
  for (const issue of issues) {
    let entry = issueNodes.get(issue.id);
    if (!entry) { entry = createIssue(issue); issueNodes.set(issue.id, entry); $("issues").append(entry.root); }
    entry.data = issue;
    const interrupted = data.status !== "running" && pausedIds.has(issue.id);
    entry.root.dataset.interrupted = String(interrupted);
    text(entry.title, `${interrupted ? "运行中断 · " : ""}${issue.resolved ? "已处理" : "待处理"} · ${translate(issue.category)}`);
    text(entry.description, issue.description);
    text(entry.meta, `问题 ${issue.id}\n来源：${list(issue.source_ids).join("、") || "未列出"}`);
    text(entry.decision, issue.decision ? `已记录决定：${display(issue.decision)}` : "");
    // Keep the form mounted, including its value, selection and focus, across polling.
    entry.input.readOnly = issue.resolved === true;
    entry.resolved.disabled = issue.resolved === true;
  }
}

function goalPreview(goal) {
  const first = String(goal || "").split(/\r?\n/)
    .map(line => line.trim().replace(/^#{1,6}(?:\s+|$)/, "").trim())
    .find(line => line && !/^(?:[-*_]\s*){3,}$/.test(line)) || "未提供编制目标";
  const characters = Array.from(first);
  return characters.length > 80 ? characters.slice(0, 80).join("") + "…" : first;
}

function render(data) {
  text($("project-name"), data.name || "未提供");
  text($("goal"), goalPreview(data.goal));
  text($("goal-full"), data.goal || "未提供编制目标");
  state($("status"), data.status);
  text($("model-mode"), translate(data.model_mode));
  renderRun(data);
  renderTasks(data.tasks);
  renderResults(data.results, data);
  renderIssues(data.issues, data);
  renderSources(data);
  renderCorrections(data);
  if (data.content_delivery?.export_ref) {
    const reviewed = data.content_current_review?.final_review_current === true
      && data.content_current_review?.overall_verdict === "satisfied";
    state($("delivery-status"), reviewed ? "reviewed_draft" : "已选定草稿");
    text($("delivery-info"), `报告草稿已保存，可下载。\n配套 Excel：${data.content_delivery.workbook_export_ref ? "已选定，可下载" : "尚未选定"}。\n${reviewed ? "已记录整体模型评审，不代表工程签审。" : "尚未确认整体评审通过。"}`);
  } else {
    state($("delivery-status"), data.delivery?.status || "暂无交付");
    const deliveryNotes = data.delivery ? resultAnnotations({ ...data.delivery, id: data.delivery.draft_id }, data) : "";
    text($("delivery-info"), data.delivery ? `草稿：${data.delivery.draft_id || "未提供"}\n审核记录：${data.delivery.review_id || "尚无审核记录"}${deliveryNotes ? `\n${deliveryNotes}` : ""}` : "尚无已选定的报告草稿");
  }
  text($("events-count"), `（${data.events.length} 条）`);
  text($("events"), data.events.map((event) => `#${event.sequence} ${event.at} ${event.kind}\n${display(event.data)}`).join("\n\n") || "暂无日志");
}

function refresh() {
  if (refreshInFlight) return refreshInFlight;
  const version = epoch;
  refreshInFlight = (async () => {
    try {
      const response = await request("/api/status");
      const data = await response.json();
      if (version !== epoch) return;
      if (!data || typeof data.status !== "string" || typeof data.can_run !== "boolean" || ![data.tasks, data.results, data.issues, data.events].every(Array.isArray)) throw new Error("/api/status：响应格式不符合约定。");
      render(data); snapshot = data; connected = true;
      message("api-error", "");
      text($("connection"), `已连接 · ${new Date().toLocaleTimeString("zh-CN", { hour12: false })}`);
    } catch (error) {
      if (version !== epoch) return;
      connected = false;
      message("api-error", `状态刷新失败：${error.message}\n${snapshot ? "当前保留上次成功获取的数据。" : "尚未获取有效状态。"}`);
      text($("connection"), "连接异常 · 数据未更新");
    } finally { controls(); }
  })().finally(() => { refreshInFlight = null; });
  return refreshInFlight;
}

$("run").addEventListener("click", async () => {
  if ($("run").disabled) return;
  posting = true; epoch++; controls();
  message("action-notice", "");
  try {
    await post("/api/run", {});
    message("action-notice", "执行请求已接收。");
  } catch (error) { message("action-notice", `执行请求失败：${error.message}`); }
  finally {
    $("action-notice").className = $("action-notice").textContent.startsWith("执行请求失败") ? "error" : "notice";
    epoch++;
    await refreshInFlight;
    await refresh();
    posting = false; controls();
  }
});

async function downloadDelivery(companion = false) {
  const native = snapshot?.content_delivery;
  const draftId = native?.export_ref?.id || snapshot?.delivery?.draft_id;
  const button = companion ? "download-workbook" : "download";
  if (!draftId || $(button).disabled) return;
  downloading = true; controls();
  try {
    const path = native?.export_ref
      ? `/api/content/delivery?expected_export_id=${encodeURIComponent(draftId)}${companion ? "&companion=true" : ""}`
      : `/api/export/${encodeURIComponent(draftId)}`;
    const response = await request(path);
    const url = URL.createObjectURL(await response.blob());
    const link = element("a");
    link.href = url;
    link.download = `report-${String(draftId).replace(/[^a-zA-Z0-9_-]/g, "_")}.${companion ? "xlsx" : "docx"}`;
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    message("action-notice", "报告下载已发起。");
    $("action-notice").className = "notice";
  } catch (error) {
    message("action-notice", `报告下载失败：${error.message}`);
    $("action-notice").className = "error";
  } finally { downloading = false; controls(); }
}
$("download").addEventListener("click", () => downloadDelivery());
$("download-workbook").addEventListener("click", () => downloadDelivery(true));

for (const kind of ["source", "search"]) {
  $(`${kind}-prev`).addEventListener("click", () => loadPage(kind, pages[kind].key, Math.max(0, pages[kind].offset - 10)));
  $(`${kind}-next`).addEventListener("click", () => { if (pages[kind].next !== null) loadPage(kind, pages[kind].key, pages[kind].next); });
  $(`${kind}-retry`).addEventListener("click", () => loadPage(kind, pages[kind].key, pages[kind].offset));
}
$("source-close").addEventListener("click", () => {
  pages.source.serial++;
  Object.assign(pages.source, { key: "", busy: false });
  $("source-reader").hidden = true;
});
$("search-form").addEventListener("submit", event => {
  event.preventDefault();
  const query = $("search-query").value.trim();
  if (query) loadPage("search", query);
});
$("source-file").addEventListener("change", controls);
$("source-replaces").addEventListener("change", controls);
$("correction-result").addEventListener("change", controls);
$("correction-description").addEventListener("input", controls);
$("upload-form").addEventListener("submit", async event => {
  event.preventDefault();
  if ($("upload-submit").disabled) return;
  const file = $("source-file").files[0];
  const replacesId = $("source-replaces").value;
  if (!/\.(txt|md|docx|pdf)$/i.test(file.name)) {
    $("upload-feedback").className = "error";
    message("upload-feedback", "请选择 TXT、MD、DOCX 或 PDF 文件。");
    return;
  }
  await recordAction("upload-feedback", async () => {
    const path = `/api/sources?filename=${encodeURIComponent(file.name)}${replacesId ? `&replaces_id=${encodeURIComponent(replacesId)}` : ""}`;
    const data = await (await request(path, { method: "POST", headers: { "X-Report-Action": "1", "Content-Type": "application/octet-stream" }, body: file })).json();
    if (!data.source?.id || typeof data.reused !== "boolean") throw new Error("上传响应不完整，操作可能已完成，请核实资料目录后再重试。");
    message("upload-feedback", `${data.reused ? "已复用已有上传记录" : "资料已保存，变更影响尚待评估"}：${data.source.title || file.name}\n资料 ${data.source.id}${data.source.replaces_id ? `\n替换的资料：${data.source.replaces_id}` : ""}\n未启动模型或 OCR。${limitationText(data.source) ? `\n解析限制：${limitationText(data.source)}` : ""}`);
    $("source-file").value = "";
    $("source-replaces").value = "";
  });
});
$("correction-form").addEventListener("submit", async event => {
  event.preventDefault();
  if ($("correction-submit").disabled) return;
  const resultId = $("correction-result").value;
  const description = $("correction-description").value.trim();
  await recordAction("correction-feedback", async () => {
    await post("/api/corrections", { result_id: resultId, description });
    message("correction-feedback", `纠错请求已记录，尚不代表成果已修订。\n成果 ${resultId}\n未启动模型。`);
    $("correction-description").value = "";
  });
});

refresh();
setInterval(() => { if (!posting) refresh(); }, 3000);
