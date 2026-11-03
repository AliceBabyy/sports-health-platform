/* 健身训练页：今日训练卡片（一计划一卡片、一行一动作）+ 记录模式 + 庆祝 + 心得
   2026-11 整改：一日可多个训练计划，按 id 定位；一个计划一张卡片（今日训练/今日训练2…），
   卡片内每个动作一行；卡片内「＋ 添加训练动作」=编辑该计划（追加动作行），顶部「＋ 新建计划」=新建整个计划。 */
(function () {
  const App = window.App;
  const todayStr = App.todayStr();
  const viewDate = window.INIT_DATE || todayStr;   // 当前查看日期（总览跳转 / 前后翻页）
  const isToday = window.INIT_IS_TODAY === true;    // 仅当日开放记录模式（后端强校验）

  const state = {
    plans: window.INIT_PLANS || [],   // 今日计划列表（view 模式）
    plan: null,                       // 记录模式中的计划
    recordPlanId: null,               // 记录模式计划 id
    editingPlanId: null,              // 计划编辑器：null=新建，否则编辑该 id
    mode: 'view',                     // view | record
    started: false,
    startedAtMs: null,
    timer: null,
    saveResult: null,
    noteRating: 0,
    historyPage: 1,
  };

  /* 初始化：若存在 started_at 且未保存的计划 → 恢复记录模式（仅当日可能） */
  (function resume() {
    if (!isToday) return;
    const p = state.plans.find(x => x.status !== 'recorded' && x.started_at);
    if (p) {
      state.plan = p;
      state.recordPlanId = p.id;
      state.mode = 'record';
      state.started = true;
      state.startedAtMs = Date.parse(p.started_at);
    }
  })();

  /* ---------- 工具 ---------- */
  function parseReps(reps) {
    if (reps == null || reps === '') return 0;
    const m = String(reps).match(/\d+/);
    return m ? parseInt(m[0], 10) : 0;
  }
  function computeVolume(items) {
    return items.reduce(function (a, it) { return a + (it.weight_kg || 0) * (it.sets || 0) * parseReps(it.reps); }, 0).toFixed(0);
  }
  function sumSets(items) { return items.reduce(function (a, it) { return a + (it.sets || 0); }, 0); }
  function partsSummary(items) {
    const parts = items.map(i => i.body_part).filter(Boolean);
    const uniq = Array.from(new Set(parts));
    return uniq.length ? uniq.join(' + ') : '训练';
  }
  function allItems() { return state.plans.reduce(function (a, p) { return a.concat(p.items || []); }, []); }
  function planById(id) {
    for (let i = 0; i < state.plans.length; i++) if (state.plans[i].id === id) return state.plans[i];
    return null;
  }

  /* ---------- 渲染日面板 ---------- */
  function renderDay() {
    if (state.mode === 'record' && state.plan) { renderRecord(); return; }
    renderPlansView();
  }

  /* ---- view：一个计划一张卡片，卡片内每个动作一行；卡片操作=编辑/删除/记录，卡内追加=编辑该计划 ---- */
  function renderPlansView() {
    const wrap = document.getElementById('planWrap');
    const statusTag = document.getElementById('statusTag');
    const foot = document.getElementById('dayFoot');
    const summary = document.getElementById('daySummary');

    statusTag.style.display = 'none';
    foot.style.display = 'none';
    document.getElementById('timerLabel').textContent = '';

    // 排序：未记录（planned）在前、已记录沉底，组内按 id（创建顺序）
    const plans = state.plans.slice().sort(function (a, b) {
      const sa = a.status === 'recorded' ? 1 : 0;
      const sb = b.status === 'recorded' ? 1 : 0;
      return (sa - sb) || (a.id - b.id);
    });
    if (!plans.length) {
      summary.textContent = '当日暂无训练计划';
      wrap.innerHTML = '<div class="empty-state"><div class="icon">🏋️</div>这一天还没有训练计划，点击上方「＋ 新建计划」创建。</div>';
      renderOverview([]);
      return;
    }

    const items = allItems();
    const recordedCount = plans.filter(p => p.status === 'recorded').length;
    summary.innerHTML = partsSummary(items) + ' · 今日 <b>' + plans.length + '</b> 个计划 / <b>' + items.length + '</b> 个动作 / <b>' + sumSets(items) + '</b> 组' +
      (recordedCount ? ' · <b>' + recordedCount + '</b> 个已保存' : '');

    wrap.innerHTML = plans.map(planCardHtml).join('');
    renderOverview(plans);
  }

  function planCardHtml(p, idx) {
    const recorded = p.status === 'recorded';
    const items = p.items || [];
    // 已记录计划为历史快照：不提供编辑/删除/记录/追加入口（编辑与追加在后端也会被拒绝）
    // 非当日：不提供「开始训练」（后端仅允许当日开启计时）
    const actions = recorded ? '' :
      '<button type="button" class="btn btn-sm" data-act="edit" data-id="' + p.id + '">编辑</button>' +
      '<button type="button" class="btn btn-sm btn-danger" data-act="del" data-id="' + p.id + '">删除</button>' +
      (isToday
        ? '<button type="button" class="btn btn-sm btn-primary" data-act="record" data-id="' + p.id + '">开始训练</button>'
        : '<span class="pc-date-note">仅当日可开始训练</span>');
    const rows = items.length
      ? items.map(itemRowHtml).join('')
      : '<tr><td colspan="6" class="pc-empty">' + (recorded ? '暂无动作数据' : '暂无动作，点击下方「＋ 添加训练动作」添加。') + '</td></tr>';
    return '<div class="plan-card' + (recorded ? ' is-recorded' : '') + '" data-pid="' + p.id + '">' +
      '<div class="plan-card-head">' +
        '<div class="plan-card-title">' + (idx === 0 ? '当日训练' : '当日训练' + (idx + 1)) +
          ' <span class="tag ' + (recorded ? 'tag-mint' : 'tag-gray') + ' no-dot">' + (recorded ? '已记录' : '计划') + '</span>' +
          ' <span class="pc-meta num">' + (p.total_sets || 0) + ' 组 · ' + (p.total_volume || 0) + ' kg</span>' +
        '</div>' +
        (actions ? '<div class="plan-card-actions"><div class="plan-actions">' + actions + '</div></div>' : '') +
      '</div>' +
      (p.remark ? '<div class="pc-remark">' + App.escapeHtml(p.remark) + '</div>' : '') +
      '<table class="tbl training-tbl pc-items"><thead><tr>' +
        '<th class="num">#</th><th>动作</th><th>部位</th><th class="num">重量 kg</th><th class="num">组数 × 每组个数</th><th class="num">目标重量</th>' +
      '</tr></thead><tbody>' + rows + '</tbody></table>' +
      (recorded ? '' : '<div class="pc-add"><button type="button" class="btn btn-sm" data-act="append" data-id="' + p.id + '">＋ 添加训练动作</button></div>') +
      '</div>';
  }

  function itemRowHtml(it, i) {
    return '<tr>' +
      '<td class="num" style="color:var(--color-text-secondary)">' + (i + 1) + '</td>' +
      '<td>' + App.escapeHtml(it.exercise_name || '—') + '</td>' +
      '<td>' + App.escapeHtml(it.body_part || '—') + '</td>' +
      '<td class="num">' + (it.weight_kg != null ? it.weight_kg : '—') + '</td>' +
      '<td class="num">' + (it.sets != null ? it.sets : '—') + ' × ' + App.escapeHtml(it.reps != null ? it.reps : '—') + '</td>' +
      '<td class="num">' + (it.target_weight_kg != null ? it.target_weight_kg : '—') + '</td></tr>';
  }

  /* ---- record：单个计划的记录表格（勾选/编辑/删除行 + 取消/保存） ---- */
  function renderRecord() {
    const wrap = document.getElementById('planWrap');
    const statusTag = document.getElementById('statusTag');
    const foot = document.getElementById('dayFoot');
    const summary = document.getElementById('daySummary');
    const volLabel = document.getElementById('volLabel');

    statusTag.style.display = 'inline-flex';
    foot.style.display = 'flex';
    const items = state.plan.items;
    volLabel.textContent = computeVolume(items);
    summary.innerHTML = '训练进行中，可随时调整动作与实际重量';
    wrap.innerHTML = '<table class="tbl training-tbl"><thead><tr>' +
      '<th style="width:34px">#</th><th>动作</th><th>部位</th><th>重量 kg</th><th>组数 × 每组个数</th><th>期望突破重量</th><th></th></tr></thead><tbody>' +
      items.map(function (it, i) {
        return '<tr class="' + (it.checked ? 'row-done' : '') + '" data-idx="' + i + '">' +
          '<td><span class="checkmark ' + (it.checked ? 'checked' : '') + '" data-act="check"><svg viewBox="0 0 12 12"><path d="M2 6.5 L4.5 9 L10 3"/></svg></span></td>' +
          '<td><input class="tin wide done-text" data-f="exercise_name" value="' + App.escapeHtml(it.exercise_name) + '"></td>' +
          '<td><input class="tin" data-f="body_part" value="' + App.escapeHtml(it.body_part || '') + '"></td>' +
          '<td><input class="tin num" type="number" step="0.5" min="0" data-f="weight_kg" value="' + (it.weight_kg != null ? it.weight_kg : '') + '"></td>' +
          '<td style="white-space:nowrap"><input class="tin num" type="number" min="1" data-f="sets" value="' + (it.sets != null ? it.sets : '') + '"><span style="margin:0 4px;color:var(--color-text-secondary)">×</span><input class="tin" style="width:64px" data-f="reps" value="' + App.escapeHtml(it.reps != null ? it.reps : '') + '"></td>' +
          '<td><input class="tin num" type="number" step="0.5" min="0" data-f="target_weight_kg" value="' + (it.target_weight_kg != null ? it.target_weight_kg : '') + '" placeholder="如 75"></td>' +
          '<td class="action-cell"><button class="btn btn-sm btn-danger" data-act="delrow">删除</button></td></tr>';
      }).join('') + '</tbody></table>';
    renderOverview([state.plan]);
    startTimerIfNeeded();
  }

  function renderOverview(plans) {
    const list = document.getElementById('overviewList');
    if (!plans || !plans.length) {
      list.innerHTML = '<div class="empty-state" style="padding:18px 0">今日暂无计划</div>';
      return;
    }
    const items = plans.reduce(function (a, p) { return a.concat(p.items || []); }, []);
    const done = items.filter(i => i.checked).length;
    const rows = [
      ['训练内容', partsSummary(items)],
      ['计划数量', plans.length + ' 个'],
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

  /* ---------- 今日卡片：行操作（卡内追加 / 编辑 / 删除 / 记录） ---------- */
  document.getElementById('planWrap').addEventListener('click', function (e) {
    const btn = e.target.closest('[data-act]');
    if (!btn) return;
    const plan = planById(parseInt(btn.dataset.id, 10));
    if (!plan) return;
    if (btn.dataset.act === 'append') { openPlan(plan, true); return; }   // 卡内「＋ 添加训练动作」=编辑该计划
    if (btn.dataset.act === 'edit') { openPlan(plan); return; }
    if (btn.dataset.act === 'del') {
      App.confirmDialog({ title: '删除训练计划', message: '确定删除该训练计划？其下的动作明细将一并删除。' })
        .then(function (ok) {
          if (!ok) return;
          App.api('/api/training/plans/' + plan.id, { method: 'DELETE' })
            .then(function () { App.toast('计划已删除'); location.reload(); })
            .catch(err => App.toast(err.message, true));
        });
      return;
    }
    if (btn.dataset.act === 'record') {
      state.recordPlanId = plan.id;
      App.openModal('modalStart');
    }
  });

  /* ---------- 进入记录模式 ---------- */
  document.getElementById('btnModeTraining').addEventListener('click', function () { startMode(); });

  function startMode() {
    App.closeModal('modalStart');
    App.api('/api/training/plans/' + state.recordPlanId + '/start', { method: 'POST', body: { mode: 'training' } })
      .then(function (res) {
        state.plan = res.plan;
        state.recordPlanId = res.plan.id;
        state.mode = 'record';
        state.started = true;
        state.startedAtMs = Date.now();
        renderDay();
        App.toast('开始训练，计时中');
      })
      .catch(e => App.toast(e.message, true));
  }

  /* ---------- 记录模式交互（勾选/删除行/输入联动） ---------- */
  document.getElementById('planWrap').addEventListener('click', function (e) {
    if (state.mode !== 'record') return;
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
      App.confirmDialog({ title: '删除训练动作', message: '删除该行训练动作？' })
        .then(function (ok) {
          if (!ok) return;
          state.plan.items.splice(idx, 1);
          renderDay();
        });
    }
  });

  document.getElementById('planWrap').addEventListener('input', function (e) {
    if (state.mode !== 'record') return;
    const t = e.target.closest('input[data-f]');
    if (!t) return;
    const row = t.closest('tr');
    const idx = parseInt(row.dataset.idx, 10);
    const f = t.dataset.f;
    const it = state.plan.items[idx];
    if (f === 'exercise_name' || f === 'body_part' || f === 'reps') it[f] = t.value;
    else if (f === 'weight_kg' || f === 'target_weight_kg') it[f] = t.value === '' ? null : parseFloat(t.value);
    else if (f === 'sets') it[f] = t.value === '' ? null : parseInt(t.value, 10);
    if (['weight_kg', 'sets', 'reps'].includes(f)) {
      document.getElementById('volLabel').textContent = computeVolume(state.plan.items);
      renderOverview([state.plan]);
    }
  });

  /* ---------- 取消 / 保存记录 ---------- */
  document.getElementById('btnCancelRecord').addEventListener('click', function () {
    clearInterval(state.timer);
    App.api('/api/training/plans/' + state.recordPlanId + '/cancel', { method: 'POST', body: {} })
      .then(function () { location.reload(); })
      .catch(e => { App.toast(e.message, true); location.reload(); });
  });

  document.getElementById('btnSaveRecord').addEventListener('click', function () {
    const items = state.plan.items.map(function (it, i) {
      return {
        exercise_name: (it.exercise_name || '').trim(),
        body_part: (it.body_part || '').trim() || null,
        weight_kg: it.weight_kg != null ? it.weight_kg : null,
        sets: it.sets != null ? it.sets : null,
        reps: (it.reps != null && it.reps !== '') ? String(it.reps) : null,
        target_weight_kg: it.target_weight_kg != null ? it.target_weight_kg : null,
        checked: !!it.checked,
      };
    });
    if (!items.some(i => i.exercise_name)) { App.toast('至少保留一条动作', true); return; }
    document.getElementById('btnSaveRecord').disabled = true;
    App.api('/api/training/plans/' + state.recordPlanId + '/save', { method: 'POST', body: { items: items } })
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
    App.api('/api/training/plans/' + state.recordPlanId + '/note', {
      method: 'POST',
      body: { status_text: e.target.elements.status_text.value.trim(), rating: state.noteRating || null }
    }).then(function () {
      App.closeModal('modalNote');
      App.toast('心得已保存');
      setTimeout(function () { location.reload(); }, 500);
    }).catch(err => App.toast(err.message, true));
  });

  /* ---------- 新建/编辑计划（TR-03；顶部「＋ 新建计划」=新建整个计划，卡内「＋ 添加训练动作」=编辑该计划并追加动作行） ---------- */
  function openPlan(plan, appendMode) {
    state.editingPlanId = plan ? plan.id : null;
    document.getElementById('modalPlanTitle').textContent = plan ? (appendMode ? '添加训练动作' : '编辑计划') : '新建计划';
    const form = document.getElementById('formPlan');
    form.reset();
    const dateInput = form.elements.plan_date;
    dateInput.value = plan ? plan.plan_date : viewDate;
    dateInput.max = '';
    dateInput.disabled = !!plan;   // 编辑时日期锁定：计划归属日期不可改
    const rowsWrap = document.getElementById('planRows');
    rowsWrap.innerHTML = '';
    form.elements.remark.value = plan ? (plan.remark || '') : '';
    const items = (plan && plan.items && plan.items.length) ? plan.items.slice() : [];
    items.forEach(function (it) { addPlanRow(it); });
    if (!items.length || appendMode) addPlanRow({});   // 新建留空行；追加模式额外补一个空行
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
      '<input class="input num" type="number" min="1" name="sets" value="' + (it.sets != null ? it.sets : '') + '">' +
      '<input class="input" name="reps" placeholder="如 10+8+6" value="' + App.escapeHtml(it.reps != null ? it.reps : '') + '">' +
      '<input class="input num" type="number" step="0.5" min="0" name="target_weight_kg" value="' + (it.target_weight_kg != null ? it.target_weight_kg : '') + '" placeholder="目标重量">' +
      '<button type="button" class="btn btn-sm btn-danger" title="删除行">✕</button>';
    div.querySelector('button').addEventListener('click', function () {
      App.confirmDialog({ title: '删除动作行', message: '删除该行动作？' })
        .then(function (ok) { if (ok) div.remove(); });
    });
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
      const weightRaw = row.querySelector('[name=weight_kg]').value;
      const setsRaw = row.querySelector('[name=sets]').value;
      const repsRaw = row.querySelector('[name=reps]').value.trim();
      const targetRaw = row.querySelector('[name=target_weight_kg]').value;
      items.push({
        exercise_name: name,
        body_part: row.querySelector('[name=body_part]').value.trim() || null,
        weight_kg: weightRaw === '' ? null : parseFloat(weightRaw),
        sets: setsRaw === '' ? null : parseInt(setsRaw, 10),
        reps: repsRaw === '' ? null : repsRaw,
        target_weight_kg: targetRaw === '' ? null : parseFloat(targetRaw),
      });
    });
    if (!items.length) { App.toast('至少填写一条动作名称', true); return; }
    const editingId = state.editingPlanId;
    const remark = form.elements.remark.value.trim() || null;
    const body = editingId
      ? { items: items, remark: remark }
      : { plan_date: form.elements.plan_date.value, items: items, remark: remark };
    App.api(editingId ? '/api/training/plans/' + editingId : '/api/training/plans', {
      method: editingId ? 'PUT' : 'POST',
      body: body,
    })
      .then(function () {
        App.closeModal('modalPlan');
        App.toast('计划已保存');
        setTimeout(function () { location.reload(); }, 500);
      })
      .catch(err => App.toast(err.message, true));
  });

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
