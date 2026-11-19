/* 系统内置角色管理：管理员增删改查 + 工具/技能白名单勾选 */
(function () {
  "use strict";

  const S = {
    personas: Array.isArray(window.INIT_SYSTEM_PERSONAS) ? window.INIT_SYSTEM_PERSONAS.slice() : [],
    tools: Array.isArray(window.INIT_TOOL_OPTIONS) ? window.INIT_TOOL_OPTIONS.slice() : [],
    skills: Array.isArray(window.INIT_SKILL_OPTIONS) ? window.INIT_SKILL_OPTIONS.slice() : [],
    current: null,
    selectedTools: new Set(),
    selectedSkills: new Set(),
    toolMode: "default",
    skillMode: "default",
  };

  const TOOL_GROUP_LABELS = { read: "只读工具", interaction: "交互工具", write: "写入工具" };
  const SKILL_GROUP_LABELS = { code: "平台代码技能", declarative: "平台声明式技能", prompt: "平台提示词技能" };
  const TOOL_GROUP_ORDER = ["read", "interaction", "write"];
  const SKILL_GROUP_ORDER = ["code", "declarative", "prompt"];

  const els = {};
  const $ = id => document.getElementById(id);

  function initEls() {
    ["personaList", "personaCount", "editorEmpty", "personaForm", "editorKicker", "editorName",
      "editorBadges", "fName", "fKey", "fSort", "fStatus", "fDescription", "fPrompt",
      "toolChecks", "skillChecks", "toolModeNote", "skillModeNote", "editorResult",
      "btnNewPersona", "btnEmptyNew", "workActions", "btnSave", "btnDelete",
      "btnResetGrants", "versionHint"].forEach(id => { els[id] = $(id); });
  }

  function findPersona(id) {
    return S.personas.find(item => item.id === Number(id)) || null;
  }

  function badge(text, cls) {
    return '<span class="badge ' + (cls || "") + '">' + App.escapeHtml(text) + "</span>";
  }

  function itemHtml(p) {
    const active = S.current && S.current.id === p.id ? " active" : "";
    const state = p.status === "disabled" ? "已停用" : "已启用";
    const stateClass = p.status === "disabled" ? "disabled" : "published";
    const initial = (p.name || "角").trim().slice(0, 1);
    return '<button class="skill-item' + active + '" data-id="' + p.id + '" type="button">' +
      '<span class="si-mark platform">' + App.escapeHtml(initial) + "</span>" +
      '<span class="si-text">' +
        '<span class="si-name"><span class="si-name-text">' + App.escapeHtml(p.name) + "</span>" +
          '<span class="si-state ' + stateClass + '">' + state + "</span></span>" +
        '<span class="si-meta"><span class="si-slash">' + p.tool_count + " 工具 · " +
          p.skill_count + " 技能</span>" +
          '<span class="si-version">v' + (p.version_no || "—") + "</span></span>" +
      "</span>" +
      '<span class="si-arrow" aria-hidden="true">&rsaquo;</span></button>';
  }

  function renderList() {
    els.personaCount.textContent = String(S.personas.length);
    els.personaList.innerHTML = S.personas.length
      ? S.personas.map(itemHtml).join("")
      : '<div class="si-empty">暂无内置角色</div>';
    document.querySelectorAll(".system-personas-page .skill-item").forEach(btn => {
      btn.addEventListener("click", () => selectPersona(Number(btn.dataset.id)));
    });
  }

  function groupOptions(options, order, labels) {
    const groups = new Map();
    options.forEach(option => {
      const kind = option.kind || "read";
      if (!groups.has(kind)) groups.set(kind, []);
      groups.get(kind).push(option);
    });
    return order.filter(kind => groups.has(kind)).map(kind => ({
      kind: kind,
      label: labels[kind] || kind,
      options: groups.get(kind),
    }));
  }

  function optionHtml(option, type) {
    const checked = (type === "tool" ? S.selectedTools : S.selectedSkills).has(
      type === "tool" ? option.name : option.key
    );
    const key = type === "tool" ? option.name : option.key;
    const meta = type === "tool"
      ? (option.restricted ? "默认受限" : "默认可用")
      : ("v" + (option.version || "—") + (option.restricted ? " · 默认受限" : ""));
    return '<label class="check-item">' +
      '<input type="checkbox" data-type="' + type + '" data-key="' + App.escapeHtml(key) + '"' +
        (checked ? " checked" : "") + ">" +
      '<span class="check-copy">' +
        '<span class="check-title">' + App.escapeHtml(option.label || key) + "</span>" +
        '<span class="check-meta">' + App.escapeHtml(meta) + "</span>" +
        '<span class="check-desc">' + App.escapeHtml(option.description || "") + "</span>" +
      "</span></label>";
  }

  function renderChecks() {
    els.toolChecks.innerHTML = groupOptions(S.tools, TOOL_GROUP_ORDER, TOOL_GROUP_LABELS).map(group =>
      '<div class="check-group"><div class="check-group-title">' +
        App.escapeHtml(group.label) + "</div><div class=\"check-grid\">" +
        group.options.map(option => optionHtml(option, "tool")).join("") +
      "</div></div>"
    ).join("") || '<div class="check-empty">当前没有可配置工具</div>';

    els.skillChecks.innerHTML = groupOptions(S.skills, SKILL_GROUP_ORDER, SKILL_GROUP_LABELS).map(group =>
      '<div class="check-group"><div class="check-group-title">' +
        App.escapeHtml(group.label) + "</div><div class=\"check-grid\">" +
        group.options.map(option => optionHtml(option, "skill")).join("") +
      "</div></div>"
    ).join("") || '<div class="check-empty">当前没有已发布的平台技能</div>';

    els.toolChecks.querySelectorAll('input[type="checkbox"]').forEach(cb => {
      cb.addEventListener("change", () => {
        if (cb.checked) S.selectedTools.add(cb.dataset.key);
        else S.selectedTools.delete(cb.dataset.key);
        if (S.toolMode === "default") S.toolMode = "explicit";
        updateModeNotes();
      });
    });
    els.skillChecks.querySelectorAll('input[type="checkbox"]').forEach(cb => {
      cb.addEventListener("change", () => {
        if (cb.checked) S.selectedSkills.add(cb.dataset.key);
        else S.selectedSkills.delete(cb.dataset.key);
        if (S.skillMode === "default") S.skillMode = "explicit";
        updateModeNotes();
      });
    });
    updateModeNotes();
  }

  function updateModeNotes() {
    els.toolModeNote.textContent = S.toolMode === "default"
      ? "默认范围：未受限工具全开，受限工具按平台规则"
      : "已锁定：" + S.selectedTools.size + " 个工具";
    els.skillModeNote.textContent = S.skillMode === "default"
      ? "默认范围：全部平台技能可用"
      : "已锁定：" + S.selectedSkills.size + " 个技能";
  }

  function selectPersona(id) {
    const p = findPersona(id);
    if (!p) return;
    S.current = p;
    S.toolMode = p.tool_grants === null ? "default" : "explicit";
    S.skillMode = p.skill_grants === null ? "default" : "explicit";
    S.selectedTools = new Set(p.effective_tools || []);
    S.selectedSkills = new Set(p.effective_skills || []);
    renderList();
    els.editorEmpty.hidden = true;
    els.personaForm.hidden = false;
    els.workActions.hidden = false;
    els.editorName.textContent = p.name;
    els.editorKicker.textContent = p.status === "disabled" ? "内置角色 · 已停用" : "内置角色 · 已启用";
    els.editorBadges.innerHTML = [
      badge("平台内置"),
      badge("v" + (p.version_no || 1)),
      badge(p.tool_count + " 工具"),
      badge(p.skill_count + " 技能"),
    ].join("");
    els.fName.value = p.name || "";
    els.fKey.value = p.key || "";
    els.fKey.readOnly = true;
    els.fSort.value = String(p.sort_order || 0);
    els.fStatus.value = p.status || "active";
    els.fDescription.value = p.description || "";
    els.fPrompt.value = ((p.definition || {}).prompt) || "";
    els.versionHint.textContent = "当前 v" + (p.version_no || 1) +
      "；提示词变更生成新版本，工具/技能范围保存后即时生效";
    els.btnDelete.hidden = !p.can_delete;
    els.btnResetGrants.hidden = false;
    renderChecks();
    clearResult();
  }

  let pendingKey = "";

  function newPersona() {
    S.current = null;
    pendingKey = "builtin_" + Date.now().toString(36);
    S.toolMode = "default";
    S.skillMode = "default";
    S.selectedTools = new Set(S.tools.filter(item => !item.restricted).map(item => item.name));
    S.selectedSkills = new Set(S.skills.filter(item => !item.restricted).map(item => item.key));
    els.editorEmpty.hidden = true;
    els.personaForm.hidden = false;
    els.workActions.hidden = false;
    els.editorName.textContent = "新建内置角色";
    els.editorKicker.textContent = "内置角色 · 新建";
    els.editorBadges.innerHTML = badge("平台内置");
    els.fName.value = "";
    els.fKey.value = pendingKey;
    els.fKey.readOnly = false;
    els.fSort.value = String(S.personas.length);
    els.fStatus.value = "active";
    els.fDescription.value = "";
    els.fPrompt.value = "";
    els.versionHint.textContent = "保存后立即生效；角色键创建后不可修改";
    els.btnDelete.hidden = true;
    els.btnResetGrants.hidden = false;
    renderList();
    renderChecks();
    clearResult();
    els.fName.focus();
  }

  function resetGrants() {
    if (S.current) {
      S.selectedTools = new Set(S.current.default_tools || []);
      S.selectedSkills = new Set(S.current.default_skills || []);
    } else {
      S.selectedTools = new Set(S.tools.filter(item => !item.restricted).map(item => item.name));
      S.selectedSkills = new Set(S.skills.filter(item => !item.restricted).map(item => item.key));
    }
    S.toolMode = "default";
    S.skillMode = "default";
    renderChecks();
    showErrors({ ok: true, summary: "已恢复默认范围；保存后按平台默认规则生效" }, false);
  }

  function payload() {
    const prompt = els.fPrompt.value.trim();
    if (!els.fName.value.trim()) return { error: "角色名不能为空" };
    if (!els.fKey.value.trim()) return { error: "角色键不能为空" };
    if (!prompt) return { error: "角色提示词不能为空" };
    if (prompt.length > window.PERSONA_MAX_CHARS) {
      return { error: "角色提示词最多 " + window.PERSONA_MAX_CHARS + " 字" };
    }
    const sortOrder = Number(els.fSort.value || 0);
    if (!Number.isInteger(sortOrder) || sortOrder < 0 || sortOrder > 9999) {
      return { error: "排序需为 0~9999 的整数" };
    }
    return {
      body: {
        key: els.fKey.value.trim(),
        name: els.fName.value.trim(),
        description: els.fDescription.value.trim(),
        definition: { schema_version: 1, prompt: prompt },
        status: els.fStatus.value,
        sort_order: sortOrder,
        tool_grants: S.toolMode === "default" ? null : Array.from(S.selectedTools).sort(),
        skill_grants: S.skillMode === "default" ? null : Array.from(S.selectedSkills).sort(),
      },
    };
  }

  function clearResult() {
    els.editorResult.innerHTML = "";
  }

  function showErrors(payload, isError) {
    const ok = payload && payload.ok !== false && !isError;
    let html = '<div class="result-box ' + (ok ? "ok" : "error") + '">';
    if (payload && payload.errors && payload.errors.length) {
      html += "<div>校验未通过：</div><ul>" + payload.errors.map(e =>
        "<li>" + App.escapeHtml(e.field) + "：" + App.escapeHtml(e.reason) + "</li>").join("") + "</ul>";
    } else {
      html += "<div>" + App.escapeHtml(payload && payload.summary
        ? payload.summary : (ok ? "保存成功" : "请求失败")) + "</div>";
    }
    html += "</div>";
    els.editorResult.innerHTML = html;
  }

  async function refresh(selectId) {
    const data = await App.api("/api/system/system-personas");
    S.personas = data.list || [];
    if (selectId && findPersona(selectId)) selectPersona(selectId);
    else renderList();
  }

  async function savePersona() {
    const collected = payload();
    if (collected.error) { showErrors({ summary: collected.error }, true); return; }
    try {
      if (S.current) {
        const saved = await App.api("/api/system/system-personas/" + S.current.id, {
          method: "PUT", body: collected.body,
        });
        await refresh(saved.id);
        showErrors({ ok: true, summary: "已保存：v" + (saved.version_no || "") +
          "，工具 " + saved.tool_count + " 个、技能 " + saved.skill_count + " 个" }, false);
      } else {
        const created = await App.api("/api/system/system-personas", {
          method: "POST", body: collected.body,
        });
        await refresh(created.id);
        showErrors({ ok: true, summary: "内置角色已创建：v" + (created.version_no || 1) }, false);
      }
    } catch (err) {
      showErrors({ errors: err.errors || [], summary: err.message }, true);
    }
  }

  async function deletePersona() {
    if (!S.current || !S.current.can_delete) {
      showErrors({ summary: "该角色已有角色会话，请先删除相关会话" }, true);
      return;
    }
    const ok = await App.confirmDialog({
      title: "删除内置角色",
      message: "删除「" + S.current.name + "」及其全部版本，不可恢复。",
    });
    if (!ok) return;
    try {
      await App.api("/api/system/system-personas/" + S.current.id, { method: "DELETE" });
      S.current = null;
      await refresh();
      els.personaForm.hidden = true;
      els.workActions.hidden = true;
      els.editorEmpty.hidden = false;
      els.editorName.textContent = "选择或新建角色";
      els.editorKicker.textContent = "内置角色";
      els.editorBadges.innerHTML = "";
      els.versionHint.textContent = "";
      App.toast("内置角色已删除");
    } catch (err) {
      showErrors({ summary: err.message }, true);
    }
  }

  function bind() {
    els.btnNewPersona.addEventListener("click", newPersona);
    els.btnEmptyNew.addEventListener("click", newPersona);
    els.btnSave.addEventListener("click", savePersona);
    els.btnDelete.addEventListener("click", deletePersona);
    els.btnResetGrants.addEventListener("click", resetGrants);
  }

  document.addEventListener("DOMContentLoaded", () => {
    initEls();
    bind();
    renderList();
    if (S.personas.length) selectPersona(S.personas[0].id);
  });
})();
