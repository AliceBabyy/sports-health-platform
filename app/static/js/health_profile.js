/* 健康档案：全部专项卡片；点「新增/编辑」进入弹窗，可改问题、改回答并追加新题 */
(function () {
  const modal = document.getElementById('hpModal');
  const body = document.getElementById('hpModalBody');
  const title = document.getElementById('hpModalTitle');
  const sub = document.getElementById('hpModalSub');
  const count = document.getElementById('hpModalCount');
  const saveBtn = document.getElementById('hpSave');
  const clearBtn = document.getElementById('hpClear');
  const cards = Array.isArray(window.INIT_HP_CARDS) ? window.INIT_HP_CARDS : [];
  const CARD_BY_KEY = new Map(cards.map(function (card) { return [card.skill_key, card]; }));
  const esc = (window.App && App.escapeHtml) ? App.escapeHtml.bind(App) : function (value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  };

  let state = null;

  function questionFromCard(card) {
    const questionSet = card && card.set;
    if (questionSet && Array.isArray(questionSet.items)) {
      return questionSet.items.map(function (item) {
        return {
          local_key: item.local_key,
          aspect: item.aspect,
          label: item.label || '',
          hint: item.hint || '',
          placeholder: item.placeholder || '',
          max_length: item.max_length || 200,
          answer: item.answer || '',
        };
      });
    }
    return [{
      local_key: 'q1',
      aspect: (card && card.aspects && card.aspects[0]) || 'exercise',
      label: '',
      hint: '',
      placeholder: '',
      max_length: 200,
      answer: '',
    }];
  }

  function updateCount() {
    if (!state) return;
    count.textContent = state.questions.length + ' 题' + (state.questions.length >= 10 ? ' · 已满' : '');
  }

  function renderEditor() {
    if (!state) return;
    const rows = state.questions.map(function (q, index) {
      const value = esc(q.label);
      const answer = esc(q.answer);
      return '' +
        '<div class="hp-qedit" data-local-key="' + esc(q.local_key) + '">' +
          '<div class="hp-qedit-head">' +
            '<span class="hp-qno">' + String(index + 1).padStart(2, '0') + '</span>' +
            '<input class="input hp-q-label" type="text" maxlength="48" value="' + value + '" placeholder="写下问题">' +
          '</div>' +
          (q.hint ? '<div class="hp-qhint">' + esc(q.hint) + '</div>' : '') +
          '<textarea class="input hp-q-answer" rows="2" maxlength="' + q.max_length + '" placeholder="' +
            esc(q.placeholder || '写下你的回答') + '">' + answer + '</textarea>' +
          '<div class="hp-qedit-foot"><span class="hp-char-count">0/' + q.max_length + '</span></div>' +
        '</div>';
    }).join('');

    body.innerHTML = rows +
      (state.questions.length < 10
        ? '<button class="hp-add-question" type="button"><span aria-hidden="true">+</span> 添加一个问题</button>'
        : '<div class="hp-add-limit">已到 10 题上限</div>');

    body.querySelectorAll('.hp-q-answer').forEach(function (textarea) {
      const update = function () {
        const foot = textarea.closest('.hp-qedit')?.querySelector('.hp-char-count');
        if (foot) foot.textContent = textarea.value.length + '/' + textarea.maxLength;
      };
      textarea.addEventListener('input', update);
      update();
    });
    body.querySelector('.hp-add-question')?.addEventListener('click', addQuestion);
    updateCount();
  }

  function capture() {
    if (!state) return;
    const byKey = new Map(state.questions.map(function (q) { return [q.local_key, q]; }));
    body.querySelectorAll('.hp-qedit').forEach(function (row) {
      const q = byKey.get(row.dataset.localKey);
      if (!q) return;
      q.label = row.querySelector('.hp-q-label').value;
      q.answer = row.querySelector('.hp-q-answer').value;
    });
  }

  function addQuestion() {
    if (!state || state.questions.length >= 10) return;
    capture();
    const last = state.questions[state.questions.length - 1];
    const aspect = (last && last.aspect) || state.aspects[0] || 'exercise';
    state.questions.push({
      local_key: 'q' + (state.questions.length + 1),
      aspect: aspect,
      label: '',
      hint: '',
      placeholder: '',
      max_length: 200,
      answer: '',
    });
    renderEditor();
    const rows = body.querySelectorAll('.hp-qedit');
    const lastRow = rows[rows.length - 1];
    lastRow?.scrollIntoView({ block: 'nearest' });
    lastRow?.querySelector('.hp-q-label')?.focus();
  }

  function openCard(card) {
    const data = CARD_BY_KEY.get(card.dataset.skillKey);
    if (!data) return;
    state = {
      skillKey: data.skill_key,
      skillName: data.name,
      setId: data.set ? data.set.set_id : '',
      aspects: data.aspects || [],
      questions: questionFromCard(data),
    };
    title.textContent = (state.setId ? '编辑档案 · ' : '新增档案 · ') + state.skillName;
    sub.textContent = state.setId
      ? '已有 ' + state.questions.length + ' 题；问题文字和回答都可以修改，也可以在末尾继续添加。'
      : '从空白问题开始；写下问题与回答，也可以继续添加更多问题。';
    renderEditor();
    App.openModal('hpModal');
  }

  async function save() {
    if (!state || !saveBtn) return;
    capture();
    if (!state.questions.length) {
      App.toast('至少需要一个问题', true);
      return;
    }
    const blank = state.questions.find(function (q) { return !q.label.trim(); });
    if (blank) {
      App.toast('请先填写问题', true);
      return;
    }
    const payload = {
      skill_key: state.skillKey,
      questions: state.questions.map(function (q) {
        return {
          local_key: q.local_key,
          aspect: q.aspect,
          label: q.label.trim(),
          hint: q.hint || '',
          placeholder: q.placeholder || '',
          max_length: q.max_length,
          answer: q.answer.trim(),
        };
      }),
    };
    saveBtn.disabled = true;
    saveBtn.textContent = '保存中…';
    try {
      const url = state.setId
        ? '/api/profile/health-profile/sets/' + encodeURIComponent(state.setId)
        : '/api/profile/health-profile/sets';
      await App.api(url, { method: state.setId ? 'PUT' : 'POST', body: payload });
      App.closeModal('hpModal');
      App.toast('已保存');
      setTimeout(function () { location.reload(); }, 350);
    } catch (err) {
      App.toast(err.message, true);
    } finally {
      saveBtn.disabled = false;
      saveBtn.textContent = '保存';
    }
  }

  document.getElementById('hpGrid')?.addEventListener('click', function (e) {
    const btn = e.target.closest('[data-action="open"]');
    if (!btn) return;
    const card = btn.closest('.hp-card');
    if (card) openCard(card);
  });

  modal?.querySelectorAll('[data-close="hpModal"]').forEach(function (btn) {
    btn.addEventListener('click', function () { App.closeModal('hpModal'); });
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && modal?.classList.contains('open')) App.closeModal('hpModal');
  });
  saveBtn?.addEventListener('click', save);

  clearBtn?.addEventListener('click', async function () {
    const ok = await App.confirmDialog({
      title: '清空档案',
      message: '会删除全部已存储的专项问题与答案，清空后不可找回。',
      confirmText: '清空',
    });
    if (!ok) return;
    try {
      await App.api('/api/profile/health-profile', { method: 'DELETE' });
      App.toast('档案已清空');
      location.href = '/profile/health-profile';
    } catch (err) {
      App.toast(err.message, true);
    }
  });
})();
