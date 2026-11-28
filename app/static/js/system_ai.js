/* 系统 AI 配置：来源 / 模型 / 功能路由三栏工作台，保存即生效 */
(function () {
  "use strict";

  const App = window.App;
  const $ = id => document.getElementById(id);
  const API = "/api/system/ai-config";
  const CAP_LABEL = { text: "文本", vision: "图片", tools: "工具", structured_output: "结构化" };

  const S = {
    config: window.INIT_AI_CONFIG || { providers: [], models: [], routes: [], features: [] },
    kind: null,      // provider / model / route
    id: null,
    feature: null,
  };

  const els = {};
  [
    "providerList", "modelList", "routeList", "providerCount", "modelCount", "routeCount",
    "snapshotStatus", "editorKicker", "editorName", "editorBadges", "editorEmpty",
    "providerForm", "modelForm", "routeForm", "editorResult", "workActions", "editorHint",
    "btnNewProvider", "btnNewModel", "btnApply", "btnTest", "btnDelete", "btnSave",
    "pKey", "pName", "pBaseUrl", "pKeyEnv", "pApiKey", "pTimeout", "pRetries", "pHeaders",
    "pStatus", "pRemark", "pKeyState", "pClearKey",
    "mAlias", "mProvider", "mUpstream", "mMethod", "mText", "mVision", "mTools",
    "mStructured", "mTimeout", "mSort", "mStatus", "mSelectable", "mExtraBody",
    "mParams", "mRemark",
    "rHead", "rDesc", "rModel", "rTimeout", "rEnabled", "rRequired", "rOverride",
    "rRemark", "routeIssues",
  ].forEach(id => { els[id] = $(id); });

  const providerById = id => S.config.providers.find(p => p.id === Number(id)) || null;
  const modelByAlias = alias => S.config.models.find(m => m.alias === alias) || null;
  const routeByKey = key => S.config.routes.find(r => r.feature_key === key) || null;

  function badge(text, cls) {
    return '<span class="badge ' + (cls || "") + '">' + App.escapeHtml(text) + "</span>";
  }

  function item(kind, key, mark, name, state, meta) {
    const active = S.kind === kind && (kind === "route" ? S.feature === key : S.id === Number(key));
    return '<button class="skill-item' + (active ? " active" : "") + '" data-kind="' + kind +
      '" data-key="' + App.escapeHtml(String(key)) + '" type="button">' +
      '<span class="si-mark' + (kind === "provider" ? " platform" : "") + '">' +
        App.escapeHtml(mark) + "</span>" +
      '<span class="si-text"><span class="si-name"><span class="si-name-text">' +
        App.escapeHtml(name) + '</span><span class="si-state ' + state.cls + '">' +
        App.escapeHtml(state.text) + "</span></span>" +
      '<span class="si-meta">' + App.escapeHtml(meta) + "</span></span>" +
      '<span class="si-arrow" aria-hidden="true">&rsaquo;</span></button>';
  }

  function renderRail() {
    const providers = S.config.providers || [];
    const models = S.config.models || [];
    const routes = S.config.routes || [];
    els.providerCount.textContent = String(providers.length);
    els.modelCount.textContent = String(models.length);
    els.routeCount.textContent = String(routes.filter(r => r.enabled).length) + "/" + routes.length;

    els.providerList.innerHTML = providers.length ? providers.map(p => item(
      "provider", p.id, (p.name || p.provider_key || "源").trim().slice(0, 1),
      p.name, {
        text: p.status === "active" ? (p.key_state === "missing" ? "缺密钥" : "启用") : "停用",
        cls: p.status !== "active" ? "disabled" : (p.key_state === "missing" ? "draft" : "published"),
      },
      p.base_url.replace(/^https?:\/\//, "") + " · " + p.model_count + " 模型"
    )).join("") : '<div class="si-empty">暂无来源</div>';

    els.modelList.innerHTML = models.length ? models.map(m => item(
      "model", m.id, (m.alias || "M").slice(0, 1), m.alias, {
        text: m.status === "active" ? (m.routes.length ? "在用" : "空闲") : "停用",
        cls: m.status !== "active" ? "disabled" : (m.routes.length ? "published" : ""),
      },
      (m.provider_key || "无来源") + " · " + (m.capabilities || []).map(c => CAP_LABEL[c] || c).join("/")
    )).join("") : '<div class="si-empty">暂无模型</div>';

    els.routeList.innerHTML = routes.map(r => item(
      "route", r.feature_key, r.label.slice(0, 1), r.label, {
        text: r.enabled ? "已配置" : "回落",
        cls: r.enabled ? "published" : "disabled",
      },
      r.enabled ? (r.model_alias || "未选模型") : "未启用"
    )).join("");

    document.querySelectorAll(".system-ai-page .skill-item").forEach(btn => {
      btn.addEventListener("click", () => selectEntity(btn.dataset.kind, btn.dataset.key));
    });
  }

  function hideForms() {
    els.providerForm.hidden = true;
    els.modelForm.hidden = true;
    els.routeForm.hidden = true;
    els.editorEmpty.hidden = true;
    els.workActions.hidden = true;
    els.editorResult.hidden = true;
  }

  function resetEditor() {
    S.kind = null; S.id = null; S.feature = null;
    hideForms();
    els.editorEmpty.hidden = false;
    els.editorKicker.textContent = "AI 配置";
    els.editorName.textContent = "选择左侧条目";
    els.editorBadges.innerHTML = "";
  }

  function selectEntity(kind, key) {
    hideForms();
    S.kind = kind;
    S.id = kind === "route" ? null : Number(key);
    S.feature = kind === "route" ? key : null;
    if (kind === "provider") renderProvider(providerById(key));
    else if (kind === "model") renderModel(modelByAlias(key));
    else renderRoute(routeByKey(key));
    renderRail();
  }

  function showForm(form, kicker, name, badges, hint) {
    hideForms();
    form.hidden = false;
    els.workActions.hidden = false;
    els.editorKicker.textContent = kicker;
    els.editorName.textContent = name;
    els.editorBadges.innerHTML = badges || "";
    els.editorHint.textContent = hint || "";
    els.btnTest.hidden = S.kind === "route";
    els.btnDelete.hidden = false;
  }

  /* ---------- 来源 ---------- */
  function renderProvider(p) {
    if (!p) return resetEditor();
    els.pKey.value = p.provider_key;
    els.pName.value = p.name;
    els.pBaseUrl.value = p.base_url;
    els.pKeyEnv.value = p.api_key_env;
    els.pApiKey.value = "";
    els.pTimeout.value = p.timeout_seconds;
    els.pRetries.value = p.max_retries;
    els.pHeaders.value = JSON.stringify(p.extra_headers || {}, null, 2);
    els.pStatus.value = p.status;
    els.pRemark.value = p.remark || "";
    els.pClearKey.checked = false;
    const keyText = p.key_state === "db" ? "库内加密保存（" + p.key_preview + "）"
      : p.key_state === "env" ? "来自 .env 变量 " + p.api_key_env + "（" + p.key_preview + "）"
      : p.key_state === "invalid" ? "库内密文无法解密，请重新写入"
      : "未配置：变量 " + p.api_key_env + " 不存在";
    els.pKeyState.textContent = keyText;

    const badges = [];
    badges.push(badge(p.status === "active" ? "启用" : "停用", p.status === "active" ? "ok" : ""));
    badges.push(badge(p.key_state === "missing" ? "缺密钥" : "密钥已配置",
      p.key_state === "missing" ? "bad" : "ok"));
    badges.push(badge(p.model_count + " 个模型"));
    showForm(els.providerForm, "模型来源", p.name, badges.join(""),
      "密钥写库时使用 SECRET_KEY 派生密钥加密；清空输入框表示不改动。");
  }

  function newProvider() {
    S.kind = "provider"; S.id = null; S.feature = null;
    els.pKey.value = "";
    els.pName.value = "";
    els.pBaseUrl.value = "";
    els.pKeyEnv.value = "AI_API_KEY";
    els.pApiKey.value = "";
    els.pTimeout.value = 30;
    els.pRetries.value = 1;
    els.pHeaders.value = "{}";
    els.pStatus.value = "active";
    els.pRemark.value = "";
    els.pClearKey.checked = false;
    els.pKeyState.textContent = "新建来源：密钥可先只填变量名";
    showForm(els.providerForm, "新建来源", "未命名来源", badge("新建"), "保存后自动生成本地 id，并立即进入模型来源下拉。");
    els.btnDelete.hidden = true;
    renderRail();
  }

  function providerPayload() {
    return {
      provider_key: els.pKey.value.trim(),
      name: els.pName.value.trim(),
      base_url: els.pBaseUrl.value.trim(),
      api_key_env: els.pKeyEnv.value.trim() || "AI_API_KEY",
      api_key: els.pApiKey.value.trim() || null,
      clear_api_key: els.pClearKey.checked,
      timeout_seconds: Number(els.pTimeout.value || 30),
      max_retries: Number(els.pRetries.value || 0),
      extra_headers: readJson("pHeaders", "附加请求头"),
      status: els.pStatus.value,
      remark: els.pRemark.value.trim(),
    };
  }

  /* ---------- 模型 ---------- */
  function fillProviderSelect(selectedId) {
    const options = S.config.providers.map(p =>
      '<option value="' + p.id + '"' + (p.id === Number(selectedId) ? " selected" : "") + ">" +
      App.escapeHtml(p.name + "（" + p.provider_key + "）" + (p.status === "active" ? "" : " · 已停用")) +
      "</option>").join("");
    els.mProvider.innerHTML = options || '<option value="">暂无来源</option>';
  }

  function renderModel(m) {
    if (!m) return resetEditor();
    els.mAlias.value = m.alias;
    els.mAlias.disabled = true;
    fillProviderSelect(m.provider_id);
    els.mUpstream.value = m.upstream_name;
    els.mMethod.value = m.structured_method || "json_schema";
    const caps = m.capabilities || [];
    els.mText.checked = caps.includes("text");
    els.mVision.checked = caps.includes("vision");
    els.mTools.checked = caps.includes("tools");
    els.mStructured.checked = caps.includes("structured_output");
    els.mTimeout.value = m.timeout_seconds == null ? "" : m.timeout_seconds;
    els.mSort.value = m.sort_order || 0;
    els.mStatus.value = m.status;
    els.mSelectable.value = m.selectable_for_chat ? "1" : "0";
    els.mExtraBody.value = JSON.stringify(m.extra_body || {}, null, 2);
    els.mParams.value = JSON.stringify(m.params || {}, null, 2);
    els.mRemark.value = m.remark || "";

    const badges = [
      badge(m.status === "active" ? "启用" : "停用", m.status === "active" ? "ok" : ""),
      badge((m.capabilities || []).map(c => CAP_LABEL[c] || c).join(" / ") || "无能力"),
      badge(m.provider_name || "来源缺失", m.provider_status === "active" ? "" : "bad"),
    ];
    if (m.routes && m.routes.length) badges.push(badge("用于 " + m.routes.join("、"), "ok"));
    showForm(els.modelForm, "模型清单", m.alias, badges.join(""),
      "别名是代码、会话与路由唯一认的标识；上游模型名可不同。");
  }

  function newModel() {
    S.kind = "model"; S.id = null; S.feature = null;
    els.mAlias.value = "";
    els.mAlias.disabled = false;
    fillProviderSelect(S.config.providers.find(p => p.status === "active")?.id);
    els.mUpstream.value = "";
    els.mMethod.value = "json_schema";
    els.mText.checked = true;
    els.mVision.checked = false;
    els.mTools.checked = false;
    els.mStructured.checked = true;
    els.mTimeout.value = "";
    els.mSort.value = 0;
    els.mStatus.value = "active";
    els.mSelectable.value = "1";
    els.mExtraBody.value = "{}";
    els.mParams.value = "{}";
    els.mRemark.value = "";
    showForm(els.modelForm, "新建模型", "未命名模型", badge("新建"), "能力必须真实声明，路由保存时会按能力校验。");
    els.btnDelete.hidden = true;
    renderRail();
  }

  function modelPayload() {
    return {
      alias: els.mAlias.value.trim(),
      provider_id: Number(els.mProvider.value || 0),
      upstream_name: els.mUpstream.value.trim(),
      supports_text: els.mText.checked,
      supports_vision: els.mVision.checked,
      supports_tools: els.mTools.checked,
      supports_structured_output: els.mStructured.checked,
      structured_method: els.mMethod.value,
      timeout_seconds: els.mTimeout.value === "" ? null : Number(els.mTimeout.value),
      extra_body: readJson("mExtraBody", "extra_body"),
      params: readJson("mParams", "通用参数"),
      selectable_for_chat: els.mSelectable.value === "1",
      status: els.mStatus.value,
      sort_order: Number(els.mSort.value || 0),
      remark: els.mRemark.value.trim(),
    };
  }

  /* ---------- 功能路由 ---------- */
  function fillRouteModelSelect(selected) {
    const rows = S.config.models.filter(m => m.status === "active" || m.alias === selected);
    els.rModel.innerHTML = rows.map(m =>
      '<option value="' + App.escapeHtml(m.alias) + '"' + (m.alias === selected ? " selected" : "") + ">" +
      App.escapeHtml(m.alias + " · " + (m.provider_key || "") +
        (m.status === "active" ? "" : " · 已停用")) + "</option>").join("") ||
      '<option value="">暂无可用模型</option>';
  }

  function renderRoute(r) {
    if (!r) return resetEditor();
    els.rHead.textContent = r.feature_key;
    els.rDesc.textContent = r.label + " · " + r.desc;
    fillRouteModelSelect(r.model_alias);
    els.rTimeout.value = r.timeout_seconds == null ? "" : r.timeout_seconds;
    els.rEnabled.value = r.enabled ? "1" : "0";
    els.rRequired.textContent = (r.required || []).map(c => CAP_LABEL[c] || c).join("、");
    els.rOverride.value = JSON.stringify(r.params_override || {}, null, 2);
    els.rRemark.value = r.remark || "";

    const issues = r.issues || [];
    els.routeIssues.hidden = issues.length === 0;
    els.routeIssues.className = "route-issues" + (issues.length && r.enabled ? " bad" : "");
    els.routeIssues.innerHTML = issues.map(x => "<span>· " + App.escapeHtml(x) + "</span>").join("");

    showForm(els.routeForm, "功能路由", r.label, badge(r.feature_key, r.enabled ? "ok" : ""),
      "一个功能点只配一个模型，不做主备降级；停用时回落 .env 旧键。");
    els.btnDelete.hidden = !r.id;
  }

  function routePayload() {
    return {
      feature_key: S.feature,
      model_alias: els.rModel.value,
      timeout_seconds: els.rTimeout.value === "" ? null : Number(els.rTimeout.value),
      params_override: readJson("rOverride", "参数覆盖"),
      enabled: els.rEnabled.value === "1",
      remark: els.rRemark.value.trim(),
    };
  }

  /* ---------- 通用 ---------- */
  function readJson(id, label) {
    const raw = (els[id].value || "").trim();
    if (!raw) return {};
    let value;
    try { value = JSON.parse(raw); } catch (e) {
      throw new Error(label + " 不是合法 JSON：" + e.message);
    }
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      throw new Error(label + " 必须是 JSON 对象");
    }
    return value;
  }

  function resultBox(ok, html) {
    els.editorResult.hidden = false;
    els.editorResult.innerHTML = '<div class="result-box ' + (ok ? "ok" : "error") + '">' + html + "</div>";
  }

  async function refresh(selectKind, selectKey) {
    S.config = await App.api(API);
    els.snapshotStatus.textContent = "快照来源：" + (S.config.snapshot?.source === "db" ? "数据库三表" : ".env 回落");
    if (selectKind) selectEntity(selectKind, selectKey);
    else { resetEditor(); renderRail(); }
  }

  async function save() {
    els.btnSave.disabled = true;
    try {
      if (S.kind === "provider") {
        const payload = providerPayload();
        const saved = S.id
          ? await App.api(API + "/providers/" + S.id, { method: "PUT", body: payload })
          : await App.api(API + "/providers", { method: "POST", body: payload });
        App.toast("来源已保存，已生效");
        await refresh("provider", saved.id);
      } else if (S.kind === "model") {
        const payload = modelPayload();
        const saved = S.id
          ? await App.api(API + "/models/" + S.id, { method: "PUT", body: payload })
          : await App.api(API + "/models", { method: "POST", body: payload });
        App.toast("模型已保存，已生效");
        await refresh("model", saved.alias);
      } else if (S.kind === "route") {
        const payload = routePayload();
        await App.api(API + "/routes/" + encodeURIComponent(S.feature), { method: "PUT", body: payload });
        App.toast("路由已保存，已生效");
        await refresh("route", S.feature);
      }
    } catch (err) {
      App.toast(err.message, true);
    } finally {
      els.btnSave.disabled = false;
    }
  }

  async function remove() {
    if (!S.kind || (S.kind !== "route" && !S.id)) return;
    const name = S.kind === "provider" ? (providerById(S.id)?.name || "")
      : S.kind === "model" ? (S.id ? els.mAlias.value : "")
      : (routeByKey(S.feature)?.label || "");
    const ok = await App.confirmDialog({
      title: "删除" + (S.kind === "provider" ? "来源" : S.kind === "model" ? "模型" : "路由"),
      message: "确定删除「" + name + "」？被模型或路由引用时会拒绝删除。",
      confirmText: "删除",
    });
    if (!ok) return;
    try {
      if (S.kind === "provider") await App.api(API + "/providers/" + S.id, { method: "DELETE" });
      else if (S.kind === "model") await App.api(API + "/models/" + S.id, { method: "DELETE" });
      else await App.api(API + "/routes/" + encodeURIComponent(S.feature), { method: "DELETE" });
      App.toast("已删除");
      await refresh();
    } catch (err) {
      App.toast(err.message, true);
    }
  }

  async function testConnection() {
    if (S.kind !== "provider" && S.kind !== "model") return;
    els.btnTest.disabled = true;
    resultBox(true, "正在发起一次最小对话…");
    try {
      const payload = S.kind === "provider"
        ? await App.api(API + "/providers/" + S.id + "/test", { method: "POST", body: {} })
        : await App.api(API + "/models/" + S.id + "/test", { method: "POST", body: {} });
      if (!payload.ok) {
        resultBox(false, App.escapeHtml(payload.error || "连接失败"));
        return;
      }
      resultBox(true, "连接成功 · " + payload.latency_ms + "ms · " +
        App.escapeHtml(payload.model || "") + " 回复：" + App.escapeHtml(payload.reply || "（空）"));
    } catch (err) {
      resultBox(false, App.escapeHtml(err.message));
    } finally {
      els.btnTest.disabled = false;
    }
  }

  async function applyConfig() {
    els.btnApply.disabled = true;
    try {
      const result = await App.api(API + "/apply", { method: "POST" });
      App.toast("配置已应用：来源 " + result.providers + " · 模型 " + result.models + " · 启用路由 " + result.routes);
      els.snapshotStatus.textContent = "快照来源：" + (result.source === "db" ? "数据库三表" : ".env 回落");
    } catch (err) {
      App.toast(err.message, true);
    } finally {
      els.btnApply.disabled = false;
    }
  }

  function bind() {
    els.btnNewProvider.addEventListener("click", newProvider);
    els.btnNewModel.addEventListener("click", newModel);
    els.btnSave.addEventListener("click", save);
    els.btnDelete.addEventListener("click", remove);
    els.btnTest.addEventListener("click", testConnection);
    els.btnApply.addEventListener("click", applyConfig);
  }

  bind();
  els.snapshotStatus.textContent = "快照来源：" +
    (S.config.snapshot?.source === "db" ? "数据库三表" : ".env 回落");
  renderRail();
})();
