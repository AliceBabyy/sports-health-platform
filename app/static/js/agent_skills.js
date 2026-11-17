/* AI 技能管理页：用户提示词编辑、平台只读展示、校验/试运行/发布/运行记录 */
(function () {
  "use strict";

  const S = {
    skills: Array.isArray(window.INIT_SKILLS) ? window.INIT_SKILLS.slice() : [],
    current: null,
  };

  const els = {};
  const $ = id => document.getElementById(id);

  function initEls() {
    ["platformList", "myList", "platformCount", "myCount", "editorEmpty", "skillForm",
      "editorKicker", "editorName", "editorSlash", "editorBadges",
      "fName", "fKey", "fAlias", "fCategory", "fDescription", "fDefinition",
      "fPrompt", "definitionSection", "promptSection",
      "editorResult", "testArgsWrap", "fTestArgs", "runPanel", "runList", "btnNewSkill",
      "btnEmptyNew", "workActions", "btnValidate", "btnTest", "btnRuns", "btnDelete", "btnDisable",
      "btnSave", "btnPublish", "btnCloseRuns"].forEach(id => { els[id] = $(id); });
  }

  function findSkill(id) {
    return S.skills.find(item => item.id === Number(id)) || null;
  }

  function badge(text, cls) {
    return '<span class="badge ' + (cls || "") + '">' + App.escapeHtml(text) + "</span>";
  }

  function renderList() {
    const platform = S.skills.filter(s => s.scope === "system");
    const mine = S.skills.filter(s => s.scope === "user");
    els.platformCount.textContent = String(platform.length);
    els.myCount.textContent = String(mine.length);
    els.platformList.innerHTML = platform.length
      ? platform.map(itemHtml).join("")
      : '<div class="si-empty">暂无平台技能</div>';
    els.myList.innerHTML = mine.length
      ? mine.map(itemHtml).join("")
      : '<div class="si-empty"><span>还没有自定义技能</span>' +
        '<button class="si-empty-new" type="button">新建一个</button></div>';
    document.querySelectorAll(".skill-item").forEach(btn => {
      btn.addEventListener("click", () => selectSkill(Number(btn.dataset.id)));
    });
    document.querySelectorAll(".si-empty-new").forEach(btn => {
      btn.addEventListener("click", newSkill);
    });
  }

  function itemHtml(s) {
    const active = S.current && S.current.id === s.id ? " active" : "";
    const mark = s.scope === "system" ? " platform" : "";
    let stateText = "已发布";
    let stateClass = "published";
    if (s.scope === "system") {
      stateText = "只读";
      stateClass = "";
    } else if (s.status === "disabled") {
      stateText = "已停用";
      stateClass = "disabled";
    } else if (s.published === false || s.status === "draft") {
      stateText = "草稿";
      stateClass = "draft";
    }
    const slash = s.slash_alias || s.name || s.key;
    const kindTag = s.kind === "prompt" ? " · 提示词" : s.kind === "declarative" ? " · 声明式" : " · 代码";
    const initial = (s.name || s.key || "技").trim().slice(0, 1);
    return '<button class="skill-item' + active + '" data-id="' + s.id + '" type="button">' +
      '<span class="si-mark' + mark + '">' + App.escapeHtml(initial) + "</span>" +
      '<span class="si-text">' +
        '<span class="si-name"><span class="si-name-text">' + App.escapeHtml(s.name) + "</span>" +
          '<span class="si-state ' + stateClass + '">' + stateText + "</span></span>" +
        '<span class="si-meta"><span class="si-slash">/' + App.escapeHtml(slash) + kindTag + "</span>" +
          '<span class="si-version">v' + (s.version_no || "—") + "</span></span>" +
      "</span>" +
      '<span class="si-arrow" aria-hidden="true">&rsaquo;</span></button>';
  }

  function selectSkill(id) {
    const skill = findSkill(id);
    if (!skill) return;
    S.current = skill;
    renderList();
    els.editorEmpty.hidden = true;
    els.skillForm.hidden = false;
    els.workActions.hidden = false;
    els.runPanel.hidden = true;
    els.editorSlash.hidden = false;
    els.editorName.textContent = skill.name;
    els.editorSlash.textContent = "/" + (skill.slash_alias || skill.name || skill.key);
    els.editorKicker.textContent = skill.scope === "system"
      ? "平台技能 · 只读"
      : skill.status === "active"
        ? "我的技能 · 已发布 v" + (skill.version_no || 1)
        : skill.status === "disabled"
          ? "我的技能 · 已停用 v" + (skill.version_no || 1)
          : "我的技能 · 草稿 v" + (skill.version_no || 1);
    els.editorBadges.innerHTML = [
      badge(skill.kind === "prompt" ? "提示词" : skill.kind === "code" ? "代码实现" : "声明式"),
      badge("v" + (skill.version_no || 1)),
    ].join("");

    els.fName.value = skill.name || "";
    els.fKey.value = skill.key || "";
    els.fAlias.value = skill.slash_alias || "";
    els.fCategory.value = skill.category || "custom";
    els.fDescription.value = skill.description || "";
    els.fPrompt.value = skill.kind === "prompt" ? ((skill.definition || {}).prompt || "") : "";
    els.fDefinition.value = skill.kind === "code"
      ? JSON.stringify({ kind: "code", key: skill.key, note: "平台技能由代码实现，定义只读" }, null, 2)
      : skill.kind === "prompt"
        ? ""
        : JSON.stringify(skill.definition || {}, null, 2);
    els.fTestArgs.value = "{}";
    setReadOnly(!skill.can_edit);
    els.btnDelete.hidden = !skill.can_delete;
    els.editorResult.innerHTML = "";
  }

  function currentKind() {
    return S.current ? S.current.kind : "prompt";
  }

  function syncKindUI() {
    const kind = currentKind();
    const isPrompt = kind === "prompt";
    els.definitionSection.hidden = isPrompt;
    els.promptSection.hidden = !isPrompt;
    els.testArgsWrap.hidden = isPrompt;
  }

  function setReadOnly(ro) {
    els.skillForm.classList.toggle("readonly", ro);
    els.fDefinition.rows = ro ? 8 : 22;
    ["fName", "fKey", "fAlias", "fCategory", "fDescription", "fDefinition", "fPrompt"].forEach(id => {
      els[id].disabled = ro;
    });
    ["btnSave", "btnPublish", "btnDisable"].forEach(id => {
      els[id].hidden = ro;
    });
    els.btnDelete.hidden = !(S.current && S.current.can_delete);
    syncKindUI();
    if (!ro && S.current) {
      els.btnDisable.hidden = S.current.status === "draft";
      els.btnDisable.textContent = S.current.status === "disabled" ? "启用" : "停用";
    }
  }

  function collect() {
    if (currentKind() !== "prompt") {
      showResult("用户技能只支持提示词类型", true);
      return null;
    }
    const text = els.fPrompt.value.trim();
    if (!text) {
      showResult("提示词不能为空", true);
      return null;
    }
    if (text.length > 4000) {
      showResult("提示词最多 4000 字", true);
      return null;
    }
    return {
      name: els.fName.value.trim(),
      key: els.fKey.value.trim(),
      slash_alias: els.fAlias.value.trim() || null,
      description: els.fDescription.value.trim(),
      category: els.fCategory.value,
      kind: "prompt",
      definition: { schema_version: 1, prompt: text },
    };
  }

  function showResult(payload, isError) {
    if (typeof payload === "string") {
      els.editorResult.innerHTML = '<div class="result-box ' + (isError ? "error" : "ok") + '">' +
        App.escapeHtml(payload) + "</div>";
      return;
    }
    const ok = payload && payload.ok !== false && !isError;
    let html = '<div class="result-box ' + (ok ? "ok" : "error") + '">';
    if (payload && payload.errors && payload.errors.length) {
      html += "<div>校验未通过：</div><ul>" + payload.errors.map(e =>
        "<li>" + App.escapeHtml(e.field) + "：" + App.escapeHtml(e.reason) + "</li>").join("") + "</ul>";
    } else if (payload && payload.summary) {
      html += "<div>" + App.escapeHtml(payload.summary) + "</div>";
    } else {
      html += "<div>" + (ok ? "校验通过" : "请求失败") + "</div>";
    }
    if (payload && payload.caveats && payload.caveats.length) {
      html += "<ul>" + payload.caveats.map(c => "<li>" + App.escapeHtml(c) + "</li>").join("") + "</ul>";
    }
    html += '<div class="result-json"><pre>' +
      App.escapeHtml(JSON.stringify(payload, null, 2)) + "</pre></div></div>";
    els.editorResult.innerHTML = html;
  }

  async function refresh(selectId) {
    const data = await App.api("/api/agent/skills");
    S.skills = data.list || [];
    if (selectId && findSkill(selectId)) selectSkill(selectId);
    else renderList();
  }

  async function saveDraft() {
    const body = collect();
    if (!body) return null;
    if (S.current && S.current.can_edit) {
      const saved = await App.api("/api/agent/skills/" + S.current.id, { method: "PUT", body });
      await refresh(saved.id);
      showResult({ ok: true, summary: "草稿已保存，版本 v" + (saved.version_no || "") }, false);
      return saved;
    }
    const created = await App.api("/api/agent/skills", { method: "POST", body });
    await refresh(created.id);
    showResult({ ok: true, summary: "已创建草稿，版本 v" + (created.version_no || 1) }, false);
    return created;
  }

  async function validateDefinition() {
    if (S.current && !S.current.can_edit) {
      const data = await App.api("/api/agent/skills/" + S.current.id + "/validate", {
        method: "POST", body: {},
      });
      showResult(data, !data.ok);
      return;
    }
    const body = collect();
    if (!body) return;
    const data = await App.api("/api/agent/skills/validate", {
      method: "POST", body: { kind: body.kind, definition: body.definition },
    });
    showResult(data, !data.ok);
  }

  async function publishSkill() {
    let saved = S.current;
    if (!saved || !saved.can_edit) {
      saved = await saveDraft();
      if (!saved) return;
    } else {
      saved = await saveDraft();
      if (!saved) return;
    }
    await App.api("/api/agent/skills/" + saved.id + "/publish", { method: "POST", body: {} });
    await refresh(saved.id);
    showResult({ ok: true, summary: "已发布，可用的工具名为 skill_" + saved.key }, false);
  }

  async function toggleStatus() {
    if (!S.current || !S.current.can_edit) return;
    const next = S.current.status === "disabled" ? "active" : "disabled";
    await App.api("/api/agent/skills/" + S.current.id + "/status", {
      method: "POST", body: { status: next },
    });
    await refresh(S.current.id);
    showResult({ ok: true, summary: next === "active" ? "已启用" : "已停用" }, false);
  }

  async function deleteSkill() {
    if (!S.current || !S.current.can_delete) return;
    const ok = await App.confirmDialog({
      title: "删除技能",
      message: "删除「" + S.current.name + "」及其全部版本和运行记录，不可恢复。",
    });
    if (!ok) return;
    await App.api("/api/agent/skills/" + S.current.id, { method: "DELETE" });
    S.current = null;
    els.skillForm.hidden = true;
    els.editorEmpty.hidden = false;
    els.workActions.hidden = true;
    els.runPanel.hidden = true;
    els.editorResult.innerHTML = "";
    els.editorKicker.textContent = "技能";
    els.editorName.textContent = "选择或新建技能";
    els.editorSlash.hidden = true;
    els.editorBadges.innerHTML = "";
    await refresh();
  }

  async function runSkill() {
    let target = S.current;
    if (!target) return;
    if (target.can_edit && (target.status === "draft" || target.published === false)) {
      target = await saveDraft();
      if (!target) return;
    }
    let args;
    try {
      args = JSON.parse(els.fTestArgs.value || "{}");
    } catch (e) {
      showResult("试运行参数不是合法 JSON：" + e.message, true);
      return;
    }
    const result = await App.api("/api/agent/skills/" + target.id + "/test", {
      method: "POST", body: { args },
    });
    showResult(result, !result.ok);
  }

  const RUN_STATUS = {
    ok: "成功",
    failed: "失败",
    invalid_args: "参数无效",
    insufficient_data: "数据不足",
  };

  async function loadRuns() {
    if (!S.current) return;
    const data = await App.api("/api/agent/skills/" + S.current.id + "/runs?limit=20");
    els.runPanel.hidden = false;
    const rows = data.list || [];
    els.runList.innerHTML = rows.length ? rows.map(r =>
      '<div class="run-row">' +
      '<div class="muted">' + App.escapeHtml((r.created_at || "").replace("T", " ").slice(0, 16)) + "</div>" +
      '<div class="run-status ' + App.escapeHtml(r.status) + '">' +
        App.escapeHtml(RUN_STATUS[r.status] || r.status) + "</div>" +
      '<div class="run-detail">' + App.escapeHtml(r.trigger || "") +
        (r.error_message ? " · " + App.escapeHtml(r.error_message) : "") +
        ' <span class="muted">' + App.escapeHtml(JSON.stringify(r.args || {})) + "</span></div>" +
      '<div class="muted">' + (r.duration_ms || 0) + " ms</div></div>"
    ).join("") : '<div class="run-row"><div class="muted">暂无运行记录</div></div>';
  }

  function newSkill() {
    S.current = null;
    renderList();
    els.editorEmpty.hidden = true;
    els.skillForm.hidden = false;
    els.workActions.hidden = false;
    els.runPanel.hidden = true;
    els.editorSlash.hidden = false;
    els.editorName.textContent = "新建技能";
    els.editorSlash.textContent = "/技能名";
    els.editorKicker.textContent = "我的技能 · 草稿";
    els.editorBadges.innerHTML = badge("提示词", "") + badge("v1");
    els.fName.value = "";
    els.fKey.value = "";
    els.fAlias.value = "";
    els.fCategory.value = "custom";
    els.fDescription.value = "";
    els.fDefinition.value = "";
    els.fPrompt.value = "";
    els.fTestArgs.value = "{}";
    els.editorResult.innerHTML = "";
    setReadOnly(false);
    els.btnDisable.hidden = true;
    els.btnDelete.hidden = true;
  }

  function bind() {
    els.btnNewSkill.addEventListener("click", newSkill);
    els.btnEmptyNew.addEventListener("click", newSkill);
    els.btnValidate.addEventListener("click", () => validateDefinition().catch(err => showResult(err.message, true)));
    els.btnSave.addEventListener("click", () => saveDraft().catch(err => showResult(err.message, true)));
    els.btnPublish.addEventListener("click", () => publishSkill().catch(err => showResult(err.message, true)));
    els.btnDisable.addEventListener("click", () => toggleStatus().catch(err => showResult(err.message, true)));
    els.btnDelete.addEventListener("click", () => deleteSkill().catch(err => showResult(err.message, true)));
    els.btnTest.addEventListener("click", () => {
      if (currentKind() !== "prompt") els.testArgsWrap.hidden = false;
      runSkill().catch(err => showResult(err.message, true));
    });
    els.btnRuns.addEventListener("click", () => loadRuns().catch(err => showResult(err.message, true)));
    els.btnCloseRuns.addEventListener("click", () => { els.runPanel.hidden = true; });
  }

  function init() {
    initEls();
    bind();
    renderList();
    const first = S.skills.find(s => s.scope === "system") || S.skills[0];
    if (first) selectSkill(first.id);
  }

  init();
})();
