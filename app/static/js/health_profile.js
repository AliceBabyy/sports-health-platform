/* 健康档案：已存储专项套直接编辑；保存逐题答案，清空删除全部档案 */
(function () {
  const form = document.getElementById('hpForm');
  const clearBtn = document.getElementById('hpClear');

  function autoGrow(el) {
    el.style.height = 'auto';
    const max = Math.min(Math.round(window.innerHeight * 0.42), 320);
    el.style.height = Math.min(el.scrollHeight, max) + 'px';
    el.style.overflowY = el.scrollHeight > max ? 'auto' : 'hidden';
  }

  function autoGrowAll() {
    if (form) form.querySelectorAll('textarea').forEach(autoGrow);
  }

  if (form) {
    form.querySelectorAll('textarea').forEach(function (el) {
      el.addEventListener('input', function () { autoGrow(el); });
      el.addEventListener('compositionend', function () { autoGrow(el); });
    });

    form.addEventListener('submit', async function (e) {
      e.preventDefault();
      const items = [];
      form.querySelectorAll('textarea[data-set-id]').forEach(function (el) {
        items.push({
          set_id: el.dataset.setId,
          local_key: el.dataset.localKey,
          answer: el.value,
        });
      });
      try {
        await App.api('/api/profile/health-profile', { method: 'PUT', body: { items } });
        App.toast('档案已保存');
        location.href = '/profile/health-profile';
      } catch (err) {
        App.toast(err.message, true);
      }
    });
    autoGrowAll();
  }

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

  window.addEventListener('resize', autoGrowAll);
})();
