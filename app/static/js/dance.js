/* 舞蹈记录页：当日视图 + 分页表格、舞种筛选、新增/编辑弹窗、Excel/JSON 导入
   2026-11-04 整改：起止时间（datetime）+ 舞蹈老师；时长自动由起止时间推导；聚合舞蹈档案卡片。 */
(function () {
  const App = window.App;
  let currentPage = 1, editingId = null, filterType = null, formMode = 'recorded';
  let editingWasRecorded = false;   // 打开编辑弹窗时原行是否已是记录态（决定保存后是否弹庆祝）
  let noteTargetId = null;          // 心得弹窗当前编辑的舞蹈记录 id
  let starGetRating = null, starGetVideo = null;  // 心得弹窗两个星级取值器
  let editNoteStars = null, editNoteVideo = null; // 编辑弹窗内心得星级取值器（编辑记录态才有）
  let durationManual = false;   // 用户是否手动改过运动时长（改过则不再自动覆盖）
  const viewDate = window.INIT_DATE || App.todayStr();
  const qs = new URLSearchParams(location.search);
  const fromOv = qs.get('fromov') === '1';
  const dailyWrap = document.getElementById('danceDaily');

  const STAR_TEXT = ['', '★', '★★', '★★★', '★★★★', '★★★★★'];

  function fmtDur(sec) { return sec != null ? App.fmtClock(sec) : '—'; }
  function statusTag(r) {
    return '<span class="tag ' + (r.status === 'planned' ? 'tag-gray' : 'tag-mint') + ' no-dot">' + (r.status === 'planned' ? '计划' : '记录') + '</span>';
  }
  // ISO datetime → "HH:MM"
  function toTimeStr(iso) {
    if (!iso) return '';
    return iso.substring(11, 16);
  }
  // 行的时间区间展示
  function timeRange(r) {
    const s = toTimeStr(r.start_time), e = toTimeStr(r.end_time);
    if (s && e) return s + '–' + e;
    if (s) return s;
    return '—';
  }

  /* ---------- 当日视图（表格化：计划/记录分块，列对齐） ---------- */
  function danceDailyButtons(r) {
    const rowAttr = 'data-row=\'' + JSON.stringify(r).replace(/'/g, "&#39;") + '\'';
    const del = '<button class="btn btn-sm btn-danger" data-daily="del" data-id="' + r.id + '">删除</button>';
    const edit = '<button class="btn btn-sm" data-daily="edit" data-id="' + r.id + '" ' + rowAttr + '>编辑</button>';
    if (r.status === 'planned') {
      return '<td class="row-actions"><button class="btn btn-sm btn-primary" data-daily="todo" data-id="' + r.id + '" ' + rowAttr + '>去记录</button>' + edit + del + '</td>';
    }
    return '<td class="row-actions">' + edit + del + '</td>';
  }
  function starsHtml(r) {
    return r.stars != null ? '<span class="stars" title="' + r.stars + ' 星">' + STAR_TEXT[r.stars] + '</span>' : '—';
  }
  function loadDaily() {
    App.api('/api/dance-records/daily?date=' + viewDate).then(function (res) {
      const plans = res.list.filter(r => r.status === 'planned');
      const records = res.list.filter(r => r.status !== 'planned');
      let html = '';
      if (!res.list.length) {
        html = '<div class="empty-state" style="padding:14px 0"><div class="icon">💃</div>这一天还没有舞蹈数据，可新建计划或记录。</div>';
      } else {
        if (plans.length) {
          html += '<div class="daily-block"><div class="daily-block-title">计划 <span class="num">' + plans.length + '</span></div>' +
            '<table class="tbl"><thead><tr><th>舞种</th><th>星级</th><th>时段</th><th>备注</th><th></th></tr></thead><tbody>' +
            plans.map(function (r) {
              return '<tr>' +
                '<td>' + App.escapeHtml(r.dance_type || '舞蹈计划') + '</td>' +
                '<td>' + starsHtml(r) + '</td>' +
                '<td class="num">' + (r.start_time ? timeRange(r) : '—') + '</td>' +
                '<td class="cell-remark">' + (r.remark ? '<span class="row-remark">' + App.escapeHtml(r.remark) + '</span>' : '—') + '</td>' +
                danceDailyButtons(r) + '</tr>';
            }).join('') + '</tbody></table></div>';
        }
        if (records.length) {
          html += '<div class="daily-block"><div class="daily-block-title">记录 <span class="num">' + records.length + '</span></div>' +
            '<table class="tbl"><thead><tr><th>舞种</th><th>星级</th><th>时段</th><th class="num">时长</th><th>风格</th><th class="num">热量</th><th>备注</th><th></th></tr></thead><tbody>' +
            records.map(function (r) {
              return '<tr>' +
                '<td>' + App.escapeHtml(r.dance_type || '—') + '</td>' +
                '<td>' + starsHtml(r) + '</td>' +
                '<td class="num">' + timeRange(r) + '</td>' +
                '<td class="num">' + fmtDur(r.duration_s) + '</td>' +
                '<td>' + App.escapeHtml(r.style || '—') + '</td>' +
                '<td class="num">' + (r.calories != null ? r.calories + ' kcal' : '—') + '</td>' +
                '<td class="cell-remark">' + (r.remark ? '<span class="row-remark">' + App.escapeHtml(r.remark) + '</span>' : '—') + '</td>' +
                danceDailyButtons(r) + '</tr>';
            }).join('') + '</tbody></table></div>';
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
      App.confirmDialog({ title: '删除', message: '确定删除这条舞蹈数据？删除后不可恢复。' })
        .then(function (ok) {
          if (!ok) return;
          App.api('/api/dance-records/' + id, { method: 'DELETE' })
            .then(function () { App.toast('已删除'); setTimeout(function () { location.reload(); }, 400); })
            .catch(err => App.toast(err.message, true));
        });
      return;
    }
    const row = JSON.parse(btn.dataset.row);
    if (btn.dataset.daily === 'todo') openForm(row, 'recorded');
    else openForm(row, row.status === 'planned' ? 'planned' : 'recorded');
  });

  /* ---------- 全部记录分页表格 ---------- */
  function load(page) {
    currentPage = page || 1;
    let url = '/api/dance-records?page=' + currentPage + '&page_size=10';
    if (filterType) url += '&dance_type=' + encodeURIComponent(filterType);
    App.api(url).then(function (res) {
      const tbody = document.getElementById('danceBody');
      if (!res.list.length) {
        tbody.innerHTML = '<tr><td colspan="12"><div class="empty-state"><div class="icon">💃</div>暂无舞蹈数据，点击右上角「新增记录 / 新建计划」开始</div></td></tr>';
      } else {
        tbody.innerHTML = res.list.map(function (r) {
          const planned = r.status === 'planned';
          return '<tr>' +
            '<td class="num">' + r.record_date + '</td>' +
            '<td class="num">' + (planned ? '—' : timeRange(r)) + '</td>' +
            '<td>' + statusTag(r) + '</td>' +
            '<td>' + App.escapeHtml(r.dance_type || '—') + '</td>' +
            '<td>' + App.escapeHtml(r.teacher || '—') + '</td>' +
            '<td class="stars" title="' + (r.stars != null ? r.stars : 0) + ' 星">' + (r.stars != null ? STAR_TEXT[r.stars] : '—') + '</td>' +
            '<td>' + App.escapeHtml(r.style || '—') + '</td>' +
            '<td class="num">' + (planned ? '—' : fmtDur(r.duration_s)) + '</td>' +
            '<td class="num">' + (r.avg_heart_rate != null ? r.avg_heart_rate : '—') + '</td>' +
            '<td class="num">' + (r.max_heart_rate != null ? r.max_heart_rate : '—') + '</td>' +
            '<td class="num">' + (r.calories != null ? r.calories + ' kcal' : '—') + '</td>' +
            '<td class="row-actions"><button class="btn btn-sm" data-act="view" data-id="' + r.id + '" data-row=\'' + JSON.stringify(r).replace(/'/g, "&#39;") + '\'>查看详情</button>' +
            '<button class="btn btn-sm" data-act="edit" data-id="' + r.id + '" data-row=\'' + JSON.stringify(r).replace(/'/g, "&#39;") + '\'>编辑</button>' +
            '<button class="btn btn-sm btn-danger" data-act="del" data-id="' + r.id + '">删除</button></td></tr>';
        }).join('');
      }
      renderPagination(res);
    }).catch(e => App.toast(e.message, true));
  }

  function renderPagination(res) {
    const wrap = document.getElementById('dancePagination');
    if (res.pages <= 1) { wrap.innerHTML = ''; return; }
    let html = '<div class="pagination"><span>共 ' + res.total + ' 条 · 每页 ' + res.page_size + ' 条</span>';
    html += '<button class="btn btn-sm" data-pg="' + (res.page - 1) + '" ' + (res.page <= 1 ? 'disabled' : '') + '>上一页</button>';
    for (let p = 1; p <= res.pages; p++) html += '<button class="btn btn-sm ' + (p === res.page ? 'active' : '') + '" data-pg="' + p + '">' + p + '</button>';
    html += '<button class="btn btn-sm" data-pg="' + (res.page + 1) + '" ' + (res.page >= res.pages ? 'disabled' : '') + '>下一页</button></div>';
    wrap.innerHTML = html;
  }

  function renderFilters(types) {
    const wrap = document.getElementById('danceFilters');
    const chips = types.map(t => '<span class="chip" data-type="' + App.escapeHtml(t[0]) + '">' + App.escapeHtml(t[0]) + '</span>').join('');
    wrap.innerHTML = '<span class="chip ' + (filterType === null ? 'active' : '') + '" data-type="">全部</span>' + chips;
  }

  /* ---------- 弹窗 ---------- */
  function applyFormMode(mode) {
    formMode = mode;
    const f = document.getElementById('formDance');
    f.elements.dance_type.required = true;
    f.elements.stars.required = true;
    document.body.classList.toggle('dance-mode-recorded', mode === 'recorded');
    document.getElementById('modalDanceDesc').textContent = mode === 'planned'
      ? '计划 = 日期/时间/舞种/星级/老师/备注，完成后可一键「去记录」补全实测数据。'
      : '记下这节课的舞种、老师与强度，星级用于自评完成度。';
  }

  // 起止时间变化 → 自动计算运动时长（分钟），用户手动改过则不覆盖
  function autoCalcDuration() {
    if (durationManual) return;
    const f = document.getElementById('formDance');
    const s = f.elements.start_tm.value, e = f.elements.end_tm.value;
    if (s && e) {
      const [sh, sm] = s.split(':').map(Number);
      const [eh, em] = e.split(':').map(Number);
      const diffMin = (eh * 60 + em) - (sh * 60 + sm);
      if (diffMin > 0) f.elements.duration_min.value = Math.round(diffMin * 10) / 10;
    }
  }

  function openForm(row, mode) {
    editingId = row ? row.id : null;
    editingWasRecorded = row ? row.status === 'recorded' : false;
    const m = mode || (row && row.status) || 'recorded';
    document.getElementById('modalDanceTitle').textContent = row
      ? (m === 'planned' ? '编辑舞蹈计划' : '编辑舞蹈记录')
      : (m === 'planned' ? '新建舞蹈计划' : '新增舞蹈记录');
    const form = document.getElementById('formDance');
    form.reset();
    durationManual = false;
    form.record_date.value = row ? row.record_date : viewDate;
    applyFormMode(m);
    if (row) {
      form.elements.remark.value = row.remark || '';
      form.elements.dance_type.value = row.dance_type || '';
      form.elements.stars.value = row.stars != null ? row.stars : 4;
      form.elements.teacher.value = row.teacher || '';
      form.elements.style.value = row.style || '';
      form.elements.start_tm.value = toTimeStr(row.start_time);
      form.elements.end_tm.value = toTimeStr(row.end_time);
      form.elements.duration_min.value = row.duration_s != null ? row.duration_s / 60 : '';
      form.elements.avg_heart_rate.value = row.avg_heart_rate != null ? row.avg_heart_rate : '';
      form.elements.max_heart_rate.value = row.max_heart_rate != null ? row.max_heart_rate : '';
      form.elements.calories.value = row.calories != null ? row.calories : '';
    }
    // 编辑「记录态」时：编辑弹窗内联展示心得区块（即使没填也显示）；计划态隐藏
    const noteSec = document.getElementById('danceEditNoteSection');
    const showNoteSec = !!row && m === 'recorded';
    noteSec.style.display = showNoteSec ? '' : 'none';
    editNoteStars = null; editNoteVideo = null;
    if (showNoteSec) {
      const n = row.note || {};
      document.getElementById('danceEditInsight').value = n.insight || '';
      const sb = document.getElementById('danceEditStars');
      const vb = document.getElementById('danceEditVideo');
      sb.innerHTML = App.starWidgetHtml(n.rating || 0);
      vb.innerHTML = App.starWidgetHtml(n.video_effect || 0);
      editNoteStars = App.bindStars(sb, n.rating || 0);
      editNoteVideo = App.bindStars(vb, n.video_effect || 0);
    }
    App.openModal('modalDance');
  }

  document.getElementById('btnAddDance').addEventListener('click', function () { openForm(null, 'recorded'); });
  document.getElementById('btnAddDancePlan').addEventListener('click', function () { openForm(null, 'planned'); });

  // 起止时间联动自动算时长
  document.getElementById('formDance').elements.start_tm.addEventListener('change', autoCalcDuration);
  document.getElementById('formDance').elements.end_tm.addEventListener('change', autoCalcDuration);
  document.getElementById('formDance').elements.duration_min.addEventListener('input', function () {
    durationManual = this.value !== '';
  });

  document.getElementById('danceFilters').addEventListener('click', function (e) {
    const c = e.target.closest('.chip');
    if (!c) return;
    filterType = c.dataset.type || null;
    Array.prototype.forEach.call(this.children, el => el.classList.remove('active'));
    c.classList.add('active');
    load(1);
  });

  document.getElementById('danceBody').addEventListener('click', function (e) {
    const btn = e.target.closest('button[data-act]');
    if (!btn) return;
    const id = parseInt(btn.dataset.id, 10);
    if (btn.dataset.act === 'view') {
      App.openDetail('dance', JSON.parse(btn.dataset.row));
      return;
    }
    if (btn.dataset.act === 'del') {
      App.confirmDialog({ title: '删除舞蹈数据', message: '确定删除这条舞蹈数据吗？删除后不可恢复。' })
        .then(function (ok) {
          if (!ok) return;
          App.api('/api/dance-records/' + id, { method: 'DELETE' })
            .then(function () { App.toast('已删除'); setTimeout(function () { location.reload(); }, 400); })
            .catch(err => App.toast(err.message, true));
        });
    } else {
      const row = JSON.parse(btn.dataset.row);
      openForm(row, row.status === 'planned' ? 'planned' : 'recorded');
    }
  });

  document.getElementById('dancePagination').addEventListener('click', function (e) {
    const b = e.target.closest('button[data-pg]');
    if (b && !b.disabled) load(parseInt(b.dataset.pg, 10));
  });

  document.getElementById('formDance').addEventListener('submit', function (e) {
    e.preventDefault();
    const form = e.target;
    const planned = formMode === 'planned';
    const dateStr = form.record_date.value;
    const sTm = form.elements.start_tm.value;
    const eTm = form.elements.end_tm.value;
    const payload = {
      record_date: dateStr,
      start_time: (dateStr && sTm) ? (dateStr + 'T' + sTm + ':00') : null,
      end_time: (dateStr && eTm) ? (dateStr + 'T' + eTm + ':00') : null,
      status: planned ? 'planned' : 'recorded',
      dance_type: form.elements.dance_type.value.trim() || null,
      stars: form.elements.stars.value !== '' ? parseInt(form.elements.stars.value, 10) : null,
      teacher: form.elements.teacher.value.trim() || null,
      remark: form.elements.remark.value.trim() || null,
      style: planned ? null : (form.elements.style.value.trim() || null),
      duration_s: planned ? null : (form.elements.duration_min.value !== '' ? Math.round(parseFloat(form.elements.duration_min.value) * 60) : null),
      avg_heart_rate: planned ? null : (form.elements.avg_heart_rate.value !== '' ? parseInt(form.elements.avg_heart_rate.value, 10) : null),
      max_heart_rate: planned ? null : (form.elements.max_heart_rate.value !== '' ? parseInt(form.elements.max_heart_rate.value, 10) : null),
      calories: planned ? null : (form.elements.calories.value !== '' ? parseFloat(form.elements.calories.value) : null),
    };
    const req = editingId
      ? App.api('/api/dance-records/' + editingId, { method: 'PUT', body: payload })
      : App.api('/api/dance-records', { method: 'POST', body: payload });
    req.then(function (saved) {
      App.closeModal('modalDance');
      const freshRecorded = !planned && !editingWasRecorded;  // 新建记录 / 计划→记录：算一次训练完成
      const editingNote = editingId && !planned && editingWasRecorded;  // 编辑已有记录：顺带保存心得
      function after() {
        if (fromOv) location.href = '/overview?date=' + viewDate + '&mode=week';
        else location.reload();
      }
      function saveNoteThen(cb) {
        App.api('/api/dance-records/' + editingId + '/note', {
          method: 'PUT',
          body: {
            rating: (editNoteStars && editNoteStars() > 0) ? editNoteStars() : null,
            video_effect: (editNoteVideo && editNoteVideo() > 0) ? editNoteVideo() : null,
            insight: document.getElementById('danceEditInsight').value.trim() || null,
          },
        }).then(cb).catch(function (err) { App.toast('心得保存失败：' + err.message, true); cb(); });
      }
      if (freshRecorded && saved && saved.id) {
        App.toast('记录已保存');
        App.celebrate({
          showNote: true,
          onNote: function () { openDanceNote(saved.id, saved.note); },
          onClose: after,
        });
      } else if (editingNote) {
        App.toast('记录已保存');
        saveNoteThen(function () { setTimeout(after, 400); });
      } else {
        App.toast(planned ? '计划已保存' : '记录已保存');
        setTimeout(after, 400);
      }
    }).catch(err => App.toast(err.message, true));
  });

  /* ---------- 练后心得弹窗（2026-11） ---------- */
  function openDanceNote(recordId, existing) {
    noteTargetId = recordId;
    document.getElementById('danceNoteInsight').value = (existing && existing.insight) || '';
    const starBox = document.getElementById('danceNoteStars');
    const videoBox = document.getElementById('danceNoteVideo');
    starBox.innerHTML = App.starWidgetHtml(existing ? existing.rating : 0);
    videoBox.innerHTML = App.starWidgetHtml(existing ? existing.video_effect : 0);
    starGetRating = App.bindStars(starBox, existing ? existing.rating || 0 : 0);
    starGetVideo = App.bindStars(videoBox, existing ? existing.video_effect || 0 : 0);
    App.openModal('modalDanceNote');
  }
  document.getElementById('formDanceNote').addEventListener('submit', function (e) {
    e.preventDefault();
    App.api('/api/dance-records/' + noteTargetId + '/note', {
      method: 'PUT',
      body: {
        rating: (starGetRating && starGetRating() > 0) ? starGetRating() : null,
        video_effect: (starGetVideo && starGetVideo() > 0) ? starGetVideo() : null,
        insight: document.getElementById('danceNoteInsight').value.trim() || null,
      },
    }).then(function () {
      App.closeModal('modalDanceNote');
      App.toast('心得已保存');
      setTimeout(function () { location.reload(); }, 400);
    }).catch(err => App.toast(err.message, true));
  });
  // 心得弹窗「取消」也要刷新：庆祝链路刚新建了记录，列表需要看到新行
  document.querySelector('#modalDanceNote [data-close]').addEventListener('click', function () {
    setTimeout(function () { location.reload(); }, 200);
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

  function openImport(mode) {
    importMode = mode;
    importForm.reset();
    importJsonText.value = '';
    importResult.style.display = 'none';
    importResult.innerHTML = '';
    importSubmit.disabled = false;
    importSubmit.textContent = '开始导入';
    importCancel.style.display = '';
    importDone.style.display = 'none';
    importCreated = 0;
    importExcelPane.style.display = mode === 'excel' ? '' : 'none';
    importJsonPane.style.display = mode === 'json' ? '' : 'none';
    App.openModal('modalImport');
  }
  importExcelBtn.addEventListener('click', function () { openImport('excel'); });
  importJsonBtn.addEventListener('click', function () { openImport('json'); });

  importForm.addEventListener('submit', function (e) {
    e.preventDefault();
    if (importMode === 'json') {
      let body;
      try { body = JSON.parse(importJsonText.value); }
      catch (err) { App.toast('JSON 格式错误：' + err.message, true); return; }
      importSubmit.disabled = true;
      importSubmit.textContent = '导入中…';
      App.api('/api/dance-records/import-json', { method: 'POST', body: body })
        .then(function (data) { showImportResult(data); })
        .catch(function (err) {
          App.toast(err.message, true);
          importSubmit.disabled = false;
          importSubmit.textContent = '开始导入';
        });
    } else {
      const file = importFile.files[0];
      if (!file) { App.toast('请先选择 .xlsx 文件', true); return; }
      const fd = new FormData();
      fd.append('file', file);
      importSubmit.disabled = true;
      importSubmit.textContent = '导入中…';
      fetch('/api/dance-records/import', { method: 'POST', body: fd })
        .then(function (res) {
          return res.json().catch(function () { return null; }).then(function (body) {
            if (!res.ok) throw new Error((body && body.message) || ('HTTP ' + res.status));
            return body;
          });
        })
        .then(function (data) { showImportResult(data); })
        .catch(function (err) {
          App.toast(err.message, true);
          importSubmit.disabled = false;
          importSubmit.textContent = '开始导入';
        });
    }
  });

  function showImportResult(data) {
    importCreated = data.imported || 0;
    const failed = data.failed || [];
    const ok = importCreated > 0;
    let html = '';
    if (ok && !failed.length) {
      html += '<div class="ok">导入成功：' + importCreated + ' 条舞蹈记录已导入</div>';
    } else {
      html += '<div class="fail">导入完成：' + importCreated + ' 条成功，' + failed.length + ' 行失败已跳过</div>';
    }
    if (failed.length) {
      html += '<ul class="fail-list">';
      failed.slice(0, 50).forEach(function (f) {
        html += '<li>第 ' + f.row + ' 行 · ' + App.escapeHtml(f.column || '') + '：' + App.escapeHtml(f.reason || '') + '</li>';
      });
      if (failed.length > 50) html += '<li>…其余 ' + (failed.length - 50) + ' 条省略</li>';
      html += '</ul>';
    }
    importResult.innerHTML = html;
    importResult.style.display = 'block';
    if (ok && !failed.length) {
      // 导入全部成功：弹庆祝；恰好 1 条 → 可顺手写心得；多条 → 只庆祝
      const ids = data.created_ids || [];
      App.toast('已导入 ' + importCreated + ' 条记录');
      App.closeModal('modalImport');
      App.celebrate({
        showNote: importCreated === 1 && ids.length === 1,
        onNote: function () { openDanceNote(ids[0], null); },
        onClose: function () { location.reload(); },
      });
    } else {
      importSubmit.disabled = true;
      importSubmit.textContent = '开始导入';
      importCancel.style.display = 'none';
      importDone.style.display = '';
      if (ok) App.toast('已导入 ' + importCreated + ' 条记录，另有 ' + failed.length + ' 行失败');
      else App.toast('导入失败 ' + failed.length + ' 行，请修正后重试', true);
    }
  }

  importDone.addEventListener('click', function () {
    App.closeModal('modalImport');
    if (importCreated > 0) setTimeout(function () { location.reload(); }, 200);
  });

  document.querySelectorAll('[data-close]').forEach(function (el) {
    el.addEventListener('click', function () { App.closeModal(el.dataset.close); });
  });

  /* ---------- 初始化 ---------- */
  fetch('/api/dance-records/stats').then(r => r.json()).then(function (s) {
    renderFilters(s.dance_types || []);
  }).catch(function () {});
  loadDaily();
  load(1);
  if (qs.get('newplan') === '1') {
    openForm(null, 'planned');
    history.replaceState(null, '', location.pathname + '?date=' + viewDate);
  }
})();
