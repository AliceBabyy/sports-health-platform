/* 健康/运动档案：空态即问卷，已填态只读展示；编辑/清空/清空重写与文本域自适应高度 */
(function () {
  const read = document.getElementById('hpRead');
  const readActions = document.getElementById('hpReadActions');
  const form = document.getElementById('hpForm');
  const editNote = document.getElementById('hpEditNote');
  const cancelBtn = document.getElementById('hpCancel');
  if (!read || !form) return;

  const initiallyFilled = !read.hidden;

  /* 文本域高度随内容增长，上限约四成屏高，超出后在框内滚动 */
  function autoGrow(el) {
    el.style.height = 'auto';
    const max = Math.min(Math.round(window.innerHeight * 0.42), 320);
    el.style.height = Math.min(el.scrollHeight, max) + 'px';
    el.style.overflowY = el.scrollHeight > max ? 'auto' : 'hidden';
  }

  function autoGrowAll() {
    form.querySelectorAll('textarea').forEach(autoGrow);
  }

  function enterEdit() {
    read.hidden = true;
    readActions.hidden = true;
    form.hidden = false;
    editNote.hidden = !initiallyFilled;
    autoGrowAll();
    const first = form.querySelector('textarea');
    if (first) first.focus();
  }

  function exitEdit() {
    form.reset();
    autoGrowAll();
    form.hidden = true;
    read.hidden = false;
    readActions.hidden = false;
    editNote.hidden = true;
  }

  document.getElementById('hpEdit')?.addEventListener('click', enterEdit);
  cancelBtn?.addEventListener('click', exitEdit);

  form.querySelectorAll('textarea').forEach(function (el) {
    el.addEventListener('input', function () { autoGrow(el); });
    /* 中文输入法组字结束再重算一次，避免拼音阶段高度跳变 */
    el.addEventListener('compositionend', function () { autoGrow(el); });
  });

  form.addEventListener('submit', async function (e) {
    e.preventDefault();
    const answers = {};
    form.querySelectorAll('textarea[name]').forEach(function (el) { answers[el.name] = el.value; });
    try {
      await App.api('/api/profile/health-profile', { method: 'PUT', body: { answers } });
      App.toast('档案已保存');
      location.href = '/profile/health-profile';
    } catch (err) {
      App.toast(err.message, true);
    }
  });

  document.getElementById('hpResetAll')?.addEventListener('click', async function () {
    const ok = await App.confirmDialog({
      title: '清空重写',
      message: '只清空当前输入，保存后才会覆盖已存档案。',
      confirmText: '清空',
      danger: false,
    });
    if (!ok) return;
    form.querySelectorAll('textarea').forEach(function (el) {
      el.value = '';
      autoGrow(el);
    });
    const first = form.querySelector('textarea');
    if (first) first.focus();
  });

  document.getElementById('hpClear')?.addEventListener('click', async function () {
    const ok = await App.confirmDialog({
      title: '清空档案',
      message: '清空后已填内容不可找回。',
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

  if (!form.hidden) autoGrowAll();
})();
