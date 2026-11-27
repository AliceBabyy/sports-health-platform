/* AI Agent 前端：会话管理、消息渲染、fetch + ReadableStream 手动解析 SSE（EventSource 不支持 POST） */
(function () {
  const conversations = [...window.INIT_CONVERSATIONS];
  const personas = [...(window.INIT_PERSONAS || [])];
  // 进入页面默认停留在一个新会话窗口，不自动选中历史会话；首条消息发送时才惰性创建后端会话
  let currentId = null;
  let streaming = false;
  let stopping = false;
  let activeStream = null; // { controller, turn }：当前进行中的流，用于中断
  let interruptedTurn = null; // 最近一次被用户停止、可用「继续」接写的回答
  let lastUserText = "";
  let activeAsk = null; // 当前唯一等待回答的卡片，主输入框也复用它作答
  let webSearchOn = false; // 本轮联网开关：默认关闭，只对下一次发送（含重生成/续写/作答）生效
  const skillPick = { all: [], items: [], index: 0, open: false, loaded: false, loading: false, personaId: null };

  const SIDEBAR_KEY = "sh.agent.sessions.collapsed";
  const CURRENT_KEY = "sh.agent.current";

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
  const ICON_SEND =
    '<svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">' +
    '<path d="M8 12V4M3.5 8.5 8 4l4.5 4.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" fill="none"/>' +
    '</svg>';
  // 流式期间同一按钮变为停止：方形图标 + 深色底，避免和发送态混淆
  const ICON_STOP =
    '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">' +
    '<rect x="4" y="4" width="8" height="8" rx="1.6" fill="currentColor"/>' +
    '</svg>';
  const ICON_CONTINUE =
    '<svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true">' +
    '<path d="M5.2 3.1 12 8l-6.8 4.9z" fill="currentColor"/>' +
    '</svg>';
  const ICON_PERSONA =
    '<svg class="s-persona-icon" viewBox="0 0 16 16" width="11" height="11" fill="none" stroke="currentColor" stroke-width="1.3" aria-hidden="true">' +
    '<circle cx="8" cy="5.5" r="2.2"/>' +
    '<path d="M3.8 13c.4-2.1 2-3.1 4.2-3.1s3.8 1 4.2 3.1"/>' +
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
    btnWebSearch: document.getElementById("btnWebSearch"),
    skillSuggest: document.getElementById("skillSuggest"),
    suggestList: document.getElementById("suggestList"),
  };

  /* ---------- 联网开关 ---------- */
  // 默认不联网；开关只在本次页面会话内有效，刷新后回到关闭态
  const WEB_TITLE_OFF = "开启联网：本轮会检索外部网页（Tavily）";
  const WEB_TITLE_ON = "本轮已开启联网：回答会标注外部来源";
  const WEB_TITLE_UNAVAILABLE = "联网搜索未配置：请先在服务端配置 TAVILY_API_KEY";

  function webAvailable() {
    return window.WEB_SEARCH_AVAILABLE !== false;
  }

  function setWebSearch(on) {
    webSearchOn = !!on && webAvailable();
    els.btnWebSearch.setAttribute("aria-pressed", webSearchOn ? "true" : "false");
    els.btnWebSearch.title = !webAvailable()
      ? WEB_TITLE_UNAVAILABLE
      : (webSearchOn ? WEB_TITLE_ON : WEB_TITLE_OFF);
    els.btnWebSearch.disabled = !webAvailable();
  }

  // 只有开启时才带 web_search=true；默认请求体保持不变
  function withWebFlag(payload) {
    if (webSearchOn) payload.web_search = true;
    return payload;
  }

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

  /* 选中会话持久化：URL 优先（刷新、复制链接都能回到同一会话），localStorage 兜底 */
  function rememberConversation(id) {
    if (id == null) localStorage.removeItem(CURRENT_KEY);
    else localStorage.setItem(CURRENT_KEY, String(id));
    const url = new URL(window.location.href);
    if (id == null) url.searchParams.delete("conversation_id");
    else url.searchParams.set("conversation_id", String(id));
    window.history.replaceState(null, "", url);
  }

  function restoreConversationId() {
    const raw = new URL(window.location.href).searchParams.get("conversation_id");
    const candidates = [];
    if (raw) candidates.push(Number(raw));
    const stored = Number(localStorage.getItem(CURRENT_KEY));
    if (stored) candidates.push(stored);
    return candidates.find(id => conversations.some(c => c.id === id)) || null;
  }

  function conversationTitle(conv) {
    if (!conv) return "";
    return conv.persona_name ? conv.title + " · " + conv.persona_name : conv.title;
  }

  /* ---------- 会话列表 ---------- */
  function renderSessions() {
    if (!conversations.length) {
      els.sessionList.innerHTML = '<div class="chat-empty">暂无会话</div>';
      return;
    }
    els.sessionList.innerHTML = conversations.map(c =>
      '<div class="session-item' + (c.id === currentId ? ' active' : '') +
        (c.kind === "persona" ? ' persona-session' : '') + '" data-id="' + c.id + '">' +
        '<span class="s-title">' + App.escapeHtml(c.title) + '</span>' +
        (c.kind === "persona" && c.persona_name
          ? '<span class="s-persona" title="角色会话 · ' + App.escapeHtml(c.persona_name) + '">' +
            ICON_PERSONA + '<span class="s-persona-name">' + App.escapeHtml(c.persona_name) + '</span></span>'
          : '') +
        '<span class="s-actions">' +
          '<button class="s-more" data-act="menu" type="button" title="更多" aria-label="更多">' + ICON_MORE + '</button>' +
        '</span>' +
      '</div>'
    ).join("");
  }

  /* 会话操作菜单：body 级固定定位弹层，避免被侧栏滚动容器裁剪 */
  function closeMenus() {
    const m = document.getElementById("sessionMenu");
    if (m) m.classList.remove("open");
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

  /* ---------- 消息渲染：流式与历史共用同一套 turn 结构 ---------- */
  function actionsHtml(withRegen = true, withContinue = false) {
    return '<div class="msg-actions">' +
      '<button type="button" class="msg-act" data-act="copy" title="复制" aria-label="复制">' + ICON_COPY + '</button>' +
      (withContinue
        ? '<button type="button" class="msg-act msg-act-continue" data-act="continue" title="从中断处继续生成" aria-label="继续生成">' +
          ICON_CONTINUE + '<span>继续</span></button>'
        : '') +
      (withRegen
        ? '<button type="button" class="msg-act" data-act="regen" title="重新生成" aria-label="重新生成">' + ICON_REGEN + '</button>'
        : '') +
    '</div>';
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

  function appendUserBubble(content) {
    return appendNode('<div class="msg-row user"><div class="msg-body"><div class="msg-bubble">' +
      App.escapeHtml(content) + '</div></div></div>');
  }

  function scrollBottom() {
    els.messageScroll.scrollTop = els.messageScroll.scrollHeight;
  }

  // 一条 AI 回答 = 一个 turn 对象；流式、历史恢复、重新生成、中途问答共用同一套状态
  const ASSISTANT_SHELL =
    '<div class="msg-row assistant">' +
      '<div class="msg-avatar">AI</div>' +
      '<div class="msg-body">' +
        '<div class="msg-bubble">' +
          '<div class="tool-trace"></div><div class="msg-blocks"></div>' +
        '</div>' +
      '</div>' +
    '</div>';

  function createTurn(node) {
    const bubble = node.querySelector(".msg-bubble");
    const turn = {
      node: node,
      bubble: bubble,
      trace: bubble.querySelector(".tool-trace"),
      blocksEl: bubble.querySelector(".msg-blocks"),
      blocks: [],
      toolRuns: [],
      meta: {},
      failure: null,
      stopped: false,
      completed: false,
      busy: false,
      closed: false,
      raf: 0,
    };
    node.__turn = turn;
    return turn;
  }

  function appendAssistantTurn(streaming) {
    const turn = createTurn(appendNode(ASSISTANT_SHELL));
    if (streaming) turn.bubble.classList.add("streaming");
    return turn;
  }

  function turnText(turn) {
    return turn.blocks
      .filter(b => b.type === "text" && b.content)
      .map(b => b.content)
      .join("\n\n");
  }

  // 正文按段渲染：每个 text 段一个 .msg-text，ask 段一张问答卡片
  function textBlockNode(turn, block) {
    if (block._node && block._node.parentNode) return block._node;
    const el = document.createElement("div");
    el.className = "msg-text";
    turn.blocksEl.appendChild(el);
    block._node = el;
    return el;
  }

  // delta 每帧只在下一个动画帧渲染一次，避免长回答反复全量解析 Markdown
  function appendDelta(turn, content) {
    let last = turn.blocks[turn.blocks.length - 1];
    if (!last || last.type !== "text") {
      last = { type: "text", content: "" };
      turn.blocks.push(last);
    }
    last.content += content;
    if (turn.raf) return;
    turn.raf = requestAnimationFrame(() => {
      turn.raf = 0;
      if (turn.closed) return;
      textBlockNode(turn, last).innerHTML = renderMarkdown(last.content);
      scrollBottom();
    });
  }

  /* ---------- 中途提问卡片 ---------- */
  function askCardNode(turn, block) {
    const waiting = !block.answer && !!block.pending;
    const card = document.createElement("div");
    card.className = "ask-card" + (waiting ? " is-pending" : "");

    const label = document.createElement("div");
    label.className = "ask-label";
    label.textContent = block.skipped ? "已跳过" : block.answer ? "已回复" : waiting ? "需要你回答" : "待回答";
    card.appendChild(label);

    const question = document.createElement("div");
    question.className = "ask-question";
    question.textContent = block.question || "";
    card.appendChild(question);

    if (block.skipped && !block.answer) {
      const note = document.createElement("div");
      note.className = "ask-answer ask-skipped";
      note.textContent = "未作答，按已有信息继续";
      card.appendChild(note);
      return card;
    }
    if (block.answer) {
      const answer = document.createElement("div");
      answer.className = "ask-answer";
      answer.textContent = block.answer;
      card.appendChild(answer);
      return card;
    }
    // 历史里未回答、且当前没有挂起（异常态）时只展示问题，不给输入
    if (!waiting) return card;

    const selected = [];
    const options = block.options || [];
    let sendBtn = null;
    if (options.length) {
      const row = document.createElement("div");
      row.className = "ask-options";
      options.forEach(opt => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "ask-opt";
        btn.textContent = opt;
        btn.addEventListener("click", () => {
          if (turn.busy) return;
          if (!block.multiple) { submitAsk(turn, block, opt); return; }
          btn.classList.toggle("active");
          const idx = selected.indexOf(opt);
          if (idx >= 0) selected.splice(idx, 1); else selected.push(opt);
          if (sendBtn) sendBtn.disabled = !selected.length;
        });
        row.appendChild(btn);
      });
      card.appendChild(row);
    }

    const reply = document.createElement("div");
    reply.className = "ask-reply";
    const input = document.createElement("input");
    input.className = "input ask-input";
    input.type = "text";
    input.placeholder = options.length ? "或直接输入回答" : "输入你的回答";
    sendBtn = document.createElement("button");
    sendBtn.type = "button";
    sendBtn.className = "btn btn-primary ask-send";
    sendBtn.textContent = "发送";
    if (block.multiple) sendBtn.disabled = true;

    const submit = () => {
      if (turn.busy) return;
      let text = "";
      if (block.multiple && selected.length) text = selected.join("、");
      else if (input.value.trim()) text = input.value.trim();
      if (!text) return;
      submitAsk(turn, block, text);
    };
    sendBtn.addEventListener("click", submit);
    input.addEventListener("keydown", e => {
      if (e.key === "Enter" && !e.isComposing) { e.preventDefault(); submit(); }
    });
    reply.appendChild(input);
    reply.appendChild(sendBtn);
    const skipBtn = document.createElement("button");
    skipBtn.type = "button";
    skipBtn.className = "ask-skip";
    skipBtn.textContent = "跳过";
    skipBtn.addEventListener("click", () => {
      if (turn.busy) return;
      submitAsk(turn, block, "", true);
    });
    reply.appendChild(skipBtn);
    card.appendChild(reply);
    return card;
  }

  function renderAskCard(turn, block) {
    const card = askCardNode(turn, block);
    if (block._node && block._node.parentNode) block._node.replaceWith(card);
    else turn.blocksEl.appendChild(card);
    block._node = card;
    if (!block.answer && block.pending) activeAsk = { turn, block };
    else if (activeAsk && activeAsk.block === block) activeAsk = null;
    scrollBottom();
  }

  function appendAskBlock(turn, data) {
    const block = {
      type: "ask",
      question: data.question || "",
      options: data.options || [],
      multiple: !!data.multiple,
      answer: null,
      skipped: false,
      pending: true,
    };
    turn.blocks.push(block);
    renderAskCard(turn, block);
  }

  // 作答/跳过就是下一条消息：后端检测到挂起的 ask_user 后在同一轮恢复
  async function submitAsk(turn, block, answer, skipped = false) {
    if (streaming || turn.busy) return;
    const conv = current();
    if (!conv) return;
    const text = String(answer || "").trim();
    if (!skipped && !text) return;

    turn.busy = true;
    turn.closed = false;
    turn.bubble.classList.add("streaming");
    block.answer = skipped ? null : text;
    block.skipped = skipped;
    block.pending = false;
    renderAskCard(turn, block);
    setStreamingUI(true);

    const payload = withWebFlag({ content: skipped ? "跳过" : text, client_msg_id: newClientMsgId() });
    if (skipped) payload.skip_ask = true;
    if (els.chatModel.value) payload.model_name = els.chatModel.value;
    await runStream("/api/agent/conversations/" + conv.id + "/messages", payload, turn);
    turn.busy = false;

    if (turn.stopped) {
      // 中断保留服务端挂起的提问：等收口完成后重拉，卡片回到待作答态
      await awaitStop();
      await loadMessages(conv);
      return;
    }
    setStreamingUI(false);

    if (turn.failure) {
      App.toast(turn.failure, true);
      turn.bubble.classList.remove("streaming");
      block.answer = null;
      block.skipped = false;
      block.pending = true;
      renderAskCard(turn, block);
      turn.failure = null;
      return;
    }
    finalizeTurn(turn);
    if (turn.meta.title) conv.title = turn.meta.title;
    if (turn.meta.last_message_at) conv.last_message_at = turn.meta.last_message_at;
    els.chatTitle.textContent = conversationTitle(conv);
    renderSessions();
  }

  function traceLine(kind, label, done) {
    const line = document.createElement("div");
    line.className = "tool-line " + (done ? "done" : "loading");
    line.innerHTML = '<span class="tool-dot"></span><span class="tool-name"></span>';
    line.querySelector(".tool-name").textContent =
      (done ? toolEgressLabel(kind) : toolIngressLabel(kind)) + label + (done ? "" : "…");
    return line;
  }

  function startToolRun(turn, data) {
    const run = {
      tool: data.tool,
      label: data.label || data.tool,
      kind: data.kind || "base",
      call_id: data.call_id || null,
      args: data.args || {},
      data: null,
    };
    run.line = traceLine(run.kind, run.label, false);
    turn.trace.appendChild(run.line);
    turn.toolRuns.push(run);
    scrollBottom();
  }

  // 结果优先按 call_id 配对，缺失时回退到第一个未回填的 run
  function finishToolRun(turn, data) {
    let run = null;
    if (data.call_id) {
      run = turn.toolRuns.find(r => r.call_id === data.call_id && r.data === null);
    }
    if (!run) run = turn.toolRuns.find(r => r.data === null);
    if (!run) return;
    run.data = data.data;
    if (!run.line) {
      run.line = traceLine(run.kind, run.label, false);
      turn.trace.appendChild(run.line);
    }
    run.line.classList.remove("loading");
    run.line.classList.add("done");
    run.line.querySelector(".tool-name").textContent = toolEgressLabel(run.kind) + run.label;
    scrollBottom();
  }

  function applyEvent(turn, evt) {
    const d = evt.data || {};
    if (evt.event === "tool_start") startToolRun(turn, d);
    else if (evt.event === "tool_result") finishToolRun(turn, d);
    else if (evt.event === "delta") appendDelta(turn, d.content || "");
    else if (evt.event === "ask") appendAskBlock(turn, d);
    else if (evt.event === "done") { turn.meta = d; turn.completed = true; }
    else if (evt.event === "error") turn.failure = d.message || "生成失败";
  }

  // 历史恢复：服务端已给出有序正文段（含 ask）与工具轨迹，直接灌进同一 turn 结构
  function hydrateTurn(turn, item) {
    turn.blocks = (item.blocks || [])
      .filter(b => b && (b.type === "ask" || (b.type === "text" && b.content)))
      .map(b => ({ ...b }));
    (item.tool_runs || []).forEach(run => {
      turn.toolRuns.push({
        tool: run.tool,
        label: run.label || run.tool,
        kind: run.kind || "base",
        call_id: run.call_id || null,
        args: run.args || {},
        data: run.data,
        line: null,
      });
    });
  }

  // 收口：按段重建正文与问答卡片、补完成态工具行、挂明细与操作按钮
  function finalizeTurn(turn, interrupted = false) {
    if (turn.raf) { cancelAnimationFrame(turn.raf); turn.raf = 0; }
    turn.node.querySelectorAll(".tool-detail").forEach(node => node.remove());
    const oldActions = turn.node.querySelector(".msg-actions");
    if (oldActions) oldActions.remove();
    const oldNote = turn.bubble.querySelector(".msg-stopped");
    if (oldNote) oldNote.remove();
    turn.blocksEl.innerHTML = "";
    turn.blocks.forEach(block => {
      block._node = null;
      if (block.type === "ask") renderAskCard(turn, block);
      else if (block.content) {
        textBlockNode(turn, block).innerHTML = renderMarkdown(block.content);
      }
    });
    turn.toolRuns.forEach(run => {
      if (!run.line) {
        run.line = traceLine(run.kind, run.label, true);
        turn.trace.appendChild(run.line);
      }
      const detail = renderToolDetail(run);
      if (detail) turn.bubble.appendChild(detail);
    });
    const text = turnText(turn);
    turn.node.dataset.raw = text;
    turn.bubble.classList.remove("streaming");
    if (interrupted) markStopped(turn);
    const waiting = turn.blocks.some(b => b.type === "ask" && b.pending && !b.answer);
    turn.node.querySelector(".msg-body").insertAdjacentHTML(
      "beforeend", actionsHtml(!waiting, interrupted && !waiting)
    );
    turn.closed = true;
  }

  // 停止后的标记：只在这一条回答末尾留一行说明，不阻塞后续提问
  function markStopped(turn) {
    if (turn.bubble.querySelector(".msg-stopped")) return;
    const note = document.createElement("div");
    note.className = "msg-stopped";
    note.textContent = "已停止生成";
    turn.bubble.appendChild(note);
  }

  /* ---------- 生成中占位与轮询 ---------- */
  let pollTimer = 0;
  let renderedConvId = null; // 上一次整表渲染的会话，用于首次进入时滚到底

  function stopPolling() {
    if (pollTimer) {
      clearTimeout(pollTimer);
      pollTimer = 0;
    }
  }

  function schedulePoll(conv) {
    stopPolling();
    pollTimer = setTimeout(() => {
      pollTimer = 0;
      if (!conv || currentId !== conv.id || streaming || stopping) return;
      loadMessages(conv);
    }, 2500);
  }

  function appendGenerating() {
    const wrap = document.createElement("div");
    wrap.innerHTML =
      '<div class="msg-row assistant is-generating">' +
        '<div class="msg-avatar">AI</div>' +
        '<div class="msg-body"><div class="msg-bubble">' +
          '<div class="msg-generating">' +
            '<span class="dots"><i></i><i></i><i></i></span><span>正在生成…</span>' +
          '</div>' +
        '</div></div>' +
      '</div>';
    els.messageList.appendChild(wrap.firstElementChild);
  }

  async function loadMessages(conv) {
    stopPolling();
    if (!conv) {
      els.messageList.innerHTML = "";
      syncWelcome(true);
      return;
    }
    const nearBottom =
      els.messageScroll.scrollHeight - els.messageScroll.scrollTop - els.messageScroll.clientHeight < 80;
    const initialRender = conv.id !== renderedConvId;
    renderedConvId = conv.id;
    try {
      const res = await App.api("/api/agent/conversations/" + conv.id + "/messages");
      const turns = res.turns || [];
      const generating = !!res.generating;
      els.messageList.innerHTML = "";
      activeAsk = null;
      interruptedTurn = null;
      turns.forEach(item => {
        if (item.user != null) appendUserBubble(item.user);
        if ((item.blocks || []).length || (item.tool_runs || []).length) {
          const turn = appendAssistantTurn();
          hydrateTurn(turn, item);
          finalizeTurn(turn, !!item.interrupted);
          if (item.interrupted) interruptedTurn = turn;
        }
      });
      // 后端还在生成：占位提示并开始轮询，生成结束后自动刷新成完整回答
      if (generating) appendGenerating();
      if (!turns.length && !generating) {
        syncWelcome(true);
        return;
      }
      syncWelcome(false);
      if (nearBottom || initialRender) scrollBottom();
      if (generating) schedulePoll(conv);
    } catch (err) {
      App.toast(err.message, true);
    }
  }

  async function selectConversation(id) {
    if (streaming) { App.toast("请等待当前回复完成"); return; }
    closeSkillSuggest();
    currentId = id;
    rememberConversation(id);
    const conv = current();
    els.chatTitle.textContent = conversationTitle(conv);
    syncModelSelect(conv);
    renderSessions();
    await loadMessages(conv);
    await loadSkillOptions(true);
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
    rememberConversation(created.id);
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

  /* 角色选择弹窗：选好后创建角色会话，整段会话固定该角色，不可切换 */
  function openPersonaModal() {
    if (streaming) return;
    if (!personas.length) { App.toast("暂无可用角色"); return; }
    const list = document.getElementById("personaPickList");
    list.innerHTML = personas.map(p =>
      '<button type="button" class="persona-pick" data-persona-id="' + p.id + '">' +
        '<span class="p-head">' +
          '<span class="p-name">' + App.escapeHtml(p.name) + '</span>' +
          '<span class="p-tag">' + (p.scope === "system" ? '内置' : '我的角色') + '</span>' +
        '</span>' +
        (p.description
          ? '<span class="p-desc">' + App.escapeHtml(p.description) + '</span>'
          : '') +
      '</button>'
    ).join("");
    App.openModal("personaModal");
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
          if (currentId === id) els.chatTitle.textContent = conversationTitle(conv);
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
        rememberConversation(currentId);
        const c = current();
        els.chatTitle.textContent = conversationTitle(c);
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
  // 工具名与展示标签一律由服务端 tool_start / tool_result 下发；前端只保留类别到文案的映射
  const KIND_TEXT = {
    base: ["正在查询", "已查询"],
    action: ["正在保存", "已保存"],
    skill: ["正在运行", "已运行"],
  };
  function toolIngressLabel(kind) { return (KIND_TEXT[kind] || KIND_TEXT.base)[0]; }
  function toolEgressLabel(kind) { return (KIND_TEXT[kind] || KIND_TEXT.base)[1]; }

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
  // 流式期间发送按钮原地变成“停止”（方形图标 + 深色底），点击即中断本轮生成
  function setStreamingUI(on) {
    streaming = on;
    els.btnSend.classList.toggle("is-stop", on);
    els.btnSend.innerHTML = on ? ICON_STOP : ICON_SEND;
    els.btnSend.title = on ? "停止生成" : "发送";
    els.btnSend.setAttribute("aria-label", on ? "停止生成" : "发送");
    els.btnNewChat.disabled = on;
    els.btnNewPersona.disabled = on;
  }

  // 发送与重新生成共用：请求 → SSE 逐帧喂给同一个 turn，失败只记录不抛给页面
  async function runStream(path, payload, turn) {
    turn.failure = null;
    const controller = new AbortController();
    activeStream = { controller, turn };
    try {
      const res = await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });
      if (!res.ok || !res.body) {
        let msg = "请求失败（" + res.status + "）";
        try { const j = await res.json(); if (j.error) msg = j.error; } catch (e) { /* 非 JSON */ }
        throw new Error(msg);
      }
      await consumeSse(res, evt => applyEvent(turn, evt));
    } catch (err) {
      // 用户主动停止导致的 abort 不算失败，由停止流程收口
      if (!turn.stopped) turn.failure = err.message || "生成失败";
    } finally {
      if (activeStream && activeStream.controller === controller) activeStream = null;
    }
  }

  /* ---------- 停止 / 继续 ---------- */
  // 立即断开前端流（用户点下去就停），再请服务端做一次收口：回滚半途的调用、保留半截回答。
  // 返回的 promise 用于让发送流程等到服务端占位释放后再收尾，避免紧接着发下一条时撞 409。
  let stopPromise = null;

  function stopStream() {
    if (!streaming || stopping) return Promise.resolve();
    stopping = true;
    const turn = activeStream ? activeStream.turn : null;
    if (turn && turn.completed) { stopping = false; return Promise.resolve(); }
    if (turn) turn.stopped = true;
    if (activeStream) activeStream.controller.abort();
    const conv = current();
    stopPromise = App.api(
      "/api/agent/conversations/" + (conv ? conv.id : "") + "/messages/stop", { method: "POST" }
    )
      .then(res => {
        if (res && conv) {
          if (res.title) conv.title = res.title;
          if (res.last_message_at) conv.last_message_at = res.last_message_at;
          els.chatTitle.textContent = conversationTitle(conv);
          renderSessions();
        }
      })
      .catch(() => { /* 前端流已断开，收口失败不打断用户操作 */ })
      .finally(() => { stopping = false; });
    return stopPromise;
  }

  async function awaitStop() {
    if (stopPromise) {
      await stopPromise;
      stopPromise = null;
    }
    setStreamingUI(false);
  }

  async function settleStopped(turn) {
    await awaitStop();
    finalizeTurn(turn, true);
    interruptedTurn = turn;
  }

  const CONTINUE_TEXT = /^(继续|接着|接着说|继续说|继续生成|继续吧|continue)[\s。，、!！?？]*$/i;

  function lastAssistantNode() {
    const rows = els.messageList.querySelectorAll(".msg-row.assistant");
    return rows.length ? rows[rows.length - 1] : null;
  }

  // 中断后只发“继续”这类短语：当作控制指令，不新开一轮，直接接写原回答
  function isContinueFollowUp(text) {
    if (!interruptedTurn) return false;
    if (lastAssistantNode() !== interruptedTurn.node) return false;
    return CONTINUE_TEXT.test(String(text).trim());
  }

  async function continueTurn(turn) {
    if (streaming || !turn) return;
    const conv = current();
    if (!conv) return;
    const oldActions = turn.node.querySelector(".msg-actions");
    if (oldActions) oldActions.remove();
    const oldNote = turn.bubble.querySelector(".msg-stopped");
    if (oldNote) oldNote.remove();
    turn.failure = null;
    turn.stopped = false;
    turn.closed = false;
    turn.bubble.classList.add("streaming");
    interruptedTurn = null;
    setStreamingUI(true);

    const payload = withWebFlag({ client_msg_id: newClientMsgId() });
    if (els.chatModel.value) payload.model_name = els.chatModel.value;

    await runStream("/api/agent/conversations/" + conv.id + "/messages/continue", payload, turn);
    setStreamingUI(false);

    if (turn.stopped) { await settleStopped(turn); return; }
    if (turn.failure) {
      App.toast(turn.failure, true);
      // 服务端可能已回滚本轮，重拉一次与持久化状态对齐
      await loadMessages(conv);
      return;
    }
    finalizeTurn(turn);
    if (turn.meta.title) conv.title = turn.meta.title;
    if (turn.meta.last_message_at) conv.last_message_at = turn.meta.last_message_at;
    els.chatTitle.textContent = conversationTitle(conv);
    renderSessions();
  }

  async function send() {
    if (streaming) return;
    const text = els.chatInput.value.trim();
    if (!text) return;
    closeSkillSuggest();

    // 上一轮还在等回答：主输入框直接作为答案，不新开一轮
    if (activeAsk) {
      els.chatInput.value = "";
      autoGrow();
      submitAsk(activeAsk.turn, activeAsk.block, text);
      return;
    }

    // 中断后接着说“继续”：接写被中断的那条回答，不新增轮次
    if (isContinueFollowUp(text)) {
      els.chatInput.value = "";
      autoGrow();
      continueTurn(interruptedTurn);
      return;
    }
    interruptedTurn = null;

    let conv;
    try {
      conv = await ensureConversation();
    } catch (err) {
      App.toast(err.message, true);
      return;
    }

    lastUserText = text;
    syncWelcome(false);
    const userNode = appendUserBubble(text);
    const turn = appendAssistantTurn(true);
    els.chatInput.value = "";
    autoGrow();
    setStreamingUI(true);

    const payload = withWebFlag({ content: text, client_msg_id: newClientMsgId() });
    if (els.chatModel.value) payload.model_name = els.chatModel.value;

    await runStream("/api/agent/conversations/" + conv.id + "/messages", payload, turn);

    if (turn.stopped) { await settleStopped(turn); return; }
    setStreamingUI(false);

    if (turn.failure) {
      userNode.remove();
      turn.node.remove();
      if (!els.messageList.children.length) syncWelcome(true);
      els.chatInput.value = lastUserText;
      autoGrow();
      App.toast(turn.failure, true);
      return;
    }
    finalizeTurn(turn);
    if (turn.meta.title) conv.title = turn.meta.title;
    if (turn.meta.last_message_at) conv.last_message_at = turn.meta.last_message_at;
    els.chatTitle.textContent = conversationTitle(conv);
    renderSessions();
  }

  /* ---------- 重新生成：回滚上一轮后用同一原文重放，流式覆盖本次回答 ---------- */
  async function regenerate(aiNode) {
    if (streaming) return;
    const conv = current();
    if (!conv) return;
    const allAi = els.messageList.querySelectorAll(".msg-row.assistant");
    if (allAi[allAi.length - 1] !== aiNode) { App.toast("只能重新生成最近一次回答"); return; }

    interruptedTurn = null;
    const oldActions = aiNode.querySelector(".msg-actions");
    if (oldActions) oldActions.remove();
    const bubble = aiNode.querySelector(".msg-bubble");
    bubble.innerHTML = '<div class="tool-trace"></div><div class="msg-blocks"></div>';
    bubble.classList.add("streaming");
    const turn = createTurn(aiNode);
    setStreamingUI(true);

    const payload = withWebFlag({ client_msg_id: newClientMsgId() });
    if (els.chatModel.value) payload.model_name = els.chatModel.value;

    await runStream("/api/agent/conversations/" + conv.id + "/messages/regenerate", payload, turn);

    if (turn.stopped) { await settleStopped(turn); return; }
    setStreamingUI(false);

    if (turn.failure) {
      App.toast(turn.failure, true);
      // 后端已回滚上一轮，前端按持久化状态重拉对齐，避免新旧回答混杂
      await loadMessages(conv);
      return;
    }
    finalizeTurn(turn);
    if (turn.meta.title) conv.title = turn.meta.title;
    if (turn.meta.last_message_at) conv.last_message_at = turn.meta.last_message_at;
    els.chatTitle.textContent = conversationTitle(conv);
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

  async function loadSkillOptions(force = false) {
    const conv = current();
    const personaId = conv && conv.persona_id ? Number(conv.persona_id) : null;
    if (force) {
      skillPick.loaded = false;
      skillPick.loading = false;
      skillPick.all = [];
    }
    if (skillPick.loading || (skillPick.loaded && skillPick.personaId === personaId)) return;
    skillPick.loading = true;
    try {
      const url = personaId
        ? "/api/agent/skills/available?persona_id=" + encodeURIComponent(personaId)
        : "/api/agent/skills/available";
      const res = await fetch(url);
      if (res.ok) {
        const data = await res.json();
        skillPick.all = (data.list || []).filter(s => s.status === "active");
      }
    } catch (e) {
      // 技能列表不可用时静默降级为普通输入
    } finally {
      skillPick.personaId = personaId;
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
    const restored = restoreConversationId();
    currentId = restored;
    if (restored !== null) rememberConversation(restored);
    else if (new URL(window.location.href).searchParams.has("conversation_id")) {
      // URL 指向的会话已不存在（被删除/换账号）：清掉参数，回到新建态
      rememberConversation(null);
    }
    renderSessions();
    const c = current();
    els.chatTitle.textContent = c ? conversationTitle(c) : "";
    syncModelSelect(c);
    els.welcomeTitle.textContent = greeting() + "，我能帮什么忙吗？";
    loadMessages(c);
    applySidebar(localStorage.getItem(SIDEBAR_KEY) === "1");
    autoGrow();
    setWebSearch(false);
    loadSkillOptions();

    els.btnNewChat.addEventListener("click", newChat);
    els.btnNewPersona.addEventListener("click", openPersonaModal);
    document.querySelectorAll("#personaModal [data-close]").forEach(btn => {
      btn.addEventListener("click", () => App.closeModal(btn.dataset.close));
    });
    document.getElementById("personaPickList").addEventListener("click", e => {
      const btn = e.target.closest(".persona-pick");
      if (!btn) return;
      App.closeModal("personaModal");
      newPersonaChat(Number(btn.dataset.personaId));
    });
    els.btnToggleSessions.addEventListener("click", () => {
      const collapsed = els.workbench.classList.contains("sessions-collapsed");
      localStorage.setItem(SIDEBAR_KEY, collapsed ? "0" : "1");
      applySidebar(!collapsed);
    });
    els.btnSend.addEventListener("click", () => {
      if (streaming) stopStream();
      else send();
    });
    els.btnWebSearch.addEventListener("click", () => setWebSearch(!webSearchOn));
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
      else if (actBtn.dataset.act === "continue") continueTurn(node.__turn);
    });
  }

  init();
})();
