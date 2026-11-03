/* 运动训练/计划 总览页：日/周/月三视图（2026-11）。
   数据源：GET /api/overview?granularity=day|week|month&date=；单日详情 GET /api/overview/day?date=。
   2026-11-03 布局：日=训练计划卡(顶)→三运动卡→当日运动情况(底)；周/月=每日卡(最上)→运动情况卡(次数+时长+每日时长图)。
   月图表粒度：按月内每日（labels=日号）。 */
(function () {
  const App = window.App;
  const todayStr = window.INIT_TODAY || App.todayStr();
  const qs = new URLSearchParams(location.search);
  const state = {
    mode: ['day', 'week', 'month'].indexOf(qs.get('mode')) >= 0 ? qs.get('mode') : 'week',
    anchor: qs.get('date') || todayStr,   // ?date= 指定锚定日（总览跳回时定位到添加计划的那天）
    pickDay: null,
    charts: {},
  };

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

  /* ---------- 统计块（通用） ---------- */
  function summaryGridHtml(stats) {
    const per = stats.per_sport;
    return '<div class="sum-item"><div class="sum-label">运动次数</div><div class="sum-value num">' + stats.records +
      '<small> 次</small></div><div class="sum-sub">健身 ' + per.fitness.records + ' · 游泳 ' + per.swim.records + ' · 舞蹈 ' + per.dance.records + '</div></div>' +
      '<div class="sum-item"><div class="sum-label">运动时长</div><div class="sum-value num">' + stats.minutes +
      '<small> 分钟</small></div><div class="sum-sub">健身 ' + per.fitness.minutes + ' · 游泳 ' + per.swim.minutes + ' · 舞蹈 ' + per.dance.minutes + '</div></div>';
  }

  function dayPlanStatHtml(stats) {
    const per = stats.per_sport;
    return '<div class="stat-card"><div class="label">训练计划</div><div class="value num">' + stats.plans +
      '<small> 项</small></div><div class="sub">健身 ' + per.fitness.plans + ' · 游泳 ' + per.swim.plans + ' · 舞蹈 ' + per.dance.plans + '</div></div>';
  }

  /* 运动标签 chip（周条带 / 月日历共用）：运动名 + 记N·计M + 时长 */
  function chipHtml(k, c, dayAttr) {
    const m = SPORT_META[k];
    const parts = [];
    if (c.records) parts.push('记' + c.records);
    if (c.plans) parts.push('计' + c.plans);
    const cnt = parts.length ? '<em class="oc-cnt">' + parts.join(' · ') + '</em>' : '';
    const min = c.minutes ? '<em class="oc-min">' + c.minutes + ' min</em>' : '';
    return '<span class="ov-chip ' + m.cls + '"' + (dayAttr ? ' data-open-day="' + dayAttr + '"' : '') + '>' +
      '<span class="oc-dot"></span>' + m.label + cnt + min + '</span>';
  }

  /* ---------- 总览加载 ---------- */
  function load() {
    App.api('/api/overview?granularity=' + state.mode + '&date=' + state.anchor).then(function (res) {
      const views = { day: 'ovDayView', week: 'ovWeekView', month: 'ovMonthView' };
      Object.keys(views).forEach(v => document.getElementById(views[v]).style.display = v === state.mode ? '' : 'none');
      history.replaceState(null, '', '?mode=' + state.mode + '&date=' + state.anchor);
      if (state.mode === 'day') { renderDayCards(res); return; }
      if (state.mode === 'week') { renderWeek(res); return; }
      renderMonth(res);
    }).catch(e => App.toast(e.message, true));
  }

  /* ---------- 日视图：训练计划卡(顶) + 三运动当日卡 + 当日运动情况(底) ---------- */
  function renderDayCards(res) {
    document.getElementById('ovDayStats').innerHTML = dayPlanStatHtml(res.stats);
    document.getElementById('ovDaySummaryGrid').innerHTML = summaryGridHtml(res.stats);
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
          '<button type="button" class="btn btn-sm osc-newplan" data-newplan="' + k + '" title="为这一天新建' + m.label + '计划">＋ 计划</button>' +
          '<span class="osc-count num">记录 ' + c.records + ' · 计划 ' + c.plans + '</span></div>' +
          '<div class="osc-list">' + listHtml + '</div></div>';
      }).join('');
    }).catch(e => App.toast(e.message, true));
  }

  /* ---------- 周视图：本周每日运动条带（最上）+ 本周运动情况（次数/时长 + 每日时长图） ---------- */
  function renderWeek(res) {
    const strip = document.getElementById('ovWeekStrip');
    const todayIdx = res.days.findIndex(d => d.date === todayStr);
    strip.innerHTML = res.days.map(function (d, i) {
      const wd = weekdayOf(d.date);
      const marks = [];
      ['fitness', 'swim', 'dance'].forEach(function (k) {
        const c = d.sports[k];
        if (c.records || c.plans) marks.push(chipHtml(k, c, d.date));
      });
      return '<div class="ws-day' + (i === todayIdx ? ' is-today' : '') + '" data-add-day="' + d.date + '" title="为这一天添加计划">' +
        '<div class="wd-top"><span class="wd-num">' + parseInt(d.date.slice(8), 10) + '</span><span class="wd-week">' + wd + '</span><button type="button" class="wd-add" title="为这一天添加计划">＋</button></div>' +
        '<div class="wd-sports">' + (marks.length ? marks.join('') : '<span class="wd-empty">—</span>') + '</div></div>';
    }).join('');
    document.getElementById('ovWeekSummaryGrid').innerHTML = summaryGridHtml(res.stats);
    renderChart('chartOvWeek', 'chartOvWeekFallback', res.chart);
  }

  /* ---------- 月视图：本月日历（最上）+ 本月运动情况（次数/时长 + 每日时长图） ---------- */
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
          if (c.records || c.plans) mk.push(chipHtml(k, c, iso));
        });
        marks = mk.length ? mk.join('') : '<span class="cd-empty">—</span>';
      }
      cells += '<div class="ov-cal-cell' + (iso === todayStr ? ' is-today' : '') + '" data-add-day="' + iso + '" title="为这一天添加计划">' +
        '<div class="cd-num num">' + day + '</div><div class="cd-marks">' + marks + '</div></div>';
    }

    const grid = document.getElementById('ovCalGrid');
    grid.innerHTML = '<div class="ov-cal"><div class="ov-cal-head">' +
      ['一', '二', '三', '四', '五', '六', '日'].map(w => '<span>' + w + '</span>').join('') + '</div>' +
      '<div class="ov-cal-grid">' + cells + '</div></div>';
    document.getElementById('ovMonthSummaryGrid').innerHTML = summaryGridHtml(res.stats);
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

  /* ---------- 为某天添加计划：选运动弹窗 → 跳对应运动页自动开新建计划表单 ---------- */
  function sportUrl(sport, day) {
    return SPORT_META[sport].url + '?date=' + day + '&newplan=1&fromov=1';
  }
  function openPicker(day) {
    state.pickDay = day;
    document.getElementById('ovPickDate').textContent = day + '（' + weekdayOf(day) + '） · 选择要添加哪类运动计划？';
    App.openModal('modalOvPick');
  }

  /* ---------- 事件 ---------- */
  function syncSeg() {
    document.querySelectorAll('#ovModeSeg button[data-mode]').forEach(function (b) {
      b.classList.toggle('active', b.dataset.mode === state.mode);
    });
  }
  document.getElementById('ovModeSeg').addEventListener('click', function (e) {
    const b = e.target.closest('button[data-mode]');
    if (!b || b.dataset.mode === state.mode) return;
    state.mode = b.dataset.mode;
    syncSeg();
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

  /* 点日期格（非标签）→ 添加计划选择器 */
  function bindAddDay(root) {
    root.addEventListener('click', function (e) {
      if (e.target.closest('[data-open-day]')) return;   // 标签→当日详情优先
      const t = e.target.closest('[data-add-day]');
      if (t) openPicker(t.dataset.addDay);
    });
  }
  bindAddDay(document.getElementById('ovWeekStrip'));
  bindAddDay(document.getElementById('ovCalGrid'));

  /* 日视图：每运动卡头部「＋ 计划」→ 直接跳该运动页新建 */
  document.getElementById('ovDayCards').addEventListener('click', function (e) {
    const b = e.target.closest('[data-newplan]');
    if (b) location.href = sportUrl(b.dataset.newplan, state.anchor);
  });

  /* 选运动弹窗 */
  document.getElementById('modalOvPick').addEventListener('click', function (e) {
    const b = e.target.closest('[data-pick]');
    if (!b) return;
    location.href = sportUrl(b.dataset.pick, state.pickDay);
  });

  document.querySelectorAll('[data-close]').forEach(function (el) {
    el.addEventListener('click', function () { App.closeModal(el.dataset.close); });
  });

  /* ---------- 初始化 ---------- */
  syncSeg();
  load();
  window.addEventListener('resize', function () {
    Object.keys(state.charts).forEach(function (k) { state.charts[k].resize(); });
  });
})();
