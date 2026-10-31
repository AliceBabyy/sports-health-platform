/* 舞蹈记录页：分页表格、舞种筛选 chips、新增/编辑弹窗（DA-01） */
(function () {
  const App = window.App;
  let currentPage = 1, editingId = null, filterType = null;

  const STAR_TEXT = ['', '★', '★★', '★★★', '★★★★', '★★★★★'];

  function load(page) {
    currentPage = page || 1;
    let url = '/api/dance-records?page=' + currentPage + '&page_size=10';
    if (filterType) url += '&dance_type=' + encodeURIComponent(filterType);
    App.api(url).then(function (res) {
      const tbody = document.getElementById('danceBody');
      if (!res.list.length) {
        tbody.innerHTML = '<tr><td colspan="9"><div class="empty-state"><div class="icon">💃</div>暂无舞蹈记录，点击右上角「新增记录」开始</div></td></tr>';
      } else {
        tbody.innerHTML = res.list.map(function (r) {
          return '<tr>' +
            '<td class="num">' + r.record_date + '</td>' +
            '<td>' + App.escapeHtml(r.dance_type) + '</td>' +
            '<td class="stars" title="' + r.stars + ' 星">' + STAR_TEXT[r.stars] + '</td>' +
            '<td>' + App.escapeHtml(r.style || '—') + '</td>' +
            '<td class="num">' + App.fmtClock(r.duration_s) + '</td>' +
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

  function openForm(row) {
    editingId = row ? row.id : null;
    document.getElementById('modalDanceTitle').textContent = row ? '编辑舞蹈记录' : '新增舞蹈记录';
    const form = document.getElementById('formDance');
    form.reset();
    form.record_date.value = row ? row.record_date : App.todayStr();
    form.record_date.max = App.todayStr();
    if (row) {
      form.elements.dance_type.value = row.dance_type;
      form.elements.stars.value = row.stars;
      form.elements.style.value = row.style || '';
      form.elements.duration_min.value = row.duration_s / 60;
      form.elements.avg_heart_rate.value = row.avg_heart_rate != null ? row.avg_heart_rate : '';
      form.elements.max_heart_rate.value = row.max_heart_rate != null ? row.max_heart_rate : '';
      form.elements.calories.value = row.calories != null ? row.calories : '';
    }
    App.openModal('modalDance');
  }

  document.getElementById('btnAddDance').addEventListener('click', function () { openForm(null); });

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
      if (!App.confirm('确定删除这条舞蹈记录吗？')) return;
      App.api('/api/dance-records/' + id, { method: 'DELETE' })
        .then(function () { App.toast('已删除'); setTimeout(function () { location.reload(); }, 400); })
        .catch(err => App.toast(err.message, true));
    } else {
      openForm(JSON.parse(btn.dataset.row));
    }
  });

  document.getElementById('dancePagination').addEventListener('click', function (e) {
    const b = e.target.closest('button[data-pg]');
    if (b && !b.disabled) load(parseInt(b.dataset.pg, 10));
  });

  document.getElementById('formDance').addEventListener('submit', function (e) {
    e.preventDefault();
    const form = e.target;
    const payload = {
      record_date: form.record_date.value,
      dance_type: form.elements.dance_type.value.trim(),
      stars: parseInt(form.elements.stars.value, 10),
      style: form.elements.style.value.trim() || null,
      duration_s: Math.round(parseFloat(form.elements.duration_min.value) * 60),
      avg_heart_rate: form.elements.avg_heart_rate.value !== '' ? parseInt(form.elements.avg_heart_rate.value, 10) : null,
      max_heart_rate: form.elements.max_heart_rate.value !== '' ? parseInt(form.elements.max_heart_rate.value, 10) : null,
      calories: form.elements.calories.value !== '' ? parseFloat(form.elements.calories.value) : null,
    };
    const req = editingId
      ? App.api('/api/dance-records/' + editingId, { method: 'PUT', body: payload })
      : App.api('/api/dance-records', { method: 'POST', body: payload });
    req.then(function () {
      App.closeModal('modalDance');
      App.toast('已保存');
      setTimeout(function () { location.reload(); }, 400);
    }).catch(err => App.toast(err.message, true));
  });

  document.querySelectorAll('[data-close]').forEach(function (el) {
    el.addEventListener('click', function () { App.closeModal(el.dataset.close); });
  });

  // 初始：统计里的舞种分布 → 筛选 chips
  fetch('/api/dance-records/stats').then(r => r.json()).then(function (s) {
    renderFilters(s.dance_types || []);
  }).catch(function () {});
  load(1);
})();
