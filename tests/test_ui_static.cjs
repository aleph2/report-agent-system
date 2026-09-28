// Static DOM contract tests. Actual browser layout verification belongs to Main.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const root = path.join(__dirname, "..", "src", "report_agent", "static");
const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
const script = fs.readFileSync(path.join(root, "app.js"), "utf8");

function harness() {
  const nodes = new Map();
  class Node {
    constructor(tag = "div") {
      this.tagName = tag;
      this.children = [];
      this.dataset = {};
      this.listeners = new Map();
      this.attributes = {};
      this.classList = new Set();
      this.classList.remove = this.classList.delete;
      this.value = "";
      this.files = [];
      this.disabled = false;
      this.hidden = false;
      this.checked = false;
      this._text = "";
    }
    set id(value) { this._id = value; nodes.set(value, this); }
    get id() { return this._id; }
    set textContent(value) { this._text = String(value); this.children = []; }
    get textContent() { return this._text + this.children.map(child => child.textContent).join(""); }
    set innerHTML(_) { throw new Error("Untrusted content must use textContent"); }
    append(...children) { for (const child of children) { child.parent = this; this.children.push(child); } }
    replaceChildren(...children) { this.children = []; this._text = ""; this.append(...children); }
    remove() { if (this.parent) this.parent.children = this.parent.children.filter(child => child !== this); }
    setAttribute(name, value) { this.attributes[name] = value; }
    addEventListener(name, handler) { this.listeners.set(name, handler); }
    scrollIntoView() {}
  }
  for (const match of html.matchAll(/<([a-z][a-z0-9]*)\b([^>]*\bid="([^"]+)"[^>]*)>/g)) {
    const node = new Node(match[1]);
    node.id = match[3];
    node.hidden = /\bhidden\b/.test(match[2]);
    node.disabled = /\bdisabled\b/.test(match[2]);
    node.open = /\bopen\b/.test(match[2]);
  }
  const context = vm.createContext({
    document: {
      getElementById(id) { assert.ok(nodes.has(id), `Missing DOM node: ${id}`); return nodes.get(id); },
      createElement: tag => new Node(tag), body: new Node("body"),
    },
    fetch: () => new Promise(() => {}),
    AbortSignal, setInterval() {}, setTimeout() {}, URL, console,
  });
  vm.runInContext(script, context);
  vm.runInContext("refreshInFlight = null", context);
  const evaluate = code => vm.runInContext(code, context);
  const show = data => evaluate(`snapshot = ${JSON.stringify(data)}; render(snapshot); connected = true; controls();`);
  return { nodes, context, evaluate, show };
}

function status(values = {}) {
  return { name: "Project", goal: "Compile supplied facts", status: "ready", can_run: true,
    model_mode: "configured", tasks: [], results: [], issues: [], events: [], sources: [], ...values };
}

function event(sequence, kind, data = {}) {
  return { sequence, kind, data, at: "2026-09-27 12:00:00" };
}

test("long markdown goal has a short preview and preserves full original text in closed native details", () => {
  const ui = harness();
  const goal = "\r\n# \r\n---\r\n## 编制桥梁报告\r\n\r\n" + "- 保留原始范围、依据和限制。\r\n".repeat(40);
  assert.ok(goal.length > 480);
  const data = status({ goal, status: "running", last_error: { message: "Visible diagnostic" } });
  ui.show(data);
  assert.equal(ui.nodes.get("goal").textContent, "编制桥梁报告");
  assert.equal(ui.nodes.get("goal-full").textContent, goal);
  const details = ui.nodes.get("goal-details");
  assert.equal(details.tagName, "details");
  assert.equal(details.open, false);
  assert.match(html, /<details id="goal-details"><summary>完整编制目标<\/summary><p id="goal-full">/);
  assert.equal(ui.nodes.get("status").textContent, "执行中");
  assert.equal(ui.nodes.get("system-error").hidden, false);
  details.open = true;
  ui.show(data);
  assert.equal(ui.nodes.get("goal-details"), details);
  assert.equal(details.open, true);
  assert.equal(ui.nodes.get("goal-full").textContent, goal);
  assert.equal(ui.evaluate("snapshot.goal"), goal);
});

