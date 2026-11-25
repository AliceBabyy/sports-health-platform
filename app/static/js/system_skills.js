/* 系统内置技能管理：平台技能列表 + 声明式定义编辑 + 启停/删除/校验/试运行/运行记录 */
(function () {
  "use strict";

  const S = {
    skills: Array.isArray(window.INIT_SYSTEM_SKILLS) ? window.INIT_SYSTEM_SKILLS.slice() : [],
    current: null,
    readOnly: false,
  };

  const KIND_LABEL = { code: "代码实现", declarative: "声明式" };
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
    ["codeList", "declarativeList", "codeCount", "declarativeCount", "editorEmpty",
      "skillForm", "editorKicker", "editorName", "editorSlash", "editorBadges",
      "fName", "fKey", "fAlias", "fCategory", "fStatus", "fDescription",
      "fDefinition", "definitionNote", "definitionHint", "codeNote", "fTestArgs",
      "editorResult", "runPanel", "runList", "btnNewSkill", "btnEmptyNew",
      "workActions", "btnValidate", "btnTest", "btnRuns", "btnDelete", "btnSave",
      "btnCloseRuns", "versionHint"].forEach(id => { els[id] = $(id); });
  }

  function findSkill(id) {
    return S.skills.find(item => item.id === Number(id)) || null;
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
    const declarative = S.skills.filter(item => item.kind === "declarative");
    els.codeCount.textContent = String(code.length);
    els.declarativeCount.textContent = String(declarative.length);
    els.codeList.innerHTML = code.length
      ? code.map(itemHtml).join("")
      : '<div class="si-empty">暂无代码技能</div>';
    els.declarativeList.innerHTML = declarative.length
      ? declarative.map(itemHtml).join("")
      : '<div class="si-empty">暂无声明式技能</div>';
    document.querySelectorAll(".system-skills-page .skill-item").forEach(btn => {
      btn.addEventListener("click", () => selectSkill(Number(btn.dataset.id)));
    });
  }

  function setReadOnly(readOnly) {
    S.readOnly = readOnly;
    ["fName", "fKey", "fAlias", "fCategory", "fDescription", "fDefinition"].forEach(id => {
      els[id].disabled = readOnly;
    });
    els.fStatus.disabled = false;
    els.btnValidate.hidden = readOnly;
    els.btnDelete.hidden = readOnly || !(S.current && S.current.can_delete);
    els.btnSave.textContent = readOnly ? "保存状态" : "保存并生效";
    els.codeNote.hidden = !readOnly;
    els.definitionHint.hidden = readOnly;
    els.definitionNote.textContent = readOnly ? "只读" : "声明式";
    els.fDefinition.classList.toggle("is-readonly", readOnly);
    if (readOnly) {
      els.codeNote.textContent = "代码技能由平台代码注册，定义不可在页面编辑；"
        + "可停用或重新启用，停用后立即从系统图中移除。";
    }
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
    els.fDefinition.value = JSON.stringify(skill.definition || {}, null, 2);
    els.fTestArgs.value = "{}";
    els.btnRuns.hidden = false;
    els.versionHint.textContent = skill.kind === "code"
      ? "代码技能由代码实现，定义不可编辑；状态保存后立即生效"
      : "当前 " + (skill.version_no ? "v" + skill.version_no : "未发布") +
        "；定义变更生成新版本并立即生效";
    setReadOnly(skill.kind === "code");
    clearResult();
  }

  function showEmpty() {
    S.current = null;
    els.skillForm.hidden = true;
    els.workActions.hidden = true;
    els.runPanel.hidden = true;
    els.editorEmpty.hidden = false;
    els.editorName.textContent = "选择或新建技能";
    els.editorKicker.textContent = "内置技能";
    els.editorSlash.hidden = true;
    els.editorBadges.innerHTML = "";
    els.versionHint.textContent = "";
    els.editorResult.innerHTML = "";
    renderList();
  }

  function newSkill() {
    S.current = null;
    renderList();
    els.editorEmpty.hidden = true;
    els.skillForm.hidden = false;
    els.workActions.hidden = false;
    els.runPanel.hidden = true;
    els.editorSlash.hidden = false;
    els.editorName.textContent = "新建内置技能";
    els.editorSlash.textContent = "/技能名";
    els.editorKicker.textContent = "内置技能 · 新建";
    els.editorBadges.innerHTML = badge("声明式") + badge("平台内置") + badge("v1");
    els.fName.value = "";
    els.fKey.value = "builtin_" + Date.now().toString(36);
    els.fKey.readOnly = false;
    els.fAlias.value = "";
    els.fCategory.value = "custom";
    els.fStatus.value = "active";
    els.fDescription.value = "";
    els.fDefinition.value = "";
    els.fTestArgs.value = "{}";
    els.btnRuns.hidden = true;
    els.versionHint.textContent = "保存后立即发布 v1；技能键创建后不可修改";
    setReadOnly(false);
    els.btnDelete.hidden = true;
    els.btnTest.hidden = false;
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

  function collect() {
    const name = els.fName.value.trim();
    const key = els.fKey.value.trim();
    const alias = els.fAlias.value.trim();
    if (!name) return { error: "技能名不能为空" };
    if (!key) return { error: "技能键不能为空" };
    const parsed = parseJsonField(els.fDefinition.value, "技能定义");
    if (parsed.error) return parsed;
    return {
      body: {
        key: key,
        name: name,
        slash_alias: alias || null,
        description: els.fDescription.value.trim(),
        category: els.fCategory.value,
        kind: "declarative",
        definition: parsed.value,
        status: els.fStatus.value,
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
      const status = els.fStatus.value;
      await App.api("/api/system/system-skills/" + S.current.id + "/status", {
        method: "POST", body: { status },
      });
      await refresh(S.current.id);
      showResult({ ok: true, summary: status === "active" ? "已启用，立即生效" : "已停用，立即从系统图移除" }, false);
      App.toast("状态已保存");
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
        showResult({ ok: true, summary: "已保存：v" + (saved.version_no || "—") + "，定义已生效" }, false);
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

  async function validateDefinition() {
    if (S.readOnly) return;
    const parsed = parseJsonField(els.fDefinition.value, "技能定义");
    if (parsed.error) { showResult({ summary: parsed.error }, true); return; }
    const data = await App.api("/api/system/system-skills/validate", {
      method: "POST", body: { kind: "declarative", definition: parsed.value },
    });
    showResult(data, !data.ok);
  }

  async function runTest() {
    if (!S.current) { showResult({ summary: "请先保存技能后再试运行" }, true); return; }
    const parsed = parseJsonField(els.fTestArgs.value, "试运行参数");
    if (parsed.error) { showResult({ summary: parsed.error }, true); return; }
    const result = await App.api("/api/system/system-skills/" + S.current.id + "/test", {
      method: "POST", body: { args: parsed.value },
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
    els.btnValidate.addEventListener("click", () => validateDefinition().catch(err =>
      showResult({ summary: err.message }, true)));
    els.btnTest.addEventListener("click", () => runTest().catch(err =>
      showResult({ summary: err.message }, true)));
    els.btnRuns.addEventListener("click", () => loadRuns().catch(err =>
      showResult({ summary: err.message }, true)));
    els.btnDelete.addEventListener("click", () => deleteSkill().catch(err =>
      showResult({ summary: err.message }, true)));
    els.btnCloseRuns.addEventListener("click", () => { els.runPanel.hidden = true; });
  }

  document.addEventListener("DOMContentLoaded", () => {
    initEls();
    bind();
    renderList();
    if (S.skills.length) selectSkill(S.skills[0].id);
  });
})();
