/* AI Agent 前端：会话管理、消息渲染、fetch + ReadableStream 手动解析 SSE（EventSource 不支持 POST） */
(function () {
  const conversations = [...window.INIT_CONVERSATIONS];
  const personas = [...(window.INIT_PERSONAS || [])];
  // 进入页面默认停留在一个新会话窗口，不自动选中历史会话；首条消息发送时才惰性创建后端会话
  let currentId = null;
  let streaming = false;
  let lastUserText = "";
  const skillPick = { all: [], items: [], index: 0, open: false, loaded: false, loading: false };

  const SIDEBAR_KEY = "sh.agent.sessions.collapsed";

  const ICON_COPY =
    '<svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.3" aria-hidden="true">' +
    '<rect x="5.5" y="5.5" width="7" height="7" rx="1.5"/>' +
    '<path d="M10.5 5.5v-2a1.5 1.5 0 0 0-1.5-1.5h-4a1.5 1.5 0 0 0-1.5 1.5v4a1.5 1.5 0 0 0 1.5 1.5h2"/>' +
    '</svg>';
  const ICON_REGEN =
    '<svg viewBox="0 0 16 16" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.3" aria-hidden="true">' +
    '<path d="M13.5 8a5.5 5.5 0 1 1-1.61-3.89"/>' +
    '<path d="M13.5 2.5v2.6h-2.6"/>' +
    '</svg>';
  const ICON_MORE =
    '<svg viewBox="0 0 16 16" width="16" height="16" fill="currentColor" aria-hidden="true">' +
    '<circle cx="8" cy="3" r="1.3"/><circle cx="8" cy="8" r="1.3"/><circle cx="8" cy="13" r="1.3"/>' +
    '</svg>';

  const els = {
    workbench: document.getElementById("agentWorkbench"),
    sessionList: document.getElementById("sessionList"),
    btnNewChat: document.getElementById("btnNewChat"),
    btnNewPersona: document.getElementById("btnNewPersona"),
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
    skillSuggest: document.getElementById("skillSuggest"),
    suggestList: document.getElementById("suggestList"),
  };

  /* 局域网 IP + HTTP 属非安全上下文，crypto.randomUUID 不存在；按 getRandomValues/Math.random 降级 */
  function newClientMsgId() {
    const c = window.crypto;
    if (c && typeof c.randomUUID === "function") return c.randomUUID();
    if (c && typeof c.getRandomValues === "function") {
      const bytes = c.getRandomValues(new Uint8Array(16));
      bytes[6] = (bytes[6] & 0x0f) | 0x40;
      bytes[8] = (bytes[8] & 0x3f) | 0x80;
      const hex = Array.from(bytes, b => b.toString(16).padStart(2, "0")).join("");
      return hex.slice(0, 8) + "-" + hex.slice(8, 12) + "-" + hex.slice(12, 16) +
        "-" + hex.slice(16, 20) + "-" + hex.slice(20);
    }
    return "c" + Date.now().toString(36) + Math.random().toString(36).slice(2, 10);
  }

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
    autoGrow();
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
        (c.kind === "persona" && c.persona_name
          ? '<span class="s-persona">' + App.escapeHtml(c.persona_name) + '</span>'
          : '') +
        '<span class="s-actions">' +
          '<button class="s-more" data-act="menu" type="button" title="更多" aria-label="更多">' + ICON_MORE + '</button>' +
        '</span>' +
      '</div>'
    ).join("");
  }

  /* 会话操作菜单：body 级固定定位弹层，避免被侧栏滚动容器裁剪 */
  function closeMenus() {
    ["sessionMenu", "personaMenu"].forEach(id => {
      const m = document.getElementById(id);
      if (m) m.classList.remove("open");
    });
  }

  function openSessionMenu(id, anchorBtn) {
    closeMenus();
    let menu = document.getElementById("sessionMenu");
    if (!menu) {
      menu = document.createElement("div");
      menu.id = "sessionMenu";
      menu.className = "s-menu";
      document.body.appendChild(menu);
      menu.addEventListener("click", e => {
        const b = e.target.closest("button");
        if (!b) return;
        closeMenus();
        if (b.dataset.act === "rename") startRename(Number(menu.dataset.id));
        else if (b.dataset.act === "delete") remove(Number(menu.dataset.id));
      });
    }
    menu.dataset.id = id;
    menu.innerHTML =
      '<button type="button" data-act="rename">重命名</button>' +
      '<button type="button" data-act="delete" class="danger">删除会话</button>';
    const r = anchorBtn.getBoundingClientRect();
    menu.style.right = (window.innerWidth - r.right) + "px";
    if (r.bottom + 84 > window.innerHeight) {
      menu.style.top = "auto";
      menu.style.bottom = (window.innerHeight - r.top + 4) + "px";
    } else {
      menu.style.bottom = "auto";
      menu.style.top = (r.bottom + 4) + "px";
    }
    menu.classList.add("open");
  }

  function syncModelSelect(conv) {
    els.chatModel.value = (conv && conv.model_name) || "";
  }

  /* ---------- 消息渲染 ---------- */
  function actionsHtml() {
    return '<div class="msg-actions">' +
      '<button type="button" class="msg-act" data-act="copy" title="复制" aria-label="复制">' + ICON_COPY + '</button>' +
      '<button type="button" class="msg-act" data-act="regen" title="重新生成" aria-label="重新生成">' + ICON_REGEN + '</button>' +
    '</div>';
  }

  function bubbleHtml(role, content, isStreaming) {
    if (role === "assistant") {
      return '<div class="msg-row assistant">' +
        '<div class="msg-avatar">AI</div>' +
        '<div class="msg-body"><div class="msg-bubble' + (isStreaming ? ' streaming' : '') + '">' +
        '<div class="msg-text">' + renderMarkdown(content) + '</div></div>' +
        (isStreaming ? '' : actionsHtml()) + '</div></div>';
    }
    return '<div class="msg-row user"><div class="msg-body"><div class="msg-bubble">' +
      App.escapeHtml(content) + '</div></div></div>';
  }

  // 通用：把一段气泡 HTML 插入消息列表并返回节点（流式/历史共用）
  function appendNode(html) {
    const empty = els.messageList.querySelector(".chat-empty");
    if (empty) empty.remove();
    const wrap = document.createElement("div");
    wrap.innerHTML = html;
    const node = wrap.firstElementChild;
    els.messageList.appendChild(node);
    scrollBottom();
    return node;
  }

  function appendBubble(role, content, isStreaming) {
    return appendNode(bubbleHtml(role, content, isStreaming));
  }

  // 历史 assistant 气泡：工具轨迹为“已查询”完成态，正文与明细由调用方补全
  function historicalAssistantHtml(turn) {
    const runs = turn.tool_runs || [];
    const traceHtml = runs.length
      ? '<div class="tool-trace">' + runs.map(run => {
          const isSkill = run.data && run.data.skill;
          const label = (run.data && run.data.name) || TOOL_LABELS[run.tool] || run.tool;
          const prefix = isSkill ? "已运行" : (ACTION_TOOL_NAMES.has(run.tool) ? "已保存" : "已查询");
          return '<div class="tool-line done"><span class="tool-dot"></span>' +
            '<span class="tool-name">' + prefix + App.escapeHtml(label) + '</span></div>';
        }).join("") + '</div>'
      : '';
    const textHtml = turn.assistant
      ? '<div class="msg-text">' + renderMarkdown(turn.assistant) + '</div>'
      : '';
    return '<div class="msg-row assistant">' +
      '<div class="msg-avatar">AI</div>' +
      '<div class="msg-body"><div class="msg-bubble">' + traceHtml + textHtml + '</div>' +
      actionsHtml() + '</div></div>';
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
      const turns = res.turns || [];
      if (!turns.length) {
        els.messageList.innerHTML = "";
        syncWelcome(true);
        return;
      }
      els.messageList.innerHTML = "";
      turns.forEach(turn => {
        if (turn.user != null) appendNode(bubbleHtml("user", turn.user, false));
        if (turn.assistant != null || (turn.tool_runs || []).length) {
          const aiNode = appendNode(historicalAssistantHtml(turn));
          const bubble = aiNode.querySelector(".msg-bubble");
          (turn.tool_runs || []).forEach(run => {
            const label = (run.data && run.data.name) || TOOL_LABELS[run.tool] || run.tool;
            const detail = renderToolDetail({ tool: run.tool, label, data: run.data });
            if (detail) bubble.appendChild(detail);
          });
          aiNode.dataset.raw = turn.assistant || "";
        }
      });
      syncWelcome(false);
      scrollBottom();
    } catch (err) {
      App.toast(err.message, true);
    }
  }

  async function selectConversation(id) {
    if (streaming) { App.toast("请等待当前回复完成"); return; }
    closeSkillSuggest();
    currentId = id;
    const conv = current();
    els.chatTitle.textContent = conv
      ? (conv.persona_name ? conv.title + " · " + conv.persona_name : conv.title)
      : "";
    syncModelSelect(conv);
    renderSessions();
    await loadMessages(conv);
  }

  /* ---------- 新建 / 重命名 / 删除 ---------- */
  async function createConversation(personaId) {
    const body = { model_name: els.chatModel.value || null };
    if (personaId) body.persona_id = personaId;
    const conv = await App.api("/api/agent/conversations", { method: "POST", body });
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

  async function newPersonaChat(personaId) {
    if (streaming) return;
    try {
      const conv = await createConversation(personaId);
      await selectConversation(conv.id);
    } catch (err) {
      App.toast(err.message, true);
    }
  }

  /* 角色选择弹层：与「新建会话」并排，创建后整个会话固定该角色，不可切换 */
  function openPersonaMenu(anchorBtn) {
    if (streaming) return;
    if (!personas.length) { App.toast("暂无可用角色"); return; }
    closeMenus();
    let menu = document.getElementById("personaMenu");
    if (!menu) {
      menu = document.createElement("div");
      menu.id = "personaMenu";
      menu.className = "s-menu";
      document.body.appendChild(menu);
      menu.addEventListener("click", e => {
        const b = e.target.closest("button");
        if (!b) return;
        closeMenus();
        newPersonaChat(Number(b.dataset.personaId));
      });
    }
    menu.innerHTML = personas.map(p =>
      '<button type="button" data-persona-id="' + p.id + '">' +
        App.escapeHtml(p.name) +
        (p.scope === "system" ? '<span class="s-menu-tag">内置</span>' : '') +
      '</button>'
    ).join("");
    const r = anchorBtn.getBoundingClientRect();
    menu.classList.add("open");
    menu.style.right = "auto";
    menu.style.left = r.left + "px";
    menu.style.bottom = "auto";
    menu.style.top = Math.min(r.bottom + 4, window.innerHeight - 12 - personas.length * 34) + "px";
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
      message: "确定删除「" + conv.title + "」？删除后不可找回，全部消息将一并删除。",
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
        out.push('<div class="md-table-wrap">' + table + "</table></div>");
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
    save_today_workout_plan: "保存今日计划",
  };

  // 工具进行中/完成时的状态文案，按 kind 区分：查询（base）、运行（skill）、保存（action）
  function toolIngressLabel(kind) {
    if (kind === "skill") return "正在运行";
    if (kind === "action") return "正在保存";
    return "正在查询";
  }
  function toolEgressLabel(kind) {
    if (kind === "skill") return "已运行";
    if (kind === "action") return "已保存";
    return "已查询";
  }
  const ACTION_TOOL_NAMES = new Set(["save_today_workout_plan"]);

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

    if (d.kind === "prompt") {
      summaryText = (d.name || run.label) + " · " + (d.version || "") + " 提示词技能";
      inner = '<div class="detail-sub">已加载技能提示词，按指令生成回答</div>';
      const meta = d.meta || {};
      if (meta.elapsed_ms != null) {
        inner += '<div class="ai-meta">应用 ' + (meta.elapsed_ms || 0) + " ms</div>";
      }
    } else if (d.skill && Array.isArray(d.outputs)) {
      summaryText = (d.name || run.label) + " · " + (d.version || "") +
        ((d.range && (d.range.start || d.range.end)) ? rangeLabel(d) : "");
      const rows = d.outputs.map(o => [o.label, o.display != null ? o.display : o.value]);
      inner = detailTable(["指标", "值"], rows);
      if (d.caveats && d.caveats.length) {
        inner += '<div class="detail-sub">说明</div><ul class="detail-list">' +
          d.caveats.map(c => "<li>" + App.escapeHtml(c) + "</li>").join("") + "</ul>";
      }
      const meta = d.meta || {};
      if (meta.strategy || meta.elapsed_ms != null) {
        inner += '<div class="ai-meta">解析 ' + App.escapeHtml(meta.strategy || "direct") +
          " · " + (meta.elapsed_ms || 0) + " ms</div>";
      }
    } else if (run.tool === "get_workout_summary") {
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

  /* 读取 SSE 流并逐帧回调；解析层与业务事件处理分离，发送/重新生成复用同一套 */
  async function consumeSse(res, onFrame) {
    const reader = res.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      buffer += decoder.decode(chunk.value, { stream: true });
      const frames = buffer.split("\n\n");
      buffer = frames.pop();
      frames.forEach(frame => onFrame(parseFrame(frame)));
    }
  }

  async function copyAnswer(node) {
    const text = node.dataset.raw || "";
    if (!text.trim()) { App.toast("暂无内容可复制", true); return; }
    try {
      await navigator.clipboard.writeText(text);
      App.toast("已复制");
    } catch (e) {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand("copy"); App.toast("已复制"); }
      catch (err) { App.toast("复制失败", true); }
      ta.remove();
    }
  }

  /* ---------- 发送 + 流式接收 ---------- */
  function setStreamingUI(on) {
    streaming = on;
    els.btnSend.disabled = on;
    els.btnNewChat.disabled = on;
    els.btnNewPersona.disabled = on;
  }

  async function send() {
    if (streaming) return;
    const text = els.chatInput.value.trim();
    if (!text) return;
    closeSkillSuggest();

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
      client_msg_id: newClientMsgId(),
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

      await consumeSse(res, evt => {
        if (evt.event === "tool_start") {
          const label = evt.data.label || TOOL_LABELS[evt.data.tool] || evt.data.tool;
          const line = document.createElement("div");
          line.className = "tool-line loading";
          line.innerHTML = '<span class="tool-dot"></span><span class="tool-name"></span>';
          line.querySelector(".tool-name").textContent = toolIngressLabel(evt.data.kind) + label + "…";
          toolTrace.appendChild(line);
          toolRuns.push({ tool: evt.data.tool, label, line, data: null, kind: evt.data.kind || "base" });
          scrollBottom();
        } else if (evt.event === "tool_result") {
          const run = toolRuns.find(r => r.data === null);
          if (run) {
            run.data = evt.data.data;
            run.line.classList.remove("loading");
            run.line.classList.add("done");
            const prefix = toolEgressLabel(run.kind);
            run.line.querySelector(".tool-name").textContent = prefix + run.label;
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
      aiNode.dataset.raw = acc;
      aiNode.querySelector(".msg-body").insertAdjacentHTML("beforeend", actionsHtml());
      els.chatTitle.textContent = conv.title;
      renderSessions();
    }
  }

  /* ---------- 重新生成：回滚上一轮后用同一原文重放，流式覆盖本次回答 ---------- */
  async function regenerate(aiNode) {
    if (streaming) return;
    const conv = current();
    if (!conv) return;
    const allAi = els.messageList.querySelectorAll(".msg-row.assistant");
    if (allAi[allAi.length - 1] !== aiNode) { App.toast("只能重新生成最近一次回答"); return; }

    const bubble = aiNode.querySelector(".msg-bubble");
    const oldActions = aiNode.querySelector(".msg-actions");
    if (oldActions) oldActions.remove();
    bubble.classList.add("streaming");
    bubble.innerHTML = '<div class="tool-trace"></div><div class="msg-text"></div>';
    const toolTrace = bubble.querySelector(".tool-trace");
    const textEl = bubble.querySelector(".msg-text");
    const toolRuns = [];
    setStreamingUI(true);

    let failure = null;
    let acc = "";
    try {
      const payload = { client_msg_id: newClientMsgId() };
      if (els.chatModel.value) payload.model_name = els.chatModel.value;

      const res = await fetch("/api/agent/conversations/" + conv.id + "/messages/regenerate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok || !res.body) {
        let msg = "请求失败（" + res.status + "）";
        try { const j = await res.json(); if (j.error) msg = j.error; } catch (e) { /* 非 JSON */ }
        throw new Error(msg);
      }
      await consumeSse(res, evt => {
        if (evt.event === "tool_start") {
          const label = evt.data.label || TOOL_LABELS[evt.data.tool] || evt.data.tool;
          const line = document.createElement("div");
          line.className = "tool-line loading";
          line.innerHTML = '<span class="tool-dot"></span><span class="tool-name"></span>';
          line.querySelector(".tool-name").textContent = toolIngressLabel(evt.data.kind) + label + "…";
          toolTrace.appendChild(line);
          toolRuns.push({ tool: evt.data.tool, label, line, data: null, kind: evt.data.kind || "base" });
          scrollBottom();
        } else if (evt.event === "tool_result") {
          const run = toolRuns.find(r => r.data === null);
          if (run) {
            run.data = evt.data.data;
            run.line.classList.remove("loading");
            run.line.classList.add("done");
            const prefix = toolEgressLabel(run.kind);
            run.line.querySelector(".tool-name").textContent = prefix + run.label;
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
    } catch (err) {
      failure = err.message;
    }

    bubble.classList.remove("streaming");
    setStreamingUI(false);

    if (failure) {
      App.toast(failure, true);
      // 后端已回滚上一轮，前端按持久化状态重拉对齐，避免新旧回答混杂
      await loadMessages(conv);
      return;
    }
    if (!acc) textEl.remove();
    toolRuns.forEach(run => {
      const detail = renderToolDetail(run);
      if (detail) aiNode.querySelector(".msg-bubble").appendChild(detail);
    });
    aiNode.dataset.raw = acc;
    aiNode.querySelector(".msg-body").insertAdjacentHTML("beforeend", actionsHtml());
    els.chatTitle.textContent = conv.title;
    renderSessions();
  }

  /* ---------- 输入框自动增高 ---------- */
  function autoGrow() {
    const el = els.chatInput;
    const cs = getComputedStyle(el);
    const minH = parseFloat(cs.minHeight) || 0;
    const maxH = parseFloat(cs.maxHeight) || Infinity;
    el.style.height = "auto";
    el.style.height = Math.min(Math.max(el.scrollHeight, minH), maxH) + "px";
  }

  /* ---------- 斜杠技能建议 ---------- */
  function showSkillSuggest() {
    els.skillSuggest.hidden = false;
    skillPick.open = true;
    els.chatInput.setAttribute("aria-expanded", "true");
  }

  function closeSkillSuggest() {
    els.skillSuggest.hidden = true;
    skillPick.open = false;
    skillPick.items = [];
    skillPick.index = 0;
    els.chatInput.setAttribute("aria-expanded", "false");
  }

  function slashContext() {
    const el = els.chatInput;
    const caret = el.selectionStart != null ? el.selectionStart : el.value.length;
    const head = el.value.slice(0, caret);
    if (!head.startsWith("/") || /\s/.test(head.slice(1))) return null;
    return { query: head.slice(1).toLowerCase(), end: caret };
  }

  function skillScore(s, query) {
    if (!query) return 0;
    const labels = [s.name, s.key, s.slash_alias].filter(Boolean).map(v => String(v).toLowerCase());
    let score = 9;
    labels.forEach(label => {
      if (label === query) score = Math.min(score, 0);
      else if (label.startsWith(query)) score = Math.min(score, 1);
      else if (label.includes(query)) score = Math.min(score, 2);
    });
    return score;
  }

  async function loadSkillOptions() {
    if (skillPick.loading || skillPick.loaded) return;
    skillPick.loading = true;
    try {
      const res = await fetch("/api/agent/skills");
      if (res.ok) {
        const data = await res.json();
        skillPick.all = (data.list || []).filter(s => s.status === "active");
      }
    } catch (e) {
      // 技能列表不可用时静默降级为普通输入
    } finally {
      skillPick.loaded = true;
      skillPick.loading = false;
      if (skillPick.open) refreshSkillSuggest();
    }
  }

  function renderSkillOptions() {
    els.suggestList.innerHTML = skillPick.items.map((s, i) => {
      const slash = s.slash_alias || s.name || s.key;
      const tag = s.kind === "prompt" ? "提示词" : s.scope === "system" ? "平台" : "数据";
      const initial = String(s.name || s.key || "技").trim().slice(0, 1);
      const desc = s.description
        ? '<span class="ss-desc">' + App.escapeHtml(s.description) + "</span>"
        : "";
      return '<button class="skill-option' + (i === skillPick.index ? " active" : "") +
        '" type="button" role="option" aria-selected="' + (i === skillPick.index) +
        '" data-index="' + i + '">' +
        '<span class="ss-mark">' + App.escapeHtml(initial) + "</span>" +
        '<span class="ss-text"><span class="ss-line">' +
          '<span class="ss-name">' + App.escapeHtml(s.name || s.key) + "</span>" +
          '<span class="ss-slash">/' + App.escapeHtml(slash) + "</span>" +
          '<span class="ss-tag">' + tag + "</span>" +
        "</span>" + desc + "</span></button>";
    }).join("");
    const active = els.suggestList.querySelector(".skill-option.active");
    if (active && active.scrollIntoView) active.scrollIntoView({ block: "nearest" });
  }

  function setActiveSkill(index) {
    if (!skillPick.items.length) return;
    const count = skillPick.items.length;
    skillPick.index = ((index % count) + count) % count;
    els.suggestList.querySelectorAll(".skill-option").forEach((node, i) => {
      node.classList.toggle("active", i === skillPick.index);
      node.setAttribute("aria-selected", i === skillPick.index ? "true" : "false");
    });
    const active = els.suggestList.querySelector(".skill-option.active");
    if (active && active.scrollIntoView) active.scrollIntoView({ block: "nearest" });
  }

  function refreshSkillSuggest(reset = true) {
    const ctx = slashContext();
    if (!ctx) { closeSkillSuggest(); return; }
    if (!skillPick.loaded) {
      els.suggestList.innerHTML = '<div class="suggest-empty">正在加载技能…</div>';
      showSkillSuggest();
      loadSkillOptions();
      return;
    }
    const matches = skillPick.all
      .map(s => ({ s, score: skillScore(s, ctx.query) }))
      .filter(item => item.score < 9)
      .sort((a, b) => a.score - b.score ||
        (a.s.scope === "system" ? 0 : 1) - (b.s.scope === "system" ? 0 : 1) ||
        String(a.s.name || "").localeCompare(String(b.s.name || ""), "zh-Hans-CN"))
      .slice(0, 8)
      .map(item => item.s);
    if (!matches.length) { closeSkillSuggest(); return; }
    skillPick.items = matches;
    if (reset) skillPick.index = 0;
    renderSkillOptions();
    showSkillSuggest();
  }

  function chooseSkill(index) {
    const s = skillPick.items[index];
    if (!s) { closeSkillSuggest(); return; }
    const insert = "/" + (s.slash_alias || s.name || s.key) + " ";
    const el = els.chatInput;
    const caret = el.selectionStart != null ? el.selectionStart : el.value.length;
    el.value = insert + el.value.slice(caret);
    el.focus();
    el.setSelectionRange(insert.length, insert.length);
    closeSkillSuggest();
    autoGrow();
  }


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
    loadSkillOptions();

    els.btnNewChat.addEventListener("click", newChat);
    els.btnNewPersona.addEventListener("click", () => openPersonaMenu(els.btnNewPersona));
    els.btnToggleSessions.addEventListener("click", () => {
      const collapsed = els.workbench.classList.contains("sessions-collapsed");
      localStorage.setItem(SIDEBAR_KEY, collapsed ? "0" : "1");
      applySidebar(!collapsed);
    });
    els.btnSend.addEventListener("click", send);
    els.chatInput.addEventListener("input", () => {
      autoGrow();
      refreshSkillSuggest();
    });
    els.chatInput.addEventListener("click", () => refreshSkillSuggest());
    els.chatInput.addEventListener("keydown", e => {
      if (e.isComposing) return;
      if (skillPick.open) {
        if (e.key === "ArrowDown" || e.key === "ArrowUp") {
          e.preventDefault();
          setActiveSkill(skillPick.index + (e.key === "ArrowDown" ? 1 : -1));
          return;
        }
        if ((e.key === "Enter" && !e.shiftKey) || e.key === "Tab") {
          e.preventDefault();
          chooseSkill(skillPick.index);
          return;
        }
        if (e.key === "Escape") {
          e.preventDefault();
          closeSkillSuggest();
          return;
        }
      }
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
        e.preventDefault();
        send();
      }
    });
    els.suggestList.addEventListener("mousedown", e => {
      const option = e.target.closest(".skill-option");
      if (!option) return;
      e.preventDefault();
      chooseSkill(Number(option.dataset.index));
    });
    els.suggestList.addEventListener("mousemove", e => {
      const option = e.target.closest(".skill-option");
      if (!option) return;
      const index = Number(option.dataset.index);
      if (index !== skillPick.index) setActiveSkill(index);
    });
    document.addEventListener("click", e => {
      if (!skillPick.open) return;
      if (e.target.closest("#skillSuggest") || e.target === els.chatInput) return;
      closeSkillSuggest();
    });
    els.sessionList.addEventListener("click", e => {
      const menuBtn = e.target.closest('[data-act="menu"]');
      if (menuBtn) {
        e.stopPropagation();
        const id = Number(menuBtn.closest(".session-item").dataset.id);
        openSessionMenu(id, menuBtn);
        return;
      }
      const actBtn = e.target.closest("[data-act]");
      if (actBtn) {
        e.stopPropagation();
        const id = Number(actBtn.closest(".session-item").dataset.id);
        closeMenus();
        if (actBtn.dataset.act === "rename") startRename(id);
        else if (actBtn.dataset.act === "delete") remove(id);
        return;
      }
      const item = e.target.closest(".session-item");
      if (item) { closeMenus(); selectConversation(Number(item.dataset.id)); }
    });
    document.addEventListener("click", e => {
      if (!e.target.closest("#sessionMenu")) closeMenus();
    });

    els.messageList.addEventListener("click", e => {
      const actBtn = e.target.closest("[data-act]");
      if (!actBtn) return;
      const node = actBtn.closest(".msg-row.assistant");
      if (!node) return;
      if (actBtn.dataset.act === "copy") copyAnswer(node);
      else if (actBtn.dataset.act === "regen") regenerate(node);
    });
  }

  init();
})();
