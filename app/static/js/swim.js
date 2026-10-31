/* 游泳记录页：分页表格、新增/编辑弹窗（配速/划频只读自动，SW-02） */
(function () {
  const App = window.App;
  let currentPage = 1, editingId = null;

  function load(page) {
    currentPage = page || 1;
    App.api('/api/swim-records?page=' + currentPage + '&page_size=5').then(function (res) {
      const tbody = document.getElementById('swimBody');
      if (!res.list.length) {
        tbody.innerHTML = '<tr><td colspan="11"><div class="empty-state"><div class="icon">🏊</div>暂无游泳记录，点击右上角「新增记录」开始</div></td></tr>';
      } else {
        tbody.innerHTML = res.list.map(function (r) {
          return '<tr>' +
            '<td class="num">' + r.record_date + '</td>' +
            '<td class="num">' + r.distance_m + ' m</td>' +
            '<td class="num">' + App.fmtClock(r.duration_s) + '</td>' +
            '<td class="num">' + App.fmtPace(r.pace) + '</td>' +
            '<td class="num">' + (r.avg_heart_rate != null ? r.avg_heart_rate : '—') + '</td>' +
            '<td class="num">' + (r.total_strokes != null ? r.total_strokes : '—') + '</td>' +
            '<td>' + App.escapeHtml(r.main_stroke_label) + '</td>' +
            '<td class="num">' + (r.laps != null ? r.laps : '—') + '</td>' +
            '<td class="num">' + (r.avg_stroke_rate != null ? r.avg_stroke_rate + ' 次/分' : '—') + '</td>' +
            '<td class="num">' + (r.calories != null ? r.calories : '—') + '</td>' +
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

  function refreshStrokePreview(form) {
    const d = parseFloat(form.elements.distance_m.value) || 0;
    const m = parseFloat(form.elements.duration_min.value) || 0;
    const s = parseFloat(form.elements.total_strokes.value) || 0;
    const durSec = m * 60;
    const pace = d > 0 && durSec > 0 ? (durSec / d * 100 / 60) : null;
    const rate = durSec > 0 && s > 0 ? (s / (durSec / 60)) : null;
    form.elements.avg_stroke_rate.value = rate != null ? rate.toFixed(1) : '';
  }

  function openForm(row) {
    editingId = row ? row.id : null;
    document.getElementById('modalSwimTitle').textContent = row ? '编辑游泳记录' : '新增游泳记录';
    const form = document.getElementById('formSwim');
    form.reset();
    form.record_date.value = row ? row.record_date : App.todayStr();
    form.record_date.max = App.todayStr();
    if (row) {
      form.elements.distance_m.value = row.distance_m;
      form.elements.duration_min.value = row.duration_s / 60;
      form.elements.avg_heart_rate.value = row.avg_heart_rate != null ? row.avg_heart_rate : '';
      form.elements.total_strokes.value = row.total_strokes != null ? row.total_strokes : '';
      form.elements.main_stroke.value = row.main_stroke;
      form.elements.laps.value = row.laps != null ? row.laps : '';
      form.elements.calories.value = row.calories != null ? row.calories : '';
    }
    refreshStrokePreview(form);
    App.openModal('modalSwim');
  }

  document.getElementById('btnAddSwim').addEventListener('click', function () { openForm(null); });

  document.getElementById('swimBody').addEventListener('click', function (e) {
    const btn = e.target.closest('button[data-act]');
    if (!btn) return;
    const id = parseInt(btn.dataset.id, 10);
    if (btn.dataset.act === 'del') {
      if (!App.confirm('确定删除这条游泳记录吗？')) return;
      App.api('/api/swim-records/' + id, { method: 'DELETE' })
        .then(function () { App.toast('已删除'); setTimeout(function () { location.reload(); }, 400); })
        .catch(err => App.toast(err.message, true));
    } else {
      const row = JSON.parse(btn.dataset.row);
      openForm(row);
    }
  });

  document.getElementById('swimPagination').addEventListener('click', function (e) {
    const b = e.target.closest('button[data-pg]');
    if (b && !b.disabled) load(parseInt(b.dataset.pg, 10));
  });

  document.getElementById('formSwim').addEventListener('input', function (e) {
    if (['distance_m', 'duration_min', 'total_strokes'].includes(e.target.name)) refreshStrokePreview(e.target.form);
  });

  document.getElementById('formSwim').addEventListener('submit', function (e) {
    e.preventDefault();
    const form = e.target;
    const payload = {
      record_date: form.record_date.value,
      distance_m: parseInt(form.elements.distance_m.value, 10),
      duration_s: Math.round(parseFloat(form.elements.duration_min.value) * 60),
      avg_heart_rate: form.elements.avg_heart_rate.value !== '' ? parseInt(form.elements.avg_heart_rate.value, 10) : null,
      total_strokes: form.elements.total_strokes.value !== '' ? parseInt(form.elements.total_strokes.value, 10) : null,
      main_stroke: form.elements.main_stroke.value,
      laps: form.elements.laps.value !== '' ? parseInt(form.elements.laps.value, 10) : null,
      calories: form.elements.calories.value !== '' ? parseFloat(form.elements.calories.value) : null,
    };
    const req = editingId
      ? App.api('/api/swim-records/' + editingId, { method: 'PUT', body: payload })
      : App.api('/api/swim-records', { method: 'POST', body: payload });
    req.then(function () {
      App.closeModal('modalSwim');
      App.toast('已保存');
      setTimeout(function () { location.reload(); }, 400);
    }).catch(err => App.toast(err.message, true));
  });

  document.querySelectorAll('[data-close]').forEach(function (el) {
    el.addEventListener('click', function () { App.closeModal(el.dataset.close); });
  });

  load(1);
})();
