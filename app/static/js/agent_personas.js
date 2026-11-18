/* 角色管理页：平台角色只读展示、用户角色提示词编辑（保存即生效） */
(function () {
  "use strict";

  const S = {
    personas: Array.isArray(window.INIT_PERSONAS) ? window.INIT_PERSONAS.slice() : [],
    current: null,
  };

  const els = {};
  const $ = id => document.getElementById(id);

  function initEls() {
    ["platformList", "myList", "platformCount", "myCount", "editorEmpty", "personaForm",
      "editorKicker", "editorName", "editorBadges", "fName", "fKey", "fDescription", "fPrompt",
      "editorResult", "btnNewPersona", "btnEmptyNew", "workActions", "btnSave", "btnDisable",
      "btnDelete", "versionHint"].forEach(id => { els[id] = $(id); });
  }

  function findPersona(id) {
    return S.personas.find(item => item.id === Number(id)) || null;
  }

  function badge(text, cls) {
    return '<span class="badge ' + (cls || "") + '">' + App.escapeHtml(text) + "</span>";
  }

  function itemHtml(p) {
    const active = S.current && S.current.id === p.id ? " active" : "";
    const mark = p.scope === "system" ? " platform" : "";
    const state = p.scope === "system" ? "只读" : (p.status === "disabled" ? "已停用" : "已启用");
    const stateClass = p.scope === "system" ? "" : (p.status === "disabled" ? "disabled" : "published");
    const initial = (p.name || "角").trim().slice(0, 1);
    return '<button class="skill-item' + active + '" data-id="' + p.id + '" type="button">' +
      '<span class="si-mark' + mark + '">' + App.escapeHtml(initial) + "</span>" +
      '<span class="si-text">' +
        '<span class="si-name"><span class="si-name-text">' + App.escapeHtml(p.name) + "</span>" +
          '<span class="si-state ' + stateClass + '">' + state + "</span></span>" +
        '<span class="si-meta"><span class="si-slash">' +
          (p.scope === "system" ? "平台内置" : "自定义提示词") + "</span>" +
          '<span class="si-version">v' + (p.version_no || "—") + "</span></span>" +
      "</span>" +
      '<span class="si-arrow" aria-hidden="true">&rsaquo;</span></button>';
  }

  function renderList() {
    const platform = S.personas.filter(p => p.scope === "system");
    const mine = S.personas.filter(p => p.scope === "user");
    els.platformCount.textContent = String(platform.length);
    els.myCount.textContent = String(mine.length);
    els.platformList.innerHTML = platform.length
      ? platform.map(itemHtml).join("")
      : '<div class="si-empty">暂无平台角色</div>';
    els.myList.innerHTML = mine.length
      ? mine.map(itemHtml).join("")
      : '<div class="si-empty"><span>还没有自定义角色</span>' +
        '<button class="si-empty-new" type="button">新建一个</button></div>';
    document.querySelectorAll(".persona-item, .personas-page .skill-item").forEach(btn => {
      btn.addEventListener("click", () => selectPersona(Number(btn.dataset.id)));
    });
    document.querySelectorAll(".si-empty-new").forEach(btn => {
      btn.addEventListener("click", newPersona);
    });
  }

  function setReadOnly(readonly) {
    els.fName.readOnly = readonly;
    els.fKey.readOnly = readonly;
    els.fDescription.readOnly = readonly;
    els.fPrompt.readOnly = readonly;
    els.fPrompt.classList.toggle("is-readonly", readonly);
  }

  function clearResult() {
    els.editorResult.innerHTML = "";
  }

  function selectPersona(id) {
    const p = findPersona(id);
    if (!p) return;
    S.current = p;
    renderList();
    els.editorEmpty.hidden = true;
    els.personaForm.hidden = false;
    els.workActions.hidden = false;
    els.editorName.textContent = p.name;
    els.editorKicker.textContent = p.scope === "system"
      ? "平台角色 · 只读"
      : p.status === "disabled" ? "我的角色 · 已停用" : "我的角色 · 已启用";
    els.editorBadges.innerHTML = [
      badge(p.scope === "system" ? "平台内置" : "自定义提示词"),
      badge("v" + (p.version_no || 1)),
    ].join("");
    els.fName.value = p.name || "";
    els.fKey.value = p.key || "";
    els.fDescription.value = p.description || "";
    els.fPrompt.value = ((p.definition || {}).prompt) || "";
    els.versionHint.textContent = p.scope === "system"
      ? "平台内置角色只读"
      : "当前版本 v" + (p.version_no || 1) + "，保存即生成新版本并生效";
    els.btnDelete.hidden = !p.can_delete;
    els.btnDisable.hidden = !p.can_edit;
    els.btnSave.hidden = !p.can_edit;
    els.btnDisable.textContent = p.status === "disabled" ? "启用" : "停用";
    setReadOnly(!p.can_edit);
    clearResult();
  }

  let pendingKey = "";

  function newPersona() {
    S.current = null;
    pendingKey = "p" + Date.now().toString(36);
    els.editorEmpty.hidden = true;
    els.personaForm.hidden = false;
    els.workActions.hidden = false;
    els.editorName.textContent = "新角色";
    els.editorKicker.textContent = "我的角色 · 新建";
    els.editorBadges.innerHTML = badge("自定义提示词");
    els.fName.value = "";
    els.fKey.value = pendingKey;
    els.fDescription.value = "";
    els.fPrompt.value = "";
    els.versionHint.textContent = "保存后立即生效";
    els.btnDelete.hidden = true;
    els.btnDisable.hidden = true;
    els.btnSave.hidden = false;
    setReadOnly(false);
    renderList();
    clearResult();
    els.fName.focus();
  }

  function payload() {
    const text = els.fPrompt.value.trim();
    if (!text) return { error: "角色提示词不能为空" };
    if (text.length > window.PERSONA_MAX_CHARS) {
      return { error: "角色提示词最多 " + window.PERSONA_MAX_CHARS + " 字" };
    }
    return {
      body: {
        name: els.fName.value.trim(),
        key: els.fKey.value.trim() || pendingKey,
        description: els.fDescription.value.trim(),
        definition: { schema_version: 1, prompt: text },
      },
    };
  }

  function showErrors(payload, isError) {
    const ok = payload && payload.ok !== false && !isError;
    let html = '<div class="result-box ' + (ok ? "ok" : "error") + '">';
    if (payload && payload.errors && payload.errors.length) {
      html += "<div>校验未通过：</div><ul>" + payload.errors.map(e =>
        "<li>" + App.escapeHtml(e.field) + "：" + App.escapeHtml(e.reason) + "</li>").join("") + "</ul>";
    } else {
      html += "<div>" + App.escapeHtml(payload && payload.summary ? payload.summary : (ok ? "保存成功" : "请求失败")) + "</div>";
    }
    html += "</div>";
    els.editorResult.innerHTML = html;
  }

  async function refresh(selectId) {
    const data = await App.api("/api/agent/personas");
    S.personas = data.list || [];
    if (selectId && findPersona(selectId)) selectPersona(selectId);
    else renderList();
  }

  async function savePersona() {
    const collected = payload();
    if (collected.error) { showErrors({ summary: collected.error }, true); return; }
    try {
      if (S.current && S.current.can_edit) {
        const saved = await App.api("/api/agent/personas/" + S.current.id, {
          method: "PUT", body: collected.body,
        });
        await refresh(saved.id);
        showErrors({ ok: true, summary: "已保存并生效：v" + (saved.version_no || "") }, false);
      } else {
        const created = await App.api("/api/agent/personas", {
          method: "POST", body: collected.body,
        });
        await refresh(created.id);
        showErrors({ ok: true, summary: "角色已创建，v" + (created.version_no || 1) }, false);
      }
    } catch (err) {
      showErrors({ errors: err.errors || [], summary: err.message }, true);
    }
  }

  async function toggleStatus() {
    if (!S.current || !S.current.can_edit) return;
    const next = S.current.status === "disabled" ? "active" : "disabled";
    try {
      await App.api("/api/agent/personas/" + S.current.id + "/status", {
        method: "POST", body: { status: next },
      });
      await refresh(S.current.id);
      showErrors({ ok: true, summary: next === "active" ? "已启用" : "已停用，已有角色会话仍可继续" }, false);
    } catch (err) {
      showErrors({ summary: err.message }, true);
    }
  }

  async function deletePersona() {
    if (!S.current || !S.current.can_delete) return;
    const ok = await App.confirmDialog({
      title: "删除角色",
      message: "删除「" + S.current.name + "」及其全部版本，不可恢复。该角色已有会话时需先删除会话。",
    });
    if (!ok) return;
    try {
      await App.api("/api/agent/personas/" + S.current.id, { method: "DELETE" });
      S.current = null;
      await refresh();
      els.personaForm.hidden = true;
      els.workActions.hidden = true;
      els.editorEmpty.hidden = false;
      els.editorName.textContent = "选择或新建角色";
      els.editorKicker.textContent = "角色";
      els.editorBadges.innerHTML = "";
      els.versionHint.textContent = "";
      App.toast("角色已删除");
    } catch (err) {
      showErrors({ summary: err.message }, true);
    }
  }

  function bind() {
    els.btnNewPersona.addEventListener("click", newPersona);
    els.btnEmptyNew.addEventListener("click", newPersona);
    els.btnSave.addEventListener("click", savePersona);
    els.btnDisable.addEventListener("click", toggleStatus);
    els.btnDelete.addEventListener("click", deletePersona);
  }

  document.addEventListener("DOMContentLoaded", () => {
    initEls();
    bind();
    renderList();
  });
})();
