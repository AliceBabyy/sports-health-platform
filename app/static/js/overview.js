/* 运动训练/计划 总览页：日/周/月三视图（2026-11）。
   数据源：GET /api/overview?granularity=day|week|month&date=；单日详情 GET /api/overview/day?date=。
   2026-11-03 布局：日=训练计划卡(顶)→三运动卡→当日运动情况(底)；周/月=每日卡(最上)→运动情况卡(次数+时长+每日时长图)。
   月图表粒度：按月内每日（labels=日号）。
   2026-11-08 周期切换：顶部 ‹ › 按视图步进（日±1天 / 周±7天 / 月±1月，跨月夹日号），
   标签显示当前区间，非当期显示「回到今天」；周每日卡周几旁加灰色「月/日」。 */
(function () {
  const App = window.App;
  // 「今天」以浏览器本地日期为准：服务端 app.state.today 在启动时固定，服务长时间不重启会过期
  const todayStr = App.todayStr() || window.INIT_TODAY;
  const qs = new URLSearchParams(location.search);
  const state = {
    mode: ['day', 'week', 'month'].indexOf(qs.get('mode')) >= 0 ? qs.get('mode') : 'week',
    anchor: qs.get('date') || todayStr,   // ?date= 指定锚定日（总览跳回时定位到添加计划的那天）
    pickDay: null,
    charts: {},
    openDay: null,     // 弹窗当前日期（保存 remark 后刷新用）
    detail: null,      // 弹窗当前 detail 快照（保存 remark 回传完整 body 用）
  };

  const SPORT_META = {
    fitness: { label: '健身', cls: 'fit', url: '/training' },
    swim: { label: '游泳', cls: 'swim', url: '/swim' },
    dance: { label: '舞蹈', cls: 'dance', url: '/dance' },
  };
  const WEEKDAY_CN = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];
  // 单一来源：运行时从 tokens.css 读 --ov-*（改令牌即生效）；fallback 仅防 CSS 未加载导致图表无色
  const COLORS = {
    fitness: App.cssVar('--ov-fit', '#6b7280'),
    swim: App.cssVar('--ov-swim', '#3d8fd1'),
    dance: App.cssVar('--ov-dance', '#e8558c'),
  };

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

  /* ---------- 周期切换（2026-11-08）：日=前后天、周=前后周、月=前后月 ---------- */
  function pad2(n) { return String(n).padStart(2, '0'); }
  function isoOf(d) { return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate()); }
  function mdText(iso) { return Number(iso.slice(5, 7)) + '月' + Number(iso.slice(8, 10)) + '日'; }
  function mdShort(iso) { return Number(iso.slice(5, 7)) + '/' + Number(iso.slice(8, 10)); }
  const PERIOD_DAYS = { day: 1, week: 7 };

  /* 按当前视图步进锚点日：跨月时把日号夹到目标月最后一天（1/31 → 2/28） */
  function stepAnchor(iso, step) {
    const d = new Date(iso + 'T00:00:00');
    if (state.mode === 'month') {
      const first = new Date(d.getFullYear(), d.getMonth() + step, 1);
      const lastDay = new Date(first.getFullYear(), first.getMonth() + 1, 0).getDate();
      first.setDate(Math.min(d.getDate(), lastDay));
      return isoOf(first);
    }
    d.setDate(d.getDate() + PERIOD_DAYS[state.mode] * step);
    return isoOf(d);
  }

  /* 顶部周期标签：日=某月某日 周X、周=起止区间、月=某年某月；并同步切换按钮提示与「回到今天」显隐 */
  function setPeriod(res) {
    const label = document.getElementById('ovDateLabel');
    const curYear = todayStr.slice(0, 4);
    if (state.mode === 'day') {
      label.textContent = (res.date.slice(0, 4) === curYear ? '' : res.date.slice(0, 4) + '年') +
        mdText(res.date) + ' ' + weekdayOf(res.date);
    } else if (state.mode === 'week') {
      const s = res.start, e = res.end;
      label.textContent = (s.slice(0, 4) === curYear ? '' : s.slice(0, 4) + '年') + mdText(s) + ' – ' +
        (e.slice(0, 4) === s.slice(0, 4) ? '' : e.slice(0, 4) + '年') + mdText(e);
    } else {
      label.textContent = res.date.slice(0, 4) + '年' + Number(res.date.slice(5, 7)) + '月';
    }
    const tip = { day: ['前一天', '后一天'], week: ['上一周', '下一周'], month: ['上个月', '下个月'] }[state.mode];
    document.querySelectorAll('#ovPeriodNav .dn-btn').forEach(function (b, i) {
      b.title = tip[i];
      b.setAttribute('aria-label', tip[i]);
    });
    document.getElementById('ovTodayBtn').hidden = (todayStr >= res.start && todayStr <= res.end);
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

  /* 运动标签 chip（周/月共用）：每条计划/记录一个独立标签；remark 显示在标签内部。
     结构：.ov-chip > .oc-line(圆点+运动名+计/记+main) + .oc-remark（可无）；
     圆点颜色：计划=蓝绿 plan、记录=深灰 rec（2026-11-04）。 */
  function chipHtml(k, it, dayAttr) {
    const m = SPORT_META[k];
    const cls = it.status === 'recorded' ? 'rec' : 'plan';
    const rm = it.remark ? '<em class="oc-remark">' + esc(it.remark) + '</em>' : '';
    return '<span class="ov-chip ' + m.cls + '"' + (dayAttr ? ' data-open-day="' + dayAttr + '"' : '') + '>' +
      '<span class="oc-line"><span class="oc-dot ' + cls + '"></span>' +
      '<span class="oc-main">' + m.label + it.tag + ' · ' + esc(it.main) + '</span></span>' + rm + '</span>';
  }

  /* ---------- 总览加载 ---------- */
  function load() {
    App.api('/api/overview?granularity=' + state.mode + '&date=' + state.anchor).then(function (res) {
      const views = { day: 'ovDayView', week: 'ovWeekView', month: 'ovMonthView' };
      Object.keys(views).forEach(v => document.getElementById(views[v]).style.display = v === state.mode ? '' : 'none');
      history.replaceState(null, '', '?mode=' + state.mode + '&date=' + state.anchor);
      setPeriod(res);
      if (state.mode === 'day') { renderDayCards(res); return; }
      if (state.mode === 'week') { renderWeek(res); return; }
      renderMonth(res);
    }).catch(e => App.toast(e.message, true));
  }

  /* ---------- 日视图：训练计划卡(顶) + 三运动当日卡 + 当日运动情况(底) ---------- */
  /* 单条计划/记录完整展示（日视图空间大，不再简略截断） */
  function dayItemHtml(k, e) {
    const rec = e.status === 'recorded';
    const cls = rec ? 'rec' : 'plan';
    const dot = '<span class="oi-dot ' + cls + '"></span>';
    if (k === 'fitness') {
      const title = rec ? '训练记录' : '训练计划';
      const exs = (e.items || []).map(function (it) {
        const w = it.weight_kg != null ? it.weight_kg + 'kg × ' : '';
        const s = it.sets != null ? it.sets + '组 × ' : '';
        const r = it.reps != null ? (/^\d+$/.test(String(it.reps)) ? it.reps + '次' : it.reps) : '';
        const spec = w + s + r;
        return '<div class="oi-ex">' + esc(it.exercise_name) +
          (spec ? '<em class="oi-w">' + esc(spec) + '</em>' : '') + '</div>';
      }).join('');
      let meta = e.total_sets + ' 组 · ' + e.total_volume + ' kg · ' + e.item_count + ' 动作';
      if (rec && e.duration_s) {
        meta += ' · ' + fmtClock(e.duration_s);
      } else if (rec && e.start_time && e.end_time) {
        meta += ' · ' + fmtClock((Date.parse(e.end_time) - Date.parse(e.start_time)) / 1000);
      }
      return '<div class="osc-item" data-open-day="' + state.anchor + '">' +
        '<div class="oi-title">' + dot + esc(title) + '</div>' +
        '<div class="oi-exs">' + exs + '</div>' +
        '<div class="oi-meta">' + esc(meta) + '</div>' +
        (e.remark ? '<div class="oi-remark">' + esc(e.remark) + '</div>' : '') + '</div>';
    }
    if (k === 'swim') {
      const title = (rec ? '游泳记录' : '游泳计划') + ' · ' +
        (e.distance_m != null ? e.distance_m + ' m' : '—') +
        (rec && e.duration_s ? ' · ' + fmtClock(e.duration_s) : '');
      let meta = rec ? '' : (e.main_stroke_label || '');
      if (rec) {
        if (e.pace != null) meta += '配速 ' + e.pace + ' min/100m · ';
        if (e.main_stroke_label) meta += e.main_stroke_label + ' · ';
        if (e.calories != null) meta += e.calories + ' kcal · ';
        if (e.avg_heart_rate != null) meta += '心率 ' + e.avg_heart_rate + ' · ';
        meta = meta.replace(/ · $/, '');
      }
      return '<div class="osc-item" data-open-day="' + state.anchor + '">' +
        '<div class="oi-title">' + dot + esc(title) + '</div>' +
        (meta ? '<div class="oi-meta">' + esc(meta) + '</div>' : '') +
        (e.remark ? '<div class="oi-remark">' + esc(e.remark) + '</div>' : '') + '</div>';
    }
    const title = (rec ? '舞蹈记录' : '舞蹈计划') + ' · ' + (e.dance_type || '舞蹈') +
      ' ★' + (e.stars != null ? e.stars : '—') + (rec && e.duration_s ? ' · ' + fmtClock(e.duration_s) : '');
    let meta = e.style || '';
    if (rec) {
      if (e.calories != null) meta += (meta ? ' · ' : '') + e.calories + ' kcal';
      if (e.max_heart_rate != null) meta += (meta ? ' · ' : '') + '心率 ' + e.max_heart_rate;
    }
    return '<div class="osc-item" data-open-day="' + state.anchor + '">' +
      '<div class="oi-title">' + dot + esc(title) + '</div>' +
      (meta ? '<div class="oi-meta">' + esc(meta) + '</div>' : '') +
      (e.remark ? '<div class="oi-remark">' + esc(e.remark) + '</div>' : '') + '</div>';
  }

  function renderDayCards(res) {
    document.getElementById('ovDayStats').innerHTML = dayPlanStatHtml(res.stats);
    document.getElementById('ovDaySummaryGrid').innerHTML = summaryGridHtml(res.stats);
    App.api('/api/overview/day?date=' + state.anchor).then(function (detail) {
      const wrap = document.getElementById('ovDayCards');
      wrap.innerHTML = ['fitness', 'swim', 'dance'].map(function (k) {
        const m = SPORT_META[k];
        const c = res.days[0].sports[k];
        const entries = detail[k] || [];
        const listHtml = entries.length
          ? entries.map(function (e) { return dayItemHtml(k, e); }).join('')
          : '<div class="osc-empty">当日无' + m.label + '数据</div>';
        return '<div class="card ov-sport-card">' +
          '<div class="osc-head"><span class="osc-rail ' + m.cls + '"></span>' +
          '<span class="osc-title">' + m.label + '</span>' +
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
        (c.items || []).forEach(function (it) { marks.push(chipHtml(k, it, d.date)); });
      });
      return '<div class="ws-day' + (i === todayIdx ? ' is-today' : '') + '" data-add-day="' + d.date + '" title="为这一天添加计划">' +
        '<div class="wd-top"><span class="wd-week">' + wd + '<em class="wd-date">' + mdShort(d.date) + '</em></span>' +
        '<button type="button" class="wd-add" title="为这一天添加计划">＋</button></div>' +
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
          (c.items || []).forEach(function (it) { mk.push(chipHtml(k, it, iso)); });
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
      legend: { data: ['健身', '游泳', '舞蹈'], top: 0, icon: 'circle', itemWidth: 8, itemHeight: 8, textStyle: { color: App.cssVar('--color-text-secondary', '#6b7280'), fontSize: 12 } },
      grid: { left: 8, right: 8, top: 30, bottom: 4, containLabel: true },
      xAxis: { type: 'category', data: chart.labels, axisLine: { lineStyle: { color: App.cssVar('--color-chart-axis', '#d7dce3') } }, axisTick: { show: false }, axisLabel: { color: App.cssVar('--color-text-secondary', '#6b7280'), fontSize: 11 } },
      yAxis: { type: 'value', splitLine: { lineStyle: { color: App.cssVar('--color-chart-grid', '#eeeeee') } }, axisLabel: { color: App.cssVar('--color-text-secondary', '#6b7280'), fontSize: 11 } },
      series: [
        { name: '健身', type: 'bar', stack: 't', data: chart.fitness, itemStyle: { color: COLORS.fitness }, barWidth: '46%' },
        { name: '游泳', type: 'bar', stack: 't', data: chart.swim, itemStyle: { color: COLORS.swim } },
        { name: '舞蹈', type: 'bar', stack: 't', data: chart.dance, itemStyle: { color: COLORS.dance } },
      ],
    });
  }

  /* ---------- 单日详情弹窗 ---------- */
  /* 弹窗条目：完整标题/信息 + remark 内联编辑（可保存，改完联动刷新视图） */
  function detailItemHtml(k, e, day) {
    const m = SPORT_META[k];
    const rec = e.status === 'recorded';
    const cls = rec ? 'rec' : 'plan';
    const dot = '<span class="oi-dot ' + cls + '"></span>';
    let title, meta = '';
    if (k === 'fitness') {
      title = rec ? '训练记录' : '训练计划';
      meta = e.item_count + ' 个动作 · ' + e.total_sets + ' 组 · ' + e.total_volume + ' kg';
      if (rec && e.duration_s) {
        meta += ' · ' + fmtClock(e.duration_s);
      } else if (rec && e.start_time && e.end_time) {
        meta += ' · ' + fmtClock((Date.parse(e.end_time) - Date.parse(e.start_time)) / 1000);
      }
    } else if (k === 'swim') {
      title = (rec ? '游泳记录' : '游泳计划') + ' · ' + (e.distance_m != null ? e.distance_m + ' m' : '—') +
        (rec && e.duration_s ? ' · ' + fmtClock(e.duration_s) : '');
      if (rec) {
        if (e.pace != null) meta += '配速 ' + e.pace + ' min/100m · ';
        if (e.main_stroke_label) meta += e.main_stroke_label + ' · ';
        if (e.calories != null) meta += e.calories + ' kcal · ';
        if (e.avg_heart_rate != null) meta += '心率 ' + e.avg_heart_rate + ' · ';
        meta = meta.replace(/ · $/, '');
      } else if (e.main_stroke_label) {
        meta = e.main_stroke_label;
      }
    } else {
      title = (rec ? '舞蹈记录' : '舞蹈计划') + ' · ' + (e.dance_type || '舞蹈') +
        ' ★' + (e.stars != null ? e.stars : '—') + (rec && e.duration_s ? ' · ' + fmtClock(e.duration_s) : '');
      if (e.style) meta += e.style;
      if (rec && e.calories != null) meta += (meta ? ' · ' : '') + e.calories + ' kcal';
      if (rec && e.max_heart_rate != null) meta += (meta ? ' · ' : '') + '心率 ' + e.max_heart_rate;
    }
    return '<div class="ov-detail-item" data-sport="' + k + '" data-id="' + e.id + '">' +
      '<div class="di-main"><div class="di-title">' + dot + esc(title) + '</div>' +
      (meta ? '<div class="di-meta">' + esc(meta) + '</div>' : '') + '</div>' +
      '<div class="di-rm"><textarea class="di-rm-input" rows="1" placeholder="备注（可编辑保存）">' + esc(e.remark || '') + '</textarea>' +
      '<button type="button" class="btn btn-sm di-rm-save" data-save-rm="' + k + ':' + e.id + '">保存</button></div>' +
      '<div class="di-go"><a class="btn btn-sm" href="' + m.url + '?date=' + day + '">去' + m.label + '页 ›</a></div></div>';
  }

  function openModal(day) {
    state.openDay = day;
    App.api('/api/overview/day?date=' + day).then(function (detail) {
      state.detail = detail;
      document.getElementById('ovModalTitle').textContent = '当日详情';
      document.getElementById('ovModalDate').textContent = day + '（' + weekdayOf(day) + '） · 点击「去该运动页」查看 / 操作当日全部数据';
      const body = document.getElementById('ovModalBody');
      body.innerHTML = ['fitness', 'swim', 'dance'].map(function (k) {
        const m = SPORT_META[k];
        const entries = detail[k] || [];
        const items = entries.length
          ? entries.map(function (e) { return detailItemHtml(k, e, day); }).join('')
          : '<div class="ov-detail-empty">当日无' + m.label + '数据</div>';
        return '<div class="ov-detail-block">' +
          '<div class="ov-detail-head"><span class="osc-rail ' + m.cls + '"></span><span class="od-title">' + m.label + '</span>' +
          '<span class="od-count num">' + (entries.length ? entries.length + ' 条' : '') + '</span></div>' + items + '</div>';
      }).join('');
      App.openModal('modalOvDay');
    }).catch(e => App.toast(e.message, true));
  }

  /* 弹窗内保存 remark：PUT 对应条目（回传完整 body），成功后刷新弹窗 + 视图 */
  document.getElementById('ovModalBody').addEventListener('click', function (e) {
    const b = e.target.closest('[data-save-rm]');
    if (!b) return;
    const itemEl = b.closest('.ov-detail-item');
    const val = (itemEl.querySelector('.di-rm-input').value || '').trim() || null;
    const key = b.dataset.saveRm;                 // sport:id
    const sport = key.slice(0, key.indexOf(':'));
    const id = key.slice(key.indexOf(':') + 1);
    const detail = state.detail || {};
    const entry = (detail[sport] || []).find(function (x) { return String(x.id) === id; });
    if (!entry) { App.toast('未找到该条目', true); return; }
    let url, body;
    if (sport === 'fitness') {
      url = '/api/training/' + id;
      body = {
        date: entry.date,
        items: entry.items.map(function (it) {
          return {
            exercise_name: it.exercise_name,
            body_part: it.body_part,
            weight_kg: it.weight_kg,
            sets: it.sets,
            reps: it.reps,
            target_weight_kg: it.target_weight_kg,
          };
        }),
        remark: val,
        start_time: entry.start_time,
        end_time: entry.end_time,
        duration_s: entry.duration_s,
        avg_heart_rate: entry.avg_heart_rate,
        max_heart_rate: entry.max_heart_rate,
        calories: entry.calories,
      };
    } else if (sport === 'swim') {
      url = '/api/swim-records/' + id;
      body = {
        date: entry.date,
        status: entry.status,
        start_time: entry.start_time,
        end_time: entry.end_time,
        distance_m: entry.distance_m,
        duration_s: entry.duration_s,
        main_stroke: entry.main_stroke,
        remark: val,
        avg_heart_rate: entry.avg_heart_rate,
        max_heart_rate: entry.max_heart_rate,
        total_strokes: entry.total_strokes,
        laps: entry.laps,
        calories: entry.calories,
        avg_stroke_rate: entry.avg_stroke_rate,
      };
    } else {
      url = '/api/dance-records/' + id;
      body = {
        date: entry.date,
        status: entry.status,
        start_time: entry.start_time,
        end_time: entry.end_time,
        dance_type: entry.dance_type,
        stars: entry.stars,
        teacher: entry.teacher,
        remark: val,
        style: entry.style,
        duration_s: entry.duration_s,
        avg_heart_rate: entry.avg_heart_rate,
        max_heart_rate: entry.max_heart_rate,
        calories: entry.calories,
      };
    }
    App.api(url, { method: 'PUT', body: body })
      .then(function () {
        App.toast('备注已保存');
        openModal(state.openDay);
        load();
      })
      .catch(err => App.toast(err.message, true));
  });

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

  /* 周期切换：‹ › 按当前视图步进锚点日；「回到今天」直接归位 */
  document.getElementById('ovPeriodNav').addEventListener('click', function (e) {
    const stepBtn = e.target.closest('[data-step]');
    if (stepBtn) {
      state.anchor = stepAnchor(state.anchor, Number(stepBtn.dataset.step));
      load();
      return;
    }
    if (e.target.closest('#ovTodayBtn')) {
      if (state.anchor === todayStr) return;
      state.anchor = todayStr;
      load();
    }
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
