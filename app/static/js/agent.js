/* AI Agent 前端：会话管理、消息渲染、fetch + ReadableStream 手动解析 SSE（EventSource 不支持 POST） */
(function () {
  const conversations = [...window.INIT_CONVERSATIONS];
  // 进入页面默认停留在一个新会话窗口，不自动选中历史会话；首条消息发送时才惰性创建后端会话
  let currentId = null;
  let streaming = false;
  let lastUserText = "";

  const SIDEBAR_KEY = "sh.agent.sessions.collapsed";

  const els = {
    workbench: document.getElementById("agentWorkbench"),
    sessionList: document.getElementById("sessionList"),
    btnNewChat: document.getElementById("btnNewChat"),
    btnToggleSessions: document.getElementById("btnToggleSessions"),
    chatTitle: document.getElementById("chatTitle"),
    chatBody: document.getElementById("chatBody"),
    chatModel: document.getElementById("chatModel"),
    messageScroll: document.getElementById("messageScroll"),
    messageList: document.getElementById("messageList"),
    chatWelcome: document.getElementById("chatWelcome"),
    welcomeTitle: document.getElementById("welcomeTitle"),
    chatInput: document.getElementById("chatInput"),
    btnSend: document.getElementById("btnSend"),
  };

  /* ---------- 欢迎语 ---------- */
  function greeting() {
    const h = new Date().getHours();
    if (h < 6) return "夜深了";
    if (h < 11) return "上午好";
    if (h < 14) return "中午好";
    if (h < 18) return "下午好";
    return "晚上好";
  }

  function syncWelcome(show) {
    els.chatWelcome.style.display = show ? "" : "none";
    els.chatBody.classList.toggle("is-empty", show);
  }

  function current() {
    return conversations.find(c => c.id === currentId) || null;
  }

  /* ---------- 会话列表 ---------- */
  function renderSessions() {
    if (!conversations.length) {
      els.sessionList.innerHTML = '<div class="chat-empty">暂无会话</div>';
      return;
    }
    els.sessionList.innerHTML = conversations.map(c =>
      '<div class="session-item' + (c.id === currentId ? ' active' : '') + '" data-id="' + c.id + '">' +
        '<span class="s-title">' + App.escapeHtml(c.title) + '</span>' +
        '<span class="s-actions">' +
          '<button class="s-act" data-act="rename" title="重命名" type="button">✎</button>' +
          '<button class="s-act danger" data-act="delete" title="删除" type="button">✕</button>' +
        '</span>' +
      '</div>'
    ).join("");
  }

  function syncModelSelect(conv) {
    els.chatModel.value = (conv && conv.model_name) || "";
  }

  /* ---------- 消息渲染 ---------- */
  function bubbleHtml(role, content, isStreaming) {
    if (role === "assistant") {
      return '<div class="msg-row assistant">' +
        '<div class="msg-avatar">AI</div>' +
        '<div class="msg-body"><div class="msg-bubble' + (isStreaming ? ' streaming' : '') + '">' +
        renderMarkdown(content) + '</div></div></div>';
    }
    return '<div class="msg-row user"><div class="msg-body"><div class="msg-bubble">' +
      App.escapeHtml(content) + '</div></div></div>';
  }

  function appendBubble(role, content, isStreaming) {
    const empty = els.messageList.querySelector(".chat-empty");
    if (empty) empty.remove();
    const wrap = document.createElement("div");
    wrap.innerHTML = bubbleHtml(role, content, isStreaming);
    const node = wrap.firstElementChild;
    els.messageList.appendChild(node);
    scrollBottom();
    return node;
  }

  function scrollBottom() {
    els.messageScroll.scrollTop = els.messageScroll.scrollHeight;
  }

  async function loadMessages(conv) {
    if (!conv) {
      els.messageList.innerHTML = "";
      syncWelcome(true);
      return;
    }
    try {
      const res = await App.api("/api/agent/conversations/" + conv.id + "/messages");
      if (!res.messages.length) {
        els.messageList.innerHTML = "";
        syncWelcome(true);
        return;
      }
      els.messageList.innerHTML = res.messages.map(m => bubbleHtml(m.role, m.content, false)).join("");
      syncWelcome(false);
      scrollBottom();
    } catch (err) {
      App.toast(err.message, true);
    }
  }

  async function selectConversation(id) {
    if (streaming) { App.toast("请等待当前回复完成"); return; }
    currentId = id;
    const conv = current();
    els.chatTitle.textContent = conv ? conv.title : "";
    syncModelSelect(conv);
    renderSessions();
    await loadMessages(conv);
  }

  /* ---------- 新建 / 重命名 / 删除 ---------- */
  async function createConversation() {
    const conv = await App.api("/api/agent/conversations", {
      method: "POST",
      body: { model_name: els.chatModel.value || null },
    });
    conversations.push(conv);
    renderSessions();
    return conv;
  }

  async function ensureConversation() {
    const conv = current();
    if (conv) return conv;
    const created = await createConversation();
    currentId = created.id;
    return created;
  }

  async function newChat() {
    if (streaming) return;
    try {
      const conv = await createConversation();
      await selectConversation(conv.id);
    } catch (err) {
      App.toast(err.message, true);
    }
  }

  function startRename(id) {
    const item = els.sessionList.querySelector('.session-item[data-id="' + id + '"]');
    const conv = conversations.find(c => c.id === id);
    if (!item || !conv) return;
    const titleEl = item.querySelector(".s-title");
    const input = document.createElement("input");
    input.className = "s-rename-input input";
    input.value = conv.title;
    titleEl.replaceWith(input);
    input.focus();
    input.select();

    let settled = false;
    async function commit() {
      if (settled) return;
      settled = true;
      const val = input.value.trim();
      if (val && val !== conv.title) {
        try {
          const updated = await App.api("/api/agent/conversations/" + id, {
            method: "PUT",
            body: { title: val },
          });
          conv.title = updated.title;
          if (currentId === id) els.chatTitle.textContent = conv.title;
        } catch (err) {
          App.toast(err.message, true);
        }
      }
      renderSessions();
    }

    input.addEventListener("keydown", e => {
      if (e.key === "Enter") { e.preventDefault(); commit(); }
      else if (e.key === "Escape") { settled = true; renderSessions(); }
    });
    input.addEventListener("blur", commit);
  }

  async function remove(id) {
    const conv = conversations.find(c => c.id === id);
    if (!conv) return;
    const ok = await App.confirmDialog({
      title: "删除会话",
      message: "确定删除「" + conv.title + "」？全部消息将一并删除，不可恢复。",
      confirmText: "删除",
    });
    if (!ok) return;
    try {
      await App.api("/api/agent/conversations/" + id, { method: "DELETE" });
      conversations.splice(conversations.findIndex(c => c.id === id), 1);
      if (currentId === id) {
        currentId = conversations.length ? conversations[0].id : null;
        const c = current();
        els.chatTitle.textContent = c ? c.title : "";
        syncModelSelect(c);
        await loadMessages(c);
      }
      renderSessions();
    } catch (err) {
      App.toast(err.message, true);
    }
  }

  /* ---------- 安全的极简 Markdown 渲染（先转义，后白名单替换，无 XSS） ---------- */
  function splitMdRow(rowStr) {
    let s = rowStr.trim();
    if (s.startsWith("|")) s = s.slice(1);
    if (s.endsWith("|")) s = s.slice(0, -1);
    return s.split("|").map(c => c.trim());
  }

  function isTableSep(s) {
    return s.includes("-") && /^[\s:|-]+$/.test(s);
  }

  function inlineMd(s) {
    s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    s = s.replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
    return s;
  }

  function renderMarkdown(src) {
    const lines = App.escapeHtml(src).split("\n");
    const out = [];
    let i = 0;
    let list = null;
    const closeList = () => { if (list) { out.push("</" + list + ">"); list = null; } };

    while (i < lines.length) {
      const t = lines[i].trim();

      if (t.startsWith("|") && i + 1 < lines.length && isTableSep(lines[i + 1].trim())) {
        closeList();
        const header = splitMdRow(t);
        i += 2;
        const body = [];
        while (i < lines.length && lines[i].trim().startsWith("|")) {
          body.push(splitMdRow(lines[i].trim()));
          i++;
        }
        let table = '<table class="md-table"><thead><tr>' +
          header.map(c => "<th>" + inlineMd(c) + "</th>").join("") + "</tr></thead>";
        if (body.length) {
          table += "<tbody>" + body.map(r =>
            "<tr>" + r.map(c => "<td>" + inlineMd(c) + "</td>").join("") + "</tr>").join("") + "</tbody>";
        }
        out.push(table + "</table>");
        continue;
      }

      const h = /^(#{1,4})\s+(.*)$/.exec(t);
      if (h) {
        closeList();
        out.push("<h" + h[1].length + ' class="md-h">' + inlineMd(h[2]) + "</h" + h[1].length + ">");
        i++;
        continue;
      }

      if (/^[-•]\s+/.test(t)) {
        if (list !== "ul") { closeList(); out.push('<ul class="md-ul">'); list = "ul"; }
        out.push("<li>" + inlineMd(t.replace(/^[-•]\s+/, "")) + "</li>");
        i++;
        continue;
      }

      if (/^\d+[.)]\s+/.test(t)) {
        if (list !== "ol") { closeList(); out.push('<ol class="md-ol">'); list = "ol"; }
        out.push("<li>" + inlineMd(t.replace(/^\d+[.)]\s+/, "")) + "</li>");
        i++;
        continue;
      }

      if (t === "") { closeList(); i++; continue; }

      closeList();
      out.push('<p class="md-p">' + inlineMd(t) + "</p>");
      i++;
    }
    closeList();
    return out.join("");
  }

  /* ---------- 工具状态与明细 ---------- */
  const TOOL_LABELS = {
    get_workout_summary: "运动汇总",
    get_fitness_records: "健身记录",
    get_swim_records: "游泳记录",
    get_dance_records: "舞蹈记录",
    get_body_measurements: "身材数据",
    get_state_records: "状态记录",
    get_cycle_records: "生理周期",
    get_profile_info: "个人资料",
  };

  // 明细只做展示：全量结果可能很长，表格最多铺 50 行，其余交给正文结论
  const MAX_DETAIL_ROWS = 50;

  function fmtDuration(s) {
    if (s == null) return "—";
    return Math.floor(s / 60) + "分" + (s % 60) + "秒";
  }

  function fmtStatus(s) {
    if (s === "planned") return "计划";
    if (s === "recorded") return "记录";
    return s == null ? "—" : String(s);
  }

  function rangeLabel(d) {
    const r = d && d.range;
    if (!r) return "";
    if (!r.start && !r.end) return "（全部历史）";
    return "（" + (r.start || "—") + " ~ " + (r.end || "—") + "）";
  }

  function detailTable(headers, rows) {
    const head = headers.map(h => "<th>" + App.escapeHtml(h) + "</th>").join("");
    const body = rows.map(r =>
      "<tr>" + r.map(c => "<td>" + (c == null ? "—" : App.escapeHtml(String(c))) + "</td>").join("") + "</tr>"
    ).join("");
    return '<table class="detail-table"><thead><tr>' + head + "</tr></thead><tbody>" + body + "</tbody></table>";
  }

  function cappedTable(headers, rows) {
    const shown = rows.slice(0, MAX_DETAIL_ROWS);
    const more = rows.length > MAX_DETAIL_ROWS
      ? '<p class="detail-more">共 ' + rows.length + " 条，此处仅展示前 " + MAX_DETAIL_ROWS + " 条</p>"
      : "";
    return detailTable(headers, shown) + more;
  }

  function renderToolDetail(run) {
    const d = run.data;
    if (!d || typeof d !== "object") return null;
    const details = document.createElement("details");
    details.className = "tool-detail";
    let summaryText = run.label;
    let inner = "";

    if (run.tool === "get_workout_summary") {
      summaryText += "明细" + rangeLabel(d);
      const labels = d.sport_labels || {};
      const per = d.per_sport || {};
      const rows = Object.keys(per).map(k => {
        const s = per[k];
        return [labels[k] || k, s.records, s.plans, s.minutes, s.kcal];
      });
      if (d.total) rows.push(["合计", d.total.records, d.total.plans, d.total.minutes, d.total.kcal]);
      inner = detailTable(["运动", "记录", "计划", "时长(分)", "热量(千卡)"], rows);
    } else if (run.tool === "get_fitness_records") {
      summaryText += "明细" + rangeLabel(d) + "（" + (d.count || 0) + " 条）";
      const rows = (d.records || []).map(r => [
        r.date, fmtStatus(r.status), r.item_count, r.total_sets, r.total_volume,
        fmtDuration(r.duration_s), r.remark || r.body_parts_summary || "—",
      ]);
      inner = cappedTable(["日期", "状态", "动作数", "总组数", "容量(kg)", "时长", "备注"], rows);
    } else if (run.tool === "get_swim_records") {
      summaryText += "明细" + rangeLabel(d) + "（" + (d.count || 0) + " 条）";
      const rows = (d.records || []).map(r => [
        r.date, fmtStatus(r.status), r.distance_m, fmtDuration(r.duration_s),
        r.pace, r.avg_stroke_rate, r.main_stroke_label || r.main_stroke, r.calories,
      ]);
      inner = cappedTable(["日期", "状态", "距离(m)", "时长", "配速", "划频", "泳姿", "热量"], rows);
    } else if (run.tool === "get_dance_records") {
      summaryText += "明细" + rangeLabel(d) + "（" + (d.count || 0) + " 条）";
      const rows = (d.records || []).map(r => [
        r.date, fmtStatus(r.status), r.dance_type, r.teacher, r.style,
        fmtDuration(r.duration_s), r.stars, r.calories,
      ]);
      inner = cappedTable(["日期", "状态", "舞种", "老师", "风格", "时长", "评分", "热量"], rows);
    } else if (run.tool === "get_body_measurements") {
      if (d.mode === "all") {
        const labels = d.metric_labels || {};
        const units = d.metric_units || {};
        const keys = [];
        (d.rows || []).forEach(r => {
          Object.keys(r.values || {}).forEach(k => { if (!keys.includes(k)) keys.push(k); });
        });
        const headers = ["日期"].concat(keys.map(k => (labels[k] || k) + "(" + (units[k] || "") + ")"));
        const rows = (d.rows || []).map(r => [r.date].concat(keys.map(k => r.values[k])));
        summaryText = "身材记录" + rangeLabel(d) + "（" + (d.count || 0) + " 天）";
        inner = cappedTable(headers, rows);
      } else {
        summaryText = (d.label || "身材") + "趋势" + rangeLabel(d) + "（" + (d.sample_count || 0) + " 个测量点）";
        inner = cappedTable(["日期", (d.label || "指标") + "(" + (d.unit || "") + ")"],
          (d.points || []).map(p => [p.date, p.value]));
      }
    } else if (run.tool === "get_state_records") {
      summaryText += "明细" + rangeLabel(d) + "（" + (d.count || 0) + " 条）";
      const rows = (d.records || []).map(r => [
        r.date, r.type_label, (r.star == null ? "未评" : r.star), r.remark || "—",
      ]);
      inner = cappedTable(["日期", "类型", "星级", "描述"], rows);
    } else if (run.tool === "get_cycle_records") {
      const t = d.today;
      summaryText += t && t.phase_label ? "（今日·" + t.phase_label + "）" : rangeLabel(d);
      const periodRows = (d.periods || []).map(p => [p.start_date, p.end_date, p.period_length, p.cycle_length]);
      const painRows = (d.pain_logs || []).map(p => [p.date, p.pain_level]);
      inner = '<p class="detail-sub">月经记录（' + (d.period_count || 0) + " 条）</p>" +
        cappedTable(["开始日", "结束日", "经期(天)", "周期(天)"], periodRows) +
        '<p class="detail-sub">每日疼痛（' + (d.pain_count || 0) + " 条）</p>" +
        cappedTable(["日期", "等级(0~3)"], painRows);
    } else if (run.tool === "get_profile_info") {
      summaryText = "基本信息";
      inner = detailTable(["项目", "值"], [
        ["昵称", d.display_name], ["性别", d.gender], ["年龄", d.age],
        ["账号状态", d.status], ["注册时间", d.created_at],
      ]);
    }

    details.innerHTML = "<summary>" + App.escapeHtml(summaryText) + "</summary><div class='detail-body'>" + inner + "</div>";
    return details;
  }

  /* ---------- SSE 帧解析 ---------- */
  function parseFrame(raw) {
    let event = "message";
    const dataLines = [];
    raw.split("\n").forEach(line => {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
    });
    let data = {};
    if (dataLines.length) {
      try { data = JSON.parse(dataLines.join("")); } catch (e) { /* 忽略坏帧 */ }
    }
    return { event, data };
  }

  /* ---------- 发送 + 流式接收 ---------- */
  function setStreamingUI(on) {
    streaming = on;
    els.btnSend.disabled = on;
    els.btnNewChat.disabled = on;
  }

  async function send() {
    if (streaming) return;
    const text = els.chatInput.value.trim();
    if (!text) return;

    let conv;
    try {
      conv = await ensureConversation();
    } catch (err) {
      App.toast(err.message, true);
      return;
    }

    lastUserText = text;
    syncWelcome(false);
    const userNode = appendBubble("user", text);
    const aiNode = appendBubble("assistant", "", true);
    const aiBubble = aiNode.querySelector(".msg-bubble");
    aiBubble.innerHTML = '<div class="tool-trace"></div><div class="msg-text"></div>';
    const toolTrace = aiBubble.querySelector(".tool-trace");
    const textEl = aiBubble.querySelector(".msg-text");
    const toolRuns = [];
    els.chatInput.value = "";
    autoGrow();
    setStreamingUI(true);

    const payload = {
      content: text,
      client_msg_id: crypto.randomUUID(),
    };
    if (els.chatModel.value) payload.model_name = els.chatModel.value;

    let failure = null;
    let acc = "";
    try {
      const res = await fetch("/api/agent/conversations/" + conv.id + "/messages", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok || !res.body) throw new Error("请求失败（" + res.status + "）");

      const reader = res.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";
      while (true) {
        const chunk = await reader.read();
        if (chunk.done) break;
        buffer += decoder.decode(chunk.value, { stream: true });
        const frames = buffer.split("\n\n");
        buffer = frames.pop();
        frames.forEach(frame => {
          const evt = parseFrame(frame);
          if (evt.event === "tool_start") {
            const label = TOOL_LABELS[evt.data.tool] || evt.data.tool;
            const line = document.createElement("div");
            line.className = "tool-line loading";
            line.innerHTML = '<span class="tool-dot"></span><span class="tool-name"></span>';
            line.querySelector(".tool-name").textContent = "正在查询" + label + "…";
            toolTrace.appendChild(line);
            toolRuns.push({ tool: evt.data.tool, label, line, data: null });
            scrollBottom();
          } else if (evt.event === "tool_result") {
            const run = toolRuns.find(r => r.data === null);
            if (run) {
              run.data = evt.data.data;
              run.line.classList.remove("loading");
              run.line.classList.add("done");
              run.line.querySelector(".tool-name").textContent = "已查询" + run.label;
            }
            scrollBottom();
          } else if (evt.event === "delta") {
            acc += evt.data.content;
            textEl.innerHTML = renderMarkdown(acc);
            scrollBottom();
          } else if (evt.event === "error") {
            failure = evt.data.message || "生成失败";
          } else if (evt.event === "done") {
            if (evt.data.title) conv.title = evt.data.title;
            conv.last_message_at = evt.data.last_message_at;
          }
        });
      }
    } catch (err) {
      failure = err.message;
    }

    aiBubble.classList.remove("streaming");
    setStreamingUI(false);

    if (failure) {
      userNode.remove();
      aiNode.remove();
      if (!els.messageList.children.length) syncWelcome(true);
      els.chatInput.value = lastUserText;
      autoGrow();
      App.toast(failure, true);
    } else {
      if (!acc) textEl.remove();
      toolRuns.forEach(run => {
        const detail = renderToolDetail(run);
        if (detail) aiBubble.appendChild(detail);
      });
      els.chatTitle.textContent = conv.title;
      renderSessions();
    }
  }

  /* ---------- 输入框自动增高 ---------- */
  function autoGrow() {
    const el = els.chatInput;
    const minH = parseFloat(getComputedStyle(el).minHeight) || 0;
    el.style.height = "auto";
    el.style.height = Math.min(Math.max(el.scrollHeight, minH), 140) + "px";
  }

  /* ---------- 会话侧栏收起 / 展开 ---------- */
  function applySidebar(collapsed) {
    els.workbench.classList.toggle("sessions-collapsed", collapsed);
  }

  /* ---------- 初始化 ---------- */
  function init() {
    renderSessions();
    const c = current();
    els.chatTitle.textContent = "";
    syncModelSelect(c);
    els.welcomeTitle.textContent = greeting() + "，我能帮什么忙吗？";
    loadMessages(c);
    applySidebar(localStorage.getItem(SIDEBAR_KEY) === "1");
    autoGrow();

    els.btnNewChat.addEventListener("click", newChat);
    els.btnToggleSessions.addEventListener("click", () => {
      const collapsed = els.workbench.classList.contains("sessions-collapsed");
      localStorage.setItem(SIDEBAR_KEY, collapsed ? "0" : "1");
      applySidebar(!collapsed);
    });
    els.btnSend.addEventListener("click", send);
    els.chatInput.addEventListener("input", autoGrow);
    els.chatInput.addEventListener("keydown", e => {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
        e.preventDefault();
        send();
      }
    });
    els.sessionList.addEventListener("click", e => {
      const actBtn = e.target.closest("[data-act]");
      if (actBtn) {
        e.stopPropagation();
        const id = Number(actBtn.closest(".session-item").dataset.id);
        if (actBtn.dataset.act === "rename") startRename(id);
        else if (actBtn.dataset.act === "delete") remove(id);
        return;
      }
      const item = e.target.closest(".session-item");
      if (item) selectConversation(Number(item.dataset.id));
    });
  }

  init();
})();
