/* 健身训练页：日/周面板、状态机（TR-10~17）、庆祝（TR-20~23）、心得（TR-24/25） */
(function () {
  const App = window.App;
  const todayStr = App.todayStr();
  const WEEKDAY = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'];

  const state = {
    plan: window.INIT_PLAN || null,
    mode: 'view',          // view | record
    started: false,
    startedAtMs: null,
    timer: null,
    weekStart: null,
    saveResult: null,
    noteRating: 0,
    historyPage: 1,
  };

  /* ---------- 初始化：若中途刷新且 started_at 存在 → 恢复记录模式 ---------- */
  if (state.plan && state.plan.status !== 'recorded' && state.plan.started_at) {
    state.mode = 'record';
    state.started = true;
    state.startedAtMs = Date.parse(state.plan.started_at);
  }
  state.weekStart = mondayStr();

  function mondayStr() {
    const d = new Date();
    const day = (d.getDay() + 6) % 7;
    d.setDate(d.getDate() - day);
    return iso(d);
  }
  function iso(d) { return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0'); }
  function parseISO(s) { const p = s.split('-'); return new Date(+p[0], +p[1] - 1, +p[2]); }
  function addDays(s, n) { const d = parseISO(s); d.setDate(d.getDate() + n); return iso(d); }

  /* ---------- 渲染日面板 ---------- */
  function renderDay() {
    const wrap = document.getElementById('planWrap');
    const statusTag = document.getElementById('statusTag');
    const startBtn = document.getElementById('btnStartRecord');
    const foot = document.getElementById('dayFoot');
    const summary = document.getElementById('daySummary');
    const volLabel = document.getElementById('volLabel');

    if (!state.plan || !state.plan.items || state.plan.items.length === 0) {
      statusTag.style.display = 'none';
      startBtn.style.display = 'none';
      foot.style.display = 'none';
      summary.textContent = '今日暂无训练计划';
      wrap.innerHTML = '<div class="empty-state"><div class="icon">🏋️</div>今天还没有训练计划，点击右上角「新建计划」创建。</div>';
      document.getElementById('timerLabel').textContent = '';
      renderOverview(null);
      return;
    }

    const items = state.plan.items;
    const volume = computeVolume(items);
    document.getElementById('timerLabel').textContent = '';

    if (state.mode === 'view') {
      statusTag.style.display = 'none';
      const recorded = state.plan.status === 'recorded';
      startBtn.style.display = window.INIT_CAN_RECORD && !recorded ? 'inline-flex' : 'none';
      foot.style.display = 'none';
      summary.innerHTML = partsSummary(items) + ' · 计划 <b>' + items.length + '</b> 个动作 / <b>' + sumSets(items) + '</b> 组' + (recorded ? ' · 已保存为训练记录' : '');
      wrap.innerHTML = '<table class="tbl training-tbl"><thead><tr><th>#</th><th>动作</th><th>部位</th><th>重量</th><th>组数 × 次数</th></tr></thead><tbody>' +
        items.map(function (it, i) {
          return '<tr><td class="num" style="color:var(--color-text-secondary)">' + String(i + 1).padStart(2, '0') + '</td>' +
            '<td class="done-text" style="font-weight:600">' + App.escapeHtml(it.exercise_name) + '</td>' +
            '<td>' + (it.body_part ? '<span class="tag tag-gray no-dot">' + App.escapeHtml(it.body_part) + '</span>' : '—') + '</td>' +
            '<td class="num">' + it.weight_kg + ' kg</td>' +
            '<td class="num" style="font-weight:600">' + it.sets + ' × ' + it.reps + '</td></tr>';
        }).join('') + '</tbody></table>';
      renderOverview(items);
      return;
    }

    // 记录模式
    statusTag.style.display = 'inline-flex';
    startBtn.style.display = 'none';
    foot.style.display = 'flex';
    volLabel.textContent = volume;
    summary.innerHTML = '训练进行中，可随时调整动作与实际重量' + (state.started ? '' : '（仅编辑·不计时）');
    wrap.innerHTML = '<table class="tbl training-tbl"><thead><tr>' +
      '<th style="width:34px">#</th><th>动作</th><th>部位</th><th>重量 kg</th><th>组数 × 每组个数</th><th>期望突破重量</th><th></th></tr></thead><tbody>' +
      items.map(function (it, i) {
        return '<tr class="' + (it.checked ? 'row-done' : '') + '" data-idx="' + i + '">' +
          '<td><span class="checkmark ' + (it.checked ? 'checked' : '') + '" data-act="check"><svg viewBox="0 0 12 12"><path d="M2 6.5 L4.5 9 L10 3"/></svg></span></td>' +
          '<td><input class="tin wide done-text" data-f="exercise_name" value="' + App.escapeHtml(it.exercise_name) + '"></td>' +
          '<td><input class="tin" data-f="body_part" value="' + App.escapeHtml(it.body_part || '') + '"></td>' +
          '<td><input class="tin num" type="number" step="0.5" min="0" data-f="weight_kg" value="' + it.weight_kg + '"></td>' +
          '<td style="white-space:nowrap"><input class="tin num" type="number" min="1" data-f="sets" value="' + it.sets + '"><span style="margin:0 4px;color:var(--color-text-secondary)">×</span><input class="tin num" type="number" min="1" data-f="reps" value="' + it.reps + '"></td>' +
          '<td><input class="tin num" type="number" step="0.5" min="0" data-f="target_weight_kg" value="' + (it.target_weight_kg != null ? it.target_weight_kg : '') + '" placeholder="如 75"></td>' +
          '<td class="action-cell"><button class="btn btn-sm btn-danger" data-act="delrow">删除</button></td></tr>';
      }).join('') + '</tbody></table>';
    renderOverview(items);
    startTimerIfNeeded();
  }

  function computeVolume(items) {
    return items.reduce(function (a, it) { return a + (it.weight_kg || 0) * (it.sets || 0) * (it.reps || 0); }, 0).toFixed(0);
  }
  function sumSets(items) { return items.reduce(function (a, it) { return a + (it.sets || 0); }, 0); }
  function partsSummary(items) {
    const parts = items.map(i => i.body_part).filter(Boolean);
    const uniq = Array.from(new Set(parts));
    return uniq.length ? uniq.join(' + ') : '训练';
  }

  function renderOverview(items) {
    const list = document.getElementById('overviewList');
    if (!items || !items.length) {
      list.innerHTML = '<div class="empty-state" style="padding:18px 0">今日暂无计划</div>';
      return;
    }
    const done = items.filter(i => i.checked).length;
    const rows = [
      ['训练内容', partsSummary(items)],
      ['动作数量', items.length + ' 个'],
      ['计划组数', sumSets(items) + ' 组'],
      ['今日完成度', done + ' / ' + items.length],
      ['总容量', computeVolume(items) + ' kg'],
    ];
    list.innerHTML = rows.map(r => '<div class="ov-row"><span class="k">' + r[0] + '</span><span class="v num">' + r[1] + '</span></div>').join('');
  }

  function startTimerIfNeeded() {
    clearInterval(state.timer);
    const label = document.getElementById('timerLabel');
    if (!state.started) { label.textContent = ''; return; }
    function upd() {
      const el = Math.floor((Date.now() - state.startedAtMs) / 1000);
      const m = Math.floor(el / 60), s = el % 60;
      label.textContent = "  · 已计时 " + m + "'" + String(s).padStart(2, '0') + '"';
    }
    upd();
    state.timer = setInterval(upd, 1000);
  }

  /* ---------- 进入记录模式 ---------- */
  document.getElementById('btnStartRecord').addEventListener('click', function () { App.openModal('modalStart'); });
  document.getElementById('btnModeEdit').addEventListener('click', function () { startMode('edit'); });
  document.getElementById('btnModeTraining').addEventListener('click', function () { startMode('training'); });

  function startMode(mode) {
    App.closeModal('modalStart');
    App.api('/api/training/plans/' + todayStr + '/start', { method: 'POST', body: { mode: mode } })
      .then(function (res) {
        state.plan = res.plan;
        state.mode = 'record';
        state.started = mode === 'training';
        state.startedAtMs = mode === 'training' ? Date.now() : null;
        renderDay();
        if (mode === 'training') App.toast('开始训练，计时中');
      })
      .catch(e => App.toast(e.message, true));
  }

  /* ---------- 记录模式交互（勾选/删除行/输入联动） ---------- */
  document.getElementById('planWrap').addEventListener('click', function (e) {
    const btn = e.target.closest('[data-act]');
    if (!btn) return;
    const row = btn.closest('tr');
    const idx = parseInt(row.dataset.idx, 10);
    if (btn.dataset.act === 'check') {
      state.plan.items[idx].checked = !state.plan.items[idx].checked;
      renderDay();
      return;
    }
    if (btn.dataset.act === 'delrow') {
      if (!App.confirm('删除该行训练动作？')) return;
      state.plan.items.splice(idx, 1);
      renderDay();
    }
  });

  document.getElementById('planWrap').addEventListener('input', function (e) {
    const t = e.target.closest('input[data-f]');
    if (!t) return;
    const row = t.closest('tr');
    const idx = parseInt(row.dataset.idx, 10);
    const f = t.dataset.f;
    const it = state.plan.items[idx];
    if (f === 'exercise_name' || f === 'body_part') it[f] = t.value;
    else if (f === 'weight_kg' || f === 'target_weight_kg') it[f] = t.value === '' ? null : parseFloat(t.value);
    else it[f] = t.value === '' ? 1 : parseInt(t.value, 10);
    if (['weight_kg', 'sets', 'reps'].includes(f)) {
      document.getElementById('volLabel').textContent = computeVolume(state.plan.items);
      renderOverview(state.plan.items);
    }
  });

  /* ---------- 取消 / 保存 ---------- */
  document.getElementById('btnCancelRecord').addEventListener('click', function () {
    clearInterval(state.timer);
    App.api('/api/training/plans/' + todayStr + '/cancel', { method: 'POST', body: {} })
      .then(function () { location.reload(); })
      .catch(e => { App.toast(e.message, true); location.reload(); });
  });

  document.getElementById('btnSaveRecord').addEventListener('click', function () {
    const items = state.plan.items.map(function (it, i) {
      return {
        exercise_name: (it.exercise_name || '').trim(),
        body_part: (it.body_part || '').trim(),
        weight_kg: it.weight_kg || 0,
        sets: it.sets || 1,
        reps: it.reps || 1,
        target_weight_kg: it.target_weight_kg != null ? it.target_weight_kg : null,
        checked: !!it.checked,
      };
    });
    if (!items.some(i => i.exercise_name)) { App.toast('至少保留一条动作', true); return; }
    document.getElementById('btnSaveRecord').disabled = true;
    App.api('/api/training/plans/' + todayStr + '/save', { method: 'POST', body: { items: items } })
      .then(function (res) {
        state.saveResult = res;
        state.plan = res.plan;
        state.mode = 'view';
        clearInterval(state.timer);
        if (res.duration_s != null) {
          showCelebrate(res);
        } else {
          App.toast('已保存训练记录');
          setTimeout(function () { location.reload(); }, 600);
        }
      })
      .catch(e => { document.getElementById('btnSaveRecord').disabled = false; App.toast(e.message, true); });
  });

  /* ---------- 庆祝弹窗（TR-20~23） ---------- */
  function showCelebrate(res) {
    document.getElementById('celebrateDuration').textContent = Math.max(1, Math.round(res.duration_s / 60));
    document.getElementById('celebrateItems').textContent = res.item_count;
    document.getElementById('celebrateMeta').textContent = '完成 ' + res.completed_count + ' 个动作 · 总容量 ' + res.total_volume.toFixed(0) + ' kg · ' + (state.plan.plan_date || todayStr);
    App.openModal('modalCelebrate');
    window.Confetti.launch();
  }
  document.getElementById('btnNoteLater').addEventListener('click', function () {
    App.closeModal('modalCelebrate');
    window.Confetti.stop();
    setTimeout(function () { location.reload(); }, 300);
  });
  document.getElementById('btnNoteConfirm').addEventListener('click', function () {
    App.closeModal('modalCelebrate');
    window.Confetti.stop();
    openNote();
  });

  /* ---------- 心得（TR-24/25） ---------- */
  function openNote() {
    state.noteRating = 0;
    document.getElementById('formNote').reset();
    Array.prototype.forEach.call(document.querySelectorAll('#starPicker span'), s => s.classList.remove('on'));
    App.openModal('modalNote');
  }
  document.getElementById('starPicker').addEventListener('click', function (e) {
    const s = e.target.closest('span'); if (!s) return;
    state.noteRating = parseInt(s.dataset.s, 10);
    Array.prototype.forEach.call(this.children, el => el.classList.toggle('on', parseInt(el.dataset.s, 10) <= state.noteRating));
  });
  document.getElementById('formNote').addEventListener('submit', function (e) {
    e.preventDefault();
    App.api('/api/training/plans/' + todayStr + '/note', {
      method: 'POST',
      body: { status_text: e.target.elements.status_text.value.trim(), rating: state.noteRating || null }
    }).then(function () {
      App.closeModal('modalNote');
      App.toast('心得已保存');
      setTimeout(function () { location.reload(); }, 500);
    }).catch(err => App.toast(err.message, true));
  });

  /* ---------- 新建/编辑计划（TR-03） ---------- */
  function openPlan(plan) {
    document.getElementById('modalPlanTitle').textContent = plan ? '编辑计划' : '新建计划';
    const form = document.getElementById('formPlan');
    form.reset();
    form.elements.plan_date.value = plan ? plan.plan_date : todayStr;
    form.elements.plan_date.max = '';
    const rowsWrap = document.getElementById('planRows');
    rowsWrap.innerHTML = '';
    const items = (plan && plan.items && plan.items.length) ? plan.items : [{}];
    items.forEach(function (it) { addPlanRow(it); });
    App.openModal('modalPlan');
  }
  function addPlanRow(it) {
    it = it || {};
    const wrap = document.getElementById('planRows');
    const div = document.createElement('div');
    div.className = 'plan-form-item';
    div.innerHTML =
      '<input class="input" name="exercise_name" placeholder="动作名称" value="' + App.escapeHtml(it.exercise_name || '') + '">' +
      '<input class="input" name="body_part" placeholder="部位" value="' + App.escapeHtml(it.body_part || '') + '">' +
      '<input class="input num" type="number" step="0.5" min="0" name="weight_kg" value="' + (it.weight_kg != null ? it.weight_kg : '') + '">' +
      '<input class="input num" type="number" min="1" name="sets" value="' + (it.sets || 1) + '">' +
      '<input class="input num" type="number" min="1" name="reps" value="' + (it.reps || 1) + '">' +
      '<button type="button" class="btn btn-sm btn-danger" title="删除行">✕</button>';
    div.querySelector('button').addEventListener('click', function () { div.remove(); });
    wrap.appendChild(div);
  }
  document.getElementById('btnNewPlan').addEventListener('click', function () { openPlan(null); });
  document.getElementById('btnAddRow').addEventListener('click', function () { addPlanRow({}); });
  document.getElementById('formPlan').addEventListener('submit', function (e) {
    e.preventDefault();
    const form = e.target;
    const items = [];
    Array.prototype.forEach.call(form.querySelectorAll('.plan-form-item'), function (row) {
      const name = row.querySelector('[name=exercise_name]').value.trim();
      if (!name) return;
      items.push({
        exercise_name: name,
        body_part: row.querySelector('[name=body_part]').value.trim(),
        weight_kg: parseFloat(row.querySelector('[name=weight_kg]').value) || 0,
        sets: parseInt(row.querySelector('[name=sets]').value, 10) || 1,
        reps: parseInt(row.querySelector('[name=reps]').value, 10) || 1,
      });
    });
    if (!items.length) { App.toast('至少填写一条动作名称', true); return; }
    const date = form.elements.plan_date.value;
    App.api('/api/training/plans/' + date, { method: 'POST', body: { items: items } })
      .then(function () {
        App.closeModal('modalPlan');
        App.toast('计划已保存');
        setTimeout(function () { location.reload(); }, 500);
      })
      .catch(err => App.toast(err.message, true));
  });

  /* ---------- 日/周切换 ---------- */
  document.getElementById('viewSeg').addEventListener('click', function (e) {
    const b = e.target.closest('button'); if (!b) return;
    Array.prototype.forEach.call(this.children, c => c.classList.remove('active'));
    b.classList.add('active');
    const isWeek = b.dataset.view === 'week';
    document.getElementById('dayPanel').style.display = isWeek ? 'none' : '';
    document.getElementById('weekPanel').style.display = isWeek ? '' : 'none';
    if (isWeek) renderWeek();
  });

  function renderWeek() {
    App.api('/api/training/plans/week?week_start=' + state.weekStart).then(function (res) {
      document.getElementById('weekRange').textContent = state.weekStart + ' ~ ' + addDays(state.weekStart, 6);
      document.getElementById('weekGrid').innerHTML = res.days.map(function (d) {
        const dd = parseISO(d.date);
        const isToday = d.date === todayStr;
        let body = '<div class="wd-empty">—</div>';
        if (d.plan) {
          body = '<div class="wd-summary"><div class="wd-parts">' + App.escapeHtml(d.plan.body_parts_summary || '训练') + '</div>' +
            '<div class="wd-meta">' + d.plan.item_count + ' 个动作 · ' + d.plan.total_sets + ' 组</div>' +
            (d.plan.status === 'recorded' ? '<div class="tag tag-mint no-dot" style="margin-top:6px">已记录</div>' : '') + '</div>';
        }
        return '<div class="week-day ' + (isToday ? 'is-today' : '') + '">' +
          '<div class="wd-date num">' + d.date.slice(5) + (isToday ? ' · 今天' : '') + '</div>' +
          '<div class="wd-week">' + WEEKDAY[dd.getDay() === 0 ? 6 : dd.getDay() - 1] + '</div>' + body + '</div>';
      }).join('');
    }).catch(e => App.toast(e.message, true));
  }
  document.getElementById('btnWeekPrev').addEventListener('click', function () { state.weekStart = addDays(state.weekStart, -7); renderWeek(); });
  document.getElementById('btnWeekNext').addEventListener('click', function () { state.weekStart = addDays(state.weekStart, 7); renderWeek(); });

  /* ---------- 训练历史 ---------- */
  function loadHistory(page) {
    App.api('/api/training/history?page=' + page + '&page_size=5').then(function (res) {
      const body = document.getElementById('historyBody');
      if (!res.list.length) {
        body.innerHTML = '<tr><td colspan="6"><div class="empty-state">暂无训练记录</div></td></tr>';
      } else {
        body.innerHTML = res.list.map(function (p) {
          let dur = '—';
          if (p.started_at && p.saved_at) {
            const s = Math.max(0, Math.round((Date.parse(p.saved_at) - Date.parse(p.started_at)) / 1000));
            dur = App.fmtDuration(s);
          }
          const note = p.note;
          const noteHtml = note
            ? (note.rating ? '<div class="star-dots">' + '★'.repeat(note.rating) + '</div>' : '') + '<div class="note-text">' + App.escapeHtml((note.status_text || '').slice(0, 40)) + '</div>'
            : '<span style="color:var(--color-text-secondary)">—</span>';
          return '<tr><td class="num">' + p.plan_date + '</td>' +
            '<td>' + App.escapeHtml(p.body_parts_summary || '训练') + '</td>' +
            '<td class="num">' + dur + '</td>' +
            '<td class="num">' + p.item_count + ' 个</td>' +
            '<td class="num" style="color:var(--color-text-secondary)">完成 ' + p.completed_count + '/' + p.item_count + ' · ' + p.total_volume + ' kg</td>' +
            '<td>' + noteHtml + '</td></tr>';
        }).join('');
      }
      const wrap = document.getElementById('historyPagination');
      if (res.pages <= 1) { wrap.innerHTML = ''; }
      else {
        let html = '<div class="pagination"><span>共 ' + res.total + ' 条</span>';
        html += '<button class="btn btn-sm" data-pg="' + (res.page - 1) + '" ' + (res.page <= 1 ? 'disabled' : '') + '>上一页</button>';
        for (let p = 1; p <= res.pages; p++) html += '<button class="btn btn-sm ' + (p === res.page ? 'active' : '') + '" data-pg="' + p + '">' + p + '</button>';
        html += '<button class="btn btn-sm" data-pg="' + (res.page + 1) + '" ' + (res.page >= res.pages ? 'disabled' : '') + '>下一页</button></div>';
        wrap.innerHTML = html;
      }
    }).catch(e => App.toast(e.message, true));
  }
  document.getElementById('historyPagination').addEventListener('click', function (e) {
    const b = e.target.closest('button[data-pg]');
    if (b && !b.disabled) loadHistory(parseInt(b.dataset.pg, 10));
  });

  /* ---------- 关闭按钮 ---------- */
  document.querySelectorAll('[data-close]').forEach(function (el) {
    el.addEventListener('click', function () { App.closeModal(el.dataset.close); window.Confetti && window.Confetti.stop(); });
  });

  /* ---------- 初始化 ---------- */
  renderDay();
  loadHistory(1);
})();
