/* 运动训练/计划 总览页：日/周/月三视图（2026-11）。
   数据源：GET /api/overview?granularity=day|week|month&date=；单日详情 GET /api/overview/day?date=。 */
(function () {
  const App = window.App;
  const todayStr = window.INIT_TODAY || App.todayStr();
  const state = { mode: 'week', anchor: todayStr, charts: {} };

  const SPORT_META = {
    fitness: { label: '健身', cls: 'fit', url: '/training' },
    swim: { label: '游泳', cls: 'swim', url: '/swim' },
    dance: { label: '舞蹈', cls: 'dance', url: '/dance' },
  };
  const WEEKDAY_CN = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];
  const COLORS = { fitness: '#1b2434', swim: '#17b3a6', dance: '#e8558c' };

  function fmtClock(sec) {
    sec = Math.max(0, Math.round(sec || 0));
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    return h ? h + ':' + String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0')
      : m + ':' + String(s).padStart(2, '0');
  }
  function esc(s) { return App.escapeHtml(s); }
  function weekdayOf(iso) {
    const d = new Date(iso + 'T00:00:00');
    return WEEKDAY_CN[d.getDay() === 0 ? 6 : d.getDay() - 1];
  }

  /* ---------- 总览加载 ---------- */
  function load() {
    App.api('/api/overview?granularity=' + state.mode + '&date=' + state.anchor).then(function (res) {
      renderStats(res.stats);
      const views = { day: 'ovDayView', week: 'ovWeekView', month: 'ovMonthView' };
      Object.keys(views).forEach(v => document.getElementById(views[v]).style.display = v === state.mode ? '' : 'none');
      if (state.mode === 'day') { renderDayCards(res); return; }
      if (state.mode === 'week') { renderWeek(res); return; }
      renderMonth(res);
    }).catch(e => App.toast(e.message, true));
  }

  function renderStats(stats) {
    const wrap = document.getElementById('ovStats');
    const per = stats.per_sport;
    wrap.innerHTML =
      '<div class="stat-card"><div class="label">运动次数</div><div class="value num">' + stats.records +
      '<small> 次</small></div><div class="sub">健身 ' + per.fitness.records + ' · 游泳 ' + per.swim.records + ' · 舞蹈 ' + per.dance.records + '</div></div>' +
      '<div class="stat-card"><div class="label">训练计划</div><div class="value num">' + stats.plans +
      '<small> 项</small></div><div class="sub">健身 ' + per.fitness.plans + ' · 游泳 ' + per.swim.plans + ' · 舞蹈 ' + per.dance.plans + '</div></div>' +
      '<div class="stat-card"><div class="label">运动时长</div><div class="value num">' + stats.minutes +
      '<small> 分钟</small></div><div class="sub">健身 ' + per.fitness.minutes + ' · 游泳 ' + per.swim.minutes + ' · 舞蹈 ' + per.dance.minutes + '</div></div>' +
      '<div class="stat-card"><div class="label">消耗估算</div><div class="value num">' + stats.kcal +
      '<small> kcal</small></div><div class="sub">游泳 + 舞蹈 · 健身暂无热量字段</div></div>';
  }

  /* ---------- 日视图：三运动卡片 ---------- */
  function renderDayCards(res) {
    App.api('/api/overview/day?date=' + state.anchor).then(function (detail) {
      const wrap = document.getElementById('ovDayCards');
      wrap.innerHTML = ['fitness', 'swim', 'dance'].map(function (k) {
        const m = SPORT_META[k];
        const c = res.days[0].sports[k];
        const entries = normalizeEntries(k, detail[k]);
        const listHtml = entries.length
          ? entries.slice(0, 3).map(function (e) {
              return '<div class="osc-item" data-open-day="' + state.anchor + '">' +
                '<div class="oi-title">' + esc(e.title) + '</div>' +
                (e.meta ? '<div class="oi-meta">' + esc(e.meta) + '</div>' : '') + '</div>';
            }).join('') + '<div class="osc-foot"><button type="button" class="btn btn-sm" data-open-day="' + state.anchor + '">查看当日详情</button></div>'
          : '<div class="osc-empty">当日无' + m.label + '数据</div>';
        return '<div class="card ov-sport-card"><div class="osc-head">' +
          '<span class="osc-dot ' + m.cls + '"></span><span class="osc-title">' + m.label + '</span>' +
          '<span class="osc-count num">记录 ' + c.records + ' · 计划 ' + c.plans + '</span></div>' +
          '<div class="osc-list">' + listHtml + '</div></div>';
      }).join('');
    }).catch(e => App.toast(e.message, true));
  }

  /* ---------- 周视图：每日条带 + 堆叠柱 ---------- */
  function renderWeek(res) {
    const strip = document.getElementById('ovWeekStrip');
    const todayIdx = res.days.findIndex(d => d.date === todayStr);
    strip.innerHTML = res.days.map(function (d, i) {
      const wd = weekdayOf(d.date);
      const marks = [];
      ['fitness', 'swim', 'dance'].forEach(function (k) {
        const c = d.sports[k];
        if (c.records || c.plans) {
          const m = SPORT_META[k];
          const parts = [];
          if (c.records) parts.push('记' + c.records);
          if (c.plans) parts.push('计' + c.plans);
          marks.push('<span class="ov-chip ' + m.cls + '" data-open-day="' + d.date + '"><span class="oc-dot"></span>' + m.label + ' ' + parts.join(' ') + '</span>');
        }
      });
      return '<div class="ws-day' + (i === todayIdx ? ' is-today' : '') + '">' +
        '<div class="wd-top"><span class="wd-num">' + parseInt(d.date.slice(8), 10) + '</span><span class="wd-week">' + wd + '</span></div>' +
        '<div class="wd-sports">' + (marks.length ? marks.join('') : '<span class="wd-empty">—</span>') + '</div></div>';
    }).join('');
    renderChart('chartOvWeek', 'chartOvWeekFallback', res.chart);
  }

  /* ---------- 月视图：日历 + 每周堆叠柱 ---------- */
  function renderMonth(res) {
    const d0 = new Date(res.date + 'T00:00:00');
    const year = d0.getFullYear(), month = d0.getMonth() + 1;
    const first = new Date(year, month - 1, 1);
    const offset = (first.getDay() + 6) % 7;   // 周一起始
    const lastDay = new Date(year, month, 0).getDate();
    const dayMap = {};
    res.days.forEach(d => { dayMap[d.date] = d; });

    let cells = '';
    for (let i = 0; i < offset; i++) cells += '<div class="ov-cal-cell blank"></div>';
    for (let day = 1; day <= lastDay; day++) {
      const iso = year + '-' + String(month).padStart(2, '0') + '-' + String(day).padStart(2, '0');
      const d = dayMap[iso];
      let marks = '<span class="cd-empty">—</span>';
      if (d) {
        const mk = [];
        ['fitness', 'swim', 'dance'].forEach(function (k) {
          const c = d.sports[k];
          if (c.records || c.plans) {
            const m = SPORT_META[k];
            const parts = [];
            if (c.records) parts.push('记' + c.records);
            if (c.plans) parts.push('计' + c.plans);
            mk.push('<span class="ov-chip ' + m.cls + '">' + m.label + ' ' + parts.join(' ') + '</span>');
          }
        });
        marks = mk.length ? mk.join('') : '<span class="cd-empty">—</span>';
      }
      cells += '<div class="ov-cal-cell' + (iso === todayStr ? ' is-today' : '') + '" data-open-day="' + iso + '">' +
        '<div class="cd-num num">' + day + '</div><div class="cd-marks">' + marks + '</div></div>';
    }

    const grid = document.getElementById('ovCalGrid');
    grid.innerHTML = '<div class="ov-cal"><div class="ov-cal-head">' +
      ['一', '二', '三', '四', '五', '六', '日'].map(w => '<span>' + w + '</span>').join('') + '</div>' +
      '<div class="ov-cal-grid">' + cells + '</div></div>';
    renderChart('chartOvMonth', 'chartOvMonthFallback', res.chart);
  }

  /* ---------- 图表（堆叠柱，周/月共用） ---------- */
  function renderChart(elId, fallbackId, chart) {
    const fallback = document.getElementById(fallbackId);
    if (!chart || !window.echarts) {
      fallback.style.display = 'block';
      if (state.charts[elId]) { state.charts[elId].dispose(); delete state.charts[elId]; }
      return;
    }
    fallback.style.display = 'none';
    if (!state.charts[elId]) state.charts[elId] = window.echarts.init(document.getElementById(elId));
    state.charts[elId].setOption({
      tooltip: { trigger: 'axis', confine: true, axisPointer: { type: 'shadow' } },
      legend: { data: ['健身', '游泳', '舞蹈'], top: 0, icon: 'circle', itemWidth: 8, itemHeight: 8, textStyle: { color: '#6b7280', fontSize: 12 } },
      grid: { left: 8, right: 8, top: 30, bottom: 4, containLabel: true },
      xAxis: { type: 'category', data: chart.labels, axisLine: { lineStyle: { color: '#d7dce3' } }, axisTick: { show: false }, axisLabel: { color: '#6b7280', fontSize: 11 } },
      yAxis: { type: 'value', splitLine: { lineStyle: { color: '#eee' } }, axisLabel: { color: '#6b7280', fontSize: 11 } },
      series: [
        { name: '健身', type: 'bar', stack: 't', data: chart.fitness, itemStyle: { color: COLORS.fitness }, barWidth: '46%' },
        { name: '游泳', type: 'bar', stack: 't', data: chart.swim, itemStyle: { color: COLORS.swim } },
        { name: '舞蹈', type: 'bar', stack: 't', data: chart.dance, itemStyle: { color: COLORS.dance } },
      ],
    });
  }

  /* ---------- 单日详情弹窗 ---------- */
  function openModal(day) {
    App.api('/api/overview/day?date=' + day).then(function (detail) {
      document.getElementById('ovModalTitle').textContent = '当日详情';
      document.getElementById('ovModalDate').textContent = day + '（' + weekdayOf(day) + '） · 点击「去该运动页」查看 / 操作当日全部数据';
      const body = document.getElementById('ovModalBody');
      body.innerHTML = ['fitness', 'swim', 'dance'].map(function (k) {
        const m = SPORT_META[k];
        const entries = normalizeEntries(k, detail[k]);
        const items = entries.length
          ? entries.map(function (e) {
              return '<div class="ov-detail-item">' +
                '<div class="di-main"><div class="di-title">' + esc(e.title) + '</div>' +
                (e.meta ? '<div class="di-meta">' + esc(e.meta) + '</div>' : '') + '</div>' +
                '<div class="di-go"><a class="btn btn-sm" href="' + m.url + '?date=' + day + '">去' + m.label + '页 ›</a></div></div>';
            }).join('')
          : '<div class="ov-detail-empty">当日无' + m.label + '数据</div>';
        return '<div class="ov-detail-block">' +
          '<div class="ov-detail-head"><span class="osc-dot ' + m.cls + '"></span><span class="od-title">' + m.label + '</span>' +
          '<span class="od-count num">' + (entries.length ? entries.length + ' 条' : '') + '</span></div>' + items + '</div>';
      }).join('');
      App.openModal('modalOvDay');
    }).catch(e => App.toast(e.message, true));
  }

  /* ---------- 条目归一化（返回原始文本，渲染时统一 esc） ---------- */
  function normalizeEntries(sport, list) {
    list = list || [];
    if (sport === 'fitness') {
      return list.map(function (p) {
        const recorded = p.status === 'recorded';
        let title = '训练';
        if (p.items && p.items.length) title = p.items[0].exercise_name;
        else if (p.body_parts_summary) title = p.body_parts_summary;
        let meta;
        if (recorded) {
          let dur = '';
          if (p.started_at && p.saved_at) dur = ' · ' + fmtClock((Date.parse(p.saved_at) - Date.parse(p.started_at)) / 1000);
          meta = p.total_sets + ' 组 · ' + p.total_volume + ' kg · ' + p.item_count + ' 动作' + dur;
        } else {
          meta = p.item_count + ' 个动作（计划）';
        }
        return { title: title, meta: meta };
      });
    }
    if (sport === 'swim') {
      return list.map(function (r) {
        if (r.status === 'planned') {
          const t = (r.distance_m != null ? r.distance_m + ' m' : '游泳计划') + ' · ' + fmtClock(r.duration_s);
          let meta = '计划';
          if (r.main_stroke_label) meta += ' · ' + r.main_stroke_label;
          if (r.remark) meta += ' · ' + r.remark;
          return { title: t, meta: meta };
        }
        let meta = fmtClock(r.duration_s);
        if (r.pace != null) meta += ' · 配速 ' + r.pace + ' min/100m';
        if (r.main_stroke_label) meta += ' · ' + r.main_stroke_label;
        if (r.calories != null) meta += ' · ' + r.calories + ' kcal';
        if (r.remark) meta += ' · ' + r.remark;
        return { title: (r.distance_m != null ? r.distance_m + ' m' : '—'), meta: meta };
      });
    }
    return list.map(function (r) {
      if (r.status === 'planned') {
        let meta = '计划';
        if (r.remark) meta += ' · ' + r.remark;
        return { title: (r.dance_type ? r.dance_type : '舞蹈') + ' ★' + (r.stars != null ? r.stars : '—'), meta: meta };
      }
      let meta = fmtClock(r.duration_s);
      if (r.style) meta += ' · ' + r.style;
      if (r.calories != null) meta += ' · ' + r.calories + ' kcal';
      if (r.remark) meta += ' · ' + r.remark;
      return { title: (r.dance_type ? r.dance_type : '舞蹈') + ' ★' + (r.stars != null ? r.stars : '—'), meta: meta };
    });
  }

  /* ---------- 事件 ---------- */
  document.getElementById('ovModeSeg').addEventListener('click', function (e) {
    const b = e.target.closest('button[data-mode]');
    if (!b || b.dataset.mode === state.mode) return;
    state.mode = b.dataset.mode;
    Array.prototype.forEach.call(this.children, el => el.classList.toggle('active', el === b));
    load();
  });

  function bindOpenDay(root) {
    root.addEventListener('click', function (e) {
      const t = e.target.closest('[data-open-day]');
      if (t) openModal(t.dataset.openDay);
    });
  }
  bindOpenDay(document.getElementById('ovDayCards'));
  bindOpenDay(document.getElementById('ovWeekStrip'));
  bindOpenDay(document.getElementById('ovCalGrid'));

  document.querySelectorAll('[data-close]').forEach(function (el) {
    el.addEventListener('click', function () { App.closeModal(el.dataset.close); });
  });

  /* ---------- 初始化 ---------- */
  load();
  window.addEventListener('resize', function () {
    Object.keys(state.charts).forEach(function (k) { state.charts[k].resize(); });
  });
})();