test("single long goal line is shortened only in preview, with original text kept safe and intact", () => {
  const ui = harness();
  const goal = "目标内容".repeat(60) + '<script>alert("not markup")</script>';
  ui.show(status({ goal }));
  assert.equal(Array.from(ui.nodes.get("goal").textContent).length, 81);
  assert.ok(ui.nodes.get("goal").textContent.endsWith("…"));
  assert.equal(ui.nodes.get("goal-full").textContent, goal);
  assert.equal(ui.nodes.get("goal-full").children.length, 0);
  assert.equal(ui.evaluate("snapshot.goal"), goal);
  ui.show(status({ goal: "\n \n" }));
  assert.equal(ui.nodes.get("goal").textContent, "未提供编制目标");
  assert.equal(ui.nodes.get("goal-full").textContent, "\n \n");
});

test("ready placeholders are labeled as no result without removing history or changing execution state", () => {
  const ui = harness();
  const tasks = [0, 1, 2].map(i => ({ id: `pending-${i}`, status: "ready", goal: `Prior attempt ${i}`, kind: "draft", result_id: null }));
  tasks.push({ id: "committed", status: "ready", goal: "Stored", kind: "draft", result_id: "draft-1" });
  tasks.push({ id: "failed", status: "failed", goal: "Failed attempt", kind: "draft", result_id: null });
  ui.show(status({ status: "running", tasks }));
  const rows = ui.nodes.get("tasks").children;
  assert.equal(rows.length, 5);
  for (const row of rows.slice(0, 3)) {
    assert.equal(row.children[2].textContent, "未形成成果");
    assert.equal(row.children[2].children[0].dataset.tone, "neutral");
  }
  assert.equal(rows[3].children[2].textContent, "已提交");
  assert.equal(rows[4].children[2].textContent, "执行失败");
  assert.match(ui.nodes.get("tasks").textContent, /Prior attempt 2/);
  assert.equal(ui.nodes.get("status").textContent, "执行中");
  assert.equal(ui.evaluate("snapshot.tasks[0].status"), "ready");
});

test("commit receipts are never presented as whole-run progress", () => {
  assert.doesNotMatch(html, /<progress\b|id="(?:completed|task-total|progress)"/);
  const ui = harness();
  ui.show(status({ status: "running", tasks: Array.from({ length: 40 }, (_, i) => ({
    id: String(i), kind: "draft", goal: "Saved output", status: "completed", result_id: `r${i}`,
  })) }));
  assert.equal(ui.nodes.get("tasks-count").textContent, "40 条");
  assert.equal(ui.nodes.get("status").textContent, "执行中");
  assert.match(ui.nodes.get("activity").textContent, /运行中/);
  assert.doesNotMatch(ui.nodes.get("activity").textContent, /40|100%|ETA/);
  assert.equal(ui.nodes.get("run").disabled, true);
});

test("resume label comes only from checkpoint_resume and controls remain server-bound", () => {
  const ui = harness();
  ui.show(status({ checkpoint_resume: true, status: "failed", last_error: { message: "Saved failure" } }));
  assert.equal(ui.nodes.get("run").textContent, "断点继续");
  assert.equal(ui.nodes.get("run").disabled, false);
  assert.match(ui.nodes.get("system-error").textContent, /Saved failure/);
  ui.show(status({ checkpoint_resume: true, can_run: false }));
  assert.equal(ui.nodes.get("run").disabled, true);
  ui.show(status({ status: "failed", checkpoint_resume: false }));
  assert.equal(ui.nodes.get("run").textContent, "运行");
  ui.evaluate("connected = false; controls()");
  assert.equal(ui.nodes.get("run").disabled, true);
});

test("active tools are matched by role and tool_call_id and cleared at run boundaries", () => {
  const ui = harness();
  const events = [event(1, "deep_run_started", { resume: true }),
    event(2, "deep_tool_start", { role: "writer", tool: "read_sources", tool_call_id: "a" }),
    event(3, "deep_tool_start", { role: "reviewer", tool: "read_result", tool_call_id: "b" }),
    event(4, "deep_tool_end", { role: "writer", tool: "read_sources", tool_call_id: "a" })];
  ui.show(status({ status: "running", events }));
  assert.match(ui.nodes.get("activity").textContent, /审核 · read_result/);
  assert.doesNotMatch(ui.nodes.get("activity").textContent, /read_sources/);
  assert.match(ui.nodes.get("run-history").textContent, /从断点继续运行/);
  ui.show(status({ status: "ready", events: [...events, event(5, "deep_run_finished")] }));
  assert.equal(ui.nodes.get("activity").textContent, "本轮运行已结束");
  ui.show(status({ status: "running", events: [...events, event(6, "deep_run_started")] }));
  assert.doesNotMatch(ui.nodes.get("activity").textContent, /read_result/);
});

