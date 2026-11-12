/* 状态记录页：月历（阶段三档圆点 + 有记录标记）、当日三类就地填写、全部记录分页列表、
   类型筛选、勾选批量删除；列表行内编辑走弹窗，详情复用 base.html 通用弹窗 #modalDetail。 */
(function () {
  const App = window.App;

  const TYPE_LABELS = { appetite: '食欲', myalgia: '肌肉疼痛', inflammation: '炎症' };
  const TYPE_TAG = { appetite: 'tag-appetite', myalgia: 'tag-gray', inflammation: 'tag-inflam' };
  const BLOCK_TITLES = { appetite: '今日食欲状况', myalgia: '今日肌肉疼痛状况', inflammation: '今日炎症状况' };
  const BLOCK_PLACEHOLDER = {
    appetite: '如：胃口正常 / 午餐量',
    myalgia: '如：大腿前侧酸胀，上下楼明显',
    inflammation: '如：膝盖轻微发热',
  };
  const PHASE_SHORT = {
    menstrual: '经期', follicular_pre: '卵泡期', ovulation_day: '排卵日',
    follicular_post: '排卵后', luteal_early: '黄体期', luteal_mid: '黄体期', luteal_late: '黄体期',
  };
  const PHASE_GROUP_TAG = { menses: 'tag-phase-menses', foll: 'tag-phase-foll', luteal: 'tag-phase-luteal' };

  const state = {
    cal: window.INIT_CAL,
    daily: window.INIT_DAILY || {},
    selected: window.TODAY_STR,
    page: 1,
    filterType: '',
    checked: {},   // key = id:type → {id, type}
    editingId: null,
    formStar: null,  // 弹窗表单当前星级：null=未评，0=最低分，1~5
    starCur: {},     // 内联表单：type → null | 0 | 1~5
  };

  function monthStr(year, month) { return year + '-' + String(month).padStart(2, '0'); }
  function dateOf(s) { const p = s.split('-'); return new Date(+p[0], +p[1] - 1, +p[2]); }
  function addMonths(s, n) { const d = dateOf(s + '-01'); d.setMonth(d.getMonth() + n); return monthStr(d.getFullYear(), d.getMonth() + 1); }
  function esc(s) { return App.escapeHtml(s == null ? '' : s); }

  /* ---------- 星级展示（静态；null=未评显示 —，0=最低分标注 0 分） ---------- */
  function starHtml(star) {
    if (star == null) return '<span class="dd-empty">—</span>';
    let html = '';
    for (let i = 1; i <= 5; i++) {
      html += '<span class="' + (i <= star ? 'on' : 'off') + '">' + (i <= star ? '★' : '☆') + '</span>';
    }
    const zeroTag = star === 0 ? '<span class="star-zero-tag">0 分</span>' : '';
    return '<span class="dd-stars">' + html + '</span>' + zeroTag;
  }

  /* 内联描述框：高度随内容自适应，不出现滚动条（删字后缩回） */
  function fitRemark(el) {
    if (!el || el.tagName !== 'TEXTAREA') return;
    el.style.height = 'auto';
    el.style.height = el.scrollHeight + 'px';
  }

  /* ---------- 月历 ---------- */
  function renderCalendar() {
    const cal = state.cal;
    const firstDay = dateOf(cal.year + '-' + String(cal.month).padStart(2, '0') + '-01');
    const offset = (firstDay.getDay() + 6) % 7; // 周一开头
    document.getElementById('calTitle').textContent = cal.year + ' 年 ' + cal.month + ' 月';

    let html = '';
    for (let i = 0; i < offset; i++) html += '<div class="cal-day cal-empty" aria-hidden="true"></div>';
    cal.days.forEach(function (d) {
      const dd = dateOf(d.date);
      const isToday = d.date === window.TODAY_STR;
      const isSel = d.date === state.selected;
      const phaseTxt = d.phase_key ? (PHASE_SHORT[d.phase_key] || d.phase_label || '') : '';
      html += '<button type="button" class="cal-day' + (d.phase_group ? ' ph-' + d.phase_group : '') +
        (isSel ? ' selected' : '') + (isToday ? ' today-cell' : '') + '" data-date="' + d.date + '"' +
        ' aria-label="' + d.date + ' ' + esc(phaseTxt) + '" aria-pressed="' + isSel + '">' +
        '<div class="cd-num num">' + dd.getDate() + '</div>' +
        (phaseTxt ? '<div class="cd-phase">' + esc(phaseTxt) + '</div>' : '') +
        (d.has_record ? '<span class="cd-dot"></span>' : '') + '</button>';
    });
    document.getElementById('calGrid').innerHTML = html;
  }

  function loadMonth(ym) {
    App.api('/api/state-record/calendar?month=' + ym).then(function (cal) {
      state.cal = cal;
      if (!cal.days.some(d => d.date === state.selected)) {
        state.selected = cal.days[0] ? cal.days[0].date : state.selected;
      }
      renderCalendar();
      loadDaily(state.selected);
    }).catch(e => App.toast(e.message, true));
  }

  /* ---------- 右栏当日详情（三类就地填写） ---------- */
  function renderDetail() {
    const day = dateOf(state.selected);
    const weekday = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'][(day.getDay() + 6) % 7];
    const dayInfo = (state.cal.days.find(d => d.date === state.selected) || {});
    const phaseTag = dayInfo.phase_group
      ? '<span class="tag no-dot ' + PHASE_GROUP_TAG[dayInfo.phase_group] + '">' + esc(PHASE_SHORT[dayInfo.phase_key] || dayInfo.phase_label) + '</span>'
      : '<span class="tag tag-gray no-dot">未推算</span>';

    let html = '<div class="dd-head"><span class="dd-date num">' + (day.getMonth() + 1) + '月' + day.getDate() + '日</span>' + phaseTag + '</div>' +
      '<div class="dd-meta">' + weekday + (state.selected === window.TODAY_STR ? ' · 今天' : '') + '</div>';

    ['appetite', 'myalgia', 'inflammation'].forEach(function (type) {
      const rec = state.daily[type];
      html += '<div class="dd-block" data-type="' + type + '">' +
        '<div class="dd-title"><span class="left">' + esc(BLOCK_TITLES[type]) + '</span>' +
        (rec ? '<button class="btn btn-sm dd-del" data-del="' + type + '">删除</button>' : '') +
        '</div>' +
        '<div class="dd-inline">' +
          '<div class="dd-star-row" data-star-box="' + type + '"></div>' +
          '<textarea class="input dd-remark" data-remark="' + type + '" rows="2" maxlength="255" placeholder="' + esc(BLOCK_PLACEHOLDER[type]) + '"></textarea>' +
          '<div class="dd-actions"><button class="btn btn-sm btn-primary" data-save="' + type + '">保存</button></div>' +
        '</div></div>';
    });

    document.getElementById('dayDetail').innerHTML = html;

    // 回填当日已有记录；星级三态：null=未评，0=最低分，1~5
    state.starCur = {};
    ['appetite', 'myalgia', 'inflammation'].forEach(function (type) {
      const rec = state.daily[type];
      const cur = rec ? rec.star : null;
      state.starCur[type] = cur;
      const box = document.querySelector('[data-star-box="' + type + '"]');
      box.innerHTML = App.starWidgetHtml(cur || 0) +
        '<button type="button" class="star-zero" data-zero="' + type + '" title="记为最低分">0</button>' +
        '<span class="star-value" data-star-value="' + type + '"></span>';
      paintInline(type);
      const remarkEl = document.querySelector('[data-remark="' + type + '"]');
      remarkEl.value = rec ? (rec.remark || '') : '';
      fitRemark(remarkEl);
    });
  }

  /* 内联块星级绘制：星高亮 / 0 按钮激活 / 分值标签 */
  function paintInline(type) {
    const cur = state.starCur[type];
    const box = document.querySelector('[data-star-box="' + type + '"]');
    if (!box) return;
    box.querySelectorAll('.sw-star').forEach(function (s) {
      s.classList.toggle('on', cur != null && parseInt(s.dataset.v, 10) <= cur);
    });
    const zeroBtn = box.querySelector('[data-zero]');
    if (zeroBtn) zeroBtn.classList.toggle('active', cur === 0);
    const val = box.querySelector('[data-star-value]');
    if (val) val.textContent = cur === 0 ? '0 分' : '';
  }

  /* 就地保存：有记录走 PUT，无记录走 POST；star 为 null=未评、0=最低分 */
  function saveInline(type) {
    const rec = state.daily[type];
    const star = state.starCur[type];
    const remark = (document.querySelector('[data-remark="' + type + '"]').value || '').trim() || null;
    if (star == null && !remark) { App.toast('请先选择星级或填写描述', true); return; }
    const payload = { date: state.selected, type: type, star: star, remark: remark };
    const req = rec
      ? App.api('/api/state-record/' + rec.id, { method: 'PUT', body: payload })
      : App.api('/api/state-record', { method: 'POST', body: payload });
    req.then(function () {
      App.toast(rec ? '记录已保存' : '记录已新增');
      reloadAll();
    }).catch(err => App.toast(err.message, true));
  }

  function delInline(type) {
    const rec = state.daily[type];
    if (!rec) return;
    App.confirmDialog({ title: '删除记录', message: '确定删除这条记录吗？删除后不可恢复。' })
      .then(function (ok) {
        if (!ok) return;
        App.api('/api/state-record/' + rec.id + '?type=' + type, { method: 'DELETE' })
          .then(function () { App.toast('已删除'); reloadAll(); })
          .catch(err => App.toast(err.message, true));
      });
  }

  function loadDaily(day) {
    App.api('/api/state-record/daily?date=' + day).then(function (res) {
      state.daily = res.records || {};
      renderDetail();
    }).catch(e => App.toast(e.message, true));
  }

  /* ---------- 全部记录列表 ---------- */
  function loadList(page) {
    state.page = page || 1;
    const qs = 'page=' + state.page + '&page_size=10' + (state.filterType ? '&type=' + state.filterType : '');
    App.api('/api/state-record?' + qs).then(function (res) {
      if (!res.list.length && res.page > 1 && res.total > 0) { loadList(res.page - 1); return; }
      const tbody = document.getElementById('recordBody');
      if (!res.list.length) {
        tbody.innerHTML = '<tr><td colspan="6"><div class="empty-state">暂无记录，可在右侧「当日状态」直接填写</div></td></tr>';
      } else {
        tbody.innerHTML = res.list.map(function (r) {
          const key = r.id + ':' + r.type;
          const checked = state.checked[key] ? 'checked' : '';
          return '<tr>' +
            '<td><input type="checkbox" class="batch-row" value="' + esc(key) + '" ' + checked + ' aria-label="选择记录"></td>' +
            '<td class="num">' + esc(r.date) + '</td>' +
            '<td><span class="tag ' + TYPE_TAG[r.type] + '">' + esc(r.type_label) + '</span></td>' +
            '<td>' + starHtml(r.star) + '</td>' +
            '<td class="desc-cell" title="' + esc(r.remark || '') + '">' + esc(r.remark || '—') + '</td>' +
            '<td class="row-actions">' +
              '<button class="btn btn-sm" data-act="view" data-row=\'' + JSON.stringify(r).replace(/'/g, "&#39;") + '\'>查看详情</button>' +
              '<button class="btn btn-sm" data-act="edit" data-row=\'' + JSON.stringify(r).replace(/'/g, "&#39;") + '\'>编辑</button>' +
              '<button class="btn btn-sm btn-danger" data-act="del" data-id="' + r.id + '" data-type="' + r.type + '">删除</button>' +
            '</td></tr>';
        }).join('');
      }
      syncBatchBtn();
      renderPagination(res);
    }).catch(e => App.toast(e.message, true));
  }

  function renderPagination(res) {
    const wrap = document.getElementById('recordPagination');
    if (res.pages <= 1) { wrap.innerHTML = '<div class="pagination"><span>共 ' + res.total + ' 条 · 每页 ' + res.page_size + ' 条</span></div>'; return; }
    let html = '<div class="pagination"><span>共 ' + res.total + ' 条 · 每页 ' + res.page_size + ' 条</span>';
    html += '<button class="btn btn-sm" data-pg="' + (res.page - 1) + '" ' + (res.page <= 1 ? 'disabled' : '') + '>上一页</button>';
    for (let p = 1; p <= res.pages; p++) html += '<button class="btn btn-sm ' + (p === res.page ? 'active' : '') + '" data-pg="' + p + '">' + p + '</button>';
    html += '<button class="btn btn-sm" data-pg="' + (res.page + 1) + '" ' + (res.page >= res.pages ? 'disabled' : '') + '>下一页</button></div>';
    wrap.innerHTML = html;
  }

  /* ---------- 勾选 / 批量删除 ---------- */
  function selectedItems() { return Object.values(state.checked); }
  function syncBatchBtn() {
    const n = selectedItems().length;
    const btn = document.getElementById('btnBatchDelete');
    btn.disabled = n === 0;
    btn.textContent = n ? '删除所选 (' + n + ')' : '删除所选';
    const all = document.getElementById('selectAll');
    const rows = document.querySelectorAll('#recordBody .batch-row');
    all.checked = rows.length > 0 && selectedItems().length === rows.length;
    all.indeterminate = selectedItems().length > 0 && selectedItems().length < rows.length;
  }

  document.getElementById('recordBody').addEventListener('change', function (e) {
    const cb = e.target.closest('.batch-row');
    if (!cb) return;
    const [id, type] = cb.value.split(':');
    if (cb.checked) state.checked[cb.value] = { id: Number(id), type };
    else delete state.checked[cb.value];
    syncBatchBtn();
  });

  document.getElementById('selectAll').addEventListener('change', function () {
    document.querySelectorAll('#recordBody .batch-row').forEach(function (cb) {
      const [id, type] = cb.value.split(':');
      cb.checked = document.getElementById('selectAll').checked;
      if (cb.checked) state.checked[cb.value] = { id: Number(id), type };
      else delete state.checked[cb.value];
    });
    syncBatchBtn();
  });

  document.getElementById('btnBatchDelete').addEventListener('click', function () {
    const items = selectedItems();
    if (!items.length) return;
    App.confirmDialog({ title: '删除所选', message: '确定删除选中的 ' + items.length + ' 条记录？删除后不可恢复。' })
      .then(function (ok) {
        if (!ok) return;
        App.api('/api/state-record/batch-delete', { method: 'POST', body: { items } })
          .then(function (res) {
            App.toast('已删除 ' + (res.deleted || []).length + ' 条');
            state.checked = {};
            reloadAll();
          })
          .catch(err => App.toast(err.message, true));
      });
  });

  /* ---------- 行操作：查看 / 编辑 / 删除 ---------- */
  document.getElementById('recordBody').addEventListener('click', function (e) {
    const btn = e.target.closest('button[data-act]');
    if (!btn) return;
    if (btn.dataset.act === 'view') {
      openDetail(JSON.parse(btn.dataset.row));
      return;
    }
    if (btn.dataset.act === 'del') {
      const id = Number(btn.dataset.id), type = btn.dataset.type;
      App.confirmDialog({ title: '删除记录', message: '确定删除这条记录吗？删除后不可恢复。' })
        .then(function (ok) {
          if (!ok) return;
          App.api('/api/state-record/' + id + '?type=' + type, { method: 'DELETE' })
            .then(function () { App.toast('已删除'); reloadAll(); })
            .catch(err => App.toast(err.message, true));
        });
      return;
    }
    openForm(JSON.parse(btn.dataset.row));
  });

  /* 内联表单：星级 / 0 分 / 保存 / 删除 */
  document.getElementById('dayDetail').addEventListener('click', function (e) {
    const starEl = e.target.closest('.sw-star');
    if (starEl) {
      const type = starEl.closest('.dd-block').dataset.type;
      state.starCur[type] = parseInt(starEl.dataset.v, 10);
      paintInline(type);
      return;
    }
    const zeroBtn = e.target.closest('[data-zero]');
    if (zeroBtn) {
      state.starCur[zeroBtn.dataset.zero] = 0;
      paintInline(zeroBtn.dataset.zero);
      return;
    }
    const saveBtn = e.target.closest('[data-save]');
    if (saveBtn) { saveInline(saveBtn.dataset.save); return; }
    const delBtn = e.target.closest('[data-del]');
    if (delBtn) delInline(delBtn.dataset.del);
  });

  /* 描述框输入时随内容自适应增高；中文输入法组字结束后补一次 */
  document.getElementById('dayDetail').addEventListener('input', function (e) {
    const el = e.target.closest('.dd-remark');
    if (el && !e.isComposing) fitRemark(el);
  });
  document.getElementById('dayDetail').addEventListener('compositionend', function (e) {
    const el = e.target.closest('.dd-remark');
    if (el) fitRemark(el);
  });

  /* ---------- 详情弹窗（复用 base.html 通用 #modalDetail） ---------- */
  function openDetail(r) {
    document.getElementById('detailTitle').textContent = '记录详情';
    document.getElementById('detailSub').innerHTML =
      '<span class="dl-sub">' + esc(r.date) + ' · <span class="tag ' + TYPE_TAG[r.type] + '">' + esc(r.type_label) + '</span></span>';
    document.getElementById('detailBody').innerHTML =
      '<div class="dl-grid">' +
      '<div class="dl-item"><span class="dl-label">日期</span><span class="dl-value num">' + esc(r.date) + '</span></div>' +
      '<div class="dl-item"><span class="dl-label">类型</span><span class="dl-value">' + esc(r.type_label) + '</span></div>' +
      '<div class="dl-item"><span class="dl-label">星级</span><span class="dl-value">' + (r.star == null ? '—' : (r.star === 0 ? '☆☆☆☆☆ 0 分' : '★'.repeat(r.star) + '☆'.repeat(5 - r.star))) + '</span></div>' +
      '</div>' +
      '<div class="dl-remark">' + esc(r.remark || '—') + '</div>';
    App.openModal('modalDetail');
  }

  /* 弹窗表单星级绘制：null=未评，0=最低分，1~5 */
  function paintFormStars() {
    const cur = state.formStar;
    const box = document.getElementById('formStars');
    box.querySelectorAll('.sw-star').forEach(function (s) {
      s.classList.toggle('on', cur != null && parseInt(s.dataset.v, 10) <= cur);
    });
    const zeroBtn = box.querySelector('[data-form-zero]');
    if (zeroBtn) zeroBtn.classList.toggle('active', cur === 0);
    const val = box.querySelector('#formStarValue');
    if (val) val.textContent = cur === 0 ? '0 分' : '';
  }

  /* ---------- 新增 / 编辑弹窗 ---------- */
  function openForm(row) {
    state.editingId = row ? row.id : null;
    const form = document.getElementById('formRecord');
    form.reset();
    form.elements.id.value = row ? row.id : '';
    form.elements.date.value = row ? row.date : state.selected;
    form.elements.type.value = row ? row.type : 'appetite';
    // 编辑时类型不可改：类型决定落在哪张表，改类型请删除后重建
    form.elements.type.disabled = !!row;
    form.elements.remark.value = row ? (row.remark || '') : '';
    document.getElementById('recordModalTitle').textContent = row ? '编辑状态记录' : '新增状态记录';
    state.formStar = row ? row.star : null;
    const box = document.getElementById('formStars');
    box.innerHTML = App.starWidgetHtml(state.formStar || 0) +
      '<button type="button" class="star-zero" data-form-zero title="记为最低分">0</button>' +
      '<span class="star-value" id="formStarValue"></span>';
    paintFormStars();
    App.openModal('modalRecord');
  }

  document.getElementById('formStars').addEventListener('click', function (e) {
    const s = e.target.closest('.sw-star');
    if (s) { state.formStar = parseInt(s.dataset.v, 10); paintFormStars(); return; }
    if (e.target.closest('[data-form-zero]')) { state.formStar = 0; paintFormStars(); }
  });

  document.getElementById('formRecord').addEventListener('submit', function (e) {
    e.preventDefault();
    const form = e.target;
    const star = state.formStar;  // null=未评，0=最低分，1~5
    const payload = {
      date: form.elements.date.value,
      type: form.elements.type.value,
      star: star,
      remark: form.elements.remark.value.trim() || null,
    };
    const req = state.editingId
      ? App.api('/api/state-record/' + state.editingId, { method: 'PUT', body: payload })
      : App.api('/api/state-record', { method: 'POST', body: payload });
    req.then(function () {
      App.closeModal('modalRecord');
      App.toast(state.editingId ? '记录已保存' : '记录已新增');
      reloadAll();
    }).catch(err => App.toast(err.message, true));
  });

  /* ---------- 月历交互 ---------- */
  document.getElementById('calGrid').addEventListener('click', function (e) {
    const cell = e.target.closest('.cal-day[data-date]');
    if (!cell) return;
    state.selected = cell.dataset.date;
    renderCalendar();
    loadDaily(state.selected);
  });

  document.getElementById('btnPrevMonth').addEventListener('click', function () { loadMonth(addMonths(monthStr(state.cal.year, state.cal.month), -1)); });
  document.getElementById('btnNextMonth').addEventListener('click', function () { loadMonth(addMonths(monthStr(state.cal.year, state.cal.month), 1)); });
  document.getElementById('btnGoToday').addEventListener('click', function () {
    state.selected = window.TODAY_STR;
    loadMonth(window.TODAY_STR.slice(0, 7));
  });

  /* ---------- 类型筛选 ---------- */
  document.getElementById('typeSeg').addEventListener('click', function (e) {
    const btn = e.target.closest('button[data-type]');
    if (!btn) return;
    state.filterType = btn.dataset.type;
    document.querySelectorAll('#typeSeg button').forEach(function (b) { b.classList.toggle('active', b === btn); });
    loadList(1);
  });

  document.getElementById('recordPagination').addEventListener('click', function (e) {
    const b = e.target.closest('button[data-pg]');
    if (b && !b.disabled) loadList(parseInt(b.dataset.pg, 10));
  });

  document.querySelectorAll('[data-close]').forEach(function (el) {
    el.addEventListener('click', function () { App.closeModal(el.dataset.close); });
  });

  function reloadAll() {
    state.checked = {};
    loadMonth(monthStr(state.cal.year, state.cal.month));
    loadList(state.page);
  }

  /* ---------- 初始化 ---------- */
  renderCalendar();
  renderDetail();
  loadList(1);
})();
