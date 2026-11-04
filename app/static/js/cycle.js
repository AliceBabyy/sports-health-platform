/* 生理周期页：月历（MC-01）、七阶段/运动等级展示、疼痛记录（MC-03）、记录月经（MC-02） */
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
    document.getElementById('calSub').textContent = ov.has_records ? '预计下次月经 ' + ov.next_period : '尚无月经记录';

    let html = '';
    for (let i = 0; i < offset; i++) html += '<div class="cal-day cal-empty" aria-hidden="true"></div>';
    cal.days.forEach(function (d) {
      const dd = dateOf(d.date);
      const isToday = d.date === window.TODAY_STR;
      const isSel = d.date === state.selected;
      const phaseTxt = d.phase_label ? d.phase_label : '—';
      const sportTxt = d.sport_label ? d.sport_label : '—';
      html += '<button type="button" class="cal-day' + (isSel ? ' selected' : '') + (isToday ? ' today-cell' : '') +
        (d.phase_key ? ' phase-' + d.phase_key : '') + (d.sport_level ? ' sport-' + d.sport_level : '') + '" data-date="' + d.date + '" aria-label="' + d.date + ' ' + App.escapeHtml(phaseTxt) + '" aria-pressed="' + isSel + '">' +
        '<div class="cd-num num">' + dd.getDate() + '</div>' +
        '<div class="cd-phase">' + App.escapeHtml(PHASE_SHORT[d.phase_key] || phaseTxt) + '</div>' +
        '<div class="cd-sport">' + App.escapeHtml(sportTxt) + '</div>' +
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
    const progressNum = ov.cycle_day_today, progressTotal = ov.cycle_length;
    const pct = Math.round(progressNum / progressTotal * 100);

    const hasPhase = !!day.phase_key;
    const painHtml = PAIN_BUTTONS.map(function (b) {
      const active = day.pain_recorded && b.level === day.pain_level;
      return '<button type="button" class="pain-btn ' + (active ? 'active' : '') + '" aria-pressed="' + active + '" data-level="' + b.level + '">' + b.label + '</button>';
    }).join('');

    document.getElementById('dayDetail').innerHTML =
      '<div class="dd-head"><span class="dd-date num">' + dd.getFullYear() + '.' + String(dd.getMonth() + 1).padStart(2, '0') + '.' + String(dd.getDate()).padStart(2, '0') + '</span>' +
      (hasPhase ? '<span class="tag phase-' + day.phase_key + '">' + App.escapeHtml(day.phase_label) + '</span>' +
        '<span class="tag tag-' + day.sport_level + '">' + App.escapeHtml(day.sport_label) + '</span>'
        : '<span class="tag tag-gray no-dot">未推算</span>') + '</div>' +
      '<div class="dd-meta">' + WEEKDAY[dd.getDay()] + (hasPhase ? ' · 周期第 ' + day.cycle_day + ' 天' : '') + (day.is_recorded_start ? ' · 已记录' : '') + '</div>' +
      (hasPhase
        ? '<div class="dd-block"><div class="dd-title">激素水平</div><div class="dd-text">' + App.escapeHtml(info.hormone || '—') + '</div></div>' +
          '<div class="dd-block"><div class="dd-title">运动建议</div><div class="dd-text">' + App.escapeHtml(info.advice || '—') + '</div></div>'
        : '<div class="dd-block"><div class="dd-text muted">该日期暂无周期推算</div></div>') +
      '<div class="dd-block"><div class="dd-title">疼痛程度' + (day.pain_recorded ? '' : ' · 未记录') + '</div><div class="pain-group">' + painHtml + '</div></div>' +
      '<div class="dd-block"><div class="dd-title">周期概览</div>' +
      '<div class="ov-grid">' +
      '<div class="ov-item"><div class="k">周期长度</div><div class="v num">' + ov.cycle_length + ' 天</div></div>' +
      '<div class="ov-item"><div class="k">经期长度</div><div class="v num">' + ov.period_length + ' 天</div></div>' +
      '<div class="ov-item"><div class="k">排卵日</div><div class="v num">' + ov.ovulation_date + '</div></div>' +
      '<div class="ov-item"><div class="k">下次月经</div><div class="v num">' + ov.next_period + '</div></div>' +
      '</div>' +
      '<div class="ov-item progress-item"><div class="k">今日周期进度</div>' +
      '<div class="v num">' + progressNum + ' / ' + progressTotal + '</div>' +
      '<div class="progress-track"><div class="progress-fill" style="width:' + pct + '%"></div></div></div></div>';
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

  /* 记录月经弹窗 */
  document.getElementById('btnRecordPeriod').addEventListener('click', function () {
    const form = document.getElementById('formPeriod');
    form.reset();
    form.elements.start_date.value = window.TODAY_STR;
    form.elements.period_length.value = state.cal.overview.period_length;
    form.elements.cycle_length.value = state.cal.overview.cycle_length;
    updateTip();
    App.openModal('modalPeriod');
  });
  function updateTip() {
    const form = document.getElementById('formPeriod');
    const start = form.elements.start_date.value;
    const cycle = parseInt(form.elements.cycle_length.value, 10) || 28;
    if (start) {
      const d = dateOf(start);
      d.setDate(d.getDate() + cycle);
      document.getElementById('nextPeriodTip').textContent = '下次月经预计 ' + d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
    } else {
      document.getElementById('nextPeriodTip').textContent = '下次月经预计：—';
    }
  }
  document.getElementById('formPeriod').addEventListener('input', updateTip);
  document.getElementById('formPeriod').addEventListener('submit', function (e) {
    e.preventDefault();
    const form = e.target;
    App.api('/api/cycle/periods', {
      method: 'POST',
      body: {
        start_date: form.elements.start_date.value,
        end_date: form.elements.end_date.value || null,
        cycle_length: parseInt(form.elements.cycle_length.value, 10),
        period_length: parseInt(form.elements.period_length.value, 10),
      }
    }).then(function () {
      App.closeModal('modalPeriod');
      App.toast('已记录，阶段将自动重算');
      refreshData();
    }).catch(err => App.toast(err.message, true));
  });

  function refreshData() {
    loadMonth(monthStr(state.cal.year, state.cal.month));
    loadPeriods();
  }
  function loadPeriods() {
    App.api('/api/cycle/periods').then(function (data) {
      state.periods = data.list;
      document.getElementById('periodList').innerHTML = data.list.length ? data.list.map(function (r) {
        return '<div class="period-row"><div><strong class="num">' + r.start_date + '</strong>' +
          '<span class="period-end">' + (r.end_date ? '至 ' + r.end_date : '结束日未填') + '</span></div>' +
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