test("bounded or unpaired events do not invent active work or successful outcomes", () => {
  const ui = harness();
  ui.show(status({ status: "running", events: [event(9, "deep_tool_start", { role: "writer", tool: "read_result" }),
    event(10, "deep_tool_end", { role: "writer", tool: "read_result" })] }));
  assert.match(ui.nodes.get("activity").textContent, /等待下一条/);
  assert.match(ui.nodes.get("run-history").textContent, /已返回/);
  assert.doesNotMatch(ui.nodes.get("run-history").textContent, /成功|审核通过/);
  ui.show(status({ status: "failed", events: [event(11, "deep_run_error", { type: "TransportError" })] }));
  assert.match(ui.nodes.get("system-error").textContent, /TransportError/);
  ui.show(status({ events: [event(11, "deep_run_error", { type: "TransportError" }), event(12, "deep_run_finished")] }));
  assert.equal(ui.nodes.get("system-error").hidden, true);
});

test("rejected submissions remain readable action errors even when followed by tool end", () => {
  const ui = harness();
  const calls = Array.from({ length: 3 }, (_, i) => {
    const data = { role: "coordinator", tool: "submit_result", tool_call_id: `submit-${i}` };
    return [event(i * 3, "deep_tool_start", data),
      event(i * 3 + 1, "deep_tool_rejected", { ...data, type: "ActionRejected",
        message: `Submission ${i} lacks valid evidence`, http_status: 409 }),
      event(i * 3 + 2, "deep_tool_end", data)];
  }).flat();
  ui.show(status({ status: "running", events: calls }));
  const history = ui.nodes.get("run-history");
  assert.match(history.textContent, /统筹 · submit_result · 调用被拒绝/);
  assert.match(history.textContent, /ActionRejected · HTTP 409 · Submission 2 lacks valid evidence/);
  const errors = history.children.map(row => row.children[1]).filter(label => label.className === "danger");
  assert.equal(errors.length, 2); // Last six events retain the two most recent rejections.
  assert.equal(ui.nodes.get("status").textContent, "执行中");
  assert.equal(ui.nodes.get("system-error").hidden, true);
  assert.doesNotMatch(ui.nodes.get("activity").textContent, /submit_result/);
});

test("rejection closes only the matching active call without requiring a tool end", () => {
  const ui = harness();
  ui.show(status({ status: "running", events: [
    event(1, "deep_tool_start", { role: "writer", tool: "submit_result", tool_call_id: "same-id" }),
    event(2, "deep_tool_start", { role: "reviewer", tool: "read_result", tool_call_id: "same-id" }),
    event(3, "deep_tool_rejected", { role: "writer", tool: "submit_result", tool_call_id: "same-id",
      message: "Result owner mismatch" }),
  ] }));
  assert.equal(ui.nodes.get("activity").textContent, "审核 · read_result");
  assert.match(ui.nodes.get("run-history").textContent, /Result owner mismatch/);
  assert.equal(ui.nodes.get("system-error").hidden, true);
});

test("standalone rejection tails render safely without changing the report status", () => {
  const ui = harness();
  const reason = '<img src=x onerror="alert(1)">';
  ui.show(status({ status: "needs_attention", events: [event(1, "deep_tool_rejected", { message: reason })] }));
  const label = ui.nodes.get("run-history").children[0].children[1];
  assert.equal(label.textContent, `智能体 · 工具 · 调用被拒绝 · ${reason}`);
  assert.equal(label.children.length, 0);
  assert.equal(label.className, "danger");
  assert.equal(ui.nodes.get("status").textContent, "需要处理");
  assert.equal(ui.nodes.get("system-error").hidden, true);
});

test("activity translates known roles and preserves descriptive actions", () => {
  const ui = harness();
  ui.show(status({ status: "running", activity: "coordinator" }));
  assert.equal(ui.nodes.get("activity").textContent, "统筹");
  ui.show(status({ status: "running", activity: "正在核对报告来源" }));
  assert.equal(ui.nodes.get("activity").textContent, "正在核对报告来源");
});

test("interrupts link to exact issue, retain decision drafts during polling, and tolerate missing issues", () => {
  const ui = harness();
  const issue = { id: "issue-1", category: "source_missing", description: "Confirm the date", resolved: false };
  const data = status({ status: "needs_human", checkpoint_resume: true, issues: [issue],
    native_interrupts: [{ id: "pause-1", value: { issue_id: issue.id } }] });
  ui.show(data);
  assert.equal(ui.nodes.get("interrupt-panel").hidden, false);
  assert.equal(ui.nodes.get("interrupts").children[0].children[1].href, "#issue-issue-1");
  const input = ui.nodes.get("decision-issue-1");
  input.value = "Keep this as a limitation";
  ui.show(data);
  assert.equal(ui.nodes.get("decision-issue-1"), input);
  assert.equal(input.value, "Keep this as a limitation");
  ui.show({ ...data, issues: [{ ...issue, decision: input.value }] });
  assert.match(ui.nodes.get("interrupt-heading").textContent, /等待恢复/);
  ui.show({ ...data, issues: [] });
  assert.match(ui.nodes.get("interrupts").textContent, /尚未获取/);
  ui.show(status());
  assert.equal(ui.nodes.get("interrupt-panel").hidden, true);
});

