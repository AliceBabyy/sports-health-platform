/* AI Agent 前端：会话管理、消息渲染、fetch + ReadableStream 手动解析 SSE（EventSource 不支持 POST） */
(function () {
  const conversations = [...window.INIT_CONVERSATIONS];
  let currentId = conversations.length ? conversations[0].id : null;
  let streaming = false;
  let lastUserText = "";

  const els = {
    sessionList: document.getElementById("sessionList"),
    btnNewChat: document.getElementById("btnNewChat"),
    chatTitle: document.getElementById("chatTitle"),
    chatModel: document.getElementById("chatModel"),
    messageScroll: document.getElementById("messageScroll"),
    messageList: document.getElementById("messageList"),
    chatInput: document.getElementById("chatInput"),
    btnSend: document.getElementById("btnSend"),
  };

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
        App.escapeHtml(content) + '</div></div></div>';
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
      els.messageList.innerHTML = '<div class="chat-empty">左侧新建或选择一个会话开始对话</div>';
      return;
    }
    try {
      const res = await App.api("/api/agent/conversations/" + conv.id + "/messages");
      if (!res.messages.length) {
        els.messageList.innerHTML = '<div class="chat-empty">开始你的第一条消息吧</div>';
        return;
      }
      els.messageList.innerHTML = res.messages.map(m => bubbleHtml(m.role, m.content, false)).join("");
      scrollBottom();
    } catch (err) {
      App.toast(err.message, true);
    }
  }

  async function selectConversation(id) {
    if (streaming) { App.toast("请等待当前回复完成"); return; }
    currentId = id;
    const conv = current();
    els.chatTitle.textContent = conv ? conv.title : "新会话";
    syncModelSelect(conv);
    renderSessions();
    await loadMessages(conv);
  }

  /* ---------- 新建 / 重命名 / 删除 ---------- */
  async function newChat() {
    if (streaming) return;
    try {
      const conv = await App.api("/api/agent/conversations", {
        method: "POST",
        body: { model_name: els.chatModel.value || null },
      });
      conversations.push(conv);
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
        els.chatTitle.textContent = c ? c.title : "新会话";
        syncModelSelect(c);
        await loadMessages(c);
      }
      renderSessions();
    } catch (err) {
      App.toast(err.message, true);
    }
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
    const conv = current();
    if (!conv || streaming) return;
    const text = els.chatInput.value.trim();
    if (!text) return;

    lastUserText = text;
    const userNode = appendBubble("user", text);
    const aiNode = appendBubble("assistant", "", true);
    const aiBubble = aiNode.querySelector(".msg-bubble");
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
          if (evt.event === "delta") {
            acc += evt.data.content;
            aiBubble.textContent = acc;
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
      els.chatInput.value = lastUserText;
      autoGrow();
      App.toast(failure, true);
    } else {
      els.chatTitle.textContent = conv.title;
      renderSessions();
    }
  }

  /* ---------- 输入框自动增高 ---------- */
  function autoGrow() {
    const el = els.chatInput;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 140) + "px";
  }

  /* ---------- 初始化 ---------- */
  function init() {
    renderSessions();
    const c = current();
    els.chatTitle.textContent = c ? c.title : "新会话";
    syncModelSelect(c);
    loadMessages(c);

    els.btnNewChat.addEventListener("click", newChat);
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
