/* 健身训练页：一个训练计划一张卡片、卡片内一行一个动作；练完点「完成训练」转训练记录（2026-11-03 移除计时记录模式/庆祝/心得）。
   2026-11 整改：一日可多个训练计划，按 id 定位；一个计划一张卡片（当日训练/当日训练2…），
   卡片内每个动作一行；卡片内「＋ 添加训练动作」=编辑该计划（追加动作行），顶部「＋ 新建计划」=新建整个计划。 */
(function () {
  const App = window.App;
  const todayStr = App.todayStr();
  const viewDate = window.INIT_DATE || todayStr;   // 当前查看日期（总览跳转 / 前后翻页）
  const qs = new URLSearchParams(location.search);
  const fromOv = qs.get('fromov') === '1';        // 是否从总览点日期格「＋ 计划」过来
  const isToday = window.INIT_IS_TODAY === true;    // 仅当日开放「完成训练」（后端强校验）

  const state = {
    plans: window.INIT_PLANS || [],   // 当日计划列表（planned 在前、recorded 沉底）
    editingPlanId: null,              // 计划编辑器：null=新建，否则编辑该 id
    completingPlanId: null,           // 待完成训练的计划 id
    editingPlanWasRecorded: false,    // 打开编辑器时该计划是否已是记录态（决定保存时是否顺带存心得）
    historyPage: 1,
  };
  let editNoteStars = null;           // 计划编辑器内心得星级取值器（编辑记录态才有）
  let planDurationManual = false;    // 记录编辑器：用户是否手改过时长（改过则起止时间不再覆盖）

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

  /* ---------- 渲染日面板：一个计划一张卡片 ---------- */
  function renderDay() {
    const wrap = document.getElementById('planWrap');
    const summary = document.getElementById('daySummary');
    if (!wrap || !summary) return;

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
    // 已记录计划为历史快照：卡片内不提供操作（编辑/删除/设为今日计划入口在训练历史列表）
    // 2026-11-04 起「完成训练」不限当日：任意日期的计划均可一键转记录
    const actions = recorded ? '' :
      '<button type="button" class="btn btn-sm" data-act="edit" data-id="' + p.id + '">编辑</button>' +
      '<button type="button" class="btn btn-sm btn-danger" data-act="del" data-id="' + p.id + '">删除</button>' +
      '<button type="button" class="btn btn-sm btn-primary" data-act="complete" data-id="' + p.id + '">完成训练</button>';
    const rows = items.length
      ? items.map(itemRowHtml).join('')
      : '<tr><td colspan="6" class="pc-empty">' + (recorded ? '暂无动作数据' : '暂无动作，点击下方「＋ 添加训练动作」添加。') + '</td></tr>';
    return '<div class="plan-card' + (recorded ? ' is-recorded' : '') + '" data-pid="' + p.id + '">' +
      '<div class="plan-card-head">' +
        '<div class="plan-card-title">' + (idx === 0 ? '当日训练' : '当日训练' + (idx + 1)) +
          ' ' + App.statusTag(p.status, recorded ? '已记录' : '计划') +
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

  function renderOverview(plans) {
    const list = document.getElementById('overviewList');
    if (!list) return;
    if (!plans || !plans.length) {
      list.innerHTML = '<div class="empty-state" style="padding:18px 0">当日暂无计划</div>';
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

  /* ---------- 计划卡：行操作（卡内追加 / 编辑 / 删除 / 完成训练） ---------- */
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
          App.api('/api/training/' + plan.id, { method: 'DELETE' })
            .then(function () { App.toast('计划已删除'); location.reload(); })
            .catch(err => App.toast(err.message, true));
        });
      return;
    }
    if (btn.dataset.act === 'complete') {
      state.completingPlanId = plan.id;
      App.openModal('modalComplete');
    }
  });

  /* ---------- 完成训练（二次确认 → planned → recorded，仅当日，后端强校验） ---------- */
  document.getElementById('btnConfirmComplete').addEventListener('click', function () {
    const id = state.completingPlanId;
    if (!id) return;
    App.api('/api/training/' + id + '/complete', { method: 'POST', body: {} })
      .then(function (resp) {
        App.closeModal('modalComplete');
        App.toast('已标记为完成训练');
        App.celebrate({
          showNote: true,
          onNote: function () { openTrainingNote(id, resp && resp.plan ? resp.plan.note : null); },
          onClose: function () { location.reload(); },
        });
      })
      .catch(err => App.toast(err.message, true));
  });

  /* ---------- 练后心得弹窗（2026-11） ---------- */
  let noteTargetId = null;
  let starGetRating = null;
  function openTrainingNote(planId, existing) {
    noteTargetId = planId;
    document.getElementById('trNoteBest').value = (existing && existing.best_movement) || '';
    document.getElementById('trNoteReflection').value = (existing && existing.notes) || '';
    document.getElementById('trNoteNext').value = (existing && existing.next_steps) || '';
    const starBox = document.getElementById('trNoteStars');
    starBox.innerHTML = App.starWidgetHtml(existing ? existing.rating : 0);
    starGetRating = App.bindStars(starBox, existing ? existing.rating || 0 : 0);
    App.openModal('modalTrainingNote');
  }
  document.getElementById('formTrainingNote').addEventListener('submit', function (e) {
    e.preventDefault();
    App.api('/api/training/' + noteTargetId + '/note', {
      method: 'PUT',
      body: {
        rating: (starGetRating && starGetRating() > 0) ? starGetRating() : null,
        best_movement: document.getElementById('trNoteBest').value.trim() || null,
        notes: document.getElementById('trNoteReflection').value.trim() || null,
        next_steps: document.getElementById('trNoteNext').value.trim() || null,
      },
    }).then(function () {
      App.closeModal('modalTrainingNote');
      App.toast('心得已保存');
      setTimeout(function () { location.reload(); }, 400);
    }).catch(err => App.toast(err.message, true));
  });
  // 心得弹窗「取消」也要刷新：庆祝链路刚新建了记录，列表需要看到新行
  document.querySelector('#modalTrainingNote [data-close]').addEventListener('click', function () {
    setTimeout(function () { location.reload(); }, 200);
  });

  /* ---------- 新建/编辑计划（顶部「＋ 新建计划」=新建整个计划，「＋ 新建记录」=直接补录一条训练记录；
     卡内「＋ 添加训练动作」=编辑该计划并追加动作行） ---------- */
  function openPlan(plan, appendMode, recordMode) {
    state.editingPlanId = plan ? plan.id : null;
    state.editingPlanSource = plan || null;
    state.recordMode = !!recordMode && !plan;   // 仅新建记录场景生效
    document.getElementById('modalPlanTitle').textContent = plan
      ? (plan.status === 'recorded' ? '编辑记录' : (appendMode ? '添加训练动作' : '编辑计划'))
      : (recordMode ? '新建记录' : '新建计划');
    document.getElementById('modalPlanDesc').textContent = recordMode
      ? '补录训练记录：保存后直接进入训练历史，日期可任意填写。'
      : '计划由用户手动创建，暂无自动生成需求（TR-03）。';
    const form = document.getElementById('formPlan');
    form.reset();
    const dateInput = form.elements.date;
    dateInput.value = plan ? plan.date : viewDate;
    dateInput.max = '';
    // 2026-11-04 起放开日期锁定：计划可挪期、记录可补录/改期（planned 与 recorded 均可改）
    const rowsWrap = document.getElementById('planRows');
    rowsWrap.innerHTML = '';
    form.elements.remark.value = plan ? (plan.remark || '') : '';
    // 记录态（新建记录 / 编辑记录）：显示起止时间与训练时长；计划态隐藏
    planDurationManual = false;
    const timingRow = document.getElementById('planTimingRow');
    const showTiming = state.recordMode || (!!plan && plan.status === 'recorded');
    timingRow.style.display = showTiming ? '' : 'none';
    document.getElementById('planStartDate').value = '';
    document.getElementById('planStartTime').value = '';
    document.getElementById('planEndDate').value = '';
    document.getElementById('planEndTime').value = '';
    document.getElementById('planDurationMin').value = '';
    if (showTiming) {
      if (plan && plan.start_time) {
        const t = String(plan.start_time).replace('T', ' ');
        document.getElementById('planStartDate').value = t.slice(0, 10);
        document.getElementById('planStartTime').value = t.slice(11, 16);
      }
      if (plan && plan.end_time) {
        const t = String(plan.end_time).replace('T', ' ');
        document.getElementById('planEndDate').value = t.slice(0, 10);
        document.getElementById('planEndTime').value = t.slice(11, 16);
      }
      if (plan && plan.duration_s != null) {
        document.getElementById('planDurationMin').value = Math.round(plan.duration_s / 60);
        planDurationManual = true;
      }
      // 默认起止日期 = 计划日期
      if (!document.getElementById('planStartDate').value) document.getElementById('planStartDate').value = dateInput.value;
      if (!document.getElementById('planEndDate').value) document.getElementById('planEndDate').value = dateInput.value;
    }
    const items = (plan && plan.items && plan.items.length) ? plan.items.slice() : [];
    items.forEach(function (it) { addPlanRow(it); });
    if (!items.length || appendMode) addPlanRow({});   // 新建留空行；追加模式额外补一个空行
    // 编辑「记录态」计划：编辑器内联展示心得区块（即使没填也显示）；计划态隐藏
    state.editingPlanWasRecorded = !!(plan && plan.status === 'recorded');
    const noteSec = document.getElementById('planEditNoteSection');
    noteSec.style.display = state.editingPlanWasRecorded ? '' : 'none';
    editNoteStars = null;
    if (state.editingPlanWasRecorded) {
      const n = plan.note || {};
      document.getElementById('trEditBest').value = n.best_movement || '';
      document.getElementById('trEditReflection').value = n.notes || '';
      document.getElementById('trEditNext').value = n.next_steps || '';
      const box = document.getElementById('trEditStars');
      box.innerHTML = App.starWidgetHtml(n.rating || 0);
      editNoteStars = App.bindStars(box, n.rating || 0);
    }
    App.openModal('modalPlan');
  }
  function addPlanRow(it) {
    it = it || {};
    const wrap = document.getElementById('planRows');
    const div = document.createElement('div');
    div.className = 'plan-form-item';
    div.innerHTML =
      '<span class="drag-handle" draggable="true" title="拖动排序">' +
        '<svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor" aria-hidden="true">' +
          '<circle cx="8" cy="6" r="1.4"/><circle cx="16" cy="6" r="1.4"/>' +
          '<circle cx="8" cy="12" r="1.4"/><circle cx="16" cy="12" r="1.4"/>' +
          '<circle cx="8" cy="18" r="1.4"/><circle cx="16" cy="18" r="1.4"/>' +
        '</svg></span>' +
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
    // 拖拽排序：手柄拖动，dragover 定位插入点，drop 按新顺序重排 DOM（保存按 DOM 顺序提交）
    const handle = div.querySelector('.drag-handle');
    handle.addEventListener('dragstart', function (e) {
      e.dataTransfer.setData('text/plain', '');
      e.dataTransfer.effectAllowed = 'move';
      div.classList.add('dragging');
    });
    handle.addEventListener('dragend', function () {
      div.classList.remove('dragging');
      clearRowDragOver();
    });
    wrap.appendChild(div);
  }
  const planRowsWrap = document.getElementById('planRows');
  function clearRowDragOver() {
    Array.prototype.forEach.call(planRowsWrap.querySelectorAll('.drag-over-before, .drag-over-after'), function (r) {
      r.classList.remove('drag-over-before', 'drag-over-after');
    });
    planRowsWrap._dropPos = null;
  }
  planRowsWrap.addEventListener('dragover', function (e) {
    const over = e.target.closest('.plan-form-item');
    if (!over) return;
    e.preventDefault();                 // 允许放置
    e.dataTransfer.dropEffect = 'move';
    if (over.classList.contains('dragging')) return;   // 源行自身不划线
    const rect = over.getBoundingClientRect();
    const after = e.clientY > rect.top + rect.height / 2;
    if (planRowsWrap._dropPos && planRowsWrap._dropPos.row === over && planRowsWrap._dropPos.after === after) return;
    clearRowDragOver();
    over.classList.add(after ? 'drag-over-after' : 'drag-over-before');
    planRowsWrap._dropPos = { row: over, after: after };
  });
  planRowsWrap.addEventListener('drop', function (e) {
    e.preventDefault();
    const src = planRowsWrap.querySelector('.plan-form-item.dragging');
    const pos = planRowsWrap._dropPos;
    clearRowDragOver();
    if (!src || !pos || pos.row === src) return;
    if (pos.after) pos.row.after(src); else pos.row.before(src);
    App.toast('动作顺序已调整，保存后生效');
  });
  document.getElementById('btnNewPlan').addEventListener('click', function () { openPlan(null); });
  document.getElementById('btnNewRecord').addEventListener('click', function () { openPlan(null, false, true); });
  document.getElementById('btnAddRow').addEventListener('click', function () { addPlanRow({}); });

  /* ---------- 记录态：起止时间自动推导训练时长（手填优先） ---------- */
  function timingIso(dateId, timeId) {
    const d = document.getElementById(dateId).value;
    if (!d) return null;
    return d + 'T' + (document.getElementById(timeId).value || '00:00') + ':00';
  }
  function autoCalcDuration() {
    if (planDurationManual) return;
    const s = timingIso('planStartDate', 'planStartTime');
    const e = timingIso('planEndDate', 'planEndTime');
    if (s && e) {
      const sec = Math.round((Date.parse(e) - Date.parse(s)) / 1000);
      if (sec > 0) document.getElementById('planDurationMin').value = Math.round(sec / 60);
    }
  }
  ['planStartDate', 'planStartTime', 'planEndDate', 'planEndTime'].forEach(function (id) {
    document.getElementById(id).addEventListener('change', autoCalcDuration);
  });
  document.getElementById('planDurationMin').addEventListener('input', function () {
    planDurationManual = this.value !== '';
  });
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
    const body = {
      date: form.elements.date.value,
      items: items,
      remark: remark,
    };
    if (!editingId && state.recordMode) body.status = 'recorded';   // 「＋ 新建记录」直接落历史
    // 记录态：起止时间 + 训练时长（秒）；后端在未手填时长时自动按起止推导
    const timingVisible = state.recordMode || state.editingPlanWasRecorded;
    if (timingVisible) {
      body.start_time = timingIso('planStartDate', 'planStartTime');
      body.end_time = timingIso('planEndDate', 'planEndTime');
      const dmRaw = document.getElementById('planDurationMin').value;
      body.duration_s = dmRaw !== '' ? Math.round(parseFloat(dmRaw) * 60) : null;
      if (state.editingPlanSource) {
        body.avg_heart_rate = state.editingPlanSource.avg_heart_rate;
        body.max_heart_rate = state.editingPlanSource.max_heart_rate;
        body.calories = state.editingPlanSource.calories;
      }
    }
    App.api(editingId ? '/api/training/' + editingId : '/api/training', {
      method: editingId ? 'PUT' : 'POST',
      body: body,
    })
      .then(function (resp) {
        App.closeModal('modalPlan');
        // 「＋ 新建记录」直接落 recorded：算一次训练完成，弹庆祝 + 可写心得
        const freshRecorded = !editingId && state.recordMode;
        const editingNote = editingId && state.editingPlanWasRecorded;  // 编辑已有记录：顺带保存心得
        function after() {
          if (fromOv) {
            location.href = '/overview?date=' + viewDate + '&mode=week';
          } else {
            location.reload();
          }
        }
        function saveNoteThen(cb) {
          App.api('/api/training/' + editingId + '/note', {
            method: 'PUT',
            body: {
              rating: (editNoteStars && editNoteStars() > 0) ? editNoteStars() : null,
              best_movement: document.getElementById('trEditBest').value.trim() || null,
              notes: document.getElementById('trEditReflection').value.trim() || null,
              next_steps: document.getElementById('trEditNext').value.trim() || null,
            },
          }).then(cb).catch(function (err) { App.toast('心得保存失败：' + err.message, true); cb(); });
        }
        if (freshRecorded && resp && resp.id) {
          App.toast('训练记录已保存');
          App.celebrate({
            showNote: true,
            onNote: function () { openTrainingNote(resp.id, resp.note); },
            onClose: after,
          });
        } else if (editingNote) {
          App.toast('训练记录已保存');
          saveNoteThen(function () { setTimeout(after, 400); });
        } else {
          App.toast(state.recordMode ? '训练记录已保存' : '计划已保存');
          setTimeout(after, 500);
        }
      })
      .catch(err => App.toast(err.message, true));
  });

  /* ---------- 训练历史 ---------- */
  let historyPage = 1;
  const historyBatch = App.bindBatchDelete('historyBody', 'trainingSelectAll', 'trainingBatchDelete', '/api/training', () => loadHistory(historyPage));
  // 类型列标签：统一走 App.statusTag（计划=绿/记录=灰）
  function statusTag(r) { return App.statusTag(r.status); }
  function loadHistory(page) {
    historyPage = page;
    App.api('/api/training?page=' + page + '&page_size=10').then(function (res) {
      if (!res.list.length && res.page > 1 && res.total > 0) { loadHistory(res.page - 1); return; }
      const body = document.getElementById('historyBody');
      if (!res.list.length) {
        body.innerHTML = '<tr><td colspan="7"><div class="empty-state">暂无计划或记录</div></td></tr>';
      } else {
        body.innerHTML = res.list.map(function (p) {
          let dur = '—';
          if (p.duration_s) {
            dur = App.fmtDuration(p.duration_s);
          } else if (p.start_time && p.end_time) {
            const s = Math.max(0, Math.round((Date.parse(p.end_time) - Date.parse(p.start_time)) / 1000));
            dur = App.fmtDuration(s);
          }
          // 列表不展示心得字段：心得只在「查看详情」/「编辑」中查看与编辑（照搬游泳/舞蹈）
          return '<tr><td class="num"><input type="checkbox" class="batch-row" value="' + p.id + '" aria-label="选择训练记录">' + p.date + '</td>' +
            '<td>' + statusTag(p) + '</td>' +
            '<td>' + App.escapeHtml(p.body_parts_summary || '训练') + '</td>' +
            '<td class="num">' + dur + '</td>' +
            '<td class="num">' + p.item_count + ' 个</td>' +
            '<td class="num" style="color:var(--color-text-secondary)">完成 ' + p.completed_count + '/' + p.item_count + ' · ' + p.total_volume + ' kg</td>' +
            '<td><div class="plan-actions">' +
              '<button type="button" class="btn btn-sm" data-hact="view" data-row=\'' + JSON.stringify(p).replace(/'/g, "&#39;") + '\'>查看详情</button>' +
              '<button type="button" class="btn btn-sm" data-hact="reuse" data-id="' + p.id + '">设为今日计划</button>' +
              '<button type="button" class="btn btn-sm" data-hact="edit" data-id="' + p.id + '" data-row=\'' + JSON.stringify(p).replace(/'/g, "&#39;") + '\'>编辑</button>' +
              '<button type="button" class="btn btn-sm btn-danger" data-hact="del" data-id="' + p.id + '">删除</button>' +
            '</div></td></tr>';
        }).join('');
      }
      historyBatch.reset();
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

  /* ---------- 训练历史行操作：设为今日计划 / 编辑 / 删除（2026-11-04） ---------- */
  document.getElementById('historyBody').addEventListener('click', function (e) {
    const btn = e.target.closest('button[data-hact]');
    if (!btn) return;
    const id = parseInt(btn.dataset.id, 10);
    if (btn.dataset.hact === 'view') {
      App.openDetail('training', JSON.parse(btn.dataset.row));
      return;
    }
    if (btn.dataset.hact === 'reuse') {
      App.api('/api/training/' + id + '/copy-to-today', { method: 'POST', body: {} })
        .then(function () {
          App.toast('已复用为今日计划');
          setTimeout(function () { location.reload(); }, 400);
        })
        .catch(err => App.toast(err.message, true));
      return;
    }
    if (btn.dataset.hact === 'edit') {
      openPlan(JSON.parse(btn.dataset.row));
      return;
    }
    if (btn.dataset.hact === 'del') {
      App.confirmDialog({ title: '删除训练记录', message: '确定删除该训练记录？其下的动作明细将一并删除。' })
        .then(function (ok) {
          if (!ok) return;
          App.api('/api/training/' + id, { method: 'DELETE' })
            .then(function () { App.toast('记录已删除'); loadHistory(historyPage); })
            .catch(err => App.toast(err.message, true));
        });
    }
  });

  /* ---------- 关闭按钮 ---------- */
  document.querySelectorAll('[data-close]').forEach(function (el) {
    el.addEventListener('click', function () { App.closeModal(el.dataset.close); });
  });

  /* ---------- Excel / JSON 导入（2026-11-04 新增：两个独立入口按钮） ---------- */
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
  let importMode = 'excel';   // 'excel' | 'json'
  let importCreated = 0;   // 本次导入新建的计划数（决定关闭时是否刷新）

  // 打开导入弹窗：重置状态，按入口按钮切换面板（Excel 文件 / JSON 文本）
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

  // 导入：Excel 走 multipart 上传（App.api 仅支持 JSON，此处原生 fetch）；JSON 走 App.api
  importForm.addEventListener('submit', function (e) {
    e.preventDefault();
    if (importMode === 'json') {
      let body;
      try { body = JSON.parse(importJsonText.value); }
      catch (err) { App.toast('JSON 格式不正确：' + err.message, true); return; }
      if (!body || !Array.isArray(body.plans) || !body.plans.length) { App.toast('需包含非空 plans 数组', true); return; }
      importSubmit.disabled = true;
      importSubmit.textContent = '导入中…';
      App.api('/api/training/import-json', { method: 'POST', body: body })
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
    fetch('/api/training/import', { method: 'POST', body: fd })
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
    importCreated = data.imported || 0;
    const items = data.items_imported || 0;
    const ok = importCreated > 0;
    let html = '<div class="summary">';
    if (!failed.length) {
      html += '<span class="ok">导入成功：' + importCreated + ' 条训练记录已导入（共 ' + items + ' 个动作）</span>';
    } else {
      html += '<span class="fail">导入完成：' + importCreated + ' 条记录成功，' + failed.length + ' 行失败已跳过</span>';
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
      // 导入全部成功：弹庆祝；恰好 1 条 → 可顺手写心得；多条 → 只庆祝
      const pids = data.training_ids || [];
      App.toast('已导入 ' + importCreated + ' 条训练记录');
      App.closeModal('modalImport');
      App.celebrate({
        showNote: importCreated === 1 && pids.length === 1,
        onNote: function () { openTrainingNote(pids[0], null); },
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

  // 「完成」：关闭弹窗；本次有成功写入则刷新
  importDone.addEventListener('click', function () {
    App.closeModal('modalImport');
    if (importCreated > 0) setTimeout(function () { location.reload(); }, 200);
  });

  /* ---------- 初始化 ---------- */
  renderDay();
  loadHistory(1);
  /* 从总览点日期格「＋ 计划」过来（?newplan=1）：自动弹出新建计划表单，日期已由 ?date= 带入 */
  if (qs.get('newplan') === '1') {
    openPlan(null);
    history.replaceState(null, '', location.pathname + '?date=' + viewDate);
  }
})();
