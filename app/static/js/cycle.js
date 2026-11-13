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

  const state = {
    cal: window.INIT_CAL,
    selected: window.TODAY_STR,
    periods: [],
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
    const info = window.PHASE_INFO[day.phase_key] || {};
    const ov = state.cal.overview;
    const hasPhase = !!day.phase_key;

    const painHtml = PAIN_BUTTONS.map(function (b) {
      const active = day.pain_recorded && b.level === day.pain_level;
      return '<button type="button" class="pain-btn ' + (active ? 'active' : '') + '" aria-pressed="' + active + '" data-level="' + b.level + '">' + b.label + '</button>';
    }).join('');

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
        ? '<div class="dd-block"><div class="dd-title">激素水平</div><div class="dd-text">' + App.escapeHtml(info.hormone || '—') + '</div></div>' +
          '<div class="dd-block"><div class="dd-title">运动建议</div><div class="dd-text">' + App.escapeHtml(info.advice || '—') + '</div></div>'
        : '<div class="dd-block"><div class="dd-text muted">该日期暂无周期推算</div></div>') +
      sourceNote +
      '<div class="dd-block"><div class="dd-title">疼痛程度' + (day.pain_recorded ? '' : ' · 未记录') + '</div><div class="pain-group">' + painHtml + '</div></div>' +
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
  }
  function loadPeriods() {
    const ov = state.cal.overview;
    App.api('/api/cycle/periods').then(function (data) {
      state.periods = data.list;
      document.getElementById('periodList').innerHTML = data.list.length ? data.list.map(function (r) {
        const periodDays = r.period_length || ov.reference_period_length;
        const cycleDays = r.cycle_length || ov.reference_cycle_length;
        return '<div class="period-row"><div><strong class="num">' + r.start_date + '</strong>' +
          '<span class="period-end">' + (r.end_date ? '至 ' + r.end_date : '结束日未填') + '</span>' +
          '<div class="period-meta">经期 ' + periodDays + ' 天 · 周期 ' + cycleDays + ' 天</div></div>' +
          '<div class="period-actions"><button class="btn btn-sm" data-edit="' + r.id + '">编辑</button>' +
          '<button class="btn btn-sm btn-danger" data-delete="' + r.id + '">删除</button></div></div>';
      }).join('') : '<div class="period-empty">暂无记录</div>';
    }).catch(err => App.toast(err.message, true));
  }
  document.getElementById('periodList').addEventListener('click', function (e) {
    const edit = e.target.closest('[data-edit]');
    const remove = e.target.closest('[data-delete]');
    if (edit) {
      const r = state.periods.find(row => row.id === Number(edit.dataset.edit));
      if (!r) return;
      const form = document.getElementById('formEditPeriod');
      form.elements.record_id.value = r.id;
      form.elements.start_date.value = r.start_date;
      form.elements.end_date.value = r.end_date || '';
      App.openModal('modalEditPeriod');
    }
    if (remove) {
      if (!window.confirm('删除这条月经记录？')) return;
      App.api('/api/cycle/periods/' + remove.dataset.delete, { method: 'DELETE' })
        .then(function () { App.toast('记录已删除'); refreshData(); })
        .catch(err => App.toast(err.message, true));
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

  /* ---------- 初始化 ---------- */
  renderCalendar();
  renderDetail();
  loadPeriods();
})();
