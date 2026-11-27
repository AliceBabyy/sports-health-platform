/* 系统内置技能管理：平台技能列表 + 提示词/声明式编辑 + 启停/删除/校验/试运行/运行记录 */
(function () {
  "use strict";

  const S = {
    skills: Array.isArray(window.INIT_SYSTEM_SKILLS) ? window.INIT_SYSTEM_SKILLS.slice() : [],
    current: null,
    readOnly: false,
  };

  const KIND_LABEL = { code: "代码实现", prompt: "提示词", declarative: "声明式" };
  const RUN_STATUS = {
    ok: "成功",
    failed: "失败",
    invalid_args: "参数无效",
    insufficient_data: "数据不足",
  };
  const TRIGGER_LABEL = { test: "试运行", slash: "斜杠", model: "模型" };

  const els = {};
  const $ = id => document.getElementById(id);

  function initEls() {
    ["codeList", "promptList", "declarativeList", "codeCount", "promptCount",
      "declarativeCount", "editorEmpty", "skillForm", "editorKicker", "editorName",
      "editorSlash", "editorBadges", "kindRow", "fName", "fKey", "fAlias", "fCategory",
      "fStatus", "fDescription", "promptSection", "fPrompt", "definitionSection",
      "fDefinition", "definitionNote", "definitionHint", "codeNote", "fTestArgs",
      "testArgsSection", "editorResult", "runPanel", "runList", "btnNewSkill",
      "btnEmptyNew",
      "workActions", "btnValidate", "btnTest", "btnRuns", "btnDelete", "btnSave",
      "btnCloseRuns", "versionHint"].forEach(id => { els[id] = $(id); });
  }

  function findSkill(id) {
    return S.skills.find(item => item.id === Number(id)) || null;
  }

  function newKind() {
    const checked = document.querySelector('input[name="newKind"]:checked');
    return checked ? checked.value : "prompt";
  }

  function badge(text, cls) {
    return '<span class="badge ' + (cls || "") + '">' + App.escapeHtml(text) + "</span>";
  }

  function itemHtml(s) {
    const active = S.current && S.current.id === s.id ? " active" : "";
    const disabled = s.status === "disabled";
    const stateText = disabled ? "已停用" : (s.kind === "code" ? "代码内置" : "已发布");
    const stateClass = disabled ? "disabled" : (s.kind === "code" ? "" : "published");
    const initial = (s.name || s.key || "技").trim().slice(0, 1);
    const slash = "/" + (s.slash_alias || s.key);
    return '<button class="skill-item' + active + '" data-id="' + s.id + '" type="button">' +
      '<span class="si-mark platform">' + App.escapeHtml(initial) + "</span>" +
      '<span class="si-text">' +
        '<span class="si-name"><span class="si-name-text">' + App.escapeHtml(s.name) + "</span>" +
          '<span class="si-state ' + stateClass + '">' + stateText + "</span></span>" +
        '<span class="si-meta"><span class="si-slash">' + App.escapeHtml(slash) +
          " · " + (KIND_LABEL[s.kind] || s.kind) + "</span>" +
          '<span class="si-version">v' + (s.version_no || "—") + "</span></span>" +
      "</span>" +
      '<span class="si-arrow" aria-hidden="true">&rsaquo;</span></button>';
  }

  function renderList() {
    const code = S.skills.filter(item => item.kind === "code");
    const prompt = S.skills.filter(item => item.kind === "prompt");
    const declarative = S.skills.filter(item => item.kind === "declarative");
    els.codeCount.textContent = String(code.length);
    els.promptCount.textContent = String(prompt.length);
    els.declarativeCount.textContent = String(declarative.length);
    els.codeList.innerHTML = code.length
      ? code.map(itemHtml).join("")
      : '<div class="si-empty">暂无代码技能</div>';
    els.promptList.innerHTML = prompt.length
      ? prompt.map(itemHtml).join("")
      : '<div class="si-empty">暂无提示词技能</div>';
    els.declarativeList.innerHTML = declarative.length
      ? declarative.map(itemHtml).join("")
      : '<div class="si-empty">暂无声明式技能</div>';
    document.querySelectorAll(".system-skills-page .skill-item").forEach(btn => {
      btn.addEventListener("click", () => selectSkill(Number(btn.dataset.id)));
    });
  }

  function setKindMode(kind) {
    const isPrompt = kind === "prompt";
    els.promptSection.hidden = !isPrompt;
    els.definitionSection.hidden = isPrompt;
    els.testArgsSection.hidden = isPrompt;
    if (!els.definitionSection.hidden) {
      els.definitionNote.textContent = kind === "code" ? "只读" : "声明式";
    }
  }

  function setReadOnly(readOnly) {
    S.readOnly = readOnly;
    ["fName", "fKey", "fAlias", "fCategory", "fDescription", "fDefinition", "fPrompt"]
      .forEach(id => { els[id].disabled = readOnly; });
    els.fStatus.disabled = false;
    els.btnValidate.hidden = readOnly;
    els.btnDelete.hidden = readOnly || !(S.current && S.current.can_delete);
    els.btnSave.textContent = readOnly ? "保存状态" : "保存并生效";
    els.codeNote.hidden = !readOnly;
    els.definitionHint.hidden = readOnly;
    els.fDefinition.classList.toggle("is-readonly", readOnly);
    if (readOnly) {
      els.codeNote.textContent = "代码技能由平台代码注册，定义不可在页面编辑；"
        + "可停用或重新启用，停用后立即从系统图中移除。";
    }
  }

  function setCodeMode() {
    S.readOnly = false;
    ["fName", "fAlias", "fCategory", "fDescription", "fStatus"]
      .forEach(id => { els[id].disabled = false; });
    els.fKey.disabled = false;
    els.fKey.readOnly = true;
    els.fDefinition.disabled = true;
    els.fPrompt.disabled = true;
    els.btnValidate.hidden = true;
    els.btnDelete.hidden = true;
    els.btnSave.textContent = "保存信息";
    els.codeNote.hidden = false;
    els.definitionHint.hidden = true;
    els.fDefinition.classList.add("is-readonly");
    els.codeNote.textContent = "代码技能由平台代码注册，定义不可编辑；"
      + "名称、斜杠别名、描述、分类与启停可在此调整。";
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
    els.kindRow.hidden = true;
    els.editorSlash.hidden = false;
    els.editorName.textContent = skill.name;
    els.editorSlash.textContent = "/" + (skill.slash_alias || skill.key);
    const kindLabel = KIND_LABEL[skill.kind] || skill.kind;
    els.editorKicker.textContent = "内置技能 · " + kindLabel +
      (skill.status === "disabled" ? " · 已停用" : "");
    els.editorBadges.innerHTML = [
      badge(kindLabel),
      badge("平台内置"),
      badge("v" + (skill.version_no || "—")),
      badge("累计 " + (skill.run_count || 0) + " 次运行"),
    ].join("");

    els.fName.value = skill.name || "";
    els.fKey.value = skill.key || "";
    els.fKey.readOnly = true;
    els.fAlias.value = skill.slash_alias || "";
    els.fCategory.value = skill.category || "custom";
    els.fStatus.value = skill.status || "active";
    els.fDescription.value = skill.description || "";
    els.fPrompt.value = skill.kind === "prompt"
      ? ((skill.definition && skill.definition.prompt) || "")
      : "";
    els.fDefinition.value = skill.kind === "prompt"
      ? ""
      : JSON.stringify(skill.definition || {}, null, 2);
    els.fTestArgs.value = "{}";
    els.btnRuns.hidden = false;
    setKindMode(skill.kind);
    els.versionHint.textContent = skill.kind === "code"
      ? "代码技能定义由代码维护；名称、别名、描述、分类与状态保存后立即生效"
      : "当前 " + (skill.version_no ? "v" + skill.version_no : "未发布") +
        "；内容变更生成新版本并立即生效";
    if (skill.kind === "code") setCodeMode();
    else setReadOnly(false);
    clearResult();
  }

  function showEmpty() {
    S.current = null;
    els.skillForm.hidden = true;
    els.workActions.hidden = true;
    els.runPanel.hidden = true;
    els.kindRow.hidden = true;
    els.editorEmpty.hidden = false;
    els.editorName.textContent = "选择或新建技能";
    els.editorKicker.textContent = "内置技能";
    els.editorSlash.hidden = true;
    els.editorBadges.innerHTML = "";
    els.versionHint.textContent = "";
    els.editorResult.innerHTML = "";
    renderList();
  }

  function syncNewKind() {
    if (S.current) return;
    const kind = newKind();
    els.editorBadges.innerHTML = badge(KIND_LABEL[kind]) + badge("平台内置") + badge("v1");
    setKindMode(kind);
  }

  function newSkill() {
    S.current = null;
    renderList();
    els.editorEmpty.hidden = true;
    els.skillForm.hidden = false;
    els.workActions.hidden = false;
    els.runPanel.hidden = true;
    els.kindRow.hidden = false;
    els.editorSlash.hidden = false;
    els.editorName.textContent = "新建内置技能";
    els.editorSlash.textContent = "/技能名";
    els.editorKicker.textContent = "内置技能 · 新建";
    els.fName.value = "";
    els.fKey.value = "builtin_" + Date.now().toString(36);
    els.fKey.readOnly = false;
    els.fAlias.value = "";
    els.fCategory.value = "custom";
    els.fStatus.value = "active";
    els.fDescription.value = "";
    els.fPrompt.value = "";
    els.fDefinition.value = "";
    els.fTestArgs.value = "{}";
    els.btnRuns.hidden = true;
    els.versionHint.textContent = "保存后立即发布 v1；技能键创建后不可修改";
    setReadOnly(false);
    els.btnDelete.hidden = true;
    els.btnTest.hidden = false;
    els.editorBadges.innerHTML = "";
    syncNewKind();
    clearResult();
    els.fName.focus();
  }

  function parseJsonField(value, label) {
    try {
      return { value: JSON.parse(value || "{}") };
    } catch (err) {
      return { error: label + "不是合法 JSON：" + err.message };
    }
  }

  function currentKind() {
    return S.current ? S.current.kind : newKind();
  }

  function collectDefinition(kind) {
    if (kind === "prompt") {
      const prompt = els.fPrompt.value.trim();
      if (!prompt) return { error: "提示词不能为空" };
      return { value: { schema_version: 1, prompt } };
    }
    return parseJsonField(els.fDefinition.value, "技能定义");
  }

  function collectMeta() {
    const name = els.fName.value.trim();
    const key = els.fKey.value.trim();
    const alias = els.fAlias.value.trim();
    if (!name) return { error: "技能名不能为空" };
    if (!key) return { error: "技能键不能为空" };
    return {
      body: {
        key: key,
        name: name,
        slash_alias: alias || null,
        description: els.fDescription.value.trim(),
        category: els.fCategory.value,
        status: els.fStatus.value,
      },
    };
  }

  function collect() {
    const meta = collectMeta();
    if (meta.error) return meta;
    const kind = currentKind();
    const parsed = collectDefinition(kind);
    if (parsed.error) return parsed;
    return {
      body: {
        ...meta.body,
        kind: kind,
        definition: parsed.value,
      },
    };
  }

  function clearResult() {
    els.editorResult.innerHTML = "";
  }

  function showResult(payload, isError) {
    if (typeof payload === "string") {
      els.editorResult.innerHTML = '<div class="result-box ' +
        (isError ? "error" : "ok") + '">' + App.escapeHtml(payload) + "</div>";
      return;
    }
    const ok = payload && payload.ok !== false && !isError;
    let html = '<div class="result-box ' + (ok ? "ok" : "error") + '">';
    if (payload && payload.errors && payload.errors.length) {
      html += "<div>校验未通过：</div><ul>" + payload.errors.map(e =>
        "<li>" + App.escapeHtml(e.field || "definition") + "：" +
        App.escapeHtml(e.reason || "") + "</li>").join("") + "</ul>";
    } else if (payload && payload.missing && payload.missing.length) {
      html += "<div>缺少参数：" + App.escapeHtml(payload.missing.join("、")) + "</div>";
    } else if (payload && payload.summary) {
      html += "<div>" + App.escapeHtml(payload.summary) + "</div>";
    } else {
      html += "<div>" + App.escapeHtml(ok ? "校验通过" : "请求失败") + "</div>";
    }
    if (payload && payload.warnings && payload.warnings.length) {
      html += '<div class="result-caveats">' + payload.warnings.map(w =>
        "<div>" + App.escapeHtml(w) + "</div>").join("") + "</div>";
    }
    if (payload && payload.outputs && payload.outputs.length) {
      html += '<div class="result-outputs"><table><tbody>' + payload.outputs.map(o =>
        "<tr><th>" + App.escapeHtml(o.label || o.key) + "</th><td>" +
        App.escapeHtml(o.display != null ? o.display : (o.value == null ? "—" : o.value)) +
        "</td></tr>").join("") + "</tbody></table></div>";
    }
    if (payload && payload.caveats && payload.caveats.length) {
      html += '<div class="result-caveats">' + payload.caveats.map(c =>
        "<div>" + App.escapeHtml(c) + "</div>").join("") + "</div>";
    }
    html += "</div>";
    els.editorResult.innerHTML = html;
    requestAnimationFrame(() => els.editorResult.scrollIntoView({ block: "nearest", behavior: "smooth" }));
  }

  async function refresh(selectId) {
    const data = await App.api("/api/system/system-skills");
    S.skills = data.list || [];
    const target = selectId || (S.current && findSkill(S.current.id) ? S.current.id : null);
    if (target && findSkill(target)) selectSkill(target);
    else if (S.current) showEmpty();
    else renderList();
  }

  async function save() {
    if (S.current && S.current.kind === "code") {
      const collected = collectMeta();
      if (collected.error) { showResult({ summary: collected.error }, true); return; }
      try {
        const saved = await App.api("/api/system/system-skills/" + S.current.id, {
          method: "PUT", body: collected.body,
        });
        await refresh(saved.id);
        showResult({ ok: true, summary: "已保存名称、描述、分类、别名与状态，立即生效" }, false);
        App.toast("信息已保存");
      } catch (err) {
        showResult({ errors: err.errors || [], summary: err.message }, true);
      }
      return;
    }
    const collected = collect();
    if (collected.error) { showResult({ summary: collected.error }, true); return; }
    try {
      if (S.current) {
        const saved = await App.api("/api/system/system-skills/" + S.current.id, {
          method: "PUT", body: collected.body,
        });
        await refresh(saved.id);
        showResult({ ok: true, summary: "已保存：v" + (saved.version_no || "—") + "，内容已生效" }, false);
        App.toast("已保存");
      } else {
        const created = await App.api("/api/system/system-skills", {
          method: "POST", body: collected.body,
        });
        await refresh(created.id);
        showResult({ ok: true, summary: "内置技能已创建：v" + (created.version_no || 1) + "，已立即生效" }, false);
        App.toast("内置技能已创建");
      }
    } catch (err) {
      showResult({ errors: err.errors || [], summary: err.message }, true);
    }
  }

  async function validateContent() {
    if (S.readOnly || (S.current && S.current.kind === "code")) return;
    const kind = currentKind();
    const parsed = collectDefinition(kind);
    if (parsed.error) { showResult({ summary: parsed.error }, true); return; }
    const data = await App.api("/api/system/system-skills/validate", {
      method: "POST", body: { kind: kind, definition: parsed.value },
    });
    showResult(data, !data.ok);
  }

  async function runTest() {
    if (!S.current) { showResult({ summary: "请先保存技能后再试运行" }, true); return; }
    let args = {};
    if (S.current.kind !== "prompt") {
      const parsed = parseJsonField(els.fTestArgs.value, "试运行参数");
      if (parsed.error) { showResult({ summary: parsed.error }, true); return; }
      args = parsed.value;
    }
    const result = await App.api("/api/system/system-skills/" + S.current.id + "/test", {
      method: "POST", body: { args },
    });
    await refresh(S.current.id);
    showResult(result, !result.ok);
  }

  async function loadRuns() {
    if (!S.current) return;
    const data = await App.api("/api/system/system-skills/" + S.current.id + "/runs?limit=20");
    els.runPanel.hidden = false;
    const rows = data.list || [];
    els.runList.innerHTML = rows.length ? rows.map(r =>
      '<div class="run-row">' +
      '<div class="muted">' + App.escapeHtml((r.created_at || "").replace("T", " ").slice(0, 16)) + "</div>" +
      '<div class="run-status ' + App.escapeHtml(r.status) + '">' +
        App.escapeHtml(RUN_STATUS[r.status] || r.status) + '</div>' +
      '<div class="run-detail">' + App.escapeHtml(TRIGGER_LABEL[r.trigger] || r.trigger || "") +
        " · v" + App.escapeHtml(String(r.version_no || "—")) +
        (r.error_message ? " · " + App.escapeHtml(r.error_message) : "") +
        ' <span class="muted">' + App.escapeHtml(JSON.stringify(r.args || {})) + "</span></div>" +
      '<div class="muted">' + (r.duration_ms || 0) + " ms</div></div>"
    ).join("") : '<div class="run-row"><div class="muted">暂无运行记录；试运行后可在这里查看</div></div>';
  }

  async function deleteSkill() {
    if (!S.current || !S.current.can_delete) return;
    const ok = await App.confirmDialog({
      title: "删除内置技能",
      message: "删除「" + S.current.name + "」及其全部版本和运行记录，不可恢复。",
    });
    if (!ok) return;
    try {
      await App.api("/api/system/system-skills/" + S.current.id, { method: "DELETE" });
      S.current = null;
      await refresh();
      showEmpty();
      App.toast("内置技能已删除");
    } catch (err) {
      showResult({ summary: err.message }, true);
    }
  }

  function bind() {
    els.btnNewSkill.addEventListener("click", newSkill);
    els.btnEmptyNew.addEventListener("click", newSkill);
    els.btnSave.addEventListener("click", () => save().catch(err => showResult({ summary: err.message }, true)));
    els.btnValidate.addEventListener("click", () => validateContent().catch(err =>
      showResult({ summary: err.message }, true)));
    els.btnTest.addEventListener("click", () => runTest().catch(err =>
      showResult({ summary: err.message }, true)));
    els.btnRuns.addEventListener("click", () => loadRuns().catch(err =>
      showResult({ summary: err.message }, true)));
    els.btnDelete.addEventListener("click", () => deleteSkill().catch(err =>
      showResult({ summary: err.message }, true)));
    els.btnCloseRuns.addEventListener("click", () => { els.runPanel.hidden = true; });
    document.querySelectorAll('input[name="newKind"]').forEach(radio => {
      radio.addEventListener("change", syncNewKind);
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    initEls();
    bind();
    renderList();
    const editable = S.skills.find(item => item.kind === "prompt") ||
      S.skills.find(item => item.kind === "declarative") ||
      S.skills[0];
    if (editable) selectSkill(editable.id);
    else showEmpty();
  });
})();
