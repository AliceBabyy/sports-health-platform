/* 生理周期页：分段推算月历、三态经期、七阶段/运动等级、疼痛记录、记录月经、周期参数 */
(function () {
  const App = window.App;
  const WEEKDAY = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
  const PAIN_BUTTONS = [
    { label: '无', level: 0 }, { label: '轻度', level: 1 },
    { label: '中度', level: 2 }, { label: '重度', level: 3 },
  ];
  const PHASE_SHORT = {
    menstrual: '经期', follicular_pre: '卵泡', ovulation_day: '排卵',
    follicular_post: '排后', luteal_early: '黄前', luteal_mid: '黄中', luteal_late: '黄后',
  };
  const STATUS_SHORT = { high: '旺盛', good: '良好', average: '一般', rest: '休息' };
  const PAIN_LABELS = { 0: '无', 1: '轻度', 2: '中度', 3: '重度' };
  const PAGE_SIZE = 10;

  const state = {
    cal: window.INIT_CAL,
    selected: window.TODAY_STR,
    periods: [],
    kind: 'period',
    recordsPage: 1,
    logRes: null,
    logPage: 1,
  };

  function monthStr(year, month) { return year + '-' + String(month).padStart(2, '0'); }
  function dateOf(s) { const p = s.split('-'); return new Date(+p[0], +p[1] - 1, +p[2]); }
  function addMonths(s, n) { const d = dateOf(s + '-01'); d.setMonth(d.getMonth() + n); return monthStr(d.getFullYear(), d.getMonth() + 1); }

  /* ---------- 月历渲染 ---------- */
  function renderCalendar() {
    const cal = state.cal;
    const ov = cal.overview;
    const firstDay = dateOf(cal.year + '-' + String(cal.month).padStart(2, '0') + '-01');
    const offset = (firstDay.getDay() + 6) % 7; // 周一开头
    document.getElementById('calTitle').textContent = cal.year + ' 年 ' + cal.month + ' 月';

    let sub = '尚未记录月经';
    if (ov.has_records) {
      if (!ov.next_period) {
        sub = '—';
      } else {
        sub = '预计下次月经 ' + ov.next_period;
        if (ov.overdue_days) sub += '（已逾期 ' + ov.overdue_days + ' 天，建议补录）';
      }
    }
    document.getElementById('calSub').textContent = sub;

    let html = '';
    for (let i = 0; i < offset; i++) html += '<div class="cal-day cal-empty" aria-hidden="true"></div>';
    cal.days.forEach(function (d) {
      const dd = dateOf(d.date);
      const isToday = d.date === window.TODAY_STR;
      const isSel = d.date === state.selected;
      const phaseTxt = d.phase_label ? d.phase_label : '—';
      // 三态经期优先：经期 / 推算经期 / 预测经期；其余显示阶段简称
      const phaseShort = d.period_state ? (d.period_label || phaseTxt) : (PHASE_SHORT[d.phase_key] || phaseTxt);
      const sportTxt = d.sport_label ? d.sport_label : '—';
      html += '<button type="button" class="cal-day' + (isSel ? ' selected' : '') + (isToday ? ' today-cell' : '') +
        (d.phase_key ? ' phase-' + d.phase_key : '') + (d.sport_level ? ' sport-' + d.sport_level : '') +
        (d.period_state ? ' period-' + d.period_state : '') + '" data-date="' + d.date + '" aria-label="' + d.date + ' ' + App.escapeHtml(d.period_label || phaseTxt) + '" aria-pressed="' + isSel + '">' +
        '<div class="cd-num num">' + dd.getDate() + '</div>' +
        '<div class="cd-phase">' + App.escapeHtml(phaseShort) + '</div>' +
        '<div class="cd-sport"><span class="cd-sport-full">' + App.escapeHtml(sportTxt) +
        '</span><span class="cd-sport-short">' + App.escapeHtml(STATUS_SHORT[d.sport_level] || '—') + '</span></div>' +
        (d.is_recorded_start ? '<span class="cd-record" title="已记录月经首日"></span>' : '') + '</button>';
    });
    document.getElementById('calGrid').innerHTML = html;
  }

  /* ---------- 右侧详情 ---------- */
  function renderDetail() {
    const day = state.cal.days.find(d => d.date === state.selected) || state.cal.days[0];
    if (!day) return;
    const dd = dateOf(day.date);
    const ov = state.cal.overview;
    const hasPhase = !!day.phase_key;
    // 疼痛入口只在「经期」开放；推算经期、预测经期与其他阶段均不展示
    const showPain = day.period_state === 'recorded';

    const painHtml = showPain ? PAIN_BUTTONS.map(function (b) {
      const active = day.pain_recorded && b.level === day.pain_level;
      return '<button type="button" class="pain-btn ' + (active ? 'active' : '') + '" aria-pressed="' + active + '" data-level="' + b.level + '">' + b.label + '</button>';
    }).join('') : '';

    let sourceNote = '';
    if (day.phase_source === 'derived') {
      sourceNote = '<div class="dd-block"><div class="dd-text muted">本段无记录，阶段按参考周期推算。</div></div>';
    } else if (day.phase_source === 'predicted') {
      sourceNote = '<div class="dd-block"><div class="dd-text muted">预测阶段，尚无记录。</div></div>';
    }

    document.getElementById('dayDetail').innerHTML =
      '<div class="dd-head"><span class="dd-date num">' + dd.getFullYear() + '.' + String(dd.getMonth() + 1).padStart(2, '0') + '.' + String(dd.getDate()).padStart(2, '0') + '</span>' +
      (hasPhase ? '<span class="tag phase-' + day.phase_key + '">' + App.escapeHtml(day.period_label || day.phase_label) + '</span>' +
        (day.sport_level ? '<span class="tag tag-' + day.sport_level + '">' + App.escapeHtml(day.sport_label) + '</span>' : '')
        : '<span class="tag tag-gray no-dot">未推算</span>') + '</div>' +
      '<div class="dd-meta">' + WEEKDAY[dd.getDay()] + (day.cycle_day ? ' · 周期第 ' + day.cycle_day + ' 天' : '') + (day.is_recorded_start ? ' · 已记录' : '') + '</div>' +
      (hasPhase
        ? '<div class="dd-block"><div class="dd-title">激素水平</div><div class="dd-text dd-hormone">' + App.escapeHtml(day.hormone_text || '—') + '</div></div>'
        : '<div class="dd-block"><div class="dd-text muted">该日期暂无周期推算</div></div>') +
      sourceNote +
      (showPain
        ? '<div class="dd-block"><div class="dd-title">疼痛程度' + (day.pain_recorded ? '' : ' · 未记录') + '</div><div class="pain-group">' + painHtml + '</div></div>'
        : '') +
      '<div class="dd-block"><div class="dd-title">周期概览</div>' +
      '<div class="ov-grid">' +
      '<div class="ov-item"><div class="k">参考周期</div><div class="v num">' + ov.reference_cycle_length + ' 天</div></div>' +
      '<div class="ov-item"><div class="k">参考经期</div><div class="v num">' + ov.reference_period_length + ' 天</div></div>' +
      '<div class="ov-item"><div class="k">排卵日</div><div class="v num">' + (ov.ovulation_date || '—') + '</div></div>' +
      '<div class="ov-item"><div class="k">预计下次月经</div><div class="v num">' + (ov.next_period || '—') + '</div></div>' +
      '</div>';
  }

  /* ---------- 事件 ---------- */
  document.getElementById('calGrid').addEventListener('click', function (e) {
    const cell = e.target.closest('.cal-day[data-date]');
    if (!cell) return;
    state.selected = cell.dataset.date;
    renderCalendar();
    renderDetail();
  });

  document.getElementById('btnPrevMonth').addEventListener('click', function () { loadMonth(addMonths(state.cal.year + '-' + String(state.cal.month).padStart(2, '0'), -1)); });
  document.getElementById('btnNextMonth').addEventListener('click', function () { loadMonth(addMonths(state.cal.year + '-' + String(state.cal.month).padStart(2, '0'), 1)); });
  document.getElementById('btnGoToday').addEventListener('click', function () {
    const t = window.TODAY_STR;
    state.selected = t;
    loadMonth(t.slice(0, 7));
  });

  function loadMonth(ym) {
    App.api('/api/cycle/calendar?month=' + ym).then(function (cal) {
      state.cal = cal;
      if (!cal.days.some(d => d.date === state.selected)) state.selected = ym === window.TODAY_STR.slice(0, 7) ? window.TODAY_STR : cal.days[0].date;
      renderCalendar();
      renderDetail();
      renderTodayNote(cal.today ? cal.today.note : null);
    }).catch(e => App.toast(e.message, true));
  }

  /* 疼痛 */
  document.getElementById('dayDetail').addEventListener('click', function (e) {
    const b = e.target.closest('.pain-btn');
    if (!b) return;
    const level = parseInt(b.dataset.level, 10);
    b.disabled = true;
    App.api('/api/cycle/pain/' + state.selected, { method: 'PUT', body: { pain_level: level } })
      .then(function () {
        return App.api('/api/cycle/calendar?month=' + state.selected.slice(0, 7));
      }).then(function (cal) {
        state.cal = cal;
        renderCalendar(); renderDetail();
        if (state.kind === 'log') loadLogs(state.logPage);
        App.toast('疼痛程度已更新');
      }).catch(err => { b.disabled = false; App.toast(err.message, true); });
  });

  /* 记录月经弹窗：只收起止日期，长度由记录自动派生 */
  document.getElementById('btnRecordPeriod').addEventListener('click', function () {
    const form = document.getElementById('formPeriod');
    form.reset();
    form.elements.start_date.value = window.TODAY_STR;
    App.openModal('modalPeriod');
  });
  document.getElementById('formPeriod').addEventListener('submit', function (e) {
    e.preventDefault();
    const form = e.target;
    App.api('/api/cycle/periods', {
      method: 'POST',
      body: {
        start_date: form.elements.start_date.value,
        end_date: form.elements.end_date.value || null,
      }
    }).then(function () {
      App.closeModal('modalPeriod');
      App.toast('已记录，阶段将自动重算');
      refreshData();
    }).catch(err => App.toast(err.message, true));
  });

  /* 周期参数：只写参考值，不改历史推算 */
  document.getElementById('btnCycleSettings').addEventListener('click', function () {
    const form = document.getElementById('formSettings');
    form.elements.cycle_length.value = state.cal.overview.reference_cycle_length;
    form.elements.period_length.value = state.cal.overview.reference_period_length;
    App.openModal('modalSettings');
  });
  document.getElementById('formSettings').addEventListener('submit', function (e) {
    e.preventDefault();
    const form = e.target;
    App.api('/api/cycle/settings', {
      method: 'PUT',
      body: {
        cycle_length: parseInt(form.elements.cycle_length.value, 10),
        period_length: parseInt(form.elements.period_length.value, 10),
      }
    }).then(function () {
      App.closeModal('modalSettings');
      App.toast('周期参数已更新');
      refreshData();
    }).catch(err => App.toast(err.message, true));
  });

  function refreshData() {
    loadMonth(monthStr(state.cal.year, state.cal.month));
    loadPeriods();
    if (state.kind === 'log') loadLogs(state.logPage);
  }

  /* ---------- 全部记录：月经记录 / 周期日志 两段切换 ---------- */
  function loadPeriods() {
    App.api('/api/cycle/periods').then(function (data) {
      state.periods = data.list;
      if (state.kind === 'period') renderPeriodTable();
      else if (state.logRes) renderLogTable();
    }).catch(err => App.toast(err.message, true));
  }

  function loadLogs(page) {
    const p = page || 1;
    App.api('/api/cycle/logs?page=' + p + '&page_size=' + PAGE_SIZE).then(function (res) {
      if (!res.list.length && res.page > 1 && res.total > 0) { loadLogs(res.page - 1); return; }
      state.logRes = res;
      state.logPage = res.page;
      if (state.kind === 'log') renderLogTable();
    }).catch(err => App.toast(err.message, true));
  }

  function renderPeriodTable() {
    const total = state.periods.length;
    const pages = Math.ceil(total / PAGE_SIZE) || 0;
    if (pages && state.recordsPage > pages) state.recordsPage = pages;
    const page = state.recordsPage;
    const rows = state.periods.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

    let html = '<div class="table-wrap"><table class="tbl record-table">' +
      '<colgroup><col style="width:110px"><col style="width:110px"><col style="width:90px"><col style="width:90px"><col style="width:180px"></colgroup>' +
      '<thead><tr><th>开始日期</th><th>结束日期</th><th>经期长度</th><th>周期长度</th><th>操作</th></tr></thead><tbody>';
    if (!rows.length) {
      html += '<tr><td colspan="5"><div class="empty-state">暂无月经记录</div></td></tr>';
    } else {
      html += rows.map(function (r) {
        return '<tr>' +
          '<td class="num">' + App.escapeHtml(r.start_date) + '</td>' +
          '<td class="num">' + (r.end_date ? App.escapeHtml(r.end_date) : '—') + '</td>' +
          '<td class="num">' + (r.period_length ? r.period_length + ' 天' : '—') + '</td>' +
          '<td class="num">' + (r.cycle_length ? r.cycle_length + ' 天' : '—') + '</td>' +
          '<td class="row-actions">' +
          '<button class="btn btn-sm" data-act="view-period" data-id="' + r.id + '">查看</button>' +
          '<button class="btn btn-sm" data-act="edit-period" data-id="' + r.id + '">编辑</button>' +
          '<button class="btn btn-sm btn-danger" data-act="del-period" data-id="' + r.id + '">删除</button>' +
          '</td></tr>';
      }).join('');
    }
    html += '</tbody></table></div>';
    document.getElementById('recordTableWrap').innerHTML = html;
    renderPagination({ page: page, total: total, page_size: PAGE_SIZE, pages: pages });
  }

  function renderLogTable() {
    const res = state.logRes || { list: [], total: 0, page: 1, page_size: PAGE_SIZE, pages: 0 };
    const periodMap = {};
    state.periods.forEach(function (r) { periodMap[r.id] = r; });

    let html = '<div class="table-wrap"><table class="tbl record-table">' +
      '<colgroup><col style="width:110px"><col style="width:90px"><col style="width:130px"><col><col style="width:110px"></colgroup>' +
      '<thead><tr><th>日期</th><th>疼痛</th><th>所属经期</th><th>note</th><th>操作</th></tr></thead><tbody>';
    if (!res.list.length) {
      html += '<tr><td colspan="5"><div class="empty-state">暂无周期日志，可在右侧填写疼痛或今日 note</div></td></tr>';
    } else {
      html += res.list.map(function (r) {
        const rec = r.period_id ? periodMap[r.period_id] : null;
        const pain = r.pain_level == null
          ? '<span class="muted">—</span>'
          : '<span class="log-pain p' + r.pain_level + '">' + PAIN_LABELS[r.pain_level] + '</span>';
        const note = r.note || '—';
        return '<tr>' +
          '<td class="num">' + App.escapeHtml(r.date) + '</td>' +
          '<td>' + pain + '</td>' +
          '<td class="num">' + (rec ? App.escapeHtml(rec.start_date) + ' 起' : '—') + '</td>' +
          '<td class="desc-cell" title="' + App.escapeHtml(note) + '">' + App.escapeHtml(note) + '</td>' +
          '<td class="row-actions"><button class="btn btn-sm" data-act="view-log" data-id="' + r.id + '">查看详情</button></td>' +
          '</tr>';
      }).join('');
    }
    html += '</tbody></table></div>';
    document.getElementById('recordTableWrap').innerHTML = html;
    renderPagination(res);
  }

  function renderPagination(res) {
    const wrap = document.getElementById('recordPagination');
    if (!res.total) { wrap.innerHTML = '<div class="pagination"><span>共 0 条</span></div>'; return; }
    const info = '<span>共 ' + res.total + ' 条 · 每页 ' + res.page_size + ' 条</span>';
    if (res.pages <= 1) { wrap.innerHTML = '<div class="pagination">' + info + '</div>'; return; }
    let html = '<div class="pagination">' + info;
    html += '<button class="btn btn-sm" data-pg="' + (res.page - 1) + '" ' + (res.page <= 1 ? 'disabled' : '') + '>上一页</button>';
    for (let p = 1; p <= res.pages; p++) html += '<button class="btn btn-sm ' + (p === res.page ? 'active' : '') + '" data-pg="' + p + '">' + p + '</button>';
    html += '<button class="btn btn-sm" data-pg="' + (res.page + 1) + '" ' + (res.page >= res.pages ? 'disabled' : '') + '>下一页</button></div>';
    wrap.innerHTML = html;
  }

  document.getElementById('recordSeg').addEventListener('click', function (e) {
    const btn = e.target.closest('button[data-kind]');
    if (!btn || btn.dataset.kind === state.kind) return;
    state.kind = btn.dataset.kind;
    document.querySelectorAll('#recordSeg button').forEach(function (b) { b.classList.toggle('active', b === btn); });
    if (state.kind === 'log') loadLogs(1);
    else renderPeriodTable();
  });

  document.getElementById('recordPagination').addEventListener('click', function (e) {
    const b = e.target.closest('button[data-pg]');
    if (!b || b.disabled) return;
    const page = parseInt(b.dataset.pg, 10);
    if (state.kind === 'period') { state.recordsPage = page; renderPeriodTable(); }
    else loadLogs(page);
  });

  function openPeriodDetail(r) {
    document.getElementById('detailTitle').textContent = '月经记录详情';
    document.getElementById('detailSub').innerHTML =
      '<span class="dl-sub">' + App.escapeHtml(r.start_date) + (r.end_date ? ' 至 ' + App.escapeHtml(r.end_date) : ' · 结束日未填') + '</span>';
    document.getElementById('detailBody').innerHTML =
      '<div class="dl-grid">' +
      '<div class="dl-item"><span class="dl-label">开始日期</span><span class="dl-value num">' + App.escapeHtml(r.start_date) + '</span></div>' +
      '<div class="dl-item"><span class="dl-label">结束日期</span><span class="dl-value num">' + (r.end_date ? App.escapeHtml(r.end_date) : '—') + '</span></div>' +
      '<div class="dl-item"><span class="dl-label">经期长度</span><span class="dl-value num">' + (r.period_length ? r.period_length + ' 天' : '—') + '</span></div>' +
      '<div class="dl-item"><span class="dl-label">周期长度</span><span class="dl-value num">' + (r.cycle_length ? r.cycle_length + ' 天' : '—') + '</span></div>' +
      '</div>';
    App.openModal('modalDetail');
  }

  function openLogDetail(r) {
    const rec = r.period_id ? state.periods.find(function (p) { return p.id === r.period_id; }) : null;
    document.getElementById('detailTitle').textContent = '周期日志详情';
    document.getElementById('detailSub').innerHTML = '<span class="dl-sub">' + App.escapeHtml(r.date) + '</span>';
    document.getElementById('detailBody').innerHTML =
      '<div class="dl-grid">' +
      '<div class="dl-item"><span class="dl-label">日期</span><span class="dl-value num">' + App.escapeHtml(r.date) + '</span></div>' +
      '<div class="dl-item"><span class="dl-label">疼痛</span><span class="dl-value">' + (r.pain_level == null ? '—' : PAIN_LABELS[r.pain_level]) + '</span></div>' +
      '<div class="dl-item"><span class="dl-label">所属经期</span><span class="dl-value num">' + (rec ? App.escapeHtml(rec.start_date) + ' 起' : '—') + '</span></div>' +
      '</div>' +
      '<div class="dl-remark">' + App.escapeHtml(r.note || '—') + '</div>';
    App.openModal('modalDetail');
  }

  document.getElementById('recordTableWrap').addEventListener('click', function (e) {
    const btn = e.target.closest('button[data-act]');
    if (!btn) return;
    const id = Number(btn.dataset.id);

    if (btn.dataset.act === 'view-period') {
      const r = state.periods.find(function (row) { return row.id === id; });
      if (r) openPeriodDetail(r);
      return;
    }
    if (btn.dataset.act === 'edit-period') {
      const r = state.periods.find(function (row) { return row.id === id; });
      if (!r) return;
      const form = document.getElementById('formEditPeriod');
      form.elements.record_id.value = r.id;
      form.elements.start_date.value = r.start_date;
      form.elements.end_date.value = r.end_date || '';
      App.openModal('modalEditPeriod');
      return;
    }
    if (btn.dataset.act === 'del-period') {
      App.confirmDialog({ title: '删除月经记录', message: '删除这条月经记录？删除后阶段将重新推算。' })
        .then(function (ok) {
          if (!ok) return;
          App.api('/api/cycle/periods/' + id, { method: 'DELETE' })
            .then(function () { App.toast('记录已删除'); refreshData(); })
            .catch(err => App.toast(err.message, true));
        });
      return;
    }
    if (btn.dataset.act === 'view-log') {
      const r = state.logRes && state.logRes.list.find(function (row) { return row.id === id; });
      if (r) openLogDetail(r);
    }
  });
  document.getElementById('formEditPeriod').addEventListener('submit', function (e) {
    e.preventDefault();
    const f = e.target;
    App.api('/api/cycle/periods/' + f.elements.record_id.value, { method: 'PUT', body: {
      start_date: f.elements.start_date.value, end_date: f.elements.end_date.value || null,
    } }).then(function () { App.closeModal('modalEditPeriod'); App.toast('记录已更新'); refreshData(); })
      .catch(err => App.toast(err.message, true));
  });

  document.querySelectorAll('[data-close]').forEach(function (el) {
    el.addEventListener('click', function () { App.closeModal(el.dataset.close); });
  });

  /* ---------- 今日 note ---------- */
  const noteInput = document.getElementById('todayNoteInput');
  const noteDateEl = document.getElementById('todayNoteDate');
  let noteDirty = false;

  function renderTodayNote(note, force) {
    noteDateEl.textContent = window.TODAY_STR.replace(/-/g, '.');
    if (force || !noteDirty) {
      noteInput.value = note || '';
      noteDirty = false;
    }
  }

  function saveTodayNote() {
    const btn = document.getElementById('btnSaveTodayNote');
    btn.disabled = true;
    App.api('/api/cycle/note/' + window.TODAY_STR, { method: 'PUT', body: { note: noteInput.value.trim() } })
      .then(function (res) {
        noteInput.value = res.note || '';
        if (state.cal.today) state.cal.today.note = res.note || null;
        noteDirty = false;
        // 重新拉月历：非经期日保存 note 后疼痛与归属被清空，今日运动等级可能随之变化
        loadMonth(state.cal.year + '-' + String(state.cal.month).padStart(2, '0'));
        if (state.kind === 'log') loadLogs(1);
        App.toast('今日 note 已保存');
      })
      .catch(function (err) { App.toast(err.message, true); })
      .finally(function () { btn.disabled = false; });
  }

  noteInput.addEventListener('input', function () { noteDirty = true; });
  noteInput.addEventListener('keydown', function (e) {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      saveTodayNote();
    }
  });
  document.getElementById('btnSaveTodayNote').addEventListener('click', saveTodayNote);

  /* ---------- 初始化 ---------- */
  renderCalendar();
  renderDetail();
  loadPeriods();
  renderTodayNote(state.cal.today ? state.cal.today.note : null, true);
})();
