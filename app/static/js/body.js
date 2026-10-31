/* 身材数据页：趋势折线（BD-10~14，null 断线 FE-17）、记录表格、添加/编辑/删除弹窗 */
(function () {
  const App = window.App;
  const chartEl = document.getElementById('trendChart');
  let chart = null;
  const METRIC_LABELS = { weight: '体重', body_fat: '体脂率', waist: '腰围' };
  const ORDER = ['weight', 'body_fat', 'chest', 'waist', 'hip', 'thigh', 'arm'];

  /* ---------- 趋势图 ---------- */
  function renderTrend(data) {
    const dates = data.points.map(p => p.date.slice(5));
    const values = data.points.map(p => (p.value == null ? null : p.value));
    const nonNull = values.filter(v => v != null);
    const current = nonNull.length ? nonNull[nonNull.length - 1] : null;
    const avg = nonNull.length ? +(nonNull.reduce((a, b) => a + b, 0) / nonNull.length).toFixed(2) : null;
    document.getElementById('lgCurrent').textContent = current != null ? current : '—';
    document.getElementById('lgAvg').textContent = avg != null ? avg : '—';
    document.getElementById('lgCount').textContent = nonNull.length + ' / ' + values.length;
    if (!chart) chart = echarts.init(chartEl);
    chart.setOption({
      animation: false,
      grid: { left: 48, right: 18, top: 26, bottom: 28 },
      tooltip: {
        trigger: 'axis',
        backgroundColor: '#ffffff',
        borderColor: '#e6e9f0',
        textStyle: { color: '#1f2430', fontSize: 12 },
        formatter: function (ps) {
          const p = ps[0];
          return p.name + '<br/>' + METRIC_LABELS[window.__metric || 'weight'] + '：' + (p.value == null ? '无记录' : p.value);
        }
      },
      xAxis: {
        type: 'category', data: dates, boundaryGap: false,
        axisLine: { lineStyle: { color: '#d5dae4' } },
        axisTick: { show: false },
        axisLabel: { color: '#6b7280', fontSize: 11 }
      },
      yAxis: {
        type: 'value', scale: true,
        splitLine: { lineStyle: { color: '#eef1f6' } },
        axisLabel: { color: '#6b7280', fontSize: 11 }
      },
      series: [{
        type: 'line',
        data: values,
        connectNulls: false,           // FE-17：缺失点断线，不插值不补零
        symbol: 'circle',
        symbolSize: 5,
        showSymbol: data.range === 'week' || data.range === 'month',
        lineStyle: { width: 2.5, color: '#1b2434' },
        itemStyle: { color: '#1b2434' },
        areaStyle: { color: 'rgba(27, 36, 52, 0.05)' },
        emphasis: { focus: 'series' }
      }]
    });
  }

  function loadTrend(metric, range) {
    window.__metric = metric;
    App.api('/api/body-metrics/trend?metric=' + metric + '&range=' + range)
      .then(renderTrend)
      .catch(e => App.toast(e.message, true));
  }

  /* ---------- 记录表格 ---------- */
  let currentPage = 1;

  function loadRecords(page) {
    currentPage = page || 1;
    App.api('/api/body-metrics?page=' + currentPage + '&page_size=10').then(function (res) {
      document.getElementById('recTotal').textContent = res.total;
      const tbody = document.getElementById('recBody');
      // 接口已按日期聚合（BD-02：同日同指标取最后一条）
      if (res.list.length === 0) {
        tbody.innerHTML = '<tr><td colspan="9"><div class="empty-state"><div class="icon">📭</div>暂无身材记录，点击右上角「添加记录」开始</div></td></tr>';
      } else {
        tbody.innerHTML = res.list.map(function (r) {
          const vals = r.values || {};
          const cells = ORDER.map(k => '<td class="num">' + (vals[k] != null ? vals[k] : '—') + '</td>').join('');
          return '<tr><td class="num">' + r.record_date + '</td>' + cells +
            '<td class="row-actions"><button class="btn btn-sm" data-act="edit" data-date="' + r.record_date + '">编辑</button>' +
            '<button class="btn btn-sm btn-danger" data-act="del" data-date="' + r.record_date + '">删除</button></td></tr>';
        }).join('');
      }
      // 分页
      renderPagination(res);
    }).catch(e => App.toast(e.message, true));
  }

  function renderPagination(res) {
    const wrap = document.getElementById('recPagination');
    if (res.pages <= 1) { wrap.innerHTML = ''; return; }
    let html = '<div class="pagination"><span>共 ' + res.total + ' 条 · 每页 ' + res.page_size + ' 条</span>';
    html += '<button class="btn btn-sm" data-pg="' + (res.page - 1) + '" ' + (res.page <= 1 ? 'disabled' : '') + '>上一页</button>';
    for (let p = 1; p <= res.pages; p++) {
      html += '<button class="btn btn-sm ' + (p === res.page ? 'active' : '') + '" data-pg="' + p + '">' + p + '</button>';
    }
    html += '<button class="btn btn-sm" data-pg="' + (res.page + 1) + '" ' + (res.page >= res.pages ? 'disabled' : '') + '>下一页</button></div>';
    wrap.innerHTML = html;
  }

  /* ---------- 弹窗表单 ---------- */
  function openForm(dateStr, values) {
    document.getElementById('modalBodyTitle').textContent = dateStr ? '编辑身材记录' : '添加身材记录';
    const form = document.getElementById('formBodyRecord');
    form.reset();
    form.record_date.value = dateStr || App.todayStr();
    ORDER.forEach(function (k) {
      const v = values && values[k] != null ? values[k] : '';
      form.elements[k].value = v;
      form.elements[k].placeholder = (values && values[k] != null) ? '' : '留空沿用最近值';
    });
    form.record_date.max = App.todayStr();
    App.openModal('modalBodyRecord');
  }

  document.getElementById('btnAddRecord').addEventListener('click', function () { openForm(null, null); });

  document.getElementById('recBody').addEventListener('click', function (e) {
    const btn = e.target.closest('button[data-act]');
    if (!btn) return;
    const date = btn.dataset.date;
    if (btn.dataset.act === 'del') {
      if (!App.confirm('确定删除 ' + date + ' 的全部身材记录吗？')) return;
      App.api('/api/body-metrics?record_date=' + date, { method: 'DELETE' })
        .then(function () { App.toast('已删除'); setTimeout(function () { location.reload(); }, 400); })
        .catch(err => App.toast(err.message, true));
    } else if (btn.dataset.act === 'edit') {
      App.api('/api/body-metrics?page=1&page_size=100').then(function (res) {
        const item = res.list.find(function (r) { return r.record_date === date; });
        openForm(date, item ? item.values : {});
      }).catch(err => App.toast(err.message, true));
    }
  });

  document.getElementById('recPagination').addEventListener('click', function (e) {
    const b = e.target.closest('button[data-pg]');
    if (b && !b.disabled) loadRecords(parseInt(b.dataset.pg, 10));
  });

  document.getElementById('formBodyRecord').addEventListener('submit', function (e) {
    e.preventDefault();
    const form = e.target;
    const values = {};
    ORDER.forEach(function (k) {
      const el = form.elements[k];
      if (el.value !== '') values[k] = parseFloat(el.value);
    });
    if (!Object.keys(values).length) { App.toast('至少填写一个指标', true); return; }
    const payload = { record_date: form.record_date.value, values: values };
    App.api('/api/body-metrics', { method: 'POST', body: payload })
      .then(function () {
        App.closeModal('modalBodyRecord');
        App.toast('已保存');
        setTimeout(function () { location.reload(); }, 400);
      })
      .catch(err => App.toast(err.message, true));
  });

  /* ---------- 档位/指标切换 ---------- */
  document.getElementById('metricSeg').addEventListener('click', function (e) {
    const b = e.target.closest('button'); if (!b) return;
    Array.prototype.forEach.call(this.children, c => c.classList.remove('active'));
    b.classList.add('active');
    loadTrend(b.dataset.metric, document.querySelector('#rangeSeg button.active').dataset.range);
  });
  document.getElementById('rangeSeg').addEventListener('click', function (e) {
    const b = e.target.closest('button'); if (!b) return;
    Array.prototype.forEach.call(this.children, c => c.classList.remove('active'));
    b.classList.add('active');
    loadTrend(document.querySelector('#metricSeg button.active').dataset.metric, b.dataset.range);
  });

  /* 关闭按钮 */
  document.querySelectorAll('[data-close]').forEach(function (el) {
    el.addEventListener('click', function () { App.closeModal(el.dataset.close); });
  });

  /* ---------- 初始化 ---------- */
  if (window.INIT_TREND) renderTrend(window.INIT_TREND);
  loadRecords(1);
  window.addEventListener('resize', function () { if (chart) chart.resize(); });
})();
