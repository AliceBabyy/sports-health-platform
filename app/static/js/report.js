/* AI 运动报告页（2026-11-17）：周报/月报单页。
   数据源：GET /api/reports?type=&anchor= → 事实快照 + 已生成叙事；
           POST /api/reports/generate → 生成/复用；DELETE /api/reports/{id} → 软删除；
           GET /api/reports/history?type=&page=&page_size= → 历史列表。 */
(function () {
  const App = window.App;
  const todayStr = App.todayStr() || (window.INIT_REPORT && window.INIT_REPORT.today);
  const qs = new URLSearchParams(location.search);
  const init = window.INIT_REPORT || {};
  const state = {
    type: qs.get('type') === 'monthly' ? 'monthly' : (init.type === 'monthly' ? 'monthly' : 'weekly'),
    anchor: qs.get('anchor') || init.anchor || todayStr,
    data: null,
    busy: false,
    histPage: 1,
    histItems: [],
  };

  function $(id) { return document.getElementById(id); }
  function esc(s) { return App.escapeHtml(s); }
  function pad2(n) { return String(n).padStart(2, '0'); }
  function parseISO(iso) { const p = String(iso).split('-').map(Number); return new Date(p[0], p[1] - 1, p[2]); }
  function isoOf(d) { return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate()); }
  function fmtNum(v) { return v == null ? '—' : String(v); }
  function num(v) { return v == null || v === '' ? '—' : String(v); }
  function durationText(sec) {
    sec = Math.max(0, Math.round(sec || 0));
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    return h ? h + ':' + pad2(m) + ':' + pad2(s) : m + ':' + pad2(s);
  }

  /* 周期锚点：周=所在周周一，月=所在月 1 日 */
  function periodStartOf(anchor, type) {
    const d = parseISO(anchor);
    if (type === 'weekly') {
      const wd = (d.getDay() + 6) % 7;
      d.setDate(d.getDate() - wd);
    } else {
      d.setDate(1);
    }
    return isoOf(d);
  }
  function stepAnchor(anchor, type, step) {
    const start = parseISO(periodStartOf(anchor, type));
    if (type === 'weekly') start.setDate(start.getDate() + 7 * step);
    else start.setMonth(start.getMonth() + step, 1);
    return isoOf(start);
  }

  /* ---------- 概览卡 ---------- */
  function renderCards() {
    const facts = state.data && state.data.facts;
    if (!facts) return;
    $('rpCards').innerHTML = (facts.cards || []).map(function (c) {
      const cls = c.delta_dir === 'up' ? ' up' : '';
      return '<div class="stat-card">' +
        '<div class="label">' + esc(c.label) + '</div>' +
        '<div class="value">' + esc(fmtNum(c.value)) + '<small>' + esc(c.unit || '') + '</small></div>' +
        '<div class="rp-delta' + cls + '">' + esc(c.delta_text || '') + '</div>' +
        '</div>';
    }).join('');
  }

  /* ---------- 周期信息 ---------- */
  function renderPeriod() {
    const p = state.data.period;
    $('rpPeriodLabel').textContent = p.label;
    const stateEl = $('rpPeriodState');
    if (p.partial) {
      stateEl.textContent = '进行中 · 截至 ' + p.as_of;
      stateEl.className = 'rp-status partial';
    } else {
      stateEl.textContent = '已结束';
      stateEl.className = 'rp-status';
    }
    const prev = stepAnchor(state.anchor, state.type, -1);
    const next = stepAnchor(state.anchor, state.type, 1);
    const nav = $('rpPeriodNav');
    const btnPrev = nav.querySelector('[data-step="-1"]');
    const btnNext = nav.querySelector('[data-step="1"]');
    btnPrev.disabled = false;
    btnNext.disabled = next > todayStr;
    btnPrev.title = state.type === 'weekly' ? '上一周' : '上个月';
    btnNext.title = state.type === 'weekly' ? '下一周' : '下个月';
    $('rpTodayBtn').textContent = state.type === 'weekly' ? '回到本周' : '回到本月';
    document.querySelectorAll('#rpTypeSeg button').forEach(function (b) {
      b.classList.toggle('active', b.dataset.type === state.type);
    });
  }

  function syncGenerateBtn() {
    const btn = $('rpGenerateBtn');
    const r = state.data && state.data.report;
    if (state.busy || (r && r.status === 'generating')) {
      btn.disabled = true;
      btn.textContent = '生成中…';
      return;
    }
    btn.disabled = false;
    btn.textContent = (r && (r.status === 'ready' || state.data.status === 'deleted')) ? '重新生成' : '生成报告';
  }

  /* ---------- 叙事 ---------- */
  function evChips(keys) {
    const metrics = state.data.facts.metrics || {};
    const chips = (keys || []).map(function (k) {
      const m = metrics[k];
      return m ? '<span class="rp-chip">' + esc(m.label) + ' ' + esc(m.display) + '</span>' : '';
    }).join('');
    return chips ? '<div class="rp-chips">' + chips + '</div>' : '';
  }

  function renderItems(items, numbered) {
    return (items || []).map(function (it, i) {
      return '<div class="rp-item">' +
        '<div class="rp-item-title">' + (numbered ? '<span class="rp-item-no">' + (i + 1) + '</span>' : '') +
        esc(it.title || '') + '</div>' +
        '<div class="rp-item-detail">' + esc(it.detail || '') + '</div>' +
        evChips(it.evidence) +
        '</div>';
    }).join('');
  }

  function renderHero() {
    const d = state.data;
    const r = d.report;
    const meta = $('rpMeta'), headline = $('rpHeadline'), summary = $('rpSummary');
    const side = $('rpHeroSide'), sections = $('rpSections'), caveats = $('rpCaveats'), empty = $('rpEmpty');
    const note = $('rpCycleNote');
    note.style.display = 'none';
    sections.innerHTML = '';
    caveats.style.display = 'none';
    empty.style.display = 'none';
    side.innerHTML = '';
    headline.textContent = '';
    summary.textContent = '';
    meta.innerHTML = '';

    if (!r) {
      const deleted = d.status === 'deleted';
      headline.textContent = deleted ? '该周期的报告已删除' : '本期还没有生成报告';
      summary.textContent = deleted
        ? '软删除后该周期不会自动重新生成，需要时可以手动生成。'
        : '生成后会得到一份基于事实快照的回顾：先算数字，再让模型解释。';
      meta.innerHTML = '<span>' + esc(d.period.label) + '</span><span class="rp-badge">未生成</span>';
      empty.style.display = 'block';
      empty.innerHTML = '<strong>' + (deleted ? '已删除' : '等待生成') + '</strong>' +
        (deleted
          ? '点击右上「重新生成」可恢复该周期报告。'
          : '本期事实已经算好，点击右上「生成报告」即可。');
      return;
    }

    const periodLabel = esc(r.period_label || d.period.label);
    let badges = '<span>' + periodLabel + '</span>';
    badges += r.mode === 'ai'
      ? '<span class="rp-badge ai">AI 生成</span>'
      : '<span class="rp-badge rule">规则生成</span>';
    if (r.stale) badges += '<span class="rp-badge stale">数据已更新</span>';
    if (r.status === 'failed') badges += '<span class="rp-badge failed">生成失败</span>';
    meta.innerHTML = badges;

    side.innerHTML = (r.generated_at ? '<span class="rp-hero-meta">生成于 ' + esc(r.generated_at.replace('T', ' ')) + '</span>' : '') +
      '<div class="rp-hero-actions">' +
      (r.status === 'ready' ? '<button type="button" class="btn btn-sm" data-action="regenerate">重新生成</button>' : '') +
      '<button type="button" class="btn btn-sm btn-danger" data-del="' + r.id + '">删除</button>' +
      '</div>' +
      (r.model_name ? '<span class="rp-hero-meta">' + esc(r.model_name) + '</span>' : '');

    if (r.status === 'generating') {
      headline.textContent = '正在生成本期报告';
      summary.textContent = '模型正在基于事实快照撰写，完成后刷新即可看到。';
      sections.innerHTML = '<div class="rp-section span-2"><div class="rp-skeleton">正在调用模型，通常需要十几秒…</div></div>';
      return;
    }
    if (r.status === 'failed') {
      headline.textContent = '本期报告生成失败';
      summary.textContent = '事实快照已经保留，可以稍后重试。';
      sections.innerHTML = '<div class="rp-section span-2"><div class="rp-error">' +
        esc((r.error && r.error.message) || '模型服务暂不可用') + '</div>' +
        '<div class="rp-empty" style="padding:12px 0 0"><button type="button" class="btn btn-primary" data-action="retry">重试生成</button></div></div>';
      return;
    }

    const n = r.narrative || {};
    headline.textContent = n.headline || r.headline || '本期报告';
    summary.textContent = n.summary || '';

    if (n.cycle_note) {
      note.style.display = 'block';
      note.innerHTML = '<span class="rp-note-label">周期视角</span>' + esc(n.cycle_note);
    }

    let html = '';
    if ((n.highlights || []).length) {
      html += '<div class="rp-section highlights"><div class="rp-section-title">做得好的地方</div>' +
        renderItems(n.highlights, false) + '</div>';
    }
    if ((n.watchouts || []).length) {
      html += '<div class="rp-section watchouts"><div class="rp-section-title">需要留意</div>' +
        renderItems(n.watchouts, false) + '</div>';
    }
    if ((n.next_actions || []).length) {
      html += '<div class="rp-section actions span-2"><div class="rp-section-title">下阶段建议</div>' +
        renderItems(n.next_actions, true) + '</div>';
    }
    sections.innerHTML = html;

    if ((n.caveats || []).length) {
      caveats.style.display = 'block';
      caveats.innerHTML = '<span>数据说明</span><ul>' + n.caveats.map(function (c) {
        return '<li>' + esc(c) + '</li>';
      }).join('') + '</ul>';
    }
  }

  /* ---------- 依据 ---------- */
  function evRow(k, v) {
    return '<div class="rp-ev-row"><span class="k">' + esc(k) + '</span><span class="v">' + v + '</span></div>';
  }

  function evBlock(title, rows, note) {
    return '<div class="rp-ev"><div class="rp-ev-title">' + esc(title) + '</div>' +
      rows.join('') + (note ? '<div class="rp-ev-note">' + note + '</div>' : '') + '</div>';
  }

  function renderEvidence() {
    const f = state.data.facts;
    if (!f) return;
    const blocks = [];

    const fit = f.sports.fitness;
    const swim = f.sports.swim;
    const dance = f.sports.dance;
    blocks.push(evBlock('运动', [
      evRow('健身', esc(fit.records) + ' 次 · ' + esc(fit.minutes) + ' 分钟' +
        (fit.volume ? ' · 容量 ' + esc(fit.volume) : '') +
        (fit.avg_heart_rate ? ' · 均心率 ' + esc(fit.avg_heart_rate) : '')),
      evRow('游泳', esc(swim.records) + ' 次 · ' + esc(swim.distance_m) + ' 米' +
        (swim.weighted_pace ? ' · 配速 ' + esc(swim.weighted_pace) + '/100m' : '')),
      evRow('舞蹈', esc(dance.records) + ' 次 · ' + esc(dance.minutes) + ' 分钟' +
        (dance.avg_stars != null ? ' · 均分 ' + esc(dance.avg_stars) + ' 星' : '')),
      evRow('计划', esc(f.totals.plans) + ' 条（不计入训练量）'),
    ], esc(f.kcal_note || '')));

    const bodyRows = [];
    [['weight', '体重', 'kg'], ['body_fat', '体脂率', '%'], ['waist', '腰围', 'cm'], ['hip', '臀围', 'cm']].forEach(function (m) {
      const b = f.body[m[0]];
      if (!b) return;
      const latest = b.latest == null ? '—' : b.latest + ' ' + m[2];
      const change = b.change == null ? '' : '（' + (b.change > 0 ? '+' : '') + b.change + '）';
      bodyRows.push(evRow(m[1], esc(latest + change)));
    });
    blocks.push(evBlock('身体', bodyRows.length ? bodyRows : [evRow('实测', '—')],
      '括号内为周期开始前最近一次实测到本期最新实测的变化。'));

    const stateRows = [];
    ['appetite', 'myalgia', 'inflammation', 'mood'].forEach(function (k) {
      const t = f.state.types[k];
      if (!t) return;
      stateRows.push(evRow(t.label, (t.avg == null ? '未评分' : esc(t.avg) + ' 星') + ' · ' + esc(t.days) + ' 天'));
    });
    stateRows.push(evRow('肌肉疼痛≥2', esc(f.state.pain_days) + ' 天'));
    stateRows.push(evRow('情绪≤2', esc(f.state.mood_low_days) + ' 天'));
    blocks.push(evBlock('状态', stateRows));

    if (f.cycle) {
      const cy = f.cycle;
      const groups = Object.keys(cy.phase_groups || {}).map(function (k) { return k + ' ' + cy.phase_groups[k] + ' 天'; }).join(' · ');
      const sources = Object.keys(cy.source_days || {}).map(function (k) { return k + ' ' + cy.source_days[k] + ' 天'; }).join(' · ');
      blocks.push(evBlock('生理周期', [
        evRow('阶段分布', esc(groups || '—')),
        evRow('阶段来源', esc(sources || '—')),
        evRow('周期疼痛≥2', esc(cy.pain_days) + ' 天'),
        evRow('最近周期长度', cy.latest_cycle_length ? esc(cy.latest_cycle_length) + ' 天' : '—'),
      ], '「预测」不是事实，只作安排参考；真实记录与推算分开统计。'));
    } else {
      blocks.push(evBlock('生理周期', [evRow('本期', '无周期数据')], '仅女性账号且存在月经记录时纳入分析。'));
    }

    const c = f.completeness;
    const missing = (c.missing || []).join('、');
    const notes = (f.notes || []).slice(0, 3).map(function (n) {
      return '<li>' + esc(n.date + ' ' + n.sport + '：' + n.text) + '</li>';
    }).join('');
    blocks.push(evBlock('数据完整度', [
      evRow('覆盖', esc(c.recorded_days) + ' / ' + esc(c.days) + ' 天有记录'),
      evRow('缺失', esc(missing || '无')),
    ], (notes ? '<div class="rp-ev-notes">用户备注（原文，仅作素材）：<ul>' + notes + '</ul></div>' : '')));

    $('rpEvidence').innerHTML = blocks.join('');
  }

  function renderAll() {
    renderPeriod();
    renderCards();
    renderHero();
    renderEvidence();
    syncGenerateBtn();
  }

  /* ---------- 数据 ---------- */
  async function load() {
    try {
      state.data = await App.api('/api/reports?type=' + state.type + '&anchor=' + state.anchor);
      renderAll();
      loadHistory(true);
    } catch (e) {
      App.toast(e.message, true);
    }
  }

  async function generate(force) {
    if (state.busy) return;
    state.busy = true;
    syncGenerateBtn();
    try {
      const res = await App.api('/api/reports/generate', {
        method: 'POST',
        body: { type: state.type, anchor: state.anchor, force: !!force },
      });
      state.data = res;
      renderAll();
      loadHistory(true);
      App.toast('报告已生成');
    } catch (e) {
      App.toast(e.message, true);
      await load();
    } finally {
      state.busy = false;
      syncGenerateBtn();
    }
  }

  async function deleteReport(id) {
    const ok = await App.confirmDialog({
      title: '删除报告',
      message: '删除后该周期不会自动重新生成，需要时可手动再生成。',
      confirmText: '删除',
    });
    if (!ok) return;
    try {
      await App.api('/api/reports/' + id, { method: 'DELETE' });
      App.toast('已删除');
      await load();
    } catch (e) {
      App.toast(e.message, true);
    }
  }

  /* ---------- 历史 ---------- */
  const STATUS_META = {
    ready: ['已生成', 'tag-mint'],
    failed: ['失败', 'tag-rest'],
    generating: ['生成中', 'tag-gray'],
  };

  async function loadHistory(reset) {
    if (reset) { state.histPage = 1; state.histItems = []; }
    try {
      const res = await App.api('/api/reports/history?type=' + state.type + '&page=' + state.histPage + '&page_size=8');
      state.histItems = reset ? res.items : state.histItems.concat(res.items);
      renderHistory(res.total);
    } catch (e) { /* 历史失败不阻塞主报告 */ }
  }

  function renderHistory(total) {
    const body = $('rpHistoryBody');
    if (!state.histItems.length) {
      body.innerHTML = '<tr><td colspan="6" class="rp-history-empty">暂无历史报告</td></tr>';
      $('rpHistoryMore').style.display = 'none';
      return;
    }
    body.innerHTML = state.histItems.map(function (it) {
      const st = STATUS_META[it.status] || ['—', 'tag-gray'];
      return '<tr>' +
        '<td>' + esc(it.period_label) + '</td>' +
        '<td>' + esc(it.type_label) + '</td>' +
        '<td><span class="rp-hl">' + esc(it.headline || '—') + '</span></td>' +
        '<td><span class="tag ' + st[1] + ' no-dot">' + st[0] + '</span></td>' +
        '<td>' + esc(it.generated_at ? it.generated_at.replace('T', ' ').slice(0, 16) : '—') + '</td>' +
        '<td><div class="rp-row-actions">' +
        '<button type="button" class="btn btn-sm" data-view-anchor="' + esc(it.period_start) + '" data-view-type="' + esc(it.type) + '">查看</button>' +
        '<button type="button" class="btn btn-sm btn-danger" data-del="' + it.id + '">删除</button>' +
        '</div></td>' +
        '</tr>';
    }).join('');
    $('rpHistoryMore').style.display = total > state.histItems.length ? 'block' : 'none';
  }

  /* ---------- 事件 ---------- */
  function bind() {
    document.querySelectorAll('#rpTypeSeg button').forEach(function (b) {
      b.addEventListener('click', function () {
        if (state.type === b.dataset.type) return;
        state.type = b.dataset.type;
        state.anchor = todayStr;
        load();
      });
    });
    $('rpPeriodNav').querySelectorAll('[data-step]').forEach(function (b) {
      b.addEventListener('click', function () {
        const step = Number(b.dataset.step);
        const next = stepAnchor(state.anchor, state.type, step);
        if (step > 0 && next > todayStr) return;
        state.anchor = next;
        load();
      });
    });
    $('rpTodayBtn').addEventListener('click', function () {
      state.anchor = todayStr;
      load();
    });
    $('rpGenerateBtn').addEventListener('click', function () {
      const r = state.data && state.data.report;
      generate(!!(r && (r.status === 'ready' || state.data.status === 'deleted')));
    });
    $('rpHistoryMoreBtn').addEventListener('click', function () {
      state.histPage += 1;
      loadHistory(false);
    });

    document.addEventListener('click', function (e) {
      const del = e.target.closest('[data-del]');
      if (del) { deleteReport(Number(del.dataset.del)); return; }
      const view = e.target.closest('[data-view-anchor]');
      if (view) {
        state.type = view.dataset.viewType;
        state.anchor = view.dataset.viewAnchor;
        load();
        return;
      }
      const act = e.target.closest('[data-action]');
      if (act) {
        if (act.dataset.action === 'regenerate') generate(true);
        if (act.dataset.action === 'retry') generate(false);
      }
    });
  }

  bind();
  load();
})();