test("decision POST records intent but never starts the runtime", async () => {
  const ui = harness();
  const issue = { id: "i/1", category: "source_missing", description: "Confirm scope", resolved: false };
  const data = status({ status: "needs_human", checkpoint_resume: true, issues: [issue],
    native_interrupts: [{ issue_id: issue.id }] });
  ui.show(data);
  ui.nodes.get("decision-i/1").value = "Keep the gap explicit";
  ui.evaluate("controls()");
  const requests = [];
  ui.context.fetch = async (url, options) => {
    requests.push({ url, options });
    return { ok: true, json: async () => ({ ...data, issues: [{ ...issue, decision: "Keep the gap explicit" }] }) };
  };
  await ui.evaluate('issueNodes.get("i/1").form.listeners.get("submit")({ preventDefault() {} })');
  assert.deepEqual(requests.map(request => request.url), ["/api/issues/i%2F1/decision", "/api/status"]);
  assert.equal(requests[0].options.headers["X-Report-Action"], "1");
  assert.match(ui.evaluate('issueNodes.get("i/1").feedback.textContent'), /断点继续/);
  assert.equal(ui.nodes.get("run").disabled, false);
});

test("checkpoint continuation requires an explicit run click and uses the existing endpoint", async () => {
  const ui = harness();
  ui.show(status({ checkpoint_resume: true, status: "interrupted" }));
  const requests = [];
  ui.context.fetch = async (url, options) => {
    requests.push({ url, options });
    return { ok: true, json: async () => status({ status: "running", can_run: false, checkpoint_resume: true }) };
  };
  assert.equal(requests.length, 0);
  await ui.nodes.get("run").listeners.get("click")();
  assert.deepEqual(requests.map(request => request.url), ["/api/run", "/api/status"]);
  assert.equal(requests[0].options.method, "POST");
  assert.equal(requests[0].options.body, "{}");
  assert.equal(ui.nodes.get("run").disabled, true);
  assert.equal(ui.nodes.get("run").textContent, "执行中");
});

test("failed status polling preserves visible data and disables execution", async () => {
  const ui = harness();
  ui.show(status({ name: "Retained project", checkpoint_resume: true }));
  ui.context.fetch = async () => { throw new Error("offline"); };
  await ui.evaluate("refresh()");
  assert.equal(ui.nodes.get("project-name").textContent, "Retained project");
  assert.equal(ui.nodes.get("run").disabled, true);
  assert.equal(ui.nodes.get("api-error").hidden, false);
  assert.match(ui.nodes.get("api-error").textContent, /保留上次/);
});

test("summary renders text blocks only and outcome impact is not a forced rewrite", () => {
  const ui = harness();
  const unsafe = '<img src=x onerror="alert(1)">';
  ui.show(status({ agent_summary: [{ type: "reasoning", text: "PRIVATE_REASONING" }, { type: "text", text: unsafe }],
    results: [{ id: "r1", kind: "draft", title: unsafe, body: unsafe, needs_assessment: true }],
    impact: { needs_assessment_result_ids: ["r1"] } }));
  assert.equal(ui.nodes.get("agent-summary").textContent, unsafe);
  assert.equal(ui.nodes.get("agent-summary-panel").hidden, false);
  assert.match(ui.nodes.get("results").textContent, /影响待评估/);
  assert.doesNotMatch(ui.nodes.get("results").textContent, /必须重写/);
  ui.show(status());
  assert.equal(ui.nodes.get("agent-summary-panel").hidden, true);
});

test("older status payloads remain renderable and fixture warnings remain visible", () => {
  const ui = harness();
  ui.show(status({ model_mode: "scripted_fixture" }));
  assert.match(ui.nodes.get("model-mode").textContent, /脚本模拟/);
  assert.match(ui.nodes.get("run-reason").textContent, /脚本模拟/);
  assert.equal(ui.nodes.get("run").textContent, "运行");
  assert.equal(ui.nodes.get("runtime").textContent, "");
  assert.match(html, /不代表工程签审/);
});
