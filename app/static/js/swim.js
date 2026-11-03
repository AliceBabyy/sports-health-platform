/* 游泳记录页：当日视图（计划/记录两态 + 前后翻页）+ 分页表格、泳姿筛选、新增/编辑弹窗
   2026-11 计划态字段化：弹窗入口即定状态（新增记录 / 新建计划），弹窗内无计划/记录切换；
   计划 = 目标距离/时长/主泳姿/备注，完成后一键「去记录」补全实测。 */
(function () {
  const App = window.App;
  let currentPage = 1, editingId = null, formMode = 'recorded';
  const viewDate = window.INIT_DATE || App.todayStr();   // 当日视图日期（总览跳转 / 前后翻页）
  const qs = new URLSearchParams(location.search);
  const fromOv = qs.get('fromov') === '1';               // 是否从总览点日期格「＋ 计划」过来
  const dailyWrap = document.getElementById('swimDaily');

  function fmtDur(sec) { return sec != null ? App.fmtClock(sec) : '—'; }
  function statusTag(r) {
    return '<span class="tag ' + (r.status === 'planned' ? 'tag-gray' : 'tag-mint') + ' no-dot">' + (r.status === 'planned' ? '计划' : '记录') + '</span>';
  }
  function remarkHtml(r) {
    return r.remark ? ' <span class="row-remark">' + App.escapeHtml(r.remark) + '</span>' : '';
  }

  /* ---------- 当日视图 ---------- */
  function loadDaily() {
    App.api('/api/swim-records/daily?date=' + viewDate).then(function (res) {
      const plans = res.list.filter(r => r.status === 'planned');
      const records = res.list.filter(r => r.status !== 'planned');
      let html = '';
      if (!res.list.length) {
        html = '<div class="empty-state" style="padding:14px 0"><div class="icon">🏊</div>这一天还没有游泳数据，可新建计划或记录。</div>';
      } else {
        if (plans.length) {
          html += '<div class="daily-block"><div class="daily-block-title">计划 <span class="num">' + plans.length + '</span></div>' +
            plans.map(function (r) {
              const meta = (r.distance_m != null ? r.distance_m + ' m' : '—') + ' · ' + fmtDur(r.duration_s) +
                (r.main_stroke_label ? ' · ' + App.escapeHtml(r.main_stroke_label) : '');
              return '<div class="daily-row is-planned" data-id="' + r.id + '">' +
                '<div class="daily-main">' + meta + remarkHtml(r) + '</div>' +
                '<div class="daily-actions">' +
                '<button class="btn btn-sm btn-primary" data-daily="todo" data-id="' + r.id + '" data-row=\'' + JSON.stringify(r).replace(/'/g, "&#39;") + '\'>去记录</button>' +
                '<button class="btn btn-sm" data-daily="edit" data-id="' + r.id + '" data-row=\'' + JSON.stringify(r).replace(/'/g, "&#39;") + '\'>编辑</button>' +
                '<button class="btn btn-sm btn-danger" data-daily="del" data-id="' + r.id + '">删除</button></div></div>';
            }).join('') + '</div>';
        }
        if (records.length) {
          html += '<div class="daily-block"><div class="daily-block-title">记录 <span class="num">' + records.length + '</span></div>' +
            records.map(function (r) {
              const meta = r.distance_m + ' m · ' + fmtDur(r.duration_s) + (r.pace != null ? ' · 配速 ' + r.pace + ' min/100m' : '') +
                (r.main_stroke_label ? ' · ' + App.escapeHtml(r.main_stroke_label) : '') + (r.calories != null ? ' · ' + r.calories + ' kcal' : '');
              return '<div class="daily-row is-recorded" data-id="' + r.id + '">' +
                '<div class="daily-main">' + meta + remarkHtml(r) + '</div>' +
                '<div class="daily-actions">' +
                '<button class="btn btn-sm" data-daily="edit" data-id="' + r.id + '" data-row=\'' + JSON.stringify(r).replace(/'/g, "&#39;") + '\'>编辑</button>' +
                '<button class="btn btn-sm btn-danger" data-daily="del" data-id="' + r.id + '">删除</button></div></div>';
            }).join('') + '</div>';
        }
      }
      dailyWrap.innerHTML = html;
    }).catch(e => App.toast(e.message, true));
  }

  dailyWrap.addEventListener('click', function (e) {
    const btn = e.target.closest('[data-daily]');
    if (!btn) return;
    const id = parseInt(btn.dataset.id, 10);
    if (btn.dataset.daily === 'del') {
      App.confirmDialog({ title: '删除', message: '确定删除这条游泳数据？删除后不可恢复。' })
        .then(function (ok) {
          if (!ok) return;
          App.api('/api/swim-records/' + id, { method: 'DELETE' })
            .then(function () { App.toast('已删除'); setTimeout(function () { location.reload(); }, 400); })
            .catch(err => App.toast(err.message, true));
        });
      return;
    }
    const row = JSON.parse(btn.dataset.row);
    if (btn.dataset.daily === 'todo') openForm(row, 'recorded');   // 计划 → 去记录（同一 id 转记录态）
    else openForm(row, row.status === 'planned' ? 'planned' : 'recorded');
  });

  /* ---------- 全部记录分页表格（计划行展示目标值） ---------- */
  function load(page) {
    currentPage = page || 1;
    App.api('/api/swim-records?page=' + currentPage + '&page_size=10').then(function (res) {
      const tbody = document.getElementById('swimBody');
      if (!res.list.length) {
        tbody.innerHTML = '<tr><td colspan="12"><div class="empty-state"><div class="icon">🏊</div>暂无游泳数据，点击右上角「新增记录 / 新建计划」开始</div></td></tr>';
      } else {
        tbody.innerHTML = res.list.map(function (r) {
          const planned = r.status === 'planned';
          return '<tr>' +
            '<td class="num">' + r.record_date + '</td>' +
            '<td>' + statusTag(r) + '</td>' +
            '<td class="num">' + (r.distance_m != null ? r.distance_m + ' m' : '—') + '</td>' +
            '<td class="num">' + fmtDur(r.duration_s) + '</td>' +
            '<td class="num">' + (planned ? '—' : (r.pace != null ? r.pace : '—')) + '</td>' +
            '<td class="num">' + (r.avg_heart_rate != null ? r.avg_heart_rate : '—') + '</td>' +
            '<td class="num">' + (r.total_strokes != null ? r.total_strokes : '—') + '</td>' +
            '<td>' + App.escapeHtml(r.main_stroke_label || '—') + '</td>' +
            '<td class="num">' + (r.laps != null ? r.laps : '—') + '</td>' +
            '<td class="num">' + (planned ? '—' : (r.avg_stroke_rate != null ? r.avg_stroke_rate : '—')) + '</td>' +
            '<td class="num">' + (r.calories != null ? r.calories + ' kcal' : '—') + '</td>' +
            '<td class="row-actions"><button class="btn btn-sm" data-act="edit" data-id="' + r.id + '" data-row=\'' + JSON.stringify(r).replace(/'/g, "&#39;") + '\'>编辑</button>' +
            '<button class="btn btn-sm btn-danger" data-act="del" data-id="' + r.id + '">删除</button></td></tr>';
        }).join('');
      }
      renderPagination(res);
    }).catch(e => App.toast(e.message, true));
  }

  function renderPagination(res) {
    const wrap = document.getElementById('swimPagination');
    if (res.pages <= 1) { wrap.innerHTML = ''; return; }
    let html = '<div class="pagination"><span>共 ' + res.total + ' 条 · 每页 ' + res.page_size + ' 条</span>';
    html += '<button class="btn btn-sm" data-pg="' + (res.page - 1) + '" ' + (res.page <= 1 ? 'disabled' : '') + '>上一页</button>';
    for (let p = 1; p <= res.pages; p++) html += '<button class="btn btn-sm ' + (p === res.page ? 'active' : '') + '" data-pg="' + p + '">' + p + '</button>';
    html += '<button class="btn btn-sm" data-pg="' + (res.page + 1) + '" ' + (res.page >= res.pages ? 'disabled' : '') + '>下一页</button></div>';
    wrap.innerHTML = html;
  }

  /* ---------- 弹窗：入口即定状态（无弹窗内切换） ---------- */
  function applyFormMode(mode) {
    formMode = mode;
    const f = document.getElementById('formSwim');
    f.elements.distance_m.required = true;                  // 计划/记录都需要距离
    f.elements.duration_min.required = (mode === 'recorded'); // 计划态时长非必填
    f.elements.main_stroke.required = false;                 // 主泳姿均非必填
    // 计划态隐藏：平均心率 / 总划水 / 趟数 / 平均划频 / 活动卡路里
    document.querySelectorAll('#formSwim .only-record').forEach(function (el) {
      el.style.display = mode === 'planned' ? 'none' : '';
    });
    document.getElementById('modalSwimDesc').textContent = mode === 'planned'
      ? '计划 = 目标距离（必填）；时长与主泳姿选填，完成后可一键「去记录」补全实测。'
      : '配速会根据距离与时长自动计算；平均划频可手填，留空则自动估算。';
  }

  function openForm(row, mode) {
    editingId = row ? row.id : null;
    const m = mode || (row && row.status) || 'recorded';
    document.getElementById('modalSwimTitle').textContent = row
      ? (m === 'planned' ? '编辑游泳计划' : '编辑游泳记录')
      : (m === 'planned' ? '新建游泳计划' : '新增游泳记录');
    const form = document.getElementById('formSwim');
    form.reset();
    form.record_date.value = row ? row.record_date : viewDate;
    form.record_date.max = '';
    applyFormMode(m);
    if (row) {
      form.elements.remark.value = row.remark || '';
      form.elements.distance_m.value = row.distance_m != null ? row.distance_m : '';
      form.elements.duration_min.value = row.duration_s != null ? row.duration_s / 60 : '';
      form.elements.main_stroke.value = row.main_stroke || '';
      form.elements.avg_heart_rate.value = row.avg_heart_rate != null ? row.avg_heart_rate : '';
      form.elements.total_strokes.value = row.total_strokes != null ? row.total_strokes : '';
      form.elements.laps.value = row.laps != null ? row.laps : '';
      form.elements.calories.value = row.calories != null ? row.calories : '';
      form.elements.avg_stroke_rate.value = row.avg_stroke_rate != null ? row.avg_stroke_rate : '';
    }
    App.openModal('modalSwim');
  }

  document.getElementById('btnAddSwim').addEventListener('click', function () { openForm(null, 'recorded'); });
  document.getElementById('btnAddSwimPlan').addEventListener('click', function () { openForm(null, 'planned'); });

  document.getElementById('swimBody').addEventListener('click', function (e) {
    const btn = e.target.closest('button[data-act]');
    if (!btn) return;
    const id = parseInt(btn.dataset.id, 10);
    if (btn.dataset.act === 'del') {
      App.confirmDialog({ title: '删除游泳数据', message: '确定删除这条游泳数据吗？删除后不可恢复。' })
        .then(function (ok) {
          if (!ok) return;
          App.api('/api/swim-records/' + id, { method: 'DELETE' })
            .then(function () { App.toast('已删除'); setTimeout(function () { location.reload(); }, 400); })
            .catch(err => App.toast(err.message, true));
        });
    } else {
      const row = JSON.parse(btn.dataset.row);
      openForm(row, row.status === 'planned' ? 'planned' : 'recorded');
    }
  });

  document.getElementById('swimPagination').addEventListener('click', function (e) {
    const b = e.target.closest('button[data-pg]');
    if (b && !b.disabled) load(parseInt(b.dataset.pg, 10));
  });

  document.getElementById('formSwim').addEventListener('submit', function (e) {
    e.preventDefault();
    const form = e.target;
    const planned = formMode === 'planned';
    const payload = {
      record_date: form.record_date.value,
      status: planned ? 'planned' : 'recorded',
      distance_m: form.elements.distance_m.value !== '' ? parseInt(form.elements.distance_m.value, 10) : null,
      duration_s: form.elements.duration_min.value !== '' ? Math.round(parseFloat(form.elements.duration_min.value) * 60) : null,
      main_stroke: form.elements.main_stroke.value || null,
      remark: form.elements.remark.value.trim() || null,
      avg_heart_rate: planned ? null : (form.elements.avg_heart_rate.value !== '' ? parseInt(form.elements.avg_heart_rate.value, 10) : null),
      total_strokes: planned ? null : (form.elements.total_strokes.value !== '' ? parseInt(form.elements.total_strokes.value, 10) : null),
      laps: planned ? null : (form.elements.laps.value !== '' ? parseInt(form.elements.laps.value, 10) : null),
      calories: planned ? null : (form.elements.calories.value !== '' ? parseFloat(form.elements.calories.value) : null),
      avg_stroke_rate: planned ? null : (form.elements.avg_stroke_rate.value !== '' ? parseFloat(form.elements.avg_stroke_rate.value) : null),
    };
    const req = editingId
      ? App.api('/api/swim-records/' + editingId, { method: 'PUT', body: payload })
      : App.api('/api/swim-records', { method: 'POST', body: payload });
    req.then(function () {
      App.closeModal('modalSwim');
      App.toast(planned ? '计划已保存' : '记录已保存');
      setTimeout(function () {
        // 从总览点日期格「＋ 计划」过来的：保存后跳回总览当天
        if (fromOv) {
          location.href = '/overview?date=' + viewDate + '&mode=week';
        } else {
          location.reload();
        }
      }, 400);
    }).catch(err => App.toast(err.message, true));
  });

  document.querySelectorAll('[data-close]').forEach(function (el) {
    el.addEventListener('click', function () { App.closeModal(el.dataset.close); });
  });

  /* ---------- 导入（Excel / JSON） ---------- */
  const importExcelBtn = document.getElementById('btnImportExcel');
  const importJsonBtn = document.getElementById('btnImportJson');
  const importForm = document.getElementById('formImport');
  const importFile = document.getElementById('importFile');
  const importJsonText = document.getElementById('importJsonText');
  const importExcelPane = document.getElementById('importExcelPane');
  const importJsonPane = document.getElementById('importJsonPane');
  const importSubmit = document.getElementById('importSubmit');
  const importCancel = document.getElementById('importCancel');
  const importDone = document.getElementById('importDone');
  const importResult = document.getElementById('importResult');
  let importMode = 'excel';
  let importCreated = 0;

  function resetImport() {
    importForm.reset();
    importJsonText.value = '';
    importResult.style.display = 'none';
    importResult.innerHTML = '';
    importSubmit.disabled = false;
    importSubmit.textContent = '开始导入';
    importCancel.style.display = '';
    importDone.style.display = 'none';
  }
  function openImport(mode) {
    resetImport();
    importMode = mode;
    importExcelPane.style.display = mode === 'excel' ? '' : 'none';
    importJsonPane.style.display = mode === 'json' ? '' : 'none';
    App.openModal('modalImport');
  }
  importExcelBtn.addEventListener('click', function () { openImport('excel'); });
  importJsonBtn.addEventListener('click', function () { openImport('json'); });

  function showImportResult(data) {
    const failed = data.failed || [];
    importCreated = data.imported || 0;
    let html = '<div class="summary">';
    if (!failed.length) {
      html += '<span class="ok">导入成功：' + importCreated + ' 条游泳记录已导入</span>';
    } else {
      html += '<span class="fail">导入完成：' + importCreated + ' 条成功，' + failed.length + ' 行失败已跳过</span>';
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
      App.toast('已导入 ' + importCreated + ' 条游泳记录');
      setTimeout(function () { location.reload(); }, 500);
    } else {
      importSubmit.disabled = true;
      importSubmit.textContent = '开始导入';
      importCancel.style.display = 'none';
      importDone.style.display = '';
      if (importCreated > 0) App.toast('已导入 ' + importCreated + ' 条，另有 ' + failed.length + ' 行失败');
      else App.toast('导入失败 ' + failed.length + ' 行，请修正后重试', true);
    }
  }

  importForm.addEventListener('submit', function (e) {
    e.preventDefault();
    if (importMode === 'json') {
      let body;
      try { body = JSON.parse(importJsonText.value); }
      catch (err) { App.toast('JSON 格式不正确：' + err.message, true); return; }
      if (!body || !Array.isArray(body.records) || !body.records.length) { App.toast('需包含非空 records 数组', true); return; }
      importSubmit.disabled = true;
      importSubmit.textContent = '导入中…';
      App.api('/api/swim-records/import-json', { method: 'POST', body: body })
        .then(function (data) { showImportResult(data); })
        .catch(function (err) {
          App.toast(err.message, true);
          importSubmit.disabled = false;
          importSubmit.textContent = '开始导入';
        });
      return;
    }
    const file = importFile.files[0];
    if (!file) { App.toast('请先选择 .xlsx 文件', true); return; }
    const fd = new FormData();
    fd.append('file', file);
    importSubmit.disabled = true;
    importSubmit.textContent = '导入中…';
    fetch('/api/swim-records/import', { method: 'POST', body: fd })
      .then(function (res) {
        return res.json().catch(function () { return null; }).then(function (body) {
          if (!res.ok || !body) throw new Error((body && body.detail) || '导入失败');
          showImportResult(body);
        });
      })
      .catch(function (err) {
        App.toast(err.message, true);
        importSubmit.disabled = false;
        importSubmit.textContent = '开始导入';
      });
  });

  importDone.addEventListener('click', function () {
    App.closeModal('modalImport');
    if (importCreated > 0) setTimeout(function () { location.reload(); }, 200);
  });

  /* ---------- 初始化 ---------- */
  loadDaily();
  load(1);
  /* 从总览点日期格「＋ 计划」过来（?newplan=1）：自动弹出新建计划表单，日期已由 ?date= 带入 */
  if (qs.get('newplan') === '1') {
    openForm(null, 'planned');
    history.replaceState(null, '', location.pathname + '?date=' + viewDate);
  }
})();
