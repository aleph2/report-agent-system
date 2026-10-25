"use strict";
(() => {
  const find = id => document.getElementById(id);
  const node = (tag, value) => { const item = document.createElement(tag); item.textContent = value; return item; };
  let reports = [], evidence = [], busy = false;
  async function api(path, body) {
    const response = await fetch(path, body === undefined ? {} : {method: "POST", headers: {
      "Content-Type": "application/json", "X-Report-Action": "1"}, body: JSON.stringify(body)});
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail === "LEARNING_NOT_CONFIGURED" ? "反馈学习尚未启用，请由项目管理员配置客户与经验库。" : JSON.stringify(result.detail));
    return result;
  }
  const report = () => reports[Number(find("learning-report").value)];
  const target = () => report()?.targets[Number(find("learning-target").value)];
  function preview() { find("learning-preview").textContent = JSON.stringify(target()?.payload || {}, null, 2); }
  function targets() {
    find("learning-target").replaceChildren(...(report()?.targets || []).map((item, index) => {
      const label = item.ref.type === "DocumentSnapshot" ? "整份报告" : item.label;
      const option = node("option", `${label} · ${item.ref.id.slice(0, 8)} · v${item.ref.version}`); option.value = index; return option;
    }));
    find("learning-submit").disabled = !target() || busy;
    preview();
  }
  async function action(button, work) {
    if (busy) return;
    busy = true; button.disabled = true;
    try { await work(); await refresh(); }
    catch (error) { find("learning-notice").textContent = `操作未确认成功：${error.message}。请刷新核对记录后再试。`; }
    finally { busy = false; button.disabled = false; find("learning-submit").disabled = !target(); }
  }
  async function refresh() {
    find("learning-refresh").disabled = true;
    try {
      const [data, content, sources] = await Promise.all([api("/api/learning"), api("/api/learning/reports"), api("/api/learning/evidence")]);
      const previous = JSON.stringify(report()?.ref);
      reports = content.reports;
      find("learning-report").replaceChildren(...reports.map((item, index) => {
        const option = node("option", `${item.created_at} · ${item.ref.id.slice(0, 8)} · v${item.ref.version}`);
        option.value = index; return option;
      }));
      const selected = reports.findIndex(item => JSON.stringify(item.ref) === previous);
      find("learning-report").value = selected >= 0 ? selected : Math.max(0, reports.length - 1);
      targets();
      evidence = sources.items;
      find("learning-evidence-list").replaceChildren(...evidence.map((item, index) => {
        const row = node("div", ""), label = node("label", ""), check = document.createElement("input");
        check.type = "checkbox"; check.value = index; check.name = "learning-evidence";
        label.append(check, document.createTextNode(`${item.label} · ${item.ref.id.slice(0, 8)} · v${item.ref.version}`));
        const detail = node("details", ""); detail.append(node("summary", "查看依据摘录"), node("pre", item.excerpt || "此版本无文本摘录"));
        row.append(label, detail); return row;
      }));
      find("learning-panel").hidden = false;
      find("learning-status").textContent = `${data.feedback.length} 条反馈 · ${data.experience.length} 个经验版本${reports.length ? "" : " · 尚无可反馈的报告快照"}`;
      find("learning-feedback-list").replaceChildren(...data.feedback.map(item => node("p", `${item.correction} · ${item.evidence?.length || 0} 个上下文/依据引用`)));
      find("learning-experiences").replaceChildren(...data.experience.map(item => {
        const card = node("article", "");
        card.append(node("h4", `${item.title} · v${item.version} · ${item.active ? "已发布" : "未生效"}`),
          node("p", item.strategy), node("p", `适用条件：${item.conditions}`), node("p", `验证要求：${item.verification}`));
        const form = node("form", ""), label = node("label", "本次发布或撤回的理由"), reason = document.createElement("input");
        reason.required = true; label.append(reason);
        const button = node("button", item.active ? "撤回此经验" : "发布此版本"); button.type = "submit";
        form.append(label, button);
        form.addEventListener("submit", event => {
          event.preventDefault();
          action(button, async () => {
            await api(`/api/learning/experience/${encodeURIComponent(item.id)}/release`, {version: item.active ? null : item.version, reason: reason.value});
            find("learning-notice").textContent = item.active ? "经验已撤回。" : `已发布版本 ${item.version}。`;
          });
        });
        card.append(form);
        if (!data.experience.some(other => other.id === item.id && other.version > item.version)) {
          const details = node("details", ""), edit = node("form", ""), fields = {};
          details.append(node("summary", "修改并保存为新候选版本"));
          for (const [key, caption] of [["title", "经验标题"], ["strategy", "经验内容"], ["conditions", "适用条件"], ["verification", "验证要求"]]) {
            const label = node("label", caption), input = document.createElement(key === "title" ? "input" : "textarea");
            input.required = true; input.value = item[key]; fields[key] = input;
            label.append(input); edit.append(label);
          }
          const save = node("button", "保存新候选版本"); save.type = "submit"; edit.append(save);
          edit.addEventListener("submit", event => {
            event.preventDefault();
            action(save, async () => {
              await api(`/api/learning/experience/${encodeURIComponent(item.id)}/revision`, {
                expected_version: item.version, ...Object.fromEntries(Object.entries(fields).map(([key, input]) => [key, input.value]))});
              find("learning-notice").textContent = "已保存新候选版本，尚未发布；原发布状态保持不变。";
            });
          });
          details.append(edit); card.append(details);
        }
        return card;
      }));
    } catch (error) { find("learning-status").textContent = error.message; }
    finally { find("learning-refresh").disabled = false; }
  }
  find("learning-report").addEventListener("change", targets);
  find("learning-target").addEventListener("change", preview);
  find("learning-refresh").addEventListener("click", refresh);
  find("learning-form").addEventListener("submit", event => {
    event.preventDefault();
    if (!target()) return;
    const body = {snapshot_ref: report().ref, target_ref: target().ref,
      correction: find("learning-correction").value, evidence_refs: [target().ref]};
    for (const check of find("learning-evidence-list").querySelectorAll("input:checked")) {
      const ref = evidence[Number(check.value)].ref;
      if (!body.evidence_refs.some(existing => JSON.stringify(existing) === JSON.stringify(ref))) body.evidence_refs.push(ref);
    }
    action(find("learning-submit"), async () => {
      await api("/api/learning/feedback", body);
      find("learning-correction").value = "";
      find("learning-notice").textContent = "反馈已保存，待处理；报告尚未修订。";
    });
  });
  refresh();
})();
