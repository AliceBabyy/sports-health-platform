/* 舞蹈记录页：当日视图（计划/记录两态 + 前后翻页）+ 分页表格、舞种筛选、新增/编辑弹窗
   2026-11 计划态字段化：弹窗入口即定状态（新增记录 / 新建计划），弹窗内无计划/记录切换；
   计划 = 舞种/星级/备注，完成后一键「去记录」补全实测。 */
(function () {
  const App = window.App;
  let currentPage = 1, editingId = null, filterType = null, formMode = 'recorded';
  const viewDate = window.INIT_DATE || App.todayStr();   // 当日视图日期（总览跳转 / 前后翻页）
  const qs = new URLSearchParams(location.search);
  const fromOv = qs.get('fromov') === '1';               // 是否从总览点日期格「＋ 计划」过来
  const dailyWrap = document.getElementById('danceDaily');

  const STAR_TEXT = ['', '★', '★★', '★★★', '★★★★', '★★★★★'];

  function fmtDur(sec) { return sec != null ? App.fmtClock(sec) : '—'; }
  function statusTag(r) {
    return '<span class="tag ' + (r.status === 'planned' ? 'tag-gray' : 'tag-mint') + ' no-dot">' + (r.status === 'planned' ? '计划' : '记录') + '</span>';
  }
  function remarkHtml(r) {
    return r.remark ? ' <span class="row-remark">' + App.escapeHtml(r.remark) + '</span>' : '';
  }

  /* ---------- 当日视图 ---------- */
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
            plans.map(function (r) {
              const meta = App.escapeHtml(r.dance_type || '舞蹈计划') + ' · ' + (r.stars ? STAR_TEXT[r.stars] : '—');
              return '<div class="daily-row" data-id="' + r.id + '">' +
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
              const meta = App.escapeHtml(r.dance_type || '—') + ' · ' + (r.stars ? STAR_TEXT[r.stars] : '—') + ' · ' + fmtDur(r.duration_s) +
                (r.style ? ' · ' + App.escapeHtml(r.style) : '') + (r.calories != null ? ' · ' + r.calories + ' kcal' : '');
              return '<div class="daily-row" data-id="' + r.id + '">' +
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
    if (btn.dataset.daily === 'todo') openForm(row, 'recorded');   // 计划 → 去记录（同一 id 转记录态）
    else openForm(row, row.status === 'planned' ? 'planned' : 'recorded');
  });

  /* ---------- 全部记录分页表格（计划行展示目标值） ---------- */
  function load(page) {
    currentPage = page || 1;
    let url = '/api/dance-records?page=' + currentPage + '&page_size=10';
    if (filterType) url += '&dance_type=' + encodeURIComponent(filterType);
    App.api(url).then(function (res) {
      const tbody = document.getElementById('danceBody');
      if (!res.list.length) {
        tbody.innerHTML = '<tr><td colspan="10"><div class="empty-state"><div class="icon">💃</div>暂无舞蹈数据，点击右上角「新增记录 / 新建计划」开始</div></td></tr>';
      } else {
        tbody.innerHTML = res.list.map(function (r) {
          const planned = r.status === 'planned';
          return '<tr>' +
            '<td class="num">' + r.record_date + '</td>' +
            '<td>' + statusTag(r) + '</td>' +
            '<td>' + App.escapeHtml(r.dance_type || '—') + '</td>' +
            '<td class="stars" title="' + (r.stars != null ? r.stars : 0) + ' 星">' + (r.stars != null ? STAR_TEXT[r.stars] : '—') + '</td>' +
            '<td>' + App.escapeHtml(r.style || '—') + '</td>' +
            '<td class="num">' + (planned ? '—' : fmtDur(r.duration_s)) + '</td>' +
            '<td class="num">' + (r.avg_heart_rate != null ? r.avg_heart_rate : '—') + '</td>' +
            '<td class="num">' + (r.max_heart_rate != null ? r.max_heart_rate : '—') + '</td>' +
            '<td class="num">' + (r.calories != null ? r.calories + ' kcal' : '—') + '</td>' +
            '<td class="row-actions"><button class="btn btn-sm" data-act="edit" data-id="' + r.id + '" data-row=\'' + JSON.stringify(r).replace(/'/g, "&#39;") + '\'>编辑</button>' +
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

  /* ---------- 弹窗：入口即定状态（无弹窗内切换） ---------- */
  function applyFormMode(mode) {
    formMode = mode;
    const f = document.getElementById('formDance');
    f.elements.dance_type.required = true;   // 计划/记录都需要舞种
    f.elements.stars.required = true;        // 计划/记录都需要星级
    f.elements.duration_min.required = mode === 'recorded';  // 仅记录态需时长
    document.getElementById('modalDanceDesc').textContent = mode === 'planned'
      ? '计划 = 舞种 / 星级 / 备注，完成后可一键「去记录」补全实测数据。'
      : '记下这节课的舞种、风格与强度，星级用于自评完成度。';
  }

  function openForm(row, mode) {
    editingId = row ? row.id : null;
    const m = mode || (row && row.status) || 'recorded';
    document.getElementById('modalDanceTitle').textContent = row
      ? (m === 'planned' ? '编辑舞蹈计划' : '编辑舞蹈记录')
      : (m === 'planned' ? '新建舞蹈计划' : '新增舞蹈记录');
    const form = document.getElementById('formDance');
    form.reset();
    form.record_date.value = row ? row.record_date : viewDate;
    form.record_date.max = '';
    applyFormMode(m);
    if (row) {
      form.elements.remark.value = row.remark || '';
      form.elements.dance_type.value = row.dance_type || '';
      form.elements.stars.value = row.stars != null ? row.stars : 4;
      form.elements.style.value = row.style || '';
      form.elements.duration_min.value = row.duration_s != null ? row.duration_s / 60 : '';
      form.elements.avg_heart_rate.value = row.avg_heart_rate != null ? row.avg_heart_rate : '';
      form.elements.max_heart_rate.value = row.max_heart_rate != null ? row.max_heart_rate : '';
      form.elements.calories.value = row.calories != null ? row.calories : '';
    }
    App.openModal('modalDance');
  }

  document.getElementById('btnAddDance').addEventListener('click', function () { openForm(null, 'recorded'); });
  document.getElementById('btnAddDancePlan').addEventListener('click', function () { openForm(null, 'planned'); });

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
    const payload = {
      record_date: form.record_date.value,
      status: planned ? 'planned' : 'recorded',
      dance_type: form.elements.dance_type.value.trim() || null,
      stars: form.elements.stars.value !== '' ? parseInt(form.elements.stars.value, 10) : null,
      remark: form.elements.remark.value.trim() || null,
      style: form.elements.style.value.trim() || null,
      duration_s: planned ? null : (form.elements.duration_min.value !== '' ? Math.round(parseFloat(form.elements.duration_min.value) * 60) : null),
      avg_heart_rate: planned ? null : (form.elements.avg_heart_rate.value !== '' ? parseInt(form.elements.avg_heart_rate.value, 10) : null),
      max_heart_rate: planned ? null : (form.elements.max_heart_rate.value !== '' ? parseInt(form.elements.max_heart_rate.value, 10) : null),
      calories: planned ? null : (form.elements.calories.value !== '' ? parseFloat(form.elements.calories.value) : null),
    };
    const req = editingId
      ? App.api('/api/dance-records/' + editingId, { method: 'PUT', body: payload })
      : App.api('/api/dance-records', { method: 'POST', body: payload });
    req.then(function () {
      App.closeModal('modalDance');
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

  /* ---------- 初始化：统计里的舞种分布 → 筛选 chips ---------- */
  fetch('/api/dance-records/stats').then(r => r.json()).then(function (s) {
    renderFilters(s.dance_types || []);
  }).catch(function () {});
  loadDaily();
  load(1);
  /* 从总览点日期格「＋ 计划」过来（?newplan=1）：自动弹出新建计划表单，日期已由 ?date= 带入 */
  if (qs.get('newplan') === '1') {
    openForm(null, 'planned');
    history.replaceState(null, '', location.pathname + '?date=' + viewDate);
  }
})();
