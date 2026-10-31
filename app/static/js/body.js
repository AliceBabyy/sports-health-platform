/* 身材数据页（4 表拆分）：趋势折线、合并记录表格、4 组添加弹窗（基础/期望/围度/目标围度）。
   新记录未填字段由服务端沿用该维度最近一次非空值；同日重复保存=覆盖当日该组。 */
(function () {
  const App = window.App;
  const chartEl = document.getElementById('trendChart');
  let chart = null;
  const LABELS = window.BODY_LABELS || {};
  const GROUPS = window.BODY_GROUPS || {};
  const GROUP_LABELS = window.GROUP_LABELS || {};
  // 表格列（主要维度）
  const TABLE_COLS = ['height', 'weight', 'body_fat', 'chest', 'waist', 'hip', 'thigh'];

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
    const metric = document.getElementById('metricSelect').value;
    const label = LABELS[metric] || metric;
    if (!chart) chart = echarts.init(chartEl);
    chart.setOption({
      animation: false,
      grid: { left: 48, right: 18, top: 34, bottom: 28 },
      tooltip: {
        trigger: 'axis',
        backgroundColor: '#ffffff',
        borderColor: 'rgba(27, 36, 52, 0.055)',
        textStyle: { color: '#1f2430', fontSize: 12 },
        formatter: function (ps) {
          const p = ps[0];
          return p.name + '<br/>' + label + '：' + (p.value == null ? '无记录' : p.value);
        }
      },
      xAxis: {
        type: 'category', data: dates, boundaryGap: false,
        axisLine: { lineStyle: { color: 'rgba(27, 36, 52, 0.055)' } },
        axisTick: { show: false },
        axisLabel: { color: '#6b7280', fontSize: 11 }
      },
      yAxis: {
        type: 'value', scale: true,
        splitLine: { lineStyle: { color: 'rgba(27, 36, 52, 0.026)' } },
        axisLabel: { color: '#6b7280', fontSize: 11 }
      },
      series: [{
        type: 'line',
        data: values,
        connectNulls: true,           // 无记录点跳过、曲线连续不中断
        symbol: 'circle',
        symbolSize: 5,
        showSymbol: true,
        lineStyle: { width: 2.5, color: '#1b2434' },
        itemStyle: { color: '#1b2434' },
        areaStyle: { color: 'rgba(27, 36, 52, 0.05)' },
        label: {
          show: true,
          position: 'top',
          color: '#6b7280',
          fontSize: 10
        },
        emphasis: { focus: 'series' }
      }]
    });
  }

  function loadTrend(metric, range) {
    App.api('/api/body-metrics/trend?metric=' + metric + '&range=' + range)
      .then(renderTrend)
      .catch(e => App.toast(e.message, true));
  }

  /* ---------- 记录表格（按日期合并 4 组） ---------- */
  let currentPage = 1;

  function targetSummary(vals) {
    const parts = [];
    if (vals.target_weight != null) parts.push(vals.target_weight + ' kg');
    if (vals.target_body_fat != null) parts.push(vals.target_body_fat + ' %');
    if (vals.target_waist != null) parts.push(vals.target_waist + ' cm');
    return parts.length ? parts.join(' / ') : '—';
  }

  function loadRecords(page) {
    currentPage = page || 1;
    App.api('/api/body-metrics?page=' + currentPage + '&page_size=10').then(function (res) {
      document.getElementById('recTotal').textContent = res.total;
      const tbody = document.getElementById('recBody');
      if (res.list.length === 0) {
        tbody.innerHTML = '<tr><td colspan="10"><div class="empty-state"><div class="icon">📭</div>暂无身材记录，点击上方四个按钮按类别添加</div></td></tr>';
      } else {
        tbody.innerHTML = res.list.map(function (r) {
          const vals = r.values || {};
          const cells = TABLE_COLS.map(k => '<td class="num">' + (vals[k] != null ? vals[k] : '—') + '</td>').join('');
          return '<tr><td class="num">' + r.record_date + '</td>' + cells +
            '<td class="num" style="color:var(--color-text-secondary)">' + targetSummary(vals) + '</td>' +
            '<td class="row-actions"><button class="btn btn-sm btn-danger" data-act="del" data-date="' + r.record_date + '">删除</button></td></tr>';
        }).join('');
      }
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

  /* ---------- 4 组添加弹窗 ---------- */
  const GROUP_OPENERS = {
    basic: 'btnAddBasic',
    goal: 'btnAddGoal',
    girth: 'btnAddGirth',
    target: 'btnAddTarget',
  };
  const GROUP_FORMS = {
    basic: 'formBasic',
    goal: 'formGoal',
    girth: 'formGirth',
    target: 'formTarget',
  };
  const GROUP_MODALS = {
    basic: 'modalBasic',
    goal: 'modalGoal',
    girth: 'modalGirth',
    target: 'modalTarget',
  };

  Object.keys(GROUP_OPENERS).forEach(function (group) {
    document.getElementById(GROUP_OPENERS[group]).addEventListener('click', function () {
      const form = document.getElementById(GROUP_FORMS[group]);
      form.reset();
      form.record_date.value = App.todayStr();
      form.record_date.max = App.todayStr();
      // 占位提示：当前该维度最新值（服务端继承兜底，此处仅提示）
      App.api('/api/body-metrics/latest').then(function (snap) {
        (GROUPS[group] || []).forEach(function (key) {
          const el = form.elements[key];
          if (!el) return;
          const cur = snap[key] ? snap[key].value : null;
          el.placeholder = cur != null ? ('沿用 ' + cur) : '新增';
        });
        App.openModal(GROUP_MODALS[group]);
      }).catch(function (e) {
        App.toast(e.message, true);
        App.openModal(GROUP_MODALS[group]);
      });
    });
  });

  Object.keys(GROUP_FORMS).forEach(function (group) {
    document.getElementById(GROUP_FORMS[group]).addEventListener('submit', function (e) {
      e.preventDefault();
      const form = e.target;
      const values = {};
      (GROUPS[group] || []).forEach(function (k) {
        const el = form.elements[k];
        if (el && el.value !== '') values[k] = parseFloat(el.value);
      });
      if (!Object.keys(values).length) { App.toast('至少填写一个指标', true); return; }
      const payload = { record_date: form.record_date.value, values: values };
      App.api('/api/body-metrics/' + group, { method: 'POST', body: payload })
        .then(function () {
          App.closeModal(GROUP_MODALS[group]);
          App.toast('已保存（留空项已沿用最近数据）');
          setTimeout(function () { location.reload(); }, 400);
        })
        .catch(err => App.toast(err.message, true));
    });
  });

  /* ---------- 删除（按日期删 4 组） ---------- */
  document.getElementById('recBody').addEventListener('click', function (e) {
    const btn = e.target.closest('button[data-act]');
    if (!btn || btn.dataset.act !== 'del') return;
    const date = btn.dataset.date;
    if (!App.confirm('确定删除 ' + date + ' 的全部身材记录吗？')) return;
    App.api('/api/body-metrics?record_date=' + date, { method: 'DELETE' })
      .then(function () { App.toast('已删除'); setTimeout(function () { location.reload(); }, 400); })
      .catch(err => App.toast(err.message, true));
  });

  document.getElementById('recPagination').addEventListener('click', function (e) {
    const b = e.target.closest('button[data-pg]');
    if (b && !b.disabled) loadRecords(parseInt(b.dataset.pg, 10));
  });

  /* ---------- 指标/档位切换 ---------- */
  document.getElementById('metricSelect').addEventListener('change', function () {
    loadTrend(this.value, document.querySelector('#rangeSeg button.active').dataset.range);
  });
  document.getElementById('rangeSeg').addEventListener('click', function (e) {
    const b = e.target.closest('button'); if (!b) return;
    Array.prototype.forEach.call(this.children, c => c.classList.remove('active'));
    b.classList.add('active');
    loadTrend(document.getElementById('metricSelect').value, b.dataset.range);
  });

  /* 关闭按钮 */
  document.querySelectorAll('[data-close]').forEach(function (el) {
    el.addEventListener('click', function () { App.closeModal(el.dataset.close); });
  });

  /* ---------- Excel 导入 / 导出 ---------- */
  const importBtn = document.getElementById('btnImportExcel');
  const exportBtn = document.getElementById('btnExportExcel');
  const importForm = document.getElementById('formImport');
  const importFile = document.getElementById('importFile');
  const importSubmit = document.getElementById('importSubmit');
  const importCancel = document.getElementById('importCancel');
  const importDone = document.getElementById('importDone');
  const importResult = document.getElementById('importResult');
  let importImported = 0;   // 本次导入成功行数（决定关闭时是否刷新）

  // 打开导入弹窗：重置状态
  importBtn.addEventListener('click', function () {
    importForm.reset();
    importResult.style.display = 'none';
    importResult.innerHTML = '';
    importSubmit.disabled = false;
    importSubmit.textContent = '开始导入';
    importCancel.style.display = '';
    importDone.style.display = 'none';
    importImported = 0;
    App.openModal('modalImport');
  });

  // 导出：直接触发下载（同站 GET 自动携带会话）
  exportBtn.addEventListener('click', function () {
    window.location.href = '/api/body-metrics/export';
  });

  // 导入：multipart 上传（App.api 仅支持 JSON，此处原生 fetch，错误处理口径一致）
  importForm.addEventListener('submit', function (e) {
    e.preventDefault();
    const file = importFile.files[0];
    if (!file) { App.toast('请先选择 .xlsx 文件', true); return; }
    const fd = new FormData();
    fd.append('file', file);
    importSubmit.disabled = true;
    importSubmit.textContent = '导入中…';
    fetch('/api/body-metrics/import', { method: 'POST', body: fd })
      .then(function (res) {
        return res.json().catch(function () { return null; }).then(function (body) {
          if (res.status === 401) { location.href = '/login'; throw new Error('未登录'); }
          if (!res.ok) throw new Error((body && body.error) ? body.error : ('请求失败（' + res.status + '）'));
          return body;
        });
      })
      .then(function (data) { showImportResult(data); })
      .catch(function (err) {
        App.toast(err.message, true);
        importSubmit.disabled = false;
        importSubmit.textContent = '开始导入';
      });
  });

  // 导入结果：全部成功 → 关闭并刷新；存在失败 → 弹窗内展示明细，由「完成」按钮关闭并刷新
  function showImportResult(data) {
    const failed = data.failed || [];
    importImported = data.imported || 0;
    const ok = importImported > 0;
    let html = '<div class="summary">';
    if (!failed.length) {
      html += '<span class="ok">导入成功：' + importImported + ' 条记录已写入（留空列已沿用最近数据）</span>';
    } else {
      html += '<span class="fail">导入完成：' + importImported + ' 条成功，' + failed.length + ' 条失败已跳过</span>';
    }
    html += '</div>';
    if (failed.length) {
      html += '<div class="tbl-wrap"><table class="tbl"><thead><tr><th>工作表</th><th>行</th><th>列</th><th>原因</th></tr></thead><tbody>';
      failed.forEach(function (f) {
        html += '<tr><td>' + App.escapeHtml(f.sheet) + '</td><td class="num">' + f.row + '</td>' +
          '<td>' + App.escapeHtml(f.column || '—') + '</td><td>' + App.escapeHtml(f.reason) + '</td></tr>';
      });
      html += '</tbody></table></div>';
    }
    importResult.innerHTML = html;
    importResult.style.display = 'block';

    if (!failed.length) {
      App.toast('已导入 ' + importImported + ' 条记录');
      setTimeout(function () { location.reload(); }, 500);
    } else {
      importSubmit.disabled = true;
      importSubmit.textContent = '开始导入';
      importCancel.style.display = 'none';
      importDone.style.display = '';
      if (ok) App.toast('已导入 ' + importImported + ' 条，另有 ' + failed.length + ' 条失败');
      else App.toast('导入失败 ' + failed.length + ' 条，请修正后重试', true);
    }
  }

  // 「完成」：关闭弹窗；本次有成功写入则刷新记录列表
  importDone.addEventListener('click', function () {
    App.closeModal('modalImport');
    if (importImported > 0) setTimeout(function () { location.reload(); }, 200);
  });

  /* ---------- 初始化 ---------- */
  if (window.INIT_TREND) renderTrend(window.INIT_TREND);
  loadRecords(1);
  window.addEventListener('resize', function () { if (chart) chart.resize(); });
})();
